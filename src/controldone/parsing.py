"""Document parsers and adapters.

The active pipeline uses ``controldone.models.Document`` everywhere.  Some
stable v3 parsers are still reused through ``controldone.adapters`` adapters,
while newer supplier-specific formats are parsed directly here.

* Parfumerie Versailles FAI invoices
* LaunchMetrics Excel invoices
* Worldnet prestation invoices
* DAU/SAD with box-position heuristics
"""
from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional

from controldone.models import Document, Line, Party
from controldone.classification import PageSegment
from controldone.formats.common import (
    all_matches,
    find_all_mrns,
    find_all_vat_fr,
    find_mrn,
    parse_date_to_iso,
    to_float,
)
from controldone.formats.declarations.delta_ie_akanea import parse as parse_delta_ie_akanea
from controldone.hs import is_in_scope, normalize_hs, normalize_hs_many

from controldone.adapters.parse_declaration import parse_declaration
from controldone.adapters.parse_invoice import parse_invoice
from controldone.adapters.parse_prestation import parse_prestation
from controldone.profile import current_profile
from controldone.paths import data_dir


# Entity identification data (our VATs/SIRENs, name & address aliases) is loaded
# from the active client profile — see controldone.profile.ClientProfile.  No
# client data is hard-coded here.


def parse_segment(seg: PageSegment, source_file: str) -> Optional[Document]:
    """Parse one classified segment into a v4 ``Document``."""
    t = seg.doc_type
    pages = list(range(seg.start_page, seg.end_page + 1))
    if t == "unknown" or not seg.text.strip():
        return None

    if t == "declaration_delta_ie_akanea":
        return parse_delta_ie_akanea(seg.text, source_file=source_file, source_pages=pages)
    if t == "declaration_dau":
        return parse_dau_v4(seg.text, source_file=source_file, source_pages=pages)
    if t.startswith("declaration_"):
        hint = {
            "declaration_delta_ie_dhl": "delta_ie",
            "declaration_h7": "h7",
        }.get(t)
        return _adapt_declaration(
            parse_declaration(seg.text, source_file=source_file, hint=hint),
            seg.text,
            t.replace("declaration_", ""),
            pages,
        )

    if t == "invoice_parfumerie_versailles":
        return parse_parfumerie_versailles(seg.text, source_file=source_file, source_pages=pages)
    if t == "invoice_launchmetrics":
        return parse_launchmetrics(seg.text, source_file=source_file, source_pages=pages)
    if t.startswith("invoice_"):
        hint = {
            "invoice_entity": "entity",
            "invoice_entity_proforma": "entity_proforma",
            "invoice_entity_delivery_note": "entity_delivery_note",
            "invoice_dhl_hawb": "dhl_commercial",
            "invoice_generic": "generic",
        }.get(t)
        return _adapt_invoice(
            parse_invoice(seg.text, source_file=source_file, hint=hint),
            seg.text,
            t.replace("invoice_", ""),
            pages,
        )

    if t == "prestation_worldnet":
        return parse_worldnet(seg.text, source_file=source_file, source_pages=pages)
    if t.startswith("prestation_"):
        forwarder = {
            "prestation_dhl": "DHL",
            "prestation_schenker": "Schenker",
            "prestation_dsv": "DSV",
        }.get(t)
        return _adapt_prestation(
            parse_prestation(seg.text, source_file=source_file, forwarder=forwarder),
            seg.text,
            t.replace("prestation_", ""),
            pages,
        )

    return None


def parse_segments(segments: Iterable[PageSegment], source_file: str) -> List[Document]:
    out: List[Document] = []
    for seg in segments:
        doc = parse_segment(seg, source_file)
        if doc:
            out.append(doc)
    return out


# ---------------------------------------------------------------------------
# Adapters from v3.1 dataclasses
# ---------------------------------------------------------------------------


def _adapt_party(p) -> Party:
    return Party(
        name=getattr(p, "name", None),
        eori=getattr(p, "eori", None),
        vat=getattr(p, "vat", None),
        country=getattr(p, "country", None),
    )


def _adapt_lines(lines) -> List[Line]:
    out = []
    for ln in lines or []:
        out.append(Line(
            item_no=getattr(ln, "item_no", None),
            hs_code=getattr(ln, "hs_code", None),
            description=getattr(ln, "description", None),
            quantity=getattr(ln, "quantity", None),
            amount=getattr(ln, "amount", None),
            currency=getattr(ln, "currency", None),
            net_weight_kg=getattr(ln, "net_weight_kg", None),
            gross_weight_kg=getattr(ln, "gross_weight_kg", None),
            origin_country=getattr(ln, "origin_country", None),
        ))
    return out


def _adapt_declaration(d, text: str, fmt: str, pages: List[int]) -> Document:
    doc = Document(
        kind="declaration",
        format=fmt,
        source_file=d.source_file,
        source_pages=pages,
        text=text,
        mrn=d.mrn,
        lrn=d.lrn,
        awb=d.transport_doc,
        transport_doc=d.transport_doc,
        referenced_invoices=list(d.accompanying_docs or []),
        total_amount=d.total_amount,
        currency=d.currency,
        dd=d.dd,
        at=d.at,
        tva=d.tva,
        tva_auto_liquidee=d.tva_auto_liquidee,
        tg=d.tg,
        lines=_adapt_lines(d.lines),
        origin_country=d.origin_country,
        destination_country=d.destination_country,
        incoterm=d.incoterm,
        incoterm_place=d.incoterm_place,
        net_weight_kg=d.net_weight_kg,
        gross_weight_kg=d.gross_weight_kg,
        importer=_adapt_party(d.importer),
        exporter=_adapt_party(d.exporter),
        declarant=_adapt_party(d.declarant),
        buyer=_adapt_party(d.destinataire),
    )
    doc.referenced_awbs.extend(_extract_refs(text, ("N741", "N740")))
    doc.referenced_invoices.extend(_extract_refs(text, ("N325", "N830", "N935")))
    doc.referenced_invoices = _dedupe(doc.referenced_invoices)
    if not doc.importer.vat:
        vats = find_all_vat_fr(text)
        if vats:
            doc.importer.vat = vats[-1]
    if not doc.awb and doc.referenced_awbs:
        doc.awb = doc.referenced_awbs[0]
    return doc


def _adapt_invoice(inv, text: str, fmt: str, pages: List[int]) -> Document:
    doc = Document(
        kind="invoice",
        format=fmt,
        source_file=inv.source_file,
        source_pages=pages,
        text=text,
        invoice_number=inv.invoice_number,
        invoice_date=parse_date_to_iso(inv.invoice_date or "") or inv.invoice_date,
        awb=getattr(inv, "awb_number", None),
        total_amount=inv.total_amount,
        currency=inv.currency,
        incoterm=inv.incoterm,
        lines=_adapt_lines(inv.lines),
        seller=_adapt_party(inv.exporter),
        exporter=_adapt_party(inv.exporter),
        buyer=_adapt_party(inv.importer),
        importer=_adapt_party(inv.importer),
    )
    _fill_party_vat_from_text(doc, text)
    _enrich_invoice_from_raw_text(doc, text)
    enrich_invoice_from_source(doc)
    return doc


def enrich_invoice_from_source(doc: Document) -> None:
    """Targeted OCR fallback for invoices still missing core fields.

    The normal ingest path intentionally stays fast and cache-backed.  When an
    invoice is parsed but lacks amount/currency or HS, we run one sparse OCR
    pass on that invoice only and use it as an enrichment source.
    """
    if doc.kind != "invoice" or not doc.source_file or not doc.source_file.lower().endswith(".pdf"):
        return
    if _is_not_goods_invoice_text(doc.text or ""):
        doc.extras["not_goods_invoice"] = True
        doc.extras["not_goods_invoice_reason"] = _not_goods_invoice_reason(doc.text or "")
        return
    base = os.path.basename(doc.source_file).upper()
    if "_INV_" not in base:
        return
    missing_value = doc.total_amount is None or not doc.currency
    missing_hs = not any(ln.hs_code for ln in doc.lines)
    suspicious_value = (
        doc.total_amount is not None
        and abs(doc.total_amount - round(doc.total_amount, 2)) > 0.001
    )
    value_needs_repair = missing_value or suspicious_value or (doc.total_amount is not None and doc.total_amount <= 5)
    deep_ocr = os.environ.get("CONTROLDONE_DEEP_OCR") == "1"
    # Keep the expensive rotated OCR targeted by default.  For audit/training
    # batches, CONTROLDONE_DEEP_OCR=1 forces the better invoice OCR pass on all
    # goods invoices and trades speed for extraction quality.
    if not (deep_ocr or missing_value or missing_hs or suspicious_value):
        return
    sparse = _sparse_ocr_pdf_pages(doc.source_file, doc.source_pages, max_pages=6)
    if not sparse or len(sparse.strip()) < len((doc.text or "").strip()) * 0.5:
        return
    combined = (doc.text or "") + "\n\n" + sparse
    doc.text = combined
    if _is_not_goods_invoice_text(combined):
        doc.extras["not_goods_invoice"] = True
        doc.extras["not_goods_invoice_reason"] = _not_goods_invoice_reason(combined)
        return
    _fill_party_vat_from_text(doc, combined)
    if missing_hs:
        doc.lines = _sanitize_invoice_lines(doc.lines, combined, awb=doc.awb, invoice_number=doc.invoice_number)
    if missing_hs:
        for hs in _extract_invoice_hs_codes(sparse, awb=doc.awb):
            if hs not in {ln.hs_code for ln in doc.lines if ln.hs_code}:
                doc.lines.append(Line(item_no=len(doc.lines) + 1, hs_code=hs))
    if missing_hs and not any(ln.hs_code for ln in doc.lines):
        legacy_hs_text = _legacy_hs_ocr_pdf_pages(doc.source_file, doc.source_pages, max_pages=3)
        if legacy_hs_text:
            doc.text += "\n\n" + legacy_hs_text
            for hs in _extract_invoice_hs_codes(legacy_hs_text, awb=doc.awb):
                if hs not in {ln.hs_code for ln in doc.lines if ln.hs_code}:
                    doc.lines.append(Line(item_no=len(doc.lines) + 1, hs_code=hs))
    cur, amount = _extract_invoice_total(sparse)
    total_from_lines = _LAST_TOTAL_FROM_LINE_SUM[0]
    if amount is None:
        cur, amount = _extract_invoice_total(combined)
        total_from_lines = _LAST_TOTAL_FROM_LINE_SUM[0]
    if cur and (not doc.currency or (value_needs_repair and amount is not None and not _close_amount(amount, doc.total_amount))):
        doc.currency = cur
    if amount is not None and _valid_invoice_amount(amount) and (
        value_needs_repair
    ):
        doc.total_amount = amount
        if total_from_lines:
            doc.extras["total_estimated_from_lines"] = True
    if _is_delivery_note_without_value(doc):
        doc.extras["not_goods_invoice"] = True
        doc.extras["not_goods_invoice_reason"] = "Delivery note sans valeur facture marchandise."


def reconcile_invoice_with_declaration_evidence(inv: Document, decl: Document) -> None:
    """Fill invoice key fields only when the invoice text supports the declaration.

    This is a conservative post-match repair layer.  The goods invoice remains
    the source of truth: we only copy a declaration value into the invoice model
    when that exact value/family is visible in the invoice OCR text.  This
    catches OCR/parser misses without hiding real business discrepancies.
    """
    if inv.kind != "invoice" or decl.kind != "declaration":
        return
    text = inv.text or ""
    if not text.strip():
        return

    extracted_cur, extracted_amount = _extract_invoice_total(text)
    extracted_matches_decl = (
        decl.total_amount is not None
        and decl.currency
        and extracted_amount is not None
        and extracted_cur == decl.currency
        and _close_amount(extracted_amount, decl.total_amount)
    )
    if (
        decl.total_amount is not None
        and decl.currency
        and (
            extracted_matches_decl
            or _amount_evidence_in_text(text, decl.total_amount, decl.currency)
            or _amount_sum_evidence_in_text(text, decl.total_amount, decl.currency)
        )
    ):
        if inv.total_amount is None or not inv.currency or not _close_amount(inv.total_amount, decl.total_amount):
            inv.total_amount = decl.total_amount
            inv.currency = decl.currency
            inv.extras["amount_reconciled_from_invoice_text"] = True

    existing_hs6 = {(normalize_hs(ln.hs_code, scope_only=True) or "")[:6] for ln in inv.lines if ln.hs_code}
    for hs in decl.hs_codes:
        hs_clean = normalize_hs(hs, scope_only=True)
        if not hs_clean or hs_clean[:6] in existing_hs6:
            continue
        if _hs_evidence_in_text(text, hs_clean):
            inv.lines.append(Line(item_no=len(inv.lines) + 1, hs_code=hs_clean))
            inv.extras["hs_reconciled_from_invoice_text"] = True
            existing_hs6.add(hs_clean[:6])

    if not inv.buyer.vat:
        _fill_party_vat_from_text(inv, text)


def _amount_evidence_in_text(text: str, amount: float, currency: str) -> bool:
    variants = _amount_text_variants(amount)
    if not variants:
        return False
    cur = _normalize_currency(currency) or currency
    aliases = _currency_aliases(cur)
    bodies = [text.upper()]
    normalized = _normalize_ocr_amount_text(bodies[0])
    if normalized != bodies[0]:
        bodies.append(normalized)
    for body in bodies:
        for v in variants:
            for m in re.finditer(re.escape(v), body):
                window = body[max(0, m.start() - 120):m.end() + 120]
                if cur and any(alias in window for alias in aliases):
                    return True
    return False


def _normalize_ocr_amount_text(text: str) -> str:
    # Keep replacements local to numeric strings; globally replacing these
    # letters would corrupt normal words and labels.
    out = text
    out = re.sub(r"(?<=\d)[EOQ](?=\d)", "8", out)
    out = re.sub(r"(?<=\d)[IL](?=\d)", "1", out)
    out = re.sub(r"(?<=\d)S(?=\d)", "5", out)
    out = out.replace("CHE", "CHF").replace("CHP", "CHF").replace("CAO", "CAD")
    return out


def _currency_aliases(currency: str) -> set[str]:
    cur = _normalize_currency(currency) or currency
    aliases = {cur}
    if cur == "CHF":
        aliases.update({"CHE", "CHP"})
    if cur == "CAD":
        aliases.add("CAO")
    if cur == "EUR":
        aliases.add("€")
    if cur == "GBP":
        aliases.add("£")
    if cur == "JPY":
        aliases.add("¥")
    return aliases


def _amount_sum_evidence_in_text(text: str, amount: float, currency: str) -> bool:
    """Return true when visible invoice line amounts add up to the declaration.

    This is intentionally used only after matching an invoice to a declaration.
    It repairs OCR cases where the grand total is garbled but line values remain
    readable, without accepting a naked declaration amount that is absent from
    the invoice text.
    """
    cur = _normalize_currency(currency) or currency
    if not cur or amount <= 0:
        return False
    if not re.search(r"\b(?:HS|H\.S\.?|CUSTOMS?\s+CODE|COSTOMS\s+CODE|COMMODITY|MATRICULE|VALUE\s+IN)\b", text, flags=re.I):
        return False
    vals: List[int] = []
    currency_pat = re.escape(cur)
    for m in re.finditer(rf"([0-9][0-9 .,]*[.,][0-9]{{2}})\s*{currency_pat}\b|{currency_pat}\s*([0-9][0-9 .,]*[.,][0-9]{{2}})", text, flags=re.I):
        raw = m.group(1) or m.group(2)
        nums = re.findall(r"[0-9]+(?:[.,][0-9]+)?", raw or "")
        val = _parse_money(nums[-1] if nums else raw, cur)
        if val is None or val <= 0:
            continue
        if val > amount * 1.05:
            continue
        window = text[max(0, m.start() - 80):m.end() + 80]
        if re.search(r"\b(?:TEL|PHONE|FAX|ACCOUNT|A/C)\b", window, flags=re.I):
            continue
        vals.append(int(round(val * 100)))
    vals = sorted(v for v in vals if v > 0)
    if len(vals) < 2:
        return False
    target = int(round(amount * 100))
    tolerance = max(100, int(round(target * 0.005)))
    states = {0: 0}
    for cents in vals[:40]:
        additions = {}
        for subtotal, count in states.items():
            new = subtotal + cents
            if new > target + tolerance:
                continue
            if abs(new - target) <= tolerance and count + 1 >= 2:
                return True
            additions[new] = max(additions.get(new, 0), count + 1)
        states.update(additions)
    return False


def _amount_text_variants(amount: float) -> List[str]:
    base = f"{amount:.2f}"
    whole, cents = base.split(".")
    thousands_comma = f"{amount:,.2f}"
    thousands_space = thousands_comma.replace(",", " ")
    thousands_dot = thousands_comma.replace(",", ".")
    comma_decimal = base.replace(".", ",")
    euro_style = thousands_dot[:-3] + "," + cents if "." in thousands_dot else comma_decimal
    no_decimal = str(int(round(amount))) if abs(amount - round(amount)) < 0.005 else ""
    variants = {
        base,
        comma_decimal,
        thousands_comma,
        thousands_space,
        euro_style,
        base.replace(".", ""),
    }
    if no_decimal:
        variants.update({
            no_decimal,
            f"{int(round(amount)):,}",
            f"{int(round(amount)):,}".replace(",", " "),
            f"{int(round(amount)):,}".replace(",", "."),
        })
    return [v.upper() for v in variants if v and len(v) >= 2]


def _hs_evidence_in_text(text: str, hs: str) -> bool:
    hs = _clean_digits(hs) or ""
    if len(hs) < 6:
        return False
    compact = re.sub(r"\D", "", text)
    candidates = {hs}
    if len(hs) >= 8:
        candidates.add(hs[:8])
    if len(hs) >= 6:
        candidates.add(hs[:6])
    # Prefer 8+ digit evidence.  Six digits alone is accepted only near an HS
    # label because it is otherwise too broad.
    for cand in sorted(candidates, key=len, reverse=True):
        if len(cand) >= 8 and cand in compact:
            return True
    label_pat = r"(?:HS|H\.S\.?|TARIFF|CUSTOMS?\s+CODE|COMMODITY|MATRICULE|\b[1I]B)"
    for m in re.finditer(label_pat, text, flags=re.I):
        window_digits = re.sub(r"\D", "", text[m.start():m.start() + 260])
        if hs[:6] in window_digits:
            return True
    return False


def _adapt_prestation(p, text: str, fmt: str, pages: List[int]) -> Document:
    doc = Document(
        kind="prestation",
        format=fmt,
        source_file=p.source_file,
        source_pages=pages,
        text=text,
        invoice_number=p.invoice_number,
        invoice_date=parse_date_to_iso(p.invoice_date or "") or p.invoice_date,
        forwarder=p.forwarder,
        currency=p.currency or "EUR",
        dd=p.dd_total,
        at=p.at_total,
        tva=p.tva_total,
        total_debours=p.total_debours,
        total_surcharges=p.total_surcharges,
        total_ttc=p.total_facture_ttc,
        referenced_mrns=list(p.mrn_references or []),
        referenced_awbs=list(p.awb_numbers or []),
    )
    doc.awb = doc.referenced_awbs[0] if doc.referenced_awbs else None
    doc.referenced_mrns = _dedupe(doc.referenced_mrns + find_all_mrns(text))
    return doc


# ---------------------------------------------------------------------------
# New invoice parsers
# ---------------------------------------------------------------------------


def parse_parfumerie_versailles(text: str, source_file: Optional[str] = None,
                                source_pages=None) -> Document:
    d = Document(
        kind="invoice",
        format="parfumerie_versailles",
        source_file=source_file,
        source_pages=source_pages or [],
        text=text,
        currency="MXN",
    )
    d.seller = Party(name="PARFUMERIE VERSAILLES", vat=None, country="MX")
    d.buyer = Party(name=_first_line_after(text, ("Direccion Fiscal del Cliente",) + current_profile().invoice_keywords), country=None)
    d.invoice_number = _first(r"\b(FAI\d{6,})\b", text)
    d.invoice_date = parse_date_to_iso(_first(r"Fecha\s*[:.\s]*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", text) or "")
    d.incoterm = _first(r"\bINCOTERM\s*:?\s*([A-Z]{3})\b", text)
    d.awb = _first(r"\b(\d{3}[\s-]\d{8})\b", text)

    totals = [to_float(x) for x in re.findall(r"([\d,]+\.\d{2})", text)]
    totals = [x for x in totals if x is not None and x > 0]
    if totals:
        d.total_amount = max(totals)

    # These invoices do not display a customs HS code.  Keep product refs as
    # diagnostic data, but HS validation will correctly flag "missing HS".
    d.extras["product_refs"] = _dedupe(re.findall(r"\bAS[A-Z0-9]{8,}\b", text, flags=re.I))
    _fill_party_vat_from_text(d, text)
    return d


def parse_launchmetrics(text: str, source_file: Optional[str] = None,
                        source_pages=None) -> Document:
    d = Document(
        kind="invoice",
        format="launchmetrics_xlsx",
        source_file=source_file,
        source_pages=source_pages or [],
        text=text,
        currency="EUR",
    )
    d.invoice_number = _first(r"Invoice\s*:\s*([A-Z0-9_-]+)", text)
    d.invoice_date = parse_date_to_iso(_first(r"Ship Date\s*:\s*(\d{1,2}/[A-Za-z]{3}/\d{2,4})", text) or "")
    d.awb = (
        _first(r"Air\s+Waybill\s+Number\s*:?\s*([0-9]{8,12})", text)
        or _first(r"Tracking\s+Number\s*:?\s*([0-9]{8,12})", text)
    )
    d.seller = Party(name=_first(r"Ship From:\s*\n\s*([^\n]+)", text), country="JP")
    ship_to = _first(r"SHIP TO:\s*\n?\s*([^\n]+)", text)
    d.buyer = Party(name=ship_to)
    for name, vat in current_profile().name_aliases:
        if ship_to and name in ship_to.upper():
            d.buyer.vat = vat
            d.extras["buyer_vat_inferred_from_name"] = True
            break

    total = _first(r"Total Sample Price Value:\s*EUR\s*([\d.,]+)", text)
    d.total_amount = to_float(total)
    d.currency = "EUR"

    hs_codes = normalize_hs_many(re.findall(r"\b(\d{6,10})\b", text), scope_only=True)
    for idx, hs in enumerate(hs_codes, start=1):
        if hs.startswith(("19", "20")) or (d.awb and hs == d.awb):
            continue
        if not _looks_like_hs(hs):
            continue
        if len(hs) >= 6:
            d.lines.append(Line(item_no=idx, hs_code=hs, currency="EUR"))

    # Better line extraction for the tabular Excel export.
    for row in text.splitlines():
        if "\t" not in row:
            continue
        cols = row.split("\t")
        if len(cols) < 15:
            continue
        hs = normalize_hs(cols[12], scope_only=True)
        amount = to_float(cols[13])
        weight_g = to_float(cols[14])
        if hs:
            d.lines.append(Line(
                item_no=len(d.lines) + 1,
                hs_code=hs,
                description=cols[9] or None,
                amount=amount,
                currency="EUR",
                net_weight_kg=round(weight_g / 1000, 3) if weight_g is not None else None,
                origin_country=_country_to_iso(cols[11]),
            ))
    d.lines = _dedupe_lines(d.lines)
    return d


# ---------------------------------------------------------------------------
# New prestation parser
# ---------------------------------------------------------------------------


def parse_worldnet(text: str, source_file: Optional[str] = None,
                   source_pages=None) -> Document:
    d = Document(
        kind="prestation",
        format="worldnet",
        source_file=source_file,
        source_pages=source_pages or [],
        text=text,
        forwarder="Worldnet",
        currency="EUR",
    )
    d.invoice_number = (
        _first(r"No\.\s*de\s*facture\.?\s*:?\s*([0-9A-Z-]{5,30})", text)
        or _first(r"Num[eé]ro\s+de\s+facture\s*:?\s*([0-9A-Z-]{5,30})", text)
        or _first(r"\b(30\d{6,})\b", os.path.basename(source_file or ""))
    )
    d.invoice_date = parse_date_to_iso(_first(r"Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", text) or "")
    d.referenced_mrns = find_all_mrns(text)
    d.referenced_awbs = _dedupe(re.findall(r"\b(\d{3}[\s/-]\d{8})\b", text))
    d.awb = d.referenced_awbs[0] if d.referenced_awbs else None
    vats = find_all_vat_fr(text)
    if vats:
        d.buyer.vat = vats[0]

    droits_et_taxes = (
        _amount_after_line_label(text, ("Droits et Taxes:", "Droits et Taxes (EUR)"))
        or _amount_after_labels(text, ("Droits et Taxes", "Droits de douane"))
    )
    d.tva = (
        _amount_after_line_label(text, ("TVA à l'importation:", "TVA a l'importation:", "TVA à l'importation (EUR)"))
        or _amount_after_labels(text, ("TVA a l'importation", "TVA a l importation", "TVA à l'importation"))
    )
    # Worldnet exposes "Droits et Taxes" as a combined customs disbursement,
    # not as a pure DD line. Keep DD/AT split empty and validate the total.
    d.total_debours = droits_et_taxes
    d.total_surcharges = (
        _amount_after_line_label(text, ("Charges totales:", "Sous-total (EUR)"))
        or _amount_after_labels(text, ("Frais totales", "Frais total", "Total frais", "Charges totales"))
    )
    d.total_ttc = (
        _amount_after_line_label(text, ("Total:", "Total (EUR)"))
        or _amount_after_labels(text, ("Montant total", "Total (EUR)", "Total EUR"))
    )
    if d.total_debours is None:
        vals = [x for x in (d.dd, d.at, d.tva) if x is not None]
        d.total_debours = round(sum(vals), 2) if vals else None
    return d


# ---------------------------------------------------------------------------
# DAU parser
# ---------------------------------------------------------------------------


def parse_dau_v4(text: str, source_file: Optional[str] = None,
                 source_pages=None) -> Document:
    base = parse_declaration(text, source_file=source_file, hint="dau")
    d = _adapt_declaration(base, text, "dau_sad", source_pages or [])
    d.mrn = find_mrn(text) or d.mrn

    refs_invoice = _extract_refs(text, ("N380", "N325", "N830", "N935"))
    refs_awb = _extract_refs(text, ("N741", "N740"))
    if refs_invoice:
        d.referenced_invoices = refs_invoice
    if refs_awb:
        d.referenced_awbs = refs_awb
        d.awb = refs_awb[0]
    vat = _first(r"\bFR7\s+(FR\d{11})\b", text) or (find_all_vat_fr(text)[-1] if find_all_vat_fr(text) else None)
    if vat:
        d.importer.vat = vat

    cur, amount, fx = _extract_dau_currency_amount_fx(text)
    if cur:
        d.currency = cur
    if amount is not None:
        d.total_amount = amount
    if fx is not None:
        d.fx_rate = fx

    article = _extract_dau_article(text)
    if article:
        d.lines = [article]
        d.origin_country = article.origin_country or d.origin_country
        d.gross_weight_kg = article.gross_weight_kg
        d.net_weight_kg = article.net_weight_kg
    if "COMMUNAUTE EUROPEENNE" in text.upper() or "COMMUNAUTÉ EUROPÉENNE" in text.upper():
        _enrich_legacy_sad(d, text, source_file)
    d.dd = d.dd if d.dd is not None else 0.0
    d.at = d.at if d.at is not None else 0.0
    d.tva = d.tva if d.tva is not None else 0.0
    d.tg = d.tg if d.tg is not None else 0.0
    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first(pattern: str, text: str, flags: int = re.I | re.S) -> Optional[str]:
    m = re.search(pattern, text, flags=flags)
    return m.group(1).strip() if m else None


def _clean_digits(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    s = "".join(c for c in str(v) if c.isdigit())
    return s or None


def _dedupe(values: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for v in values:
        if not v:
            continue
        vv = str(v).strip().rstrip(".,;:")
        key = vv.upper()
        if vv and key not in seen:
            seen.add(key)
            out.append(vv)
    return out


def _dedupe_lines(lines: Iterable[Line]) -> List[Line]:
    out, seen = [], set()
    for ln in lines:
        key = (ln.hs_code, ln.description, ln.amount)
        if ln.hs_code and key not in seen:
            seen.add(key)
            out.append(ln)
    return out


def _extract_refs(text: str, labels: Iterable[str]) -> List[str]:
    vals = []
    for label in labels:
        vals.extend(all_matches(rf"\b{label}\b\s*[-:]?\s*([A-Z0-9][A-Z0-9./ -]{{2,40}})", text))
    clean = []
    for v in vals:
        v = re.split(r"\s+\d{1,2}/\d{1,2}/\d{2,4}|\s+\|\s+|/ N\d{3}", v)[0]
        clean.append(v.strip())
    return _dedupe(clean)


def _fill_party_vat_from_text(doc: Document, text: str) -> None:
    bill_context = _context_after_labels(text, ("BILL TO", "BILLED TO", "INVOICE TO", "SOLD TO", "ACHETEUR", "CLIENT"))
    ship_context = _context_after_labels(text, ("SHIP TO", "DESTINATAIRE", "IMPORTATEUR", "CONSIGNEE", "ULTIMATE CONSIGNEE"))
    identity_vat = (
        _known_identity_vat(bill_context)
        or _known_identity_vat(ship_context)
        or _known_identity_vat(text)
    )
    current_vat = (doc.buyer.vat or "").upper()
    if identity_vat and current_vat not in current_profile().our_vats:
        doc.buyer.vat = identity_vat
        doc.extras["buyer_vat_inferred_from_entity_identity"] = True
        return
    if not doc.buyer.vat:
        doc.buyer.vat = _known_vat_from_text(bill_context)
        if doc.buyer.vat:
            doc.extras["buyer_vat_inferred_from_bill_to_context"] = True
    if not doc.buyer.vat:
        doc.buyer.vat = _known_vat_from_text(ship_context)
        if doc.buyer.vat:
            doc.extras["buyer_vat_inferred_from_ship_to_context"] = True
    vats = find_all_vat_fr(text)
    if vats and not doc.buyer.vat:
        doc.buyer.vat = vats[-1]
    if not doc.buyer.vat:
        for raw in re.findall(r"\bFR\s*((?:[0-9]\s*){11})\b", text, flags=re.I):
            doc.buyer.vat = "FR" + re.sub(r"\D", "", raw)
            break
    if not doc.buyer.vat:
        for raw in re.findall(r"\bFR\s*([0-9][0-9\s]{9,16})\b", text, flags=re.I):
            compact = "FR" + re.sub(r"\D", "", raw)
            for vat in current_profile().our_vats:
                if compact.startswith(vat):
                    doc.buyer.vat = vat
                    doc.extras["buyer_vat_inferred_from_noisy_vat"] = True
                    break
            if doc.buyer.vat:
                break
    up = text.upper()
    if not doc.buyer.vat:
        for name, vat in current_profile().name_aliases:
            if name in up:
                doc.buyer.vat = vat
                doc.extras["buyer_vat_inferred_from_name"] = True
                break
    if not doc.buyer.vat:
        for marker, vat in current_profile().address_aliases:
            if marker in up:
                doc.buyer.vat = vat
                doc.extras["buyer_vat_inferred_from_address"] = True
                break


def _context_after_labels(text: str, labels: Iterable[str], width: int = 900) -> str:
    up = text.upper()
    chunks = []
    for label in labels:
        idx = up.find(label)
        if idx >= 0:
            chunks.append(text[idx:idx + width])
    return "\n".join(chunks)


def _siren_evidence(text: str) -> Optional[str]:
    """Unambiguous SIREN-digit evidence for exactly one of our entities.

    A printed SIREN beats any name-based guess (OCR mangles the FR key digits
    but rarely the 9-digit SIREN).  Data lives on the active client profile.
    """
    return current_profile().siren_evidence(text)


def _known_identity_vat(text: str) -> Optional[str]:
    """Resolve one of our VATs from free text (SIREN, then name, then address)."""
    return current_profile().identity_vat(text)


def _known_vat_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    profile = current_profile()
    vat = profile.identity_vat(text)
    if vat:
        return vat
    vats = find_all_vat_fr(text)
    for candidate in vats:
        if candidate in profile.our_vats:
            return candidate
    return vats[-1] if vats else None


def _enrich_invoice_from_raw_text(doc: Document, text: str) -> None:
    """Last-mile extraction for OCR-heavy supplier invoices.

    The legacy invoice parsers cover the entity's templates well, but supplier
    invoices often expose customs data under simple labels such as
    ``Tariff Code`` / ``Tarif Code``.  This enrichment is deliberately generic
    and only fills missing fields.
    """
    if _is_not_goods_invoice_text(text):
        doc.extras["not_goods_invoice"] = True
        doc.extras["not_goods_invoice_reason"] = _not_goods_invoice_reason(text)
        return

    if not doc.awb:
        doc.awb = (
            _first(r"(?:AWB|TRACKING|TRACKING\s+NO|PARCEL\s+NO)\s*[:#.]?\s*([0-9]{8,12})", text)
            or _first(r"\b([0-9]{10})_(?:INV|HWB|ENT)_", os.path.basename(doc.source_file or ""))
        )

    doc.lines = _sanitize_invoice_lines(doc.lines, text, awb=doc.awb, invoice_number=doc.invoice_number)
    explicit_hs = _extract_invoice_hs_codes(text, awb=doc.awb)
    # DHL commercial invoices often print HS as split "IB:4202." + "21.009".
    # When those explicit IB labels are present, they are more reliable than
    # the legacy parser's isolated digit capture.
    if explicit_hs and re.search(r"\b[1I]B[:\s]*[0-9]{4}[.,]?", text, flags=re.I):
        doc.lines = [Line(item_no=i, hs_code=hs) for i, hs in enumerate(explicit_hs, start=1)]

    if not doc.lines:
        for hs in explicit_hs:
            doc.lines.append(Line(item_no=len(doc.lines) + 1, hs_code=hs))
    elif not any(ln.hs_code for ln in doc.lines):
        for hs in explicit_hs:
            doc.lines.append(Line(item_no=len(doc.lines) + 1, hs_code=hs))

    cur, amount = _extract_invoice_total(text)
    total_from_lines = _LAST_TOTAL_FROM_LINE_SUM[0]
    if cur and (doc.currency is None or amount and doc.total_amount and amount > doc.total_amount * 10):
        doc.currency = cur
    if amount is not None and (
        doc.total_amount is None
        or doc.total_amount <= 5
        or amount > doc.total_amount * 10
    ):
        doc.total_amount = amount
        if total_from_lines:
            doc.extras["total_estimated_from_lines"] = True
    if _is_delivery_note_without_value(doc):
        doc.extras["not_goods_invoice"] = True
        doc.extras["not_goods_invoice_reason"] = "Delivery note sans valeur facture marchandise."


def _is_not_goods_invoice_text(text: str) -> bool:
    up = (text or "").upper()
    if not up.strip():
        return False
    non_invoice_markers = (
        "PRE ALERTE IMPORTATION",
        "PRÉ ALERTE IMPORTATION",
        "REPAIR SHIPPING LIST",
        "DANS LE CAS D'UNE IMPORTATION",
        "DANS LE CAS D’UNE IMPORTATION",
        "VOTRE ACCORD POUR LE REGLEMENT DES DROITS",
        "VOTRE ACCORD POUR LE RÈGLEMENT DES DROITS",
        "OUTWARD PROCESSING DECLARATION",
        "OP AUTHORISATION",
        "PLEASE EXPORT THIS SHIPMENT USING OUR OP AUTHORISATION",
        "YOUR CDS REFERENCE NUMBER",
        # Canadian CERS export declaration pages bundled inside INV PDFs.
        "CERS EXPORT DECLARATION",
        "DECLARATION D'EXPORTATION SCDE",
        "DECLARATION D’EXPORTATION SCDE",
    )
    invoice_markers = (
        "PROFORMA INVOICE",
        "COMMERCIAL INVOICE",
        "INVOICE TOTAL",
        "TOTAL INVOICE AMOUNT",
        "TOTAL GOODS VALUE",
        "VALUE FOR CUSTOMS",
    )
    non_hits = sum(1 for marker in non_invoice_markers if marker in up)
    invoice_hits = sum(1 for marker in invoice_markers if marker in up)
    repair_table = (
        "REQUEST ID" in up
        and "CLIENT CASE" in up
        and "SKU NUMBER" in up
        and "VALUE FOR CUSTOMS" not in up
        and "COMMERCIAL INVOICE" not in up
        and "PROFORMA INVOICE" not in up
    )
    # A DHL pre-alert may mention that details are on the invoice; that does
    # not make the pre-alert itself a goods invoice.
    return repair_table or (
        non_hits >= 1 and (
            invoice_hits == 0
            or "PRE ALERTE IMPORTATION" in up
            or "OUTWARD PROCESSING DECLARATION" in up
            or "REPAIR SHIPPING LIST" in up
        )
    )


def _is_delivery_note_without_value(doc: Document) -> bool:
    up = (doc.text or "").upper()
    return "DELIVERY NOTE" in up and "INVOICE" not in up and doc.total_amount is None


def _not_goods_invoice_reason(text: str) -> str:
    up = (text or "").upper()
    if "OUTWARD PROCESSING DECLARATION" in up or "OP AUTHORISATION" in up:
        return "Document OP/export, pas facture marchandise."
    if "PRE ALERTE IMPORTATION" in up or "PRÉ ALERTE IMPORTATION" in up:
        return "Pre-alerte import DHL, pas facture marchandise."
    if "REPAIR SHIPPING LIST" in up:
        return "Repair shipping list, pas facture marchandise."
    if "REQUEST ID" in up and "CLIENT CASE" in up and "SKU NUMBER" in up:
        return "Repair/shipping list sans valeur facture marchandise."
    return "Document non facture detecte."


def _extract_invoice_hs_codes(text: str, awb: Optional[str] = None) -> List[str]:
    found: List[str] = []
    # DHL commercial invoices often split "IB:4202.21.00" across OCR lines:
    # "IB:4202. 1.000 kg ... FRANCE ... 21.00". Rebuild that before generic scans.
    ib_matches = list(re.finditer(r"\b[1I]B[:\s]*([0-9]{4})[.,]?", text, flags=re.I))
    for idx, m in enumerate(ib_matches):
        next_ib = ib_matches[idx + 1].start() if idx + 1 < len(ib_matches) else m.end() + 360
        block = text[m.end():min(next_ib, m.end() + 360)]
        block = re.split(r"Total\s+Goods\s+Value|Total\s+Invoice\s+Amount|Currency\s+Code", block, flags=re.I)[0]
        if not re.search(r"\b(?:ITALY|FRANCE|SWITZERLAND|HONG\s+KONG|CHINA|JAPAN|UNITED\s+KINGDOM|GB|FR|IT|CH|HK|CN|JP)\b", block, flags=re.I):
            continue
        parts = re.findall(r"\b([0-9]{2})[.,]([0-9]{2,3})\b", block)
        if parts:
            hs = normalize_hs(m.group(1) + parts[-1][0] + parts[-1][1], scope_only=True)
            if hs:
                found.append(hs)

    patterns = [
        r"\bCITES\s+Customs[\s\S]{0,140}?\bNo\s+([0-9]{8,10})\b",
        r"\bCustoms\s+Number\s+code[\s\S]{0,180}?\bNo\s+([0-9]{8,10})\b",
        r"\bTariff\s+Code\s*:?\s*([0-9 ]{6,12})",
        r"\bTarif\s+Code\s*:?\s*([0-9 ]{6,12})",
        r"\bCustoms?\s+Code\s*:?\s*([0-9 .,]{6,16})",
        r"\bCommodity\s+Code\s*:?\s*([0-9 .,]{6,16})",
        r"\bHS\s+Code\s*:?\s*([0-9 .,]{6,16})",
        r"\bH\.?\s*S\.?\s*Code\s*:?\s*([0-9 .,]{6,16})",
        r"\bCustom\s+Code\s+([0-9 .,]{6,16})\b",
        r"\b[1I]B[: ]+([0-9]{6,10})\b",
        r"\bMATRICULE\s+([0-9][0-9 .,]{9,16})",
    ]
    for pat in patterns:
        for raw in re.findall(pat, text, flags=re.I):
            hs = normalize_hs(raw, scope_only=True)
            if hs and hs != awb and not _looks_like_tax_id(hs, text):
                found.append(hs)

    countries = (
        "United Kingdom", "France", "Italy", "Spain", "Switzerland", "Japan",
        "China", "Hong Kong", "Korea", "Mexico", "Portugal", "Germany",
        "GB", "FR", "IT", "ES", "CH", "JP", "CN", "HK", "KR", "MX", "PT", "DE",
        "ITA", "FRA", "ESP", "CHE", "USA", "THA", "AUS", "CAN", "NOR",
    )
    country_pat = "|".join(re.escape(c) for c in countries)
    customs_block = _customs_code_block(text)
    if customs_block:
        for raw in re.findall(r"\b([0-9]{4}[ ]?[0-9]{2}[ ]?[0-9]{0,5})\b", customs_block):
            hs = normalize_hs(raw, scope_only=True)
            if hs and hs != awb and not _looks_like_tax_id(hs, text):
                found.append(hs)
    broad_value_table_hs: List[str] = []
    for m in re.finditer(r"\b(?:Unit\s+Value|Total\s+Value|Unit\s+Valve|Total\s+Valse)\b[\s\S]{0,700}", text, flags=re.I):
        block = m.group(0)
        if not re.search(r"\b(?:CHF|CHE|EUR|USD|GBP|AED|HKD|SGD|NOK|CAD)\b", block, flags=re.I):
            continue
        for raw in re.findall(r"\b([0-9]{8,10})\b", block):
            hs = normalize_hs(raw, scope_only=True)
            if hs and hs != awb and not _looks_like_tax_id(hs, text):
                broad_value_table_hs.append(hs)
    if not found and len(_dedupe(broad_value_table_hs)) <= 2:
        found.extend(broad_value_table_hs)
    for raw in re.findall(rf"(?:{country_pat})\s+\|?\s*([0-9]{{6,11}})\b", text, flags=re.I):
        hs = normalize_hs(raw, scope_only=True)
        if hs and hs != awb and not _looks_like_tax_id(hs, text):
            found.append(hs)
    for raw in re.findall(rf"\b([0-9]{{6,11}})\s+(?:{country_pat})\b", text, flags=re.I):
        hs = normalize_hs(raw, scope_only=True)
        if hs and hs != awb and not _looks_like_tax_id(hs, text):
            found.append(hs)
    for raw in re.findall(r"\b([0-9]{4}[.,\s-][0-9]{2}[.,\s-][0-9]{4}|[0-9]{4}[.,\s-][0-9]{2}[.,\s-][0-9]{2}(?:[.,\s-][0-9]{2})?)\b", text):
        hs = normalize_hs(raw, scope_only=True)
        if hs and hs != awb and not _looks_like_tax_id(hs, text):
            found.append(hs)
    if not found and re.search(r"\b(?:COSTUME\s+JEWEL(?:RY|LERY)|EARRINGS?|BROOCH|NECKLACE|BIJOUTERIE\s+FANTAISIE)\b", text, flags=re.I):
        found.append("7117190090")
    return normalize_hs_many(found, scope_only=True)


def _sanitize_invoice_lines(lines: Iterable[Line], text: str, awb: Optional[str],
                            invoice_number: Optional[str]) -> List[Line]:
    out: List[Line] = []
    awb_digits = _clean_digits(awb)
    inv_digits = _clean_digits(invoice_number)
    for ln in lines or []:
        hs = normalize_hs(ln.hs_code, scope_only=True)
        if not hs:
            continue
        if hs in {awb_digits, inv_digits}:
            continue
        if not hs or _looks_like_tax_id(hs, text):
            continue
        ln.hs_code = hs
        out.append(ln)
    return _dedupe_lines(out)


def _close_amount(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    diff = abs(a - b)
    return diff <= 1.0 or diff / max(abs(a), abs(b), 1) <= 0.01


def _extract_invoice_total(text: str):
    _LAST_TOTAL_FROM_LINE_SUM[0] = False
    currencies = r"(?:EUR|USD|GBP|CHF|CHE|CHP|CAD|CAO|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR|€|£|¥)"
    amount = r"[0-9][0-9\s.,]*(?:[.,][0-9]{2})?"
    patterns = [
        rf"\b(?:TOTAL\s+INVOICE\s+AMOUNT|TOTAL\s+GOODS\s+VALUE|TOTAL\s+INCL\.?\s*TAXES|TOTAL\s+INCL\.?|RECIPIENT\s+TOTAL\s+EXCL\.?\s*TAXES|TOTAL\s+AMOUNT)\s*:?\s*({amount})\s*({currencies})",
        rf"\b(?:TOTAL\s+INVOICE\s+AMOUNT|TOTAL\s+GOODS\s+VALUE|TOTAL\s+INCL\.?\s*TAXES|TOTAL\s+INCL\.?|RECIPIENT\s+TOTAL\s+EXCL\.?\s*TAXES|TOTAL\s+AMOUNT)\s*:?\s*({currencies})\s*({amount})",
        rf"\bTOTAL\b[^\n\r]{{0,80}}?({currencies})\s*({amount})",
        rf"\bTOTAL\b[^\n\r]{{0,80}}?({amount})\s*({currencies})",
        rf"\bSUB\s+TOTAL\b[^\n\r]{{0,80}}?({currencies})\s*({amount})",
        rf"\bVALUE\b[^\n\r]{{0,80}}?({currencies})\s*({amount})",
        rf"\bINVOICE\s+VALUE\b[\s\S]{{0,100}}?({amount})\s*({currencies})",
        rf"\bVALUE\s+FOR\s+CUSTOMS\b[^\n\r]{{0,120}}?({amount})\s*({currencies})",
        rf"\bTOTAL\s*:?[^\n\r]{{0,80}}?([€£¥])\s*({amount})",
        rf"\bTotal\s+Currency[\s\S]{{0,220}}?({amount})\s+([A-Z]{{3}})",
        rf"\bTotal\s*amount\s+Currency\s*\n?[^\n\r]{{0,120}}?({amount})\s+([A-Z]{{3}})",
    ]
    origin_value = _extract_country_origin_value(text)
    if origin_value and _valid_invoice_amount(origin_value[1]):
        return origin_value
    special = _extract_total_amount_currency_table(text)
    if special and _valid_invoice_amount(special[1]):
        return special
    loose_table = _extract_loose_total_amount_currency_table(text)
    if loose_table and _valid_invoice_amount(loose_table[1]):
        return loose_table
    candidates = []
    line_total = _extract_tax_excl_total(text)
    if line_total:
        candidates.append(line_total)
    table_total = _extract_total_total_value_table(text)
    if table_total:
        candidates.append(table_total)
    before_value = _extract_amount_before_value_for_customs(text)
    if before_value:
        candidates.append(before_value)
    footer_total = _extract_footer_amount_currency(text)
    if footer_total:
        return footer_total
    currency_table = _extract_currency_summary_table(text)
    if currency_table:
        candidates.append(currency_table)
    after_value = _extract_amount_after_value_for_customs(text)
    if after_value:
        candidates.append(after_value)
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.I):
            a, b = m.group(1), m.group(2)
            if re.fullmatch(currencies, a, flags=re.I):
                cur, num = _normalize_currency(a), b
            else:
                cur, num = _normalize_currency(b), a
            val = _parse_money(num, cur)
            if cur and val is not None:
                candidates.append((cur, val))
    line_sum = _extract_invoice_line_amount_total(text)
    used_line_sum = False
    if not candidates and line_sum:
        candidates.append(line_sum)
        used_line_sum = True
    if not candidates:
        return None, None
    candidates = [(cur, val) for cur, val in candidates if _valid_invoice_amount(val)]
    if not candidates:
        return None, None
    # Prefer the last labelled total, which is usually the payable/customs
    # total.  If that value is clearly a fragment/OCR artefact but line totals
    # reconcile to a plausible amount, keep the line total instead.
    selected = candidates[-1]
    if line_sum and line_sum[0] == selected[0] and not _close_amount(line_sum[1], selected[1]):
        if selected[1] < line_sum[1] * 0.5 or selected[1] > line_sum[1] * 1.5:
            selected = line_sum
            used_line_sum = True
    # Record provenance: a sum of OCR-read lines is a lower-bound estimate
    # (missed rows make it undershoot), not a printed grand total.
    _LAST_TOTAL_FROM_LINE_SUM[0] = used_line_sum
    return selected


# Provenance flag of the most recent _extract_invoice_total call (single-item
# list so nested helpers can set it without a global statement).
_LAST_TOTAL_FROM_LINE_SUM = [False]


def _extract_footer_amount_currency(text: str):
    currencies = r"EUR|USD|GBP|CHF|CHE|CHP|CAD|CAO|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR"
    labels = (
        r"Total\s+amount",
        r"Invoice\s+Total",
        r"Involce\s+Total",
        r"Total\s+Value",
    )
    for label in labels:
        for m in re.finditer(label, text, flags=re.I):
            block = text[m.end(): m.end() + 260]
            found = []
            for mt in re.finditer(rf"([0-9][0-9\s.,]*)\s*({currencies})\b|({currencies})\s*([0-9][0-9\s.,]*)", block, flags=re.I):
                if mt.group(1):
                    raw, cur_raw = mt.group(1), mt.group(2)
                else:
                    cur_raw, raw = mt.group(3), mt.group(4)
                cur = _normalize_currency(cur_raw)
                nums = re.findall(r"[0-9]+(?:[.,][0-9]+)?", raw)
                raw_num = nums[-1] if nums else raw
                val = _parse_money(raw_num, cur)
                if cur and _valid_invoice_amount(val):
                    found.append((cur, val))
            if found:
                return found[-1]
            cur_guess = _dominant_currency_near_amounts(text)
            if cur_guess:
                symbol_amounts = []
                for raw in re.findall(r"[$€£¥]\s*([0-9][0-9\s,]*(?:[.,][0-9]{2})?)", block):
                    val = _parse_money(raw, cur_guess)
                    if _valid_invoice_amount(val):
                        symbol_amounts.append((cur_guess, val))
                if symbol_amounts:
                    return symbol_amounts[-1]
    return None


def _valid_invoice_amount(value: Optional[float]) -> bool:
    if value is None:
        return False
    return 0 < value < 10_000_000


def _extract_loose_total_amount_currency_table(text: str):
    """Extract DHL-style total rows even with OCR label drift.

    Common layouts expose two pairs on the same row:
        <original amount> <original currency> <converted amount> EUR
    The declaration repeats the original currency, so the first non-EUR pair is
    the safest source.
    """
    currencies = r"EUR|USD|GBP|CHF|CHE|CHP|CAD|CAO|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR"
    anchors = (
        r"Total\s+amount\s+Currency",
        r"Total\s*ame?o?u?nt\s+Curr?e?n?c?y",
        r"Tatal\s+Total\s+gross\s+welght\s+Total",
        r"Total\s+gross\s+weight\s+Total\s+amount",
        r"Number\s+of\s+parcel[\s\S]{0,120}?Currency",
    )
    for anchor in anchors:
        m = re.search(anchor, text, flags=re.I)
        if not m:
            continue
        block = text[m.end(): m.end() + 420]
        pairs = []
        for mt in re.finditer(rf"([0-9][0-9\s.,]*)(?:\s*)({currencies})\b|({currencies})\s*([0-9][0-9\s.,]*)", block, flags=re.I):
            if mt.group(1):
                raw, cur_raw = mt.group(1), mt.group(2)
            else:
                cur_raw, raw = mt.group(3), mt.group(4)
            cur = _normalize_currency(cur_raw)
            val = _parse_money(raw, cur)
            if cur and _valid_invoice_amount(val):
                pairs.append((cur, val))
        non_eur = [p for p in pairs if p[0] != "EUR"]
        if non_eur:
            return non_eur[0]
        if pairs:
            return pairs[0]
    return None


def _extract_country_origin_value(text: str):
    currencies = r"EUR|USD|GBP|CHF|CHE|CHP|CAD|CAO|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR"
    for m in re.finditer(r"Country\s+of\s+Origin[\s\S]{0,80}?Value", text, flags=re.I):
        block = text[m.end(): m.end() + 220]
        for mt in re.finditer(rf"\b({currencies})\s*([0-9][0-9\s.,]*)\b|([0-9][0-9\s.,]*)\s*({currencies})\b", block, flags=re.I):
            if mt.group(1):
                cur, raw = _normalize_currency(mt.group(1)), mt.group(2)
            else:
                cur, raw = _normalize_currency(mt.group(4)), mt.group(3)
            val = _parse_money(raw, cur)
            if cur and _valid_invoice_amount(val):
                return cur, val
    return None


def _extract_invoice_line_amount_total(text: str):
    """Sum line amounts when a scanned invoice has no explicit grand total."""
    currency = _dominant_currency_near_amounts(text)
    if not currency:
        return None
    hs_positions = []
    for mt in re.finditer(r"\b([0-9]{4}[0-9 .]{2,7})\b", text):
        hs = normalize_hs(mt.group(1), scope_only=True)
        if hs and not _looks_like_tax_id(hs, text):
            hs_positions.append((mt.start(), mt.end()))
    if not hs_positions:
        return None
    amounts = []
    amount_re = r"\b([0-9]{1,3}(?:[,.][0-9]{3})+(?:[,.][0-9]{2})|[0-9]{1,6}[,.][0-9]{2})\b"
    for idx, (_, end) in enumerate(hs_positions):
        next_start = hs_positions[idx + 1][0] if idx + 1 < len(hs_positions) else end + 320
        block = text[end:min(next_start, end + 360)]
        # An amount immediately followed by the invoice currency is the value
        # column; bare numbers in the same block are often weights/quantities.
        tagged = []
        for raw in re.findall(amount_re.rstrip(r"\b") + rf"\s*{currency}\b", block, flags=re.I):
            val = _parse_money(raw, currency)
            if _valid_invoice_amount(val):
                tagged.append(val)
        if tagged:
            amounts.append(tagged[-1])
            continue
        vals = []
        for raw in re.findall(amount_re, block):
            val = _parse_money(raw, currency)
            if _valid_invoice_amount(val):
                vals.append(val)
        if vals:
            amounts.append(vals[-1])
    if not amounts:
        return None
    total = round(sum(amounts), 2)
    return (currency, total) if _valid_invoice_amount(total) else None


def _dominant_currency_near_amounts(text: str) -> Optional[str]:
    currencies = ("EUR", "USD", "GBP", "CHF", "CHE", "CHP", "CAD", "CAO", "JPY", "CNY", "HKD", "KRW", "SGD", "MXN", "BRL", "INR", "AED", "SAR", "AUD", "NZD", "NOK", "SEK", "DKK", "TWD", "THB", "MYR")
    counts = {}
    up = text.upper()
    for cur in currencies:
        n = len(re.findall(rf"\b{cur}\b", up))
        if n:
            counts[_normalize_currency(cur)] = counts.get(_normalize_currency(cur), 0) + n
    if not counts:
        return None
    # Original invoice currency usually dominates; OCR variants are normalized.
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[0][0]


def _extract_total_amount_currency_table(text: str):
    currencies = {"EUR", "USD", "GBP", "CHF", "CHE", "CHP", "CAD", "CAO", "JPY", "CNY", "HKD", "KRW", "SGD", "MXN", "BRL", "INR", "AED", "SAR", "AUD", "NZD", "NOK", "SEK", "DKK", "TWD", "THB", "MYR"}
    m = re.search(r"Total\s*(?:amount)?\s+Currency|Totalamount\s+Currency", text, flags=re.I)
    if not m:
        return None
    block = text[m.end(): m.end() + 260]
    found = []
    for cur in currencies:
        for mt in re.finditer(rf"([\s\S]{{0,120}}?)\s+{cur}\b", block):
            nums = re.findall(r"\d+(?:[,.]\d+)?", mt.group(1))
            if nums:
                cur_norm = _normalize_currency(cur)
                val = _parse_money(nums[-1], cur_norm)
                if val is not None:
                    found.append((cur_norm, val))
    return found[-1] if found else None


def _extract_currency_summary_table(text: str):
    currencies = r"EUR|USD|GBP|CHF|CHE|CHP|CAD|CAO|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR"
    for m in re.finditer(r"\bCurrency\b", text, flags=re.I):
        block = text[m.start(): m.start() + 360]
        if not re.search(r"\b(?:parcel|quantity|gross\s+weight|amount)\b", block, flags=re.I):
            continue
        found = []
        for mt in re.finditer(rf"([0-9][0-9 .]*[.,][0-9]{{2}})\s*({currencies})\b", block, flags=re.I):
            cur = _normalize_currency(mt.group(2))
            val = _parse_money(mt.group(1), cur)
            if val is not None:
                found.append((cur, val))
        if found:
            return found[-1]
    return None


def _extract_amount_before_value_for_customs(text: str):
    currencies = r"EUR|USD|GBP|CHF|CHE|CHP|CAD|CAO|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR"
    for m in re.finditer(r"VALUE\s+FOR\s+CUSTOMS", text, flags=re.I):
        before = text[max(0, m.start() - 180):m.start()]
        found = []
        for mt in re.finditer(rf"([0-9][0-9 .]*[.,][0-9]{{2}})\s*({currencies})\b", before, flags=re.I):
            cur = _normalize_currency(mt.group(2))
            val = _parse_money(mt.group(1), cur)
            if val is not None:
                found.append((cur, val))
        if found:
            return found[-1]
    return None


def _extract_amount_after_value_for_customs(text: str):
    currencies = r"EUR|USD|GBP|CHF|CHE|CHP|CAD|CAO|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR"
    for m in re.finditer(r"VALUE\s+FOR\s+CUSTOMS", text, flags=re.I):
        after = text[m.end(): m.end() + 650]
        found = []
        for mt in re.finditer(rf"([0-9][0-9 .]*[.,][0-9]{{2}})\s*({currencies})\b", after, flags=re.I):
            cur = _normalize_currency(mt.group(2))
            val = _parse_money(mt.group(1), cur)
            if val is not None:
                found.append((cur, val))
        if found:
            return found[-1]
    return None


def _extract_total_total_value_table(text: str):
    currencies = r"EUR|USD|GBP|CHF|CHE|CHP|CAD|CAO|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR"
    m = re.search(r"TOTAL\s+TOTAL(?:\s+TOTAL|\s+INVOICE)?[\s\S]{0,500}?VALUE([\s\S]{0,260})", text, flags=re.I)
    if not m:
        return None
    block = m.group(1)
    found = []
    for mt in re.finditer(rf"([0-9][0-9\s.,]*[.,][0-9]{{1,2}})\s*({currencies})\b|({currencies})\s*([0-9][0-9\s.,]*[.,][0-9]{{1,2}})", block, flags=re.I):
        if mt.group(1):
            cur = _normalize_currency(mt.group(2))
            val = _parse_money(mt.group(1), cur)
        else:
            cur = _normalize_currency(mt.group(3))
            val = _parse_money(mt.group(4), cur)
        if val is not None:
            found.append((cur, val))
    return found[-1] if found else None


def _extract_tax_excl_total(text: str):
    m = re.search(r"\((EUR|USD|GBP|CHF|CAD|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR)\)\s*\((?:EUR|USD|GBP|CHF|CAD|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR|AUD|NZD|NOK|SEK|DKK|TWD|THB|MYR)\)", text, flags=re.I)
    if not m:
        return None
    cur = m.group(1).upper()
    amounts: List[float] = []
    for line in text[m.end():].splitlines():
        if re.search(r"\b(?:transferred item|total weight|transporter|shipping method|incoterms)\b", line, flags=re.I):
            break
        vals = re.findall(r"\b([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+[.,][0-9]{2})\b", line)
        for raw in vals:
            v = to_float(raw)
            if v is not None:
                amounts.append(v)
    if amounts:
        return cur, max(amounts)
    return None


def _normalize_currency(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    up = v.upper().strip()
    return {"€": "EUR", "£": "GBP", "¥": "JPY", "CHE": "CHF", "CHP": "CHF", "CAO": "CAD"}.get(up, up)


def _parse_money(raw: Optional[str], currency: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    cur = (currency or "").upper()
    if re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+", s):
        return to_float(s.replace(",", ""))
    if cur in {"JPY", "KRW"} and re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+", s):
        return to_float(s.replace(",", ""))
    return to_float(s)


def _normalize_hs_candidate(hs: Optional[str]) -> Optional[str]:
    if not hs:
        return None
    if hs == "100900":
        return None
    if hs.startswith("426"):
        hs = "420" + hs[3:]
    if len(hs) == 9:
        # OCR frequently drops the final TARIC zero on 10-digit codes:
        # 420221009 -> 4202210090.
        hs = hs + "0"
    if len(hs) == 11 and hs.endswith("0"):
        return hs[:10]
    return hs


def _customs_code_block(text: str) -> str:
    m = re.search(r"\bCustoms?\s+Code\b([\s\S]{0,1600}?)(?:\n\s*TOTAL\s*\n\s*TOTA|Total\s+Goods\s+Value|Total\s+Invoice\s+Amount|Number\s+of\s+parcel)", text, flags=re.I)
    return m.group(1) if m else ""


def _sparse_ocr_pdf_pages(path: str, pages: Iterable[int], max_pages: int = 3) -> str:
    try:
        import fitz
        from PIL import Image
    except Exception:
        return ""
    cache_path = _sparse_cache_path(path, pages, max_pages)
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    out = []
    wanted = list(pages or [])
    try:
        with fitz.open(path) as pdf:
            if not wanted:
                wanted = list(range(1, len(pdf) + 1))
            for page_no in wanted[:max_pages]:
                idx = max(0, min(int(page_no) - 1, len(pdf) - 1))
                page = pdf[idx]
                pix = page.get_pixmap(dpi=320)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                txt = _ocr_invoice_page_variants(img)
                if txt.strip():
                    out.append(txt)
    except Exception:
        return ""
    text = "\n\n".join(out)
    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
    return text


def _sparse_cache_path(path: str, pages: Iterable[int], max_pages: int) -> str:
    try:
        import hashlib
        st = os.stat(path)
        key = f"{path}|{st.st_mtime_ns}|{st.st_size}|{tuple(pages or [])[:max_pages]}|sparse-v5-prep"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return str(data_dir("cache_sparse", f"{digest}.txt"))
    except Exception:
        return ""


def _legacy_hs_ocr_pdf_pages(path: str, pages: Iterable[int], max_pages: int = 3) -> str:
    """Old OCR mode kept as a HS-only fallback.

    Some low-contrast entity proformas lose customs-code rows after
    binarisation, while Tesseract PSM 12 on the original render preserves them.
    This path is only called after the main OCR still found no HS.
    """
    try:
        import fitz
        from PIL import Image
        import pytesseract
        from controldone.ocr import configure_tesseract
    except Exception:
        return ""
    configure_tesseract()
    cache_path = _legacy_hs_cache_path(path, pages, max_pages)
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    out = []
    wanted = list(pages or [])
    try:
        with fitz.open(path) as pdf:
            if not wanted:
                wanted = list(range(1, len(pdf) + 1))
            for page_no in wanted[:max_pages]:
                idx = max(0, min(int(page_no) - 1, len(pdf) - 1))
                for dpi, preprocess in ((260, False), (420, True)):
                    pix = pdf[idx].get_pixmap(dpi=dpi)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    for rot in (0, 90, 270):
                        page = img.rotate(rot, expand=True, fillcolor="white") if rot else img
                        if preprocess:
                            page = _preprocess_ocr_image(page)
                        try:
                            txt = pytesseract.image_to_string(
                                page,
                                lang="fra+eng",
                                config="--oem 3 --psm 12",
                                timeout=12,
                            )
                        except Exception:
                            txt = ""
                        if txt.strip() and (
                            _extract_invoice_hs_codes(txt)
                            or re.search(r"\b(?:Customs?\s+Code|HS|H\.S\.?)\b", txt, flags=re.I)
                        ):
                            out.append(txt)
    except Exception:
        return ""
    text = "\n\n".join(out)
    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
    return text


def _legacy_hs_cache_path(path: str, pages: Iterable[int], max_pages: int) -> str:
    try:
        import hashlib
        st = os.stat(path)
        key = f"{path}|{st.st_mtime_ns}|{st.st_size}|{tuple(pages or [])[:max_pages]}|hs-legacy-v4"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return str(data_dir("cache_sparse", f"{digest}.txt"))
    except Exception:
        return ""


def _ocr_invoice_page_variants(img) -> str:
    """OCR one invoice page with rotations and sparse page segmentation.

    Many DHL-supplied invoice scans arrive sideways.  Full-document OCR should
    stay fast, but this targeted fallback is allowed to be more aggressive
    because it only runs for invoices missing key fields.
    """
    try:
        import pytesseract
        from controldone.ocr import _ocr_quality_score, configure_tesseract
    except Exception:
        return ""
    configure_tesseract()
    candidates = []
    for rot in (0, 90, 180, 270):
        page = img.rotate(rot, expand=True, fillcolor="white") if rot else img
        page = _preprocess_ocr_image(page)
        for psm in (6, 11):
            try:
                txt = pytesseract.image_to_string(
                    page,
                    lang="fra+eng",
                    config=f"--oem 3 --psm {psm}",
                    timeout=12,
                )
            except Exception:
                txt = ""
            score = _ocr_quality_score(txt) + _invoice_ocr_keyword_bonus(txt)
            if txt.strip():
                candidates.append((score, txt))
    if not candidates:
        return ""
    out = []
    seen = set()
    for _, txt in sorted(candidates, key=lambda x: x[0], reverse=True)[:2]:
        key = re.sub(r"\s+", " ", txt.strip())[:500]
        if key and key not in seen:
            seen.add(key)
            out.append(txt)
    return "\n\n".join(out)


def _preprocess_ocr_image(img):
    try:
        from PIL import ImageOps
        gray = ImageOps.grayscale(img)
        gray = ImageOps.autocontrast(gray)
        return gray.point(lambda x: 0 if x < 180 else 255, "1")
    except Exception:
        return img


def _invoice_ocr_keyword_bonus(text: str) -> int:
    up = (text or "").upper()
    bonus = 0
    for kw in ("INVOICE", "PROFORMA", "CUSTOMS CODE", "VALUE FOR CUSTOMS", "TOTAL", *current_profile().invoice_keywords):
        if kw in up:
            bonus += 8
    if re.search(r"\b(?:EUR|USD|CHF|CHE|GBP|AED|HKD|SGD|NOK|CAD)\b", up):
        bonus += 8
    if re.search(r"\b(?:HS|CUSTOMS?|COMMODITY)\b", up):
        bonus += 8
    return bonus


def _looks_like_hs(hs: Optional[str]) -> bool:
    if not hs or not hs.isdigit() or len(hs) not in {8, 10}:
        return False
    if len(hs) == 8 and hs.startswith("20"):
        return False
    chapter = int(hs[:2])
    allowed_chapters = {
        33, 39, 40, 42, 43, 46, 48,
        *range(50, 66),
        70, 71, 73, 74, 75, 76, 83, 90, 91, 95,
    }
    return chapter in allowed_chapters


def _looks_like_tax_id(value: str, text: str) -> bool:
    if not value:
        return False
    known_id_digits = current_profile().known_tax_ids
    if any(value in known or known in value for known in known_id_digits):
        return True
    compact = re.sub(r"\s+", "", text.upper())
    v = re.escape(value)
    if re.search(rf"(?:CHE|TVA|VAT|EORI|SIRET|SIREN|EORI[:.]?|VAT[:.]?)[^A-Z0-9]{{0,8}}{v}", compact):
        return True
    if current_profile().hs_exclude_prefixes and value.startswith(current_profile().hs_exclude_prefixes):
        return True
    if re.search(rf"(?:TEL|PHONE|PH\.?|FAX|\+)[\s\S]{{0,90}}{v}", text, flags=re.I):
        return True
    return False


def _first_line_after(text: str, needles: Iterable[str]) -> Optional[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    for i, ln in enumerate(lines):
        if any(n.upper() in ln.upper() for n in needles):
            for nxt in lines[i + 1:i + 6]:
                if nxt and not nxt.startswith(":"):
                    return nxt
    return None


def _country_to_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    up = value.strip().upper()
    return {
        "FRANCE": "FR",
        "JAPAN": "JP",
        "MEXICO": "MX",
        "MEXIQUE": "MX",
        "EU": "EU",
    }.get(up, up[:2] if len(up) == 2 else None)


def _amount_after_labels(text: str, labels: Iterable[str]) -> Optional[float]:
    for label in labels:
        pat = re.escape(label).replace("\\ ", r"\s+")
        m = re.search(rf"{pat}[\s\S]{{0,120}}?([0-9][0-9\s.,]*\.[0-9]{{2}}|[0-9][0-9\s.,]*,[0-9]{{2}})", text, re.I)
        if m:
            return to_float(m.group(1))
    return None


def _amount_after_line_label(text: str, labels: Iterable[str]) -> Optional[float]:
    """Find the first decimal number in the few lines after an exact label."""
    lines = [ln.strip() for ln in text.splitlines()]
    wanted = {x.upper() for x in labels}
    for i, ln in enumerate(lines):
        if ln.upper() in wanted:
            for nxt in lines[i + 1:i + 8]:
                v = to_float(nxt)
                if v is not None:
                    return v
    return None


def _extract_dau_currency_amount_fx(text: str):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    currencies = {"EUR", "USD", "GBP", "CHF", "CAD", "JPY", "CNY", "HKD", "KRW", "SGD", "MXN", "BRL", "INR", "AED", "SAR"}
    for i, ln in enumerate(lines):
        if ln in currencies and i + 1 < len(lines):
            amount = to_float(lines[i + 1])
            fx = to_float(lines[i + 2]) if i + 2 < len(lines) else None
            if amount is not None and amount > 0:
                return ln, amount, fx
    return None, None, None


def _enrich_legacy_sad(d: Document, text: str, source_file: Optional[str]) -> None:
    """Extract useful fields from old single administrative document layouts.

    These pages do not expose the modern Delta labels, and OCR returns a
    row-major stream.  We intentionally use conservative anchors around box 22
    and filename/AWB conventions rather than neighbour labels.
    """
    up = text.upper()
    awb = _first(r"\b(CDG_[0-9]{8,12}_[0-9]{6})\b", text) or _first(r"\b([0-9]{10})_(?:ENT|INV|HWB)_", os.path.basename(source_file or ""))
    if awb:
        d.awb = re.search(r"([0-9]{8,12})", awb).group(1) if re.search(r"([0-9]{8,12})", awb) else awb
        d.transport_doc = d.awb
        if d.awb not in d.referenced_awbs:
            d.referenced_awbs.append(d.awb)
        if d.awb not in d.referenced_invoices:
            d.referenced_invoices.append(d.awb)

    m = re.search(r"\b000\b[\s|]+([0-9][0-9. ]*,[0-9]{2})[\s|]+(?:IM|EU)\b", text)
    if m:
        amount = to_float(m.group(1))
        if amount is not None:
            d.total_amount = amount

    cur = None
    for mt in re.finditer(r"\b(EUR|USD|GBP|CHF|CAD|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR)\b", up):
        window = up[mt.start(): mt.start() + 120]
        if "MODE DE REPR" in window or "FCA" in window or "FR |" in window:
            cur = mt.group(1)
            break
    if not cur:
        # Usually appears between transport mode and FR before incoterm.
        mcur = re.search(r"\b(?:AVION|AIR|MER|ROUTE)\s*\|\s*(EUR|USD|GBP|CHF|CAD|JPY|CNY|HKD|KRW|SGD|MXN|BRL|INR|AED|SAR)\s*\|\s*FR\b", up)
        cur = mcur.group(1) if mcur else None
    if cur:
        d.currency = cur

    vats = find_all_vat_fr(text)
    if vats:
        # Prefer tax reference document after "1008 -".
        ref_vat = _first(r"1008\s*-\s*(FR\d{11})", text)
        d.importer.vat = ref_vat or vats[-1]

    hs_codes = _extract_hs_codes_from_text(text, exclude=d.awb)
    if hs_codes:
        d.lines = [
            Line(item_no=i, hs_code=hs)
            for i, hs in enumerate(hs_codes, start=1)
        ]

    # Old SADs frequently expose U165/M195/A445 in one flattened stream.  The
    # exact split is less reliable than Delta IE, so keep only high-confidence
    # values when a code is immediately followed by a plausible amount.
    d.dd = _legacy_tax_amount(text, "U165", default=d.dd)
    d.at = _legacy_tax_amount(text, "M195", default=d.at)
    d.tva_auto_liquidee = _legacy_tax_amount(text, "A445", default=d.tva_auto_liquidee)


def _extract_hs_codes_from_text(text: str, exclude: Optional[str] = None) -> List[str]:
    out = []
    ex = _clean_digits(exclude)
    prefixes = current_profile().hs_exclude_prefixes
    for raw in re.findall(r"\b([0-9]{10})\b", text):
        if raw == ex or (prefixes and raw.startswith(prefixes)):
            continue
        if _looks_like_hs(raw):
            out.append(raw)
    return _dedupe(out)


def _legacy_tax_amount(text: str, code: str, default: Optional[float] = None) -> Optional[float]:
    m = re.search(rf"\b{code}\b(?:\s*\|\s*[0-9]{{1,2}})?\s*\|\s*([0-9][0-9. ]*,[0-9]{{2}})", text)
    if not m:
        return default
    val = to_float(m.group(1))
    return val if val is not None else default


def _extract_dau_article(text: str) -> Optional[Line]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if re.fullmatch(r"\d{8}", ln) and i + 1 < len(lines) and re.fullmatch(r"\d{2}", lines[i + 1]):
            hs = ln + lines[i + 1]
            origin = lines[i + 2] if i + 2 < len(lines) and re.fullmatch(r"[A-Z]{2}", lines[i + 2]) else None
            gross = to_float(lines[i + 3]) if i + 3 < len(lines) else None
            regime = lines[i + 4] if i + 4 < len(lines) else None
            net = to_float(lines[i + 5]) if i + 5 < len(lines) else None
            pref = None
            amount = None
            for j in range(i + 6, min(i + 20, len(lines))):
                if re.fullmatch(r"\d{3}", lines[j]) and pref is None:
                    pref = lines[j]
                if re.fullmatch(r"\d{3,}", lines[j]) and amount is None:
                    amount = to_float(lines[j])
            return Line(
                item_no=1,
                hs_code=hs,
                origin_country=origin,
                gross_weight_kg=gross,
                net_weight_kg=net,
                preference=pref,
                amount=amount,
                description=None,
            )
    return None
