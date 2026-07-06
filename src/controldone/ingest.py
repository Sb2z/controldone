"""Ingest layer — read PDF or Excel files and yield page-level text.

For PDFs we delegate to `controldone.ocr.extract_text_per_page`, which handles
native text, OCR fallback, caching and parallelism.

For Excel files (.xlsx, .xls, .xlsm) we serialise each sheet to a
"text page" so the same downstream classifier/parser pipeline can be
used uniformly. Each sheet becomes one "page" with cell content joined
by tabs / newlines and the sheet name prepended as a header.

Public API
----------
    read_document(path) -> IngestedDocument
    read_directory(folder) -> Iterable[IngestedDocument]

`IngestedDocument` is a thin record carrying:
    - path
    - kind: "pdf" | "excel"
    - pages: list[str]   # one item per page (or per sheet for Excel)
    - sheet_names: list[str] | None   # only for Excel
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from controldone.ocr import extract_text_per_page

try:
    from openpyxl import load_workbook
    _OPENPYXL_OK = True
except ImportError:
    _OPENPYXL_OK = False


PDF_EXTS = (".pdf",)
EXCEL_EXTS = (".xlsx", ".xlsm", ".xls")


@dataclass
class IngestedDocument:
    path: str
    kind: str                              # "pdf" | "excel"
    pages: List[str] = field(default_factory=list)
    sheet_names: Optional[List[str]] = None
    error: Optional[str] = None            # set if extraction failed

    @property
    def basename(self) -> str:
        return os.path.basename(self.path)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _read_pdf(path: str) -> IngestedDocument:
    try:
        pages = extract_text_per_page(path)
        return IngestedDocument(path=path, kind="pdf", pages=pages)
    except Exception as e:
        return IngestedDocument(
            path=path, kind="pdf", pages=[],
            error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

def _excel_sheet_to_text(ws) -> str:
    """Serialise a worksheet to a single text block.

    Conventions:
        - each row is one line
        - cells separated by `\t` (tabs) — preserves column alignment hints
        - empty cells are represented by an empty string (not "None")
    """
    out_lines = []
    for row in ws.iter_rows(values_only=True):
        cells = [
            ("" if c is None else str(c).strip())
            for c in row
        ]
        # Strip trailing empties so empty rows / right-padding don't bloat the output
        while cells and cells[-1] == "":
            cells.pop()
        if not cells:
            continue
        out_lines.append("\t".join(cells))
    return "\n".join(out_lines)


def _read_excel(path: str) -> IngestedDocument:
    if not _OPENPYXL_OK:
        return IngestedDocument(
            path=path, kind="excel", pages=[],
            error="ImportError: openpyxl manquant — pip install openpyxl",
        )
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
        pages = []
        names = []
        for sn in wb.sheetnames:
            ws = wb[sn]
            text = _excel_sheet_to_text(ws)
            # Prepend a sheet header so classifiers/parsers can use the sheet name
            page_text = f"[SHEET:{sn}]\n{text}"
            pages.append(page_text)
            names.append(sn)
        wb.close()
        return IngestedDocument(path=path, kind="excel", pages=pages, sheet_names=names)
    except Exception as e:
        return IngestedDocument(
            path=path, kind="excel", pages=[],
            error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_document(path: str) -> IngestedDocument:
    """Read any supported document. Unknown extensions return an error."""
    ext = os.path.splitext(path)[1].lower()
    if ext in PDF_EXTS:
        return _read_pdf(path)
    if ext in EXCEL_EXTS:
        return _read_excel(path)
    return IngestedDocument(
        path=path, kind="unknown", pages=[],
        error=f"UnsupportedFormat: extension {ext}",
    )


def iter_document_paths(folder: str,
                        include_pdf: bool = True,
                        include_excel: bool = True,
                        recursive: bool = True,
                        skip_transport_docs: bool = True) -> Iterable[str]:
    """Yield supported document paths without reading/OCRing them.

    Real broker drops often contain nested folders plus HWB/AWB transport
    copies.  Those transport copies are not used by the v4 business controls
    and are expensive to OCR, so they are skipped by default.
    """
    if not os.path.isdir(folder):
        return
    walker = os.walk(folder) if recursive else [(folder, [], sorted(os.listdir(folder)))]
    for root, _, files in walker:
        for fname in sorted(files):
            if fname.startswith("._") or fname == ".DS_Store":
                continue
            upper = fname.upper()
            if skip_transport_docs and ("_HWB_" in upper or "_AWB_" in upper or "HAWB" in upper):
                continue
            full = os.path.join(root, fname)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext in PDF_EXTS and include_pdf:
                yield full
            elif ext in EXCEL_EXTS and include_excel:
                yield full


def read_directory(folder: str,
                   include_pdf: bool = True,
                   include_excel: bool = True,
                   recursive: bool = True,
                   skip_transport_docs: bool = True) -> Iterable[IngestedDocument]:
    """Yield ingested documents for all supported files in `folder`."""
    for path in iter_document_paths(
        folder,
        include_pdf=include_pdf,
        include_excel=include_excel,
        recursive=recursive,
        skip_transport_docs=skip_transport_docs,
    ):
        yield read_document(path)
