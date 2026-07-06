"""Page-level document classifier.

Given the pages of an ingested document, classify each page as one of:
    prestation_dhl / prestation_schenker / prestation_dsv / prestation_worldnet
    declaration_delta_ie_dhl / declaration_delta_ie_akanea / declaration_h7 / declaration_dau
    invoice_entity / invoice_entity_proforma / invoice_entity_delivery_note
    invoice_parfumerie_versailles / invoice_launchmetrics / invoice_dhl_hawb
    invoice_generic
    packing_list / awb / cgv / unknown

Then group consecutive pages of the same logical document into segments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from controldone.profile import current_profile


def _entity_kw(up: str) -> bool:
    """True when the text carries one of the controlled entity's keywords."""
    return any(kw in up for kw in current_profile().invoice_keywords)


# ---------------------------------------------------------------------------
# Doc-type taxonomy
# ---------------------------------------------------------------------------

PRESTATION_TYPES = {
    "prestation_dhl",
    "prestation_schenker",
    "prestation_dsv",
    "prestation_worldnet",
}
DECLARATION_TYPES = {
    "declaration_delta_ie_dhl",
    "declaration_delta_ie_akanea",
    "declaration_h7",
    "declaration_dau",
}
INVOICE_TYPES = {
    "invoice_entity",
    "invoice_entity_proforma",
    "invoice_entity_delivery_note",
    "invoice_parfumerie_versailles",
    "invoice_launchmetrics",
    "invoice_dhl_hawb",
    "invoice_generic",
}
SKIP_TYPES = {"packing_list", "awb", "cgv", "unknown"}


@dataclass
class PageSegment:
    doc_type: str
    start_page: int     # 1-indexed
    end_page: int       # inclusive
    text: str
    sheet_name: Optional[str] = None    # for Excel inputs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has(up: str, *needles: str) -> bool:
    return any(n in up for n in needles)


# ---------------------------------------------------------------------------
# Per-page classifier
# ---------------------------------------------------------------------------

def classify_page(text: str, kind_hint: str = "pdf") -> str:
    """Classify a single page (or Excel sheet) of text.

    `kind_hint` is "pdf" or "excel" — Excel sheets get extra heuristics.
    """
    up = text.upper()

    # =======================================================================
    # PRESTATIONS
    # =======================================================================

    # DHL Express prestation
    if "DHL EXPRESS" in up and _has(up, "FACTURE DE DROITS ET TAXES", "DROITS ET TAXES") \
            and _has(up, "FACTURE", "INVOICE"):
        return "prestation_dhl"
    if "DHL" in up and _has(up, "DROITS ET TAXES") and "IMPORTATION" in up:
        return "prestation_dhl"

    # Worldnet prestation (NEW) — distinct from "Method of Dispatch: Worldnet"
    # which appears in shipper invoices using Worldnet as carrier.
    # Must have a Worldnet-as-billing-entity signature.
    if _has(up, "WORLDNET INTERNATIONAL FRANCE", "WORLDNET INTERNATIONAL LTD") \
            and _has(up, "FACTURE", "INVOICE"):
        return "prestation_worldnet"
    if ("FR80 432 500 551" in up or "FR80432500551" in up) and _has(up, "FACTURE", "INVOICE"):
        return "prestation_worldnet"
    # Worldnet header line + duties block
    if "WORLDNET" in up and _has(up, "DROITS ET TAXES", "TVA À L'IMPORTATION", "TVA A L'IMPORTATION") \
            and _has(up, "NUMÉRO DE FACTURE", "NUMERO DE FACTURE"):
        return "prestation_worldnet"

    # DSV before Schenker (same template)
    if "DSV AIR" in up and _has(up, "FACTURE NO", "N° FACTURE", "FACTURE NO."):
        return "prestation_dsv"
    if "DSV AIR" in up and _has(up, "DEBOURS", "DOUANE"):
        return "prestation_dsv"

    # Schenker
    if "SCHENKER" in up and _has(up, "DEBOURS", "DROIT DE DOUANE") \
            and _has(up, "FACTURE", "INVOICE"):
        return "prestation_schenker"

    # Forwarder cover page (skip)
    if _has(up, "DSV AIR", "SCHENKER") and "ENVOI DOCUMENT" in up:
        return "unknown"

    # =======================================================================
    # CGV / GENERAL CONDITIONS (skip)
    # =======================================================================
    if _has(up, "CONDITIONS GÉNÉRALES", "CONDITIONS GENERALES", "GENERAL TERMS"):
        if _has(up, "TRANSPORT", "VENTE", "SERVICE", "STANDARD"):
            return "cgv"

    # =======================================================================
    # DECLARATIONS
    # =======================================================================

    # AKANEA Delta IE (NEW) — has its own header signature
    if _has(up, "AKANEA DOUANE", "ÉDITION AKANEA", "EDITION AKANEA") and "DELTA IE" in up:
        return "declaration_delta_ie_akanea"
    if _has(up, "AKANEA") and _has(up, "DELTA IE") and _has(up, "MRN", "CRN"):
        return "declaration_delta_ie_akanea"
    # AKANEA continuation pages (article + annexe)
    if _has(up, "AKANEA") and _has(up, "DELTA IE", "ARTICLE 1/", "ANNEXE"):
        return "declaration_delta_ie_akanea"

    # DHL Delta IE
    if "DHL DELTA IE" in up:
        return "declaration_delta_ie_dhl"
    # DHL Delta IE continuation page (article)
    if "ARTICLE" in up and "REGIME" in up and "NOMENCLATURE" in up and "MASSE NETTE" in up:
        return "declaration_delta_ie_dhl"

    # Delta H7
    if _has(up, "DELTA H7", "DELTA-H7", "DELTAH7"):
        return "declaration_h7"

    # DAU / Justificatif dédouanement
    if _has(up, "JUSTIFICATIF DÉDOUANEMENT", "JUSTIFICATIF DEDOUANEMENT"):
        return "declaration_dau"
    if "FRA0619B" in up and _has(up, "DONNÉES COMPTABLES", "DONNEES COMPTABLES"):
        return "declaration_dau"
    if _has(up, "COMMUNAUTE EUROPEENNE", "COMMUNAUTÉ EUROPÉENNE") \
            and _has(up, "DECLARATION", "DÉCLARATION") \
            and _has(up, "BUREAU DE DESTINATION", "BUREAU D'ENTREE", "BUREAU D’ENTREE", "CONTROLE PAR"):
        return "declaration_dau"

    # =======================================================================
    # AWB
    # =======================================================================
    if _has(up, "AIR WAYBILL", "AIRWAYBILL") and _has(up, "SHIPPER", "CONSIGNEE", "ISSUED BY"):
        return "awb"

    # =======================================================================
    # PACKING LIST
    # =======================================================================
    if _has(up, "PACKING LIST", "SHIPMENT PACKING LIST"):
        return "packing_list"

    # =======================================================================
    # INVOICES
    # =======================================================================

    # LaunchMetrics (NEW) — Excel supplier export format
    if "LAUNCHMETRICS" in up and _has(up, "INVOICE", "SHIP FROM", "SHIP TO"):
        return "invoice_launchmetrics"
    # LaunchMetrics fallback: signature columns
    if _has(up, "INCOMING INVOICE NUMBER", "INCOMING AIR WAYBILL NUMBER") \
            and _has(up, "STYLE", "BARCODE", "CUSTOM CODE"):
        return "invoice_launchmetrics"

    # Parfumerie Versailles (NEW) — Mexican Spanish supplier
    if _has(up, "PARFUMERIE VERSAILLES") and _has(up, "PVE891221", "FACTURA", "COPIA DE FACTURA", "FACTURE"):
        return "invoice_parfumerie_versailles"
    # FAI invoice number prefix (Parfumerie Versailles only)
    if re.search(r"\bFAI\d{6,}\b", up) and _has(up, "PARFUMERIE", "PVE891221", "MXN"):
        return "invoice_parfumerie_versailles"

    # Controlled-entity PROFORMA INVOICE
    if _entity_kw(up) and _has(up, "PROFORMA INVOICE", "PRO-FORMA INVOICE", "PRO FORMA INVOICE"):
        return "invoice_entity_proforma"

    # Controlled-entity standard INVOICE
    if _entity_kw(up) and "INVOICE" in up and _has(up, "INVOICE NO", "INVOICE NUMBER", "HS CODE"):
        return "invoice_entity"
    if _entity_kw(up) and _has(up, "HS CODE", "HS-CODE") and _has(up, "TOTAL", "AMOUNT"):
        return "invoice_entity"

    # Controlled-entity delivery note (Turkey-style)
    if _entity_kw(up) and _has(up, "DELIVERY NOTE NO", "DELIVERY NOTE NUMBER"):
        return "invoice_entity_delivery_note"

    # DHL HAWB Commercial Invoice (DHL_HAWB_*_inv.pdf)
    # These are commercial invoices generated by DHL for the shipper
    if "DHL" in up and _has(up, "COMMERCIAL INVOICE", "AWB NO", "AWB NUMBER", "HAWB"):
        return "invoice_dhl_hawb"
    if _has(up, "COMMERCIAL INVOICE") and _has(up, "AWB", "HAWB", "WAYBILL"):
        return "invoice_dhl_hawb"

    # Generic invoice — has HS code + INVOICE / FACTURE label
    if _has(up, "INVOICE", "FACTURE") and _has(up, "HS CODE", "HS-CODE", "CUSTOMS CODE"):
        return "invoice_generic"
    if _has(up, "INVOICE PROFORMA", "PROFORMA INVOICE") and _has(up, "VALUE FOR CUSTOMS", "CUSTOMS ONLY"):
        return "invoice_generic"
    if _has(up, "PRO-FORMA INVOICE", "PROFORMA INVOICE", "PRO-FORMA", "PROFORMA") \
            and _has(up, "RECIPIENT VAT", "TRANSFER NO", "CUSTOM REF", "CUSTOMS", "TAX EXCL"):
        return "invoice_generic"
    if _has(up, "NO COMMERCIAL VALUE", "VALUE FOR CUSTOMS ONLY") and _has(up, "CUSTOMS", "TOTAL", "CURRENCY"):
        return "invoice_generic"
    if _entity_kw(up) and _has(up, "DELIVERY ADVICE", "VALUE FOR CUSTOMS") and _has(up, "TOTAL", "CURRENCY", "CUSTOMS"):
        return "invoice_generic"
    if _has(up, "TARIFF CODE", "TARIF CODE") and _has(up, "DESCRIPTION OF GOODS", "PRICE TOTAL", "ORIGIN"):
        return "invoice_generic"

    return "unknown"


# ---------------------------------------------------------------------------
# Page → segment grouping
# ---------------------------------------------------------------------------

_MRN_RE = re.compile(r"\b(\d{2}[A-Z]{2}[A-Z0-9]{12,16})\b")


def _decl_id(text: str) -> Optional[str]:
    """Stable 15-char prefix of MRN — same for MRN/CRN variants of one decl."""
    m = _MRN_RE.search(text.upper())
    return m.group(1)[:15] if m else None


def _group(page_types: List[str], page_texts: List[str]) -> List[PageSegment]:
    """Group consecutive same-type pages into a segment.

    Special rules:
      * Declaration pages with the same 15-char MRN prefix are merged.
      * Prestation continuation pages (often "unknown" tail) are absorbed.
      * Invoice continuations are absorbed up to the next non-invoice type.
    """
    n = len(page_types)
    segments: List[PageSegment] = []
    i = 0
    while i < n:
        t = page_types[i]
        j = i + 1

        if t in DECLARATION_TYPES:
            cur_id = _decl_id(page_texts[i])
            while j < n:
                nt = page_types[j]
                # Same declaration type, or unknown continuation, with same MRN prefix
                if nt == t or nt == "unknown":
                    nxt_id = _decl_id(page_texts[j])
                    if cur_id and nxt_id and nxt_id != cur_id:
                        break
                    j += 1
                elif nt in DECLARATION_TYPES and nt != t:
                    break
                else:
                    break

        elif t in PRESTATION_TYPES:
            while j < n and page_types[j] in (t, "unknown"):
                if page_types[j] in PRESTATION_TYPES and page_types[j] != t:
                    break
                j += 1

        elif t in INVOICE_TYPES:
            while j < n and page_types[j] in INVOICE_TYPES:
                j += 1

        elif t == "packing_list":
            while j < n and page_types[j] == "packing_list":
                j += 1

        elif t == "cgv":
            while j < n and page_types[j] == "cgv":
                j += 1

        merged_text = "\n\n".join(page_texts[i:j])
        segments.append(PageSegment(
            doc_type=t, start_page=i + 1, end_page=j, text=merged_text
        ))
        i = j

    return segments


def classify_pages(page_texts: List[str], kind_hint: str = "pdf") -> List[PageSegment]:
    """Classify each page and group into logical segments."""
    types = [classify_page(t, kind_hint=kind_hint) for t in page_texts]
    return _group(types, page_texts)
