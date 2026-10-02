"""Modèle des documents d'un dossier synthétique (valeurs exactes, Decimal)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(eq=False)
class Party:
    name: str
    addr: tuple
    country: str = "FR"
    vat: str | None = None
    siren: str | None = None
    eori: str | None = None


@dataclass(eq=False)
class CILine:
    no: int
    ref: str
    desc: str
    product: str
    hs10: str
    hs_printed: str | None
    qty: Decimal
    unit: str
    price: Decimal
    amount: Decimal
    origin: str
    net: Decimal
    gross: Decimal


@dataclass(eq=False)
class CommercialInvoice:
    doc_id: str
    numero: str
    date: dt.date
    seller: Party
    buyer: Party
    consignee: Party | None
    currency: str
    language: str
    sous_type: str
    lines: list
    goods: Decimal
    footer: dict  # nature -> Decimal (fret, assurance, emballage, remise)
    total: Decimal
    total_printed: bool
    incoterm: str
    incoterm_place: str
    transport_ref: str
    transport_kind: str  # awb | bl
    gross_total: Decimal
    net_total: Decimal
    packages: int
    shipping_mode: str | None
    numstyle: str
    fmt: str = "pdf"  # pdf | ubl | cii | xlsx
    eori_printed: bool = False
    multipage: bool = False
    payment_terms: str = ""
    seller_key: str = ""


@dataclass(eq=False)
class Article:
    no: int
    hs10: str
    desc: str
    origin: str
    pref_origin: str | None
    pref_code: str
    regime: str
    amount: Decimal  # dans la devise déclarée
    stat_value: Decimal  # EUR
    net: Decimal
    gross: Decimal
    qty_sup: Decimal | None
    unit_sup: str | None
    packages: int
    invoice_refs: list
    line_refs: list
    qty_total: Decimal = Decimal("0")


@dataclass(eq=False)
class Tax:
    article: int | None
    code: str
    categorie: str
    label: str
    base_montant: Decimal | None
    base_quantite: Decimal | None
    base_unite: str | None
    taux: Decimal
    taux_nature: str  # ad_valorem | specifique
    montant: Decimal
    mp: str
    paiement: str  # comptant | differe | autoliquide | garanti


@dataclass(eq=False)
class Declaration:
    doc_id: str
    layout: str
    sous_type: str
    mrn: str
    lrn: str
    version: int
    date: dt.date
    importer: Party
    declarant: Party
    currency: str
    total_invoiced: Decimal
    rate_printed: Decimal | None
    rate_sens: str | None
    eur_per_unit: Decimal
    incoterm: str
    incoterm_place: str
    pays_exp: str
    gross_total: Decimal
    packages_total: int
    articles: list
    taxes: list
    doc_refs: list  # [(code, ref)]
    autoliq: bool
    euro_round: bool = False
    cat_totals: dict = field(default_factory=dict)
    total_droits_taxes: Decimal = Decimal("0")
    total_a_payer: Decimal = Decimal("0")
    cat_totals_printed: bool = True
    n_articles_printed: int = 0
    ci_ids: list = field(default_factory=list)
    shipment: int = 0
    printed_totals_override: dict = field(default_factory=dict)

    def liquide(self) -> dict:
        out = {"droit": Decimal("0"), "autre_taxe": Decimal("0"), "tva": Decimal("0"),
               "forfait_petits_envois": Decimal("0")}
        for t in self.taxes:
            if t.paiement == "autoliquide":
                continue
            out[t.categorie] += t.montant
        if self.autoliq:
            out["tva"] = Decimal("0")
        return out


@dataclass(eq=False)
class FTLine:
    nature: str
    code: str  # code poste interne (DEDOUANEMENT, DROITS, …)
    libelle: str
    qty: Decimal
    unit_price: Decimal
    montant_ht: Decimal
    taux_tva: Decimal
    montant_tva: Decimal
    marker: str
    mrn: str | None = None
    ref_transport: str | None = None
    hs: str | None = None
    base_droit: Decimal | None = None
    base_tva: Decimal | None = None
    date_debut: dt.date | None = None
    date_fin: dt.date | None = None
    detail: str = ""
    article: int | None = None

    @property
    def is_debours(self) -> bool:
        return self.nature.startswith("debours_")


@dataclass(eq=False)
class ForwarderInvoice:
    doc_id: str
    kind: str  # facture | releve | debours | prestations | complementaire | rebill
    template: str
    numero: str
    date: dt.date
    emetteur: Party
    client: Party
    refs_transport: list
    refs_mrn: list
    refs_ci: list
    lines: list
    language: str
    total_debours: Decimal = Decimal("0")
    total_debours_printed: bool = True
    total_ht: Decimal = Decimal("0")
    total_tva: Decimal = Decimal("0")
    total_ttc: Decimal = Decimal("0")
    acompte: Decimal = Decimal("0")
    net_a_payer: Decimal = Decimal("0")
    est_releve: bool = False
    dossier_ref: str = ""
    decl_ids: list = field(default_factory=list)
    printed_override: dict = field(default_factory=dict)
    period: tuple | None = None
    due_date: dt.date | None = None

    def recompute(self):
        from .common import q2
        self.total_debours = q2(sum((l.montant_ht for l in self.lines if l.is_debours), Decimal("0")))
        self.total_ht = q2(sum((l.montant_ht for l in self.lines), Decimal("0")))
        self.total_tva = q2(sum((l.montant_tva for l in self.lines), Decimal("0")))
        self.total_ttc = self.total_ht + self.total_tva
        self.net_a_payer = self.total_ttc - self.acompte

    def printed(self, key: str) -> Decimal:
        return self.printed_override.get(key, getattr(self, key))


@dataclass(eq=False)
class CreditNote:
    doc_id: str
    numero: str
    date: dt.date
    emetteur: Party
    client: Party
    refs_origin: list
    refs_mrn: list
    refs_transport: list
    lines: list  # FTLine
    motif: str
    template: str
    language: str
    total_ht: Decimal = Decimal("0")
    total_tva: Decimal = Decimal("0")
    total_ttc: Decimal = Decimal("0")
    printed_override: dict = field(default_factory=dict)

    def recompute(self):
        from .common import q2
        self.total_ht = q2(sum((l.montant_ht for l in self.lines), Decimal("0")))
        self.total_tva = q2(sum((l.montant_tva for l in self.lines), Decimal("0")))
        self.total_ttc = self.total_ht + self.total_tva

    def printed(self, key: str) -> Decimal:
        return self.printed_override.get(key, getattr(self, key))


@dataclass(eq=False)
class SupportDoc:
    doc_id: str
    sous_type: str  # titre_transport, liste_colisage, lettre_accompagnement, conditions_generales, courriel, pre_alerte
    language: str
    data: dict = field(default_factory=dict)
    doc_type: str = "document_support"  # ou document_non_exploitable


# ---------------------------------------------------------------------------
# Libellés des lignes de facture transitaire (identiques à ceux des grilles)
# ---------------------------------------------------------------------------

FT_LABELS = {
    "DROITS": {"fr": "Droits de douane", "en": "Customs duty", "fr_en": "Droits de douane / Customs duty"},
    "AUTRES": {"fr": "Autres taxes", "en": "Other duties and taxes", "fr_en": "Autres taxes / Other taxes"},
    "TVA": {"fr": "TVA à l'importation", "en": "Import VAT", "fr_en": "TVA import / Import VAT"},
    "COMBINES": {"fr": "Droits et taxes", "en": "Duties and taxes", "fr_en": "Droits et taxes / Duties and taxes"},
    "FORFAIT": {"fr": "Droit forfaitaire petits envois", "en": "Flat duty low-value parcels",
                "fr_en": "Droit forfaitaire petits envois / Flat duty"},
    "DEDOUANEMENT": {"fr": "Frais de dédouanement", "en": "Customs clearance",
                     "fr_en": "Frais de dédouanement / Customs clearance"},
    "LIGNE_SUP": {"fr": "Lignes supplémentaires", "en": "Additional lines",
                  "fr_en": "Lignes supplémentaires / Additional lines"},
    "AVANCE_FONDS": {"fr": "Frais d'avance de fonds", "en": "Disbursement fee",
                     "fr_en": "Avance de fonds / Disbursement fee"},
    "MAGASINAGE": {"fr": "Magasinage", "en": "Storage", "fr_en": "Magasinage / Storage"},
    "TRANSPORT": {"fr": "Livraison", "en": "Delivery", "fr_en": "Livraison / Delivery"},
    "MANUTENTION": {"fr": "Manutention", "en": "Handling", "fr_en": "Manutention / Handling"},
    "SURCHARGE_CARBURANT": {"fr": "Surcharge carburant", "en": "Fuel surcharge",
                            "fr_en": "Surcharge carburant / Fuel surcharge"},
    "SURCHARGE_SURETE": {"fr": "Surcharge sûreté", "en": "Security surcharge",
                         "fr_en": "Surcharge sûreté / Security surcharge"},
    "OUVERTURE_DOSSIER": {"fr": "Ouverture de dossier", "en": "File opening",
                          "fr_en": "Ouverture de dossier / File opening"},
}

# Libellés hors grille (D2 / D7)
OFF_GRID = {
    "autre_prestation": [
        {"fr": "Frais de dossier informatique", "en": "IT processing fee", "fr_en": "Frais informatiques / IT fee"},
        {"fr": "Frais de traitement documentaire", "en": "Document handling fee",
         "fr_en": "Traitement documentaire / Document fee"},
        {"fr": "Frais d'archivage", "en": "Archiving fee", "fr_en": "Archivage / Archiving fee"},
    ],
    "surcharge": [
        {"fr": "Surcharge haute saison", "en": "Peak season surcharge",
         "fr_en": "Surcharge haute saison / Peak season surcharge"},
        {"fr": "Surcharge congestion portuaire", "en": "Port congestion surcharge",
         "fr_en": "Surcharge congestion / Congestion surcharge"},
    ],
}

NATURE_OF_CODE = {
    "DROITS": "debours_droits", "AUTRES": "debours_autres_taxes", "TVA": "debours_tva",
    "COMBINES": "debours_combines", "FORFAIT": "debours_forfait_petits_envois",
    "DEDOUANEMENT": "frais_dedouanement", "LIGNE_SUP": "frais_ligne_supplementaire",
    "AVANCE_FONDS": "frais_avance_fonds", "MAGASINAGE": "magasinage", "TRANSPORT": "transport",
    "MANUTENTION": "manutention", "SURCHARGE_CARBURANT": "surcharge", "SURCHARGE_SURETE": "surcharge",
    "OUVERTURE_DOSSIER": "autre_prestation",
}

COMPOSANTE_OF_NATURE = {
    "debours_droits": "droit", "debours_autres_taxes": "autre_taxe", "debours_tva": "tva",
    "debours_forfait_petits_envois": "forfait_petits_envois", "debours_combines": "combine",
}


def composante_of(nature: str) -> str:
    return COMPOSANTE_OF_NATURE.get(nature, "prestation")
