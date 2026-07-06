"""Application pipeline for ControlDOne.

This module is the integration point for future apps and APIs.  It reads
input documents, classifies/parses them, builds dossiers, and runs business
validation.  Presentation concerns such as CLI arguments and Excel writing
belong outside this file.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import traceback
from typing import Callable, List, Tuple

from controldone.classification import PageSegment, classify_pages
from controldone.ingest import iter_document_paths, read_document
from controldone.matching import build_bundles_v4
from controldone.models import Document
from controldone.parsing import (
    enrich_invoice_from_source,
    parse_segments,
    reconcile_invoice_with_declaration_evidence,
)
from controldone.profile import ClientProfile, resolve_default_profile, use_profile
from controldone.validation import validate_bundle


@dataclass
class ControlRun:
    """Complete result of one analysis run."""

    bundles: List
    errors: List[Tuple[str, str]]
    documents: List[Document]


ProgressCallback = Callable[[int, int, str], None]


def analyze(input_path: str, progress: ProgressCallback | None = None,
            *, profile: ClientProfile | None = None) -> ControlRun:
    """Analyze a PDF/Excel file or a folder of documents.

    ``profile`` is the injection point for all client-specific configuration.
    It is activated for the whole run via contextvars so the parsing and
    validation layers read it without any global state (multi-tenant safe).
    When omitted, the default profile is resolved (CONTROLDONE_CLIENT env var
    or the single configured client under config/clients/).
    """
    with use_profile(profile or resolve_default_profile()):
        return _analyze(input_path, progress)


def _analyze(input_path: str, progress: ProgressCallback | None) -> ControlRun:
    """Run one analysis with the active profile already set."""
    if os.path.isdir(input_path):
        paths = list(iter_document_paths(input_path, include_pdf=True, include_excel=True))
    else:
        paths = [input_path]

    documents: List[Document] = []
    errors: List[Tuple[str, str]] = []

    total_items = len(paths)
    for idx, path in enumerate(paths, start=1):
        if progress:
            progress(idx, total_items, path)
        item = read_document(path)
        if item.error:
            errors.append((item.path, item.error))
            continue
        try:
            segments = classify_pages(item.pages, kind_hint=item.kind)
            parsed = parse_segments(segments, item.path)
            if not parsed:
                parsed = _fallback_docs_from_filename(item.path, item.pages, segments)
            for doc in parsed:
                _annotate_source_context(doc, item.path, input_path)
                if doc.kind == "invoice":
                    enrich_invoice_from_source(doc)
            documents.extend(parsed)
        except Exception as exc:
            errors.append((item.path, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))

    bundles = build_bundles_v4(documents)
    for b in bundles:
        _reconcile_bundle_from_evidence(b)
    for b in bundles:
        validate_bundle(b)
    return ControlRun(bundles=bundles, errors=errors, documents=documents)


def process(input_path: str) -> Tuple[List, List[Tuple[str, str]], List[Document]]:
    """Backward-compatible tuple API used by older local scripts."""
    result = analyze(input_path)
    return result.bundles, result.errors, result.documents


def _reconcile_bundle_from_evidence(bundle) -> None:
    if not bundle.invoices or not bundle.declarations:
        return
    for inv in bundle.invoices:
        decl = _best_decl_for_invoice_context(inv, bundle.declarations)
        if decl:
            reconcile_invoice_with_declaration_evidence(inv, decl)


def _best_decl_for_invoice_context(inv: Document, declarations: List[Document]) -> Document | None:
    inv_awb = _norm_ref(inv.awb)
    inv_sub = (inv.extras or {}).get("source_awb_folder")
    inv_no = _norm_ref(inv.invoice_number)
    best = None
    best_score = -1
    for decl in declarations:
        score = 0
        dec_sub = (decl.extras or {}).get("source_awb_folder")
        if inv_sub and dec_sub and inv_sub == dec_sub:
            score += 100
        dec_refs = [_norm_ref(x) for x in decl.referenced_invoices]
        if inv_no and any(inv_no == r or inv_no in r or r in inv_no for r in dec_refs):
            score += 60
        dec_awbs = {_norm_ref(decl.awb), *[_norm_ref(x) for x in decl.referenced_awbs]}
        if inv_awb and inv_awb in dec_awbs:
            score += 60
        if score > best_score:
            best_score = score
            best = decl
    return best or (declarations[0] if declarations else None)


def _annotate_source_context(doc: Document, path: str, input_path: str) -> None:
    """Attach supplier folder context used as a hard matching boundary.

    New DHL drops are structured as:
        <dossier>/<AWB>/<AWB>_INV_3.pdf
        <dossier>/<AWB>/<AWB>_ENT_1.pdf
        <dossier>/<dossier>.pdf

    The top folder is a stronger signal than OCR text.  We keep it in extras
    so the matcher can avoid cross-dossier contamination.
    """
    if not doc.extras:
        doc.extras = {}
    try:
        base = input_path if os.path.isdir(input_path) else os.path.dirname(input_path)
        rel = os.path.relpath(path, base)
        parts = rel.split(os.sep)
    except Exception:
        parts = []
    base_name = os.path.basename(os.path.abspath(base)) if "base" in locals() else ""
    if os.path.isdir(input_path) and re.match(r"[A-Z]{2,4}\d{5,}$", base_name, re.I):
        doc.extras["source_dossier"] = base_name
        if len(parts) >= 2:
            doc.extras["source_awb_folder"] = parts[0]
        return
    if len(parts) >= 2:
        doc.extras["source_dossier"] = parts[0]
    if len(parts) >= 3:
        doc.extras["source_awb_folder"] = parts[1]


def _fallback_docs_from_filename(path: str, pages: List[str], segments: List[PageSegment]) -> List[Document]:
    """Create minimal docs when OCR is unavailable and the filename is explicit.

    This keeps image-only invoices visible in the report and lets filename
    conventions pair INV/ENT files for manual follow-up.
    """
    base = os.path.basename(path)
    text = "\n".join(pages)
    out: List[Document] = []
    leading = _leading_ref(base)
    if "_INV_" in base.upper() or "HAWB" in base.upper():
        out.append(Document(
            kind="invoice",
            format="filename_fallback",
            source_file=path,
            source_pages=list(range(1, max(len(pages), 1) + 1)),
            text=text,
            invoice_number=leading or _first(r"\b(INV[-_A-Z0-9]{4,})\b", base),
            awb=leading if leading and len(leading) >= 8 else None,
            extras={"fallback_reason": "OCR/text extraction unavailable"},
        ))
    elif re.match(r"[A-Z]{2,4}\d{5,}$", base, re.I):
        out.append(Document(
            kind="prestation",
            format="filename_fallback",
            source_file=path,
            source_pages=list(range(1, max(len(pages), 1) + 1)),
            text=text,
            invoice_number=os.path.splitext(base)[0],
            forwarder="DHL",
            currency="EUR",
            extras={"fallback_reason": "OCR/text extraction unavailable"},
        ))
    return out


def _leading_ref(name: str) -> str:
    m = re.match(r"([0-9]{8,12})_", name)
    if m:
        return m.group(1)
    m = re.search(r"HAWB[_ -]?([0-9]{8,12})", name, re.I)
    if m:
        return m.group(1)
    return ""


def _first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else ""


def _norm_ref(v: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", v or "").upper()
