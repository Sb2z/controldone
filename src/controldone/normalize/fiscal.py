"""Identifiants fiscaux : TVA intracommunautaire, SIREN, SIRET, EORI (SPEC §5.2, §19.1)."""

from __future__ import annotations

import re

__all__ = [
    "cle_tva_fr",
    "extraire_siren",
    "normalize_eori",
    "normalize_vat",
    "siren_depuis_siret",
    "siren_depuis_tva",
    "siren_luhn_valide",
    "tva_fr_depuis_siren",
    "tva_fr_valide",
]

_VAT_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{2,13}$")


def normalize_vat(x: str | None) -> str | None:
    """Majuscules, sans espace ni ponctuation : ``"fr 32 000 123 459"`` -> ``"FR32000123459"``.

    ``EL`` (Grèce) est conservé tel quel. ``None`` si la forme n'est pas celle d'un numéro de TVA.
    """
    if not x:
        return None
    t = re.sub(r"[^A-Za-z0-9]", "", x).upper()
    t = re.sub(r"^(?:TVA|VAT|IVA|USTIDNR|NIF)", "", t)
    if not _VAT_RE.match(t) or sum(c.isdigit() for c in t[2:]) < 2:
        return None
    return t


def cle_tva_fr(siren: str) -> str:
    """Clé numérique de la TVA française : ``(12 + 3 × (SIREN mod 97)) mod 97`` sur 2 chiffres."""
    return f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"


def tva_fr_depuis_siren(siren: str) -> str:
    return f"FR{cle_tva_fr(siren)}{siren}"


def tva_fr_valide(tva: str | None) -> bool | None:
    """Vrai/faux pour une TVA FR à clé numérique ; ``None`` si non vérifiable (clé alphabétique, autre pays)."""
    t = normalize_vat(tva)
    if not t or not t.startswith("FR") or len(t) != 13 or not t[4:].isdigit():
        return None
    cle = t[2:4]
    if not cle.isdigit():
        return None
    return cle == cle_tva_fr(t[4:])


def siren_depuis_tva(tva: str | None) -> str | None:
    """SIREN (9 chiffres) d'une TVA française ``FR`` + clé (2) + SIREN, même si la clé est abîmée."""
    t = normalize_vat(tva) if tva else None
    if t and t.startswith("FR") and len(t) == 13 and t[4:].isdigit():
        return t[4:]
    return None


def siren_depuis_siret(siret: str | None) -> str | None:
    chiffres = re.sub(r"\D", "", siret or "")
    return chiffres[:9] if len(chiffres) == 14 else None


def siren_luhn_valide(siren: str | None) -> bool:
    """Contrôle de Luhn d'un SIREN (9 chiffres)."""
    if not siren or not re.fullmatch(r"\d{9}", siren):
        return False
    total = 0
    for i, c in enumerate(reversed(siren)):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def extraire_siren(texte: str | None) -> str | None:
    """SIREN depuis une TVA FR, un SIRET (14 chiffres) ou un SIREN (9 chiffres, espaces admis)."""
    if not texte:
        return None
    s = siren_depuis_tva(texte)
    if s:
        return s
    chiffres = re.sub(r"[\s.\-]", "", texte)
    m = re.search(r"(?<!\d)(\d{14}|\d{9})(?!\d)", chiffres)
    if not m:
        return None
    return m.group(1)[:9]


def normalize_eori(x: str | None) -> str | None:
    """EORI : majuscules, sans espace ni ponctuation (2 lettres pays + jusqu'à 15 caractères)."""
    if not x:
        return None
    t = re.sub(r"[^A-Za-z0-9]", "", x).upper()
    return t if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{1,15}", t) else None
