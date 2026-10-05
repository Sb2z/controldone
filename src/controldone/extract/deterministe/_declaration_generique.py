"""Lectures génériques des déclarations imprimées sous une forme « texte » (SPEC §5.3.2, D-1801 à D-1806).

Aides **sans état** de l'extracteur ``declaration`` pour les présentations qui ne sont ni un formulaire à cases ni
un tableau à colonnes : récapitulatif en texte (corps d'un courriel, certificat d'un commissionnaire), où chaque
article est une ligne d'ancrage « [1] 8467210000 Perceuse… » suivie de couples « libellé valeur » séparés par
« | » et de lignes de taxation en prose (« A00 Droits de douane : base 357,52 EUR x 2,7 % = 10,00 EUR (payé
comptant) »). Les fonctions travaillent sur des suites de mots (objets portant ``t`` : texte du mot) et rendent
des **indices** de mots ; l'extracteur en fait des valeurs sourcées (ancrage, zone, confiance).

Libellés fr / en / de / it / es ; aucune chaîne propre à un gabarit, à un fichier ou à une société.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Any

from controldone.normalize.text import sans_accents

__all__ = ["ancre_article", "date_en_lettres", "date_prose_acceptation", "ligne_taxe_prose", "segments_libelles"]


def _cle(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sans_accents(s).lower())


# --- dates en toutes lettres -----------------------------------------------------------------------------------

_MOIS: dict[str, int] = {}
for _n, _noms in enumerate((
        ("janvier", "january", "januar", "jan", "gennaio", "gen", "enero", "ene", "janv"),
        ("fevrier", "february", "februar", "feb", "fev", "fevr", "febbraio", "febrero"),
        ("mars", "march", "marz", "mar", "marzo"),
        ("avril", "april", "apr", "avr", "aprile", "abril", "abr"),
        ("mai", "may", "maggio", "mag", "mayo"),
        ("juin", "june", "juni", "jun", "giugno", "giu", "junio"),
        ("juillet", "july", "juli", "jul", "juil", "luglio", "lug", "julio"),
        ("aout", "august", "aug", "agosto", "ago"),
        ("septembre", "september", "sep", "sept", "settembre", "set", "septiembre"),
        ("octobre", "october", "oktober", "oct", "okt", "ottobre", "ott", "octubre"),
        ("novembre", "november", "nov", "noviembre"),
        ("decembre", "december", "dezember", "dec", "dez", "dicembre", "dic", "diciembre"),
), start=1):
    for _m in _noms:
        _MOIS.setdefault(_m, _n)

#: « 18 août 2026 », « 11 Mar 2026 », « 1er juillet 2026 », « 7. September 2026 », « 3 de mayo de 2026 »
_DATE_LETTRES_RE = re.compile(
    r"(?<![\w])(\d{1,2})(?:er|st|nd|rd|th|\.|º)?\s+(?:de\s+)?([^\W\d_]{3,10})\.?\s+(?:de\s+)?(\d{4})(?!\d)")
#: « March 11, 2026 », « Mar 11 2026 »
_DATE_LETTRES_EN_RE = re.compile(r"(?<![\w])([^\W\d_]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")


def date_en_lettres(texte: str) -> tuple[int, int, str] | None:
    """Première date écrite avec le nom du mois : (début, fin, date ISO) ; ``None`` sinon."""
    cands: list[tuple[int, int, str]] = []
    for m in _DATE_LETTRES_RE.finditer(texte):
        mois = _MOIS.get(sans_accents(m.group(2)).lower())
        iso = _iso(int(m.group(3)), mois, int(m.group(1)))
        if iso:
            cands.append((m.start(), m.end(), iso))
            break
    for m in _DATE_LETTRES_EN_RE.finditer(texte):
        mois = _MOIS.get(sans_accents(m.group(1)).lower())
        iso = _iso(int(m.group(3)), mois, int(m.group(2)))
        if iso:
            cands.append((m.start(), m.end(), iso))
            break
    return min(cands) if cands else None


def _iso(annee: int, mois: int | None, jour: int) -> str | None:
    if mois is None or not 1990 <= annee <= 2100:
        return None
    try:
        return date(annee, mois, jour).isoformat()
    except ValueError:
        return None


#: Verbe ou nom d'acceptation / mainlevée suivi, dans la même phrase, de la date (fr / en / de / it / es).
_ACCEPTATION_RE = re.compile(
    r"accept\w*|mainlev\w*|releas\w*|cleared|clearance granted|freigegeben|angenommen|uberlassen\w*"
    r"|accettat\w*|svincolat\w*|aceptad\w*|levante|despachad\w*", re.I)


_DATE_NUM_RE = re.compile(r"(?<!\d)\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}(?!\d)|(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


def _dates(portee: str) -> list[tuple[int, int]]:
    out = [(m.start(), m.end()) for m in _DATE_NUM_RE.finditer(portee)]
    k = 0
    while k < len(portee):
        d = date_en_lettres(portee[k:])
        if d is None:
            break
        out.append((k + d[0], k + d[1]))
        k += d[1]
    return sorted(out)


def date_prose_acceptation(texte: str) -> tuple[int, int] | None:
    """Phrase « … acceptée par la douane le 18 août 2026 » / « released … on 11 Mar 2026 » / « … wurde am
    7. September 2026 angenommen » : position (début, fin) dans ``texte`` de la date de la phrase qui porte le
    premier mot d'acceptation, ou ``None``. Date numérique ou en lettres ; de préférence la première **après** le
    mot ; à défaut (verbe en fin de phrase), la seule date de la phrase **avant** le mot."""
    norm = sans_accents(texte)
    for m in _ACCEPTATION_RE.finditer(norm):
        reste = texte[m.end():]
        fin_phrase = re.search(r"(?<!\d)[.!?](?:\s|$)", reste)
        apres = _dates(reste[:fin_phrase.start() + 1] if fin_phrase else reste)
        if apres:
            return m.end() + apres[0][0], m.end() + apres[0][1]
        debut_phrase = max((x.end() for x in re.finditer(r"(?<!\d)[.!?]\s", texte[:m.start()])), default=0)
        avant = _dates(texte[debut_phrase:m.start()])
        if len(avant) == 1:
            return debut_phrase + avant[0][0], debut_phrase + avant[0][1]
    return None


# --- articles en liste -----------------------------------------------------------------------------------------

_NUMERO_RE = re.compile(r"^[\[(#]?(\d{1,3})[\]).:]?$")
_PREFIXES_ARTICLE = frozenset({"art", "article", "item", "pos", "position", "posizione", "partida", "artikel"})


def _est_code(toks: Sequence[Any], i: int) -> int:
    """Nombre de mots du code marchandise qui commence au mot ``i`` (0 si aucun) : 8 ou 10 chiffres, d'un bloc
    ou par groupes « 8467 21 00 00 »."""
    if i >= len(toks):
        return 0
    if re.fullmatch(r"\d{8}|\d{10}", toks[i].t.strip(".,:;")):
        return 1
    if re.fullmatch(r"\d{4}", toks[i].t):
        for n in (4, 3):
            txt = " ".join(t.t for t in toks[i:i + n])
            if len(toks[i:i + n]) == n and re.fullmatch(r"\d{4}(?: \d{2}){2,3}", txt.rstrip(".,:;")):
                return n
    return 0


def ancre_article(toks: Sequence[Any]) -> tuple[int, int, int] | None:
    """Ligne qui ouvre un article d'une liste : « [1] 8467210000 Désignation », « 1. 8467 21 00 00 … »,
    « Item 2 8203200000 … ». Rend (indice du numéro, début du code, fin du code) ; ``None`` sinon. Le numéro doit
    être entre crochets ou parenthèses, suivi d'un point, ou précédé d'un mot « article / item / pos »."""
    if not toks:
        return None
    i = 0
    prefixe = _cle(toks[0].t) in _PREFIXES_ARTICLE
    if prefixe:
        i = 1
    if i >= len(toks):
        return None
    t = toks[i].t
    m = _NUMERO_RE.match(t)
    if m is None or not (prefixe or t[0] == "#" or t[-1] in ".)]"):
        return None
    if (t[0] == "[") != (t[-1] == "]") or (t[0] == "(" and t[-1] != ")"):
        return None  # crochet ou parenthèse non refermé (débris d'OCR)
    n = _est_code(toks, i + 1)
    if n == 0:
        return None
    return i, i + 1, i + 1 + n


#: Libellés des couples « libellé valeur » d'un article (clé normalisée -> champ de l'article).
LIBELLES_ARTICLE: dict[str, str] = {}
for _champ, _libs in {
    "pays_origine": ("origine", "pays d'origine", "origin", "country of origin", "ursprung", "ursprungsland",
                     "origen", "pais de origen", "paese di origine"),
    "montant_facture_article": ("montant facturé", "montant", "invoiced amount", "invoice amount", "amount invoiced",
                                "rechnungsbetrag", "importo fatturato", "importe facturado", "valeur facturée"),
    "valeur_statistique": ("valeur statistique", "val. stat.", "statistical value", "statistischer wert",
                           "valore statistico", "valor estadístico"),
    "masse_nette": ("net", "masse nette", "poids net", "net mass", "net weight", "netto", "eigenmasse",
                    "massa netta", "peso netto", "masa neta", "peso neto"),
    "masse_brute": ("brut", "masse brute", "poids brut", "gross", "gross mass", "gross weight", "brutto", "rohmasse",
                    "massa lorda", "peso lordo", "masa bruta", "peso bruto"),
    "nombre_colis": ("colis", "packages", "pkgs", "packstücke", "colli", "bultos"),
    "quantite": ("quantité", "qté sup.", "unités supplémentaires", "quantity", "supplementary units", "menge",
                 "quantità", "cantidad"),
    "code_preference": ("préférence", "preference", "präferenz", "preferenza", "preferencia"),
    "regime": ("régime", "procedure", "procédure", "verfahren", "regime", "régimen"),
}.items():
    for _lib in _libs:
        LIBELLES_ARTICLE[_cle(_lib)] = _champ


def segments_libelles(toks: Sequence[Any]) -> list[tuple[str, int, int]]:
    """Couples « libellé valeur » d'une ligne séparés par « | » (ou « ; ») : liste de (champ, début, fin) des mots
    de la **valeur**. Le libellé est le plus long préfixe connu du segment (un à trois mots)."""
    out: list[tuple[str, int, int]] = []
    debut = 0
    bornes: list[tuple[int, int]] = []
    for k, t in enumerate(toks):
        if t.t in ("|", "¦", ";"):
            bornes.append((debut, k))
            debut = k + 1
    bornes.append((debut, len(toks)))
    for a, b in bornes:
        if b - a < 2:
            continue
        for n in (3, 2, 1):
            if a + n >= b:
                continue
            champ = LIBELLES_ARTICLE.get(_cle(" ".join(t.t for t in toks[a:a + n])))
            if champ:
                v = a + n
                while v < b and toks[v].t in (":", "=", "-", "–"):
                    v += 1
                if v < b:
                    out.append((champ, v, b))
                break
    return out


# --- taxation en prose -----------------------------------------------------------------------------------------

_CODE_TAXE_RE = re.compile(r"^[A-Z](?:\d{2}|[A-Z]{2})$")
_MOTS_BASE = frozenset({"base", "basis", "assiette", "bemessungsgrundlage", "imponibile", "imponible", "on"})
_FOIS = frozenset({"x", "×", "*", "at", "à", "a", "@"})


def ligne_taxe_prose(toks: Sequence[Any]) -> dict[str, tuple[int, int]] | None:
    """Ligne de taxation écrite en prose : « A00 Droits de douane : base 357,52 EUR x 2,7 % = 10,00 EUR (payé
    comptant) », « FPE Droit forfaitaire petits envois : 2 articles x 3,00 EUR = 6,00 EUR (paiement différé) ».

    Rend les plages de mots (début, fin) ``code``, ``libelle``, ``base``, ``taux``, ``montant`` et ``mp``
    (facultatifs sauf code, montant et le signe « = ») ; ``None`` si la ligne n'a pas cette forme."""
    if len(toks) < 5 or not _CODE_TAXE_RE.match(toks[0].t.strip(".,:;")):
        return None
    if toks[0].t.strip(".,:;") in ("EUR", "TVA", "VAT", "MRN", "LRN", "USD", "TOT", "REF"):
        return None
    egal = next((k for k, t in enumerate(toks) if t.t in ("=", "→")), None)
    if egal is None or egal < 2:
        return None
    deux_points = next((k for k in range(1, egal) if toks[k].t == ":" or toks[k].t.endswith(":")), None)
    debut_calc = (deux_points + 1) if deux_points is not None else None
    if debut_calc is None:
        return None
    lib_fin = deux_points + (0 if toks[deux_points].t == ":" else 1)
    out: dict[str, tuple[int, int]] = {"code": (0, 1)}
    if lib_fin > 1:
        out["libelle"] = (1, lib_fin)
    calc = list(range(debut_calc, egal))
    fois = next((k for k in calc if toks[k].t.lower() in _FOIS), None)
    if fois is not None:
        a = debut_calc
        while a < fois and _cle(toks[a].t) in _MOTS_BASE:
            a += 1
        if a < fois:
            out["base"] = (a, fois)
        if fois + 1 < egal:
            out["taux"] = (fois + 1, egal)
    else:
        a = debut_calc
        while a < egal and _cle(toks[a].t) in _MOTS_BASE:
            a += 1
        pct = next((k for k in range(a, egal) if toks[k].t.endswith("%")), None)
        if pct is None:
            return None
        out["taux"] = (a, pct + 1)
    # montant : nombre (et devise) après « = », jusqu'à la parenthèse
    b = egal + 1
    fin = b
    while fin < len(toks) and not toks[fin].t.startswith("("):
        fin += 1
    if fin == b or not any(re.search(r"\d", t.t) for t in toks[b:fin]):
        return None
    out["montant"] = (b, fin)
    if fin < len(toks):
        out["mp"] = (fin, len(toks))
    return out
