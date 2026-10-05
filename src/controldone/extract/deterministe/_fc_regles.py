"""Règles générales de mise en page des factures commerciales (aides sans état, D-2002, D-2003, D-2005).

- ``scinder_mots_colles`` : mots d'un en-tête de tableau soudés par l'extraction du texte (« arancelariaOrigen »,
  « UnidadPrecio ») redécoupés à la frontière minuscule → majuscule, positions interpolées ;
- ``nettoyer_colonnes`` : code de devise imprimé à la suite d'un libellé de colonne de prix ou de montant
  (« Amount CNY », « Importo EUR », « Prix (USD) ») rattaché à cette colonne au lieu d'ouvrir une colonne
  inconnue (qui volait les montants alignés à droite) ; deuxième colonne « numéro » (« NO. | ITEM NO. ») lue comme
  référence d'article, deuxième colonne « article » sans colonne de désignation (« SKU | Item ») lue comme
  désignation ;
- ``chercher_partout`` : libellé cherché aussi au milieu d'un segment (« Net weight: 1 kg Gross weight: 2 kg »),
  précédé d'une frontière de mot ;
- ``codes_devise_libelle`` / ``devise_symbole`` : code ISO 4217 imprimé dans un libellé (« TOTAL CNY »,
  « Total due (INR) ») ; symbole monétaire univoque (€, £, ₩, ₹, ₺) ; « ¥ » et « $ » seulement si un seul code ISO
  compatible est imprimé sur le document (¥ : CNY ou JPY ; $ : USD, CAD, AUD…), sinon devise inconnue.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Sequence

from controldone.extract.deterministe._mise_en_page import (
    Colonne,
    Segment,
    Trouve,
    VueDocument,
    VueLigne,
    chercher,
)
from controldone.ingest.texte import Mot
from controldone.normalize import ISO_4217

__all__ = [
    "chercher_partout",
    "codes_devise_libelle",
    "devise_symbole",
    "nettoyer_colonnes",
    "scinder_mots_colles",
]

_COLLE = re.compile(r"(?<=[a-zà-ÿ]{2})(?=[A-ZÀ-Ý][a-zà-ÿ])")


def scinder_mots_colles(li: VueLigne) -> VueLigne:
    """Copie de la ligne dont les mots soudés « minusculesMajuscule… » sont redécoupés (positions au prorata
    des caractères). La ligne d'origine est inchangée ; sans mot soudé, la ligne est rendue telle quelle."""
    if not any(_COLLE.search(m.texte) for m in li.mots):
        return li
    segs = []
    for s in li.segments:
        mots: list[Mot] = []
        for m in s.mots:
            coupes = [0] + [x.start() for x in _COLLE.finditer(m.texte)] + [len(m.texte)]
            if len(coupes) == 2:
                mots.append(m)
                continue
            n = max(1, len(m.texte))
            larg = m.x1 - m.x0
            for a, b in itertools.pairwise(coupes):
                mots.append(Mot(m.texte[a:b], m.x0 + larg * a / n, m.y0, m.x0 + larg * b / n, m.y1, m.confiance,
                                m.taille))
        segs.append(Segment(tuple(mots), s.page, s.ligne, s.rang))
    return VueLigne(page=li.page, rang=li.rang, segments=segs, ligne=li.ligne)


_CODE_SEUL = re.compile(r"^\(?([A-Z]{3})\)?:?$")
_SYMBOLES = {"€": "EUR", "£": "GBP", "₩": "KRW", "₹": "INR", "₺": "TRY"}


def _code_colonne(libelle: str) -> str | None:
    m = _CODE_SEUL.match(libelle.strip())
    if m and m.group(1) in ISO_4217:
        return m.group(1)
    t = libelle.strip("() :")
    return t if t in _SYMBOLES or t in ("$", "¥") else None


def nettoyer_colonnes(cols: list[Colonne], mots: Sequence[Mot] = ()) -> tuple[list[Colonne], list[str]]:
    """Colonnes d'en-tête nettoyées (voir le module) et codes de devise lus dans l'en-tête des colonnes de prix
    et de montant (symboles « $ » / « ¥ » rendus tels quels, à résoudre par ``devise_symbole``). ``mots`` : mots
    de la ligne d'en-tête ; une colonne inconnue qui prolonge le code par d'autres mots (cellules voisines
    soudées) garde ces mots en colonne inconnue."""
    out: list[Colonne] = []
    codes: list[str] = []
    for c in cols:
        code = _code_colonne(c.libelle) if c.type == "inconnue" else None
        if code is not None and out and out[-1].type in ("prix_unitaire", "montant"):
            mot = next((m for m in mots if abs(m.x0 - c.x0) < 1e-9), None)
            fin = mot.x1 if mot is not None else c.x1
            out[-1].x1 = max(out[-1].x1, fin)
            out[-1].libelle = f"{out[-1].libelle} {c.libelle}"
            codes.append(code)
            reste = [m for m in mots if m.x0 >= fin and m.x1 <= c.x1 + 1e-9]
            if reste:
                out.append(Colonne("inconnue", min(m.x0 for m in reste), c.x1, " ".join(m.texte for m in reste)))
            continue
        out.append(c)
    vus: set[str] = set()
    types = {c.type for c in out}
    for c in out:
        if c.type == "numero_ligne" and c.type in vus and "reference_article" not in types:
            c.type = "reference_article"
            types.add("reference_article")
        elif c.type == "reference_article" and c.type in vus and "description" not in types:
            c.type = "description"
            types.add("description")
        vus.add(c.type)
    for a, b in itertools.pairwise(out):
        mid = (a.x1 + b.x0) / 2
        a.droite = mid
        b.gauche = mid
    if out:
        out[0].gauche = 0.0
        out[-1].droite = 1.0
    return out, codes


def chercher_partout(vue: VueDocument, motifs: Sequence[re.Pattern[str]], *,
                     pages: Iterable[int] | None = None) -> list[Trouve]:
    """Comme ``chercher``, mais le libellé peut commencer au milieu d'un segment (après une frontière de mot)."""
    pats = [re.compile(r"(?<![a-z0-9])(?:" + p.pattern + ")") for p in motifs]
    return chercher(vue, pats, pages=pages, debut_segment=False)


def codes_devise_libelle(mots: Sequence[Mot]) -> list[str]:
    """Codes ISO 4217 écrits en capitales, seuls dans leur mot (« CNY », « (INR) »), dans un libellé."""
    out = []
    for m in mots:
        mm = _CODE_SEUL.match(m.texte.strip())
        if mm and mm.group(1) in ISO_4217:
            out.append(mm.group(1))
    return out


_DOLLARS = frozenset({"USD", "CAD", "AUD", "NZD", "HKD", "SGD", "MXN", "TWD"})
_YENS = frozenset({"JPY", "CNY"})


def devise_symbole(symbole: str, codes_page: Iterable[str]) -> str | None:
    """Devise d'un symbole monétaire : univoque (€, £, ₩, ₹, ₺) ; « ¥ » (CNY ou JPY) et « $ » seulement si un seul
    code ISO compatible est imprimé sur le document ; ``None`` sinon (devise inconnue)."""
    s = symbole.strip("() :")
    if s in _SYMBOLES:
        return _SYMBOLES[s]
    codes = set(codes_page)
    familles = {"¥": _YENS, "￥": _YENS, "$": _DOLLARS, "US$": {"USD"}}
    fam = familles.get(s)
    if fam is None:
        return None
    compatibles = codes & fam
    return next(iter(compatibles)) if len(compatibles) == 1 else None
