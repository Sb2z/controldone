"""Lecture corroborée : filet de sécurité contre les lectures fausses sur une mise en page inconnue (D-1700).

Un extracteur réglé sur certaines mises en page peut lire, sur une mise en page qu'il n'a jamais vue, une
valeur **fausse avec une confiance élevée** (séparateur de milliers perdu, colonne voisine, ligne non lue).
La confiance seule ne protège donc pas un « écart certain ». Ce module demande une **preuve interne** : une
valeur lue (méthode ``texte_natif``, ``ocr`` ou ``llm``) ne fonde un ``ecart_certain`` que si une autre
**identité arithmétique** du même document, qui ne fait pas partie du calcul contesté, la contient et
**tient** (la lecture est alors confirmée par l'arithmétique imprimée du document lui-même).

Réseau d'identités d'un document (``reseau``), construit uniquement sur des valeurs **lues** (jamais sur des
valeurs dérivées, qui reproduiraient la lecture qu'elles prétendent confirmer) :

- déclaration : base × taux = montant par ligne de taxation ; Σ lignes d'une taxe = total imprimé de la
  taxe (ligne de total ou ``totaux_par_code``, D-3101) ; Σ totaux par code = total des droits et taxes ou total
  à payer ; Σ lignes = total des droits et taxes ou total à payer (TVA autoliquidée incluse ou exclue) ;
  Σ montants facturés des articles = montant total facturé ; écho montant facturé de l'article = valeur
  statistique ou base du droit de l'article (deux colonnes distinctes donnent le même nombre) ;
- facture du transitaire, avoir : quantité × prix unitaire = montant (quantité ≠ 1) ; montant HT × taux =
  TVA de la ligne ; Σ débours = total des débours ; Σ lignes = total HT ; Σ (HT × taux) ou Σ TVA des lignes
  = total TVA ; HT + TVA = TTC ; TTC − acomptes = net ;
- facture commerciale : quantité × prix unitaire = montant (quantité ≠ 1) ; Σ lignes (+ pieds) = total.

Règle (``evaluer``) : chaque valeur clé de type **montant**, ramenée à ses sources lues, venant d'un document
non structuré doit être confirmée par une identité qui tient, autre que l'identité contestée. L'identité
contestée est déduite des valeurs clés quand elles viennent toutes d'un seul document (contrôle
d'arithmétique interne : B1, B2, B3, D1, E4, G1) :

- somme contestée (B2, B3, D1 totaux, E4) : le total imprimé est la valeur mise en cause, il n'a pas à être
  confirmé ; chaque ligne sommée doit l'être (B1 de la ligne, autre total…) et, pour la facture du
  transitaire, la **complétude** des lignes lues doit être prouvée par une autre identité de même portée ;
- produit contesté (B1, G1, D1 ligne / TVA de ligne) : le montant imprimé doit être confirmé (par une somme
  qui le contient) ; les facteurs (base, prix unitaire) sont admis si une autre identité de même nature tient
  sur le document (les colonnes ont été lues au bon endroit).

Sinon : ``a_verifier``, raison ``lecture_non_corroboree``. Les valeurs structurées (XML, CSV valides) et
saisies par un humain sont dispensées.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from controldone.controls.structure_declaration import totaux_par_categorie
from controldone.model.champs import TaxationDeclaration
from controldone.model.documents import Document
from controldone.model.enums import (
    CategorieTaxe,
    Methode,
    PaiementNormalise,
    TauxNature,
    TypeDocument,
    TypeSousTotal,
    TypeValeur,
)
from controldone.model.valeur import ValeurSourcee

__all__ = [
    "Identite",
    "evaluer",
    "lecture_confirmee",
    "rangees",
    "reseau",
]

_ZERO = Decimal(0)
_CENT = Decimal(100)

# Natures d'identités (une identité « de même nature » qui tient prouve que les colonnes des facteurs ont été
# lues au bon endroit).
TAXE_LIGNE = "taxe_ligne"
LIGNE_FT = "ligne_ft"
TVA_LIGNE = "tva_ligne"
LIGNE_FC = "ligne_fc"


class _Tol(Protocol):
    def t_ligne(self) -> Decimal: ...
    def t_somme(self, n: int) -> Decimal: ...
    def taxe_ligne_concorde(self, montant: Decimal, calcul: Decimal) -> bool: ...


@dataclass(frozen=True, slots=True)
class Identite:
    """Identité arithmétique imprimée sur un document : ``imprime`` ≟ f(``operandes``)."""

    cle: str
    genre: str  # "somme" | "produit" | "echo"
    nature: str
    imprime: str
    operandes: tuple[str, ...]
    tient: bool
    #: Portée d'une somme de lignes (« debours », « tout », « taxable »…), pour la complétude.
    portee: str | None = None
    #: Opérandes nuls d'une somme : une somme ne prouve pas la lecture d'un zéro (une valeur lue à 0, ou
    #: prise dans une colonne vide, ne change pas la somme).
    inertes: tuple[str, ...] = ()

    @property
    def membres(self) -> frozenset[str]:
        return frozenset((self.imprime, *self.operandes))

    @property
    def confirmes(self) -> frozenset[str]:
        """Valeurs dont la lecture est confirmée quand l'identité tient."""
        return self.membres - frozenset(self.inertes)


# =====================================================================================================
# Lecture des valeurs
# =====================================================================================================


class _Lecteur:
    """Valeurs **lues** et exploitables d'un document (jamais dérivées)."""

    def __init__(self, utilisable: Callable[[ValeurSourcee | None], bool]) -> None:
        self._utilisable = utilisable

    def lue(self, v: ValeurSourcee | None) -> bool:
        return v is not None and v.methode is not Methode.derive and not v.est_reconstruite and self._utilisable(v)

    def num(self, v: ValeurSourcee | None) -> Decimal | None:
        if not self.lue(v):
            return None
        assert v is not None
        try:
            return v.decimal_signe()
        except ValueError:
            return None

    def taux(self, v: ValeurSourcee | None) -> Decimal | None:
        """Taux de TVA d'une ligne, lu ou déduit (taux normal attribué selon la nature de la ligne) : il ne sert
        que de facteur d'une identité dont les membres confirmés sont des montants lus (D-2804)."""
        if v is None or v.est_reconstruite or not self._utilisable(v):
            return None
        try:
            return v.decimal_signe()
        except ValueError:
            return None


def _zones_distinctes(a: ValeurSourcee, b: ValeurSourcee) -> bool:
    """Deux valeurs lues à deux endroits différents de la page (écho probant)."""
    if a.id == b.id or a.zone is None or b.zone is None:
        return False
    if a.page != b.page:
        return True
    za, zb = a.zone, b.zone
    chevauche_x = min(za.x1, zb.x1) - max(za.x0, zb.x0) > 0
    chevauche_y = min(za.y1, zb.y1) - max(za.y0, zb.y0) > 0
    return not (chevauche_x and chevauche_y)


# =====================================================================================================
# Réseaux par type de document
# =====================================================================================================


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


def _montant_taxe(t: TaxationDeclaration) -> ValeurSourcee | None:
    return t.montant if t.montant is not None else t.montant_a_payer


def _somme_identite(
    cle: str, nature: str, total: ValeurSourcee, v_total: Decimal, ops: Sequence[tuple[ValeurSourcee, Decimal]],
    tol: _Tol, portee: str | None = None,
) -> Identite:
    s = sum((x for _, x in ops), _ZERO)
    return Identite(cle, "somme", nature, total.id, tuple(v.id for v, _ in ops),
                    abs(v_total - s) <= tol.t_somme(len(ops)), portee,
                    tuple(v.id for v, x in ops if x == 0) + ((total.id,) if v_total == 0 else ()))


def _reseau_declaration(doc: Document, lec: _Lecteur, tol: _Tol) -> list[Identite]:
    c = doc.dec
    out: list[Identite] = []
    # base × taux = montant (B1, G1)
    for i, t in enumerate(c.taxations):
        nature = _nature_taux(t)
        base = t.base_montant if nature is TauxNature.ad_valorem else t.base_quantite
        b, tx, m = lec.num(base), lec.num(t.taux), lec.num(t.montant)
        if nature is None or b is None or tx is None or m is None:
            continue
        assert base is not None and t.taux is not None and t.montant is not None
        calcul = b * tx / _CENT if nature is TauxNature.ad_valorem else b * tx
        out.append(Identite(f"dec:taxe:{i}", "produit", TAXE_LIGNE, t.montant.id, (base.id, t.taux.id),
                            tol.taxe_ligne_concorde(m, calcul)))
    # Totaux de catégorie imprimés (une ligne sans article, des lignes par article : D-301, D-2210).
    exclus: set[int] = set()
    for code, (i_total, avec) in sorted(totaux_par_categorie(doc, lec.num, tol).items()):
        exclus.add(i_total)
        total = _montant_taxe(c.taxations[i_total])
        v_total = lec.num(total)
        ops = [(v, lec.num(v)) for v in (_montant_taxe(c.taxations[i]) for i in avec)]
        if total is None or v_total is None or any(x is None for _, x in ops):
            continue
        out.append(_somme_identite(f"dec:categorie:{code}", "taxes", total, v_total,
                                   [(v, x) for v, x in ops if v is not None and x is not None], tol))
    # Totaux imprimés par code (D-3101) : Σ lignes du code = total du code ; Σ totaux par code = total des droits et
    # taxes ou total à payer. Jamais des lignes de taxation.
    lus_codes: list[tuple[ValeurSourcee, Decimal]] = []
    for tot in c.totaux_par_code:
        code = (tot.type_taxe.valeur or "").strip().upper() if tot.type_taxe is not None and tot.type_taxe.valeur else ""
        v_total = lec.num(tot.montant)
        if not code or tot.montant is None or v_total is None:
            lus_codes = []
            break
        lus_codes.append((tot.montant, v_total))
        du_code = [_montant_taxe(t) for t in c.taxations
                   if t.type_taxe is not None and (t.type_taxe.valeur or "").strip().upper() == code]
        ops_code = [(v, lec.num(v)) for v in du_code]
        if ops_code and all(v is not None and x is not None for v, x in ops_code):
            out.append(_somme_identite(f"dec:code:{code}", "taxes", tot.montant, v_total,
                                       [(v, x) for v, x in ops_code if v is not None and x is not None], tol))
    if len(lus_codes) >= 2:
        for nom_total, total in (("total_droits_taxes", c.total_droits_taxes), ("total_a_payer", c.total_a_payer)):
            v_total = lec.num(total)
            if total is not None and v_total is not None:
                out.append(_somme_identite(f"dec:codes:{nom_total}", "taxes", total, v_total, lus_codes, tol))
    # Σ lignes = total des droits et taxes / total à payer, TVA autoliquidée incluse ou exclue.
    lignes = [(i, _montant_taxe(t)) for i, t in enumerate(c.taxations) if i not in exclus]
    lues = [(i, v, lec.num(v)) for i, v in lignes]
    if lues and all(x is not None for _, _, x in lues):
        indice = any(lec.lue(ind.valeur) or lec.lue(ind.tva) for ind in c.indices_autoliquidation)

        def autoliquidee(t: TaxationDeclaration) -> bool:
            if t.paiement_normalise is PaiementNormalise.autoliquide:
                return True
            return indice and t.categorie is CategorieTaxe.tva and t.paiement_normalise is PaiementNormalise.inconnu

        tout = [(v, x) for _, v, x in lues if v is not None and x is not None]
        hors = [(v, x) for i, v, x in lues if v is not None and x is not None and not autoliquidee(c.taxations[i])]
        hypotheses = {"incluse": tout}
        if len(hors) != len(tout):
            hypotheses["exclue"] = hors
        for nom_total, total in (("total_droits_taxes", c.total_droits_taxes), ("total_a_payer", c.total_a_payer)):
            v_total = lec.num(total)
            if total is None or v_total is None:
                continue
            for nom_h, ops in hypotheses.items():
                if ops:
                    out.append(_somme_identite(f"dec:{nom_total}:{nom_h}", "taxes", total, v_total, ops, tol))
    # Σ montants facturés des articles = montant total facturé (B3).
    total = c.montant_total_facture
    v_total = lec.num(total)
    arts = [(a.montant_facture_article, lec.num(a.montant_facture_article)) for a in c.articles]
    if total is not None and v_total is not None and arts and all(x is not None for _, x in arts):
        out.append(_somme_identite("dec:articles", "articles", total, v_total,
                                   [(v, x) for v, x in arts if v is not None and x is not None], tol))
    # Écho : montant facturé de l'article = valeur statistique ou base ad valorem d'une taxe de l'article.
    bases_par_article: dict[str, list[ValeurSourcee]] = {}
    for t in c.taxations:
        if t.article is not None and t.article.valeur and t.base_montant is not None:
            bases_par_article.setdefault(t.article.valeur.strip(), []).append(t.base_montant)
    for k, a in enumerate(c.articles):
        m = lec.num(a.montant_facture_article)
        if m is None or a.montant_facture_article is None:
            continue
        numero = a.numero_article.valeur.strip() if a.numero_article is not None and a.numero_article.valeur else ""
        candidats = [a.valeur_statistique, *bases_par_article.get(numero, [])]
        for autre in candidats:
            x = lec.num(autre)
            if x is not None and autre is not None and x == m and _zones_distinctes(a.montant_facture_article, autre):
                out.append(Identite(f"dec:echo_article:{k}", "echo", "echo_article", a.montant_facture_article.id,
                                    (autre.id,), True))
                break
    return out


def _reseau_lignes_ft(
    prefixe: str, lignes: Sequence, total_debours: ValeurSourcee | None, total_ht: ValeurSourcee | None,
    total_tva: ValeurSourcee | None, total_ttc: ValeurSourcee | None, acomptes: ValeurSourcee | None,
    net: ValeurSourcee | None, lec: _Lecteur, tol: _Tol,
) -> list[Identite]:
    out: list[Identite] = []
    hts: list[tuple[object, ValeurSourcee | None, Decimal | None]] = []
    for i, lg in enumerate(lignes):
        q, pu, ht = lec.num(lg.quantite), lec.num(lg.prix_unitaire), lec.num(lg.montant_ht)
        hts.append((lg, lg.montant_ht, ht))
        # Quantité 1 : « 1 × x = x » ne prouve rien (deux lectures du même nombre).
        if q is not None and pu is not None and ht is not None and q != 1:
            out.append(Identite(f"{prefixe}:ligne:{i}", "produit", LIGNE_FT, lg.montant_ht.id,
                                (lg.quantite.id, lg.prix_unitaire.id), abs(ht - q * pu) <= tol.t_ligne()))
        tx, tva = lec.num(lg.taux_tva), lec.num(lg.montant_tva)
        if ht is not None and tx is not None and tva is not None and (tx != 0 or tva != 0):
            out.append(Identite(f"{prefixe}:tva_ligne:{i}", "produit", TVA_LIGNE, lg.montant_tva.id,
                                (lg.montant_ht.id, lg.taux_tva.id), abs(tva - ht * tx / _CENT) <= tol.t_ligne()))
    complets = bool(hts) and all(x is not None for _, _, x in hts)
    # Σ débours = total des débours : seules les lignes de débours doivent être lues ; une ligne de prestation dont
    # seul le TTC est imprimé (« TVA comprise ») n'entre pas dans cette somme (D-2804).
    debours_lus = all(x is not None for lg, _, x in hts if lg.nature.est_debours)
    debours = [(v, x) for lg, v, x in hts if lg.nature.est_debours and v is not None and x is not None]
    prest = [(v, x) for lg, v, x in hts if not lg.nature.est_debours and v is not None and x is not None]
    tout = debours + prest
    v_td, v_ht, v_tva = lec.num(total_debours), lec.num(total_ht), lec.num(total_tva)
    if debours_lus and debours and total_debours is not None and v_td is not None:
        out.append(_somme_identite(f"{prefixe}:total_debours", "lignes", total_debours, v_td, debours, tol, "debours"))
    if complets and total_ht is not None and v_ht is not None:
        out.append(_somme_identite(f"{prefixe}:total_ht", "lignes", total_ht, v_ht, tout, tol, "tout"))
        if debours and prest:
            out.append(_somme_identite(f"{prefixe}:total_ht_prestations", "lignes", total_ht, v_ht, prest, tol,
                                       "prestations"))
    # Σ TVA des lignes (lue) ou Σ HT × taux (taux lu) = total TVA : portée « lignes taxables ».
    if complets and total_tva is not None and v_tva is not None:
        tvas = [(lg, lg.montant_tva, lec.num(lg.montant_tva), lec.num(lg.taux_tva)) for lg, _, _ in hts]
        if any(x is not None for _, _, x, _ in tvas) and all(
            x is not None or t == 0 or (t is None and lg.nature.est_debours) for lg, _, x, t in tvas
        ):
            ops = [(v, x) for _, v, x, _ in tvas if v is not None and x is not None]
            out.append(_somme_identite(f"{prefixe}:tva_lignes", "tva", total_tva, v_tva, ops, tol, "taxable"))
        taxees = [(v, x, lg.taux_tva, t) for (lg, v, x), (_, _, _, t) in zip(hts, tvas, strict=True)
                  if t is not None and t != 0 and v is not None and x is not None]
        sans_taux = [lg for lg, _, _, t in tvas if t is None and not lg.nature.est_debours]
        if not sans_taux and (taxees or v_tva == 0):
            s = sum((x * t / _CENT for _, x, _, t in taxees), _ZERO)
            ops_ids = tuple(v.id for v, _, _, _ in taxees) + tuple(tx.id for _, _, tx, _ in taxees)
            out.append(Identite(f"{prefixe}:tva_base", "somme", "tva", total_tva.id, ops_ids,
                                abs(v_tva - s) <= tol.t_somme(len(taxees) + 1), "taxable"))
        elif sans_taux and v_tva != 0:
            # D-2804 : taux de ligne non imprimés mais déduits (taux normal selon la nature) : Σ HT lus × taux = total
            # de TVA lu. Membres confirmés : le total et les HT lus (jamais les taux déduits).
            derives = [(lg, v, x, lec.taux(lg.taux_tva)) for lg, v, x in hts]
            if all(t is not None or lg.nature.est_debours for lg, _, _, t in derives):
                taxees_d = [(v, x, t) for _, v, x, t in derives if t is not None and t != 0 and v is not None
                            and x is not None]
                if taxees_d:
                    s = sum((x * t / _CENT for _, x, t in taxees_d), _ZERO)
                    out.append(Identite(f"{prefixe}:tva_base_taux_deduits", "somme", "tva", total_tva.id,
                                        tuple(v.id for v, _, _ in taxees_d),
                                        abs(v_tva - s) <= tol.t_somme(len(taxees_d) + 1), "taxable"))
    # Aucun débours lu ni total des débours imprimé : la portée « débours » est vide.
    if complets and not debours and (v_td is None or v_td == 0):
        out.append(Identite(f"{prefixe}:sans_debours", "somme", "vide", "", (), True, "debours"))
    # Σ TTC des lignes = total TTC (lignes « TVA comprise », D-2804) : chaque ligne doit imprimer son TTC ; l'identité
    # couvre toutes les lignes (portée « tout »).
    ttcs = [(getattr(lg, "montant_ttc", None), lec.num(getattr(lg, "montant_ttc", None))) for lg in lignes]
    v_ttc_total = lec.num(total_ttc)
    if (ttcs and total_ttc is not None and v_ttc_total is not None
            and all(v is not None and x is not None for v, x in ttcs)):
        out.append(_somme_identite(f"{prefixe}:ttc_lignes", "lignes", total_ttc, v_ttc_total,
                                   [(v, x) for v, x in ttcs if v is not None and x is not None], tol, "tout"))
    # Totaux d'en-tête.
    v_ttc = lec.num(total_ttc)
    if v_ttc is not None and v_ht is not None and v_tva is not None:
        assert total_ttc is not None and total_ht is not None and total_tva is not None
        calculs = [v_ht + v_tva]
        ops_ids = (total_ht.id, total_tva.id)
        out.append(Identite(f"{prefixe}:total_ttc", "somme", "entete", total_ttc.id, ops_ids,
                            any(abs(v_ttc - c) <= tol.t_somme(2) for c in calculs)))
        if v_td is not None and total_debours is not None:
            out.append(Identite(f"{prefixe}:total_ttc_debours", "somme", "entete", total_ttc.id,
                                (total_ht.id, total_tva.id, total_debours.id),
                                abs(v_ttc - (v_ht + v_tva + v_td)) <= tol.t_somme(3)))
    v_net = lec.num(net)
    if v_net is not None and v_ttc is not None:
        assert net is not None and total_ttc is not None
        v_ac = lec.num(acomptes)
        ops = (total_ttc.id,) + ((acomptes.id,) if acomptes is not None and v_ac is not None else ())
        out.append(Identite(f"{prefixe}:net", "somme", "entete", net.id, ops,
                            abs(v_net - (v_ttc - abs(v_ac or _ZERO))) <= tol.t_somme(len(ops))))
    return out


def _reseau_facture_commerciale(doc: Document, lec: _Lecteur, tol: _Tol) -> list[Identite]:
    f = doc.fc
    out: list[Identite] = []
    lignes = []
    for i, lg in enumerate(f.lignes):
        q, pu, m = lec.num(lg.quantite), lec.num(lg.prix_unitaire), lec.num(lg.montant_ligne)
        lignes.append((lg.montant_ligne, m))
        if q is not None and pu is not None and m is not None and q != 1:
            # Arrondi au centime du produit ; prix unitaires à 4 décimales admis.
            out.append(Identite(f"fc:ligne:{i}", "produit", LIGNE_FC, lg.montant_ligne.id,
                                (lg.quantite.id, lg.prix_unitaire.id),
                                abs(m - q * pu) <= max(tol.t_ligne(), abs(q) * Decimal("0.005"))))
    total, v_total = f.total_facture, lec.num(f.total_facture)
    if total is None or v_total is None or not lignes or any(x is None for _, x in lignes):
        return out
    ops = [(v, x) for v, x in lignes if v is not None and x is not None]
    out.append(_somme_identite("fc:total", "lignes", total, v_total, ops, tol))
    pieds = []
    for st in f.sous_totaux:
        x = lec.num(st.montant)
        if x is None or st.montant is None or st.type in (TypeSousTotal.marchandises, TypeSousTotal.autre):
            continue
        pieds.append((st.montant, -abs(x) if st.type is TypeSousTotal.remise else abs(x)))
    if pieds:
        out.append(_somme_identite("fc:total_pieds", "lignes", total, v_total, ops + pieds, tol))
    for k, st in enumerate(f.sous_totaux):
        x = lec.num(st.montant)
        if st.type is TypeSousTotal.marchandises and x is not None and st.montant is not None:
            out.append(_somme_identite(f"fc:sous_total:{k}", "lignes", st.montant, x, ops, tol))
            if pieds:
                out.append(_somme_identite(f"fc:total_sous_total:{k}", "entete", total, v_total,
                                           [(st.montant, x), *pieds], tol))
    return out


def rangees(doc: Document) -> dict[str, str]:
    """Valeur -> rangée de tableau (ligne de taxation, article, ligne de facture) qui la porte."""
    if doc.champs is None:
        return {}
    c = doc.champs
    tables: list[tuple[str, Sequence]] = []
    if doc.type is TypeDocument.declaration:
        tables = [("taxations", doc.dec.taxations), ("articles", doc.dec.articles)]
    elif doc.type in (TypeDocument.facture_transitaire, TypeDocument.avoir, TypeDocument.facture_commerciale):
        tables = [("lignes", getattr(c, "lignes", []))]
    out: dict[str, str] = {}
    for nom, lignes in tables:
        for i, lg in enumerate(lignes):
            for v in lg.iter_valeurs():
                out[v.id] = f"{nom}[{i}]"
    return out


def reseau(doc: Document, utilisable: Callable[[ValeurSourcee | None], bool], tol: _Tol) -> tuple[Identite, ...]:
    """Identités arithmétiques imprimées d'un document, sur ses valeurs lues (voir l'en-tête du module)."""
    if doc.champs is None:
        return ()
    lec = _Lecteur(utilisable)
    if doc.type is TypeDocument.declaration:
        return tuple(_reseau_declaration(doc, lec, tol))
    if doc.type is TypeDocument.facture_transitaire:
        ft = doc.ft
        return tuple(_reseau_lignes_ft("ft", ft.lignes, ft.total_debours, ft.total_ht, ft.total_tva, ft.total_ttc,
                                       ft.acomptes, ft.net_a_payer, lec, tol))
    if doc.type is TypeDocument.avoir:
        av = doc.av
        return tuple(_reseau_lignes_ft("av", av.lignes, None, av.total_credite_ht, av.total_tva,
                                       av.total_credite_ttc, None, None, lec, tol))
    if doc.type is TypeDocument.facture_commerciale:
        return tuple(_reseau_facture_commerciale(doc, lec, tol))
    return ()


# =====================================================================================================
# Évaluation d'un constat
# =====================================================================================================


def _feuilles(valeurs: Iterable[ValeurSourcee], index: Callable[[str], ValeurSourcee | None]) -> list[ValeurSourcee]:
    """Valeurs clés ramenées à leurs sources lues (une valeur dérivée sans source connue reste une feuille)."""
    out: dict[str, ValeurSourcee] = {}
    pile = list(valeurs)
    vus: set[str] = set()
    while pile:
        v = pile.pop()
        if v.id in vus:
            continue
        vus.add(v.id)
        sources = [s for s in (index(i) for i in v.derivee_de) if s is not None] if v.methode is Methode.derive else []
        if sources:
            pile.extend(sources)
        else:
            out[v.id] = v
    return list(out.values())


def _a_confirmer(v: ValeurSourcee) -> bool:
    """Valeur lue (non structurée, non saisie) de type montant : sa lecture doit être confirmée."""
    return v.type is TypeValeur.montant and not v.est_structuree


def lecture_confirmee(
    identites: Sequence[Identite], valeur_id: str, exclues: Iterable[Identite] = (),
    rangee_de: dict[str, str] | None = None,
) -> bool:
    """La valeur figure dans une identité qui tient, hors identités exclues (contestées) ; ou, pour une valeur
    d'une rangée de tableau, un autre montant de la même rangée y figure (la rangée a été lue au bon endroit)."""
    ex = {i.cle for i in exclues}
    tenues = [i for i in identites if i.tient and i.cle not in ex]
    if any(valeur_id in i.confirmes for i in tenues):
        return True
    rangee = (rangee_de or {}).get(valeur_id)
    if rangee is None:
        return False
    voisines = {k for k, r in (rangee_de or {}).items() if r == rangee and k != valeur_id}
    return any(i.confirmes & voisines for i in tenues if i.genre != "echo")


def _complet(identites: Sequence[Identite], contestee: Identite) -> bool:
    """Complétude des lignes lues d'une somme contestée (facture du transitaire, avoir) : chaque portée de la
    somme est couverte par une **autre** identité de lignes qui tient et qui ne contient pas le total contesté
    (débours : total des débours ; lignes taxables : total de TVA ; toutes les lignes : total HT)."""
    autres = [i for i in identites if i.tient and i.cle != contestee.cle and contestee.imprime not in i.membres]
    portees = {i.portee for i in autres if i.portee}
    if contestee.portee == "debours":
        return "tout" in portees
    if contestee.portee == "prestations":
        return "taxable" in portees
    if contestee.portee == "tout":
        return {"debours", "taxable"} <= portees
    return True


def evaluer(
    valeurs_cles: Sequence[ValeurSourcee],
    *,
    index: Callable[[str], ValeurSourcee | None],
    document: Callable[[str], Document | None],
    reseau_de: Callable[[Document], Sequence[Identite]],
    rangees_de: Callable[[Document], dict[str, str]] = rangees,
    operandes_non_confirmees_max: int = 0,
) -> tuple[bool, list[str]]:
    """``(corroboree, motifs)`` pour un constat dont les valeurs clés sont ``valeurs_cles``.

    ``operandes_non_confirmees_max`` : nombre de lignes d'une somme contestée admises sans confirmation (B3 :
    l'erreur porte sur **un** article ; les autres doivent prouver la lecture de la colonne).
    """
    feuilles = [v for v in _feuilles(valeurs_cles, index) if v.document_id]
    a_voir = [v for v in feuilles if _a_confirmer(v)]
    if not a_voir:
        return True, []
    docs = {v.document_id for v in feuilles if not v.est_structuree}
    un_seul_document = len({v.document_id for v in feuilles}) == 1
    ids = {v.id for v in feuilles}
    motifs: list[str] = []
    for doc_id in sorted(d for d in docs if d):
        doc = document(doc_id)
        if doc is None:
            continue
        identites = list(reseau_de(doc))
        rangee_de = rangees_de(doc)
        contestees = [i for i in identites if i.membres <= ids] if un_seul_document else []
        sommes = [i for i in contestees if i.genre == "somme"]
        produits = [i for i in contestees if i.genre == "produit"]
        exempts: set[str] = {i.imprime for i in sommes}
        for p in produits:
            meme_nature = any(i.tient and i.nature == p.nature and i.cle != p.cle and not (i.membres & p.membres)
                              for i in identites)
            if meme_nature:
                exempts.update(p.operandes)
        operandes_somme = {o for s in sommes for o in s.operandes}
        non_confirmees = 0
        for v in a_voir:
            if v.document_id != doc_id or v.id in exempts:
                continue
            if lecture_confirmee(identites, v.id, contestees, rangee_de):
                continue
            if v.id in operandes_somme:
                non_confirmees += 1
                continue
            motifs.append(f"{v.chemin} : lecture non confirmée par une autre identité du document")
        if non_confirmees > operandes_non_confirmees_max or (
            non_confirmees and non_confirmees >= len(operandes_somme)
        ):
            motifs.append(f"{non_confirmees} ligne(s) sommée(s) sans confirmation par une autre identité")
        for s in sommes:
            if s.portee and not _complet(identites, s):
                motifs.append(f"{s.cle} : complétude des lignes lues non prouvée")
    return not motifs, motifs
