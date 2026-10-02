"""Modèle d'une facture du fondateur (pur, ``Decimal`` exact) : parties, lignes, remise, ventilation de
TVA, totaux et mentions obligatoires.

Règles de calcul (EN 16931) : montant de ligne = quantité × prix unitaire net, arrondi au centime ;
base de TVA = Σ lignes − remises de document ; TVA = base × taux / 100 arrondie au centime (une seule
catégorie : S à 20 % ou E — franchise en base) ; TTC = base + TVA ; net à payer = TTC − déjà payé.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from controldone.facturation.offres import ParametresPaiement, ParametresTVA, Vendeur, arrondi

__all__ = [
    "TYPE_AVOIR",
    "TYPE_FACTURE",
    "Acheteur",
    "Facture",
    "Ligne",
    "Remise",
    "mentions_obligatoires",
]

TYPE_FACTURE = "380"  # UNTDID 1001 : facture commerciale
TYPE_AVOIR = "381"  # UNTDID 1001 : avoir


@dataclass(frozen=True)
class Acheteur:
    client_id: str
    raison_sociale: str
    siren: str = ""
    tva_intracom: str = ""
    adresse_ligne: str = ""
    code_postal: str = ""
    ville: str = ""
    pays: str = "FR"
    email: str = ""
    adresse_electronique: str = ""  # annuaire (schéma 0225) ; défaut : SIREN
    # Adresse de livraison si différente de celle du client (nouvelle mention 2026, BT-75 à BT-80).
    livraison_ligne: str = ""
    livraison_code_postal: str = ""
    livraison_ville: str = ""
    livraison_pays: str = ""

    @property
    def adresse_livraison_differente(self) -> bool:
        return bool(self.livraison_ligne.strip())

    @property
    def adresse_electronique_effective(self) -> str:
        return self.adresse_electronique or self.siren


@dataclass(frozen=True)
class Ligne:
    libelle: str
    prix_unitaire_ht: Decimal
    quantite: Decimal = Decimal("1")

    @property
    def montant_ht(self) -> Decimal:
        return arrondi(Decimal(self.prix_unitaire_ht) * Decimal(self.quantite))


@dataclass(frozen=True)
class Remise:
    """Remise de document (EN 16931 BG-20), ex. coupon de lancement à 100 %."""

    libelle: str
    montant: Decimal
    code_raison: str = "95"  # UNTDID 5189 : remise (« Discount »)


@dataclass(frozen=True)
class Facture:
    numero: str
    type_code: str
    date_emission: date
    date_echeance: date
    vendeur: Vendeur
    acheteur: Acheteur
    lignes: tuple[Ligne, ...]
    tva: ParametresTVA
    paiement: ParametresPaiement
    remises: tuple[Remise, ...] = ()
    devise: str = "EUR"
    # Facture d'origine (avoir) : numéro et date (BT-25, BT-26).
    facture_origine: str | None = None
    date_facture_origine: date | None = None
    date_prestation: date | None = None  # fin d'exécution de la prestation (BT-72), si différente
    deja_paye: Decimal = Decimal("0.00")
    reference_paiement: str = ""
    notes: tuple[str, ...] = ()
    objet: str = ""
    categorie_operation: str = "S1"  # BT-23 « cadre de facturation » : S1 = prestation de services

    def __post_init__(self) -> None:
        if not self.lignes:
            raise ValueError("une facture comporte au moins une ligne")
        for x in self.lignes:
            if Decimal(x.prix_unitaire_ht) < 0 or Decimal(x.quantite) <= 0:
                raise ValueError("ligne invalide : prix négatif ou quantité nulle")
        if self.remise_totale > self.total_lignes_ht:
            raise ValueError("remise supérieure au total des lignes")
        if self.date_echeance < self.date_emission:
            raise ValueError("échéance antérieure à la date de facture")
        if self.type_code == TYPE_AVOIR and not self.facture_origine:
            raise ValueError("un avoir cite la facture d'origine")

    # --- totaux ---
    @property
    def est_avoir(self) -> bool:
        return self.type_code == TYPE_AVOIR

    @property
    def total_lignes_ht(self) -> Decimal:
        return sum((x.montant_ht for x in self.lignes), Decimal("0.00"))

    @property
    def remise_totale(self) -> Decimal:
        return sum((arrondi(r.montant) for r in self.remises), Decimal("0.00"))

    @property
    def base_ht(self) -> Decimal:
        return self.total_lignes_ht - self.remise_totale

    @property
    def taux_tva(self) -> Decimal:
        return self.tva.taux_effectif

    @property
    def montant_tva(self) -> Decimal:
        return arrondi(self.base_ht * self.taux_tva / Decimal(100))

    @property
    def total_ttc(self) -> Decimal:
        return self.base_ht + self.montant_tva

    @property
    def net_a_payer(self) -> Decimal:
        return self.total_ttc - arrondi(self.deja_paye)


def mentions_obligatoires(f: Facture) -> dict[str, str]:
    """Mentions imprimées et reprises en notes du XML (codes BT-21 utilisés en France : PMD, PMT, AAB,
    TXD ; REG pour les mentions réglementaires de l'émetteur)."""
    v = f.vendeur
    mentions = {
        "PMD": f.paiement.penalites,
        "PMT": f.paiement.indemnite,
        "AAB": f.paiement.escompte,
        "REG": (f"{v.raison_sociale} — {v.forme_juridique} — SIREN {v.siren} — {v.rcs}"
                f"{' — TVA ' + v.tva_intracom if f.tva.tva_applicable else ''}"),
        "CAT": "Catégorie de l'opération : prestation de services.",
    }
    if not f.tva.tva_applicable:
        mentions["TXD"] = f.tva.mention_franchise
    elif f.tva.option_debits:
        mentions["TXD"] = "Option pour le paiement de la taxe d'après les débits."
    return mentions

