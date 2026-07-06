"""Core dataclasses for the v4 customs control engine.

Design principles
-----------------
* `Document` is the universal carrier, invoice, declaration or prestation.
  Each format-specific parser produces a Document with the right `kind` and
  `format` set, plus the common fields populated.
* `Bundle` regroups docs that belong together (1+ invoice + 1+ decl + 0/1 presta)
  and carries the rule-engine output (`checks`) and the resolved status.
* `CheckResult` is the unit of validation output, one line per rule.

Status semantics (Bundle)
-------------------------
OK, all checks pass
OK_A_CONTROLER, key invoice data was not OCR-readable but declaration data is coherent
KO, at least one NOK non-critical
KO_BLOQUANT, at least one CRITICAL NOK (valeur/devise/entité/HS/préférence)
NON_CONCERNE, TVA on invoice not in our scope (still reported, not actionable)
MANQUE_DOC, missing mandatory document(s) (invoice or declaration)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Per-line data (article level)
# ---------------------------------------------------------------------------

@dataclass
class Line:
    """A single article / line in an invoice or a declaration."""
    item_no: Optional[int] = None
    hs_code: Optional[str] = None          # raw HS as found, may be 6/8/10 digits
    description: Optional[str] = None
    quantity: Optional[float] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    net_weight_kg: Optional[float] = None
    gross_weight_kg: Optional[float] = None
    origin_country: Optional[str] = None   # ISO-2
    preference: Optional[str] = None       # ex: "100", "300"


# ---------------------------------------------------------------------------
# Party (any business entity referenced in a doc)
# ---------------------------------------------------------------------------

@dataclass
class Party:
    name: Optional[str] = None
    eori: Optional[str] = None
    vat: Optional[str] = None              # FR-only TVA num for now (FRxxxxxxxxxxx)
    country: Optional[str] = None
    address: Optional[str] = None


# ---------------------------------------------------------------------------
# Document, universal carrier
# ---------------------------------------------------------------------------

@dataclass
class Document:
    """One source document: invoice / declaration / prestation."""

    # ------ Identity / provenance --------------------------------------------
    kind: str = ""                # "invoice" | "declaration" | "prestation"
    format: str = ""              # ex: "delta_ie_akanea", "worldnet", "launchmetrics_xlsx"
    source_file: Optional[str] = None
    source_pages: List[int] = field(default_factory=list)   # 1-indexed
    text: str = ""                # raw text extracted (debug / fallback)

    # ------ Universal references ---------------------------------------------
    invoice_number: Optional[str] = None        # N° facture (invoice/prestation)
    invoice_date: Optional[str] = None          # ISO yyyy-mm-dd if possible
    mrn: Optional[str] = None                   # declaration MRN (declarations only)
    lrn: Optional[str] = None                   # declaration LRN
    awb: Optional[str] = None                   # Air Waybill / LTA number
    transport_doc: Optional[str] = None         # generic transport ref

    # ------ Cross-doc references ---------------------------------------------
    # Invoices may carry an AWB (commercial invoice from forwarder).
    # Declarations carry references to their invoice (N380), prior MRN (N785),
    # transport doc (N741).
    # Prestations carry MRN references to declarations they paid duties for.
    referenced_invoices: List[str] = field(default_factory=list)
    referenced_mrns: List[str] = field(default_factory=list)
    referenced_awbs: List[str] = field(default_factory=list)

    # ------ Money & currency -------------------------------------------------
    total_amount: Optional[float] = None        # invoice/decl: total facturé
    currency: Optional[str] = None              # ISO-3
    fx_rate: Optional[float] = None             # rate used in declaration

    # Customs amounts (declarations + prestations)
    dd: Optional[float] = None                  # Droits de douane
    at: Optional[float] = None                  # Autres taxes
    tva: Optional[float] = None                 # TVA (cash)
    tva_auto_liquidee: Optional[float] = None   # TVA auto-liquidée
    tg: Optional[float] = None                  # Total général (déclaration)
    total_debours: Optional[float] = None       # Prestation: somme débours
    total_surcharges: Optional[float] = None    # Prestation: charges propres
    total_ttc: Optional[float] = None           # Prestation: TTC

    # ------ HS / origin / weights / commerce ---------------------------------
    lines: List[Line] = field(default_factory=list)
    origin_country: Optional[str] = None        # aggregate
    destination_country: Optional[str] = None
    incoterm: Optional[str] = None
    incoterm_place: Optional[str] = None
    net_weight_kg: Optional[float] = None
    gross_weight_kg: Optional[float] = None

    # ------ Parties ----------------------------------------------------------
    seller: Party = field(default_factory=Party)
    buyer: Party = field(default_factory=Party)
    importer: Party = field(default_factory=Party)
    exporter: Party = field(default_factory=Party)
    declarant: Party = field(default_factory=Party)
    representative: Party = field(default_factory=Party)
    forwarder: Optional[str] = None             # Prestation: nom du prestataire

    # ------ Free-form parser data -------------------------------------------
    extras: Dict[str, Any] = field(default_factory=dict)

    # ------ Convenience -----------------------------------------------------
    @property
    def hs_codes(self) -> List[str]:
        """All HS codes seen in lines, deduplicated, in order."""
        seen, out = set(), []
        for ln in self.lines:
            if ln.hs_code and ln.hs_code not in seen:
                seen.add(ln.hs_code)
                out.append(ln.hs_code)
        return out

    @property
    def vat_buyer(self) -> Optional[str]:
        return self.buyer.vat or self.importer.vat

    @property
    def vat_seller(self) -> Optional[str]:
        return self.seller.vat or self.exporter.vat


# ---------------------------------------------------------------------------
# CheckResult, one rule evaluation
# ---------------------------------------------------------------------------

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_NOK = "NOK"
STATUS_SKIP = "SKIP"

SEVERITY_INFO = "INFO"
SEVERITY_WARN = "WARN"
SEVERITY_ERROR = "ERROR"
SEVERITY_CRITICAL = "CRITICAL"


@dataclass
class CheckResult:
    code: str                                   # ex: "tva_scope", "hs_match"
    section: str                                # ex: "Entité", "Marchandise"
    label: str                                  # human-readable French
    expected: str = ""
    got: str = ""
    status: str = STATUS_SKIP                   # OK | WARN | NOK | SKIP
    severity: str = SEVERITY_INFO               # INFO | WARN | ERROR | CRITICAL
    comment: str = ""

    @property
    def is_blocking(self) -> bool:
        return self.status == STATUS_NOK and self.severity == SEVERITY_CRITICAL


# ---------------------------------------------------------------------------
# Bundle, what we report on
# ---------------------------------------------------------------------------

BUNDLE_OK = "OK"
BUNDLE_VERIFY = "OK_A_CONTROLER"
BUNDLE_KO = "KO"
BUNDLE_KO_BLOQUANT = "KO_BLOQUANT"
BUNDLE_NON_CONCERNE = "NON_CONCERNE"
BUNDLE_MANQUE_DOC = "MANQUE_DOC"


@dataclass
class Bundle:
    invoices: List[Document] = field(default_factory=list)
    declarations: List[Document] = field(default_factory=list)
    prestation: Optional[Document] = None
    source_files: List[str] = field(default_factory=list)
    checks: List[CheckResult] = field(default_factory=list)
    status: str = BUNDLE_OK
    notes: List[str] = field(default_factory=list)        # ex: missing-doc reason

    # ------ Folder reference (always 3 fields, in display order) ------------
    @property
    def ref_prestation_no(self) -> str:
        return self.prestation.invoice_number if self.prestation and self.prestation.invoice_number else ""

    @property
    def ref_awb_lta(self) -> str:
        # priority: prestation AWB → declaration AWB → first invoice AWB
        for d in [self.prestation] + list(self.declarations) + list(self.invoices):
            if d and d.awb:
                return d.awb
        # fallback: any referenced AWB
        for d in [self.prestation] + list(self.declarations) + list(self.invoices):
            if d and d.referenced_awbs:
                return d.referenced_awbs[0]
        return ""

    @property
    def ref_mrn(self) -> str:
        if self.declarations:
            return self.declarations[0].mrn or ""
        if self.prestation and self.prestation.referenced_mrns:
            return self.prestation.referenced_mrns[0]
        return ""

    @property
    def folder_id(self) -> str:
        """Best single-string identifier for tab naming (priority order)."""
        return self.ref_prestation_no or self.ref_awb_lta or self.ref_mrn or "DOSSIER"

    @property
    def primary_invoice_total(self) -> Optional[float]:
        """Sum of invoice totals (for synthesis)."""
        vals = [i.total_amount for i in self.invoices if i.total_amount is not None]
        return round(sum(vals), 2) if vals else None

    @property
    def primary_currency(self) -> Optional[str]:
        for i in self.invoices:
            if i.currency:
                return i.currency
        for d in self.declarations:
            if d.currency:
                return d.currency
        return None
