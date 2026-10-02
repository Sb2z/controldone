"""Lectures communes (web, API, MCP) dans le périmètre d'un client (``TenantScope``).

Règle de publication (§4) : la couche d'accès ne renvoie à un rôle client que les constats ``valide`` ;
ces fonctions ajoutent le filtre de **version** (seuls les constats de la version courante du dossier
sont montrés, une correction produisant une nouvelle version). Les textes lus dans les documents sont des
**données** : ils sont renvoyés tels quels, échappés à l'affichage, jamais interprétés.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from controldone.controls.specs import get_spec
from controldone.formatage import format_montant, format_nombre
from controldone.guardrails import AVERTISSEMENT, PHRASE_RENVOI
from controldone.model.documents import Document as DocumentModele
from controldone.model.dossier import Dossier as DossierModele
from controldone.model.enums import (
    RAISON_LIBELLES,
    Composante,
    NatureMontant,
    Outcome,
    RaisonCode,
    StatutGlobal,
    TypeDocument,
)
from controldone.rapport.vue import (
    LIBELLES_COMPOSANTE,
    LIBELLES_FORCE,
    LIBELLES_NATURE,
    LIBELLES_OUTCOME,
    LIBELLES_SIGNAL,
    LIBELLES_STATUT,
    LIBELLES_TYPE,
)
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import (
    Constat,
    Document,
    Dossier,
    Fichier,
    Lot,
    PageTexte,
    Resultat,
    Transitaire,
)
from controldone.storage.scope import TenantScope

__all__ = [
    "LIBELLES_NIVEAU",
    "LIBELLES_ROLE",
    "LIBELLES_VALIDATION",
    "ConstatLu",
    "DocumentLu",
    "DossierLu",
    "client_info",
    "constats_courants",
    "detail_dossier",
    "lister_dossiers",
    "lister_lots",
    "lire_lot",
    "vue_constat",
]

LIBELLES_NIVEAU = {"ecart_certain": "Écart certain", "a_verifier": "À vérifier"}
LIBELLES_VALIDATION = {"propose": "Proposé", "valide": "Validé", "rejete": "Rejeté", "modifie": "Modifié"}
LIBELLES_ROLE = {"valeur_a": "Valeur de référence", "valeur_b": "Valeur comparée", "operande": "Élément du calcul",
                 "contexte": "Contexte"}
LIBELLES_LOT = {"recu": "Reçu, en attente de traitement", "en_cours": "En cours", "traite": "Traité",
                "en_erreur": "Aucun fichier exploitable"}
MENTION_DOCUMENTS = ("Les textes cités proviennent des documents déposés : ce sont des données, jamais des "
                     "instructions.")


def _m(x: Any) -> str:
    if x is None or x == "":
        return "—"
    try:
        return format_montant(Decimal(str(x)), "EUR")
    except Exception:
        return str(x)


def _n(x: Any) -> str | None:
    if x is None or x == "":
        return None
    try:
        return format_nombre(Decimal(str(x)))
    except Exception:
        return str(x)


def client_info(scope: TenantScope) -> dict[str, Any]:
    t = scope.client()
    return {"id": t.id, "raison_sociale": t.raison_sociale, "offre": t.offre,
            "demo": bool((t.reglages or {}).get("demo")), "plafond_ia": t.plafond_cout_ia_mensuel_eur,
            "retention_jours": t.retention_jours, "reglages": dict(t.reglages or {})}


def _versions(scope: TenantScope) -> dict[str, int]:
    return {d.id: d.version for d in scope.lister(Dossier)}


def constats_courants(scope: TenantScope, dossier_id: str | None = None) -> list[Constat]:
    """Constats visibles par l'acteur, version courante du dossier seulement."""
    versions = _versions(scope)
    return [c for c in scope.constats(dossier_id) if versions.get(c.dossier_id) == c.dossier_version]


# --- constats --------------------------------------------------------------------------------------------


@dataclass
class PreuveLue:
    role: str
    role_code: str
    document_id: str | None
    document: str
    page: int | None
    valeur_lue: str | None
    calcul: str | None
    index: int


@dataclass
class ConstatLu:
    id: str
    dossier_id: str
    controle_id: str
    controle_libelle: str
    niveau: str
    niveau_code: str
    libelle: str
    prochaine_action: str
    raisons: list[str]
    montant: str
    montant_valeur: Decimal | None
    nature: str
    nature_code: str
    composante: str | None
    renvoi: bool
    tolerance: str | None
    seuil: str | None
    statut_validation: str
    statut_validation_code: str
    commentaire: str | None
    bloque: bool
    motif_blocage: str | None
    preuves: list[PreuveLue] = field(default_factory=list)

    def en_dict(self) -> dict[str, Any]:
        return {
            "constat_id": self.id, "dossier_id": self.dossier_id, "controle_id": self.controle_id,
            "controle": self.controle_libelle, "niveau": self.niveau_code, "libelle": self.libelle,
            "prochaine_action": self.prochaine_action, "raisons": self.raisons,
            "montant_en_jeu": str(self.montant_valeur) if self.montant_valeur is not None else None,
            "nature_montant": self.nature_code, "composante": self.composante, "renvoi": self.renvoi,
            "tolerance_appliquee": self.tolerance, "seuil_certitude": self.seuil,
            "statut_validation": self.statut_validation_code,
            "preuves": [{"role": p.role_code, "document_id": p.document_id, "document": p.document, "page": p.page,
                         "valeur_lue": p.valeur_lue, "calcul": p.calcul} for p in self.preuves],
        }


def vue_constat(c: Constat, libelles_docs: dict[str, str] | None = None) -> ConstatLu:
    j = dict(c.contenu or {})
    libelles_docs = libelles_docs or {}
    spec = get_spec(c.controle_id)
    renvoi = bool(j.get("renvoi"))
    codes = []
    for x in j.get("raisons") or []:
        try:
            code = RaisonCode(x)
        except ValueError:
            continue
        if renvoi and code in (RaisonCode.renvoi_reglementaire, RaisonCode.controle_signal_seulement):
            continue
        codes.append(code)
    bloque = j.get("motif_blocage") is not None
    libelle = j.get("libelle") or ""
    action = j.get("prochaine_action") or ""
    if bloque:
        libelle = ("Libellé retenu pour relecture avant publication (formulation à revoir) ; les valeurs "
                   "comparées figurent ci-dessous.")
        action = ""
    if renvoi and PHRASE_RENVOI not in libelle and PHRASE_RENVOI not in action:
        action = (action + " " + PHRASE_RENVOI).strip()
    nature = j.get("nature_montant") or c.nature_montant or "aucun"
    montant = c.montant_en_jeu
    preuves = []
    ordre = ["valeur_a", "valeur_b", "operande", "contexte"]
    brutes = sorted(enumerate(j.get("preuves") or []),
                    key=lambda ip: ordre.index(ip[1].get("role")) if ip[1].get("role") in ordre else 9)
    for i, p in brutes:
        doc_id = p.get("document_id")
        lib = libelles_docs.get(doc_id or "", "Document") if doc_id else ("Calcul" if p.get("calcul") else "—")
        preuves.append(PreuveLue(role=LIBELLES_ROLE.get(p.get("role"), p.get("role") or ""),
                                 role_code=p.get("role") or "", document_id=doc_id, document=lib, page=p.get("page"),
                                 valeur_lue=p.get("valeur_brute"), calcul=p.get("calcul"), index=i))
    try:
        nature_lib = LIBELLES_NATURE[NatureMontant(nature)]
    except ValueError:
        nature_lib = nature
    composante = j.get("composante")
    try:
        composante_lib = LIBELLES_COMPOSANTE.get(Composante(composante)) if composante else None
    except ValueError:
        composante_lib = composante
    return ConstatLu(
        id=c.id, dossier_id=c.dossier_id, controle_id=c.controle_id, controle_libelle=spec.libelle,
        niveau=LIBELLES_NIVEAU.get(c.niveau, c.niveau), niveau_code=c.niveau, libelle=libelle,
        prochaine_action=action, raisons=[RAISON_LIBELLES.get(x, x.value) for x in codes],
        montant=_m(montant) if nature not in ("renvoi", "aucun") else "—",
        montant_valeur=montant if nature not in ("renvoi", "aucun") else None,
        nature=nature_lib, nature_code=nature, composante=composante_lib, renvoi=renvoi,
        tolerance=_n(j.get("tolerance_appliquee")), seuil=_n(j.get("seuil_certitude_applique")),
        statut_validation=LIBELLES_VALIDATION.get(c.statut_validation, c.statut_validation),
        statut_validation_code=c.statut_validation, commentaire=c.commentaire_validation,
        bloque=bloque, motif_blocage=j.get("motif_blocage"), preuves=preuves,
    )


def trier_constats(constats: list[ConstatLu]) -> list[ConstatLu]:
    """Ordre §7.7 : écarts certains à montant décroissant, puis à vérifier, puis renvois."""
    rang = {"ecart_certain": 0, "a_verifier": 1}
    return sorted(constats, key=lambda c: (c.renvoi, rang.get(c.niveau_code, 2), -(c.montant_valeur or 0),
                                           c.controle_id))


# --- dossiers --------------------------------------------------------------------------------------------


@dataclass
class DossierLigne:
    id: str
    reference: str
    statut: str
    statut_code: str
    version: int
    lot_id: str | None
    cree_le: Any
    cles: list[tuple[str, str]]
    nb_constats: int
    nb_proposes: int
    recouvrable_certain: Decimal
    recouvrable_a_verifier: Decimal

    def en_dict(self) -> dict[str, Any]:
        return {"dossier_id": self.id, "reference": self.reference, "statut": self.statut_code,
                "version": self.version, "lot_id": self.lot_id,
                "cree_le": self.cree_le.isoformat() if self.cree_le else None,
                "cles": dict(self.cles), "nb_constats": self.nb_constats,
                "recouvrable_certain_eur": str(self.recouvrable_certain),
                "recouvrable_a_verifier_eur": str(self.recouvrable_a_verifier)}


def _cles(contenu: dict[str, Any]) -> list[tuple[str, str]]:
    c = contenu.get("cles") or {}
    return [("Facture du transitaire", ", ".join(c.get("num_facture_transitaire") or []) or "—"),
            ("Transport", ", ".join(c.get("ref_transport") or []) or "—"),
            ("MRN", ", ".join(c.get("mrn") or []) or "—"),
            ("Facture commerciale", ", ".join(c.get("num_facture_commerciale") or []) or "—")]


def _statut(code: str | None, constats: list[Constat], *, client: bool) -> tuple[str, str]:
    """Statut affiché. Pour un rôle client, ``ecart_certain`` / ``a_verifier`` ne s'affichent que si un
    constat publié le justifie (sinon « en cours de validation »)."""
    if code is None:
        return "En cours", "en_cours"
    if client and code in ("ecart_certain", "a_verifier"):
        niveaux = {c.niveau for c in constats if c.statut_validation == "valide"}
        if "ecart_certain" in niveaux:
            return LIBELLES_STATUT[StatutGlobal.ecart_certain], "ecart_certain"
        if "a_verifier" in niveaux:
            return LIBELLES_STATUT[StatutGlobal.a_verifier], "a_verifier"
        return "En cours de validation", "en_validation"
    try:
        return LIBELLES_STATUT[StatutGlobal(code)], code
    except ValueError:
        return code, code


def lister_dossiers(scope: TenantScope) -> list[DossierLigne]:
    client = scope.actor.est_client
    constats = constats_courants(scope)
    par_dossier: dict[str, list[Constat]] = {}
    for c in constats:
        par_dossier.setdefault(c.dossier_id, []).append(c)
    out = []
    for d in scope.lister(Dossier, ordre=Dossier.reference):
        cs = par_dossier.get(d.id, [])
        statut, code = _statut(d.statut_global, cs, client=client)
        cert = sum((c.montant_en_jeu for c in cs if c.niveau == "ecart_certain" and c.statut_validation == "valide"
                    and c.nature_montant == "recouvrable" and c.montant_en_jeu and c.montant_en_jeu > 0), Decimal(0))
        aver = sum((c.montant_en_jeu for c in cs if c.niveau == "a_verifier" and c.statut_validation != "rejete"
                    and c.nature_montant == "recouvrable" and c.montant_en_jeu and c.montant_en_jeu > 0), Decimal(0))
        out.append(DossierLigne(
            id=d.id, reference=d.reference or d.id, statut=statut, statut_code=code, version=d.version,
            lot_id=d.lot_id, cree_le=d.cree_le, cles=_cles(d.contenu or {}),
            nb_constats=len([c for c in cs if c.statut_validation != "rejete"]),
            nb_proposes=len([c for c in cs if c.statut_validation == "propose"]),
            recouvrable_certain=cert, recouvrable_a_verifier=aver,
        ))
    return out


@dataclass
class ValeurLue:
    id: str
    chemin: str
    libelle: str
    valeur: str | None
    valeur_brute: str | None
    unite: str | None
    page: int | None
    methode: str
    confiance: str
    ancree: bool
    texte_contexte: str | None
    remplace: str | None


@dataclass
class DocumentLu:
    id: str
    type: str
    type_code: str
    libelle: str
    sous_type: str | None
    confiance: str
    lien: str
    signaux: str
    faible: bool
    pages: list[tuple[str, int]]
    fichier_id: str | None
    fichier_nom: str | None
    fichier_mime: str | None
    valeurs: list[ValeurLue]


@dataclass
class DossierLu:
    ligne: DossierLigne
    modele: DossierModele
    documents: list[DocumentLu]
    constats: list[ConstatLu]
    resultats: list[dict[str, Any]]
    corrections: list[Any]
    documents_manquants: list[str]
    transitaire: str | None
    mention_documents: str = MENTION_DOCUMENTS
    avertissement: str = AVERTISSEMENT


def libelle_document(doc: DocumentModele) -> str:
    lib = LIBELLES_TYPE.get(doc.type, doc.type.value)
    num = getattr(doc.champs, "numero", None) if doc.champs is not None else None
    if doc.type is TypeDocument.declaration and doc.champs is not None and doc.dec.mrn is not None:
        num = doc.dec.mrn
    if num is not None and getattr(num, "valeur", None):
        lib += f" n° {num.valeur_brute or num.valeur}"
    return lib


def documents_du_dossier(scope: TenantScope, modele: DossierModele) -> dict[str, DocumentModele]:
    out = {}
    for doc_id in modele.document_ids():
        try:
            out[doc_id] = DocumentModele.model_validate(scope.obtenir(Document, doc_id).contenu)
        except AccesRefuse:
            continue
    return out


def detail_dossier(scope: TenantScope, dossier_id: str) -> DossierLu:
    """Vue complète d'un dossier. Un rôle client ne voit que les constats publiés ; les résultats bruts des
    contrôles et l'historique des corrections ne sont lus que pour le fondateur."""
    row = scope.obtenir(Dossier, dossier_id)
    modele = DossierModele.model_validate(row.contenu)
    docs = documents_du_dossier(scope, modele)
    fichiers = {f.id: f for f in scope.lister(Fichier, lot_id=row.lot_id)} if row.lot_id else {}
    libelles = {i: libelle_document(d) for i, d in docs.items()}
    documents: list[DocumentLu] = []
    for lien in modele.liens:
        d = docs.get(lien.document_id)
        if d is None:
            continue
        fid = d.pages[0].fichier_id if d.pages else None
        f = fichiers.get(fid or "")
        if f is None and fid:
            try:
                f = scope.obtenir(Fichier, fid)
            except AccesRefuse:
                f = None
        valeurs = [ValeurLue(
            id=v.id, chemin=v.chemin, libelle=v.chemin.partition(".")[2] or v.chemin, valeur=v.valeur,
            valeur_brute=v.valeur_brute, unite=v.unite, page=v.page, methode=v.methode.value,
            confiance=f"{round(v.confiance * 100)} %", ancree=v.ancree, texte_contexte=v.texte_contexte,
            remplace=v.remplace) for v in d.valeurs()]
        documents.append(DocumentLu(
            id=d.id, type=LIBELLES_TYPE.get(d.type, d.type.value), type_code=d.type.value, libelle=libelles[d.id],
            sous_type=d.sous_type, confiance=f"{round(d.confiance_classement * 100)} %",
            lien=LIBELLES_FORCE[lien.force], signaux=", ".join(LIBELLES_SIGNAL.get(s, s.value) for s in lien.signaux),
            faible=lien.force.value == "faible", pages=[(p.fichier_id, p.numero) for p in d.pages],
            fichier_id=f.id if f else None, fichier_nom=f.chemin_relatif if f else None,
            fichier_mime=f.type_mime if f else None, valeurs=valeurs))
    constats_rows = constats_courants(scope, dossier_id)
    constats = trier_constats([vue_constat(c, libelles) for c in constats_rows])
    statut, code = _statut(row.statut_global, constats_rows, client=scope.actor.est_client)
    ligne = DossierLigne(
        id=row.id, reference=row.reference or row.id, statut=statut, statut_code=code, version=row.version,
        lot_id=row.lot_id, cree_le=row.cree_le, cles=_cles(row.contenu or {}),
        nb_constats=len(constats), nb_proposes=len([c for c in constats if c.statut_validation_code == "propose"]),
        recouvrable_certain=Decimal(0), recouvrable_a_verifier=Decimal(0))
    resultats: list[dict[str, Any]] = []
    corrections: list[Any] = []
    if not scope.actor.est_client:
        for r in scope.lister(Resultat, dossier_id=dossier_id, ordre=Resultat.controle_id):
            if r.dossier_version != row.version:
                continue
            j = r.contenu or {}
            try:
                res = LIBELLES_OUTCOME[Outcome(r.outcome)]
            except ValueError:
                res = r.outcome
            resultats.append({"controle_id": r.controle_id, "libelle": get_spec(r.controle_id).libelle,
                              "resultat": res, "code": r.outcome, "attendu": j.get("attendu") or "—",
                              "constate": j.get("constate") or "—",
                              "raison": RAISON_LIBELLES.get(RaisonCode(j["raison_code"]), "")
                              if j.get("raison_code") in RaisonCode.__members__ else ""})
        corrections = scope.corrections(dossier_id)
    transitaires = {t.id: t.nom for t in _transitaires(scope)}
    return DossierLu(
        ligne=ligne, modele=modele, documents=documents, constats=constats, resultats=resultats,
        corrections=corrections,
        documents_manquants=[LIBELLES_TYPE.get(TypeDocument(x), x) for x in modele.documents_manquants],
        transitaire=transitaires.get(modele.transitaire_id or "", modele.transitaire_id))


def _transitaires(scope: TenantScope) -> list[Any]:
    return scope.lister(Transitaire)


# --- lots ------------------------------------------------------------------------------------------------


def lister_lots(scope: TenantScope, limite: int = 50) -> list[dict[str, Any]]:
    lots = scope.lister(Lot, ordre=Lot.recu_le.desc(), limite=limite)
    return [{"id": lot.id, "canal": lot.canal, "statut": lot.statut, "statut_libelle": LIBELLES_LOT.get(lot.statut,
             lot.statut), "recu_le": lot.recu_le, "resume": lot.resume or {}} for lot in lots]


def jobs_du_client(db: Any, tenant_id: str) -> list[Any]:
    """Jobs du client (à appeler **hors** d'un périmètre ouvert en écriture : transaction système)."""
    return JobStore(db).lister(tenant_id=tenant_id, limite=2000)


def lire_lot(scope: TenantScope, lot_id: str, *, jobs: list[Any] | None = None) -> dict[str, Any]:
    lot = scope.obtenir(Lot, lot_id)
    fichiers = scope.lister(Fichier, lot_id=lot_id, ordre=Fichier.chemin_relatif)
    job = None
    for j in jobs or []:
        if j.kind == "traiter_lot" and j.payload.get("lot_id") == lot_id and j.tenant_id == scope.tenant_id:
            job = j
    dossiers = [d for d in scope.lister(Dossier, lot_id=lot_id, ordre=Dossier.reference)]
    return {
        "id": lot.id, "canal": lot.canal, "statut": lot.statut, "statut_libelle": LIBELLES_LOT.get(lot.statut, lot.statut),
        "recu_le": lot.recu_le, "resume": lot.resume or {},
        "fichiers": [{"id": f.id, "chemin": f.chemin_relatif, "taille": f.taille, "type": f.type_mime,
                      "statut": f.statut, "motif": f.motif_refus, "doublon": f.doublon_de is not None}
                     for f in fichiers],
        "job": {"id": job.id, "statut": job.statut, "essais": job.attempts} if job else None,
        "dossiers": [{"id": d.id, "reference": d.reference or d.id} for d in dossiers],
    }


def pages_du_fichier(scope: TenantScope, fichier_id: str) -> list[PageTexte]:
    return scope.lister(PageTexte, fichier_id=fichier_id, ordre=PageTexte.numero)
