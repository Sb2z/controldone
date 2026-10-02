"""Commission sur avoirs obtenus (SPEC §1.1, §17.4) — fonctions pures, ``Decimal`` exact.

``base_commission = Σ montants imputés (§17.2) sur des écarts issus de constats validés``. Un crédit
imputé sur un écart dont le constat n'est pas (ou plus) validé n'entre pas dans la base : seuls les
écarts **signalés par le produit et validés par le fondateur** donnent lieu à commission.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

__all__ = ["TAUX_COMMISSION_DEFAUT", "base_commission", "montant_commission", "taux_commission"]

TAUX_COMMISSION_DEFAUT = Decimal("0.20")
_CENTIME = Decimal("0.01")


def taux_commission(reglages: Mapping[str, Any] | None) -> Decimal:
    """Taux lu dans les réglages de l'offre du client (``reglages["commission_taux"]``, fraction :
    ``"0.20"`` = 20 %), sinon 20 %. Un taux invalide (hors [0, 1]) lève ``ValueError``."""
    brut = (reglages or {}).get("commission_taux")
    if brut is None:
        return TAUX_COMMISSION_DEFAUT
    try:
        taux = Decimal(str(brut))
    except InvalidOperation as exc:
        raise ValueError("taux de commission invalide") from exc
    if not (Decimal(0) <= taux <= Decimal(1)):
        raise ValueError("taux de commission hors de [0, 1]")
    return taux


def base_commission(imputations: Mapping[str, Decimal], ecarts_eligibles: Iterable[str]) -> Decimal:
    """Somme exacte des montants imputés sur les écarts éligibles (constats validés)."""
    eligibles = set(ecarts_eligibles)
    return sum((Decimal(m) for e, m in sorted(imputations.items()) if e in eligibles), Decimal("0.00"))


def montant_commission(base: Decimal, taux: Decimal) -> Decimal:
    """``base × taux`` arrondi au centime (demi supérieur)."""
    return (Decimal(base) * Decimal(taux)).quantize(_CENTIME, rounding=ROUND_HALF_UP)
