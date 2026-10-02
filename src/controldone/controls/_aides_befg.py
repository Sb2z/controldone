"""Aides privées partagées par les familles E, F et G (lecture des documents, débours, avoirs).

Module **interne** (préfixe ``_``) : il n'est pas chargé comme famille de contrôles et ne fait pas partie du
contrat publié (``controls.framework``). Toutes les fonctions sont pures.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from controldone.controls.context import ControlContext
from controldone.model import (
    CategorieTaxe,
    Document,
    NatureLigne,
    PaiementNormalise,
    ParametresPetitsEnvois,
    TaxationDeclaration,
    TypeDocument,
    ValeurSourcee,
)
from controldone.model.champs import LigneFactureTransitaire
from controldone.normalize.refs import mrn_prefixe, norm_ref, ref_compatibles
from controldone.normalize.text import cle_texte
from controldone.recouvrement.imputation import cle_emetteur

ZERO = Decimal(0)


# --- lecture de valeurs ------------------------------------------------------------------------------


def num(v: ValeurSourcee | None) -> Decimal | None:
    """Valeur numérique signée, ``None`` si absente ou illisible."""
    if v is None or not v.est_lisible:
        return None
    try:
        return v.decimal_signe()
    except ValueError:
        return None


def entier(v: ValeurSourcee | None) -> int | None:
    if v is None or not v.est_lisible:
        return None
    try:
        return v.entier()
    except ValueError:
        return None


def date_de(v: ValeurSourcee | None) -> date | None:
    if v is None or not v.valeur:
        return None
    try:
        return v.date_iso()
    except ValueError:
        return None


def texte(v: ValeurSourcee | None) -> str | None:
    return v.valeur if v is not None and v.valeur else None


def utilisable_num(ctx: ControlContext, v: ValeurSourcee | None) -> bool:
    return ctx.utilisable(v) and num(v) is not None


# --- références lisibles des documents (libellés, §3.1) ----------------------------------------------


def _numero(doc: Document) -> ValeurSourcee | None:
    c = doc.champs
    return getattr(c, "numero", None) if c is not None else None


def page_de(doc: Document, v: ValeurSourcee | None = None) -> int | None:
    if v is not None and v.page:
        return v.page
    return doc.pages[0].numero if doc.pages else None


def ref_document(doc: Document, v: ValeurSourcee | None = None) -> str:
    """« la facture du transitaire n° FT-1 (page 2) », « l'avoir n° AV-1 », « la déclaration (MRN …) »."""
    page = page_de(doc, v)
    p = f"page {page}" if page else None
    if doc.type is TypeDocument.declaration and doc.champs is not None:
        mrn = texte(doc.dec.mrn)
        ref = ", ".join(x for x in (f"MRN {mrn}" if mrn else None, p) if x)
        return f"la déclaration ({ref})" if ref else "la déclaration"
    noms = {
        TypeDocument.facture_transitaire: "la facture du transitaire",
        TypeDocument.avoir: "l'avoir",
        TypeDocument.facture_commerciale: "la facture commerciale",
    }
    nom = noms.get(doc.type, "le document")
    numero = texte(_numero(doc))
    base = f"{nom} n° {numero}" if numero else nom
    return f"{base} ({p})" if p else base


def maj(s: str) -> str:
    """Majuscule initiale sans toucher au reste (références imprimées conservées)."""
    return s[:1].upper() + s[1:]


# --- émetteurs, dates, fenêtre ----------------------------------------------------------------------


def emetteur_de(ctx: ControlContext, doc: Document) -> str | None:
    """Clé d'émetteur d'une facture transitaire ou d'un avoir (voir ``cle_emetteur``)."""
    if doc.champs is None or doc.type not in (TypeDocument.facture_transitaire, TypeDocument.avoir):
        return None
    return cle_emetteur(doc.champs.emetteur, ctx.transitaires)  # type: ignore[union-attr]


def memes_emetteurs(a: str | None, b: str | None) -> bool:
    """Émetteurs égaux ; un émetteur illisible d'un côté n'empêche pas le rapprochement (D-3xx)."""
    return a is None or b is None or a == b


def date_document(doc: Document) -> date | None:
    c = doc.champs
    if c is None:
        return None
    if doc.type is TypeDocument.declaration:
        return date_de(doc.dec.date_acceptation)
    return date_de(getattr(c, "date", None))


def ajouter_mois(d: date, mois: int) -> date:
    m = d.month - 1 + mois
    an, m = d.year + m // 12, m % 12 + 1
    jours = [31, 29 if an % 4 == 0 and (an % 100 != 0 or an % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31,
             30, 31][m - 1]
    return date(an, m, min(d.day, jours))


def dans_fenetre(a: date | None, b: date | None, mois: int) -> bool:
    """Deux dates à moins de ``mois`` mois d'écart ; une date inconnue ne fait pas sortir de la fenêtre."""
    if a is None or b is None:
        return True
    debut, fin = sorted((a, b))
    return fin <= ajouter_mois(debut, mois)


def cle_chrono(doc: Document) -> tuple:
    """Ordre « le plus récent » : date, puis numéro normalisé, puis identifiant (UUID v7 triable)."""
    d = date_document(doc)
    return (d is not None, d or date.min, norm_ref(texte(_numero(doc))), doc.id)


# --- autres dossiers (famille F) ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocAilleurs:
    """Document d'un autre dossier du même client, avec l'identifiant de ce dossier et la solidité du lien."""

    doc: Document
    dossier_id: str
    lien_solide: bool


def documents_autres(ctx: ControlContext, type_document: TypeDocument) -> list[DocAilleurs]:
    """Documents d'un type dans les autres dossiers (doublons F1 exclus, documents partagés exclus)."""
    ici = set(ctx.documents)
    out: list[DocAilleurs] = []
    for autre in ctx.autres_dossiers:
        for lien in autre.dossier.liens:
            d = autre.documents.get(lien.document_id)
            if d is None or d.id in ici or d.type is not type_document or d.champs is None or d.doublon_de:
                continue
            out.append(DocAilleurs(d, autre.dossier.id, lien.force.est_solide))
    return out


# --- déclarations : forfait petits envois, montants liquidés -----------------------------------------


def est_forfait(t: TaxationDeclaration, params: ParametresPetitsEnvois) -> bool:
    """Ligne de forfait petits envois (§16, détection) : catégorie normalisée, code configuré, ou libellé
    configuré retrouvé dans le texte lu du type de taxe."""
    if t.categorie is CategorieTaxe.forfait_petits_envois:
        return True
    if t.type_taxe is None:
        return False
    code = norm_ref(t.type_taxe.valeur)
    if code and code in {norm_ref(c) for c in params.codes_forfait_petits_envois}:
        return True
    lu = cle_texte(" ".join(x for x in (t.type_taxe.valeur_brute, t.type_taxe.texte_contexte) if x))
    return any(cle_texte(lib) in lu for lib in params.libelles_forfait_petits_envois if lib)


def lignes_forfait(dec: Document, params: ParametresPetitsEnvois) -> list[tuple[int, TaxationDeclaration]]:
    return [(i, t) for i, t in enumerate(dec.dec.taxations) if est_forfait(t, params)]


def montant_liquide(t: TaxationDeclaration) -> ValeurSourcee | None:
    """``montant_a_payer`` à défaut ``montant`` (§12.1)."""
    return t.montant_a_payer if t.montant_a_payer is not None else t.montant


def liquide(
    ctx: ControlContext, taxations: Iterable[TaxationDeclaration]
) -> tuple[Decimal, list[ValeurSourcee]] | None:
    """Σ des montants liquidés (hors lignes autoliquidées) ; ``None`` si un montant est inexploitable."""
    total, vals = ZERO, []
    for t in taxations:
        if t.paiement_normalise is PaiementNormalise.autoliquide:
            continue
        v = montant_liquide(t)
        if not utilisable_num(ctx, v):
            return None
        assert v is not None
        total += num(v) or ZERO
        vals.append(v)
    return total, vals


def liquide_total(ctx: ControlContext, dec: Document) -> Decimal | None:
    """``liquide_total[d]`` (§12.1, sans la règle de complétude) ; ``None`` si inexploitable."""
    r = liquide(ctx, dec.dec.taxations)
    return r[0] if r is not None else None


def nb_articles(dec: Document) -> int:
    n = entier(dec.dec.nombre_articles)
    return n if n is not None else len(dec.dec.articles)


# --- factures transitaires : MRN cités et ventilation des débours (§12.2) -----------------------------


def mrn_cites(doc: Document) -> dict[str, ValeurSourcee]:
    """Préfixes MRN cités par une facture transitaire ou un avoir (en-tête, tableau, lignes)."""
    c = doc.champs
    out: dict[str, ValeurSourcee] = {}
    vals: list[ValeurSourcee] = list(getattr(c, "refs_mrn", []))
    vals += [x.mrn for x in getattr(c, "tableau_mrn", []) if x.mrn is not None]
    vals += [ln.mrn for ln in getattr(c, "lignes", []) if ln.mrn is not None]
    for v in vals:
        p = mrn_prefixe(v.valeur)
        if len(p) == 15:
            out.setdefault(p, v)
    return out


@dataclass(frozen=True, slots=True)
class GroupeDebours:
    """Débours d'une facture transitaire affectés à un ensemble de déclarations (§12.2)."""

    prefixes: tuple[str, ...]
    lignes: tuple[int, ...]
    #: Valeur sourcée du MRN qui justifie l'affectation (ligne ou en-tête), si lue.
    mrn_valeurs: tuple[ValeurSourcee, ...]


def ventiler_debours(
    ft: Document, prefixes_dossier: Sequence[str], natures: Iterable[NatureLigne] | None = None
) -> list[GroupeDebours]:
    """Ventilation §12.2 des lignes de débours (``natures`` ; toutes les natures ``debours_*`` par défaut).

    - lignes citant un MRN -> groupe de cette déclaration ;
    - lignes sans MRN : si la facture ne couvre qu'une déclaration (MRN cités, à défaut déclarations du
      dossier) -> ce groupe ; sinon un groupe unique « somme des déclarations couvertes » qui absorbe
      aussi les lignes ventilées de ces déclarations.
    """
    nat = set(natures) if natures is not None else {n for n in NatureLigne if n.est_debours}
    cites = mrn_cites(ft)
    par_prefixe: dict[str, list[int]] = {}
    mrn_vals: dict[str, list[ValeurSourcee]] = {}
    sans_mrn: list[int] = []
    for i, ln in enumerate(ft.ft.lignes if ft.type is TypeDocument.facture_transitaire else ft.av.lignes):
        if ln.nature not in nat:
            continue
        p = mrn_prefixe(ln.mrn.valeur) if ln.mrn is not None else ""
        if len(p) == 15:
            par_prefixe.setdefault(p, []).append(i)
            assert ln.mrn is not None
            mrn_vals.setdefault(p, []).append(ln.mrn)
        else:
            sans_mrn.append(i)
    groupes: dict[tuple[str, ...], tuple[list[int], list[ValeurSourcee]]] = {
        (p,): (idx, mrn_vals[p]) for p, idx in par_prefixe.items()
    }
    if sans_mrn:
        couverts = sorted(cites) if cites else sorted(set(prefixes_dossier))
        if len(couverts) == 1:
            p = couverts[0]
            idx, vals = groupes.setdefault((p,), ([], []))
            idx.extend(sans_mrn)
            if p in cites:
                vals.append(cites[p])
        else:
            idx, vals = list(sans_mrn), [cites[p] for p in couverts if p in cites]
            for p in couverts:
                g = groupes.pop((p,), None)
                if g is not None:
                    idx.extend(g[0])
            groupes[tuple(couverts)] = (idx, vals)
    return [GroupeDebours(k, tuple(sorted(v[0])), tuple(v[1])) for k, v in sorted(groupes.items())]


def lignes_ft(doc: Document) -> list[LigneFactureTransitaire]:
    if doc.type is TypeDocument.facture_transitaire:
        return doc.ft.lignes
    if doc.type is TypeDocument.avoir:
        return doc.av.lignes
    return []


def montant_ht(ln: LigneFactureTransitaire) -> ValeurSourcee | None:
    return ln.montant_ht if ln.montant_ht is not None else ln.montant_ttc


# --- avoirs reçus deux fois (E3) -----------------------------------------------------------------------


def _total_avoir(doc: Document) -> Decimal | None:
    av = doc.av
    v = av.total_credite_ttc if av.total_credite_ttc is not None else av.total_credite_ht
    return num(v)


def avoirs_en_double(a: Document, b: Document, ea: str | None, eb: str | None) -> str | None:
    """Motif si ``a`` et ``b`` sont le même avoir reçu deux fois (§14 E3), sinon ``None``."""
    if a.id == b.id or not memes_emetteurs(ea, eb):
        return None
    na, nb = norm_ref(texte(a.av.numero)), norm_ref(texte(b.av.numero))
    if na and na == nb and ea is not None and eb is not None:
        return "meme_numero"
    ta, tb = _total_avoir(a), _total_avoir(b)
    if ta is None or tb is None or abs(ta) != abs(tb):
        return None
    oa = [x.valeur for x in a.av.refs_facture_origine if x.valeur]
    ob = [x.valeur for x in b.av.refs_facture_origine if x.valeur]
    if not any(ref_compatibles(x, y) for x in oa for y in ob):
        return None
    da, db = date_de(a.av.date), date_de(b.av.date)
    if da is None or db is None or abs((da - db).days) >= 7:
        return None
    return "meme_montant_meme_origine"


@dataclass(frozen=True, slots=True)
class AvoirDouble:
    second: Document
    premier: Document
    dossier_premier: str | None  # None : même dossier
    motif: str


def avoirs_doubles(ctx: ControlContext) -> dict[str, AvoirDouble]:
    """Avoirs du dossier qui sont la **seconde** réception d'un avoir déjà reçu (ici ou ailleurs)."""
    ici = ctx.avoirs()
    tous: list[tuple[Document, str | None]] = [(d, None) for d in ici]
    tous += [(x.doc, x.dossier_id) for x in documents_autres(ctx, TypeDocument.avoir)]
    out: dict[str, AvoirDouble] = {}
    for d in ici:
        ed = emetteur_de(ctx, d)
        anterieurs = []
        for autre, dos in tous:
            if autre.id == d.id or cle_chrono(autre) >= cle_chrono(d):
                continue
            motif = avoirs_en_double(d, autre, ed, emetteur_de(ctx, autre))
            if motif:
                anterieurs.append((cle_chrono(autre), autre, dos, motif))
        if anterieurs:
            _, premier, dos, motif = min(anterieurs, key=lambda x: x[0])
            out[d.id] = AvoirDouble(d, premier, dos, motif)
    return out


def avoirs_imputables(ctx: ControlContext) -> list[Document]:
    """Avoirs du dossier à imputer : la seconde réception d'un même avoir n'est pas imputée (E3)."""
    doubles = avoirs_doubles(ctx)
    return [d for d in ctx.avoirs() if d.id not in doubles]
