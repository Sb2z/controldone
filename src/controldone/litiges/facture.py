"""Brouillons de facture (actions sortantes ``facture_emise``) : diagnostic, abonnement, commission.

Le contenu est un brouillon soumis au fondateur ; la facturation de niveau 3 (numérotation, TVA,
paiement) le reprend. Montants en chaînes décimales exactes (``"48.00"``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from controldone.formatage import format_montant
from controldone.guardrails import AVERTISSEMENT

__all__ = ["LigneFacture", "payload_facture"]

_CENTIME = Decimal("0.01")


@dataclass(frozen=True)
class LigneFacture:
    libelle: str
    prix_unitaire_ht: Decimal
    quantite: Decimal = Decimal("1")

    @property
    def montant_ht(self) -> Decimal:
        return (self.prix_unitaire_ht * self.quantite).quantize(_CENTIME, rounding=ROUND_HALF_UP)

    def en_json(self) -> dict[str, str]:
        return {"libelle": self.libelle, "quantite": str(self.quantite),
                "prix_unitaire_ht": str(self.prix_unitaire_ht.quantize(_CENTIME)), "montant_ht": str(self.montant_ht)}


def payload_facture(type_facture: str, lignes: Sequence[LigneFacture], *, destinataires: list[str],
                    raison_sociale: str, references: dict[str, Any] | None = None) -> dict[str, Any]:
    """Contenu d'un brouillon ``facture_emise`` (le fondateur relit, corrige ou refuse)."""
    total = sum((x.montant_ht for x in lignes), Decimal("0.00"))
    detail = "\n".join(f"- {x.libelle} : {format_montant(x.montant_ht, 'EUR')} HT" for x in lignes)
    corps = (
        f"Brouillon de facture pour {raison_sociale} ({type_facture}).\n\n{detail}\n\n"
        f"Total HT : {format_montant(total, 'EUR')}. TVA et numérotation à appliquer par la facturation.\n\n"
        f"{AVERTISSEMENT}"
    )
    return {
        "objet": f"Brouillon de facture — {type_facture}",
        "corps": corps,
        "destinataires": destinataires,
        "type_facture": type_facture,
        "lignes": [x.en_json() for x in lignes],
        "total_ht": str(total),
        "devise": "EUR",
        "references": references or {},
    }
