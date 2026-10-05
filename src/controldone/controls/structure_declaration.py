"""Structure lue d'une déclaration : validation avant un « écart certain » de B2 et B4 (D-2210).

Sur une mise en page inconnue, l'extracteur peut lire chaque valeur correctement (forte confiance, base ×
taux = montant sur chaque ligne) et pourtant **assembler** le tableau de travers : montant de droit rangé
sous le code de TVA, ligne d'article dont le numéro n'est pas lu prise pour un total de catégorie, lignes
d'une seule page sommées contre le total de toutes les pages, deux copies de la même déclaration fusionnées,
masses nettes et brutes prises à deux niveaux différents. La confiance et la corroboration ligne à ligne
(D-1700) ne voient pas ces erreurs d'assemblage.

Ce module donne les **motifs** pour lesquels la structure lue ne fonde pas un écart certain. Un motif
non vide fait passer le constat en ``a_verifier`` (raison ``structure_non_validee``) ; il ne change jamais
un ``conforme``. Les règles ne regardent que la **forme** du tableau lu (doublons, couverture des articles,
cohérence interne des lignes), jamais un taux ou un code : la famille B ne juge pas la réglementation.

Taxes (B2) :

- pas deux lignes pour le même article et le même code, pas deux articles de même numéro (copie fusionnée,
  ligne lue deux fois) ;
- quand les lignes portent un numéro d'article, chaque article attendu (numéros lus, ``1..nombre_articles``)
  a au moins une ligne (lignes d'une page manquantes) ; pour un total de catégorie, le code couvre tous les
  articles que couvrent les autres codes (sinon la ligne « sans article » peut être celle de l'article
  manquant, dont le numéro n'a pas été lu) ;
- chaque ligne sommée dont la base et le taux sont lus vérifie base × taux = montant (sinon le montant peut
  venir d'une colonne voisine ou d'une autre ligne) ;
- un total de catégorie qui imprime une base : base imprimée = Σ bases des lignes (sinon ce n'est pas le
  total de ces lignes).

Masses (B4 au total) : numéros d'articles uniques, articles lus = ``nombre_articles`` imprimé (s'il est
lu), et la masse brute totale est bien du niveau « total » : Σ masses brutes des articles = masse brute
totale quand toutes sont lues ; sinon, les masses brutes lues ne la dépassent pas et elle ne reprend pas la
masse brute d'un seul article.

Totaux de catégorie (``totaux_par_categorie``) : une ligne sans article n'est **pas** prise pour le total de
sa catégorie quand son code n'a pas de ligne pour un article attendu **et** que le total des droits et taxes
imprimé n'est retrouvé qu'en la comptant comme une ligne ordinaire (c'est alors la ligne de cet article,
dont le numéro n'a pas été lu).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Protocol

from controldone.model import Document, PaiementNormalise, TauxNature, TaxationDeclaration, ValeurSourcee

__all__ = [
    "code_taxe",
    "montant_taxe",
    "motifs_structure_masses",
    "motifs_structure_taxes",
    "numero_article",
    "totaux_par_categorie",
]

_ZERO = Decimal(0)
_CENT = Decimal(100)

Num = Callable[[ValeurSourcee | None], Decimal | None]


class _TolSomme(Protocol):
    def t_somme(self, n: int) -> Decimal: ...


class _Tol(_TolSomme, Protocol):
    def taxe_ligne_concorde(self, montant: Decimal, calcul: Decimal) -> bool: ...
    def t_masse(self, a: Decimal, b: Decimal | None = None) -> Decimal: ...


def code_taxe(t: TaxationDeclaration) -> str:
    return (t.type_taxe.valeur or "").strip().upper() if t.type_taxe is not None and t.type_taxe.valeur else ""


def montant_taxe(t: TaxationDeclaration) -> ValeurSourcee | None:
    """Montant imprimé de la taxe (à défaut, montant à payer)."""
    return t.montant if t.montant is not None else t.montant_a_payer


def numero_article(v: ValeurSourcee | None) -> str:
    """Numéro d'article normalisé (``"01"`` = ``"1"``) ; ``""`` si absent."""
    if v is None or not v.valeur:
        return ""
    s = str(v.valeur).strip()
    return (s.lstrip("0") or "0") if s.isdigit() else s.upper()


def _nature_taux(t: TaxationDeclaration) -> TauxNature | None:
    if t.taux_nature is not None:
        return t.taux_nature
    a_m = t.base_montant is not None and t.base_montant.est_lisible
    a_q = t.base_quantite is not None and t.base_quantite.est_lisible
    if a_m and not a_q:
        return TauxNature.ad_valorem
    if a_q and not a_m:
        return TauxNature.specifique
    return None


# =====================================================================================================
# Totaux de catégorie
# =====================================================================================================


def _sommes_lignes(dec: Document, indices: Sequence[int], num: Num) -> list[Decimal] | None:
    """Σ des lignes (toutes ; hors TVA autoliquidée) ; ``None`` si un montant n'est pas lu."""
    taxations = dec.dec.taxations
    tout: list[Decimal] = []
    hors: list[Decimal] = []
    for i in indices:
        x = num(montant_taxe(taxations[i]))
        if x is None:
            return None
        tout.append(x)
        if taxations[i].paiement_normalise is not PaiementNormalise.autoliquide:
            hors.append(x)
    return [sum(tout, _ZERO), sum(hors, _ZERO)]


def _total_retrouve(dec: Document, indices: Sequence[int], num: Num, tol: _TolSomme) -> bool:
    sommes = _sommes_lignes(dec, indices, num)
    if sommes is None:
        return False
    c = dec.dec
    for total in (c.total_droits_taxes, c.total_a_payer):
        vt = num(total)
        if vt is not None and any(abs(vt - s) <= tol.t_somme(len(indices)) for s in sommes):
            return True
    return False


def totaux_par_categorie(dec: Document, num: Num, tol: _TolSomme) -> dict[str, tuple[int, list[int]]]:
    """Totaux de catégorie imprimés (D-301) : pour un code de taxe, **une seule** ligne sans article **et** au
    moins une ligne par article -> la ligne sans article est le total imprimé de la catégorie. Retourne
    ``{code: (index_total, [index_lignes_articles])}``.

    D-2210 : un candidat est écarté quand son code n'a pas de ligne pour un article attendu et que le total des
    droits et taxes (ou à payer) imprimé n'est retrouvé qu'en le comptant comme une ligne ordinaire (c'est la
    ligne de cet article, dont le numéro n'a pas été lu)."""
    par_code: dict[str, tuple[list[int], list[int]]] = {}
    for i, t in enumerate(dec.dec.taxations):
        code = code_taxe(t)
        if not code:
            continue
        sans, avec = par_code.setdefault(code, ([], []))
        (avec if numero_article(t.article) else sans).append(i)
    candidats = {code: (sans[0], avec) for code, (sans, avec) in par_code.items() if len(sans) == 1 and avec}
    if not candidats:
        return candidats
    n = len(dec.dec.taxations)
    exclus = {i for i, _ in candidats.values()}
    base = [i for i in range(n) if i not in exclus]
    if _total_retrouve(dec, base, num, tol):
        return candidats
    taxations = dec.dec.taxations
    attendus = _articles_attendus(dec) | ({numero_article(t.article) for t in taxations} - {""})
    out: dict[str, tuple[int, list[int]]] = {}
    for code, (i_total, avec) in candidats.items():
        couverts = {numero_article(taxations[i].article) for i in avec}
        if attendus - couverts and _total_retrouve(dec, sorted([*base, i_total]), num, tol):
            continue  # la ligne « sans article » est une ligne ordinaire
        out[code] = (i_total, avec)
    return out


# =====================================================================================================
# Taxes (B2)
# =====================================================================================================


def _articles_attendus(dec: Document) -> set[str]:
    """Numéros d'articles attendus : numéros lus des articles, et ``1..nombre_articles`` quand les numéros
    sont numériques."""
    c = dec.dec
    attendus = {numero_article(a.numero_article) for a in c.articles} - {""}
    nb = c.nombre_articles
    if nb is not None and nb.est_lisible:
        try:
            n = nb.entier()
        except ValueError:
            n = 0
        numeriques = all(x.isdigit() for x in attendus | {numero_article(t.article) for t in c.taxations} - {""})
        if 0 < n <= 999 and numeriques:
            attendus |= {str(k) for k in range(1, n + 1)}
    return attendus


def _doublons(dec: Document) -> list[str]:
    c = dec.dec
    motifs: list[str] = []
    arts = Counter(numero_article(a.numero_article) for a in c.articles)
    arts.pop("", None)
    if any(k > 1 for k in arts.values()):
        motifs.append("articles de même numéro lus plusieurs fois")
    paires = Counter((numero_article(t.article), code_taxe(t)) for t in c.taxations if code_taxe(t))
    if any(k > 1 and art for (art, _), k in paires.items()):
        motifs.append("plusieurs lignes du même code de taxe pour un même article")
    return motifs


def _ligne_coherente(t: TaxationDeclaration, num: Num, tol: _Tol) -> bool:
    """Base × taux = montant quand les trois sont lus (sinon rien à opposer)."""
    nature = _nature_taux(t)
    base = t.base_montant if nature is TauxNature.ad_valorem else t.base_quantite
    b, tx, m = num(base), num(t.taux), num(t.montant)
    if nature is None or b is None or tx is None or m is None:
        return True
    calcul = b * tx / _CENT if nature is TauxNature.ad_valorem else b * tx
    return tol.taxe_ligne_concorde(m, calcul)


def motifs_structure_taxes(
    dec: Document, lignes: Sequence[int], num: Num, tol: _Tol, *, i_total: int | None = None,
) -> list[str]:
    """Motifs pour lesquels la somme des ``lignes`` (indices de taxations) contre un total ne fonde pas un écart
    certain. ``i_total`` : ligne de total de catégorie (B2 ``categorie``), ``None`` pour le total de la
    déclaration (B2 ``total``)."""
    c = dec.dec
    taxations = c.taxations
    motifs = _doublons(dec)
    numeros = {numero_article(t.article) for t in taxations} - {""}
    if numeros:
        if i_total is None:
            manquants = _articles_attendus(dec) - numeros
            if manquants:
                motifs.append(f"article(s) sans ligne de taxe lue : {', '.join(sorted(manquants))}")
        else:
            du_code = {numero_article(taxations[i].article) for i in lignes} - {""}
            manquants = (numeros | _articles_attendus(dec)) - du_code
            if manquants:
                motifs.append(
                    f"le code n'a pas de ligne lue pour l'article {', '.join(sorted(manquants))} : la ligne sans "
                    "article peut être la sienne"
                )
    incoherentes = [i for i in lignes if not _ligne_coherente(taxations[i], num, tol)]
    if incoherentes:
        motifs.append(f"ligne(s) {', '.join(str(i) for i in incoherentes)} : montant ≠ base × taux")
    if i_total is not None:
        tot = taxations[i_total]
        bt = num(tot.base_montant)
        bases = [num(taxations[i].base_montant) for i in lignes]
        if bt is not None and bases and all(b is not None for b in bases):
            s = sum((b for b in bases if b is not None), _ZERO)
            if abs(bt - s) > tol.t_somme(len(bases)):
                motifs.append("la base imprimée du total diffère de la somme des bases des lignes")
    return motifs


# =====================================================================================================
# Masses (B4 au total)
# =====================================================================================================


def motifs_structure_masses(dec: Document, num: Num, tol: _Tol) -> list[str]:
    """Motifs pour lesquels Σ masses nettes des articles contre la masse brute totale ne fonde pas un écart
    certain : articles en double ou incomplets, masse brute totale non retrouvée par Σ masses brutes des
    articles (articles et total lus à des niveaux différents)."""
    c = dec.dec
    motifs = [m for m in _doublons(dec) if m.startswith("articles")]
    nb = c.nombre_articles
    if nb is not None and nb.est_lisible:
        try:
            n = nb.entier()
        except ValueError:
            n = -1
        if n != len(c.articles):
            motifs.append("le nombre d'articles lus diffère du nombre d'articles imprimé")
    brutes = [num(a.masse_brute) for a in c.articles]
    lues = [b for b in brutes if b is not None]
    vt = num(c.masse_brute_totale)
    if vt is not None and lues:
        s = sum(lues, _ZERO)
        if len(lues) == len(brutes):
            if abs(s - vt) > tol.t_masse(vt, s):
                motifs.append("la masse brute totale diffère de la somme des masses brutes des articles")
        elif s - vt > tol.t_masse(vt, s):
            motifs.append("la masse brute totale est inférieure aux masses brutes des articles lus")
        elif len(brutes) > 1 and vt in lues:
            motifs.append("la masse brute totale reprend la masse brute d'un seul article")
    return motifs
