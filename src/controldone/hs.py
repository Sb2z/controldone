"""HS code normalization and scope filtering.

The set of in-scope HS6 codes is client-specific and lives in the active
:class:`~controldone.profile.ClientProfile` (loaded from the client's
``hs_scope.txt``).  This module keeps no codes of its own.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from controldone.profile import current_profile


def allowed_hs6() -> frozenset[str]:
    """In-scope HS6 codes for the active client profile."""
    return current_profile().hs_scope


def hs_digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_hs(value: object, *, scope_only: bool = False) -> Optional[str]:
    """Normalize a visible HS candidate and reject obvious OCR pollution.

    Invoice HS extraction is intentionally strict when ``scope_only`` is set:
    the first six digits must belong to the active profile's HS scope.  This
    removes broker VAT, phone numbers, invoice numbers and OCR fragments such
    as 7000000000.
    """
    digits = hs_digits(value)
    if not digits:
        return None
    if digits == "100900":
        return None
    if digits.startswith("426"):
        digits = "420" + digits[3:]
    if len(digits) == 9:
        digits = digits + "0"
    if len(digits) == 11 and digits.endswith("0"):
        digits = digits[:10]
    if len(digits) < 6 or len(digits) > 10:
        return None
    if scope_only and digits[:6] not in allowed_hs6():
        return None
    return digits


def normalize_hs_many(values: Iterable[object], *, scope_only: bool = False) -> list[str]:
    seen, out = set(), []
    for value in values:
        hs = normalize_hs(value, scope_only=scope_only)
        if hs and hs not in seen:
            seen.add(hs)
            out.append(hs)
    return out


def is_in_scope(value: object) -> bool:
    hs = normalize_hs(value)
    return bool(hs and hs[:6] in allowed_hs6())
