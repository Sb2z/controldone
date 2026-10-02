"""Famille C — Facture du transitaire contre déclaration (SPEC §12).

La déclaration est la **référence** : ses montants sont pris tels qu'imprimés, jamais recalculés à partir
des taux. Les libellés sont comparatifs (« la facture refacture X ; la déclaration indique Y ») ; ils ne
qualifient jamais le transitaire (§3.1 règle 3) et ne disent pas si l'autoliquidation était applicable
(C3 constate seulement ce que la déclaration indique).

Structure :

- ``reference_declaration`` : montants de référence par déclaration (§12.1), règle de complétude incluse ;
- ``unites_c`` : unités de comparaison (facture(s) transitaire × déclaration(s), §12.2), avec la ventilation
  par MRN, les allocations, les factures complémentaires additionnées et les avoirs déjà reçus ;
- C1 à C8, chacun enregistré par ``@control``.

Convention d'unité (§8.6, runner) : C1–C5 utilisent ``UniteC.cle`` = ``cle_unite(ft=…, dec=[…])`` ; C6
``cle_unite(ft=<facture>, ligne=<index>)`` ; C7 et C8 ``cle_unite(ft=<facture>)``. Les choix
d'interprétation sont notés dans ``docs/DECISIONS.md`` (D-2xx, « Contrôles C et D »).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from controldone.controls.confusion import (
    CLASSES_CONFUSION,
    LETTRES_CHIFFRES,
    codes_confondables,
    confusion_applicable,
)
from controldone.controls.framework import (
    Confusion,
    ControlContext,
    arrondi_centime,
    cle_unite,
    control,
    preuve,
)
from controldone.formatage import format_montant, format_pourcentage
from controldone.model import (
    ChampsDeclaration,
    BasePourcentage,
    CategorieTaxe,
    Composante,
    Document,
    GrilleTarifaire,
    LigneFactureTransitaire,
    ModePoste,
    NatureLigne,
    Niveau,
    PaiementNormalise,
    PosteGrille,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    TypeIndiceAutoliquidation,
    ValeurSourcee,
)
from controldone.normalize.fiscal import normalize_vat
from controldone.normalize.refs import (
    mrn_prefixe,
    norm_ref,
    norm_ref_transport,
    ref_compatibles,
    ref_transport_compatibles,
)
from controldone.normalize.text import cle_texte

__all__ = [
    "ACTION_C",
    "ACTION_C_FAVEUR",
    "CreditAvoir",
    "LigneDebours",
    "ReferenceDeclaration",
    "UniteC",
    "assiette_debours",
    "c1_droits",
    "c2_autres_taxes",
    "c3_tva_autoliquidee",
    "c4_tva",
    "c5_total_debours",
    "c6_faf_sur_excedent",
    "c7_references",
    "c8_client_facture",
    "declarations_couvertes",
    "declarations_de_ligne",
    "dossier_principal",
    "dossiers_freres",
    "excedent_debours",
    "grille_pour_facture",
    "libelle_facture",
    "ligne_evaluee_ici",
    "ligne_hors_dossier",
    "page_txt",
    "reference_declaration",
    "unites_c",
    "unites_pour_facture",
    "unites_pour_ligne",
]

ZERO = Decimal(0)
_CENT = Decimal(100)

#: Prochaine action d'un écart refacturé au-delà de la référence (jamais d'accusation, §3.1 règle 3).
ACTION_C = (
    "Vérifier les montants sur les pièces citées puis, si l'écart se confirme, demander au transitaire "
    "un avoir ou le détail du montant refacturé, en joignant la déclaration."
)
#: Prochaine action d'un écart en faveur du client (§8.6 : jamais réclamé).
ACTION_C_FAVEUR = (
    "Écart en faveur du client : vérifier si une facture complémentaire est attendue. "
    "Aucun avoir n'est à demander pour cet écart."
)
ACTION_C3 = (
    "Demander au transitaire un avoir de cette TVA ou l'explication de sa refacturation, en joignant la "
    "déclaration. Ce constat porte sur la différence entre les deux documents ; il ne se prononce pas sur "
    "l'applicabilité de l'autoliquidation."
)
ACTION_C6 = (
    "Si l'écart de débours est confirmé, demander au transitaire l'avoir des frais d'avance de fonds "
    "correspondants, calculés sur l'excédent seulement."
)
ACTION_C7 = (
    "Vérifier que la facture se rapporte bien à cet envoi et, si besoin, demander au transitaire une facture "
    "citant les bonnes références."
)
ACTION_C8 = (
    "Vérifier l'entité facturée et, si besoin, demander au transitaire une facture établie au nom de "
    "l'entité importatrice."
)

#: Catégories de taxe comparées par la famille C (le forfait petits envois est comparé par G4, compté en C5).
CATEGORIES = (
    CategorieTaxe.droit,
    CategorieTaxe.autre_taxe,
    CategorieTaxe.tva,
    CategorieTaxe.forfait_petits_envois,
)
_NATURE_CATEGORIE: dict[NatureLigne, CategorieTaxe | None] = {
    NatureLigne.debours_droits: CategorieTaxe.droit,
    NatureLigne.debours_autres_taxes: CategorieTaxe.autre_taxe,
    NatureLigne.debours_tva: CategorieTaxe.tva,
    NatureLigne.debours_forfait_petits_envois: CategorieTaxe.forfait_petits_envois,
    NatureLigne.debours_combines: None,
}
_COMPOSANTE = {
    CategorieTaxe.droit: Composante.droit,
    CategorieTaxe.autre_taxe: Composante.autre_taxe,
    CategorieTaxe.tva: Composante.tva,
    CategorieTaxe.forfait_petits_envois: Composante.forfait_petits_envois,
}
_NOM_CATEGORIE = {
    CategorieTaxe.droit: "les droits de douane",
    CategorieTaxe.autre_taxe: "les autres taxes",
    CategorieTaxe.tva: "la TVA à l'importation",
    CategorieTaxe.forfait_petits_envois: "le droit forfaitaire petits envois",
}
_REFACTURE_CATEGORIE = {
    CategorieTaxe.droit: "de droits de douane",
    CategorieTaxe.autre_taxe: "d'autres taxes",
    CategorieTaxe.tva: "de TVA à l'importation",
    CategorieTaxe.forfait_petits_envois: "de droit forfaitaire petits envois",
}


# =====================================================================================================
# Outils communs
# =====================================================================================================


def _dec(ctx: ControlContext, v: ValeurSourcee | None) -> Decimal | None:
    """Montant signé d'une valeur utilisable (``None`` si absente, illisible ou trop douteuse)."""
    if not ctx.utilisable(v):
        return None
    assert v is not None
    try:
        return v.decimal_signe()
    except ValueError:
        return None


def _somme(xs: Iterable[Decimal]) -> Decimal:
    return sum(xs, ZERO)


def page_txt(valeurs: Iterable[ValeurSourcee | None]) -> str:
    """« page 2 » / « pages 1, 3 » (vide si aucune page connue)."""
    pages = sorted({v.page for v in valeurs if v is not None and v.page is not None})
    if not pages:
        return ""
    return ("page " if len(pages) == 1 else "pages ") + ", ".join(str(p) for p in pages)


def _entre_parentheses(*morceaux: str) -> str:
    m = [x for x in morceaux if x]
    return f" ({', '.join(m)})" if m else ""


def _numero(doc: Document) -> str:
    champs = doc.champs
    v = getattr(champs, "numero", None)
    return f"n° {v.valeur}" if v is not None and v.valeur else "sans numéro lu"


def libelle_facture(factures: Sequence[Document]) -> str:
    """« La facture du transitaire n° F-1 » / « Les factures du transitaire n° F-1 et n° F-2 »."""
    nums = [_numero(f) for f in factures]
    if len(nums) == 1:
        return f"La facture du transitaire {nums[0]}"
    return f"Les factures du transitaire {', '.join(nums[:-1])} et {nums[-1]}"


def _mrn(dec: Document) -> str:
    v = dec.dec.mrn
    return f"MRN {v.valeur}" if v is not None and v.valeur else "MRN non lu"


def _libelle_declarations(decs: Sequence[Document]) -> str:
    if len(decs) == 1:
        return f"la déclaration ({_mrn(decs[0])})"
    return f"les déclarations ({', '.join(_mrn(d) for d in decs)})"


def _accord(n: int, singulier: str, pluriel: str) -> str:
    return singulier if n == 1 else pluriel


# =====================================================================================================
# §12.1 — Montants de référence par déclaration
# =====================================================================================================


@dataclass
class ReferenceDeclaration:
    """Montants de référence d'une déclaration (§12.1)."""

    dec: Document
    liquide: dict[CategorieTaxe, Decimal]
    sources: dict[CategorieTaxe, list[ValeurSourcee]]
    #: Lignes de catégorie ``inconnue`` (comptées dans le total seulement).
    autres_sources: list[ValeurSourcee]
    #: Catégories sans aucune ligne de taxation lue.
    sans_ligne: set[CategorieTaxe]
    #: Composantes non vérifiables (ligne illisible, composante non extraite…) et leur raison.
    indisponibles: dict[CategorieTaxe, RaisonCode]
    #: Indices d'autoliquidation utilisables, du plus sûr au moins sûr, avec leur description.
    indices: list[tuple[ValeurSourcee, str]]
    #: Lignes de TVA écartées de la comparaison (autoliquidation indiquée).
    tva_ecartee: list[ValeurSourcee]
    total: ValeurSourcee | None
    total_utilise: bool
    complet_verifie: bool
    liquide_total: Decimal | None
    raison_total: RaisonCode | None
    nb_articles: int
    #: Montant imprimé au total à payer et non retrouvé dans les lignes lues (règle de complétude), ou 0.
    manquant: Decimal = ZERO
    #: Lecture des lignes de taxation probablement incomplète (D-901) : motif, ou ``None``. Les comparaisons
    #: par composante (et C5 fondé sur la somme des lignes) sont alors au plus ``a_verifier``.
    lecture_incomplete: str | None = None

    @property
    def autoliquide(self) -> bool:
        return bool(self.indices)

    def valeurs_total(self) -> list[ValeurSourcee]:
        """Valeurs qui fondent ``liquide_total``."""
        if self.total_utilise and self.total is not None:
            return [self.total]
        return [v for c in CATEGORIES for v in self.sources[c]] + list(self.autres_sources)


def _description_indice(type_indice: TypeIndiceAutoliquidation, ind_valeur: ValeurSourcee | None,
                        ind_tva: ValeurSourcee | None) -> str:
    if type_indice is TypeIndiceAutoliquidation.code_1008:
        if ind_tva is not None and ind_tva.valeur:
            return f"code document 1008 suivi du numéro {ind_tva.valeur_brute or ind_tva.valeur}"
        return "code document 1008"
    if type_indice is TypeIndiceAutoliquidation.reference_fr7:
        return "référence fiscale complémentaire FR7"
    brut = ind_valeur.valeur_brute or ind_valeur.valeur if ind_valeur is not None else None
    return f"mode de paiement de la ligne de TVA « {brut} »" if brut else "mode de paiement de la ligne de TVA"


def _nb_articles(ctx: ControlContext, dec: Document) -> int:
    c = dec.dec
    if ctx.utilisable(c.nombre_articles):
        assert c.nombre_articles is not None
        try:
            return max(1, c.nombre_articles.entier())
        except ValueError:
            pass
    if c.articles:
        return len(c.articles)
    arts = {t.article.valeur for t in c.taxations if t.article is not None and t.article.valeur}
    return max(1, len(arts))


def reference_declaration(ctx: ControlContext, dec: Document) -> ReferenceDeclaration:
    """§12.1 : ``liquide[d][k]``, ``autoliquide[d]``, ``liquide_total[d]`` et règle de complétude.

    - ``liquide[k]`` = Σ ``montant_a_payer`` (à défaut ``montant``) des lignes de catégorie ``k`` dont le
      paiement n'est pas ``autoliquide`` ;
    - autoliquidation : au moins un indice utilisable (code 1008, FR7, ligne TVA ``autoliquide``) ; la
      confiance ≥ 0,90 exigée par §12.1 pour un ``ecart_certain`` est vérifiée par le classement de C3
      (l'indice est une valeur clé) ; si autoliquidation, ``liquide[tva] = 0`` ;
    - complétude : si ``total_a_payer`` dépasse la somme de plus de ``T_SOMME``, ``liquide_total`` =
      ``total_a_payer`` et les composantes non extraites deviennent indisponibles (C5 seul s'exécute).
    """
    c = dec.dec
    tol = ctx.tol
    liquide = {k: ZERO for k in CATEGORIES}
    sources: dict[CategorieTaxe, list[ValeurSourcee]] = {k: [] for k in CATEGORIES}
    autres: list[ValeurSourcee] = []
    indisponibles: dict[CategorieTaxe, RaisonCode] = {}
    presentes: set[CategorieTaxe] = set()

    # Indices d'autoliquidation (§5.3.2, §12.1).
    indices: list[tuple[ValeurSourcee, str]] = []
    for ind in c.indices_autoliquidation:
        v = next((x for x in (ind.valeur, ind.tva) if ctx.utilisable(x)), None)
        if v is not None:
            indices.append((v, _description_indice(ind.type, ind.valeur, ind.tva)))
    for t in c.taxations:
        if t.categorie is CategorieTaxe.tva and t.paiement_normalise is PaiementNormalise.autoliquide:
            v = next((x for x in (t.mode_paiement, t.montant, t.type_taxe) if ctx.utilisable(x)), None)
            if v is not None:
                indices.append((v, _description_indice(TypeIndiceAutoliquidation.mode_paiement_tva,
                                                       t.mode_paiement, None)))
    indices.sort(key=lambda iv: -iv[0].confiance)
    autoliquide = bool(indices)

    tva_ecartee: list[ValeurSourcee] = []
    montant_autoliquide = ZERO
    inutilisables: list[RaisonCode] = []
    for t in c.taxations:
        cat = t.categorie
        presentes.add(cat)
        v = t.montant_a_payer if ctx.utilisable(t.montant_a_payer) else t.montant
        if t.paiement_normalise is PaiementNormalise.autoliquide:
            m = _dec(ctx, t.montant)
            if m is not None:
                montant_autoliquide += m
            if t.montant is not None:
                tva_ecartee.append(t.montant)
            continue
        m = _dec(ctx, v)
        if m is None:
            raison = ctx.raison_inutilisable(v)
            inutilisables.append(raison)
            cibles = CATEGORIES if cat is CategorieTaxe.inconnue else (cat,)
            for k in cibles:
                indisponibles.setdefault(k, raison)
            continue
        assert v is not None
        if cat is CategorieTaxe.inconnue:
            autres.append(v)
            continue
        if cat is CategorieTaxe.tva and autoliquide:
            tva_ecartee.append(v)
            montant_autoliquide += m
            continue
        liquide[cat] += m
        sources[cat].append(v)

    if autres:
        for k in (CategorieTaxe.droit, CategorieTaxe.autre_taxe, CategorieTaxe.tva):
            indisponibles.setdefault(k, RaisonCode.valeur_absente)

    sans_ligne = {k for k in CATEGORIES if k not in presentes}
    somme = _somme(liquide.values()) + _somme(v.decimal_signe() for v in autres)
    total = c.total_a_payer if _dec(ctx, c.total_a_payer) is not None else None
    total_utilise = False
    complet_verifie = False
    manquant = ZERO
    liquide_total: Decimal | None = somme
    raison_total: RaisonCode | None = None

    if inutilisables:
        if total is not None:
            total_utilise, liquide_total = True, total.decimal_signe()
            manquant = max(ZERO, liquide_total - somme)
        else:
            liquide_total, raison_total = None, inutilisables[0]
    elif not c.taxations and total is None:
        liquide_total, raison_total = None, RaisonCode.valeur_absente
        for k in CATEGORIES:
            indisponibles.setdefault(k, RaisonCode.valeur_absente)
    elif total is not None:
        tot = total.decimal_signe()
        t_somme = tol.t_somme(max(1, len(c.taxations)))
        diff = tot - somme
        if diff > t_somme and not (montant_autoliquide and abs(diff - montant_autoliquide) <= t_somme):
            # Règle de complétude (§12.1) : une composante n'a pas été extraite.
            total_utilise, liquide_total, manquant = True, tot, diff
            candidates = [k for k in (CategorieTaxe.droit, CategorieTaxe.autre_taxe) if k in sans_ligne]
            if not autoliquide and CategorieTaxe.tva in sans_ligne:
                candidates.append(CategorieTaxe.tva)
            for k in candidates or CATEGORIES:
                indisponibles.setdefault(k, RaisonCode.valeur_absente)
        elif diff >= -t_somme or (montant_autoliquide and abs(diff - montant_autoliquide) <= t_somme):
            complet_verifie = True

    return ReferenceDeclaration(
        dec=dec, liquide=liquide, sources=sources, autres_sources=autres, sans_ligne=sans_ligne,
        indisponibles=indisponibles, indices=indices, tva_ecartee=tva_ecartee, total=total,
        total_utilise=total_utilise, complet_verifie=complet_verifie, liquide_total=liquide_total,
        raison_total=raison_total, nb_articles=_nb_articles(ctx, dec), manquant=manquant,
        lecture_incomplete=_lecture_incomplete(ctx, dec, somme, montant_autoliquide),
    )


def _lecture_incomplete(ctx: ControlContext, dec: Document, somme: Decimal, montant_autoliquide: Decimal
                        ) -> str | None:
    """Garde de complétude (§12.1, §8.5.1 conditions 3–4 ; D-901) : la somme des lignes de taxation lues
    peut-elle être incomplète ?

    1. Un total imprimé (``total_a_payer`` ou ``total_droits_taxes``) est lu (confiance ≥ ``C_MIN_UTILE``) et
       aucun total lu ne concorde, à ``T_SOMME`` près, avec la somme des lignes lues, TVA autoliquidée
       exclue ou incluse (mêmes hypothèses que B2). Une ligne non lue (ou mal lue) est l'explication la plus
       fréquente, dans un sens comme dans l'autre.
    2. Les lignes par article semblent incomplètes : un article attendu (articles lus, ``nombre_articles``)
       sans aucune ligne, ou un article sans ligne d'une catégorie (droits, TVA) que portent tous les
       autres articles.
    """
    c = dec.dec
    totaux = [v for v in (_dec(ctx, c.total_a_payer), _dec(ctx, c.total_droits_taxes)) if v is not None]
    if totaux:
        t = ctx.tol.t_somme(max(1, len(c.taxations)))
        hypotheses = [somme] + ([somme + montant_autoliquide] if montant_autoliquide else [])
        if not any(abs(tot - h) <= t for tot in totaux for h in hypotheses):
            return "total_imprime_different_de_la_somme_des_lignes_lues"
    return _lignes_par_article_incompletes(ctx, c)


def _lignes_par_article_incompletes(ctx: ControlContext, c: ChampsDeclaration) -> str | None:
    par_article: dict[int, set[CategorieTaxe]] = {}
    for t in c.taxations:
        if not ctx.utilisable(t.article):
            continue
        assert t.article is not None
        try:
            n = t.article.entier()
        except (ValueError, ArithmeticError):
            continue
        par_article.setdefault(n, set()).add(t.categorie)
    if len(par_article) < 2:
        return None  # taxation au niveau de la déclaration, ou un seul article : rien à comparer
    attendus: set[int] = set()
    for a in c.articles:
        if ctx.utilisable(a.numero_article):
            assert a.numero_article is not None
            try:
                attendus.add(a.numero_article.entier())
            except (ValueError, ArithmeticError):
                pass
    if ctx.utilisable(c.nombre_articles):
        assert c.nombre_articles is not None
        try:
            n_art = c.nombre_articles.entier()
        except (ValueError, ArithmeticError):
            n_art = 0
        if 0 < n_art <= 999 and max(par_article) <= n_art:
            attendus.update(range(1, n_art + 1))
    if attendus - set(par_article):
        return "article_sans_ligne_de_taxation"
    for cat in (CategorieTaxe.droit, CategorieTaxe.tva):
        avec = [n for n, cats in par_article.items() if cat in cats]
        if len(avec) >= 2 and len(avec) < len(par_article):
            return "article_sans_ligne_de_sa_categorie"
    return None


# =====================================================================================================
# §12.2 — Montants refacturés, unités de comparaison
# =====================================================================================================


@dataclass
class LigneDebours:
    """Ligne de débours d'une facture transitaire affectée à une unité."""

    facture: Document
    index: int
    ligne: LigneFactureTransitaire
    valeur: ValeurSourcee | None
    montant: Decimal | None
    categorie: CategorieTaxe | None  # None : « droits et taxes » combinés
    raison: RaisonCode | None = None
    allocation: bool = False


@dataclass
class CreditAvoir:
    """Ligne de débours d'un avoir déjà reçu, déduite du montant refacturé (§12.2, §17.2)."""

    avoir: Document
    index: int
    valeur: ValeurSourcee
    montant: Decimal
    categorie: CategorieTaxe | None


@dataclass
class UniteC:
    """Unité de comparaison C1–C5 : facture(s) transitaire(s) × déclaration(s) (§12.2)."""

    factures: list[Document]
    declarations: list[Document]
    lignes: list[LigneDebours]
    credits: list[CreditAvoir] = field(default_factory=list)
    ventilation_incomplete: bool = False

    @property
    def cle(self) -> str:
        ids = [f.id for f in self.factures]
        return cle_unite(ft=ids[0] if len(ids) == 1 else ids, dec=[d.id for d in self.declarations])

    @property
    def document_ids(self) -> list[str]:
        return [f.id for f in self.factures] + [d.id for d in self.declarations]

    def lignes_categorie(self, cat: CategorieTaxe | None) -> list[LigneDebours]:
        return [x for x in self.lignes if x.categorie is cat]

    @property
    def a_combines(self) -> bool:
        return any(x.categorie is None for x in self.lignes)

    def inutilisables(self, cats: Iterable[CategorieTaxe | None] | None = None) -> list[LigneDebours]:
        cs = None if cats is None else set(cats)
        return [x for x in self.lignes if x.montant is None and (cs is None or x.categorie in cs)]

    def refacture(self, cat: CategorieTaxe | None) -> Decimal:
        return _somme(x.montant for x in self.lignes_categorie(cat) if x.montant is not None)

    def refacture_total(self) -> Decimal:
        return _somme(x.montant for x in self.lignes if x.montant is not None)

    def credit(self, cat: CategorieTaxe | None) -> Decimal:
        return _somme(c.montant for c in self.credits if c.categorie is cat)

    def credit_total(self) -> Decimal:
        return _somme(c.montant for c in self.credits)


def _montant_ligne(ctx: ControlContext, ligne: LigneFactureTransitaire) -> ValeurSourcee | None:
    """Montant d'une ligne : HT, à défaut TTC si aucune TVA n'est portée."""
    if ctx.utilisable(ligne.montant_ht):
        return ligne.montant_ht
    sans_tva = _dec(ctx, ligne.montant_tva) in (None, ZERO)
    if sans_tva and ctx.utilisable(ligne.montant_ttc):
        return ligne.montant_ttc
    return ligne.montant_ht or ligne.montant_ttc


def _mrn_cites(ctx: ControlContext, f: Document) -> list[ValeurSourcee]:
    ft = f.ft
    vals = list(ft.refs_mrn) + [t.mrn for t in ft.tableau_mrn if t.mrn is not None]
    vals += [ligne.mrn for ligne in ft.lignes if ligne.mrn is not None]
    return [v for v in vals if ctx.utilisable(v)]


def declarations_couvertes(ctx: ControlContext, f: Document) -> list[Document]:
    """Déclarations du dossier citées par la facture (MRN en en-tête, tableau ou lignes) ; toutes les
    déclarations du dossier si la facture n'en cite aucune."""
    decs = ctx.declarations()
    prefixes = {mrn_prefixe(v.valeur) for v in _mrn_cites(ctx, f)}
    cites = [d for d in decs if d.dec.mrn_prefixe and d.dec.mrn_prefixe in prefixes]
    return cites or decs


def _prefixes_autres_dossiers(ctx: ControlContext) -> set[str]:
    out: set[str] = set()
    for autre in ctx.autres_dossiers:
        for d in autre.documents.values():
            if d.champs is not None and getattr(d.champs, "type_document", None) == "declaration":
                p = d.dec.mrn_prefixe
                if p:
                    out.add(p)
    return out


def unites_c(ctx: ControlContext) -> list[UniteC]:
    """Unités de comparaison de §12.2.

    1. Chaque ligne de débours est affectée : par allocation explicite du dossier, sinon par le MRN qu'elle
       cite (préfixe), sinon à la seule déclaration couverte par la facture. Une ligne non ventilée d'une
       facture couvrant plusieurs déclarations fusionne ces déclarations en une unité (comparaison sur la
       somme). Une ligne citant le MRN d'une déclaration d'un autre dossier est écartée (relevé).
    2. Les factures qui portent des débours pour les mêmes déclarations sont additionnées (facture initiale
       et facture complémentaire, ou même déclaration refacturée deux fois : l'excédent apparaît en C5).
    3. Les avoirs du dossier qui citent une facture de l'unité (à défaut un MRN de l'unité) sont déduits,
       ligne de débours par ligne de débours.
    """
    decs = ctx.declarations()
    if not decs:
        return []
    par_prefixe = {d.dec.mrn_prefixe: d for d in decs if d.dec.mrn_prefixe}
    par_id = {d.id: d for d in decs}
    for d in ctx.declarations(dernieres_versions=False):
        p = d.dec.mrn_prefixe
        if p and p in par_prefixe:
            par_id.setdefault(d.id, par_prefixe[p])
    autres_prefixes = _prefixes_autres_dossiers(ctx)

    explicites: dict[str, list[LigneDebours]] = {d.id: [] for d in decs}
    globales: list[tuple[list[Document], LigneDebours, bool]] = []
    for f in ctx.factures_transitaires():
        lignes = [(i, lg) for i, lg in enumerate(f.ft.lignes) if lg.nature.est_debours]
        if not lignes:
            continue
        couvertes = declarations_couvertes(ctx, f)
        prefixes_cites = {mrn_prefixe(v.valeur) for v in _mrn_cites(ctx, f)}
        hors_dossier = bool(prefixes_cites - set(par_prefixe))
        for i, lg in lignes:
            v = _montant_ligne(ctx, lg)
            m = _dec(ctx, v)
            ld = LigneDebours(
                facture=f, index=i, ligne=lg, valeur=v, montant=m, categorie=_NATURE_CATEGORIE[lg.nature],
                raison=None if m is not None else ctx.raison_inutilisable(v),
            )
            allocs = [a for a in ctx.dossier.allocations if a.source_document_id == f.id and a.source_ligne == i]
            cibles = []
            for a in allocs:
                cible = par_id.get(a.cible_document_id or "") or par_prefixe.get(mrn_prefixe(a.mrn))
                if cible is not None:
                    montant = a.montant_alloue if a.montant_alloue is not None else m
                    cibles.append((cible, montant))
            if cibles:
                for cible, montant in cibles:
                    explicites[cible.id].append(replace(ld, montant=montant, allocation=True))
                continue
            if ctx.utilisable(lg.mrn):
                assert lg.mrn is not None
                p = mrn_prefixe(lg.mrn.valeur)
                d = par_prefixe.get(p)
                if d is not None:
                    explicites[d.id].append(ld)
                elif not f.ft.est_releve and p not in autres_prefixes and len(decs) == 1:
                    # MRN sans correspondance (sujet de C7) : la seule déclaration du dossier reste la cible.
                    explicites[decs[0].id].append(ld)
                continue
            if len(couvertes) == 1:
                explicites[couvertes[0].id].append(ld)
            else:
                globales.append((couvertes, ld, hors_dossier and f.ft.est_releve))

    # Union des déclarations couvertes par une même ligne non ventilée.
    parent = {d.id: d.id for d in decs}

    def racine(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for couvertes, _, _ in globales:
        r0 = racine(couvertes[0].id)
        for d in couvertes[1:]:
            parent[racine(d.id)] = r0

    groupes: dict[str, dict] = {}
    for d in decs:
        g = groupes.setdefault(racine(d.id), {"decs": [], "lignes": [], "incomplet": False})
        g["decs"].append(d)
        g["lignes"].extend(explicites[d.id])
    for couvertes, ld, incomplet in globales:
        g = groupes[racine(couvertes[0].id)]
        g["lignes"].append(ld)
        g["incomplet"] = g["incomplet"] or incomplet

    ordre = ctx.dossier.document_ids()
    unites: list[UniteC] = []
    for g in groupes.values():
        if not g["lignes"]:
            continue
        lignes = sorted(g["lignes"], key=lambda x: (ordre.index(x.facture.id), x.index))
        factures = list({x.facture.id: x.facture for x in lignes}.values())
        unites.append(UniteC(factures=factures, declarations=g["decs"], lignes=lignes,
                             ventilation_incomplete=g["incomplet"]))
    _imputer_avoirs(ctx, unites)
    return unites


def _imputer_avoirs(ctx: ControlContext, unites: list[UniteC]) -> None:
    vus: set[str] = set()
    for a in ctx.avoirs():
        num = norm_ref(a.av.numero.valeur) if a.av.numero is not None and a.av.numero.valeur else a.id
        if num in vus:  # même avoir reçu deux fois (E3) : imputé une seule fois
            continue
        vus.add(num)
        refs = [v.valeur for v in a.av.refs_facture_origine if ctx.utilisable(v)]
        if refs:
            cibles = [
                u for u in unites
                if any(f.ft.numero is not None and ref_compatibles(r, f.ft.numero.valeur)
                       for f in u.factures for r in refs)
            ]
        else:
            prefixes = {mrn_prefixe(v.valeur) for v in a.av.refs_mrn if ctx.utilisable(v)}
            cibles = [u for u in unites if any(d.dec.mrn_prefixe in prefixes for d in u.declarations)]
        if not cibles:
            continue
        for i, lg in enumerate(a.av.lignes):
            if not lg.nature.est_debours:
                continue
            v = _montant_ligne(ctx, lg)
            m = _dec(ctx, v)
            if m is None or v is None:
                continue
            cands = cibles
            if ctx.utilisable(lg.mrn):
                assert lg.mrn is not None
                p = mrn_prefixe(lg.mrn.valeur)
                cands = [u for u in cibles if any(d.dec.mrn_prefixe == p for d in u.declarations)]
            if len(cands) == 1:
                cands[0].credits.append(
                    CreditAvoir(avoir=a, index=i, valeur=v, montant=abs(m), categorie=_NATURE_CATEGORIE[lg.nature])
                )


def _donnees(ctx: ControlContext, cid: str) -> tuple[list[UniteC], dict[str, ReferenceDeclaration]] | list[
    ResultatControle
]:
    """Préalables communs de C1–C6 : facture transitaire présente, déclaration présente, débours refacturés."""
    if not ctx.factures_transitaires():
        return [ctx.non_applicable(cid, RaisonCode.facture_transitaire_absente)]
    if not ctx.declarations():
        return [ctx.non_verifiable(cid, RaisonCode.document_manquant)]
    unites = unites_c(ctx)
    if not unites:
        return [ctx.non_applicable(cid, RaisonCode.valeur_absente, details={"motif": "aucune_ligne_de_debours"})]
    refs = {d.id: reference_declaration(ctx, d) for d in ctx.declarations()}
    return unites, refs


def _tolerances(ctx: ControlContext, u: UniteC, refs: dict[str, ReferenceDeclaration]) -> tuple[Decimal, Decimal]:
    n = sum(refs[d.id].nb_articles for d in u.declarations)
    return ctx.tol.t_debours(n), ctx.tol.s_debours(n)


def _confusions(lignes: Iterable[ValeurSourcee], sources: Iterable[ValeurSourcee], ecart: Decimal,
                tol: Decimal) -> list[Confusion]:
    """Test de confusion (§8.5.4) sur chaque opérande d'une somme : une variante de lecture d'une ligne
    refacturée (signe +) ou d'une ligne de taxation (signe −) ramène-t-elle l'écart dans la tolérance ?"""

    def cand(v: ValeurSourcee, signe: int) -> Confusion:
        d = v.decimal_signe()
        return Confusion(v, accepte=lambda x: abs(ecart - signe * d + signe * x) <= tol)

    return [cand(v, 1) for v in lignes] + [cand(v, -1) for v in sources]


def _texte_avoirs(credits: Sequence[CreditAvoir]) -> str:
    if not credits:
        return ""
    total = _somme(c.montant for c in credits)
    nums = list(dict.fromkeys(_numero(c.avoir) for c in credits))
    return f", après déduction de {format_montant(total)} d'avoir déjà reçu ({', '.join(nums)})"


def _preuves_lignes(lignes: Iterable[LigneDebours]) -> list:
    return [preuve(x.valeur, RolePreuve.valeur_b) for x in lignes if x.valeur is not None]


def _preuves_sources(vals: Iterable[ValeurSourcee]) -> list:
    return [preuve(v, RolePreuve.valeur_a) for v in vals]


def _explication_version(
    ctx: ControlContext,
    u: UniteC,
    refs: dict[str, ReferenceDeclaration],
    valeur: Callable[[ReferenceDeclaration], Decimal | None],
    refacture: Decimal,
    tol: Decimal,
) -> RaisonCode | None:
    """§8.5.1 condition 7 : une version antérieure de la déclaration expliquerait l'écart."""
    base = [valeur(refs[d.id]) for d in u.declarations]
    if any(b is None for b in base):
        return None
    total = _somme(b for b in base if b is not None)
    for i, d in enumerate(u.declarations):
        for ancienne in ctx.versions_anterieures(d):
            alt = valeur(reference_declaration(ctx, ancienne))
            if alt is None:
                continue
            b = base[i]
            assert b is not None
            if abs(refacture - (total - b + alt)) <= tol:
                return RaisonCode.version_rectificative
    return None


# =====================================================================================================
# C1, C2, C4 — comparaison par composante
# =====================================================================================================


def _comparer_composante(
    ctx: ControlContext, cid: str, cat: CategorieTaxe, u: UniteC, refs: dict[str, ReferenceDeclaration]
) -> ResultatControle:
    unite = u.cle
    docs = u.document_ids
    details: dict = {"categorie": cat.value, "declarations": [d.id for d in u.declarations],
                     "factures": [f.id for f in u.factures]}

    def nv(raison: RaisonCode, motif: str) -> ResultatControle:
        return ctx.non_verifiable(cid, raison, unite=unite, documents=docs, details={**details, "motif": motif})

    if u.ventilation_incomplete:
        return nv(RaisonCode.valeur_absente, "ventilation_par_mrn_absente")
    lignes = u.lignes_categorie(cat)
    inut = u.inutilisables([cat, None])
    if inut:
        return nv(inut[0].raison or RaisonCode.valeur_absente, "ligne_de_debours_illisible")
    if u.a_combines and (cat is not CategorieTaxe.tva or not lignes):
        return nv(RaisonCode.valeur_absente, "debours_combines_sans_ventilation")
    for d in u.declarations:
        raison = refs[d.id].indisponibles.get(cat)
        if raison is not None:
            return nv(raison, "composante_de_la_declaration_indisponible")
    if (
        cat is CategorieTaxe.droit
        and lignes
        and not u.lignes_categorie(CategorieTaxe.forfait_petits_envois)
        and all(CategorieTaxe.droit in refs[d.id].sans_ligne
                and CategorieTaxe.forfait_petits_envois not in refs[d.id].sans_ligne for d in u.declarations)
    ):
        # G4 : le transitaire refacture en « droits » le seul droit forfaitaire liquidé.
        return ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle, unite=unite, documents=docs,
                                  details={**details, "couvert_par": "G4"})

    brut = u.refacture(cat)
    credits = [c for c in u.credits if c.categorie is cat]
    refact = brut - u.credit(cat)
    liq = _somme(refs[d.id].liquide[cat] for d in u.declarations)
    sources = [v for d in u.declarations for v in refs[d.id].sources[cat]]
    ecart = refact - liq
    tol, seuil = _tolerances(ctx, u, refs)
    vals_lignes = [x.valeur for x in lignes if x.valeur is not None]
    commun = dict(
        unite=unite,
        entrees={f"refacture_{i}": v for i, v in enumerate(vals_lignes)} | {f"liquide_{i}": v for i, v in
                                                                             enumerate(sources)},
        attendu=arrondi_centime(liq), constate=arrondi_centime(refact), ecart=arrondi_centime(ecart),
        tolerance=tol, seuil_certitude=seuil, documents=docs, details=details,
    )
    if abs(ecart) <= tol:
        return ctx.conforme(cid, **commun)
    manquant = _somme(refs[d.id].manquant for d in u.declarations)
    if manquant > 0 and tol < ecart <= manquant + tol:
        # Le total à payer imprimé contient des montants non retrouvés dans les lignes lues : une ligne de
        # cette composante non extraite expliquerait l'excédent (§12.1, « comparaisons concernées » ; D-705).
        return nv(RaisonCode.valeur_absente, "ecart_explicable_par_une_ligne_de_taxation_non_lue")

    raisons = []
    if any(cat in refs[d.id].sans_ligne and not refs[d.id].complet_verifie for d in u.declarations):
        raisons.append(RaisonCode.valeur_absente)
    incompletes = {d.id: refs[d.id].lecture_incomplete for d in u.declarations if refs[d.id].lecture_incomplete}
    if incompletes:
        # D-901 : la somme des lignes lues n'est pas confirmée par le total imprimé (ou une ligne d'article
        # semble manquer) ; une ligne non lue de cette composante peut expliquer l'écart.
        raisons.append(RaisonCode.valeur_absente)
        details["lecture_incomplete"] = incompletes
    classement = ctx.classify(
        cid, ecart=ecart, tolerance=tol, seuil_certitude=seuil,
        valeurs_cles=vals_lignes + sources + [c.valeur for c in credits],
        confusion=_confusions(vals_lignes, sources, ecart, tol),
        documents=docs + [c.avoir.id for c in credits],
        explication=_explication_version(ctx, u, refs, lambda r: None if cat in r.indisponibles else r.liquide[cat],
                                         refact, tol),
        montant=ecart, raisons_supplementaires=raisons,
    )
    nom = _NOM_CATEGORIE[cat]
    if sources:
        ref_txt = (f"indique comme montant liquidé pour {nom} {format_montant(liq)}"
                   f"{_entre_parentheses(str(len(sources)) + ' ' + _accord(len(sources), 'ligne', 'lignes') + ' de taxation', page_txt(sources))}")
    else:
        ref_txt = f"n'indique aucun montant liquidé pour {nom} (aucune ligne de taxation de cette catégorie)"
    libelle = (
        f"{libelle_facture(u.factures)}{_entre_parentheses(page_txt(vals_lignes))} "
        f"{_accord(len(u.factures), 'refacture', 'refacturent')} {format_montant(refact)} "
        f"{_REFACTURE_CATEGORIE[cat]}{_texte_avoirs(credits)} ; {_libelle_declarations(u.declarations)} {ref_txt}. "
        f"Écart constaté entre les documents : {format_montant(arrondi_centime(ecart))} "
        f"(tolérance appliquée : {format_montant(tol)})."
    )
    return ctx.constat(
        cid, classement, libelle=libelle,
        prochaine_action=ACTION_C if ecart > 0 else ACTION_C_FAVEUR,
        montant=ecart, montant_brut=(brut - liq) if credits else None, composante=_COMPOSANTE[cat],
        preuves=_preuves_lignes(lignes) + _preuves_sources(sources)
        + [preuve(c.valeur, RolePreuve.contexte) for c in credits],
        **commun,
    )


def _composante(ctx: ControlContext, cid: str, cat: CategorieTaxe) -> list[ResultatControle]:
    d = _donnees(ctx, cid)
    if isinstance(d, list):
        return d
    unites, refs = d
    out = []
    for u in unites:
        if cat is CategorieTaxe.tva:
            autos = [x for x in u.declarations if refs[x.id].autoliquide]
            if len(autos) == len(u.declarations):
                out.append(ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle, unite=u.cle,
                                              documents=u.document_ids, details={"couvert_par": "C3"}))
                continue
        out.append(_comparer_composante(ctx, cid, cat, u, refs))
    return out


@control("C1")
def c1_droits(ctx: ControlContext) -> list[ResultatControle]:
    """C1 — Droits de douane refacturés contre droits liquidés (§12, ``T_DEBOURS`` / ``S_DEBOURS``)."""
    return _composante(ctx, "C1", CategorieTaxe.droit)


@control("C2")
def c2_autres_taxes(ctx: ControlContext) -> list[ResultatControle]:
    """C2 — Autres taxes refacturées contre autres taxes liquidées."""
    return _composante(ctx, "C2", CategorieTaxe.autre_taxe)


@control("C4")
def c4_tva(ctx: ControlContext) -> list[ResultatControle]:
    """C4 — TVA refacturée contre TVA liquidée (déclarations sans indice d'autoliquidation ; sinon C3)."""
    return _composante(ctx, "C4", CategorieTaxe.tva)


# =====================================================================================================
# C3 — TVA refacturée alors que la déclaration indique l'autoliquidation
# =====================================================================================================


@control("C3")
def c3_tva_autoliquidee(ctx: ControlContext) -> list[ResultatControle]:
    """C3 — ``autoliquide[d]`` et ``refacture[tva] > T_DEBOURS`` -> constat ; montant = TVA refacturée.

    Le texte constate ce que la déclaration indique ; il ne dit jamais si l'autoliquidation était
    applicable. TVA autoliquidée non refacturée : ``conforme`` (aucun constat).
    """
    d = _donnees(ctx, "C3")
    if isinstance(d, list):
        return d
    unites, refs = d
    out = []
    for u in unites:
        unite, docs = u.cle, u.document_ids
        autos = [x for x in u.declarations if refs[x.id].autoliquide]
        details: dict = {"declarations": [x.id for x in u.declarations], "factures": [f.id for f in u.factures]}
        if not autos:
            out.append(ctx.non_applicable("C3", RaisonCode.couvert_par_autre_controle, unite=unite, documents=docs,
                                          details={**details, "couvert_par": "C4"}))
            continue
        lignes = u.lignes_categorie(CategorieTaxe.tva)
        motif = None
        if len(autos) != len(u.declarations) or u.ventilation_incomplete:
            motif = "ventilation_par_mrn_absente"
        elif u.inutilisables([CategorieTaxe.tva, None]):
            motif = "ligne_de_debours_illisible"
        elif u.a_combines and not lignes:
            motif = "debours_combines_sans_ventilation"
        if motif is not None:
            out.append(ctx.non_verifiable("C3", RaisonCode.valeur_absente, unite=unite, documents=docs,
                                          details={**details, "motif": motif}))
            continue
        tol, seuil = _tolerances(ctx, u, refs)
        credits = [c for c in u.credits if c.categorie is CategorieTaxe.tva]
        brut = u.refacture(CategorieTaxe.tva)
        refact = brut - u.credit(CategorieTaxe.tva)
        vals = [x.valeur for x in lignes if x.valeur is not None]
        indice, description = refs[autos[0].id].indices[0]
        for x in autos[1:]:
            if refs[x.id].indices[0][0].confiance < indice.confiance:
                indice, description = refs[x.id].indices[0]
        commun = dict(
            unite=unite, entrees={"indice": indice} | {f"refacture_{i}": v for i, v in enumerate(vals)},
            attendu=ZERO, constate=arrondi_centime(refact), ecart=arrondi_centime(refact), tolerance=tol,
            seuil_certitude=seuil, documents=docs, details=details,
        )
        if refact <= tol:
            out.append(ctx.conforme("C3", **commun))
            continue
        classement = ctx.classify(
            "C3", ecart=refact, tolerance=tol, seuil_certitude=seuil, valeurs_cles=[*vals, indice,
                                                                                   *(c.valeur for c in credits)],
            confusion=_confusions(vals, [], refact, tol), documents=docs + [c.avoir.id for c in credits],
            montant=refact,
        )
        cette = "cette déclaration" if len(u.declarations) == 1 else "ces déclarations"
        libelle = (
            f"{libelle_facture(u.factures)}{_entre_parentheses(page_txt(vals))} "
            f"{_accord(len(u.factures), 'refacture', 'refacturent')} {format_montant(refact)} de TVA à "
            f"l'importation{_texte_avoirs(credits)} ; pour {cette} "
            f"({', '.join(_mrn(x) for x in u.declarations)}), la TVA est indiquée comme autoliquidée"
            f"{_entre_parentheses(description, page_txt([indice]))}."
        )
        out.append(ctx.constat(
            "C3", classement, libelle=libelle, prochaine_action=ACTION_C3, montant=refact,
            montant_brut=brut if credits else None, composante=Composante.tva,
            preuves=_preuves_lignes(lignes) + [preuve(indice, RolePreuve.valeur_a)]
            + [preuve(c.valeur, RolePreuve.contexte) for c in credits],
            **commun,
        ))
    return out


# =====================================================================================================
# C5 — Total des débours
# =====================================================================================================


def _c3_declenche(ctx: ControlContext, unite: str) -> bool:
    return any(r.outcome.est_constat for r in ctx.anterieurs("C3", unite=unite))


@control("C5")
def c5_total_debours(ctx: ControlContext) -> list[ResultatControle]:
    """C5 — ``Σ refacture − liquide_total`` (débours combinés inclus), exécuté pour chaque unité.

    - Si C3 se déclenche pour l'unité, la part TVA refacturée est retirée (pas de double comptage, §8.6).
    - Si l'unité refacture le forfait petits envois sur des lignes distinctes, ce forfait est retiré des
      deux côtés (comparé par G4).
    - Le moteur retire le montant (``doublon_composantes``) quand C1, C2 et C3/C4 sont tous évaluables.
    """
    d = _donnees(ctx, "C5")
    if isinstance(d, list):
        return d
    unites, refs = d
    out = []
    for u in unites:
        unite, docs = u.cle, u.document_ids
        details: dict = {"declarations": [x.id for x in u.declarations], "factures": [f.id for f in u.factures]}
        if u.ventilation_incomplete:
            out.append(ctx.non_verifiable("C5", RaisonCode.valeur_absente, unite=unite, documents=docs,
                                          details={**details, "motif": "ventilation_par_mrn_absente"}))
            continue
        inut = u.inutilisables()
        if inut:
            out.append(ctx.non_verifiable("C5", inut[0].raison or RaisonCode.valeur_absente, unite=unite,
                                          documents=docs, details={**details, "motif": "ligne_de_debours_illisible"}))
            continue
        manquante = next((refs[x.id] for x in u.declarations if refs[x.id].liquide_total is None), None)
        if manquante is not None:
            out.append(ctx.non_verifiable("C5", manquante.raison_total or RaisonCode.valeur_absente, unite=unite,
                                          documents=docs, details={**details, "motif": "total_liquide_indisponible"}))
            continue
        exclues: set[CategorieTaxe] = set()
        if _c3_declenche(ctx, unite):
            exclues.add(CategorieTaxe.tva)
            details["tva_exclue"] = "C3"
        # Le forfait n'est retiré des deux côtés que si chaque déclaration en porte une ligne lue ; sinon le
        # retirer de la seule facture fausserait la comparaison (le total liquidé l'inclut) — D-711.
        forfait_separe = bool(u.lignes_categorie(CategorieTaxe.forfait_petits_envois)) and all(
            CategorieTaxe.forfait_petits_envois not in refs[x.id].sans_ligne
            and CategorieTaxe.forfait_petits_envois not in refs[x.id].indisponibles for x in u.declarations)
        if forfait_separe:
            exclues.add(CategorieTaxe.forfait_petits_envois)
            details["forfait_exclu"] = "G4"
        lignes = [x for x in u.lignes if x.categorie not in exclues]
        credits = [c for c in u.credits if c.categorie not in exclues]
        brut = _somme(x.montant for x in lignes if x.montant is not None)
        refact = brut - _somme(c.montant for c in credits)
        liq = ZERO
        sources: list[ValeurSourcee] = []
        for x in u.declarations:
            r = refs[x.id]
            assert r.liquide_total is not None
            liq += r.liquide_total
            if forfait_separe:
                liq -= r.liquide[CategorieTaxe.forfait_petits_envois]
            forfaits = {id(v) for v in r.sources[CategorieTaxe.forfait_petits_envois]} if forfait_separe else set()
            sources.extend(v for v in r.valeurs_total() if id(v) not in forfaits)
        ecart = refact - liq
        tol, seuil = _tolerances(ctx, u, refs)
        vals = [x.valeur for x in lignes if x.valeur is not None]
        commun = dict(
            unite=unite,
            entrees={f"refacture_{i}": v for i, v in enumerate(vals)} | {f"liquide_{i}": v for i, v in
                                                                         enumerate(sources)},
            attendu=arrondi_centime(liq), constate=arrondi_centime(refact), ecart=arrondi_centime(ecart),
            tolerance=tol, seuil_certitude=seuil, documents=docs, details=details,
        )
        if abs(ecart) <= tol:
            out.append(ctx.conforme("C5", **commun))
            continue

        def total_ref(r: ReferenceDeclaration, fs: bool = forfait_separe) -> Decimal | None:
            if r.liquide_total is None:
                return None
            return r.liquide_total - (r.liquide[CategorieTaxe.forfait_petits_envois] if fs else ZERO)

        # D-901 : total liquidé fondé sur la somme des lignes d'une déclaration dont la lecture semble
        # incomplète -> au plus « à vérifier » (le total imprimé, quand il est retenu, fait foi).
        incompletes = {x.id: refs[x.id].lecture_incomplete for x in u.declarations
                       if refs[x.id].lecture_incomplete and not refs[x.id].total_utilise}
        if incompletes:
            details["lecture_incomplete"] = incompletes
        classement = ctx.classify(
            "C5", ecart=ecart, tolerance=tol, seuil_certitude=seuil,
            valeurs_cles=vals + sources + [c.valeur for c in credits],
            confusion=_confusions(vals, sources, ecart, tol), documents=docs + [c.avoir.id for c in credits],
            explication=_explication_version(ctx, u, refs, total_ref, refact, tol), montant=ecart,
            raisons_supplementaires=[RaisonCode.valeur_absente] if incompletes else (),
        )
        composition = []
        for cat in (*CATEGORIES, None):
            if cat in exclues:
                continue
            m = u.refacture(cat)
            if m:
                nom = "droits et taxes combinés" if cat is None else _NOM_CATEGORIE[cat].split(" ", 1)[1]
                composition.append(f"{nom} : {format_montant(m)}")
        sources_txt = ("total à payer imprimé" if any(refs[x.id].total_utilise for x in u.declarations)
                       else "somme des lignes de taxation")
        exclusion = ""
        if CategorieTaxe.tva in exclues:
            exclusion += ", hors TVA refacturée relevée par le contrôle C3"
        if forfait_separe:
            exclusion += ", hors droit forfaitaire petits envois comparé séparément"
        libelle = (
            f"{libelle_facture(u.factures)} {_accord(len(u.factures), 'refacture', 'refacturent')} au total "
            f"{format_montant(refact)} de débours{_entre_parentheses(' ; '.join(composition), page_txt(vals))}"
            f"{exclusion}{_texte_avoirs(credits)} ; {_libelle_declarations(u.declarations)} "
            f"{_accord(len(u.declarations), 'indique', 'indiquent')} un total liquidé de {format_montant(liq)}"
            f"{_entre_parentheses(sources_txt, page_txt(sources))}. Écart constaté entre les documents : "
            f"{format_montant(arrondi_centime(ecart))} (tolérance appliquée : {format_montant(tol)})."
        )
        out.append(ctx.constat(
            "C5", classement, libelle=libelle, prochaine_action=ACTION_C if ecart > 0 else ACTION_C_FAVEUR,
            montant=ecart, montant_brut=(brut - liq) if credits else None,
            preuves=_preuves_lignes(lignes) + _preuves_sources(sources)
            + [preuve(c.valeur, RolePreuve.contexte) for c in credits],
            **commun,
        ))
    return out


# =====================================================================================================
# Excédent de débours, assiette des frais d'avance de fonds (C6, D4)
# =====================================================================================================


def _categories_base(base: BasePourcentage | None) -> set[CategorieTaxe | None]:
    """Composantes de débours comprises dans l'assiette d'un pourcentage (``None`` = combinés)."""
    if base is BasePourcentage.debours_hors_tva:
        return {CategorieTaxe.droit, CategorieTaxe.autre_taxe, CategorieTaxe.forfait_petits_envois, None}
    if base is BasePourcentage.droits:
        return {CategorieTaxe.droit}
    if base is BasePourcentage.droits_et_autres_taxes:
        return {CategorieTaxe.droit, CategorieTaxe.autre_taxe, None}
    if base is BasePourcentage.tva:
        return {CategorieTaxe.tva}
    return {*CATEGORIES, None}


def assiette_debours(u: UniteC, base: BasePourcentage | None) -> Decimal:
    """Débours refacturés (bruts, avant avoirs) de l'unité compris dans l'assiette."""
    cats = _categories_base(base)
    return _somme(x.montant for x in u.lignes if x.categorie in cats and x.montant is not None)


def excedent_debours(u: UniteC, refs: dict[str, ReferenceDeclaration], base: BasePourcentage | None) -> Decimal | None:
    """Excédent (positif seulement) des débours refacturés de l'unité sur la référence, restreint aux
    composantes de l'assiette ; ``None`` si la référence n'est pas calculable."""
    cats = _categories_base(base)
    refact = _somme(x.montant for x in u.lignes if x.categorie in cats and x.montant is not None)
    if u.inutilisables(cats):
        return None
    if cats >= {*CATEGORIES, None}:
        totals = [refs[d.id].liquide_total for d in u.declarations]
        if any(t is None for t in totals):
            return None
        liq = _somme(t for t in totals if t is not None)
    else:
        liq = ZERO
        for d in u.declarations:
            r = refs[d.id]
            if any(k in r.indisponibles for k in cats if k is not None):
                return _excedent_hors_tva_autoliquidee(u, refs, cats)
            liq += _somme(r.liquide[k] for k in cats if k is not None)
    return max(ZERO, refact - liq)


def _excedent_hors_tva_autoliquidee(
    u: UniteC, refs: dict[str, ReferenceDeclaration], cats: set[CategorieTaxe | None]
) -> Decimal | None:
    """Assiette « débours hors TVA » quand une composante de la déclaration n'est pas ventilée (ligne de
    catégorie inconnue) : si la TVA de chaque déclaration est autoliquidée (référence TVA nulle, §12.1) et
    qu'aucune TVA n'est refacturée, l'excédent hors TVA est l'excédent total (D-702). Sinon ``None``."""
    if {*CATEGORIES} - {k for k in cats if k is not None} != {CategorieTaxe.tva}:
        return None
    if u.lignes_categorie(CategorieTaxe.tva) or u.inutilisables():
        return None
    totals = []
    for d in u.declarations:
        r = refs[d.id]
        if not r.autoliquide or r.liquide_total is None:
            return None
        totals.append(r.liquide_total)
    return max(ZERO, u.refacture_total() - _somme(totals))


def unites_pour_facture(ctx: ControlContext, f: Document, unites: Sequence[UniteC]) -> list[UniteC]:
    """Unités de débours auxquelles se rapporte une ligne de prestation de la facture ``f`` : celles qui
    contiennent ``f``, sinon celles des déclarations couvertes par ``f`` (facture de prestations séparée
    de la facture de débours pour un même MRN)."""
    propres = [u for u in unites if any(x.id == f.id for x in u.factures)]
    if propres:
        return propres
    couvertes = {d.id for d in declarations_couvertes(ctx, f)}
    return [u for u in unites if any(d.id in couvertes for d in u.declarations)]


def _est_declaration(d: Document) -> bool:
    return d.champs is not None and getattr(d.champs, "type_document", None) == "declaration"


def dossiers_freres(ctx: ControlContext, document_id: str) -> list[str]:
    """Identifiants des autres dossiers qui contiennent le même document (relevé ou facture mensuelle
    rattaché à plusieurs dossiers, §7.5 ; D-202)."""
    return sorted(a.dossier.id for a in ctx.autres_dossiers if document_id in a.documents)


def dossier_principal(ctx: ControlContext, document_id: str) -> bool:
    """Vrai si ce dossier est celui (premier identifiant) qui porte les contrôles **de niveau document** d'un
    document partagé entre plusieurs dossiers : un même fait n'est signalé qu'une fois (D-701)."""
    return all(ctx.dossier.id < x for x in dossiers_freres(ctx, document_id))


def ligne_hors_dossier(ctx: ControlContext, f: Document, ligne: LigneFactureTransitaire) -> bool:
    """La ligne cite le MRN d'une déclaration absente de ce dossier mais présente dans un autre dossier qui
    contient la même facture : elle relève de cet autre dossier (relevé réparti, D-202, D-701)."""
    if not ctx.utilisable(ligne.mrn):
        return False
    assert ligne.mrn is not None
    p = mrn_prefixe(ligne.mrn.valeur)
    if not p or any(d.dec.mrn_prefixe == p for d in ctx.declarations(dernieres_versions=False)):
        return False
    return any(
        f.id in a.documents and any(_est_declaration(d) and d.dec.mrn_prefixe == p for d in a.documents.values())
        for a in ctx.autres_dossiers
    )


def ligne_evaluee_ici(ctx: ControlContext, f: Document, ligne: LigneFactureTransitaire) -> bool:
    """Une ligne d'une facture partagée entre dossiers est évaluée une seule fois : dans le dossier de la
    déclaration dont elle cite le MRN ; à défaut (aucun MRN du dossier cité), dans le dossier principal."""
    if ligne_hors_dossier(ctx, f, ligne):
        return False
    if ctx.utilisable(ligne.mrn):
        assert ligne.mrn is not None
        p = mrn_prefixe(ligne.mrn.valeur)
        if any(d.dec.mrn_prefixe == p for d in ctx.declarations(dernieres_versions=False)):
            return True
    return dossier_principal(ctx, f.id)


def declarations_de_ligne(ctx: ControlContext, f: Document, ligne: LigneFactureTransitaire) -> list[Document]:
    """Déclarations auxquelles se rapporte une ligne de prestation (assiette d'un FAF, nombre d'articles) :
    la déclaration dont la ligne cite le MRN ; à défaut, les déclarations couvertes par la facture
    (§12.2 : une facture qui ne ventile pas couvre la somme de ses déclarations). Liste vide si la ligne
    relève d'un autre dossier."""
    if ligne_hors_dossier(ctx, f, ligne):
        return []
    if ctx.utilisable(ligne.mrn):
        assert ligne.mrn is not None
        p = mrn_prefixe(ligne.mrn.valeur)
        cites = [d for d in ctx.declarations() if d.dec.mrn_prefixe == p]
        if cites:
            return cites
        # MRN de la ligne sans déclaration dans le dossier : sur une facture qui cite plusieurs MRN, la ligne
        # se rapporte à un autre envoi (déclaration absente ou mal lue) ; on ne la rapporte pas aux autres.
        if len({mrn_prefixe(v.valeur) for v in _mrn_cites(ctx, f)}) > 1:
            return []
        return declarations_couvertes(ctx, f)
    # Ligne non ventilée d'une facture qui cite aussi des MRN absents du dossier : elle couvre des envois
    # d'autres dossiers ; aucune déclaration du dossier n'en représente seule l'assiette.
    ici = {d.dec.mrn_prefixe for d in ctx.declarations(dernieres_versions=False) if d.dec.mrn_prefixe}
    if {mrn_prefixe(v.valeur) for v in _mrn_cites(ctx, f)} - ici:
        return []
    return declarations_couvertes(ctx, f)


def unites_pour_ligne(
    ctx: ControlContext, f: Document, ligne: LigneFactureTransitaire, unites: Sequence[UniteC]
) -> list[UniteC]:
    """Unités de débours d'une ligne de prestation (FAF) : celles de ``unites_pour_facture`` restreintes aux
    déclarations de la ligne (``declarations_de_ligne``). Sur un relevé ventilé par MRN, le FAF de chaque
    envoi est calculé sur les débours de son seul MRN (D-701)."""
    decs = {d.id for d in declarations_de_ligne(ctx, f, ligne)}
    if not decs:
        return []
    propres = [u for u in unites_pour_facture(ctx, f, unites) if any(d.id in decs for d in u.declarations)]
    if propres:
        return propres
    return [u for u in unites if any(d.id in decs for d in u.declarations)]


def grille_pour_facture(ctx: ControlContext, f: Document) -> GrilleTarifaire | None:
    """Grille **validée** applicable à la facture : transitaire du dossier, sinon émetteur reconnu par
    son numéro de TVA puis par son nom ou un alias ; valide à la date de la facture (§13)."""
    tid = ctx.dossier.transitaire_id
    if tid is None:
        em = f.ft.emetteur
        tva = normalize_vat(em.tva.valeur) if ctx.utilisable(em.tva) and em.tva is not None else None
        for t in ctx.transitaires:
            if tva and t.tva and normalize_vat(t.tva) == tva:
                tid = t.id
                break
        if tid is None and ctx.utilisable(em.nom) and em.nom is not None:
            nom = cle_texte(em.nom.valeur or "")
            candidats = [
                t.id for t in ctx.transitaires
                if any(a and (cle_texte(a) == nom or f" {cle_texte(a)} " in f" {nom} ") for a in [t.nom, *t.alias])
            ]
            if len(set(candidats)) == 1:
                tid = candidats[0]
    if tid is None:
        return None
    le = None
    if ctx.utilisable(f.ft.date) and f.ft.date is not None:
        try:
            le = f.ft.date.date_iso()
        except ValueError:
            le = None
    grilles = ctx.grilles_applicables(tid, le)
    if not grilles:
        return None
    return max(grilles, key=lambda g: (g.version, g.valide_du.isoformat() if g.valide_du else "", g.id))


def poste_faf(grille: GrilleTarifaire | None) -> PosteGrille | None:
    if grille is None:
        return None
    postes = [p for p in grille.postes if p.nature is NatureLigne.frais_avance_fonds]
    return postes[0] if len(postes) == 1 else None


def borner(x: Decimal, minimum: Decimal | None, maximum: Decimal | None) -> Decimal:
    if minimum is not None and x < minimum:
        x = minimum
    if maximum is not None and x > maximum:
        x = maximum
    return x


# =====================================================================================================
# C6 — Frais d'avance de fonds calculés sur des débours en écart
# =====================================================================================================


def _dependance(ctx: ControlContext, unites: Sequence[UniteC]) -> tuple[bool, list[RaisonCode]]:
    """Le constat de débours dont dépend C6 est-il ``ecart_certain`` ? (C5, à défaut C1–C4.)"""
    certain = True
    raisons: list[RaisonCode] = []
    for u in unites:
        rs = [r for cid in ("C5", "C1", "C2", "C3", "C4") for r in ctx.anterieurs(cid, unite=u.cle)
              if r.constat is not None and (r.ecart or ZERO) > 0]
        if not any(r.constat is not None and r.constat.niveau is Niveau.ecart_certain for r in rs):
            certain = False
            for r in rs:
                assert r.constat is not None
                raisons.extend(r.constat.raisons)
    return certain, raisons


@control("C6")
def c6_faf_sur_excedent(ctx: ControlContext) -> list[ResultatControle]:
    """C6 — Frais d'avance de fonds calculés sur l'excédent de débours (§12, C6).

    ``excedent_faf = FAF(assiette facturée) − FAF(assiette sans l'excédent)``, borné par le minimum et le
    maximum de la grille, et par le FAF facturé (FAF au minimum : excédent nul). Taux : grille validée,
    sinon pourcentage imprimé sur la ligne. Unité : la ligne FAF (``cle_unite(ft=…, ligne=…)``).
    """
    d = _donnees(ctx, "C6")
    if isinstance(d, list):
        return d
    unites, refs = d
    out = []
    lignes_faf = [(f, i, lg) for f in ctx.factures_transitaires() for i, lg in enumerate(f.ft.lignes)
                  if lg.nature is NatureLigne.frais_avance_fonds]
    if not lignes_faf:
        return [ctx.non_applicable("C6", RaisonCode.valeur_absente, details={"motif": "aucune_ligne_faf"})]
    for f, i, lg in lignes_faf:
        unite = cle_unite(ft=f.id, ligne=i)
        if not ligne_evaluee_ici(ctx, f, lg):
            out.append(ctx.non_applicable("C6", RaisonCode.couvert_par_autre_controle, unite=unite, documents=[f.id],
                                          details={"motif": "ligne_evaluee_dans_un_autre_dossier"}))
            continue
        concernees = unites_pour_ligne(ctx, f, lg, unites)
        docs = [f.id] + [x for u in concernees for x in u.document_ids if x != f.id]
        details: dict = {"unites_debours": [u.cle for u in concernees]}
        v_faf = _montant_ligne(ctx, lg)
        faf = _dec(ctx, v_faf)
        if faf is None:
            out.append(ctx.non_verifiable("C6", ctx.raison_inutilisable(v_faf), unite=unite, documents=docs,
                                          details=details))
            continue
        if not concernees:
            out.append(ctx.non_verifiable("C6", RaisonCode.valeur_absente, unite=unite, documents=docs,
                                          details={**details, "motif": "aucun_debours_rattache"}))
            continue
        grille = grille_pour_facture(ctx, f)
        poste = poste_faf(grille)
        minimum = maximum = None
        v_taux: ValeurSourcee | None = None
        base: BasePourcentage | None = None
        if poste is not None and poste.mode is ModePoste.pourcentage and poste.pourcentage is not None:
            taux, minimum, maximum, base = poste.pourcentage, poste.minimum, poste.maximum, poste.base_pourcentage
            details["taux_source"] = "grille"
        elif ctx.utilisable(lg.pourcentage):
            assert lg.pourcentage is not None
            v_taux, taux = lg.pourcentage, lg.pourcentage.decimal()
            details["taux_source"] = "ligne"
        else:
            out.append(ctx.non_verifiable("C6", RaisonCode.valeur_absente, unite=unite, documents=docs,
                                          details={**details, "motif": "taux_faf_inconnu"}))
            continue
        excedents = [excedent_debours(u, refs, base) for u in concernees]
        if any(e is None for e in excedents):
            out.append(ctx.non_verifiable("C6", RaisonCode.valeur_absente, unite=unite, documents=docs,
                                          details={**details, "motif": "excedent_non_calculable"}))
            continue
        excedent = _somme(e for e in excedents if e is not None)
        assiette = _somme(assiette_debours(u, base) for u in concernees)
        sur_facture = borner(taux * assiette / _CENT, minimum, maximum)
        corrige = borner(taux * (assiette - excedent) / _CENT, minimum, maximum)
        excedent_faf = arrondi_centime(min(sur_facture - corrige, max(ZERO, faf - corrige)))
        details |= {"excedent_debours": str(arrondi_centime(excedent)), "assiette": str(arrondi_centime(assiette))}
        tol = ctx.tol.t_tarif()
        seuil = ctx.tol.s_debours()
        commun = dict(unite=unite, entrees={"faf": v_faf} | ({"taux": v_taux} if v_taux else {}),
                      attendu=arrondi_centime(faf - excedent_faf), constate=faf, ecart=excedent_faf, tolerance=tol,
                      seuil_certitude=seuil, documents=docs, details=details)
        if excedent_faf <= tol:
            out.append(ctx.conforme("C6", **commun))
            continue
        certain, raisons_dep = _dependance(ctx, concernees)
        assert v_faf is not None
        classement = ctx.classify(
            "C6", ecart=excedent_faf, tolerance=tol, seuil_certitude=seuil,
            valeurs_cles=[v_faf] + ([v_taux] if v_taux else []), documents=docs, montant=excedent_faf,
            raisons_supplementaires=[] if certain else (raisons_dep or [RaisonCode.confiance_insuffisante]),
        )
        source_taux = (f"taux de la grille tarifaire validée {grille.reference}" if v_taux is None and grille
                       else "taux imprimé sur la ligne")
        libelle = (
            f"{libelle_facture([f])} facture {format_montant(faf)} de frais d'avance de fonds"
            f"{_entre_parentheses(page_txt([v_faf]))}, calculés au {source_taux} ({format_pourcentage(taux)}) "
            f"sur des débours qui dépassent de {format_montant(arrondi_centime(excedent))} les montants liquidés "
            f"indiqués sur la déclaration. Sur cet excédent seulement, ces frais représentent "
            f"{format_montant(excedent_faf)}."
        )
        out.append(ctx.constat(
            "C6", classement, libelle=libelle, prochaine_action=ACTION_C6, montant=excedent_faf,
            composante=Composante.prestation,
            preuves=[preuve(v_faf, RolePreuve.valeur_b)] + ([preuve(v_taux, RolePreuve.operande)] if v_taux else [])
            + [preuve(None, RolePreuve.operande,
                      calcul=f"{format_pourcentage(taux)} × {format_montant(arrondi_centime(excedent))}")],
            **commun,
        ))
    return out


# =====================================================================================================
# C7 — Références de la facture transitaire
# =====================================================================================================


def _refs_transport_documents(docs: Iterable[Document]) -> list[ValeurSourcee]:
    """Références de transport citées par des documents : déclarations (documents produits), factures
    commerciales, documents support."""
    refs: list[ValeurSourcee] = []
    for d in docs:
        t = getattr(d.champs, "type_document", None) if d.champs is not None else None
        if t == "declaration":
            refs += [r.reference for r in d.dec.documents_references if r.reference is not None and r.reference.valeur]
        elif t == "facture_commerciale":
            if d.fc.ref_transport is not None and d.fc.ref_transport.valeur:
                refs.append(d.fc.ref_transport)
        elif t == "document_support":
            refs += [v for v in (d.sup.ref_transport_maitre, d.sup.ref_transport_maison) if v is not None and v.valeur]
    return refs


def _refs_transport_dossier(ctx: ControlContext) -> list[ValeurSourcee]:
    docs = [*ctx.declarations(dernieres_versions=False), *ctx.factures_commerciales(), *ctx.supports()]
    return _refs_transport_documents(docs)


_CONFUSIONS_REF: dict[str, set[str]] = {}
#: Confusions de lecture d'un identifiant alphanumérique : celles de §8.5.4, plus les lettres de forme voisine
#: (I/J/L, O/Q, U/V) qu'une lecture OCR confond aussi dans une référence (D-709).
_LETTRES_VOISINES = (("I", "J"), ("I", "L"), ("J", "1"), ("L", "1"), ("O", "Q"), ("Q", "0"), ("U", "V"))
for _a, _b in [*LETTRES_CHIFFRES.items(), *_LETTRES_VOISINES,
               *((x, y) for cl in CLASSES_CONFUSION for x in cl for y in cl if x != y)]:
    _CONFUSIONS_REF.setdefault(_a.upper(), set()).add(_b.upper())
    _CONFUSIONS_REF.setdefault(_b.upper(), set()).add(_a.upper())


def refs_confondables(a: str | None, b: str | None, *, max_differences: int = 2) -> bool:
    """Références normalisées de même longueur qui ne diffèrent que par 1 à ``max_differences`` caractères,
    chacun d'une paire de confusion de lecture (§8.5.4 : classes de chiffres, O↔0, D↔0, I↔1, S↔5, B↔8, Z↔2,
    G↔6). Sert à ne pas signaler comme « sans correspondance » une référence mal lue (C7, D-709)."""
    x, y = norm_ref(a), norm_ref(b)
    if len(x) != len(y) or x == y or len(x) < 5:
        return False
    diff = [i for i in range(len(x)) if x[i] != y[i]]
    return len(diff) <= max_differences and all(y[i] in _CONFUSIONS_REF.get(x[i], set()) for i in diff)


def _sujette(ctx: ControlContext, v: ValeurSourcee) -> bool:
    return confusion_applicable(v, ctx.qualite_page(v))


@control("C7")
def c7_references(ctx: ControlContext) -> list[ResultatControle]:
    """C7 — MRN et références de transport cités par la facture transitaire contre le dossier.

    Un MRN est reconnu par son préfixe (toutes versions, et déclarations des autres dossiers du client
    pour un relevé) ; une référence de transport par ``ref_compatibles`` avec une référence de la
    déclaration, de la facture commerciale ou d'un document support — du dossier ou d'un autre dossier qui
    contient la même facture (relevé réparti). Une référence qui ne diffère d'une référence connue que par
    une confusion de lecture (l'une des deux lue par OCR) n'est pas signalée. Une facture partagée entre
    dossiers est jugée dans le dossier principal seulement. ``a_verifier`` seulement, sans montant.
    """
    factures = ctx.factures_transitaires()
    if not factures:
        return [ctx.non_applicable("C7", RaisonCode.facture_transitaire_absente)]
    prefixes_vals = [d.dec.mrn for d in ctx.declarations(dernieres_versions=False)
                     if d.dec.mrn_prefixe and d.dec.mrn is not None]
    prefixes_vals += [d.dec.mrn for a in ctx.autres_dossiers for d in a.documents.values()
                      if _est_declaration(d) and d.dec.mrn is not None and d.dec.mrn_prefixe]
    # Sans déclaration dans le dossier, les MRN cités ne peuvent pas être rapprochés (P1 : contrôles C
    # dépendant du document manquant non vérifiables).
    mrn_verifiable = bool(ctx.declarations(dernieres_versions=False))
    prefixes_propres = {d.dec.mrn_prefixe for d in ctx.declarations(dernieres_versions=False) if d.dec.mrn_prefixe}
    refs_propres = _refs_transport_dossier(ctx)
    out = []
    groupes: dict[frozenset[str], tuple[list[Document], list[ValeurSourcee], list[ValeurSourcee], dict]] = {}
    for f in factures:
        unite = cle_unite(ft=f.id)
        if not dossier_principal(ctx, f.id):
            out.append(ctx.non_applicable("C7", RaisonCode.couvert_par_autre_controle, unite=unite, documents=[f.id],
                                          details={"motif": "facture_evaluee_dans_un_autre_dossier"}))
            continue
        # Autres dossiers qui contiennent la même facture (relevé réparti) : leurs déclarations et références
        # comptent ; un MRN d'un dossier sans lien avec la facture reste « sans correspondance » (D-709).
        freres = [a for a in ctx.autres_dossiers if f.id in a.documents]
        prefixes = prefixes_propres | {d.dec.mrn_prefixe for a in freres for d in a.documents.values()
                                       if _est_declaration(d) and d.dec.mrn_prefixe}
        refs_dossier = refs_propres + _refs_transport_documents(
            d for a in freres for d in a.documents.values() if d.id != f.id)
        ft = f.ft
        mrns = _mrn_cites(ctx, f)
        transports = [v for v in [*ft.refs_transport, *(t.ref_transport for t in ft.tableau_mrn),
                                  *(lg.ref_transport for lg in ft.lignes)] if v is not None and ctx.utilisable(v)]
        if not mrns and not transports:
            out.append(ctx.non_verifiable("C7", RaisonCode.valeur_absente, unite=unite, documents=[f.id]))
            continue
        sans: list[ValeurSourcee] = []
        vus: set[str] = set()
        for v in (mrns if mrn_verifiable else []):
            p = mrn_prefixe(v.valeur)
            if p in vus:
                continue
            vus.add(p)
            if p in prefixes:
                continue
            if any(refs_confondables(p, mrn_prefixe(x.valeur)) and (_sujette(ctx, v) or _sujette(ctx, x))
                   for x in prefixes_vals):
                continue
            sans.append(v)
        transports_sans: list[ValeurSourcee] = []
        verifiable_transport = bool(refs_dossier)
        if verifiable_transport:
            vus_t: set[str] = set()
            for v in transports:
                k = norm_ref(v.valeur)
                if k in vus_t:
                    continue
                vus_t.add(k)
                if any(ref_transport_compatibles(v.valeur, r.valeur) or ref_compatibles(v.valeur, r.valeur)
                       for r in refs_dossier):
                    continue
                if any(refs_confondables(norm_ref_transport(v.valeur), norm_ref_transport(r.valeur))
                       and (_sujette(ctx, v) or _sujette(ctx, r)) for r in refs_dossier):
                    continue
                transports_sans.append(v)
        details = {"mrn_cites": len(vus), "refs_transport_verifiees": verifiable_transport}
        if not sans and not transports_sans:
            if not (mrns and mrn_verifiable) and not verifiable_transport:
                out.append(ctx.non_verifiable("C7", RaisonCode.valeur_absente, unite=unite, documents=[f.id],
                                              details=details))
            else:
                out.append(ctx.conforme("C7", unite=unite, documents=[f.id], details=details))
            continue
        # Factures du dossier qui citent les mêmes références sans correspondance (facture de débours et
        # facture de prestations d'un même envoi) : un seul constat (D-709).
        cle = frozenset({"mrn:" + mrn_prefixe(v.valeur) for v in sans}
                        | {"tr:" + norm_ref_transport(v.valeur) for v in transports_sans})
        g = groupes.setdefault(cle, ([], [], [], details))
        g[0].append(f)
        g[1].extend(sans)
        g[2].extend(transports_sans)
    for fs, sans, transports_sans, details in groupes.values():
        ids = [f.id for f in fs]
        unite = cle_unite(ft=ids[0] if len(ids) == 1 else ids)
        entrees = {f"ref_{i}": v for i, v in enumerate(sans + transports_sans)}
        classement = ctx.classify("C7", ecart=None, tolerance=None, seuil_certitude=None,
                                  valeurs_cles=sans + transports_sans, documents=ids)
        vus_txt: set[str] = set()
        morceaux = []
        for nom, v in [*(("MRN", v) for v in sans), *(("référence de transport", v) for v in transports_sans)]:
            k = nom + norm_ref(v.valeur)
            if k in vus_txt:
                continue
            vus_txt.add(k)
            morceaux.append(f"{nom} {v.valeur_brute or v.valeur}{_entre_parentheses(page_txt([v]))}")
        cite = "cite" if len(fs) == 1 else "citent"
        libelle = (
            f"{libelle_facture(fs)} {cite} des références sans correspondance parmi les documents du dossier : "
            f"{' ; '.join(morceaux)}."
        )
        out.append(ctx.constat(
            "C7", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_C7,
            preuves=[preuve(v, RolePreuve.valeur_b) for v in sans + transports_sans], documents=ids,
            entrees=entrees, details=details,
        ))
    return out


# =====================================================================================================
# C8 — Client facturé
# =====================================================================================================


def _tva_importateur(ctx: ControlContext) -> list[ValeurSourcee]:
    vals = [d.dec.importateur.tva for d in ctx.declarations() if ctx.utilisable(d.dec.importateur.tva)]
    if not vals:
        vals = [fc.fc.acheteur.tva for fc in ctx.factures_commerciales() if ctx.utilisable(fc.fc.acheteur.tva)]
    return [v for v in vals if v is not None]


@control("C8")
def c8_client_facture(ctx: ControlContext) -> list[ResultatControle]:
    """C8 — TVA (à défaut nom) du client facturé contre l'entité importatrice (déclaration, à défaut
    acheteur de la facture commerciale). ``ecart_certain`` possible si les deux TVA sont lues ≥ 0,90."""
    factures = ctx.factures_transitaires()
    if not factures:
        return [ctx.non_applicable("C8", RaisonCode.facture_transitaire_absente)]
    importateurs = _tva_importateur(ctx)
    out = []
    # Factures adressées à un même numéro de TVA différent de l'importateur : un seul constat par dossier et
    # par numéro (une facture de débours et une facture de prestations pour le même envoi relèvent du même
    # fait ; D-707). Une facture partagée entre dossiers (relevé) n'est jugée que dans le dossier principal.
    ecarts: dict[str, list[Document]] = {}
    for f in factures:
        unite = cle_unite(ft=f.id)
        cf = f.ft.client_facture
        if not dossier_principal(ctx, f.id):
            out.append(ctx.non_applicable("C8", RaisonCode.couvert_par_autre_controle, unite=unite, documents=[f.id],
                                          details={"motif": "facture_evaluee_dans_un_autre_dossier"}))
            continue
        if not importateurs:
            out.append(ctx.non_verifiable("C8", RaisonCode.valeur_absente, unite=unite, documents=[f.id],
                                          details={"motif": "tva_importateur_absente"}))
            continue
        tvas_imp = {normalize_vat(v.valeur) for v in importateurs}
        ref = importateurs[0]
        docs = [f.id, *dict.fromkeys(v.document_id for v in importateurs if v.document_id)]
        if ctx.utilisable(cf.tva):
            assert cf.tva is not None
            t = normalize_vat(cf.tva.valeur)
            if t in tvas_imp:
                out.append(ctx.conforme("C8", unite=unite, entrees={"client_facture": cf.tva, "importateur": ref},
                                        attendu=ref.valeur, constate=cf.tva.valeur, documents=docs))
                continue
            ecarts.setdefault(t or norm_ref(cf.tva.valeur), []).append(f)
            continue
        # Pas de TVA lue : comparaison par nom ou alias (jamais certaine).
        if not ctx.utilisable(cf.nom):
            out.append(ctx.non_verifiable("C8", ctx.raison_inutilisable(cf.tva), unite=unite, documents=docs))
            continue
        assert cf.nom is not None
        nom = cle_texte(cf.nom.valeur or "")
        attendue = next((e for v in importateurs if (e := ctx.entite_par_tva(v.valeur)) is not None), None)

        def correspond(e, nom: str = nom) -> bool:
            return any(a and (cle_texte(a) == nom or f" {cle_texte(a)} " in f" {nom} ")
                       for a in [e.raison_sociale, *e.alias])

        if attendue is not None and correspond(attendue):
            out.append(ctx.conforme("C8", unite=unite, documents=docs, entrees={"client_facture": cf.nom}))
            continue
        autres = [e for e in ctx.entites if e is not attendue and correspond(e)]
        if attendue is None or len(autres) != 1:
            out.append(ctx.non_verifiable("C8", RaisonCode.valeur_absente, unite=unite, documents=docs,
                                          details={"motif": "nom_client_non_rapproche"}))
            continue
        classement = ctx.classify("C8", ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=[cf.nom, ref],
                                  documents=docs, raisons_supplementaires=[RaisonCode.plusieurs_entites])
        libelle = (
            f"{libelle_facture([f])} est adressée à {cf.nom.valeur_brute or cf.nom.valeur}"
            f"{_entre_parentheses(page_txt([cf.nom]))}, nom de l'entité {autres[0].raison_sociale} du client ; "
            f"l'importateur indiqué porte le numéro de TVA {ref.valeur}{_entre_parentheses(page_txt([ref]))} "
            f"({attendue.raison_sociale})."
        )
        out.append(ctx.constat(
            "C8", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_C8, documents=docs,
            preuves=[preuve(cf.nom, RolePreuve.valeur_b), preuve(ref, RolePreuve.valeur_a)],
            entrees={"client_facture": cf.nom, "importateur": ref},
        ))
    for groupe in ecarts.values():
        out.append(_c8_ecart_tva(ctx, groupe, importateurs))
    return out


def _c8_ecart_tva(ctx: ControlContext, groupe: Sequence[Document], importateurs: Sequence[ValeurSourcee]
                  ) -> ResultatControle:
    """Constat C8 pour des factures adressées à un même numéro de TVA, différent de celui de l'importateur."""
    ref = importateurs[0]
    tvas = [f.ft.client_facture.tva for f in groupe]
    assert all(v is not None for v in tvas)
    cf_tva = max((v for v in tvas if v is not None), key=lambda v: v.confiance)
    ids = [f.id for f in groupe]
    unite = cle_unite(ft=ids[0] if len(ids) == 1 else ids)
    docs = [*ids, *dict.fromkeys(v.document_id for v in importateurs if v.document_id)]
    commun = dict(unite=unite, entrees={"client_facture": cf_tva, "importateur": ref},
                  attendu=ref.valeur, constate=cf_tva.valeur, documents=docs)
    entite = ctx.entite_par_tva(cf_tva.valeur)
    douteuse = any(
        confusion_applicable(v, ctx.qualite_page(v)) and codes_confondables(
            (normalize_vat(cf_tva.valeur) or "")[2:], (normalize_vat(ref.valeur) or "")[2:], max_differences=1)
        for v in (cf_tva, ref)
    )
    cles = [v for v in tvas if v is not None] + [ref]
    classement = ctx.classify("C8", ecart=None, tolerance=None, seuil_certitude=None,
                              valeurs_cles=cles, documents=docs, lecture_douteuse=douteuse)
    qui = (f"Ce numéro est celui de l'entité {entite.raison_sociale} du client." if entite is not None
           else "Ce numéro ne correspond à aucune entité enregistrée du client.")
    src = "la déclaration" if ref.chemin.startswith("declaration") else "la facture commerciale"
    est = "est adressée" if len(groupe) == 1 else "sont adressées"
    libelle = (
        f"{libelle_facture(list(groupe))} {est} au numéro de TVA {cf_tva.valeur_brute or cf_tva.valeur}"
        f"{_entre_parentheses(page_txt(tvas))} ; {src} indique comme importateur le numéro "
        f"{ref.valeur_brute or ref.valeur}{_entre_parentheses(page_txt([ref]))}. {qui}"
    )
    return ctx.constat(
        "C8", classement, libelle=libelle, prochaine_action=ACTION_C8,
        preuves=[*(preuve(v, RolePreuve.valeur_b) for v in tvas), preuve(ref, RolePreuve.valeur_a)], **commun,
    )
