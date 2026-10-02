"""Outils communs : décimaux, aléa déterministe, identifiants fictifs, formats de nombres."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import string
from decimal import ROUND_HALF_UP, Decimal

D0 = Decimal("0")
CENT = Decimal("0.01")
ZERO_DEC_CURRENCIES = {"JPY", "KRW"}


# ---------------------------------------------------------------------------
# Décimaux
# ---------------------------------------------------------------------------

def D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(str(x))


def q2(x) -> Decimal:
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def q0(x) -> Decimal:
    return D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def q3(x) -> Decimal:
    return D(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q5(x) -> Decimal:
    return D(x).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


def qcur(x, currency: str) -> Decimal:
    return q0(x) if currency in ZERO_DEC_CURRENCIES else q2(x)


def cur_decimals(currency: str) -> int:
    return 0 if currency in ZERO_DEC_CURRENCIES else 2


def s2(x) -> str:
    """Chaîne décimale à 2 décimales (contrat truth.json)."""
    return str(q2(x))


def sdec(x, currency: str | None = None) -> str:
    if currency is not None and currency in ZERO_DEC_CURRENCIES:
        return str(q0(x))
    return str(q2(x))


# ---------------------------------------------------------------------------
# Aléa déterministe
# ---------------------------------------------------------------------------

def sub_seed(*parts) -> int:
    h = hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:16], 16)


def rng_for(*parts) -> random.Random:
    return random.Random(sub_seed(*parts))


def split_of(dossier_id: str) -> str:
    return "holdout" if int(hashlib.sha256(dossier_id.encode()).hexdigest()[0:8], 16) % 5 == 0 else "dev"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Identifiants fictifs (SPEC §19.1)
# ---------------------------------------------------------------------------

def luhn_ok(num: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def make_siren(rng: random.Random) -> str:
    """SIREN fictif : commence par 000, valide au sens de Luhn."""
    body = "000" + "".join(rng.choice(string.digits) for _ in range(5))
    for c in string.digits:
        if luhn_ok(body + c):
            return body + c
    raise AssertionError


def vat_fr(siren: str) -> str:
    key = (12 + 3 * (int(siren) % 97)) % 97
    return f"FR{key:02d}{siren}"


def eori_fr(siren: str) -> str:
    return f"FR{siren}00000"


ALNUM = string.ascii_uppercase + string.digits


def make_mrn(rng: random.Random, year: int) -> str:
    return f"{year % 100:02d}FR" + "".join(rng.choice(ALNUM) for _ in range(14))


def make_lrn(rng: random.Random) -> str:
    return "LRN-" + "".join(rng.choice(string.digits) for _ in range(7))


def awb_check(serial7: str) -> str:
    return str(int(serial7) % 7)


def make_awb(rng: random.Random) -> str:
    """LTA fictive : préfixe 999 (non attribué) + 7 chiffres + clé modulo 7."""
    s = "".join(rng.choice(string.digits) for _ in range(7))
    return f"999-{s}{awb_check(s)}"


def make_bl(rng: random.Random) -> str:
    return "DEMO" + "".join(rng.choice(string.digits) for _ in range(9))


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def d_iso(d: dt.date) -> str:
    return d.isoformat()


def d_fr(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def d_en(d: dt.date) -> str:
    return d.strftime("%b %d, %Y")


def d_dot(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]


def d_es(d: dt.date) -> str:
    return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"


def d_long_fr(d: dt.date) -> str:
    return f"{d.day} {MONTHS_FR[d.month - 1]} {d.year}"


# ---------------------------------------------------------------------------
# Formats de nombres (SPEC §5.2)
# ---------------------------------------------------------------------------

NBSP = " "
NNBSP = " "


def _group(int_part: str, sep: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return sep.join(out)


def fmt_num(value, style: str = "fr", decimals: int = 2, neg: str = "minus") -> str:
    """Formate un décimal.

    styles : fr (1 234,56 espace insécable), frn (espace fine), frs (espace simple),
    de (1.234,56), en (1,234.56), ch (1'234.56), raw (1234.56), rawc (1234,56).
    neg : minus (-1,00), paren ((1,00)), suffix (1,00-).
    """
    v = D(value)
    q = Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)
    v = v.quantize(q, rounding=ROUND_HALF_UP)
    negative = v < 0
    v = abs(v)
    s = f"{v:.{decimals}f}"
    if "." in s:
        ip, fp = s.split(".")
    else:
        ip, fp = s, ""
    seps = {"fr": (NBSP, ","), "frn": (NNBSP, ","), "frs": (" ", ","), "de": (".", ","),
            "en": (",", "."), "ch": ("'", "."), "raw": ("", "."), "rawc": ("", ",")}
    gs, ds = seps[style]
    ip = _group(ip, gs) if gs else ip
    out = ip + (ds + fp if fp else "")
    if negative:
        if neg == "paren":
            out = f"({out})"
        elif neg == "suffix":
            out = out + "-"
        else:
            out = "-" + out
    return out


def fmt_rate(value, style: str) -> str:
    return fmt_num(value, style, 5)


def fmt_kg(value, style: str = "fr", decimals: int = 3) -> str:
    return fmt_num(value, style, decimals)


def fmt_qty(value, style: str = "fr") -> str:
    v = D(value)
    if v == v.to_integral_value():
        return fmt_num(v, style, 0)
    return fmt_num(v, style, 3)


def pct_str(value, style: str = "fr") -> str:
    v = D(value).normalize()
    s = format(v, "f")
    if style in ("fr", "frn", "frs", "de", "rawc"):
        s = s.replace(".", ",")
    return s


# ---------------------------------------------------------------------------
# Test de confusion de lecture (SPEC §8.5.4) — utilisé pour fixer expected_level
# ---------------------------------------------------------------------------

CONF_CLASSES = [set("0689"), set("358"), set("147")]


def is_confusion_variant(a: str, b: str) -> bool:
    """Vrai si b se déduit de a par UNE substitution de chiffre de même classe de confusion,
    ou par perte/ajout d'un zéro final, ou par un facteur 100/1000 (séparateur décimal)."""
    da = "".join(ch for ch in a if ch.isdigit())
    db = "".join(ch for ch in b if ch.isdigit())
    if len(da) == len(db):
        diffs = [(x, y) for x, y in zip(da, db) if x != y]
        if len(diffs) == 1:
            x, y = diffs[0]
            if any(x in c and y in c for c in CONF_CLASSES):
                return True
    if da + "0" == db or db + "0" == da:
        return True
    try:
        fa, fb = D(a), D(b)
        if fa and fb:
            r = fb / fa
            if r in (Decimal(100), Decimal(1000), Decimal("0.01"), Decimal("0.001")):
                return True
    except Exception:
        pass
    return False


def transpose_digits(value: Decimal, rng: random.Random, currency: str = "EUR") -> Decimal:
    """Permute deux chiffres adjacents distincts de la partie entière (erreur de saisie)."""
    dec = cur_decimals(currency)
    s = f"{abs(value):.{dec}f}"
    ip = s.split(".")[0]
    cands = [i for i in range(len(ip) - 1) if ip[i] != ip[i + 1] and not (i == 0 and ip[1] == "0")]
    if not cands:
        return value + (Decimal(10) if dec == 0 else Decimal("10.00"))
    # privilégie les positions de poids fort pour que l'écart dépasse les tolérances
    cands.sort()
    i = cands[min(len(cands) - 1, rng.randrange(0, max(1, min(2, len(cands)))))]
    lst = list(ip)
    lst[i], lst[i + 1] = lst[i + 1], lst[i]
    rest = s[len(ip):]
    return D("".join(lst) + rest)
