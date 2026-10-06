"""Arrondis (§8.2) et tolérances (§8.3) calculés à partir d'un ``ProfilTolerances``.

Convention (D-015) : quand une tolérance est un pourcentage, il s'applique à la **plus grande** des deux
valeurs comparées en valeur absolue (lecture la plus prudente : tolérance la plus large). Un seuil de
certitude n'est jamais inférieur à la tolérance du même contrôle (§2 « Seuil de certitude »).
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from controldone.model.referentiel import ProfilTolerances
from controldone.normalize.currency import exposant_devise
from controldone.normalize.units import UNITES_ENTIERES

__all__ = [
    "CENTIME",
    "Tolerances",
    "arrondi_centime",
    "arrondi_devise",
    "arrondi_unite",
    "dans_tolerance",
]

CENTIME = Decimal("0.01")
_UN = Decimal("1")


def arrondi_centime(x: Decimal) -> Decimal:
    """Arrondi au centime, demi vers le haut (§8.2). Ne pas l'appliquer aux sommes intermédiaires."""
    return Decimal(x).quantize(CENTIME, rounding=ROUND_HALF_UP)


def arrondi_unite(x: Decimal) -> Decimal:
    return Decimal(x).quantize(_UN, rounding=ROUND_HALF_UP)


def arrondi_devise(x: Decimal, devise: str | None) -> Decimal:
    """Arrondi à l'unité de la devise (0 décimale pour JPY, KRW… ; 2 sinon), demi vers le haut."""
    exp = exposant_devise(devise)
    return Decimal(x).quantize(Decimal(1).scaleb(-exp), rounding=ROUND_HALF_UP)


def dans_tolerance(ecart: Decimal, tolerance: Decimal) -> bool:
    """``|écart| ≤ tolérance``."""
    return abs(ecart) <= tolerance


def _base(*valeurs: Decimal | None) -> Decimal:
    return max((abs(v) for v in valeurs if v is not None), default=Decimal(0))


class Tolerances:
    """Accès typé aux tolérances (§8.3) d'un profil. Toutes les valeurs sont des ``Decimal`` en EUR,
    en unités de devise, en kg ou en unités, selon le code."""

    def __init__(self, profil: ProfilTolerances) -> None:
        self.profil = profil

    # --- arithmétique -------------------------------------------------------------------------

    def t_ligne(self) -> Decimal:
        """``T_LIGNE`` : quantité × prix, base × taux de TVA d'une prestation."""
        return self.profil.t_ligne

    def t_somme(self, n: int) -> Decimal:
        """``T_SOMME`` : ``min(0,01 × n ; 0,50)``, au moins 0,01 (n = nombre de lignes sommées)."""
        p = self.profil
        return max(p.t_somme_minimum, min(p.t_somme_par_ligne * max(n, 0), p.t_somme_plafond))

    def t_taxe_ligne(self) -> Decimal:
        return self.profil.t_taxe_ligne

    def taxe_ligne_concorde(self, montant: Decimal, calcul: Decimal) -> bool:
        """``T_TAXE_LIGNE`` (B1, G1) : ``|montant − calcul| ≤ 0,01`` ou montant égal à l'arrondi à l'euro
        inférieur, supérieur ou au plus proche du calcul."""
        if abs(montant - calcul) <= self.profil.t_taxe_ligne:
            return True
        return montant in {
            calcul.quantize(_UN, rounding=ROUND_FLOOR),
            calcul.quantize(_UN, rounding=ROUND_CEILING),
            calcul.quantize(_UN, rounding=ROUND_HALF_UP),
        }

    def s_arith(self) -> Decimal:
        """``S_ARITH`` (D1, E4)."""
        return self.profil.s_arith

    def s_calcul_declaration(self) -> Decimal:
        """Seuil de certitude des écarts de calcul sur la déclaration (B1, B2, B3, G1 : 1,00 EUR)."""
        return self.profil.s_calcul_declaration

    # --- valeur, conversion ---------------------------------------------------------------------

    def t_valeur(self, a: Decimal, b: Decimal | None = None) -> Decimal:
        """``T_VALEUR`` (A4) : ``max(1 unité de devise ; 0,1 %)``."""
        p = self.profil
        return max(p.t_valeur_unites, p.t_valeur_fraction * _base(a, b))

    def s_valeur(self, a: Decimal, b: Decimal | None = None) -> Decimal:
        """``S_VALEUR`` (A4) : ``max(5 unités ; 0,5 %)``."""
        p = self.profil
        return max(p.s_valeur_unites, p.s_valeur_fraction * _base(a, b), self.t_valeur(a, b))

    def t_conversion(self, a: Decimal, b: Decimal | None = None) -> Decimal:
        """``T_CONVERSION`` (A5) : ``max(1,00 EUR ; 0,1 %)``."""
        p = self.profil
        return max(p.t_conversion_eur, p.t_conversion_fraction * _base(a, b))

    def s_conversion(self, a: Decimal, b: Decimal | None = None) -> Decimal:
        """``S_CONVERSION`` (A5) : ``max(5,00 EUR ; 0,5 %)``."""
        p = self.profil
        return max(p.s_conversion_eur, p.s_conversion_fraction * _base(a, b), self.t_conversion(a, b))

    def bande_indicative(self, devise: str | None) -> Decimal:
        """``BANDE_INDICATIVE`` (A7) : ± 25 %, ± 40 % pour les devises volatiles."""
        p = self.profil
        if devise and devise.upper() in {d.upper() for d in p.devises_volatiles}:
            return p.bande_indicative_volatile
        return p.bande_indicative

    # --- débours, tarifs ------------------------------------------------------------------------

    def t_debours(self, nb_articles: int) -> Decimal:
        """``T_DEBOURS`` (C1–C5, G4) : ``max(0,05 ; min(0,01 × nb_articles ; 0,50))``."""
        p = self.profil
        return max(
            p.t_debours_minimum, min(p.t_debours_par_article * max(nb_articles, 0), p.t_debours_plafond)
        )

    def s_debours(self, nb_articles: int = 0) -> Decimal:
        """``S_DEBOURS`` (C, F3, G4, G5) : 1,00 EUR."""
        return max(self.profil.s_debours, self.t_debours(nb_articles))

    def t_tarif(self) -> Decimal:
        return self.profil.t_tarif

    def s_tarif(self) -> Decimal:
        return max(self.profil.s_tarif, self.profil.t_tarif)

    # --- masses, quantités, colis ---------------------------------------------------------------

    def t_masse(self, a: Decimal, b: Decimal | None = None) -> Decimal:
        """``T_MASSE`` (A10, B4) : ``max(0,5 kg ; 0,5 %)``."""
        p = self.profil
        return max(p.t_masse_kg, p.t_masse_fraction * _base(a, b))

    def t_quantite(self, unite: str | None, a: Decimal, b: Decimal | None = None) -> Decimal:
        """``T_QUANTITE`` (A9) : 0 pour les unités dénombrées (pièces, paires…), 0,5 % sinon."""
        if unite in UNITES_ENTIERES:
            return Decimal(0)
        return self.profil.t_quantite_fraction * _base(a, b)

    def t_colis(self) -> Decimal:
        return self.profil.t_colis

    # --- confiances -----------------------------------------------------------------------------

    @property
    def c_min_certain(self) -> float:
        return self.profil.c_min_certain

    @property
    def c_min_utile(self) -> float:
        return self.profil.c_min_utile
