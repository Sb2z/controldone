"""Parse forwarder invoices (facture de prestation) containing duties/taxes.

Supports three formats :
  - DHL Express ("FACTURE DE DROITS ET TAXES A L'IMPORTATION")
  - Schenker France SAS
  - DSV Air & Sea SAS

v3.1 improvements
-----------------
DHL:
  * dd_total / tva_total / at_total: multiple alternative patterns to handle
    OCR linearisation of the 3-column table (Z/C suffix, EUR label variants).
  * Parse MRN also from embedded declaration pages in the same PDF.

Schenker / DSV:
  * Better total_debours: try 'Total Débours', 'Total debours', 'DEBOURS',
    and also the sum DD + AT + TVA if no explicit label found.
  * AWB: handle format '176/EK 23456344' (with space inside AWB number).
  * Also extract AWB from 'N° de connaissement' and 'N° LTA'.

All formats:
  * If total_debours is not explicitly given, compute DD + AT + TVA.
  * Search for MRN on any attached declaration pages (full-text scan).
"""
from __future__ import annotations

import re
from typing import List, Optional

from controldone.adapters.models import Prestation, PrestationLine


# ---------------------------------------------------------------------------
# Helpers
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
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _first(pattern: str, text: str, flags: int = re.I | re.S) -> Optional[str]:
    m = re.search(pattern, text, flags=flags)
    return m.group(1).strip() if m else None


def detect_forwarder(text: str) -> Optional[str]:
    up = text.upper()
    if "DHL EXPRESS" in up or ("FACTURE DE DROITS ET TAXES" in up and "DHL" in up):
        return "DHL"
    if "SCHENKER FRANCE" in up or "SCHENKER" in up:
        return "Schenker"
    if "DSV AIR" in up or "DSV SERV" in up:
        return "DSV"
    return None


MRN_REGEX = re.compile(r"\b(\d{2}[A-Z]{2}[A-Z0-9]{12,16})\b")


def _collect_mrns(text: str, existing: List[str]) -> List[str]:
    """Append all MRNs found in text that are not already in existing."""
    for m in MRN_REGEX.finditer(text):
        mrn = m.group(1)
        if mrn not in existing:
            existing.append(mrn)
    return existing


# ---------------------------------------------------------------------------
# DHL Express
# ---------------------------------------------------------------------------

def _parse_dhl(text: str) -> Prestation:
    p = Prestation(forwarder="DHL", currency="EUR")
    p.invoice_number = _first(r"Num[ée]ro de Facture\s*:?\s*([A-Z0-9\-]{5,30})", text)
    p.invoice_date = _first(r"Date de Facture\s*:?\s*(\d{2}[\-/]\d{2}[\-/]\d{4})", text)
    p.forwarder_vat = _first(r"TVA\s*FR\s*(\d{11})", text) or _first(
        r"Code TVA\s*FR\s*(\d{11})", text
    )

    # ---- Aggregated amounts — try primary then fallback patterns --------
    # The DHL 3-column table typically linearises as:
    #   "Droits de Douane\n136,00\nZ\n..."
    # or on one line: "Droits de Douane  136,00 Z"
    # Trailing markers: Z = zero-rated, C = standard VAT, EUR = currency label

    p.dd_total = _extract_dhl_amount(
        text,
        [
            r"Droits de Douane\s+([\d.,\s]+?)\s*(?:Z|C|EUR|\n)",
            r"Droits de Douane\s*\n\s*([\d.,]+)",
            r"DROIT(?:S)? DE DOUANE[^\n]*\n?\s*([\d.,]+)",
        ],
    )
    p.tva_total = _extract_dhl_amount(
        text,
        [
            r"TVA à l['' ]importation\s+([\d.,\s]+?)\s*(?:Z|C|EUR|\n)",
            r"TVA [àa] l[''`]importation\s*\n\s*([\d.,]+)",
            r"TVA\s+importation[^\n]*\n?\s*([\d.,]+)",
            r"T\.V\.A[^\n]*\n?\s*([\d.,]+)",
        ],
    )
    p.at_total = _extract_dhl_amount(
        text,
        [
            r"Autres Taxes\s+([\d.,\s]+?)\s*(?:Z|C|EUR|\n)",
            r"Autres Taxes\s*\n\s*([\d.,]+)",
            r"AUTRES TAXES[^\n]*\n?\s*([\d.,]+)",
            r"Taxes diverses\s*\n?\s*([\d.,]+)",
        ],
    )
    p.total_surcharges = _to_float(
        _first(r"Montant Total des Surcharges\s*([\d.,\s]+?)\s", text)
    )

    # Totals HT / TTC
    m = re.search(
        r"Montant Total\s*\(EUR\)\s*([\d.,\s]+?)\s+([\d.,]+?)\s+([\d.,]+)",
        text, flags=re.I,
    )
    if m:
        p.total_facture_ht = _to_float(m.group(1))
        p.total_facture_ttc = _to_float(m.group(3))

    if p.total_facture_ttc is None:
        p.total_facture_ttc = _to_float(
            _first(r"Montant Total TTC\s*([\d.,\s]+)", text)
        )
    if p.total_facture_ttc is None:
        # Another DHL layout: "Total EUR: 140,00"
        p.total_facture_ttc = _to_float(_first(r"Total EUR\s*:?\s*([\d.,]+)", text))

    # Débours = DD + TVA + AT (sum what we have)
    p.total_debours = _compute_debours(p)

    # ---- AWB + MRN breakdown (page-2 table) ----------------------------
    for m in re.finditer(
        r"(\d{8,12})\s+([0-9]{2}[A-Z]{2}[A-Z0-9]{12,16})\s+(\d{2}[-/]\d{2}[-/]\d{4})\s*",
        text,
    ):
        line = PrestationLine()
        line.awb_number = m.group(1)
        line.mrn = m.group(2)
        line.declaration_date = m.group(3)
        p.lines.append(line)
        if line.awb_number not in p.awb_numbers:
            p.awb_numbers.append(line.awb_number)
        if line.mrn not in p.mrn_references:
            p.mrn_references.append(line.mrn)

    # Fallback MRN from anywhere in text
    if not p.mrn_references:
        _collect_mrns(text, p.mrn_references)

    # HS + duty detail per line
    for m in re.finditer(
        r"(\d{10})\s+([\d.,]+)\s+Droits de Douane\s+([\d.,]+)\s+([\d.,]+)",
        text, flags=re.I,
    ):
        hs, base, rate, amt = m.group(1), m.group(2), m.group(3), m.group(4)
        target = p.lines[-1] if p.lines else PrestationLine()
        target.hs_code = hs
        target.base_dd = _to_float(base)
        target.dd_amount = _to_float(amt)
        if target not in p.lines:
            p.lines.append(target)
        seg = text[m.end(): m.end() + 400]
        mtva = re.search(r"TVA [àa] l['' ]importation\s+([\d.,]+)\s+([\d.,]+)", seg, flags=re.I)
        if mtva:
            target.base_tva = _to_float(mtva.group(1))
            target.tva_amount = _to_float(mtva.group(2))
        mat = re.search(r"Autres Taxes\s+([\d.,]+)\s+([\d.,]+)", seg, flags=re.I)
        if mat:
            target.at_amount = _to_float(mat.group(2))
        mttc = re.search(r"Total\s*EUR\s*:?\s*([\d.,]+)", seg, flags=re.I)
        if mttc:
            target.total_ttc = _to_float(mttc.group(1))

    return p


def _extract_dhl_amount(text: str, patterns: List[str]) -> Optional[float]:
    """Try each pattern in order; return the first valid non-zero float."""
    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if m:
            v = _to_float(m.group(1))
            if v is not None:
                return v
    return None


def _compute_debours(p: Prestation) -> Optional[float]:
    """Compute total débours = DD + AT + TVA if not already set explicitly."""
    if p.total_debours is not None:
        return p.total_debours
    components = [x for x in (p.dd_total, p.at_total, p.tva_total) if x is not None]
    if components:
        return round(sum(components), 2)
    return None


# ---------------------------------------------------------------------------
# Schenker / DSV (shared template)
# ---------------------------------------------------------------------------

def _parse_schenker(text: str) -> Prestation:
    return _parse_schenker_or_dsv(text, "Schenker")


def _parse_dsv(text: str) -> Prestation:
    return _parse_schenker_or_dsv(text, "DSV")


def _parse_schenker_or_dsv(text: str, forwarder: str) -> Prestation:
    """Schenker and DSV use the same invoice template."""
    p = Prestation(forwarder=forwarder, currency="EUR")

    # Invoice number
    p.invoice_number = (
        _first(r"N°\s*Facture\s*:?\s*([A-Z0-9\-]{5,30})", text)
        or _first(r"Facture No\.?\s*:?\s*([A-Z0-9\-]{5,30})", text)
        or _first(r"FACTURE\s*N°\s*([A-Z0-9\-]{5,30})", text)
    )
    p.invoice_date = _first(
        r"Date Facture\s*:?\s*([0-9]{1,2}[\-/][A-Za-zéû]{3,6}[\-/]?\s*[-]?\s*\d{2,4})", text
    )

    # Forwarder VAT
    p.forwarder_vat = _first(r"TVA-?Id:\s*(FR\d{11})", text)

    # AWB — handle "176/EK 23456344" (with space) and "172/CV00059264" (no space)
    awb_raw = _first(
        r"AWB\s*No\s*:?\s*([0-9]{3}/[A-Z]{2}[\s]?[0-9\s]{6,12})", text
    )
    if awb_raw:
        awb_clean = re.sub(r"\s+", "", awb_raw)
        if awb_clean not in p.awb_numbers:
            p.awb_numbers.append(awb_clean)

    # Also look for N° LTA or N° connaissement
    for pat in (
        r"N[°o]\s*(?:LTA|de connaissement|transport)\s*[:\-]?\s*([A-Z0-9\-/\s]{6,30})",
        r"LTA\s*[:\-]?\s*([A-Z0-9\-/]{6,20})",
    ):
        alt_awb = _first(pat, text)
        if alt_awb:
            alt_clean = re.sub(r"\s+", "", alt_awb)
            if alt_clean and alt_clean not in p.awb_numbers:
                p.awb_numbers.append(alt_clean)

    # Amounts
    p.dd_total = _to_float(_first(r"DROIT DE DOUANE\s*([\d.,]+)", text))
    if p.dd_total is None:
        p.dd_total = _to_float(_first(r"Droits de douane\s*([\d.,]+)", text))

    p.at_total = _to_float(_first(r"TAXES DIVERSES DOUANE\s*([\d.,]+)", text))
    if p.at_total is None:
        p.at_total = _to_float(_first(r"Taxes diverses\s*([\d.,]+)", text))

    p.tva_total = _to_float(_first(r"TVA\s*[àa]\s*l['' ]importation\s*([\d.,]+)", text))
    if p.tva_total is None:
        p.tva_total = _to_float(_first(r"T\.V\.A\.?\s*([\d.,]+)", text))

    # Total débours — try multiple label variants
    p.total_debours = (
        _to_float(_first(r"Total\s+D[eé]bours?\s*([\d.,]+)", text))
        or _to_float(_first(r"TOTAL\s+D[EÉ]BOURS?\s*([\d.,]+)", text))
        or _to_float(_first(r"D[eé]bours?\s+Total\s*([\d.,]+)", text))
        or _to_float(_first(r"Montant D[eé]bours?\s*([\d.,]+)", text))
    )

    # Fallback: compute if not found explicitly
    if p.total_debours is None:
        p.total_debours = _compute_debours(p)

    # Total facture
    p.total_facture_ttc = (
        _to_float(_first(r"Total\s*Montant\s*Facture\s*([\d.,]+)", text))
        or _to_float(_first(r"MONTANT\s*TOTAL\s*FACTURE\s*([\d.,]+)", text))
        or _to_float(_first(r"Total\s*TTC\s*([\d.,]+)", text))
    )
    if p.total_facture_ht is None:
        p.total_facture_ht = p.total_debours

    # MRN from "IMA <MRN>" line (Schenker/DSV attachment)
    for m in re.finditer(r"IMA\s+([A-Z0-9]{15,30})", text):
        ref = m.group(1).strip()
        if ref not in p.mrn_references:
            p.mrn_references.append(ref)
    # Full-MRN fallback
    if not any(len(r) >= 18 for r in p.mrn_references):
        _collect_mrns(text, p.mrn_references)

    # Synthetic single line
    line = PrestationLine(
        awb_number=p.awb_numbers[0] if p.awb_numbers else None,
        mrn=p.mrn_references[0] if p.mrn_references else None,
        dd_amount=p.dd_total,
        tva_amount=p.tva_total,
        at_amount=p.at_total,
        total_ttc=p.total_facture_ttc or p.total_debours,
    )
    p.lines.append(line)

    return p


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def parse_prestation(text: str, source_file: Optional[str] = None,
                     forwarder: Optional[str] = None) -> Prestation:
    fwd = forwarder or detect_forwarder(text) or "Unknown"
    if fwd == "DHL":
        p = _parse_dhl(text)
    elif fwd == "Schenker":
        p = _parse_schenker(text)
    elif fwd == "DSV":
        p = _parse_dsv(text)
    else:
        p = Prestation(forwarder=fwd)

    # If still no debours, try computing from components
    if p.total_debours is None:
        p.total_debours = _compute_debours(p)

    p.source_file = source_file
    return p
