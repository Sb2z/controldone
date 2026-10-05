"""Utilitaires du générateur n° 2 : décimaux, aléa déterministe, identifiants fictifs, formats.

Tout est déterministe : aucune horloge, aucun ordre de hachage Python (les ensembles sont triés).
"""

from __future__ import annotations

import hashlib
import random
import string
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

GENERATOR_VERSION = "2.0.1"
FICTIF = "DONNÉES FICTIVES"

D = Decimal
ZERO = Decimal("0")
CENT = Decimal("0.01")

DEVISES_SANS_DECIMALES = ("JPY", "KRW")


def q2(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def q0(x) -> Decimal:
    return Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def qcur(x, devise: str) -> Decimal:
    return q0(x) if devise in DEVISES_SANS_DECIMALES else q2(x)


def q3(x) -> Decimal:
    return Decimal(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q5(x) -> Decimal:
    return Decimal(x).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


def s2(x) -> str:
    """Chaîne décimale du contrat truth.json (point, 2 décimales)."""
    return str(q2(x))


def sdec(x) -> str:
    """Chaîne décimale sans exposant (masses, quantités, taux)."""
    d = Decimal(x)
    s = format(d, "f")
    return s


def rng_for(seed: int, *parts) -> random.Random:
    h = hashlib.sha256(("|".join([str(seed)] + [str(p) for p in parts])).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def split_of(dossier_id: str) -> str:
    return "holdout" if int(hashlib.sha256(dossier_id.encode()).hexdigest()[0:8], 16) % 5 == 0 else "dev"


# ---------------------------------------------------------------------------
# Identifiants fictifs (§19.1)
# ---------------------------------------------------------------------------

def luhn_ok(num: str) -> bool:
    tot = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        tot += d
    return tot % 10 == 0


def siren_fictif(rng: random.Random, used: set | None = None) -> str:
    while True:
        base = "000" + "".join(rng.choice(string.digits) for _ in range(5))
        for c in string.digits:
            s = base + c
            if luhn_ok(s):
                break
        if used is None or s not in used:
            if used is not None:
                used.add(s)
            return s


def tva_fr(siren: str) -> str:
    cle = (12 + 3 * (int(siren) % 97)) % 97
    return f"FR{cle:02d}{siren}"


def eori_fr(siren: str) -> str:
    return f"FR{siren}00000"


def mrn_fictif(rng: random.Random, annee: int) -> str:
    alnum = string.ascii_uppercase + string.digits
    return f"{annee % 100:02d}FR" + "".join(rng.choice(alnum) for _ in range(14))


def mrn_version(mrn: str, rng: random.Random) -> str:
    """Même préfixe stable (15 caractères), suffixe différent : version rectifiée."""
    alnum = string.ascii_uppercase + string.digits
    while True:
        suf = "".join(rng.choice(alnum) for _ in range(3))
        if suf != mrn[15:]:
            return mrn[:15] + suf


def awb_fictif(rng: random.Random) -> str:
    """LTA : préfixe compagnie 3 chiffres (999 = fictif) + 7 chiffres + clé modulo 7."""
    serie = rng.randint(1000000, 9999999)
    return f"999-{serie}{serie % 7}"


def bl_fictif(rng: random.Random) -> str:
    return "FICU" + "".join(rng.choice(string.digits) for _ in range(9))


def cmr_fictif(rng: random.Random) -> str:
    return "CMR-FX-" + "".join(rng.choice(string.digits) for _ in range(6))


def lrn_fictif(rng: random.Random) -> str:
    return "LRN" + "".join(rng.choice(string.digits) for _ in range(9))


# ---------------------------------------------------------------------------
# Formats numériques et dates
# ---------------------------------------------------------------------------

NBSP = " "
NNBSP = " "


def _group(intpart: str, sep: str) -> str:
    out = []
    while len(intpart) > 3:
        out.insert(0, intpart[-3:])
        intpart = intpart[:-3]
    out.insert(0, intpart)
    return sep.join(out)


def fmt_num(value, style: str = "fr", decimals: int = 2) -> str:
    """Formate un décimal selon un style :
    fr  : 1 234,56 (espace fine insécable)    frs : 1 234,56 (espace simple)
    en  : 1,234.56     de : 1.234,56     ch : 1'234.56
    plain : 1234.56    plainc : 1234,56
    """
    v = Decimal(value)
    neg = v < 0
    v = abs(v)
    q = Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)
    v = v.quantize(q, rounding=ROUND_HALF_UP)
    s = format(v, "f")
    if "." in s:
        ip, fp = s.split(".")
    else:
        ip, fp = s, ""
    seps = {"fr": (NNBSP, ","), "frs": (" ", ","), "frn": (NBSP, ","), "en": (",", "."),
            "de": (".", ","), "ch": ("'", "."), "plain": ("", "."), "plainc": ("", ",")}
    gs, ds = seps[style]
    ip = _group(ip, gs) if gs else ip
    out = ip + (ds + fp if decimals > 0 else "")
    return ("-" if neg else "") + out


def cur_decimals(devise: str) -> int:
    return 0 if devise in DEVISES_SANS_DECIMALES else 2


MOIS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
           "octobre", "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
           "Oktober", "November", "Dezember"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
           "settembre", "ottobre", "novembre", "dicembre"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
    "nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september",
           "oktober", "november", "december"],
}


def fmt_date(d: date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "dmy/":
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    if style == "dmy.":
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    if style == "dmy-":
        return f"{d.day:02d}-{d.month:02d}-{d.year}"
    if style == "mdy/":
        return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if style == "ymd/":
        return f"{d.year}/{d.month:02d}/{d.day:02d}"
    if style == "en_long":
        return f"{d.day} {MOIS['en'][d.month - 1][:3]} {d.year}"
    if style == "us_long":
        return f"{MOIS['en'][d.month - 1]} {d.day}, {d.year}"
    for lang in ("fr", "de", "it", "es", "nl"):
        if style == f"{lang}_long":
            if lang == "de":
                return f"{d.day}. {MOIS['de'][d.month - 1]} {d.year}"
            if lang == "es":
                return f"{d.day} de {MOIS['es'][d.month - 1]} de {d.year}"
            return f"{d.day} {MOIS[lang][d.month - 1]} {d.year}"
    raise ValueError(style)


DATE_STYLES = ["iso", "dmy/", "dmy.", "dmy-", "mdy/", "ymd/", "en_long", "us_long", "fr_long",
               "de_long", "it_long", "es_long", "nl_long"]


def date_candidates(d: date) -> list[str]:
    return [fmt_date(d, s) for s in DATE_STYLES]


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def fmt_hs(code10: str, digits: int, style: str) -> str:
    """Forme imprimée d'un code marchandise : 6, 8 ou 10 chiffres, ponctuation variable."""
    c = code10[:digits]
    if style == "dots":
        parts = [c[:4], c[4:6]] + ([c[6:8]] if digits >= 8 else []) + ([c[8:10]] if digits == 10 else [])
        return ".".join(p for p in parts if p)
    if style == "space":
        parts = [c[:4], c[4:6]] + ([c[6:8]] if digits >= 8 else []) + ([c[8:10]] if digits == 10 else [])
        return " ".join(p for p in parts if p)
    if style == "dot4":
        return c[:4] + "." + c[4:]
    return c
