"""Références : normalisation et comparaison (SPEC §5.2 « Références », §8.4)."""

from __future__ import annotations

import re

__all__ = [
    "LONGUEUR_MIN_CONTAINMENT",
    "distance_bornee",
    "est_mrn",
    "mrn_egaux",
    "mrn_prefixe",
    "mrn_proches",
    "norm_ref",
    "norm_ref_containment",
    "norm_ref_transport",
    "ref_compatibles",
    "ref_egales",
    "ref_transport_compatibles",
    "ref_transport_egales",
    "ref_transport_proches",
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
CONFUSION_OCR = str.maketrans(
    {"0": "O", "Q": "O", "D": "O", "1": "I", "L": "I", "4": "A", "5": "S", "8": "B", "2": "Z", "6": "G"}
)


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


# --- Références lues imparfaitement (regroupement, D-3702) ----------------------------------------------


def distance_bornee(a: str, b: str, borne: int) -> int:
    """Distance d'édition (substitution, insertion, suppression) de ``a`` à ``b``, plafonnée à ``borne + 1``."""
    if abs(len(a) - len(b)) > borne:
        return borne + 1
    prec = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cour = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cour[j] = min(prec[j] + 1, cour[j - 1] + 1, prec[j - 1] + (ca != cb))
        if min(cour) > borne:
            return borne + 1
        prec = cour
    return min(prec[-1], borne + 1)


#: Écart toléré entre deux lectures d'un même MRN (préfixe de 15 caractères, après classes de confusion OCR).
MRN_DIFFERENCES_PROCHES = 4


def mrn_proches(x: str | None, y: str | None) -> bool:
    """Deux lectures d'un même MRN (préfixe stable) malgré l'OCR : clés de confusion (``cle_confusion_ocr``) d'au
    moins 12 caractères, même année (deux premiers chiffres, sous confusion) et au plus
    ``MRN_DIFFERENCES_PROCHES`` caractères d'écart. Onze caractères aléatoires parmi 36 : deux MRN distincts
    n'en partagent pas sept par hasard (D-3104)."""
    a, b = cle_confusion_ocr(mrn_prefixe(x)), cle_confusion_ocr(mrn_prefixe(y))
    if len(a) < 12 or len(b) < 12 or a[:2] != b[:2]:
        return False
    return distance_bornee(a, b, MRN_DIFFERENCES_PROCHES) <= MRN_DIFFERENCES_PROCHES


def ref_compatibles_ocr(x: str | None, y: str | None) -> bool:
    """``ref_compatibles`` sur les clés de confusion OCR (D-4207) : égales, ou la plus courte (au moins
    5 caractères, dont un chiffre) contenue dans l'autre. Deux lectures d'une même référence de facture qui ne
    diffèrent que par des caractères souvent confondus (« 0MS » / « OMS », « G1 » / « GI »)."""
    if ref_compatibles(x, y):
        return True
    a, b = cle_confusion_ocr(x), cle_confusion_ocr(y)
    if not a or not b:
        return False
    if a == b:
        return True
    court, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return (
        len(court) >= LONGUEUR_MIN_CONTAINMENT
        and any(c.isdigit() for c in norm_ref(x) + norm_ref(y))
        and court in long_
    )


def ref_facture_proches(x: str | None, y: str | None) -> bool:
    """Deux lectures **OCR** possibles d'une même référence de facture (D-4207) : clés de confusion d'au moins 8
    caractères à au plus ``max(1, n // 6)`` caractères d'écart (``n`` : longueur la plus courte ; 2 pour 12
    caractères). À n'employer que si l'une des deux valeurs est lue par OCR."""
    a, b = cle_confusion_ocr(x), cle_confusion_ocr(y)
    n = min(len(a), len(b))
    if n < 8:
        return False
    borne = max(1, n // 6)
    return distance_bornee(a, b, borne) <= borne


def ref_transport_proches(x: str | None, y: str | None) -> bool:
    """Deux lectures d'une même référence de transport : compatibles (``ref_transport_compatibles``), ou clés de
    confusion OCR d'au moins 10 caractères à au plus ``max(1, n // 4)`` caractères d'écart (``n`` : longueur
    la plus courte ; 3 pour une référence de 13 caractères)."""
    if ref_transport_compatibles(x, y):
        return True
    a = norm_ref_transport(x).translate(CONFUSION_OCR)
    b = norm_ref_transport(y).translate(CONFUSION_OCR)
    n = min(len(a), len(b))
    if n < 10:
        return False
    borne = max(1, n // 4)
    return distance_bornee(a, b, borne) <= borne
