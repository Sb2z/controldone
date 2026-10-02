"""Devises ISO 4217 et symboles (SPEC §5.2, §7.4).

Règle du ``$`` (§7.4) : un symbole ambigu ne devient un code ISO que si le pays du vendeur ou un code
ISO présent sur la page le confirme ; sinon la devise est ``inconnue`` (``DEVISE_INCONNUE``).
Même règle pour ``¥`` (JPY ou CNY) et ``kr`` (SEK, NOK, DKK, ISK).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from controldone.normalize.text import cle_texte

__all__ = [
    "DEVISES_SANS_DECIMALES",
    "DEVISE_INCONNUE",
    "ISO_4217",
    "codes_iso_dans_texte",
    "exposant_devise",
    "normalize_currency",
]

DEVISE_INCONNUE = "inconnue"

ISO_4217: frozenset[str] = frozenset(
    """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD
    CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD
    GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT
    LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR
    NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP
    STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF
    XPF YER ZAR ZMW ZWL
    """.split()
)

#: Devises à 0 décimale (ISO 4217, exposant 0).
DEVISES_SANS_DECIMALES: frozenset[str] = frozenset(
    "BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX VND VUV XAF XOF XPF".split()
)
#: Devises à 3 décimales.
_DEVISES_3_DECIMALES = frozenset("BHD IQD JOD KWD LYD OMR TND".split())


def exposant_devise(devise: str | None) -> int:
    """Nombre de décimales de la devise (2 par défaut)."""
    if devise in DEVISES_SANS_DECIMALES:
        return 0
    if devise in _DEVISES_3_DECIMALES:
        return 3
    return 2


# Symboles non ambigus (préfixés compris) -> code
_SYMBOLES_SURS: dict[str, str] = {
    "€": "EUR",
    "£": "GBP",
    "₩": "KRW",
    "₹": "INR",
    "₺": "TRY",
    "₽": "RUB",
    "₫": "VND",
    "₱": "PHP",
    "₪": "ILS",
    "฿": "THB",
    "zł": "PLN",
    "us$": "USD",
    "u$s": "USD",
    "usd$": "USD",
    "hk$": "HKD",
    "c$": "CAD",
    "ca$": "CAD",
    "can$": "CAD",
    "a$": "AUD",
    "au$": "AUD",
    "s$": "SGD",
    "nz$": "NZD",
    "r$": "BRL",
    "mx$": "MXN",
    "nt$": "TWD",
    "rmb": "CNY",
    "cn¥": "CNY",
    "jp¥": "JPY",
    "sfr": "CHF",
}

# Mots -> code (clé sans accents, minuscules)
_MOTS: dict[str, str] = {
    "euro": "EUR",
    "euros": "EUR",
    "dollar us": "USD",
    "dollars us": "USD",
    "dollar americain": "USD",
    "dollars americains": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "dolar estadounidense": "USD",
    "dolares estadounidenses": "USD",
    "livre sterling": "GBP",
    "livres sterling": "GBP",
    "pound sterling": "GBP",
    "yen": "JPY",
    "yens": "JPY",
    "yuan": "CNY",
    "renminbi": "CNY",
    "won": "KRW",
    "franc suisse": "CHF",
    "francs suisses": "CHF",
    "swiss franc": "CHF",
    "swiss francs": "CHF",
}

# Symboles ambigus -> devises candidates ; pays -> devise pour lever l'ambiguïté
_AMBIGUS: dict[str, frozenset[str]] = {
    "$": frozenset({"USD", "CAD", "AUD", "HKD", "SGD", "NZD", "MXN", "TWD", "ARS", "CLP", "COP"}),
    "¥": frozenset({"JPY", "CNY"}),
    "kr": frozenset({"SEK", "NOK", "DKK", "ISK"}),
    "kr.": frozenset({"SEK", "NOK", "DKK", "ISK"}),
    "fr": frozenset({"CHF"}),  # « Fr. » : franc suisse en pratique, à confirmer par le pays
    "fr.": frozenset({"CHF"}),
}
_DEVISE_DU_PAYS: dict[str, str] = {
    "US": "USD", "CA": "CAD", "AU": "AUD", "HK": "HKD", "SG": "SGD", "NZ": "NZD", "MX": "MXN",
    "TW": "TWD", "AR": "ARS", "CL": "CLP", "CO": "COP", "JP": "JPY", "CN": "CNY", "SE": "SEK",
    "NO": "NOK", "DK": "DKK", "IS": "ISK", "CH": "CHF", "LI": "CHF", "EC": "USD", "SV": "USD",
    "PA": "USD", "PR": "USD",
}

_CODE_RE = re.compile(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])")


def codes_iso_dans_texte(texte: str) -> set[str]:
    """Codes ISO 4217 présents en majuscules dans un texte (page), pour lever l'ambiguïté du ``$``."""
    return {c for c in _CODE_RE.findall(texte or "") if c in ISO_4217}


def normalize_currency(
    texte: str | None,
    *,
    pays_vendeur: str | None = None,
    codes_iso_page: Iterable[str] = (),
) -> str | None:
    """Code ISO 4217 d'une devise lue, ``DEVISE_INCONNUE`` si ambigu non confirmé, ``None`` si rien lu.

    >>> normalize_currency("USD 12,540.00")
    'USD'
    >>> normalize_currency("$")
    'inconnue'
    >>> normalize_currency("$", pays_vendeur="US")
    'USD'
    """
    if texte is None:
        return None
    brut = texte.strip()
    if not brut:
        return None
    codes = [c for c in _CODE_RE.findall(brut.upper()) if c in ISO_4217]
    # Un code ISO explicite l'emporte (« USD », « 12 540,00 EUR »). Plusieurs codes différents : ambigu.
    if codes and _CODE_RE.findall(brut):
        distincts = sorted(set(c for c in _CODE_RE.findall(brut) if c in ISO_4217))
        if len(distincts) == 1:
            return distincts[0]
        if len(distincts) > 1:
            return DEVISE_INCONNUE
    cle = cle_texte(brut)
    cle_sans_nombres = re.sub(r"[\d.,'\s\-+()]+", " ", cle).strip()
    if cle_sans_nombres.upper() in ISO_4217 and len(cle_sans_nombres) == 3:
        return cle_sans_nombres.upper()
    for mot, code in sorted(_MOTS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z]){re.escape(mot)}(?![a-z])", cle):
            return code
    for sym, code in sorted(_SYMBOLES_SURS.items(), key=lambda kv: -len(kv[0])):
        if sym in cle or sym in brut:
            return code
    for sym, candidats in sorted(_AMBIGUS.items(), key=lambda kv: -len(kv[0])):
        trouve = sym in brut if not sym.isalpha() and not sym.endswith(".") else bool(
            re.search(rf"(?<![a-z]){re.escape(sym)}(?![a-z])", cle)
        )
        if trouve:
            return _lever_ambiguite(candidats, pays_vendeur, codes_iso_page)
    reste = re.sub(r"[\d.,'\s\-+()%:]+", "", brut)
    return DEVISE_INCONNUE if re.fullmatch(r"[A-Za-z]{3}", reste) else None


def _lever_ambiguite(candidats: frozenset[str], pays_vendeur: str | None, codes_iso_page: Iterable[str]) -> str:
    sur_page = {c for c in codes_iso_page if c in candidats}
    if len(sur_page) == 1:
        return next(iter(sur_page))
    if len(sur_page) > 1:
        return DEVISE_INCONNUE
    if pays_vendeur:
        code = _DEVISE_DU_PAYS.get(pays_vendeur.upper())
        if code in candidats:
            return code
    return DEVISE_INCONNUE
