"""Famille P — Préalables (SPEC §9).

Ces contrôles conditionnent les autres. Ils ne produisent que des constats ``a_verifier`` (jamais
``ecart_certain``) et n'ont jamais de montant (§8.6 : nature ``aucun``).

- P1 Complétude du dossier (unité : dossier) ;
- P2 Document non exploitable (unité : document) ;
- P3 Champ clé illisible (unité : document × champ clé) : **pas de constat**, un résultat
  ``non_verifiable`` par champ clé absent ou de confiance < ``C_MIN_UTILE`` (section « non vérifiable » du
  rapport). Le mécanisme lui-même est porté par ``ControlContext.utilisable`` / ``raison_inutilisable``,
  appliqué par chaque contrôle dépendant ;
- P4 Rattachement faible (unité : lien) ;
- P5 Dossier non concerné (unité : dossier) : statut, pas de constat (D-020).

Le module expose aussi l'identification des entités du client (``identifier_partie``,
``identifier_facture``, ``entites_client_declaration``), partagée avec A1.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from controldone.controls.framework import Classement, ControlContext, cle_unite, control
from controldone.model import (
    CHAMPS_CLES,
    Document,
    Entite,
    ForceLien,
    LienDocument,
    MotifNonExploitable,
    Niveau,
    Partie,
    Preuve,
    RaisonCode,
    ResultatControle,
    RoleLien,
    RolePreuve,
    TypeDocument,
    TypeValeur,
    ValeurSourcee,
)
from controldone.normalize.fiscal import normalize_vat, siren_depuis_tva
from controldone.normalize.text import cle_texte

__all__ = [
    "ACTION_P1",
    "ACTION_P2",
    "ACTION_P4",
    "LIBELLES_MOTIF",
    "Identification",
    "champs_cles_illisibles",
    "entites_client_declaration",
    "identifier_facture",
    "identifier_partie",
    "p1_completude",
    "p2_document_non_exploitable",
    "p3_champ_cle_illisible",
    "p4_rattachement_faible",
    "p5_dossier_non_concerne",
]

#: Confiance minimale de la lecture du pavé acheteur pour conclure « non concerné » (§9, P5).
CONFIANCE_P5 = 0.90

ACTION_P1 = "Compléter le dossier avec le ou les documents manquants, puis relancer le contrôle."
ACTION_P2 = (
    "Vérifier ce document ; si une facture commerciale exploitable existe pour cet envoi, l'ajouter au dossier."
)
ACTION_P4 = (
    "Confirmer que ce document appartient bien à ce dossier (rattachement manuel) ; en attendant, les constats "
    "qui en dépendent restent à vérifier."
)

LIBELLES_MOTIF: dict[MotifNonExploitable, str] = {
    MotifNonExploitable.pre_alerte: "pré-alerte",
    MotifNonExploitable.liste_reparation: "liste de réparation",
    MotifNonExploitable.liste_expedition: "liste d'expédition",
    MotifNonExploitable.bon_livraison_sans_valeur: "bon de livraison sans valeur",
    MotifNonExploitable.document_export: "document d'export",
    MotifNonExploitable.perfectionnement_passif: "document de perfectionnement passif",
    MotifNonExploitable.devis: "devis",
    MotifNonExploitable.bon_commande: "bon de commande",
    MotifNonExploitable.recu: "reçu",
    MotifNonExploitable.hors_sujet: "document hors sujet",
    MotifNonExploitable.illisible: "document illisible",
    MotifNonExploitable.protege: "document protégé",
    MotifNonExploitable.corrompu: "fichier corrompu",
}
_LIBELLES_TYPE = {
    TypeDocument.facture_commerciale: "facture commerciale",
    TypeDocument.declaration: "déclaration en douane",
}
_ROLE_TYPE = {RoleLien.facture_commerciale: TypeDocument.facture_commerciale,
              RoleLien.declaration: TypeDocument.declaration}
_SIGNAUX = {
    "mrn_cite": "MRN cité",
    "ref_facture_citee": "référence de facture citée",
    "ref_transport": "référence de transport",
    "montant_egal": "montant égal",
    "meme_dossier_source": "même dossier source",
    "meme_fichier_source": "même fichier source",
    "tva": "numéro de TVA",
    "codes_communs": "codes marchandise communs",
    "nom_fichier": "nom de fichier",
    "graine": "document graine",
    "reference_proche": "référence retrouvée dans le dossier",
}


# --- Outils communs ---------------------------------------------------------------------------------


def _pages(doc: Document) -> str:
    nums = sorted({p.numero for p in doc.pages})
    if not nums:
        return ""
    if len(nums) == 1:
        return f"page {nums[0]}"
    return f"pages {nums[0]} à {nums[-1]}"


def _type_doc(doc: Document) -> str:
    return {
        TypeDocument.facture_commerciale: "facture commerciale",
        TypeDocument.declaration: "déclaration",
        TypeDocument.facture_transitaire: "facture du transitaire",
        TypeDocument.avoir: "avoir",
        TypeDocument.document_support: "document support",
    }.get(doc.type, "document")


def _est_non_exploitable(doc: Document) -> bool:
    return doc.motif_non_exploitable is not None or doc.type is TypeDocument.document_non_exploitable


def _documents_lies(ctx: ControlContext) -> list[tuple[Document, RoleLien]]:
    """Documents liés au dossier (ordre des liens), doublons exclus."""
    out = []
    for lien in ctx.dossier.liens:
        doc = ctx.document(lien.document_id)
        if doc is None or doc.doublon_de:
            continue
        out.append((doc, lien.role))
    return out


def _classement_p(*raisons: RaisonCode) -> Classement:
    """Constat P : toujours ``a_verifier`` (Annexe A, « Certain ? » = non)."""
    return Classement(Niveau.a_verifier, tuple(dict.fromkeys(raisons)))


def _preuve_document(doc: Document, valeur_brute: str | None = None) -> Preuve:
    page = min((p.numero for p in doc.pages), default=None)
    return Preuve(role=RolePreuve.contexte, document_id=doc.id, page=page, valeur_brute=valeur_brute)


# --- Identification des entités du client (P5, A1) ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Identification:
    """Entité du client identifiée sur un pavé (acheteur, importateur…).

    - ``entite`` : entité du client identifiée, ou ``None`` ;
    - ``methode`` : ``tva`` (TVA normalisée exacte), ``siren`` (SIREN imprimé ou tiré d'une TVA à clé abîmée),
      ``alias`` (alias unique le plus spécifique) ;
    - ``valeur`` : valeur sourcée qui a permis l'identification ;
    - ``tva_hors_client`` : TVA lisible du pavé qui n'est celle d'aucune entité du client.
    """

    entite: Entite | None = None
    methode: str | None = None
    valeur: ValeurSourcee | None = None
    tva_hors_client: ValeurSourcee | None = None

    @property
    def par_tva(self) -> bool:
        return self.entite is not None and self.methode == "tva"


def _siren_entite(e: Entite) -> str | None:
    return e.siren or siren_depuis_tva(e.tva)


def _par_alias(ctx: ControlContext, nom: str) -> Entite | None:
    """Alias unique le plus spécifique : l'alias (ou la raison sociale) le plus long contenu dans le nom
    lu ; ``None`` si deux entités différentes partagent ce meilleur alias."""
    cle = f" {cle_texte(nom)} "
    meilleurs: dict[str, int] = {}
    for e in ctx.entites:
        for a in [e.raison_sociale, *e.alias]:
            ca = cle_texte(a or "")
            if len(ca) >= 3 and f" {ca} " in cle:
                meilleurs[e.id] = max(meilleurs.get(e.id, 0), len(ca))
    if not meilleurs:
        return None
    top = max(meilleurs.values())
    gagnants = [i for i, n in meilleurs.items() if n == top]
    if len(gagnants) != 1:
        return None
    return next(e for e in ctx.entites if e.id == gagnants[0])


def identifier_partie(ctx: ControlContext, partie: Partie) -> Identification:
    """A1 : TVA normalisée exacte, sinon SIREN imprimé (9 chiffres, même si la clé TVA est abîmée), sinon
    alias unique le plus spécifique. Seules les valeurs utilisables (``C_MIN_UTILE``) sont lues."""
    hors_client = None
    if ctx.utilisable(partie.tva):
        assert partie.tva is not None
        e = ctx.entite_par_tva(partie.tva.valeur)
        if e is not None:
            return Identification(e, "tva", partie.tva)
        if normalize_vat(partie.tva.valeur):
            hors_client = partie.tva
    # SIREN : imprimé, ou tiré d'une TVA française dont la clé est abîmée.
    candidats: list[tuple[str | None, ValeurSourcee]] = []
    if ctx.utilisable(partie.siren):
        assert partie.siren is not None
        candidats.append(("".join(c for c in partie.siren.valeur or "" if c.isdigit()), partie.siren))
    if ctx.utilisable(partie.tva):
        assert partie.tva is not None
        candidats.append((siren_depuis_tva(partie.tva.valeur), partie.tva))
    for siren, v in candidats:
        if siren and len(siren) == 9:
            trouvees = [e for e in ctx.entites if _siren_entite(e) == siren]
            if len(trouvees) == 1:
                return Identification(trouvees[0], "siren", v, hors_client)
    if ctx.utilisable(partie.nom):
        assert partie.nom is not None
        e = _par_alias(ctx, partie.nom.valeur or "")
        if e is not None:
            return Identification(e, "alias", partie.nom, hors_client)
    return Identification(tva_hors_client=hors_client)


def identifier_facture(ctx: ControlContext, fc: Document) -> Identification:
    """Entité de la facture : pavé acheteur, puis destinataire si l'acheteur n'identifie rien (A1)."""
    ident = identifier_partie(ctx, fc.fc.acheteur)
    if ident.entite is not None:
        return ident
    dest = identifier_partie(ctx, fc.fc.destinataire)
    if dest.entite is not None:
        return dest
    return ident


def entites_client_declaration(ctx: ControlContext, dec: Document) -> dict[str, tuple[Entite, ValeurSourcee]]:
    """Entités du client dont une TVA lisible figure sur la déclaration (importateur, destinataire,
    indices d'autoliquidation…) : ``{entite_id: (entite, valeur)}``."""
    out: dict[str, tuple[Entite, ValeurSourcee]] = {}
    for v in dec.valeurs():
        if v.type is not TypeValeur.tva and not v.chemin.endswith(".tva"):
            continue
        if not ctx.utilisable(v):
            continue
        e = ctx.entite_par_tva(v.valeur)
        if e is not None and e.id not in out:
            out[e.id] = (e, v)
    return out


# --- P1 ------------------------------------------------------------------------------------------------


@control("P1")
def p1_completude(ctx: ControlContext) -> list[ResultatControle]:
    """P1 — au moins une facture commerciale exploitable **et** au moins une déclaration (§9).

    Une facture du transitaire absente n'est pas un manque (C et D deviennent ``non_applicable``) : P1 le
    mentionne seulement dans ``details``.
    """
    manquants: list[TypeDocument] = []
    if not ctx.factures_commerciales():
        manquants.append(TypeDocument.facture_commerciale)
    if not ctx.declarations():
        manquants.append(TypeDocument.declaration)
    details = {"facture_transitaire_absente": not ctx.factures_transitaires()}
    if not manquants:
        return [ctx.conforme("P1", details=details)]

    # Documents présents mais non exploitables (P2) : rattachés au type manquant selon leur rôle ;
    # un document sans rôle explicite est un document « intitulé facture » (§5.3.1).
    non_exploitables: dict[TypeDocument, list[Document]] = {}
    for doc, role in _documents_lies(ctx):
        if not _est_non_exploitable(doc):
            continue
        t = _ROLE_TYPE.get(role, TypeDocument.facture_commerciale)
        non_exploitables.setdefault(t, []).append(doc)

    phrases = []
    preuves = []
    raisons = [RaisonCode.document_manquant]
    for t in manquants:
        nom = _LIBELLES_TYPE[t]
        presents = non_exploitables.get(t, [])
        if presents:
            motifs = ", ".join(
                LIBELLES_MOTIF.get(d.motif_non_exploitable, "document non reconnu")
                if d.motif_non_exploitable else "document non reconnu"
                for d in presents
            )
            phrases.append(f"{nom} présente mais non exploitable : {motifs}")
            preuves.extend(_preuve_document(d, d.motif_non_exploitable) for d in presents)
            raisons.append(RaisonCode.document_non_exploitable)
        else:
            phrases.append(f"aucune {nom} exploitable")
    libelle = "Le dossier est incomplet : " + " ; ".join(phrases) + "."
    details["documents_manquants"] = [t.value for t in manquants]
    # Documents concernés : ceux qui restent sans contrepartie (facture sans déclaration, déclaration sans
    # facture) et les documents non exploitables tenant lieu du document manquant (D-801).
    concernes = [d.id for d in (*ctx.factures_commerciales(), *ctx.declarations())]
    concernes += [d.id for t in manquants for d in non_exploitables.get(t, [])]
    return [
        ctx.constat(
            "P1",
            _classement_p(*raisons),
            libelle=libelle,
            prochaine_action=ACTION_P1,
            preuves=preuves,
            documents=list(dict.fromkeys(concernes)),
            attendu=",".join(t.value for t in manquants),
            constate="absent",
            details=details,
        )
    ]


# --- P2 ------------------------------------------------------------------------------------------------


@control("P2")
def p2_document_non_exploitable(ctx: ControlContext) -> list[ResultatControle]:
    """P2 — un résultat par document lié : constat ``a_verifier`` (raison ``document_non_exploitable``) pour
    un document reconnu comme non exploitable (pré-alerte, devis, illisible…), ``conforme`` sinon."""
    resultats = []
    for doc, _role in _documents_lies(ctx):
        unite = cle_unite(doc=doc.id)
        if not _est_non_exploitable(doc):
            resultats.append(ctx.conforme("P2", unite=unite, documents=[doc.id]))
            continue
        motif = doc.motif_non_exploitable
        nom_motif = LIBELLES_MOTIF.get(motif, "document non reconnu") if motif else "document non reconnu"
        pages = _pages(doc)
        lieu = f" ({pages})" if pages else ""
        libelle = (
            f"Un document du dossier{lieu} a été reconnu comme « {nom_motif} » : il n'est pas exploité comme "
            "facture commerciale."
        )
        resultats.append(
            ctx.constat(
                "P2",
                _classement_p(RaisonCode.document_non_exploitable),
                unite=unite,
                libelle=libelle,
                prochaine_action=ACTION_P2,
                preuves=[_preuve_document(doc, motif.value if motif else None)],
                documents=[doc.id],
                constate=motif.value if motif else "non_reconnu",
                details={"motif": motif.value if motif else None},
            )
        )
    return resultats


# --- P3 ------------------------------------------------------------------------------------------------


def _champs_cles_requis(doc: Document) -> list[str]:
    cles = sorted(CHAMPS_CLES.get(doc.type, frozenset()))
    if doc.type is TypeDocument.declaration:
        # Le taux de change n'est un champ clé que si la monnaie de facturation n'est pas l'euro.
        devise = doc.dec.devise_facture
        if devise is not None and (devise.valeur or "").upper() == "EUR":
            cles = [c for c in cles if c != "taux_change"]
    return cles


def champs_cles_illisibles(ctx: ControlContext, doc: Document) -> list[tuple[str, RaisonCode]]:
    """P3 : champs clés (*) d'un document absents ou de confiance < ``C_MIN_UTILE``, avec la raison."""
    if doc.champs is None:
        return []
    out = []
    for chemin in _champs_cles_requis(doc):
        v = doc.champs.obtenir(chemin)
        if not ctx.utilisable(v):
            out.append((chemin, ctx.raison_inutilisable(v)))
    return out


@control("P3")
def p3_champ_cle_illisible(ctx: ControlContext) -> list[ResultatControle]:
    """P3 — mécanisme « non vérifiable » : un résultat ``non_verifiable`` (jamais de constat) par champ clé
    absent ou illisible d'un document exploitable ; rien pour les champs lisibles. Les contrôles dépendants
    appliquent eux-mêmes la règle (``ctx.utilisable``)."""
    resultats = []
    for doc, _role in _documents_lies(ctx):
        if _est_non_exploitable(doc):
            continue
        for chemin, raison in champs_cles_illisibles(ctx, doc):
            resultats.append(
                ctx.non_verifiable(
                    "P3", raison, unite=cle_unite(doc=doc.id, champ=chemin), documents=[doc.id],
                    details={"champ": chemin, "type_document": doc.type.value},
                )
            )
    return resultats


# --- P4 ------------------------------------------------------------------------------------------------


@control("P4")
def p4_rattachement_faible(ctx: ControlContext) -> list[ResultatControle]:
    """P4 — un résultat par lien : ``conforme`` pour un lien solide ; les liens de force ``faible`` donnent
    **un** constat ``a_verifier`` (raison ``rattachement_faible``, signaux affichés pour chaque document).
    Plusieurs documents faiblement rattachés au même dossier relèvent d'une même vérification (D-2312) : un
    seul constat les énumère tous, les autres liens faibles renvoient à lui (``couvert_par_autre_controle``).
    La condition 5 de §8.5.1 rend en outre « au plus à vérifier » tout constat qui dépend d'un lien non
    solide."""
    resultats = []
    faibles: list[tuple[LienDocument, Document, list[str], dict]] = []
    for lien in ctx.dossier.liens:
        doc = ctx.document(lien.document_id)
        if doc is None:
            continue
        unite = cle_unite(lien=lien.document_id)
        signaux = [s.value for s in lien.signaux]
        details = {"force": lien.force.value, "signaux": signaux}
        if doc.doublon_de:
            # Copie d'un document déjà présent (F1) : écartée des contrôles, son lien suit celui de l'original.
            resultats.append(ctx.non_applicable("P4", RaisonCode.couvert_par_autre_controle, unite=unite,
                                                documents=[doc.id], details={**details, "doublon_de": doc.doublon_de}))
            continue
        if lien.force is not ForceLien.faible:
            resultats.append(ctx.conforme("P4", unite=unite, documents=[doc.id], details=details))
            continue
        faibles.append((lien, doc, signaux, details))
    if not faibles:
        return resultats
    lien0, _doc0, _, details0 = faibles[0]
    morceaux = []
    for _lien, doc, signaux, _details in faibles:
        noms = ", ".join(_SIGNAUX.get(s, s) for s in signaux) or "aucun"
        pages = _pages(doc)
        lieu = f" ({pages})" if pages else ""
        morceaux.append((doc, noms, f"{_type_doc(doc)}{lieu} (signaux : {noms})"))
    if len(morceaux) == 1:
        doc, noms, _ = morceaux[0]
        pages = _pages(doc)
        lieu = f" ({pages})" if pages else ""
        libelle = (
            f"Le document {_type_doc(doc)}{lieu} est rattaché au dossier par un lien faible "
            f"(signaux : {noms})."
        )
    else:
        libelle = ("Les documents suivants sont rattachés au dossier par un lien faible : "
                   + " ; ".join(m[2] for m in morceaux) + ".")
    unite0 = cle_unite(lien=lien0.document_id)
    resultats.append(
        ctx.constat(
            "P4",
            _classement_p(RaisonCode.rattachement_faible),
            unite=unite0,
            libelle=libelle,
            prochaine_action=ACTION_P4,
            preuves=[_preuve_document(doc, noms) for doc, noms, _ in morceaux],
            documents=[doc.id for doc, _, _ in morceaux],
            constate=lien0.force.value,
            details={**details0, "documents_faibles": [
                {"document_id": doc.id, "signaux": signaux} for _, doc, signaux, _ in faibles]},
        )
    )
    for lien, doc, _signaux, details in faibles[1:]:
        resultats.append(ctx.non_applicable(
            "P4", RaisonCode.couvert_par_autre_controle, unite=cle_unite(lien=lien.document_id), documents=[doc.id],
            details={**details, "regroupe_dans": unite0}))
    return resultats


# --- P5 ------------------------------------------------------------------------------------------------


def _acheteur_hors_client(ctx: ControlContext, fc: Document) -> ValeurSourcee | None:
    """TVA lue avec confiance ≥ 0,90 dans le pavé acheteur, qui n'est celle d'aucune entité du client, et
    aucune autre lecture (SIREN, alias, destinataire) n'identifie le client."""
    tva = fc.fc.acheteur.tva
    if tva is None or not ctx.utilisable(tva) or tva.confiance < CONFIANCE_P5 or not normalize_vat(tva.valeur):
        return None
    if identifier_facture(ctx, fc).entite is not None:
        return None
    return tva


def _tva_lisibles(ctx: ControlContext, dec: Document) -> Iterable[ValeurSourcee]:
    for v in dec.valeurs():
        if (v.type is TypeValeur.tva or v.chemin.endswith(".tva")) and ctx.utilisable(v):
            yield v


@control("P5")
def p5_dossier_non_concerne(ctx: ControlContext) -> list[ResultatControle]:
    """P5 — statut ``non_concerne`` (aucun constat, D-020) si **chaque** facture commerciale identifie dans son
    pavé acheteur, avec une confiance ≥ 0,90, une entité qui n'est pas une entité du client, **et** si aucune
    déclaration ne porte de TVA du client (au moins une TVA importateur lisible exigée : prudence).
    Le moteur arrête alors l'exécution des contrôles suivants."""
    fcs, decs = ctx.factures_commerciales(), ctx.declarations()
    if not fcs or not decs:
        return [ctx.non_verifiable("P5", RaisonCode.document_manquant)]
    if not ctx.entites:
        return [ctx.non_verifiable("P5", RaisonCode.valeur_absente, details={"motif": "aucune_entite_client"})]
    tvas_acheteur = [_acheteur_hors_client(ctx, fc) for fc in fcs]
    importateurs_lus = all(ctx.utilisable(d.dec.importateur.tva) for d in decs)
    tva_client_dec = any(entites_client_declaration(ctx, d) for d in decs)
    docs = [d.id for d in fcs] + [d.id for d in decs]
    if all(t is not None for t in tvas_acheteur) and importateurs_lus and not tva_client_dec:
        return [
            ctx.non_applicable(
                "P5", RaisonCode.dossier_non_concerne, documents=docs,
                entrees={f"acheteur_tva_{i}": t for i, t in enumerate(tvas_acheteur) if t is not None},
                details={
                    "non_concerne": True,
                    "tva_acheteur": [t.valeur for t in tvas_acheteur if t is not None],
                    "tva_declaration": sorted({v.valeur or "" for d in decs for v in _tva_lisibles(ctx, d)}),
                },
            )
        ]
    return [ctx.conforme("P5", documents=docs)]
