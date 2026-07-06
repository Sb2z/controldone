"""Parse AKANEA Delta IE customs declarations.

This is the format produced by Akanea Douane software (vs the DHL Delta IE
format which has a different layout). Identifiable by the header
"DÉCLARATION STANDARD ÉDITION AKANEA DOUANE" or the footer "AKANEA / DELTA IE".

Layout reference (from a real declaration)
------------------------------------------
Page 1 — header, intervenants, transport, document references, totals
Page 2 — per-article: nomenclature, weights, values, liquidation
Page 3 — annexe (barcode, identifier)
"""
from __future__ import annotations

import re
from typing import Optional

from controldone.models import Document, Line, Party
from controldone.formats.common import (
    to_float, first_match, all_matches,
    find_mrn, find_all_mrns, find_vat_fr, parse_date_to_iso,
)


def parse(text: str, source_file: Optional[str] = None,
          source_pages=None) -> Document:
    """Parse an AKANEA Delta IE declaration into a Document."""
    d = Document(
        kind="declaration",
        format="delta_ie_akanea",
        source_file=source_file,
        source_pages=source_pages or [],
        text=text,
    )

    # ----- Identifiers -----
    d.mrn = (
        first_match(r"MRN\s*:\s*([A-Z0-9]{15,20})", text)
        or find_mrn(text)
    )
    d.lrn = first_match(r"N°\s*de\s*référence\s*\(LRN\)\s*:\s*([A-Z0-9]+)", text)
    d.extras["crn"] = first_match(r"N°\s*déclaration\s*\(CRN\)\s*:\s*([A-Z0-9]+)", text)

    # ----- Date validation/BAE -----
    val_date = first_match(r"Date\s*et\s*heure\s*de\s*validation\s*:\s*([\d/]+)", text)
    if val_date:
        d.invoice_date = parse_date_to_iso(val_date)

    # ----- Total amount + currency -----
    m = re.search(
        r"Montant\s+total\s+facturé\s*:\s*([\d\s.,]+?)\s*\(?([A-Z]{3})\)?",
        text, flags=re.I,
    )
    if m:
        d.total_amount = to_float(m.group(1))
        d.currency = m.group(2).upper()

    # FX rate
    fx = first_match(r"Taux\s+de\s+change\s*:\s*([\d.,]+)", text)
    if fx:
        d.fx_rate = to_float(fx)

    # ----- Total weight -----
    d.gross_weight_kg = to_float(first_match(
        r"Masse\s+brute\s+totale\s*\(kg\)\s*:\s*([\d.,]+)", text,
    ))

    # ----- Customs amounts (LIQUIDATION TOTALE) -----
    # Block usually:
    #   T.Nat T.com - Catég Montant Statut
    #   A445  B00 - TVA  1 667.00 6
    #   M830  NAT - AUTRES  5.00 1
    #   U165  A00 - DD  891.00 1
    #   Total 896.00
    _parse_akanea_liquidation_total(text, d)

    # Explicit duties at top-level (override if present)
    tva_al = first_match(r"TVA\s+autoliquid[ée]e\s*:\s*([\d\s.,]+)", text)
    if tva_al:
        d.tva_auto_liquidee = to_float(tva_al)

    tg = first_match(r"Montant\s+total\s+à\s+payer\s*:\s*([\d\s.,]+)", text)
    if tg:
        d.tg = to_float(tg)

    # ----- Parties -----
    d.exporter = _parse_party_block(text, "EXPORTATEUR")
    d.importer = _parse_party_block(text, "IMPORTATEUR")
    d.declarant = _parse_party_block(text, "DÉCLARANT|DECLARANT")
    d.representative = _parse_party_block(text, "REPRÉSENTANT|REPRESENTANT")

    # VAT (REFERENCE FISCALE)
    vat = (
        first_match(r"FR7\s*-\s*(FR\d{11})", text)
        or find_vat_fr(text)
    )
    if vat:
        d.importer.vat = d.importer.vat or vat

    # ----- Countries / incoterm -----
    d.destination_country = first_match(r"Destination\s*:\s*([A-Z]{2})\b", text)
    d.origin_country = (
        first_match(r"Pays\s+d'origine\s*:\s*([A-Z]{2})\b", text)
        or first_match(r"Expédition\s*:\s*([A-Z]{2})\b", text)
    )
    inco = first_match(r"INCOTERM\s*:\s*([A-Z]{3})\b", text)
    if inco:
        d.incoterm = inco
        place = first_match(r"INCOTERM\s*:\s*[A-Z]{3}\s+([A-Z\-\s]+?)\s*$", text, flags=re.I | re.M)
        if place:
            d.incoterm_place = place.strip()

    # ----- Document references (Box 44) -----
    # N380 - CJP4132 / N785 - 329895 / N741 - 131/22512033
    for label, target in [
        ("N380", "referenced_invoices"),
        ("N785", "referenced_mrns"),  # previous declaration
        ("N741", "referenced_awbs"),
        ("N740", "referenced_awbs"),
        ("N830", "referenced_invoices"),
        ("N935", "referenced_invoices"),
        ("N325", "referenced_invoices"),  # proforma
    ]:
        for m in re.finditer(
            rf"\b{label}\b\s*[\-:,]\s*([A-Z0-9][A-Z0-9\-/.]{{2,40}})",
            text, flags=re.I,
        ):
            ref = m.group(1).strip().rstrip(",;:")
            lst = getattr(d, target)
            if ref and ref not in lst:
                lst.append(ref)

    # AWB primary value: first referenced AWB
    if d.referenced_awbs and not d.awb:
        d.awb = d.referenced_awbs[0]

    # ----- Per-article extraction -----
    _parse_akanea_articles(text, d)

    # Aggregate weights from articles if not already set
    if d.net_weight_kg is None:
        nets = [l.net_weight_kg for l in d.lines if l.net_weight_kg is not None]
        if nets:
            d.net_weight_kg = round(sum(nets), 3)
    if d.gross_weight_kg is None:
        gross = [l.gross_weight_kg for l in d.lines if l.gross_weight_kg is not None]
        if gross:
            d.gross_weight_kg = round(sum(gross), 3)

    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AKANEA_LIQ_CODES = {
    "U165": "dd",
    "M830": "at",
    "M195": "at",
    "A445": "tva_auto_liquidee",
}


def _parse_akanea_liquidation_total(text: str, d: Document) -> None:
    """Extract the LIQUIDATION TOTALE block on the first page.

    Akanea exports the table in column-major order, e.g.:
        LIQUIDATION TOTALE
        T.Nat               <- column 1 header
        T.com - Catég       <- column 2 header
        Montant             <- column 3 header
        Statut              <- column 4 header
        A445                <- row 1 col 1
        B00 - TVA           <- row 1 col 2
        1 667.00            <- row 1 col 3
        6                   <- row 1 col 4
        M830                <- row 2 col 1
        NAT - AUTRES        <- row 2 col 2
        5.00                <- row 2 col 3
        1                   <- row 2 col 4
        ...
        Total
        896.00
    """
    m = re.search(
        r"LIQUIDATION\s+TOTALE\s*\n(.*?)(?=Montant\s+total\s+facturé|Montant\s+total\s+à\s+payer|GARANTIE|\Z)",
        text, flags=re.I | re.S,
    )
    if not m:
        return
    block = m.group(1)
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]

    # Locate codes (T.Nat values) — they all match [UAMG]\d{3}
    code_indices = [
        i for i, ln in enumerate(lines)
        if re.fullmatch(r"[UAMGE]\d{3}", ln)
    ]
    for i in code_indices:
        code = lines[i].upper()
        # row layout: code, "X00 - LABEL", "amount", "status"
        # but sometimes only 3 cells (no statut), so we look at the next 2-3 lines
        amount = None
        for j in range(i + 1, min(i + 4, len(lines))):
            v = to_float(lines[j])
            if v is not None and v < 1_000_000:
                # Skip pure 1-2 digit "Statut" values (typically 1, 6, etc.) by
                # picking the largest plausible amount in the row window.
                # Heuristic: amounts with decimals or > 9 are taxes; small ints
                # are status codes.
                if v >= 9 or "." in lines[j] or "," in lines[j]:
                    amount = v
                    break
        attr = _AKANEA_LIQ_CODES.get(code)
        if attr and amount is not None and getattr(d, attr) is None:
            setattr(d, attr, amount)

    # Total line — "Total\n896.00"
    for i, ln in enumerate(lines):
        if ln.lower() == "total" and i + 1 < len(lines):
            v = to_float(lines[i + 1])
            if v is not None:
                d.tg = d.tg or v
                break


def _parse_party_block(text: str, label_alt: str) -> Party:
    """Extract a party block.

    Pattern: 'IMPORTATEUR : <vat/eori> - <name>' or 'IMPORTATEUR : <name>'
    Often followed by an address line.
    """
    m = re.search(
        rf"\b(?:{label_alt})\s*:\s*([^\n]+)",
        text, flags=re.I,
    )
    if not m:
        return Party()
    line = m.group(1).strip()
    p = Party()

    # vat/eori - name
    m2 = re.match(r"([A-Z]{2}\d{9,17})\s*[-–]\s*(.+)$", line, flags=re.I)
    if m2:
        ref = m2.group(1).upper()
        p.eori = ref
        if re.match(r"FR\d{11}$", ref):
            p.vat = ref
        p.name = m2.group(2).strip()
    else:
        m3 = re.match(r"([A-Z]{2}\d{9,17})$", line, flags=re.I)
        if m3:
            p.eori = m3.group(1).upper()
        else:
            p.name = line

    return p


def _parse_akanea_articles(text: str, d: Document) -> None:
    """Parse 'INFORMATIONS GÉNÉRALES DE L'ARTICLE N°X' blocks."""
    blocks = re.split(
        r"(?=INFORMATIONS\s+GÉN[ÉE]RALES\s+DE\s+L[''']?ARTICLE\s+N[°o]?\s*\d+)",
        text, flags=re.I,
    )
    art_idx = 0
    for blk in blocks:
        if not re.search(r"INFORMATIONS\s+GÉN[ÉE]RALES\s+DE\s+L[''']?ARTICLE\s+N[°o]?\s*\d+", blk, re.I):
            continue
        art_idx += 1
        line = Line(item_no=art_idx)
        line.amount = to_float(first_match(
            r"Montant\s+article\s+factur[ée]\s*:\s*([\d\s.,]+)", blk,
        ))
        line.gross_weight_kg = to_float(first_match(
            r"Masse\s+brute\s*:\s*([\d.,]+)\s*kg", blk,
        ))
        line.net_weight_kg = to_float(first_match(
            r"Masse\s+nette\s*:\s*([\d.,]+)\s*kg", blk,
        ))
        line.hs_code = first_match(
            r"Nomenclature\s*:\s*(\d{8,10})", blk,
        )
        line.description = first_match(
            r"Désignation\s+commerciale\s*:\s*([^\n]+)", blk,
        )
        line.origin_country = first_match(
            r"Pays\s+d'origine\s*:\s*([A-Z]{2})\b", blk,
        )
        line.preference = first_match(
            r"Préf[ée]rence\s*:\s*(\d+)", blk,
        )
        line.quantity = to_float(first_match(
            r"Unités\s+supplémentaires\s*:\s*([\d.,]+)", blk,
        ))
        line.currency = d.currency
        d.lines.append(line)
