"""Helpers shared by all format parsers."""
from __future__ import annotations

import re
from typing import Optional, List


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

_NBSP = " "
_NARROW_NBSP = " "


def to_float(s: Optional[str]) -> Optional[float]:
    """Parse a string into a float, accepting French / English / mixed formats.

    Handles:
        '1 234,56' / '1 234.56' / '1,234.56' / '1234.56' / '1234,56'
        '1\xa0234,56' (non-breaking space) / '1 234,56'
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    s = s.replace(_NBSP, "").replace(_NARROW_NBSP, "").replace(" ", "")
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


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

def first_match(pattern, text: str, group: int = 1, flags: int = re.I | re.S) -> Optional[str]:
    m = re.search(pattern, text, flags=flags)
    if not m:
        return None
    try:
        return m.group(group).strip()
    except IndexError:
        return m.group(0).strip()


def all_matches(pattern, text: str, group: int = 1, flags: int = re.I | re.S) -> List[str]:
    out = []
    for m in re.finditer(pattern, text, flags=flags):
        try:
            out.append(m.group(group).strip())
        except IndexError:
            out.append(m.group(0).strip())
    return out


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

MRN_RE = re.compile(r"\b(\d{2}[A-Z]{2}[A-Z0-9]{12,16})\b")


def find_mrn(text: str) -> Optional[str]:
    m = MRN_RE.search(text.upper())
    return m.group(1) if m else None


def find_all_mrns(text: str) -> List[str]:
    seen, out = set(), []
    for m in MRN_RE.finditer(text.upper()):
        v = m.group(1)
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def find_vat_fr(text: str) -> Optional[str]:
    """Find the first French VAT number FRxxxxxxxxxxx (11 digits)."""
    # FR7 = code rubrique fiscale: FR7 FRxxxxxxxxxxx
    m = re.search(r"\bFR7\b[\s\-:]*?\b(FR\d{11})\b", text, flags=re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"REFERENCE(?:S)?\s+FISC(?:ALES?)?[^A-Z]*?(FR\d{11})", text, flags=re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b(FR\d{11})\b", text)
    return m.group(1).upper() if m else None


def find_all_vat_fr(text: str) -> List[str]:
    seen, out = set(), []
    for m in re.finditer(r"\b(FR\d{11})\b", text):
        v = m.group(1).upper()
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# AWB / LTA
# ---------------------------------------------------------------------------

def find_awb(text: str) -> Optional[str]:
    """Find an Air Waybill number.

    Common formats:
        - 3 digits + 8 digits: 057-58278021 or 057 58278021
        - 11 digits in a row: 5858515143 (10) or 58585151434 (11)
        - 'XXX/EK XXXXXXXX' style
        - 'N741 - 131/22512033' (AKANEA documents)
    """
    # 3-digit prefix + dash + 8-digit
    m = re.search(r"\b(\d{3}[\s\-]\d{8})\b", text)
    if m:
        return m.group(1).replace(" ", "-")
    # 8-12 digit standalone (skip phone numbers — must be 10-11 digits)
    return None


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})\b")


def parse_date_to_iso(s: str) -> Optional[str]:
    """Parse a date string to YYYY-MM-DD ISO format. Returns None on failure."""
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        # already ISO?
        m2 = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
        if m2:
            return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
        return None
    d, mo, y = m.group(1), m.group(2), m.group(3)
    if len(y) == 2:
        y = "20" + y if int(y) < 70 else "19" + y
    return f"{y}-{int(mo):02d}-{int(d):02d}"
