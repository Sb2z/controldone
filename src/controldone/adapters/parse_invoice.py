"""Parse commercial (goods) invoices.

Supports :
  - entity INVOICE (structured table with HS Code column)
  - entity PROFORMA INVOICE (same parser, different header)
  - entity DELIVERY NOTE (Turkey-like, with CUSTOMS CODE)
  - DHL Commercial Invoice
  - Generic fallback

v3.1 improvements
-----------------
entity:
  * Total: prefer the LAST explicitly-labelled TOTAL line rather than max().
  * HS codes: extract ALL lines, not just the first hit.
  * PROFORMA INVOICE support (_parse_entity_proforma reuses _parse_entity logic).
  * Invoice number: extended patterns for Korea (#YYYYMMDD-N), UK (INV-xxxx),
    HK (HK-xxxx), and other regional formats.

DHL Commercial:
  * Exclude AWB numbers AND phone numbers (start with 0, or 7+ digits with 0
    in position 1) more aggressively from HS candidates.

Generic:
  * Multiple pattern attempts to capture currency + amount in >95% of cases.
  * Fallback table-scan for TOTAL row.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

from controldone.adapters.models import Invoice, Line, Party
from controldone.profile import current_profile


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _to_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # "7,017,140" / "1,234" are thousand separators; "12,50" is a decimal.
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _first(pattern: str, text: str, flags: int = re.I | re.S) -> Optional[str]:
    m = re.search(pattern, text, flags=flags)
    return m.group(1).strip() if m else None


CURRENCY_CODES = ("EUR", "USD", "GBP", "CHF", "CAD", "JPY", "CNY", "HKD", "KRW", "SGD", "TRY")


def _digits_only(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return "".join(c for c in s if c.isdigit())


def _normalize_incoterm(s: str) -> str:
    """Map free-text incoterm strings to the standard 3-letter code."""
    up = s.upper().strip()
    mapping = {
        "FREE CARRIER": "FCA",
        "FREE ON BOARD": "FOB",
        "COST AND FREIGHT": "CFR",
        "COST INSURANCE AND FREIGHT": "CIF",
        "COST, INSURANCE AND FREIGHT": "CIF",
        "EX WORKS": "EXW",
        "EXW EX WORKS": "EXW",
        "CARRIAGE PAID TO": "CPT",
        "CARRIAGE AND INSURANCE PAID TO": "CIP",
        "DELIVERED AT PLACE": "DAP",
        "DELIVERED DUTY PAID": "DDP",
        "DELIVERED AT TERMINAL": "DAT",
        "DELIVERED AT PLACE UNLOADED": "DPU",
        "FRANCO AEROPORT": "FCA",
    }
    for k, v in mapping.items():
        if up.startswith(k):
            return v
    m = re.match(r"^([A-Z]{3})\b", up)
    if m:
        return m.group(1)
    return up


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _detect_format(text: str) -> str:
    up = text.upper()
    entity = any(k in up for k in current_profile().invoice_keywords)
    if entity and any(k in up for k in (
            "PROFORMA INVOICE", "PRO-FORMA INVOICE", "PRO FORMA INVOICE")):
        return "entity_proforma"
    if entity and any(k in up for k in ("DELIVERY NOTE NO", "DELIVERY NOTE NO.", "DELIVERY NOTE NUMBER")):
        return "entity_delivery_note"
    if entity and "INVOICE" in up and any(k in up for k in ("INVOICE NO", "HS CODE", "INVOICE NUMBER")):
        return "entity"
    if ("COMMERCIAL INVOICE" in up or "AWB NO" in up) and (
            "COMMODITY CODE" in up or "TERMS OF TRADE" in up):
        return "dhl_commercial"
    return "generic"


# ---------------------------------------------------------------------------
# entity INVOICE
# ---------------------------------------------------------------------------

def _parse_entity(text: str) -> Invoice:
    inv = Invoice(invoice_format="entity")

    # Invoice number, try multiple regional formats
    inv.invoice_number = _extract_entity_invoice_number(text)

    inv.invoice_date = _first(r"Date\s*[:\.]*\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})", text)

    # Incoterm
    m = re.search(r"Incoterms?\s*[:\.]*\s*([A-Za-z][A-Za-z\s]{2,30})", text)
    if m:
        inv.incoterm = _normalize_incoterm(m.group(1).strip())

    # -------- Total amount + currency ------------------------------------
    # Strategy: collect ALL currency+amount pairs, then use the LAST explicitly
    # labelled "TOTAL" line.  Fall back to max() only if no TOTAL label found.
    amounts_by_pos: List[tuple] = []  # (position, value, currency)
    for m in re.finditer(
        rf"({'|'.join(CURRENCY_CODES)}|€)\s+([\d,]+\.\d{{2}})",
        text, flags=re.I,
    ):
        cur = m.group(1).upper()
        cur = "EUR" if cur == "€" else cur
        val = _to_float(m.group(2))
        if val is not None:
            amounts_by_pos.append((m.start(), val, cur))

    # Find LAST labelled TOTAL line
    total_val, total_cur = _find_last_total(text)
    if total_val is not None:
        inv.total_amount = total_val
        inv.currency = total_cur or (amounts_by_pos[-1][2] if amounts_by_pos else "EUR")
    elif amounts_by_pos:
        # fallback: take last (bottom of page) currency amount
        _, inv.total_amount, inv.currency = amounts_by_pos[-1]

    # -------- HS codes, extract ALL hs codes ----------------------------
    hs_codes: List[tuple] = []  # (hs_digits, origin)
    # Pattern 1: "HS CODE: 6403591100" or "HS CODE 64.03.59.11.00"
    for m in re.finditer(r"HS\s*CODE[\s\-:]*([0-9][\d\.\s]{7,14}\d)", text, flags=re.I):
        raw = m.group(1)
        digits = "".join(c for c in raw if c.isdigit())
        if 8 <= len(digits) <= 10:
            hs_codes.append((digits, None))
    # Pattern 2: column value, 8-10 digit number on its own
    if not hs_codes:
        hs = _first(r"HS\s*Code\s*\n?[^\d]*(\d{8,10})", text)
        if hs:
            hs_codes.append((hs, None))

    made_in = _first(r"Made\s*in\s*\n?\s*([A-Z]{2})\b", text)
    seen_hs = set()
    for idx, (hs, origin) in enumerate(hs_codes):
        if hs not in seen_hs:
            seen_hs.add(hs)
            inv.lines.append(Line(item_no=len(inv.lines) + 1,
                                  hs_code=hs,
                                  origin_country=origin or made_in))

    # Importer EORI
    eori = _first(r"EORI[:\s\-]*(FR\d{9,17})", text)
    if eori:
        inv.importer.eori = eori

    return inv


def _extract_entity_invoice_number(text: str) -> Optional[str]:
    """Try several regional entity invoice number formats."""
    # Asia: "Invoice No.: PF-030430"
    n = _first(r"Invoice\s*No\.?\s*[:\.]*\s*([A-Z0-9\-/#]{4,40})", text)
    if n:
        return n.lstrip("#")

    # Korea: "No. & Date of invoice\n#20250620-1"
    m = re.search(
        r"No\.?\s*&?\s*Date\s*of\s*invoice[\s\S]{0,200}?(?:^|\s)#?(\d[A-Z0-9\-/]{5,40})",
        text, flags=re.I | re.M,
    )
    if m:
        return m.group(1).lstrip("#")

    # UK: "INV-XXXX" or "Invoice Number: INV-XXXX"
    n = _first(r"(?:Invoice\s+Number|INVOICE\s+NUMBER)\s*[:\-]*\s*([A-Z0-9\-/]{4,40})", text)
    if n:
        return n

    # HK: "HK-XXXXX" or numeric prefix
    n = _first(r"\b(HK[\-\s]?\d{4,12})\b", text)
    if n:
        return n

    # Generic fallback
    n = _first(r"Invoice\s*N[o°\.]*\s*[:\-]?\s*([A-Z0-9\-/]{4,40})", text)
    return n.lstrip("#") if n else None


# Lines about weights/packages must never feed the invoice total.
_WEIGHT_LINE = re.compile(
    r"WEIGHT|POIDS|\bKGS?\b|\bGRS?\b|GROSS|BRUT|CARTONS?|PACKAGES?|UNITS?\b|PIECES?\b",
    re.I,
)


def _find_last_total(text: str) -> tuple:
    """Return (value, currency) of the last TOTAL label in the document."""
    # Patterns for labelled total lines.  KRW/JPY style integers with thousand
    # separators ("Total Amount -------- KRW 7,017,140") have no decimals.
    patterns = [
        r"TOTAL\s*(?:AMOUNT|PRICE|VALUE|EUR|USD|GBP|CHF|CAD|JPY|CNY|HKD|KRW|SGD|TRY|AED)?[^\n]{0,20}?[:\-]?\s*([\d,]+\.\d{2})",
        r"(?:€|EUR)\s*TOTAL\s*[:\-]?\s*([\d,]+\.\d{2})",
        r"TOTAL[^\n]{0,40}?€\s*([\d,]+\.\d{2})",
        r"GRAND\s+TOTAL\s*[:\-]?\s*([\d,]+\.\d{2})",
        r"TOTAL\s*(?:AMOUNT|VALUE)?[^\n]{0,30}?\b(?:KRW|JPY)\b[^\n]{0,20}?(\d{1,3}(?:,\d{3})+)\b",
        # Grid forms put the amount on the line below "16. Invoice Total".
        r"INVOICE[,.]?\s+TOTAL[^\n]{0,30}\n[^\n\d]{0,10}([\d,]+\.\d{2})",
    ]
    best_pos = -1
    best_val = None
    best_cur = None
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.I):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line = text[line_start: line_end if line_end >= 0 else len(text)]
            if _WEIGHT_LINE.search(line):
                continue
            if m.start() > best_pos:
                v = _to_float(m.group(1))
                if v is not None and v > 0:
                    best_pos = m.start()
                    best_val = v
                    # Try to find currency in same match or nearby
                    snippet = text[max(0, m.start() - 10): m.end()]
                    cur_m = re.search(r"(EUR|USD|GBP|CHF|CAD|JPY|CNY|HKD|KRW|SGD|TRY|AED|€)",
                                      snippet, flags=re.I)
                    best_cur = cur_m.group(1).upper().replace("€", "EUR") if cur_m else None
    return best_val, best_cur


# ---------------------------------------------------------------------------
# entity PROFORMA INVOICE
# ---------------------------------------------------------------------------

def _parse_entity_proforma(text: str) -> Invoice:
    """Same structure as a entity commercial invoice, just a different header."""
    inv = _parse_entity(text)
    inv.invoice_format = "entity_proforma"
    # Proforma-specific: if invoice number not found, look for proforma number
    if not inv.invoice_number:
        inv.invoice_number = (
            _first(r"Proforma\s*(?:Invoice)?\s*No\.?\s*[:\.]*\s*([A-Z0-9\-/#]{4,40})", text)
            or _first(r"Pro.?forma\s*N[o°\.]*\s*[:\-]?\s*([A-Z0-9\-/]{4,40})", text)
        )
    return inv


# ---------------------------------------------------------------------------
# entity DELIVERY NOTE (Turkey format)
# ---------------------------------------------------------------------------

def _parse_entity_delivery_note(text: str) -> Invoice:
    inv = Invoice(invoice_format="entity_delivery_note")
    inv.invoice_number = _first(r"INVOICE[\s\.]*NUMBER[\s\.:]*([A-Z0-9\-/]{3,40})", text)
    inv.invoice_date = _first(r"(?:DATE[\s\.:]*)(\d{1,2}[.\-/:]\d{1,2}[.\-/:]\d{2,4})", text)
    inv.currency = _first(r"CURRENCY[\s\.:]*([A-Z]{3})", text) or "EUR"

    terms = _first(r"DELIVERY\s*TERMS[\s\.:]*([A-Za-z][A-Za-z\s]{2,30})", text)
    if terms:
        inv.incoterm = _normalize_incoterm(terms)

    # Consignee EORI
    eori = _first(r"CONSIGNEE.*?EORI\s*[:\-]*\s*([A-Z]{2}\d{9,17})", text)
    if not eori:
        eori = _first(r"EORI\s*[:\-]*\s*([A-Z]{2}\d{9,17})", text)
    if eori:
        inv.importer.eori = eori

    # Total, prefer last TOTAL row
    total_val, _ = _find_last_total(text)
    if total_val:
        inv.total_amount = total_val
    else:
        m = re.search(
            r"TOTAL[^\n]{0,80}?\b([\d][\d.,\s]{2,15}[\d])\b\s*(?:\|?\s*)?$",
            text, flags=re.I | re.M,
        )
        if m:
            inv.total_amount = _to_float(m.group(1))

    if inv.total_amount in (None, 0.0):
        amounts = re.findall(r"\b(\d{1,3}(?:[.,\s]\d{3})+[.,]\d{2})\b", text)
        values = [v for v in (_to_float(a) for a in amounts) if v is not None]
        if values:
            inv.total_amount = max(values)

    # HS codes : CUSTOMS CODE column values (10 digits)
    hs_set = re.findall(r"\b(\d{10})\b", text)
    origin = _first(
        r"\b(ITA|FRA|CHN|TUR|KOR|JPN|DEU|USA|GBR|CHE|SGP|HKG|IND|VNM|THA|IDN)\b", text
    )
    if hs_set:
        most_common_hs, _ = Counter(hs_set).most_common(1)[0]
        inv.lines.append(Line(item_no=1, hs_code=most_common_hs, origin_country=origin))

    return inv


# ---------------------------------------------------------------------------
# DHL Commercial Invoice
# ---------------------------------------------------------------------------

def _parse_dhl_commercial(text: str) -> Invoice:
    inv = Invoice(invoice_format="dhl_commercial")

    m = re.search(r"Invoice\s*No\.?\s*[:\.]*\s*([A-Z0-9\-/]{3,30})", text, flags=re.I)
    if m:
        inv.invoice_number = m.group(1).rstrip(",;:")

    inv.invoice_date = _first(r"Invoice\s*Date\s*[:\.]*\s*(\d{4}[\-/]\d{2}[\-/]\d{2})", text)
    inv.awb_number = _first(r"AWB\s*No\.?\s*[:\.]*\s*([0-9]{8,12})", text)

    m = re.search(r"Terms\s*of\s*Trade\s*[:\.]*\s*([A-Z]{3,4})", text, flags=re.I)
    if m:
        inv.incoterm = m.group(1).upper()

    # Total + currency
    m = re.search(
        rf"Total\s*[:\.]*\s*({'|'.join(CURRENCY_CODES)})\s*([\d.,]+)", text, flags=re.I,
    )
    if m:
        inv.currency = m.group(1).upper()
        inv.total_amount = _to_float(m.group(2))
    else:
        m = re.search(
            rf"Total\s*[:\.]*\s*([\d.,]+)\s*({'|'.join(CURRENCY_CODES)})", text, flags=re.I,
        )
        if m:
            inv.total_amount = _to_float(m.group(1))
            inv.currency = m.group(2).upper()

    # HS code, aggressively exclude AWB, phone numbers, invoice numbers
    awb_digits = _digits_only(inv.awb_number) or ""
    inv_digits = _digits_only(inv.invoice_number) if inv.invoice_number else ""

    hs_candidates = re.findall(r"\b(\d{8,10})\b", text)
    for c in hs_candidates:
        # Exclude known non-HS digit strings
        if awb_digits and c == awb_digits:
            continue
        if inv_digits and c == inv_digits:
            continue
        # Phone / postal: starts with 0 or too many leading zeros
        if c.startswith("0"):
            continue
        # Check chapter plausibility (01-99)
        ch = int(c[:2])
        if 1 <= ch <= 99:
            inv.lines.append(Line(item_no=1, hs_code=c))
            break

    return inv


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

def _parse_generic(text: str) -> Invoice:
    inv = Invoice(invoice_format="generic")

    # Invoice number
    m = re.search(
        r"(?:Invoice|Facture)\s*(?:N[o°\.]*|Number)\s*[:\.\-]*\s*([A-Z0-9\-/]{3,30})",
        text, flags=re.I,
    )
    if m:
        inv.invoice_number = m.group(1)

    # Currency and total, try several patterns
    # 1. Currency code followed by amount at end of line
    for cur in CURRENCY_CODES:
        m = re.search(rf"\b{cur}\b\s*([\d.,]+)\s*$", text, flags=re.I | re.M)
        if m:
            val = _to_float(m.group(1))
            if val and val > 0:
                inv.currency = cur
                inv.total_amount = val
                break

    # 2. TOTAL row with decimal amount
    if inv.total_amount is None:
        m = re.search(r"TOTAL[^\n]*?([\d][\d.,]*\.\d{2})", text, flags=re.I)
        if m:
            inv.total_amount = _to_float(m.group(1))

    # 3. Standalone currency amount in the document
    if inv.total_amount is None:
        for cur in CURRENCY_CODES:
            for m in re.finditer(rf"([\d\s.,]{{4,15}})\s*{cur}", text, flags=re.I):
                v = _to_float(m.group(1))
                if v and v > 0:
                    inv.currency = cur
                    inv.total_amount = v
                    break
            if inv.total_amount is not None:
                break

    # 4. Currency symbol € + amount
    if inv.total_amount is None:
        m = re.search(r"€\s*([\d,]+\.\d{2})", text)
        if m:
            inv.currency = "EUR"
            inv.total_amount = _to_float(m.group(1))

    # HS code
    hs = _first(r"\b(\d{8,10})\b", text)
    if hs:
        inv.lines.append(Line(item_no=1, hs_code=hs))

    return inv


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def parse_invoice(text: str, source_file: Optional[str] = None,
                  hint: Optional[str] = None) -> Invoice:
    """Parse one commercial invoice from its full text."""
    fmt = hint or _detect_format(text)
    if fmt == "entity":
        inv = _parse_entity(text)
    elif fmt == "entity_proforma":
        inv = _parse_entity_proforma(text)
    elif fmt == "entity_delivery_note":
        inv = _parse_entity_delivery_note(text)
    elif fmt == "dhl_commercial":
        inv = _parse_dhl_commercial(text)
    else:
        inv = _parse_generic(text)
    inv.source_file = source_file
    return inv
