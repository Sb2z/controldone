"""Références : normalisation et comparaison (SPEC §5.2 « Références », §8.4)."""

from __future__ import annotations

import re

__all__ = [
    "LONGUEUR_MIN_CONTAINMENT",
    "est_mrn",
    "mrn_egaux",
    "mrn_prefixe",
    "norm_ref",
    "norm_ref_containment",
    "norm_ref_transport",
    "ref_compatibles",
    "ref_egales",
    "ref_transport_compatibles",
    "ref_transport_egales",
]

#: §8.4 : l'une contient l'autre et la plus courte a au moins 5 caractères.
LONGUEUR_MIN_CONTAINMENT = 5
_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def norm_ref(x: str | None) -> str:
    """Majuscules, suppression de tout caractère hors ``[A-Z0-9]`` (§5.2)."""
    if not x:
        return ""
    from controldone.normalize.text import sans_accents

    return _NON_ALNUM.sub("", sans_accents(x).upper())


def norm_ref_containment(x: str | None) -> str:
    """Forme de comparaison par inclusion : zéros de tête supprimés des segments **numériques purs**.

    Les segments sont ceux de la chaîne brute (séparés par tout caractère non alphanumérique) :
    ``"INV-000123"`` -> ``"INV123"`` ; ``"A00123"`` reste ``"A00123"`` (segment mixte).
    """
    if not x:
        return ""
    from controldone.normalize.text import sans_accents

    segments = re.split(r"[^A-Z0-9]+", sans_accents(x).upper())
    sortie = []
    for s in segments:
        if not s:
            continue
        sortie.append((s.lstrip("0") or "0") if s.isdigit() else s)
    return "".join(sortie)


def ref_egales(x: str | None, y: str | None) -> bool:
    """``norm_ref(x) == norm_ref(y)`` (et non vides)."""
    a, b = norm_ref(x), norm_ref(y)
    return bool(a) and a == b


def ref_compatibles(x: str | None, y: str | None) -> bool:
    """Égales, ou l'une contient l'autre et la plus courte a au moins 5 caractères (§8.4)."""
    if ref_egales(x, y):
        return True
    # Inclusion sur la forme §5.2 (``norm_ref``), telle que l'écrit §8.4 : « 0001-0 » est une troncature de
    # « FAC/2026/0001-0 » (D-805) ; puis sur la forme sans zéros de tête des segments numériques.
    n1, n2 = norm_ref(x), norm_ref(y)
    if n1 and n2:
        court, long_ = (n1, n2) if len(n1) <= len(n2) else (n2, n1)
        if len(court) >= LONGUEUR_MIN_CONTAINMENT and court in long_:
            return True
    a, b = norm_ref_containment(x), norm_ref_containment(y)
    if not a or not b:
        return False
    if a == b:
        return True
    court, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(court) >= LONGUEUR_MIN_CONTAINMENT and court in long_


# --- MRN --------------------------------------------------------------------------------------------

_MRN_RE = re.compile(r"^\d{2}[A-Z]{2}[A-Z0-9]{14}$")


def est_mrn(x: str | None) -> bool:
    """18 caractères alphanumériques, l'année (2 chiffres) puis le code pays (§5.3.2)."""
    return bool(_MRN_RE.match(norm_ref(x)))


def mrn_prefixe(x: str | None) -> str:
    """15 premiers caractères normalisés (« préfixe stable » entre versions rectificatives)."""
    return norm_ref(x)[:15]


def norm_alnum(x: str | None) -> str:
    """Majuscules, seulement ``A-Z`` et ``0-9`` (accents **non** retirés : « É » disparaît). Forme brute des
    extracteurs pour rapprocher deux lectures d'une même référence ; ``norm_ref`` retire aussi les accents."""
    return _NON_ALNUM.sub("", (x or "").upper())


#: Classes de confusion OCR (caractères souvent pris l'un pour l'autre) : 0/O/Q/D, 1/I/L, 4/A, 5/S, 8/B, 2/Z, 6/G.
CONFUSION_OCR = str.maketrans({"0": "O", "Q": "O", "D": "O", "1": "I", "L": "I", "4": "A", "5": "S", "8": "B",
                               "2": "Z", "6": "G"})


def cle_confusion_ocr(x: str | None) -> str:
    """Forme ``norm_ref`` où chaque caractère est remplacé par le représentant de sa classe de confusion OCR :
    deux lectures d'une même référence qui ne diffèrent que par ces confusions ont la même clé."""
    return norm_ref(x).translate(CONFUSION_OCR)


def mrn_egaux(x: str | None, y: str | None) -> bool:
    """Comparaison des MRN sur le préfixe stable (§8.4)."""
    a, b = mrn_prefixe(x), mrn_prefixe(y)
    return len(a) == 15 and a == b


# --- Références de transport ---------------------------------------------------------------------------

_LIBELLES_TRANSPORT = re.compile(
    r"^\s*(?:(?:M|H)?AWB|(?:M|H)?LTA|B\s*/\s*L|BL|BOL|CMR|HBL|MBL|N[°ºO]\.?)\s*(?:N[°ºO]\.?)?\s*[:#.\-]?\s+",
    re.IGNORECASE,
)


def norm_ref_transport(x: str | None) -> str:
    """Référence de transport comparable : libellé de tête retiré (``AWB``, ``LTA``, ``B/L``…),
    puis espaces, tirets, barres et toute ponctuation supprimés (§8.4).

    ``"999-11112222"``, ``"999 1111 2222"`` et ``"99911112222"`` sont égaux.
    """
    if not x:
        return ""
    t = x
    for _ in range(2):
        t = _LIBELLES_TRANSPORT.sub("", t)
    return norm_ref(t)


def ref_transport_egales(x: str | None, y: str | None) -> bool:
    a, b = norm_ref_transport(x), norm_ref_transport(y)
    return bool(a) and a == b


def ref_transport_compatibles(x: str | None, y: str | None) -> bool:
    """Égales, ou inclusion avec au moins 5 caractères (référence maison tronquée, préfixe compagnie)."""
    a, b = norm_ref_transport(x), norm_ref_transport(y)
    if not a or not b:
        return False
    if a == b:
        return True
    court, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(court) >= LONGUEUR_MIN_CONTAINMENT and court in long_
