"""Formatage d'affichage commun aux rendus."""

from __future__ import annotations

from decimal import Decimal as D

from .util import cur_decimals, fmt_date, fmt_hs, fmt_num

COUNTRY = {
    "CN": {"en": "China", "fr": "Chine", "de": "China", "it": "Cina", "nl": "China", "es": "China"},
    "JP": {"en": "Japan", "fr": "Japon", "de": "Japan", "it": "Giappone", "nl": "Japan", "es": "Japón"},
    "KR": {"en": "Korea", "fr": "Corée", "de": "Korea", "it": "Corea", "nl": "Korea", "es": "Corea"},
    "IN": {"en": "India", "fr": "Inde", "de": "Indien", "it": "India", "nl": "India", "es": "India"},
    "TR": {"en": "Turkey", "fr": "Turquie", "de": "Türkei", "it": "Turchia", "nl": "Turkije", "es": "Turquía"},
    "GB": {"en": "United Kingdom", "fr": "Royaume-Uni", "de": "Vereinigtes Königreich", "it": "Regno Unito", "nl": "Verenigd Koninkrijk", "es": "Reino Unido"},
    "CH": {"en": "Switzerland", "fr": "Suisse", "de": "Schweiz", "it": "Svizzera", "nl": "Zwitserland", "es": "Suiza"},
    "AW": {"en": "Aruba", "fr": "Aruba", "de": "Aruba", "it": "Aruba", "nl": "Aruba", "es": "Aruba"},
    "MX": {"en": "Mexico", "fr": "Mexique", "de": "Mexiko", "it": "Messico", "nl": "Mexico", "es": "México"},
    "US": {"en": "United States", "fr": "États-Unis", "de": "USA", "it": "Stati Uniti", "nl": "Verenigde Staten", "es": "Estados Unidos"},
    "VN": {"en": "Viet Nam", "fr": "Viêt Nam", "de": "Vietnam", "it": "Vietnam", "nl": "Vietnam", "es": "Vietnam"},
    "TW": {"en": "Taiwan", "fr": "Taïwan", "de": "Taiwan", "it": "Taiwan", "nl": "Taiwan", "es": "Taiwán"},
    "TH": {"en": "Thailand", "fr": "Thaïlande", "de": "Thailand", "it": "Tailandia", "nl": "Thailand", "es": "Tailandia"},
    "MY": {"en": "Malaysia", "fr": "Malaisie", "de": "Malaysia", "it": "Malesia", "nl": "Maleisië", "es": "Malasia"},
    "ID": {"en": "Indonesia", "fr": "Indonésie", "de": "Indonesien", "it": "Indonesia", "nl": "Indonesië", "es": "Indonesia"},
    "BD": {"en": "Bangladesh", "fr": "Bangladesh", "de": "Bangladesch", "it": "Bangladesh", "nl": "Bangladesh", "es": "Bangladés"},
    "KH": {"en": "Cambodia", "fr": "Cambodge", "de": "Kambodscha", "it": "Cambogia", "nl": "Cambodja", "es": "Camboya"},
    "FR": {"en": "France", "fr": "France", "de": "Frankreich", "it": "Francia", "nl": "Frankrijk", "es": "Francia"},
}


def money(v, devise="EUR", style="fr"):
    return fmt_num(v, style, cur_decimals(devise))


def amt(v, style="fr", dec=2):
    return fmt_num(v, style, dec)


def pu(v, devise, style):
    v = D(v)
    dec = cur_decimals(devise)
    if dec and v != v.quantize(D("0.01")):
        dec = 4
    return fmt_num(v, style, dec)


def qty(v, style):
    v = D(v)
    if v == v.to_integral_value():
        return fmt_num(v, style, 0)
    s = format(v.normalize(), "f")
    dec = len(s.split(".")[1]) if "." in s else 0
    return fmt_num(v, style, min(3, dec))


def mass(v, style, dec=3):
    return fmt_num(v, style, dec)


def rate(v, style="fr"):
    v = D(v)
    s = format(v.normalize(), "f")
    dec = len(s.split(".")[1]) if "." in s else 0
    return fmt_num(v, style, max(1, min(3, dec)))


def hs(code10, digits, style):
    return fmt_hs(code10, digits, style) if digits else ""


def date(d, style):
    return fmt_date(d, style)


def country(code, lang, mode="code"):
    if mode == "code":
        return code
    name = COUNTRY.get(code, {}).get(lang, code)
    return f"{name} ({code})"


_ONES = ["", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE",
         "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
_TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]


def words(n: int) -> str:
    if n == 0:
        return "ZERO"
    out = []
    for val, name in ((10 ** 9, "BILLION"), (10 ** 6, "MILLION"), (1000, "THOUSAND"), (1, "")):
        if n >= val:
            chunk = n // val
            n %= val
            parts = []
            if chunk >= 100:
                parts.append(_ONES[chunk // 100] + " HUNDRED")
                chunk %= 100
            if chunk >= 20:
                parts.append(_TENS[chunk // 10] + ("-" + _ONES[chunk % 10] if chunk % 10 else ""))
            elif chunk:
                parts.append(_ONES[chunk])
            out.append(" ".join(parts) + (" " + name if name else ""))
    return " ".join(out).strip()


CUR_WORDS = {"USD": "US DOLLARS", "CNY": "CHINESE YUAN", "JPY": "JAPANESE YEN", "KRW": "KOREAN WON", "GBP": "POUNDS STERLING",
             "CHF": "SWISS FRANCS", "INR": "INDIAN RUPEES", "TRY": "TURKISH LIRA", "EUR": "EUROS"}
