"""Parse customs declarations - supports DHL Delta IE, DELTA H7, and DAU/SAD.

Public entry point: parse_declaration(text, source_file=None)
The dispatcher picks the right sub-parser based on format markers.

v3.1 improvements
-----------------
Delta IE:
  * Extract ALL articles (loop on ARTICLE N°X blocks), not just the first.
  * Better LIQUIDATION table: codes U165/M195/A445 with per-article amounts.
  * Multiple MRN support from DOCUMENT PRECEDENT blocks.

H7:
  * Improved Box 34 (origin country) extraction — multiple pattern attempts.
  * Improved Box 22 (amount) with broader OCR-tolerance patterns.

DAU:
  * Better Box 47 (DD/AT/TG) from DONNÉES COMPTABLES table.
  * Better Box 44 (N380 invoice number) extraction.

All formats:
  * VAT number extraction from REFERENCE FISCALES : FR7 FRxxx
  * Graceful fallback (None) for any missing field — never crashes.
"""
from __future__ import annotations

import re
from typing import List, Optional

from controldone.adapters.models import Declaration, Line, Party

CURRENCY_RE = r"EUR|USD|GBP|CHF|CAD|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    # Handle both 1,234.56 and 1 234,56 styles
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


def _all(pattern: str, text: str, flags: int = re.I | re.S):
    return re.findall(pattern, text, flags=flags)


MRN_REGEX = re.compile(r"\b(\d{2}[A-Z]{2}[A-Z0-9]{12,16})\b")


def _find_mrn(text: str) -> Optional[str]:
    m = MRN_REGEX.search(text)
    return m.group(1) if m else None


def _find_all_mrns(text: str) -> List[str]:
    seen: List[str] = []
    for m in MRN_REGEX.finditer(text):
        mrn = m.group(1)
        if mrn not in seen:
            seen.append(mrn)
    return seen


# ---------------------------------------------------------------------------
# DHL Delta IE parser
# ---------------------------------------------------------------------------

def _parse_delta_ie(text: str) -> Declaration:
    d = Declaration(declaration_format="delta_ie")

    d.mrn = _find_mrn(text) or _first(r"MRN\s*:?\s*([A-Z0-9]{15,20})", text)
    d.lrn = _first(r"(?:LRN|NUMERO DE REFERENCE\s*\(LRN\))\s*:?\s*([A-Z0-9]{10,25})", text)

    d.regime = _first(r"REGIME\s*:?\s*([\d\s]{5,11})", text)
    if d.regime:
        d.regime = d.regime.strip()

    # ---------- Multi-article extraction -----------------------------------
    # Split on ARTICLE N°X blocks
    article_blocks = _split_article_blocks(text)
    if not article_blocks:
        article_blocks = [text]  # treat entire text as one article

    art_amounts = []
    for art_idx, block in enumerate(article_blocks, start=1):
        # HS code for this article
        hs = _extract_hs_from_block(block)
        # Weight per article
        net_w = _to_float(_first(r"MASSE NETTE\s*:?\s*([\d\s.,]+)\s*(?:Kg|kg|KG)?", block))
        gross_w = _to_float(_first(
            r"MASSE BRUT(?:E)?(?:\s+TOTALE)?\s*(?:\(KG\))?\s*:?\s*([\d\s.,]+)\s*(?:Kg|kg|KG)?",
            block,
        ))
        # Amount per article
        m_amt = re.search(
            rf"MONTANT ARTICLE FACTURE\s*:.*?([\d.,\s]+?)\s+({CURRENCY_RE})",
            block, flags=re.S | re.I,
        )
        amount = None
        currency = None
        if m_amt:
            amount = _to_float(m_amt.group(1))
            currency = m_amt.group(2)
            if amount is not None:
                art_amounts.append((amount, currency))

        # Origin per article
        origin = _first(r"PAYS D'ORIGINE\s*:?\s*([A-Z]{2})\b", block)

        line = Line(
            item_no=art_idx,
            hs_code=hs,
            origin_country=origin,
            net_weight_kg=net_w,
            gross_weight_kg=gross_w,
            amount=amount,
            currency=currency,
        )
        d.lines.append(line)

    # Aggregate weights and total amount
    if art_amounts:
        d.total_amount = round(sum(v for v, _ in art_amounts), 2)
        d.currency = art_amounts[0][1]
    else:
        # fallback — scan full text
        m = re.search(
            rf"MONTANT TOTAL A PAYER\s*:?\s*\n\s*([\d.,\s]+?)\s+({CURRENCY_RE})",
            text, flags=re.I,
        )
        if m:
            d.total_amount = _to_float(m.group(1))
            d.currency = m.group(2)

    # If only one article was detected and no HS found, try the old full-text patterns
    if d.lines and d.lines[0].hs_code is None:
        hs = _first(r"NOMENCLATURE\s*:\s*\n(?:DESIGNATION COMMERCIALE\s*:\s*\n)?(\d{8,10})", text)
        if not hs:
            hs = _first(r"Code des marchandises\s*\n?\s*(\d{8,10})", text)
        if hs:
            d.lines[0].hs_code = hs

    # Global weights (aggregate across articles)
    all_net = [l.net_weight_kg for l in d.lines if l.net_weight_kg is not None]
    all_gross = [l.gross_weight_kg for l in d.lines if l.gross_weight_kg is not None]
    if all_net:
        d.net_weight_kg = round(sum(all_net), 3)
    else:
        d.net_weight_kg = _to_float(_first(r"MASSE NETTE\s*:?\s*([\d\s.,]+)\s*(?:Kg|kg|KG)?", text))
    if all_gross:
        d.gross_weight_kg = round(sum(all_gross), 3)
    else:
        d.gross_weight_kg = _to_float(_first(
            r"MASSE BRUT(?:E)?(?:\s+TOTALE)?\s*(?:\(KG\))?\s*:?\s*([\d\s.,]+)\s*(?:Kg|kg|KG)?",
            text,
        ))

    # TG from TG label or "xxx EUR \n Montant à couvrir"
    m = re.search(r"([\d.,]+)\s*EUR\s*\n\s*Montant à couvrir", text, flags=re.I)
    if m:
        d.tg = _to_float(m.group(1))

    # Incoterm
    inco = _first(r"INCOTERM\s*:?\s*([A-Z]{3})\s+([^\n\r]+)?", text)
    if inco:
        d.incoterm = inco
        place = _first(r"INCOTERM\s*:?\s*[A-Z]{3}\s+([^\n\r]+)", text)
        if place:
            d.incoterm_place = place.strip()

    # Countries
    d.destination_country = _first(r"DESTINATION\s*:?\s*([A-Z]{2})\b", text)
    d.origin_country = (
        _first(r"PAYS D'ORIGINE\s*:?\s*([A-Z]{2})\b", text)
        or _first(r"EXPEDITION\s*:?\s*([A-Z]{2})\b", text)
    )

    # N380 accompanying docs — may be multiple
    for m in re.finditer(r"N380\s*[,:\s]\s*([A-Z0-9\-/]{3,40})", text, flags=re.I):
        ref = m.group(1).strip().rstrip(",;:")
        if ref and ref not in d.accompanying_docs:
            d.accompanying_docs.append(ref)

    # N740 transport doc (AWB)
    awb = _first(r"N740\s*[,:Z\s]+([A-Z0-9\-/]{5,40})", text)
    if awb:
        d.transport_doc = awb.rstrip(",;:")

    # N785 previous doc — may reference multiple MRNs across articles
    prev = _first(r"N785\s*[,:\s]\s*([A-Z0-9\-/]{3,40})", text)
    if prev:
        d.previous_doc = prev.rstrip(",;:")

    # Parties
    d.exporter = _extract_party(text, "EXPORTATEUR")
    d.destinataire = _extract_party(text, "DESTINATAIRE")
    d.importer = _extract_party(text, "IMPORTATEUR") or d.destinataire
    d.declarant = _extract_party(text, "DECLARANT") or d.declarant

    if d.destinataire and d.destinataire.eori:
        if not d.importer.eori:
            d.importer.eori = d.destinataire.eori

    # VAT number — REFERENCE FISCALES : FR7 FRxxx
    vat = (
        _first(r"FR7\s*[,\s]\s*(FR\d{11})", text)
        or _first(r"REFERENCE(?:S)?\s+FISC(?:ALES?)?\s*:.*?(FR\d{11})", text)
        or _first(r"\b(FR\d{11})\b", text)
    )
    if vat:
        d.importer.vat = vat

    # Liquidation — primary: labeled values; fallback: tabular LIQUIDATION block
    d.dd = _to_float(_first(r"\bDD\s+([\d\s.,]+)", text))
    d.dump = _to_float(_first(r"\bDUMP\s+([\d\s.,]+)", text))
    d.at = _to_float(_first(r"\bAT\s+([\d\s.,]+)", text))
    if d.tg is None:
        d.tg = _to_float(_first(r"\bTG\s+([\d\s.,]+)", text))
    d.tva_auto_liquidee = _to_float(_first(r"TVA AUTO LIQUID[EÉ]E?\s*:?\s*([\d\s.,]+)", text))

    if d.dd is None or d.at is None:
        _extract_article_liquidation(text, d)

    return d


def _split_article_blocks(text: str) -> List[str]:
    """Split text on ARTICLE N°X markers, returning one block per article."""
    pattern = re.compile(r"(?:^|\n)\s*ARTICLE\s+(?:N[°o]?\s*)?\d+(?:\s*/\s*\d+)?", re.I)
    positions = [m.start() for m in pattern.finditer(text)]
    if not positions:
        return []
    blocks = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        blocks.append(text[pos:end])
    return blocks


def _extract_hs_from_block(block: str) -> Optional[str]:
    """Extract HS code from a single article block."""
    hs = _first(r"NOMENCLATURE\s*:\s*\n(?:DESIGNATION COMMERCIALE\s*:\s*\n)?(\d{8,10})", block)
    if not hs:
        hs = _first(r"Code des marchandises\s*\n?\s*(\d{8,10})", block)
    if not hs:
        # More permissive: any 8-10 digit sequence after the NOMENCLATURE label
        hs = _first(r"NOMENCLATURE\s*:?\s*\n?[^\d]*(\d{8,10})", block)
    return hs


# ---------------------------------------------------------------------------
# DELTA H7 parser
# ---------------------------------------------------------------------------

def _parse_h7(text: str) -> Declaration:
    d = Declaration(declaration_format="h7")

    d.mrn = _find_mrn(text)

    # Box 22 Monnaie et montant total facturé — try multiple patterns
    m = re.search(
        r"22[\.\s]*Monnaie et montant total\s*factur[eé]\s*\n?\s*([A-Z]{3})\s*[\n\s]+([\d\s.,]+)",
        text, flags=re.I,
    )
    if m:
        d.currency = m.group(1).upper()
        d.total_amount = _to_float(m.group(2))

    if not d.total_amount:
        # Broader OCR-tolerant pattern for Box 22
        m = re.search(
            rf"22[^\n]{{0,60}}({CURRENCY_RE})\s*[\n\s]+([\d\s.,]{{3,20}})",
            text, flags=re.I,
        )
        if m:
            d.currency = m.group(1).upper()
            d.total_amount = _to_float(m.group(2))

    if not d.total_amount:
        # Absolute fallback: look for prominent EUR/currency + amount pair
        m = re.search(
            rf"({CURRENCY_RE})\s+([\d\s.,]{{4,15}})(?=\s|\n)",
            text, flags=re.I,
        )
        if m:
            d.currency = m.group(1).upper()
            d.total_amount = _to_float(m.group(2))

    # Box 35 Masse brute
    d.gross_weight_kg = _to_float(_first(r"35\s*Masse brute\s*\(kg\)\s*\n?\s*([\d.,]+)", text))
    # Box 38 Masse nette
    d.net_weight_kg = _to_float(_first(
        r"38\s*Masse nette\s*\(kg\).*?(?:\d{1,2}\s+\d{2,3}\s+\d{3}\s+)?([\d]+[.,]\d+|[\d]{1,2})",
        text,
    ))

    # Box 33 Code marchandise (HS) — single article for H7
    hs = _first(r"33\s*Code des marchandises\s*\n?\s*(\d{8,10})", text)
    if not hs:
        hs = _first(r"33[^\n]{0,20}\n\s*(\d{8,10})", text)
    if hs:
        d.lines.append(Line(item_no=1, hs_code=hs))

    # Box 34 Code P. origine — try several layouts produced by OCR
    origin = _first(r"34\s*Code\s*P\.?\s*origine\s*\n?\s*(?:35[^\n]+\n?)?\s*([A-Z]{2})\b", text)
    if not origin:
        # OCR sometimes puts 34 and 35 on the same line or collapses them
        origin = _first(r"34[^\n]{0,30}([A-Z]{2})\b(?!\d)", text)
    if not origin:
        origin = _first(r"Pays d'origine[^\n]{0,30}([A-Z]{2})\b", text, flags=re.I)
    d.origin_country = origin

    # Box 15 / 17 Pays destination
    d.destination_country = _first(r"17\s*Code P\.?\s*destination\s*\n?\s*a\|?\s*([A-Z]{2})", text)

    # Box 8 Destinataire (EORI)
    eori = _first(r"8\s*Destinataire.*?No\.?\s*([A-Z]{2}\d{9,17})", text)
    if eori:
        d.destinataire = Party(eori=eori)
        d.importer = Party(eori=eori)

    # TG / DD / AT from DONNÉES COMPTABLES
    d.dd = _to_float(_first(r"\bDD\s+([\d\s.,]+)", text))
    d.tg = _to_float(_first(r"\bTG\s+([\d\s.,]+)", text))
    d.at = _to_float(_first(r"\bAT\s+([\d\s.,]+)", text))
    d.tva_auto_liquidee = _to_float(_first(r"TVA Auto liquid[eé]e\s*:?\s*([\d\s.,]+)", text))

    # VAT
    vat = (
        _first(r"FR7\s*[,\s]\s*(FR\d{11})", text)
        or _first(r"\b(FR\d{11})\b", text)
    )
    if vat:
        if not d.importer:
            d.importer = Party()
        d.importer.vat = vat

    # Accompanying / transport docs
    for m in re.finditer(r"N380\s*[,:\s]\s*([A-Z0-9\-/]{3,40})", text, flags=re.I):
        ref = m.group(1).strip().rstrip(",;:")
        if ref and ref not in d.accompanying_docs:
            d.accompanying_docs.append(ref)
    awb = _first(r"N740\s*[,:Z\s]+([A-Z0-9\-/]{5,40})", text)
    if awb:
        d.transport_doc = awb.rstrip(",;:")

    return d


# ---------------------------------------------------------------------------
# Justificatif dédouanement (DAU / SAD) parser
# ---------------------------------------------------------------------------

def _parse_dau(text: str) -> Declaration:
    d = Declaration(declaration_format="dau")

    d.mrn = _find_mrn(text)

    # Box 22 Monnaie et montant total facturé
    m = re.search(
        r"22\s*Monnaie et montant total\s*factur[eé]\s*\n?[^\n]*?([A-Z]{3})\s*[\n\s|,]+([\d\s.,]+?)(?:\s+\d+\s+\d)",
        text, flags=re.I | re.S,
    )
    if m:
        d.currency = m.group(1).upper()
        d.total_amount = _to_float(m.group(2))
    if not d.total_amount:
        m = re.search(
            rf"({CURRENCY_RE})\s*[,\s]+([\d.,]{{4,15}})\s+\d+\s+\d",
            text, flags=re.I,
        )
        if m:
            d.currency = m.group(1).upper()
            d.total_amount = _to_float(m.group(2))
    if not d.total_amount:
        m = re.search(
            rf"({CURRENCY_RE})\s+([\d\s.,]{{3,15}})",
            text, flags=re.I,
        )
        if m:
            d.currency = m.group(1).upper()
            d.total_amount = _to_float(m.group(2))

    # Box 33 Code des marchandises
    m = re.search(
        r"33\s*Code des marchandises.{0,250}?\b(\d{8,10})(?:\s+\d{2})?",
        text, flags=re.I | re.S,
    )
    hs = m.group(1) if m else None
    if not hs:
        hs = _first(r"Code des marchandises\s*\n?\s*(\d{8,10})", text)
    if hs:
        d.lines.append(Line(item_no=1, hs_code=hs))

    # Box 34 Code P. origine
    m = re.search(r"34\s*Code\s*P\.?\s*origine.{0,200}?\n\s*([A-Z]{2})\b", text, flags=re.I | re.S)
    if m:
        d.origin_country = m.group(1)
    if not d.origin_country:
        d.origin_country = _first(r"16\s*Pays d'origine\s*\n?\s*([A-Z]{2})\b", text)
    if not d.origin_country:
        # Broader: label "Pays d'origine" anywhere
        d.origin_country = _first(r"Pays d'origine[^\n]{0,30}([A-Z]{2})\b", text, flags=re.I)

    # Box 17 Code P. destination
    d.destination_country = _first(
        r"17\s*Code P\.?\s*destination\s*\n?\s*[ab]?\|?\s*([A-Z]{2})", text
    )
    if not d.destination_country:
        d.destination_country = _first(r"17\s*Pays de destination\s*\n?\s*([A-Z]+)\b", text)

    # Box 35 / 38 Weights
    d.gross_weight_kg = _to_float(_first(r"35\s*Masse brute\s*\(kg\)\s*\n?\s*([\d.,]+)", text))
    m = re.search(
        r"38\s*Masse nette\s*\(kg\).{0,150}?(?:\d{1,2}\s+\d{2,3}\s+\d{3}\s+)?\|?\s*([\d]+[.,]?\d*)",
        text, flags=re.S,
    )
    if m:
        candidate = _to_float(m.group(1))
        if candidate and candidate < 100000:
            d.net_weight_kg = candidate

    # Box 20 Incoterm
    m = re.search(
        r"20\s*Conditions de l[ia]{1,2}[iv]*raison\s*\n?\s*([A-Z]{3})(?:\s+([A-Z0-9\-\s]+?))?(?:\n|\d+\s*$)",
        text, flags=re.I,
    )
    if m:
        d.incoterm = m.group(1)
        if m.group(2):
            d.incoterm_place = m.group(2).strip()

    # Box 8 Destinataire EORI
    eori = (
        _first(r"8\s*Destinataire.*?No\.?\s*([A-Z]{2}\d{9,17})", text)
        or _first(r"Destinataire.*?(FR\d{11,17})", text)
    )
    if eori:
        d.destinataire = Party(eori=eori)

    # Box 14 Declarant / Représentant
    dec_eori = _first(r"14\s*D[ée]clarant/Repr[ée]sentant.*?No\.?\s*([A-Z]{2}\d{9,17})", text)
    if dec_eori:
        d.declarant = Party(eori=dec_eori)

    # Importer from destinataire
    if d.destinataire and d.destinataire.eori:
        d.importer = Party(eori=d.destinataire.eori)

    # Box 44 / REFERENCE FISCALES : VAT
    vat = (
        _first(r"FR7\s*[,\s]\s*(FR\d{11})", text)
        or _first(r"REFERENCE(?:S)?\s+FISC(?:ALES?)?\s*:.*?(FR\d{11})", text)
        or _first(r"\b(FR\d{11})\b", text)
    )
    if vat and d.importer:
        d.importer.vat = vat

    # N380 (Box 44 / invoice references)
    for m in re.finditer(r"N380\s*[,:\s]\s*([A-Z0-9\-/]{3,40})", text, flags=re.I):
        ref = m.group(1).strip().rstrip(",;:")
        if ref and ref not in d.accompanying_docs:
            d.accompanying_docs.append(ref)

    # Box 40 AWB (N740) and previous doc (N785)
    awb = _first(r"N740\s*[,:Z\s]+([A-Z0-9\-/]{5,40})", text)
    if awb:
        d.transport_doc = awb.rstrip(",;:")
    prev = _first(r"N785\s*[,:\s]\s*([A-Z0-9\-/]{3,40})", text)
    if prev:
        d.previous_doc = prev.rstrip(",;:")

    # Box 47 — DONNÉES COMPTABLES: DD / AT / TG
    # Try multiple patterns for the accounting block
    d.dd = _to_float(_first(r"\bDD\s+([\d\s.,]+)", text))
    d.dump = _to_float(_first(r"\bDUMP\s+([\d\s.,]+)", text))
    d.at = _to_float(_first(r"\bAT\s+([\d\s.,]+)", text))
    d.tg = _to_float(_first(r"\bTG\s+([\d\s.,]+)", text))
    d.tva_auto_liquidee = _to_float(_first(r"TVA Auto liquid[eé]e\s*:?\s*([\d\s.,]+)", text))

    # DONNÉES COMPTABLES tabular block fallback
    if d.dd is None or d.tg is None:
        _extract_dau_comptables(text, d)

    return d


def _extract_dau_comptables(text: str, d: Declaration) -> None:
    """Parse the DONNÉES COMPTABLES table from a DAU document.

    Typical layout after pyMuPDF:
        DONNÉES COMPTABLES
        DD   136,00
        AT   4,00
        TG   140,00
    or (older forms):
        Droits de douane   136,00
        Taxes diverses       4,00
        Total               140,00
    """
    m = re.search(
        r"DONN[ÉE]ES\s+COMPTABLES\s*\n(.*?)(?=\n\s*\n|\Z)",
        text, flags=re.I | re.S,
    )
    if not m:
        return
    block = m.group(1)

    if d.dd is None:
        d.dd = _to_float(_first(r"\bDD\s+([\d\s.,]+)", block))
    if d.dd is None:
        d.dd = _to_float(_first(r"Droits de douane\s+([\d\s.,]+)", block, flags=re.I))

    if d.at is None:
        d.at = _to_float(_first(r"\bAT\s+([\d\s.,]+)", block))
    if d.at is None:
        d.at = _to_float(_first(r"Taxes diverses\s+([\d\s.,]+)", block, flags=re.I))

    if d.tg is None:
        d.tg = _to_float(_first(r"\bTG\s+([\d\s.,]+)", block))
    if d.tg is None:
        d.tg = _to_float(_first(r"Total\s+([\d\s.,]+)", block, flags=re.I))


# ---------------------------------------------------------------------------
# Article LIQUIDATION table parser (Delta IE)
# ---------------------------------------------------------------------------

def _extract_article_liquidation(text: str, d: Declaration) -> None:
    """Parse the tabular LIQUIDATION block of a Delta IE article.

    U165 = droits de douane ad valorem → DD
    M195 = taxe additionnelle → AT
    A445 = TVA (usually auto-liquidated)
    """
    totals = {"U165": 0.0, "M195": 0.0, "A445": 0.0}
    found = {"U165": False, "M195": False, "A445": False}

    for m in re.finditer(
        r"LIQUIDATION\s*\n(.*?)(?=DONNEE COMPLEMENTAIRE|MENTION SPECIALES|Page\s+\d+\s+of|$)",
        text, flags=re.I | re.S,
    ):
        block = m.group(1)

        # Extract tax-type codes in order
        tax_codes: List[str] = []
        for line in block.splitlines():
            stripped = line.strip()
            if re.fullmatch(r"[UMA]\d{3}(?:-[A-Z0-9]{2,4})?", stripped):
                tax_codes.append(stripped.split("-")[0])

        # Find "Montant\n" then collect subsequent numeric lines
        m2 = re.search(r"Montant\s*\n((?:\s*[\d.,]+\s*\n){1,10})", block)
        amounts: List[float] = []
        if m2:
            for line in m2.group(1).splitlines():
                v = _to_float(line.strip())
                if v is not None:
                    amounts.append(v)

        # Associate amounts to tax codes by position and sum across articles.
        for code, amt in zip(tax_codes, amounts):
            if code in totals:
                totals[code] += amt
                found[code] = True

    if found["U165"]:
        d.dd = round(totals["U165"], 2)
    if found["M195"]:
        d.at = round(totals["M195"], 2)
    if found["A445"]:
        d.tva_auto_liquidee = round(totals["A445"], 2)


# ---------------------------------------------------------------------------
# Party extraction
# ---------------------------------------------------------------------------

_PARTY_KEYWORDS = [
    "AUTRE ACTEUR DE LA CHAINE LOGISTIQUE",
    "REPRESENTANT",
    "EXPORTATEUR",
    "DESTINATAIRE",
    "IMPORTATEUR",
    "DECLARANT",
    "VENDEUR",
    "ACHETEUR",
    "AUTORISATION",
    "PAYS",
    "CONDITIONS DE LIVRAISON",
    "TRANSPORT",
    "DONNEE COMPLEMENTAIRE",
    "DOCUMENT",
    "GARANTIE",
    "LIQUIDATION",
    "INFORMATIONS GENERALES",
    "CONDITIONS DE TRANSACTION",
    "MARCHANDISE",
    "NUMERO DE DECLARATION",
    "INTERVENANTS",
]


def _extract_party(text: str, keyword: str) -> Party:
    """Extract a party block starting after 'KEYWORD :' up to the next keyword."""
    pattern = rf"{keyword}\s*:\s*(.+?)(?=\n\s*(?:{'|'.join(_PARTY_KEYWORDS)})\s*:|\Z)"
    m = re.search(pattern, text, flags=re.I | re.S)
    if not m:
        return Party()
    block = m.group(1).strip()
    p = Party()
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if lines:
        p.name = lines[0]
    eori_m = re.search(r"\b([A-Z]{2}\d{9,17})\b", block)
    if eori_m:
        p.eori = eori_m.group(1)
    vat_m = re.search(r"\b(FR\d{11})\b", block)
    if vat_m:
        p.vat = vat_m.group(1)
    country_m = re.search(r"\n\s*([A-Z]{2})\s*$", block)
    if country_m:
        p.country = country_m.group(1)
    return p


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def parse_declaration(text: str, source_file: Optional[str] = None,
                      hint: Optional[str] = None) -> Declaration:
    """Parse a declaration from its full text.

    hint : 'delta_ie' | 'h7' | 'dau' to skip detection
    """
    fmt = hint
    if not fmt:
        up = text.upper()
        if "DHL DELTA IE" in up:
            fmt = "delta_ie"
        elif "DELTA H7" in up or "DELTA-H7" in up:
            fmt = "h7"
        elif "JUSTIFICATIF DÉDOUANEMENT" in up or "JUSTIFICATIF DEDOUANEMENT" in up:
            fmt = "dau"
        elif "FRA0619B" in up or "DONNEES COMPTABLES" in up:
            fmt = "dau"
        else:
            fmt = "delta_ie"

    if fmt == "delta_ie":
        d = _parse_delta_ie(text)
    elif fmt == "h7":
        d = _parse_h7(text)
    elif fmt == "dau":
        d = _parse_dau(text)
    else:
        d = _parse_delta_ie(text)

    d.source_file = source_file
    return d
