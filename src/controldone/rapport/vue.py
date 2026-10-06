"""Vue du rapport de diagnostic (SPEC §18) : données prêtes à afficher, communes au HTML, au PDF, au JSON
et au tableur. Aucun calcul de contrôle ici : on additionne des montants **déjà** calculés par les
contrôles, par nature et jamais entre natures (§8.6, §18.3).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from controldone import SCHEMA_VERSION, VERSION_MOTEUR, VERSION_REGLES
from controldone.controls.specs import get_spec
from controldone.findings_io import constats_hors_totaux
from controldone.formatage import format_montant, format_nombre
from controldone.guardrails import AVERTISSEMENT, PHRASE_RENVOI
from controldone.model.documents import Document
from controldone.model.enums import (
    RAISON_LIBELLES,
    Composante,
    ForceLien,
    NatureMontant,
    Niveau,
    Outcome,
    RaisonCode,
    RolePreuve,
    SignalLien,
    StatutGlobal,
    StatutValidation,
    TypeDocument,
)
from controldone.model.resultats import Constat, Preuve
from controldone.pipeline import NonLu, ResultatDossier
from controldone.referentiel_io import ProfilClient

__all__ = [
    "LIBELLES_COMPOSANTE",
    "LIBELLES_NATURE",
    "LIBELLES_STATUT",
    "LIBELLES_TYPE",
    "VERSION_RAPPORT",
    "ConstatVue",
    "DossierVue",
    "PreuveVue",
    "RapportVue",
    "construire_vue",
]

VERSION_RAPPORT = "1.0.0"

LIBELLES_STATUT = {
    StatutGlobal.non_concerne: "Non concerné",
    StatutGlobal.document_manquant: "Document manquant",
    StatutGlobal.ecart_certain: "Écart certain",
    StatutGlobal.a_verifier: "À vérifier",
    StatutGlobal.conforme: "Conforme",
}
LIBELLES_NIVEAU = {Niveau.ecart_certain: "Écart certain", Niveau.a_verifier: "À vérifier"}
LIBELLES_OUTCOME = {
    Outcome.conforme: "Conforme",
    Outcome.ecart_certain: "Écart certain",
    Outcome.a_verifier: "À vérifier",
    Outcome.non_verifiable: "Non vérifiable",
    Outcome.non_applicable: "Non applicable",
}
LIBELLES_TYPE = {
    TypeDocument.facture_commerciale: "Facture commerciale",
    TypeDocument.declaration: "Déclaration en douane",
    TypeDocument.facture_transitaire: "Facture du transitaire",
    TypeDocument.avoir: "Avoir",
    TypeDocument.document_support: "Document support",
    TypeDocument.document_non_exploitable: "Document non exploitable",
    TypeDocument.inconnu: "Document non reconnu",
}
LIBELLES_NATURE = {
    NatureMontant.recouvrable: "Écart refacturé (montant recouvrable)",
    NatureMontant.ecart_documentaire: "Écart de valeur entre documents",
    NatureMontant.arithmetique_declaration: "Écart de calcul sur la déclaration",
    NatureMontant.renvoi: "Point à faire vérifier par un professionnel",
    NatureMontant.aucun: "Écart documentaire sans montant",
}
LIBELLES_COMPOSANTE = {
    Composante.droit: "Droits de douane",
    Composante.autre_taxe: "Autres taxes",
    Composante.tva: "TVA à l'importation",
    Composante.forfait_petits_envois: "Forfait petits envois",
    Composante.prestation: "Prestations du transitaire",
    Composante.valeur: "Valeur",
}
LIBELLES_ROLE_PREUVE = {
    RolePreuve.valeur_a: "Valeur de référence",
    RolePreuve.valeur_b: "Valeur comparée",
    RolePreuve.operande: "Élément du calcul",
    RolePreuve.contexte: "Contexte",
}
LIBELLES_FORCE = {
    ForceLien.forte: "forte",
    ForceLien.moyenne: "moyenne",
    ForceLien.faible: "faible",
    ForceLien.manuelle: "manuelle",
}
LIBELLES_SIGNAL = {
    SignalLien.mrn_cite: "MRN cité",
    SignalLien.ref_facture_citee: "référence de facture citée",
    SignalLien.ref_transport: "référence de transport commune",
    SignalLien.montant_egal: "montants égaux",
    SignalLien.meme_dossier_source: "même dossier de dépôt",
    SignalLien.meme_fichier_source: "même fichier",
    SignalLien.tva: "même numéro de TVA",
    SignalLien.codes_communs: "codes SH6 communs",
    SignalLien.nom_fichier: "nom de fichier",
    SignalLien.graine: "document de référence du dossier",
    SignalLien.reference_proche: "référence retrouvée dans le dossier",
}
LIBELLES_NON_LU = {
    "ingestion_indisponible": "lecture des fichiers indisponible",
    "doublon_de_fichier": "fichier identique déjà reçu",
    "aucun_document_reconnu": "aucun document reconnu dans le fichier",
    "document_non_reconnu": "document non reconnu (classement incertain)",
    "document_non_rattache": "document non rattaché à un dossier",
    "refuse:protege": "fichier protégé par mot de passe",
    "refuse:corrompu": "fichier corrompu ou illisible",
    "refuse:vide": "fichier vide",
    "refuse:non_supporte": "type de fichier non pris en charge",
    "refuse:trop_gros": "fichier trop volumineux",
    "refuse:archive_dangereuse": "archive refusée (structure dangereuse)",
}
LIBELLES_TOLERANCES = [
    ("t_ligne", "T_LIGNE — arithmétique d'une ligne", "EUR"),
    ("t_somme_plafond", "T_SOMME — plafond d'une somme de lignes", "EUR"),
    ("t_taxe_ligne", "T_TAXE_LIGNE — base × taux", "EUR"),
    ("t_valeur_unites", "T_VALEUR — unités de devise", "unités"),
    ("s_valeur_unites", "S_VALEUR — seuil de certitude (unités)", "unités"),
    ("t_conversion_eur", "T_CONVERSION", "EUR"),
    ("s_conversion_eur", "S_CONVERSION — seuil de certitude", "EUR"),
    ("t_debours_minimum", "T_DEBOURS — minimum", "EUR"),
    ("s_debours", "S_DEBOURS — seuil de certitude", "EUR"),
    ("t_tarif", "T_TARIF — prix contre grille", "EUR"),
    ("s_tarif", "S_TARIF — seuil de certitude", "EUR"),
    ("s_arith", "S_ARITH — arithmétique interne", "EUR"),
    ("s_calcul_declaration", "Seuil des écarts de calcul de la déclaration", "EUR"),
    ("t_masse_kg", "T_MASSE — minimum", "kg"),
    ("c_min_certain", "C_MIN_CERTAIN — confiance minimale pour un écart certain", ""),
    ("c_min_utile", "C_MIN_UTILE — confiance minimale pour exécuter un contrôle", ""),
]
LIMITES_METHODE = [
    "Les constats sont proposés par des contrôles déterministes et testés ; ils sont validés par le "
    "fondateur avant toute utilisation.",
    "Un écart n'est « certain » que si chaque valeur comparée a été lue avec une confiance suffisante, sur "
    "un document identifié et rattaché, avec la page citée. Dans le doute, il est « à vérifier ».",
    "Les conversions utilisent uniquement le taux imprimé sur la déclaration ; un taux indicatif ne sert "
    "jamais à calculer un montant.",
    "Les points réglementaires (classement, origine, valeur en douane, régimes) ne sont jamais chiffrés : "
    "ils sont renvoyés vers un professionnel.",
    "Les montants de natures différentes ne sont jamais additionnés entre eux.",
]
ROUGE, AMBRE = "certain", "verifier"


def _m(x: Decimal | None, devise: str | None = "EUR") -> str:
    return "—" if x is None else format_montant(x, devise)


# --- vues ----------------------------------------------------------------------------------------------


@dataclass
class PreuveVue:
    role: str
    document: str  # libellé du document
    fichier: str | None
    page: int | None
    valeur_lue: str | None
    calcul: str | None = None
    image: bytes | None = None  # PNG du rognage de la zone (si disponible)
    # pour le rognage (non affiché)
    chemin_local: str | None = None
    type_mime: str | None = None
    zone: tuple[float, float, float, float] | None = None


@dataclass
class ConstatVue:
    id: str
    controle_id: str
    controle_libelle: str
    niveau: str  # libellé
    niveau_code: str
    libelle: str
    prochaine_action: str
    raisons: list[str]
    montant: str
    montant_valeur: Decimal | None
    nature: str
    nature_code: str
    composante: str | None
    tolerance: str | None
    seuil: str | None
    renvoi: bool
    preuves: list[PreuveVue]
    dossier_reference: str
    bloque: bool = False
    statut_validation: str = "propose"
    #: Motif d'exclusion des totaux (``remplace_par_e6``, ``doublon_documentaire``), D-1202 ; sinon ``None``.
    hors_totaux: str | None = None


@dataclass
class DocumentVue:
    id: str
    type: str
    fichier: str
    pages: str
    confiance: str
    lien: str
    signaux: str
    faible: bool = False


@dataclass
class ResultatVue:
    controle_id: str
    libelle: str
    resultat: str
    resultat_code: str
    attendu: str
    constate: str
    raison: str


@dataclass
class LigneCoteACote:
    sh6: str
    facture: str
    declaration: str


@dataclass
class DossierVue:
    reference: str
    statut: str
    statut_code: str
    cles: list[tuple[str, str]]
    tva_acheteur: str
    tva_importateur: str
    montant_facture: str
    montant_declare: str
    raisons: str
    recouvrable_certain: Decimal
    recouvrable_a_verifier: Decimal
    transitaire: str | None
    documents: list[DocumentVue]
    constats: list[ConstatVue]
    resultats: list[ResultatVue]
    cote_a_cote: list[LigneCoteACote]
    documents_manquants: list[str]
    mois: str | None = None


@dataclass
class LigneNature:
    libelle: str
    nombre: int
    montant: str
    note: str


@dataclass
class Action:
    priorite: str
    titre: str
    details: list[str]


@dataclass
class RapportVue:
    titre: str
    client: str
    offre: str
    periode: str
    date: str
    demo: bool
    nb_dossiers: int
    versions: dict[str, str]
    execution_ids: list[str]
    empreinte: str
    statuts: list[tuple[str, str, int]]
    recouvrable_certain: str
    recouvrable_a_verifier: str
    ecarts_documentaires: str
    ecarts_documentaires_nb: int
    ecarts_calcul: str
    ecarts_calcul_nb: int
    nb_renvois: int
    par_composante: list[tuple[str, str, str]]
    par_transitaire: list[tuple[str, str, str]]
    par_mois: list[tuple[str, str, str]]
    table_nature: list[LigneNature]
    actions: list[Action]
    dossiers: list[DossierVue]
    renvois: list[ConstatVue]
    non_lus: list[tuple[str, str, str]]
    tolerances: list[tuple[str, str]]
    extracteurs: list[tuple[str, str]]
    modele_llm: str
    limites: list[str]
    avertissement: str = AVERTISSEMENT
    phrase_renvoi: str = PHRASE_RENVOI
    mention_validation: str = ""
    constats_bloques: int = 0

    def constats(self) -> list[ConstatVue]:
        return [c for d in self.dossiers for c in d.constats]


# --- construction -----------------------------------------------------------------------------------------


def _doc_libelle(doc: Document | None, rd: ResultatDossier) -> tuple[str, str | None]:
    if doc is None:
        return "document", None
    fic = rd.fichiers.get(doc.pages[0].fichier_id) if doc.pages else None
    num = getattr(doc.champs, "numero", None) if doc.champs is not None else None
    if doc.type is TypeDocument.declaration and doc.champs is not None and doc.dec.mrn is not None:
        num = doc.dec.mrn
    lib = LIBELLES_TYPE.get(doc.type, doc.type.value)
    if num is not None and num.valeur:
        lib += f" n° {num.valeur_brute or num.valeur}"
    return lib, fic.chemin_relatif if fic else None


def _preuve_vue(p: Preuve, rd: ResultatDossier) -> PreuveVue:
    doc = rd.documents.get(p.document_id or "")
    lib, fichier = _doc_libelle(doc, rd)
    chemin = mime = None
    zone = None
    if doc is not None and doc.pages:
        fid = doc.pages[0].fichier_id
        if p.page is not None:
            for pr in doc.pages:
                if pr.numero == p.page:
                    fid = pr.fichier_id
        chemin = rd.chemins.get(fid)
        fic = rd.fichiers.get(fid)
        mime = fic.type_mime if fic else None
        if p.valeur_sourcee_id:
            for v in doc.valeurs():
                if v.id == p.valeur_sourcee_id and v.zone is not None:
                    zone = (v.zone.x0, v.zone.y0, v.zone.x1, v.zone.y1)
    if p.document_id is None and p.calcul:
        lib, fichier = "Calcul", None
    return PreuveVue(
        role=LIBELLES_ROLE_PREUVE.get(p.role, p.role.value), document=lib, fichier=fichier, page=p.page,
        valeur_lue=p.valeur_brute, calcul=p.calcul, chemin_local=chemin, type_mime=mime, zone=zone,
    )


#: Mention publiée à la place du libellé d'un constat bloqué (§3.2) : HTML, PDF, JSON (D-1205).
LIBELLE_RETENU = (
    "Libellé retenu pour relecture avant publication (formulation à revoir) ; les valeurs comparées "
    "figurent ci-dessous."
)


def _constat_vue(c: Constat, r, rd: ResultatDossier) -> ConstatVue:
    spec = get_spec(c.controle_id)
    codes = [x for x in c.raisons if not (c.renvoi and x in (RaisonCode.renvoi_reglementaire,
                                                              RaisonCode.controle_signal_seulement))]
    if len(codes) > 1:
        codes = [x for x in codes if x is not RaisonCode.controle_signal_seulement]
    raisons = [RAISON_LIBELLES.get(x, x.value) for x in codes]
    bloque = c.motif_blocage is not None
    libelle = c.libelle if not bloque else LIBELLE_RETENU
    action = c.prochaine_action if not bloque else ""
    if c.renvoi and PHRASE_RENVOI not in libelle and PHRASE_RENVOI not in action:
        action = (action + " " + PHRASE_RENVOI).strip()
    return ConstatVue(
        id=c.id, controle_id=c.controle_id, controle_libelle=spec.libelle,
        niveau=LIBELLES_NIVEAU[c.niveau], niveau_code=c.niveau.value, libelle=libelle, prochaine_action=action,
        raisons=raisons,
        montant=_m(c.montant_en_jeu) if c.nature_montant not in (NatureMontant.renvoi, NatureMontant.aucun) else "—",
        montant_valeur=c.montant_en_jeu,
        nature=LIBELLES_NATURE[c.nature_montant], nature_code=c.nature_montant.value,
        composante=LIBELLES_COMPOSANTE.get(c.composante) if c.composante else None,
        tolerance=format_nombre(r.tolerance_appliquee) if r.tolerance_appliquee is not None else None,
        seuil=format_nombre(r.seuil_certitude_applique) if r.seuil_certitude_applique is not None else None,
        renvoi=c.renvoi,
        preuves=[_preuve_vue(p, rd) for p in sorted(c.preuves, key=lambda p: _ORDRE_ROLES.index(p.role))],
        dossier_reference=rd.dossier.reference or rd.dossier.id, bloque=bloque,
        statut_validation=c.statut_validation.value,
    )


def _nombre_fr(x: str | None) -> str:
    """Valeur attendue / constatée affichée en français si c'est un nombre."""
    if x is None or x == "":
        return "—"
    if "." not in x:  # entiers, codes, devises : tels quels
        return x
    try:
        d = Decimal(x)
    except Exception:
        return x
    return format_nombre(d) if d.is_finite() else x


_ORDRE_ROLES = [RolePreuve.valeur_a, RolePreuve.valeur_b, RolePreuve.operande, RolePreuve.contexte]


def _valeur(v) -> str | None:
    return None if v is None or not v.est_lisible else (v.valeur_brute or v.valeur)


def _montant_doc(v_montant, v_devise) -> str:
    if v_montant is None or not v_montant.est_lisible:
        return "—"
    try:
        return format_montant(v_montant.decimal(), v_devise.valeur if v_devise and v_devise.valeur else None)
    except Exception:
        return v_montant.valeur or "—"


def _sh6(code: str | None) -> str | None:
    import re

    c = re.sub(r"\D", "", code or "")
    return c[:6] if len(c) >= 6 else None


def _cote_a_cote(fcs: list[Document], decs: list[Document]) -> list[LigneCoteACote]:
    gauche: dict[str, list[str]] = defaultdict(list)
    droite: dict[str, list[str]] = defaultdict(list)
    for d in fcs:
        for li in d.fc.lignes:
            k = _sh6(_valeur(li.code_marchandise_imprime)) or "—"
            morceaux = [x for x in (_valeur(li.description), _valeur(li.quantite) and f"qté {_valeur(li.quantite)}",
                                    _valeur(li.montant_ligne), _valeur(li.pays_origine)) if x]
            gauche[k].append(" · ".join(morceaux) or "ligne")
    for d in decs:
        for a in d.dec.articles:
            k = a.code_sh6 or "—"
            morceaux = [x for x in (f"article {_valeur(a.numero_article)}" if _valeur(a.numero_article) else None,
                                    _valeur(a.code_marchandise), _valeur(a.montant_facture_article),
                                    _valeur(a.pays_origine)) if x]
            droite[k].append(" · ".join(morceaux) or "article")
    out = []
    for k in sorted(set(gauche) | set(droite), key=lambda x: (x == "—", x)):
        n = max(len(gauche[k]), len(droite[k]))
        for i in range(n):
            out.append(LigneCoteACote(k, gauche[k][i] if i < len(gauche[k]) else "—",
                                      droite[k][i] if i < len(droite[k]) else "—"))
    return out[:60]


_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
         "novembre", "décembre"]


def _mois_libelle(iso: str) -> str:
    a, m = iso.split("-")[:2]
    return f"{_MOIS[int(m) - 1]} {a}"


def _dossier_vue(rd: ResultatDossier, transitaires: dict[str, str]) -> DossierVue:
    d = rd.dossier
    docs_liens = [(rd.documents.get(lien.document_id), lien) for lien in d.liens]
    fcs = [x for x, _l in docs_liens if x is not None and x.type is TypeDocument.facture_commerciale and x.champs]
    decs = [x for x, _l in docs_liens if x is not None and x.type is TypeDocument.declaration and x.champs]
    fts = [x for x, _l in docs_liens if x is not None and x.type is TypeDocument.facture_transitaire and x.champs]
    cles = [
        ("Facture du transitaire", ", ".join(d.cles.num_facture_transitaire) or "—"),
        ("Transport", ", ".join(d.cles.ref_transport) or "—"),
        ("MRN", ", ".join(d.cles.mrn) or "—"),
        ("Facture commerciale", ", ".join(d.cles.num_facture_commerciale) or "—"),
    ]
    documents = []
    for doc, lien in docs_liens:
        if doc is None:
            continue
        _lib, fichier = _doc_libelle(doc, rd)
        documents.append(DocumentVue(
            id=doc.id, type=LIBELLES_TYPE.get(doc.type, doc.type.value), fichier=fichier or "—",
            pages=", ".join(str(p.numero) for p in doc.pages) or "—",
            confiance=f"{round(doc.confiance_classement * 100)} %",
            lien=LIBELLES_FORCE[lien.force], signaux=", ".join(LIBELLES_SIGNAL.get(s, s.value) for s in lien.signaux),
            faible=lien.force is ForceLien.faible,
        ))
    constats, resultats = [], []
    exclus = constats_hors_totaux(rd.resultats)
    for r in rd.resultats:
        spec = get_spec(r.controle_id)
        if r.constat is not None:
            cv = _constat_vue(r.constat, r, rd)
            cv.hors_totaux = exclus.get(r.constat.id)
            constats.append(cv)
        resultats.append(ResultatVue(
            controle_id=r.controle_id + (f" ({r.sous_controle})" if r.sous_controle else ""),
            libelle=spec.libelle, resultat=LIBELLES_OUTCOME[r.outcome], resultat_code=r.outcome.value,
            attendu=_nombre_fr(r.attendu), constate=_nombre_fr(r.constate),
            raison=RAISON_LIBELLES.get(r.raison_code, "") if r.raison_code else "",
        ))
    ordre_niveau = {"ecart_certain": 0, "a_verifier": 1}
    constats.sort(key=lambda c: (c.renvoi, ordre_niveau.get(c.niveau_code, 2), -(c.montant_valeur or 0), c.controle_id))
    cert = sum((c.montant_valeur for c in constats if c.niveau_code == "ecart_certain" and not c.hors_totaux
                and c.nature_code == "recouvrable" and c.montant_valeur and c.montant_valeur > 0), Decimal(0))
    aver = sum((c.montant_valeur for c in constats if c.niveau_code == "a_verifier" and not c.hors_totaux
                and c.nature_code == "recouvrable" and c.montant_valeur and c.montant_valeur > 0), Decimal(0))
    raisons = Counter(r for c in constats for r in c.raisons)
    fc0 = fcs[0] if fcs else None
    dec0 = decs[0] if decs else None
    mois = None
    for x in [*fts, *fcs]:
        v = x.ft.date if x.type is TypeDocument.facture_transitaire else x.fc.date
        if v is not None and v.valeur and len(v.valeur) >= 7:
            mois = v.valeur[:7]
            break
    return DossierVue(
        reference=d.reference or d.id, statut=LIBELLES_STATUT[rd.statut_global], statut_code=rd.statut_global.value,
        cles=cles,
        tva_acheteur=(_valeur(fc0.fc.acheteur.tva) if fc0 else None) or "—",
        tva_importateur=(_valeur(dec0.dec.importateur.tva) if dec0 else None) or "—",
        montant_facture=_montant_doc(fc0.fc.total_facture, fc0.fc.devise) if fc0 else "—",
        montant_declare=_montant_doc(dec0.dec.montant_total_facture, dec0.dec.devise_facture) if dec0 else "—",
        raisons="; ".join(r for r, _n in raisons.most_common(3)) or "—",
        recouvrable_certain=cert, recouvrable_a_verifier=aver,
        transitaire=transitaires.get(d.transitaire_id or "", d.transitaire_id),
        documents=documents, constats=constats, resultats=resultats, cote_a_cote=_cote_a_cote(fcs, decs),
        documents_manquants=[LIBELLES_TYPE[TypeDocument(x)] for x in d.documents_manquants],
        mois=mois,
    )


def _periode(resultats: Sequence[ResultatDossier], profil: ProfilClient) -> str:
    if profil.periode:
        return profil.periode
    dates = []
    for rd in resultats:
        for doc in rd.documents.values():
            if doc.champs is None:
                continue
            v = None
            if doc.type is TypeDocument.facture_commerciale:
                v = doc.fc.date
            elif doc.type is TypeDocument.declaration:
                v = doc.dec.date_acceptation
            if v is not None and v.valeur and len(v.valeur) == 10:
                dates.append(v.valeur)
    if not dates:
        return "non déterminée"
    a, b = _mois_libelle(min(dates)), _mois_libelle(max(dates))
    return a if a == b else f"{a} – {b}"


def construire_vue(
    resultats: Sequence[ResultatDossier],
    profil: ProfilClient,
    *,
    titre: str = "Rapport de diagnostic",
    date_rapport: date | None = None,
    non_lus: Sequence[NonLu] | None = None,
) -> RapportVue:
    """Construit la vue du rapport à partir des résultats du pipeline."""
    transitaires = {t.id: t.nom for t in profil.transitaires}
    dossiers = [_dossier_vue(rd, transitaires) for rd in resultats]
    constats = [c for d in dossiers for c in d.constats]
    statuts = Counter(rd.statut_global for rd in resultats)

    def somme(filtre) -> Decimal:
        return sum((c.montant_valeur for c in constats if filtre(c) and c.montant_valeur is not None), Decimal(0))

    def rec_cert(c):
        return (c.nature_code == "recouvrable" and c.niveau_code == "ecart_certain" and not c.hors_totaux
                and (c.montant_valeur or 0) > 0)

    def rec_aver(c):
        return (c.nature_code == "recouvrable" and c.niveau_code == "a_verifier" and not c.hors_totaux
                and (c.montant_valeur or 0) > 0)

    doc_c = [c for c in constats if c.nature_code == "ecart_documentaire" and not c.hors_totaux]
    calc_c = [c for c in constats if c.nature_code == "arithmetique_declaration"]
    renvois = [c for c in constats if c.renvoi or c.nature_code == "renvoi"]
    abs_doc = sum((abs(c.montant_valeur) for c in doc_c if c.montant_valeur is not None), Decimal(0))
    abs_calc = sum((abs(c.montant_valeur) for c in calc_c if c.montant_valeur is not None), Decimal(0))

    def repartition(cle) -> list[tuple[str, str, str]]:
        cert: dict[str, Decimal] = defaultdict(Decimal)
        aver: dict[str, Decimal] = defaultdict(Decimal)
        for d in dossiers:
            for c in d.constats:
                k = cle(d, c)
                if k is None:
                    continue
                if rec_cert(c):
                    cert[k] += c.montant_valeur or 0
                elif rec_aver(c):
                    aver[k] += c.montant_valeur or 0
        return [(k, _m(cert.get(k, Decimal(0))), _m(aver.get(k, Decimal(0)))) for k in sorted(set(cert) | set(aver))]

    autres_nature = [c for c in constats if c.nature_code == "aucun"]
    table = [
        LigneNature("Écarts refacturés — certains", len([c for c in constats if rec_cert(c)]), _m(somme(rec_cert)),
                    "montant recouvrable certain"),
        LigneNature("Écarts refacturés — à vérifier", len([c for c in constats if rec_aver(c)]), _m(somme(rec_aver)),
                    "affiché à part, jamais additionné au précédent"),
        LigneNature("Écarts de valeur entre documents", len(doc_c), _m(abs_doc),
                    "valeur absolue ; ne constitue pas un montant de droits"),
        LigneNature("Écarts de calcul sur la déclaration", len(calc_c), _m(abs_calc),
                    "valeur absolue ; à faire expliquer par le déclarant"),
        LigneNature("Points à faire vérifier par un professionnel", len(renvois), "—", "sans montant"),
        LigneNature("Autres écarts documentaires (sans montant)", len(autres_nature), "—", ""),
    ]
    # prochaines actions (§18.3 point 3)
    actions = []
    par_tr: dict[str, list[ConstatVue]] = defaultdict(list)
    for d in dossiers:
        for c in d.constats:
            if rec_cert(c):
                par_tr[d.transitaire or "transitaire non identifié"].append(c)
    if par_tr:
        actions.append(Action("P1", "Préparer les demandes d'avoir prêtes, à envoyer par vos soins après validation",
                              [f"{t} : {_m(sum((c.montant_valeur or 0 for c in cs), Decimal(0)))} "
                               f"({len(cs)} écart{'s' if len(cs) > 1 else ''} certain{'s' if len(cs) > 1 else ''})"
                               for t, cs in sorted(par_tr.items())]))
    a_verifier = [c for c in constats if c.niveau_code == "a_verifier" and not c.renvoi]
    if a_verifier:
        actions.append(Action("P2", "Lever les points à vérifier",
                              [f"{c.dossier_reference} — {c.controle_id} {c.controle_libelle}" for c in a_verifier[:25]]
                              + ([f"… et {len(a_verifier) - 25} autres"] if len(a_verifier) > 25 else [])))
    if renvois:
        actions.append(Action("P3", "Transmettre les points réglementaires à un représentant en douane enregistré "
                                    "ou à un avocat",
                              [f"{c.dossier_reference} — {c.controle_id} {c.controle_libelle}" for c in renvois]))
    manquants = [f"{d.reference} : {', '.join(d.documents_manquants)}" for d in dossiers if d.documents_manquants]
    nl = list(non_lus) if non_lus is not None else _non_lus(resultats)
    if manquants or nl:
        actions.append(Action("P4", "Compléter les documents manquants ou illisibles",
                              manquants + [f"{n.fichier} : {LIBELLES_NON_LU.get(n.motif, n.motif)}" for n in nl[:15]]))
    executions = sorted({rd.execution.id for rd in resultats})
    ex0 = resultats[0].execution if resultats else None
    contenu = profil.tolerances.contenu()
    tolerances = []
    for k, lib, unite in LIBELLES_TOLERANCES:
        v = contenu.get(k)
        if v is None:
            continue
        tolerances.append((lib, f"{format_nombre(Decimal(str(v)))} {unite}".strip()))
    validation = all(c.statut_validation in (StatutValidation.valide.value, StatutValidation.modifie.value)
                     for c in constats)
    return RapportVue(
        titre=titre, client=profil.client.raison_sociale,
        offre={"diagnostic": "Diagnostic", "continu": "Contrôle continu"}.get(profil.client.offre.value,
                                                                            profil.client.offre.value),
        periode=_periode(resultats, profil), date=_date_fr(date_rapport or date.today()), demo=profil.demo,
        nb_dossiers=len(dossiers),
        versions={"moteur": VERSION_MOTEUR, "règles": VERSION_REGLES, "schéma": SCHEMA_VERSION,
                  "rapport": VERSION_RAPPORT},
        execution_ids=executions, empreinte=profil.tolerances.empreinte(),
        statuts=[(LIBELLES_STATUT[s], s.value, statuts.get(s, 0)) for s in StatutGlobal],
        recouvrable_certain=_m(somme(rec_cert)), recouvrable_a_verifier=_m(somme(rec_aver)),
        ecarts_documentaires=_m(abs_doc), ecarts_documentaires_nb=len(doc_c),
        ecarts_calcul=_m(abs_calc), ecarts_calcul_nb=len(calc_c), nb_renvois=len(renvois),
        par_composante=repartition(lambda d, c: c.composante if c.nature_code == "recouvrable" else None),
        par_transitaire=repartition(lambda d, c: d.transitaire or "non identifié"),
        par_mois=repartition(lambda d, c: _mois_libelle(d.mois) if d.mois else "non daté"),
        table_nature=table, actions=actions, dossiers=dossiers, renvois=renvois,
        non_lus=[(n.fichier, LIBELLES_NON_LU.get(n.motif, n.motif.replace("_", " ")),
                  ", ".join(str(p) for p in n.pages) or "—") for n in nl],
        tolerances=tolerances,
        extracteurs=sorted((ex0.versions_extracteurs if ex0 else {}).items()),
        modele_llm=(ex0.modele_llm if ex0 and ex0.modele_llm else "aucun (extraction sans modèle de langage)"),
        limites=LIMITES_METHODE,
        mention_validation="" if (validation and constats) else
        "Constats proposés par le système, avant validation par le fondateur.",
        constats_bloques=sum(1 for c in constats if c.bloque),
    )


def _non_lus(resultats: Sequence[ResultatDossier]) -> list[NonLu]:
    vus, out = set(), []
    for rd in resultats:
        for n in rd.non_lus:
            k = (n.fichier, n.motif, n.document_id)
            if k not in vus:
                vus.add(k)
                out.append(n)
    return out


def _date_fr(d: date) -> str:
    return f"{d.day} {_MOIS[d.month - 1]} {d.year}"


__all__ += ["Action", "DocumentVue", "LigneNature", "ResultatVue"]
