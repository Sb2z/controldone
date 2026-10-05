"""Outils communs des extracteurs déterministes : lecture de la mise en page d'un document.

Ce module ne connaît aucun type de document. Il fournit :

- ``VueDocument`` : les pages d'un document (``PageText`` positionné de l'ingestion) découpées en lignes
  et en **segments** (suites de mots séparés par un blanc étroit : une cellule, un libellé, une valeur) ;
- la recherche de **libellés multilingues** (expressions régulières sur le texte sans accents) et de la
  valeur associée (reste du segment, segment à droite, segment en dessous) ;
- la lecture des **nombres imprimés** (groupes de mots « 1 234,56 », devise adjacente, unité de masse
  ou de colis qui interdit la lecture comme montant) et l'inférence du séparateur décimal du document ;
- la lecture de **tableaux** par colonnes : en-tête reconnu par vocabulaire, attribution des mots aux
  colonnes par recouvrement horizontal, lignes de continuation ;
- la **confiance** d'une lecture (texte natif, ou minimum des confiances OCR des mots lus) et la
  construction de la ``ValeurSourcee`` (ancrage, zone, contexte).

Le texte des documents est une donnée : rien n'y est interprété comme une consigne (§20.2).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import pairwise

from controldone.ids import IdGenerator, Prefixe
from controldone.ingest.texte import Ligne, Mot, PageText
from controldone.model.champs import type_valeur_pour
from controldone.model.documents import Page
from controldone.model.enums import Methode, QualiteTexte, TypeDocument, TypeValeur
from controldone.model.valeur import ExtracteurInfo, ValeurSourcee, Zone
from controldone.normalize import (
    DEVISE_INCONNUE,
    ISO_4217,
    normalize_currency,
    normalize_vat,
    parse_amount,
)
from controldone.normalize.text import cle_texte, normaliser_espaces

__all__ = [
    "Colonne",
    "Fabrique",
    "Lecture",
    "Nombre",
    "Segment",
    "VueDocument",
    "VueLigne",
    "VuePage",
    "chercher",
    "colonne_droite",
    "confiance_mots",
    "est_bandeau_texte",
    "lignes_bandeau",
    "lire_tableau",
    "lire_tva_ocr",
    "nombres_dans",
    "pages_du_document",
    "pave",
    "vue_document",
]

_ELLIPSE = "…"


# --- structures -----------------------------------------------------------------------------------------


@dataclass
class Segment:
    """Suite de mots d'une même ligne séparés par des blancs étroits (une cellule, un libellé…)."""

    mots: tuple[Mot, ...]
    page: int
    ligne: int  # rang de la ligne dans la page (0-based)
    rang: int  # rang du segment dans la ligne

    @property
    def texte(self) -> str:
        return " ".join(m.texte for m in self.mots)

    @property
    def cle(self) -> str:
        return cle_texte(self.texte)

    @property
    def x0(self) -> float:
        return min(m.x0 for m in self.mots)

    @property
    def x1(self) -> float:
        return max(m.x1 for m in self.mots)

    @property
    def y0(self) -> float:
        return min(m.y0 for m in self.mots)

    @property
    def y1(self) -> float:
        return max(m.y1 for m in self.mots)


@dataclass
class VueLigne:
    page: int
    rang: int
    segments: list[Segment]
    ligne: Ligne

    @property
    def mots(self) -> list[Mot]:
        return [m for s in self.segments for m in s.mots]

    @property
    def texte(self) -> str:
        return "   ".join(s.texte for s in self.segments)

    @property
    def cle(self) -> str:
        return cle_texte(self.texte)

    @property
    def y0(self) -> float:
        return min((m.y0 for m in self.mots), default=0.0)

    @property
    def y1(self) -> float:
        return max((m.y1 for m in self.mots), default=0.0)

    @property
    def hauteur(self) -> float:
        return max(1e-3, self.y1 - self.y0)


@dataclass
class VuePage:
    numero: int
    texte: PageText
    lignes: list[VueLigne]
    methode: Methode
    geometrie: bool
    tableur: bool
    qualite: QualiteTexte

    @property
    def pas_ligne(self) -> float:
        """Interligne médian (hauteur relative)."""
        ys = sorted(li.y0 for li in self.lignes)
        ecarts = sorted(b - a for a, b in pairwise(ys) if b - a > 1e-4)
        return ecarts[len(ecarts) // 2] if ecarts else 0.015


@dataclass
class VueDocument:
    pages: list[VuePage]
    separateur_decimal: str | None = None
    textes: dict[int, str] = field(default_factory=dict)

    def lignes(self) -> Iterable[VueLigne]:
        for p in self.pages:
            yield from p.lignes

    def page(self, numero: int) -> VuePage | None:
        return next((p for p in self.pages if p.numero == numero), None)

    @property
    def texte(self) -> str:
        return "\n".join(p.texte.texte for p in self.pages)


@dataclass
class Lecture:
    """Valeur lue sur une page : mots consécutifs d'une ligne (ou cellule), avec leur provenance."""

    mots: tuple[Mot, ...]
    page: int
    methode: Methode
    contexte: str | None = None
    texte_force: str | None = None

    @property
    def texte(self) -> str:
        return self.texte_force if self.texte_force is not None else " ".join(m.texte for m in self.mots)

    @property
    def zone(self) -> Zone | None:
        if not self.mots or all(m.x1 <= 0 for m in self.mots):
            return None
        return Zone(
            x0=_borne(min(m.x0 for m in self.mots)), y0=_borne(min(m.y0 for m in self.mots)),
            x1=_borne(max(m.x1 for m in self.mots)), y1=_borne(max(m.y1 for m in self.mots)),
        )

    @property
    def confiance_ocr(self) -> float | None:
        cs = [m.confiance for m in self.mots if m.confiance is not None]
        return min(cs) if cs else None


def _borne(v: float) -> float:
    return min(1.0, max(0.0, round(float(v), 5)))


# --- construction de la vue -------------------------------------------------------------------------------


def _page_texte(p: object) -> PageText:
    if isinstance(p, PageText):
        return p
    texte = getattr(p, "texte", None)
    if isinstance(texte, PageText):  # PageExtraite
        return texte
    if isinstance(p, Page):
        try:
            from controldone.ingest.decoupage import texte_positionne

            return texte_positionne(p)
        except Exception:  # pragma: no cover - repli sans géométrie
            pass
        return _sans_geometrie(p.numero, p.texte, p.qualite_texte)
    raise TypeError(f"page non reconnue : {type(p).__name__}")


def _sans_geometrie(numero: int, texte: str, qualite: QualiteTexte) -> PageText:
    lignes = []
    for li in texte.splitlines():
        if li.strip():
            lignes.append(Ligne(texte=li.strip(), mots=tuple(Mot(m, 0, 0, 0, 0) for m in li.split())))
    return PageText(numero=numero, texte=texte, lignes=lignes, qualite=qualite, source="inconnue")


def _synthetiser_geometrie(pt: PageText) -> list[Ligne]:
    """Page sans boîtes : positions déduites des colonnes de caractères (« 3 espaces » = colonne)."""
    n = max(1, len(pt.lignes))
    larg = max([len(li.texte) for li in pt.lignes] + [1])
    sortie = []
    for i, li in enumerate(pt.lignes):
        mots = []
        for m in re.finditer(r"\S+", li.texte):
            mots.append(Mot(m.group(0), m.start() / larg, i / n, m.end() / larg, (i + 0.8) / n))
        if mots:
            sortie.append(Ligne(texte=li.texte, mots=tuple(mots)))
    return sortie


def _mots_cellule(cellule: Mot) -> list[Mot]:
    """Mots d'une cellule de tableur, positionnés proportionnellement dans la boîte de la cellule."""
    texte = cellule.texte
    n = max(1, len(texte))
    larg = cellule.x1 - cellule.x0
    return [Mot(m.group(0), cellule.x0 + larg * m.start() / n, cellule.y0, cellule.x0 + larg * m.end() / n,
                cellule.y1, cellule.confiance, cellule.taille) for m in re.finditer(r"\S+", texte)]


def _segmenter(mots: Sequence[Mot], *, tableur: bool) -> list[list[Mot]]:
    if not mots:
        return []
    if tableur:
        return [g for g in (_mots_cellule(m) for m in mots) if g]
    groupes: list[list[Mot]] = [[mots[0]]]
    for prec, m in pairwise(mots):
        lc = [(x.x1 - x.x0) / max(1, len(x.texte)) for x in (prec, m) if x.x1 > x.x0]
        largeur_car = sum(lc) / len(lc) if lc else 0.006
        seuil = max(2.2 * largeur_car, 0.011)
        if m.x0 - prec.x1 > seuil:
            groupes.append([m])
        else:
            groupes[-1].append(m)
    return groupes


def pages_du_document(document: object, pages: Sequence[object], options: dict | None = None) -> list[object]:
    """Pages du document (numéros de ``document.pages``), remplacées par leur ``PageText`` positionné quand
    le pipeline le fournit dans ``options["textes_pages"]`` (``{numéro: PageText}``)."""
    refs = getattr(document, "pages", None) or []
    nums = {r.numero for r in refs}
    choisies = [p for p in pages if not nums or getattr(p, "numero", None) in nums] or list(pages)
    opt = (options or {}).get("textes_pages") or (options or {}).get("pages_texte")
    if opt:
        par_num = opt if isinstance(opt, dict) else {getattr(p, "numero", i + 1): p for i, p in enumerate(opt)}
        choisies = [par_num.get(getattr(p, "numero", None), p) for p in choisies]
    return choisies


def vue_document(pages: Sequence[object], *, separateur_decimal: str | None = None) -> VueDocument:
    """Vue d'un document à partir de ``Page`` (modèle), ``PageText`` ou ``PageExtraite``."""
    vues = []
    for p in pages:
        pt = _page_texte(p)
        qualite = getattr(p, "qualite_texte", None) or pt.qualite
        tableur = pt.source in ("tableur", "csv")
        lignes_src = pt.lignes
        geometrie = any(m.x1 > 0 for li in lignes_src for m in li.mots)
        if not geometrie:
            lignes_src = _synthetiser_geometrie(pt)
        methode = Methode.ocr if (pt.source == "ocr" or qualite is QualiteTexte.ocr) else Methode.texte_natif
        lignes: list[VueLigne] = []
        for li in lignes_src:
            mots = sorted(li.mots, key=lambda m: m.x0)
            if not mots:
                continue
            rang = len(lignes)
            segs = [Segment(tuple(g), pt.numero, rang, k)
                    for k, g in enumerate(_segmenter(mots, tableur=tableur))]
            lignes.append(VueLigne(page=pt.numero, rang=rang, segments=segs, ligne=li))
        vues.append(VuePage(numero=pt.numero, texte=pt, lignes=lignes, methode=methode, geometrie=geometrie,
                            tableur=tableur, qualite=qualite))
    vue = VueDocument(pages=vues, textes={v.numero: v.texte.texte for v in vues})
    vue.separateur_decimal = separateur_decimal or inferer_separateur(vue)
    return vue


# --- nombres ----------------------------------------------------------------------------------------------

_NUM_MOT = re.compile(r"^[(\-−–]?[$€£¥₩]?\d[\d.,'’\u00a0\u202f\u2009]*\)?-?$")
_GROUPE3 = re.compile(r"^\d{3}(?:[.,]\d{1,3})?\)?-?$")
_TETE = re.compile(r"^[(\-−–]?[$€£¥₩]?\d{1,3}$")
_SYMBOLES_DEVISE = set("$€£¥₩")

UNITES_MASSE = re.compile(r"^(kgs?|kilos?|kilogrammes?|kilograms?|kilogramos?|lbs?|pounds?|t|tonnes?|tons?|g|grs?)\.?$")
MOTS_COLIS = re.compile(
    r"^(cartons?|ctns?|colis|packages?|pkgs?|pcs|pieces?|pallets?|palettes?|bultos?|cajas?|caisses?|cases?|"
    r"boxes|bo[iî]tes|bundles?|rolls?|drums?|bags?|sacs?|pce|uds)\.?$"
)


@dataclass(frozen=True)
class Nombre:
    """Nombre imprimé repéré dans une suite de mots : ``i`` à ``j`` exclus (indices de mots)."""

    i: int
    j: int
    texte: str
    tronque: bool = False


def _est_num(t: str) -> bool:
    return bool(_NUM_MOT.match(t))


def nombres_dans(mots: Sequence[Mot]) -> list[Nombre]:
    """Nombres d'une suite de mots, en regroupant les milliers séparés par des espaces (« 1 234,56 »)."""
    out: list[Nombre] = []
    k = 0
    while k < len(mots):
        t = mots[k].texte
        if t.endswith(_ELLIPSE):
            if re.match(r"^[(\-]?\d", t):
                out.append(Nombre(k, k + 1, t, tronque=True))
            k += 1
            continue
        if not _est_num(t):
            k += 1
            continue
        j = k + 1
        if _TETE.match(t):
            while j < len(mots) and _GROUPE3.match(mots[j].texte) and _ecart_etroit(mots[j - 1], mots[j]):
                j += 1
        # OCR : espace parasite après un séparateur (« 113, 212.72 », « 1.008, 46 »)
        while j < len(mots) and _ecart_etroit(mots[j - 1], mots[j]) and (
                (re.search(r"\d[.,]$", mots[j - 1].texte) and re.match(r"^\d", mots[j].texte) and _est_num(mots[j].texte))
                or (re.search(r"\d$", mots[j - 1].texte) and re.fullmatch(r"[.,]\d{1,3}\)?-?", mots[j].texte))):
            j += 1  # OCR : espace parasite autour d'un séparateur (« 113, 212.72 », « 2,902 .060 »)
        out.append(Nombre(k, j, " ".join(m.texte for m in mots[k:j])))
        k = j
    return out


_ESPACE_APRES_SEP = re.compile(r"(?<=\d[.,])\s+(?=\d)|(?<=\d)\s+(?=[.,]\d)")


def texte_nombre(texte: str) -> str:
    """Texte numérique à interpréter : espace parasite de l'OCR après un séparateur retirée."""
    return _ESPACE_APRES_SEP.sub("", texte)


def _ecart_etroit(a: Mot, b: Mot) -> bool:
    if a.x1 <= 0 and b.x1 <= 0:
        return True
    largeur_car = (a.x1 - a.x0) / max(1, len(a.texte))
    return b.x0 - a.x1 <= max(1.6 * largeur_car, 0.009)


def inferer_separateur(vue: VueDocument) -> str | None:
    """Séparateur décimal dominant du document (``"."`` ou ``","``), ``None`` sans indice."""
    votes = {".": 0.0, ",": 0.0}
    for li in vue.lignes():
        for n in nombres_dans(li.mots):
            t = n.texte.strip("()-−–$€£¥₩")
            if n.tronque:
                continue
            p, v = t.rfind("."), t.rfind(",")
            if p >= 0 and v >= 0:
                votes["." if p > v else ","] += 3
                continue
            for sep, autre in ((".", ","), (",", ".")):
                if t.count(sep) >= 2 and re.fullmatch(rf"\d{{1,3}}(?:{re.escape(sep)}\d{{3}})+", t):
                    votes[autre] += 1  # « 1,250,000 » : la virgule groupe les milliers
            m0 = re.fullmatch(r"0([.,])\d+", t)
            if m0:
                votes[m0.group(1)] += 2  # « 0.479 » : séparateur décimal certain
                continue
            m1 = re.fullmatch(r"\d+([.,])(\d{1}|\d{4,})", t)
            if m1 and not re.fullmatch(r"\d{4}[.,]\d{2}(?:[.,]\d{2})*", t):
                votes[m1.group(1)] += 1  # « 12.5 », « 3.1416 »
                continue
            m = re.fullmatch(r"([\d '’]+)([.,])(\d{2})", t)
            if m:
                entier = m.group(1)
                poids = 1.0 if (" " in entier or "'" in entier or "’" in entier or len(entier) <= 3) else 0.3
                votes[m.group(2)] += poids
    if votes["."] == votes[","]:
        return None
    return "." if votes["."] > votes[","] else ","


def lire_montant_mots(
    mots: Sequence[Mot], *, vue: VueDocument, devise: str | None = None, dernier: bool = True,
    rejeter_masse: bool = True,
) -> tuple[int, int, Decimal] | None:
    """Repère un montant dans une suite de mots : (i, j, valeur absolue) en incluant devise et signe
    adjacents dans [i, j). Une valeur suivie d'une unité de masse ou de colis est rejetée."""
    nombres = nombres_dans(mots)
    if dernier:
        nombres = list(reversed(nombres))
    for n in nombres:
        if n.tronque:
            continue
        suite = mots[n.j].texte if n.j < len(mots) else ""
        suite_cle = cle_texte(suite).strip(":;,")
        if rejeter_masse and (UNITES_MASSE.match(suite_cle) or MOTS_COLIS.match(suite_cle)):
            continue
        if re.search(r"(kgs?|lbs?)$", cle_texte(n.texte)):
            continue
        i, j = n.i, n.j
        if i > 0 and _est_devise(mots[i - 1].texte):
            i -= 1
        elif j < len(mots) and _est_devise(mots[j].texte):
            j += 1
        if i > 0 and mots[i - 1].texte in ("-", "−", "–"):
            i -= 1
        texte = " ".join(m.texte for m in mots[i:j])
        dev = devise
        code = normalize_currency(texte)
        if code and code != DEVISE_INCONNUE:
            dev = code
        m = parse_amount(texte_nombre(n.texte), devise=dev, separateur_decimal=vue.separateur_decimal)
        if m is None:
            continue
        return i, j, m.valeur
    return None


def _est_devise(t: str) -> bool:
    t2 = t.strip(":()")
    return (t2.upper() in ISO_4217 and t2.isupper()) or (len(t2) <= 3 and bool(t2) and set(t2) <= _SYMBOLES_DEVISE)


def devise_dans(texte: str) -> str | None:
    """Code ISO 4217 écrit en majuscules dans un texte (premier trouvé)."""
    for c in re.findall(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])", texte):
        if c in ISO_4217:
            return c
    return None


# --- libellés ------------------------------------------------------------------------------------------------


@dataclass
class Trouve:
    """Libellé reconnu : segment, et indice du premier mot après le libellé dans ce segment."""

    segment: Segment
    ligne: VueLigne
    page: VuePage
    apres: int
    motif: str


def _decoupe_mots(segment: Segment) -> tuple[str, list[int]]:
    """Texte normalisé du segment et position de début de chaque mot dans ce texte."""
    pos, parts, n = [], [], 0
    for k, m in enumerate(segment.mots):
        c = cle_texte(m.texte)
        if k == 0 and c != "#":
            c = re.sub(r"^[_|'\"“”‘’.,:;°*~-]+", "", c)  # bruit d'OCR en tête de libellé (« _Invoice No: »)
        pos.append(n)
        parts.append(c)
        n += len(c) + 1
    return " ".join(parts), pos


def chercher(
    vue: VueDocument, motifs: Sequence[re.Pattern[str]], *, pages: Iterable[int] | None = None,
    debut_segment: bool = True, exclure: re.Pattern[str] | None = None,
) -> list[Trouve]:
    """Segments dont le texte (sans accents, minuscules) commence par un des ``motifs`` (ou le contient
    si ``debut_segment=False``). Ordre de lecture : page, ligne, segment."""
    pages_ok = set(pages) if pages is not None else None
    out = []
    for p in vue.pages:
        if pages_ok is not None and p.numero not in pages_ok:
            continue
        for li in p.lignes:
            for s in li.segments:
                cle, pos = _decoupe_mots(s)
                if exclure is not None and exclure.search(cle):
                    continue
                for mo in motifs:
                    m = mo.match(cle) if debut_segment else mo.search(cle)
                    if not m:
                        continue
                    fin = m.end()
                    if 0 < fin < len(cle) and cle[fin - 1].isalnum() and cle[fin].isalnum():
                        continue  # le libellé doit finir sur une frontière de mot (« bl » ≠ « block »)
                    apres = next((k for k, d in enumerate(pos) if d >= fin), len(pos))
                    # un libellé qui finit au milieu d'un mot : ce mot fait partie du libellé
                    out.append(Trouve(s, li, p, apres, mo.pattern))
                    break
    return out


def motifs(*expr: str) -> list[re.Pattern[str]]:
    return [re.compile(e) for e in expr]


Accepte = Callable[[Sequence[Mot]], tuple[int, int] | None]


def valeur_apres(
    vue: VueDocument, t: Trouve, accepte: Accepte, *, droite: bool = True, dessous: bool = True,
    max_dx: float = 0.6, lignes_dessous: int = 2, marge_dessous: float = 0.01, dessous_seul: bool = False,
) -> Lecture | None:
    """Valeur associée à un libellé : reste du segment, puis segment(s) à droite, puis en dessous."""
    page = t.page
    mots_seg = t.segment.mots
    reste = mots_seg[t.apres:]
    reste = tuple(m for m in reste if cle_texte(m.texte) not in (":", "#", "-"))
    if reste:
        r = accepte(reste)
        if r is not None:
            return _lecture(reste[r[0]:r[1]], page, t.ligne)
    if droite:
        for s in t.ligne.segments[t.segment.rang + 1:]:
            if s.x0 - t.segment.x1 > max_dx:
                break
            mots = tuple(m for m in s.mots if cle_texte(m.texte) not in (":",))
            r = accepte(mots) if mots else None
            if r is not None:
                return _lecture(mots[r[0]:r[1]], page, t.ligne)
            break  # seulement le segment immédiatement à droite
    if dessous:
        pas = page.pas_ligne
        for li in page.lignes[t.ligne.rang + 1: t.ligne.rang + 1 + lignes_dessous]:
            if li.y0 - t.ligne.y1 > 3.0 * pas + 0.01:
                break
            for s in li.segments:
                if s.x1 < t.segment.x0 - 0.01 or s.x0 > t.segment.x1 + marge_dessous:
                    continue  # la valeur sous un libellé chevauche horizontalement ce libellé
                r = accepte(s.mots)
                if r is not None and dessous_seul and (r[1] - r[0]) < len(s.mots):
                    continue  # la valeur prise dessous doit occuper seule son segment
                # une valeur prise dessous ne doit pas appartenir à un autre couple « libellé : valeur »
                if r is not None and not any(m.texte.endswith(":") for m in s.mots[:r[0]]) and not (
                        r[0] > 0 and re.search(r"[A-Za-z]{3}", s.mots[0].texte) and s.mots[0].texte.endswith(":")):
                    return _lecture(s.mots[r[0]:r[1]], page, li)
    return None


def _lecture(mots: Sequence[Mot], page: VuePage, ligne: VueLigne) -> Lecture:
    return Lecture(tuple(mots), page.numero, page.methode, contexte=normaliser_espaces(ligne.texte)[:200])


def lecture_mots(mots: Sequence[Mot], page: VuePage, ligne: VueLigne) -> Lecture:
    return _lecture(mots, page, ligne)


def pave(t: Trouve, *, fin: Sequence[re.Pattern[str]] = (), exclus: frozenset | set = frozenset(),
         max_lignes: int = 7) -> list[tuple[VueLigne, list[Mot]]]:
    """Lignes du pavé ouvert par le libellé ``t`` : reste du segment, puis segments alignés dessous."""
    page = t.page
    sortie: list[tuple[VueLigne, list[Mot]]] = []
    reste = [m for m in t.segment.mots[t.apres:] if m.texte not in (":", "/")]
    if reste:
        sortie.append((t.ligne, reste))
    elif page.tableur:
        # formulaire « libellé | valeur » : la valeur est dans la cellule à droite ; les lignes suivantes
        # dont le libellé prolonge celui-ci (« Buyer address », « Buyer VAT No. ») complètent le pavé
        droite = t.ligne.segments[t.segment.rang + 1:]
        if droite:
            sortie.append((t.ligne, list(droite[0].mots)))
        tete = cle_texte(t.segment.texte).split()[0] if t.segment.texte else ""
        for li in page.lignes[t.ligne.rang + 1: t.ligne.rang + 1 + max_lignes]:
            if len(li.segments) < 2 or not li.segments[0].cle.startswith(tete):
                break
            sortie.append((li, list(li.segments[1].mots)))
        return sortie
    x0 = t.segment.x0
    # largeur de colonne : jusqu'au segment suivant de la ligne du libellé, sinon mi-page
    # (bruit OCR isolé — « 7 », « : » — ignoré : il ne borne pas la colonne, D-2513)
    suivants = [s for s in t.ligne.segments[t.segment.rang + 1:]
                if not (page.methode is Methode.ocr and all(_BRUIT_OCR.fullmatch(m.texte) for m in s.mots))]
    xmax = suivants[0].x0 - 0.005 if suivants else max(t.segment.x1 + 0.35, 0.5)
    # en-tête à deux colonnes : les lignes de la colonne de droite s'intercalent avec celles du pavé (D-951)
    droite_col = colonne_droite(page, t.ligne, x0, t.segment.x1) if page.geometrie and not suivants else None
    if droite_col is not None:
        xmax = min(xmax, droite_col - 0.005)
    pas = page.pas_ligne
    prec_y = t.ligne.y1
    for li in page.lignes[t.ligne.rang + 1:]:
        if li.y0 - prec_y > 2.6 * pas + 0.005 or len(sortie) >= max_lignes:
            break
        segs = [s for s in li.segments if s.x0 >= x0 - 0.03 and s.x0 < xmax and s.x1 <= xmax + 0.25]
        if droite_col is not None:
            segs = [s for s in segs if s.x1 <= droite_col + 0.01]
        if not segs:
            if any(s.x0 < x0 - 0.03 for s in li.segments):
                break
            continue
        s0 = segs[0]
        if any(mo.match(s0.cle) for mo in fin) or (li.page, li.rang) in exclus:
            break
        mots = [m for s in segs for m in s.mots]
        if page.methode is Methode.ocr and all(_BRUIT_OCR.fullmatch(m.texte) for m in mots):
            continue  # tache, ponctuation isolée lue par l'OCR : ni une ligne du pavé ni sa fin (D-2513)
        if page.methode is Methode.ocr and sortie and sortie[-1][0] is not t.ligne:
            li_p, mots_p = sortie[-1]
            recouvre = min(li.y1, li_p.y1) - max(li.y0, li_p.y0)
            if recouvre >= 0.5 * min(li.y1 - li.y0, li_p.y1 - li_p.y0) > 0:
                # une ligne imprimée découpée par l'OCR en deux lignes de même hauteur (« SARL » lu avant
                # « Utopia Outillage ») : mots réunis dans l'ordre de lecture, bruit isolé écarté (D-2513)
                tous = sorted([*mots_p, *mots], key=lambda m: m.x0)
                sortie[-1] = (li_p, [m for m in tous if not _BRUIT_OCR.fullmatch(m.texte)])
                prec_y = max(prec_y, li.y1)
                continue
        sortie.append((li, mots))
        prec_y = li.y1
    return sortie


#: Mot de bruit OCR dans un pavé (ponctuation, chiffre isolé : « 7. », « ‘ »).
_BRUIT_OCR = re.compile(r"[\W_]*\d?[\W_]*")



# --- bandeaux, en-têtes et pieds de page répétés (D-953) ----------------------------------------------------

#: Vocabulaire des bandeaux et filigranes (texte sans accents, minuscules) : jamais le nom d'une partie.
BANDEAU_VOCABULAIRE = re.compile(
    r"donnees fictives|fictitious (?:data|document)|document fictif|documents? (?:de )?(?:demonstration|test|"
    r"specimen)|(?:demonstration|demo|test|sample|specimen) (?:document|copy|data)|\bspecimen\b|"
    r"pour (?:la )?demonstration|for demonstration|aucune valeur reelle|no real value|not a real|"
    r"sans valeur (?:legale|juridique)|watermark|filigrane|ne pas utiliser|do not use|\bbrouillon\b|\bdraft\b"
)
#: Marges haute et basse de la page (hauteur relative) : un texte qui y tient entièrement est un bandeau.
MARGE_BANDEAU = 0.03


def _cle_repetition(texte: str) -> str:
    return re.sub(r"\d+", "#", cle_texte(texte))


def est_bandeau_texte(texte: str) -> bool:
    return bool(BANDEAU_VOCABULAIRE.search(cle_texte(texte)))


def lignes_bandeau(vue: VueDocument, *, entetes_repetes: bool = True) -> set[tuple[int, int]]:
    """Lignes ``(page, rang)`` qui sont des bandeaux, en-têtes ou pieds de page plutôt que du contenu :

    - vocabulaire de bandeau ou de filigrane (« données fictives », « specimen », « draft »…) ;
    - texte tenant entièrement dans la marge haute ou basse de la page (``MARGE_BANDEAU``) ;
    - sur un document de plusieurs pages, ligne répétée (chiffres neutralisés : « Page 1 / 2 ») sur
      **toutes** les pages, dans le quart haut ou bas de chacune.

    Règle générale de mise en page, sans référence à un gabarit : un nom de partie n'est jamais lu sur
    ces lignes. ``entetes_repetes=False`` : les lignes répétées du **haut** de page ne sont pas retenues
    (papier à en-tête de l'émetteur, imprimé sur chaque page : c'est là que se lit son nom) ; les pieds
    répétés le restent."""
    out: set[tuple[int, int]] = set()
    for p in vue.pages:
        for li in p.lignes:
            if est_bandeau_texte(li.texte) or (p.geometrie and li.mots and (li.y1 <= MARGE_BANDEAU or li.y0 >= 1 - MARGE_BANDEAU)):
                out.add((p.numero, li.rang))
    if len(vue.pages) >= 2:
        par_page: list[dict[str, list[VueLigne]]] = []
        for p in vue.pages:
            d: dict[str, list[VueLigne]] = {}
            for li in p.lignes:
                if not p.geometrie or (entetes_repetes and li.y1 <= 0.25) or li.y0 >= 0.75:
                    k = _cle_repetition(li.texte)
                    if len(k) >= 6:
                        d.setdefault(k, []).append(li)
            par_page.append(d)
        communes = set(par_page[0])
        for d in par_page[1:]:
            communes &= set(d)
        for p, d in zip(vue.pages, par_page, strict=True):
            for k in communes:
                for li in d[k]:
                    out.add((p.numero, li.rang))
    return out


def colonne_droite(page: VuePage, ligne: VueLigne, x0: float, x1: float, *, n_lignes: int = 8) -> float | None:
    """Bord gauche d'une colonne de texte imprimée **à droite** d'un pavé ouvert en ``x0`` sur ``ligne`` (en-tête
    à deux colonnes dont les lignes s'intercalent avec celles du pavé) ; ``None`` s'il n'y en a pas.

    Une ligne voisine (au-dessus ou au-dessous du libellé) dont **tout** le texte commence nettement à droite du
    pavé (au-delà de ``x1`` + 0,05 et de ``x0`` + 0,15) appartient à une autre colonne ; le bord retenu est le
    plus petit début de ces lignes, s'il est confirmé par au moins deux lignes alignées (± 0,02)."""
    rang = ligne.rang
    debuts: list[float] = []
    voisines = page.lignes[max(0, rang - n_lignes): rang + 1 + n_lignes]
    for li in voisines:
        segs = li.segments
        if page.methode is Methode.ocr:  # bruit OCR isolé (« . », « —* ») : pas une colonne (D-2513)
            segs = [sg for sg in segs if not all(_BRUIT_OCR.fullmatch(m.texte) for m in sg.mots)]
        if li is ligne or not segs:
            continue
        d = segs[0].x0
        if page.methode is Methode.ocr and d <= max(x1 + 0.05, x0 + 0.15):
            # scan : les deux colonnes lues sur une même ligne ; le segment séparé du pavé par un large blanc
            # ouvre la colonne de droite
            d = next((b.x0 for a, b in pairwise(segs) if b.x0 - a.x1 > 0.08), d)
        if d > max(x1 + 0.05, x0 + 0.15):
            debuts.append(d)
    if not debuts:
        return None
    debuts.sort()
    for d in debuts:
        alignes = [e for e in debuts if abs(e - d) <= 0.02]
        if len(alignes) >= 2:
            return min(alignes)
    return None


# --- accepteurs usuels ------------------------------------------------------------------------------------


def accepte_reference(mots: Sequence[Mot]) -> tuple[int, int] | None:
    """Premier mot ressemblant à une référence (au moins un chiffre, 3 caractères ou plus)."""
    for k, m in enumerate(mots):
        t = m.texte.strip(":;,")
        # OCR : référence coupée par une espace parasite (« EXP -26-00180 », « FAC/2026/0099 -0 »)
        j = k + 1
        while j < len(mots) and re.fullmatch(r"[\-/.][A-Za-z0-9][A-Za-z0-9./\-_]*|[A-Za-z0-9./\-_]*[\-/.]", t) is None \
                and re.match(r"^[\-/]", mots[j].texte) and re.search(r"\d", mots[j].texte) \
                and _ecart_etroit(mots[j - 1], mots[j]):
            t += mots[j].texte
            j += 1
        if j == k + 1 and t.endswith(("-", "/")) and j < len(mots) and re.match(r"^\w", mots[j].texte) \
                and _ecart_etroit(mots[j - 1], mots[j]):
            t += mots[j].texte
            j += 1
        if j == k + 1 and re.fullmatch(r"(?i)no\.|nr\.|n°", t) and j < len(mots) \
                and re.fullmatch(r"\d[\w/\-.]*", mots[j].texte) and mots[j].x0 - m.x1 < (m.x1 - m.x0) / 2:
            t += mots[j].texte  # « No.202601371 » coupé par l'OCR
            j += 1
        if len(t) >= 3 and re.search(r"\d", t) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./\-_#]*", t):
            return k, j
        if k >= 2:
            break
    return None


def accepte_entier(mots: Sequence[Mot]) -> tuple[int, int] | None:
    for n in nombres_dans(mots):
        if not n.tronque and re.fullmatch(r"\d{1,3}(?:[ ,.'’]\d{3})*|\d+", n.texte):
            return n.i, n.j
    return None


def accepte_masse(vue: VueDocument) -> Accepte:
    def f(mots: Sequence[Mot]) -> tuple[int, int] | None:
        for n in nombres_dans(mots):
            if n.tronque:
                continue
            j = n.j
            if j < len(mots) and UNITES_MASSE.match(cle_texte(mots[j].texte).strip(".,;:)")):
                j += 1
            return n.i, j
        return None

    return f


def accepte_montant(vue: VueDocument, devise: str | None) -> Accepte:
    def f(mots: Sequence[Mot]) -> tuple[int, int] | None:
        r = lire_montant_mots(mots, vue=vue, devise=devise)
        return (r[0], r[1]) if r else None

    return f


# --- numéros de TVA ----------------------------------------------------------------------------------------

PAYS_TVA = frozenset(
    "AT BE BG CY CZ DE DK EE EL ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK XI GB CH NO".split()
)
_TVA_LIB = re.compile(r"(vat|tva|iva|ust|btw|mwst|nif|cif|tax\s*id|n[°º.]?\s*(de\s*)?(tva|iva))")


#: Formats nationaux du numéro de TVA (partie après le code pays), pour écarter les références qui
#: commencent par deux lettres (« DEMO307604768 » n'est pas une TVA allemande).
FORMATS_TVA: dict[str, str] = {
    "AT": r"U\d{8}", "BE": r"[01]\d{9}", "BG": r"\d{9,10}", "CY": r"\d{8}[A-Z]", "CZ": r"\d{8,10}",
    "DE": r"\d{9}", "DK": r"\d{8}", "EE": r"\d{9}", "EL": r"\d{9}", "GR": r"\d{9}",
    "ES": r"[0-9A-Z]\d{7}[0-9A-Z]", "FI": r"\d{8}", "FR": r"[0-9A-HJ-NP-Z]{2}\d{9}", "HR": r"\d{11}",
    "HU": r"\d{8}", "IE": r"\d{7}[A-Z]{1,2}|\d[A-Z+*]\d{5}[A-Z]", "IT": r"\d{11}", "LT": r"\d{9}|\d{12}",
    "LU": r"\d{8}", "LV": r"\d{11}", "MT": r"\d{8}", "NL": r"\d{9}B\d{2}", "PL": r"\d{10}", "PT": r"\d{9}",
    "RO": r"\d{2,10}", "SE": r"\d{12}", "SI": r"\d{8}", "SK": r"\d{10}",
    "GB": r"\d{9}|\d{12}|GD\d{3}|HA\d{3}", "XI": r"\d{9}|\d{12}|GD\d{3}|HA\d{3}", "NO": r"\d{9}(?:MVA)?",
    "CH": r"E\d{9}(?:MWST|TVA|IVA)?",
}


#: Libellé d'un numéro de TVA de représentant fiscal (« TVA rep. fiscal : FR… ») : ce n'est pas le numéro de la
#: partie représentée (D-2504).
REP_FISCAL = re.compile(r"\b(rep\.? fiscal|representant fiscal|representante fiscal|fiscal rep(?:resentative)?|"
                        r"steuervertret\w*|fiskalvertret\w*|rappresentante fiscale|fiscaal vertegenwoordiger|"
                        r"przedstawiciel podatkowy)\b")


def lire_tva_mots(mots: Sequence[Mot]) -> tuple[int, int, str] | None:
    """Numéro de TVA dans une suite de mots : (i, j, forme normalisée). Le pays doit être un code TVA
    européen et la suite respecter le format national ; les chiffres peuvent être répartis sur plusieurs
    mots (« FR 68 000 458 570 », « CHE-123.456.789 »)."""
    for k, m in enumerate(mots):
        t = m.texte.strip(":;,()")
        colle = _LIB_TVA_COLLE.match(t)
        if colle and colle.end() < len(t):
            t = t[colle.end():]  # libellé collé au numéro (« TVAFR15000100008 », D-952)
        mm = re.match(r"^([A-Z]{2})([0-9A-Z.\-]*)$", t)
        if not mm or mm.group(1) not in PAYS_TVA:
            continue
        pays = mm.group(1)
        fmt = re.compile(FORMATS_TVA.get(pays, r"[0-9A-Z]{8,12}"))
        corps = re.sub(r"[.\-]", "", mm.group(2))
        meilleur = None
        j = k + 1
        if fmt.fullmatch(corps):
            meilleur = j
        while j < len(mots) and len(corps) < 15:
            u = re.sub(r"[.\-]", "", mots[j].texte.strip(":;,()"))
            if not re.fullmatch(r"[0-9A-Z]{1,12}", u) or (not re.search(r"\d", u) and u not in ("B", "MWST", "TVA",
                                                                                                 "IVA", "MVA")):
                break
            corps += u
            j += 1
            if fmt.fullmatch(corps):
                meilleur = j
        if meilleur is None:
            continue
        brut = t + "".join(re.sub(r"[.\-]", "", x.texte.strip(":;,()")) for x in mots[k + 1:meilleur])
        norm = normalize_vat(re.sub(r"[.\-]", "", brut))
        if norm and colle and colle.end() < len(m.texte.strip(":;,()")) and not tva_colle_valide(norm):
            continue  # libellé collé : la forme seule ne suffit pas, la clé (ou le format) doit être juste
        if norm:
            return k, meilleur, norm
    return None


#: Libellé de TVA collé devant le numéro par la mise en page ou l'OCR (« N°TVAFR… », « VAT:GB… »).
_LIB_TVA_COLLE = re.compile(r"^(?:N[°º]?\.?)?(?:TVA|VAT|IVA|UST-?IDNR|USTID|NIF)(?:NO|N[°º])?[.:#]?(?=[A-Z]{2}\d)",
                            re.IGNORECASE)


def separer_libelle_tva(texte: str) -> str | None:
    """Numéro de TVA collé à son libellé (« TVAFR15000100008 ») -> « FR15000100008 » si la forme (et, pour la
    France, la clé) est valide ; ``None`` sinon."""
    t = texte.strip(":;,()")
    m = _LIB_TVA_COLLE.match(t)
    if not m or m.end() >= len(t):
        return None
    reste = t[m.end():]
    norm = normalize_vat(reste)
    return reste if norm and tva_colle_valide(norm) else None


def tva_colle_valide(norm: str) -> bool:
    """Forme nationale respectée et, pour une TVA française à clé numérique, clé juste."""
    from controldone.normalize import tva_fr_valide

    pays, corps = norm[:2], norm[2:]
    fmt = FORMATS_TVA.get(pays)
    if pays not in PAYS_TVA or fmt is None or not re.fullmatch(fmt, corps):
        return False
    return tva_fr_valide(norm) is not False


_CONFUSION_CHIFFRE = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "S": "5",
                                    "B": "8", "Z": "2", "G": "6"})


def lire_tva_ocr(mots: Sequence[Mot]) -> tuple[int, int, str, bool] | None:
    """Comme ``lire_tva_mots``, en corrigeant les confusions lettre/chiffre de l'OCR (« FRO7000909341 »)
    là où le format national n'admet que des chiffres. Retourne (i, j, TVA normalisée, corrigée ?). Une
    TVA française corrigée n'est retenue que si sa clé est valide."""
    r = lire_tva_mots(mots)
    if r is not None:
        return r[0], r[1], r[2], False
    from controldone.normalize import tva_fr_valide

    for k, m in enumerate(mots):
        t = m.texte.strip(":;,()")
        mm = re.match(r"^([A-Z]{2})(\S*)$", t)
        if not mm or mm.group(1) not in PAYS_TVA:
            continue
        pays = mm.group(1)
        corps = re.sub(r"[.\-]", "", mm.group(2))
        j = k + 1
        while j < len(mots) and len(corps) < 13 and re.fullmatch(r"[0-9A-Za-z|]{1,12}", mots[j].texte.strip(":;,()")) \
                and re.search(r"\d", mots[j].texte):
            corps += mots[j].texte.strip(":;,()")
            j += 1
        if pays == "FR" and len(corps) == 11:
            cle, siren = corps[:2], corps[2:].translate(_CONFUSION_CHIFFRE)
            cle = cle.replace("O", "0").replace("I", "1").replace("o", "0").replace("l", "1")
            cand = f"FR{cle}{siren}"
            if re.fullmatch(FORMATS_TVA["FR"], cle + siren) and tva_fr_valide(cand):
                return k, j, cand, True
        elif pays != "FR":
            cand = corps.translate(_CONFUSION_CHIFFRE)
            fmt = FORMATS_TVA.get(pays)
            if fmt and re.fullmatch(fmt, cand) and re.fullmatch(r"\d+", cand):
                return k, j, f"{pays}{cand}", True
    return None


# --- tableaux ---------------------------------------------------------------------------------------------------


@dataclass
class Colonne:
    type: str
    x0: float
    x1: float
    libelle: str
    gauche: float = 0.0  # bornes d'attribution (calculées)
    droite: float = 1.0


def _cle_entete(t: str) -> str:
    if t == "#":
        return t
    tronque = t.endswith(_ELLIPSE) or t.endswith("...")
    c = cle_texte(t.replace(_ELLIPSE, "")).strip(":").rstrip(".")
    return c + _ELLIPSE if tronque else c


def reconnaitre_entete(
    ligne: VueLigne, vocabulaire: dict[str, Sequence[str]], *, min_colonnes: int = 3,
) -> list[Colonne] | None:
    """Colonnes d'une ligne d'en-tête : chaque type de colonne a des libellés (normalisés, sans accents) ;
    un mot tronqué (« Prix unita… ») est reconnu comme préfixe d'un libellé."""
    mots = ligne.mots
    phrases = [(typ, lib, len(lib.split())) for typ, libs in vocabulaire.items() for lib in libs]
    phrases.sort(key=lambda x: -x[2])
    cols: list[Colonne] = []
    k = 0
    while k < len(mots):
        trouve = None
        for typ, lib, n in phrases:
            if k + n > len(mots):
                continue
            seq = mots[k:k + n]
            if any(b.x0 - a.x1 > 0.03 for a, b in pairwise(seq)):
                continue
            txt = " ".join(_cle_entete(m.texte) for m in seq)
            if txt == lib or (txt.endswith(_ELLIPSE) and len(txt) > 2 and lib.startswith(txt[:-1].rstrip())):
                trouve = (typ, lib, n)
                break
        if trouve is None:
            # libellé inconnu : colonne neutre (ses valeurs ne doivent pas déborder sur les voisines)
            m = mots[k]
            if cols and cols[-1].type == "inconnue" and m.x0 - cols[-1].x1 < 0.012:
                cols[-1].x1 = m.x1
            else:
                cols.append(Colonne("inconnue", m.x0, m.x1, m.texte))
            k += 1
            continue
        typ, lib, n = trouve
        seq = mots[k:k + n]
        cols.append(Colonne(typ, min(m.x0 for m in seq), max(m.x1 for m in seq), " ".join(m.texte for m in seq)))
        k += n
    types = [c.type for c in cols if c.type != "inconnue"]
    if len(types) < min_colonnes or len(set(types)) < min_colonnes:
        return None
    for a, b in pairwise(cols):
        mid = (a.x1 + b.x0) / 2
        a.droite = mid
        b.gauche = mid
    cols[0].gauche = 0.0
    cols[-1].droite = 1.0
    return cols


def attribuer(mots: Sequence[Mot], colonnes: Sequence[Colonne], *, tableur: bool = False) -> dict[str, list[Mot]]:
    """Répartit les mots d'une ligne dans les colonnes (recouvrement horizontal, sinon centre)."""
    out: dict[str, list[Mot]] = {}
    for m in mots:
        meilleur, score = None, -1.0
        for c in colonnes:
            if tableur:
                s = min(m.x1, c.x1) - max(m.x0, c.x0)
            else:
                cx = (m.x0 + m.x1) / 2
                s = 1.0 if c.gauche <= cx < c.droite else -min(abs(cx - c.gauche), abs(cx - c.droite))
            if s > score:
                meilleur, score = c, s
        if meilleur is not None:
            out.setdefault(meilleur.type, []).append(m)
    return out


@dataclass
class RangeeTableau:
    """Ligne logique d'un tableau : cellules par type de colonne (mots), lignes physiques couvertes."""

    cellules: dict[str, list[Mot]]
    lignes: list[VueLigne]
    page: VuePage

    def mots(self, typ: str) -> list[Mot]:
        return self.cellules.get(typ, [])

    def texte(self, typ: str) -> str:
        return " ".join(m.texte for m in self.mots(typ))


def lire_tableau(
    page: VuePage, rang_entete: int, colonnes: Sequence[Colonne], *,
    est_debut: Callable[[dict[str, list[Mot]]], bool],
    est_fin: Callable[[VueLigne], bool],
    est_ignoree: Callable[[VueLigne], bool] | None = None,
) -> tuple[list[RangeeTableau], int]:
    """Lit les lignes sous l'en-tête jusqu'à une ligne de fin (ou un grand blanc). Retourne les rangées et
    le rang de la première ligne après le tableau. ``est_ignoree`` : ligne sautée sans finir le tableau ni
    s'ajouter à une rangée (report « Brought forward » d'une page précédente, D-2508)."""
    rangees: list[RangeeTableau] = []
    pas = page.pas_ligne
    prec_y = page.lignes[rang_entete].y1
    k = rang_entete + 1
    ecart_max = None
    while k < len(page.lignes):
        li = page.lignes[k]
        if est_fin(li):
            break
        if est_ignoree is not None and est_ignoree(li):
            prec_y = li.y1
            k += 1
            continue
        ecart = li.y0 - prec_y
        if rangees:
            pitchs = [b.lignes[0].y0 - a.lignes[-1].y0 for a, b in pairwise(rangees)]
            ref = max(pitchs) if pitchs else 2.5 * pas
            ecart_max = max(2.2 * ref, 3.0 * pas) if not page.tableur else 1.5 / max(1, len(page.lignes))
            if page.tableur:
                ecart_max = 2.5 * (rangees[-1].lignes[-1].y1 - rangees[-1].lignes[-1].y0) + 1e-6
            if ecart > ecart_max:
                break
        cellules = attribuer(li.mots, colonnes, tableur=page.tableur)
        if est_debut(cellules) or not rangees:
            if not est_debut(cellules) and not rangees:
                # ligne avant la première rangée (sous-titre d'en-tête) : ignorée
                k += 1
                prec_y = li.y1
                continue
            rangees.append(RangeeTableau(cellules, [li], page))
        else:
            r = rangees[-1]
            for typ, ms in cellules.items():
                r.cellules.setdefault(typ, []).extend(ms)
            r.lignes.append(li)
        prec_y = li.y1
        k += 1
    return rangees, k


# --- confiance et fabrique de valeurs -------------------------------------------------------------------------

#: Confiance d'une lecture sur texte natif bien identifiée (libellé reconnu, valeur bien formée).
CONF_NATIF = 0.95
#: Plafond d'une lecture OCR non recoupée.
PLAFOND_OCR = 0.88


def confiance_mots(lecture: Lecture | None, *, natif: float = CONF_NATIF, plafond_ocr: float = PLAFOND_OCR) -> float:
    """Confiance d'une lecture : ``natif`` sur texte natif ; sur OCR, fonction du minimum des confiances
    OCR des mots lus, plafonnée (une lecture OCR non recoupée n'atteint pas 0,90)."""
    if lecture is None:
        return 0.0
    if lecture.methode is not Methode.ocr:
        return natif
    c = lecture.confiance_ocr
    if c is None:
        return min(0.7, plafond_ocr)
    return round(max(0.05, min(plafond_ocr, natif - 0.02, 0.2 + 0.75 * c)), 3)


class Fabrique:
    """Construit les ``ValeurSourcee`` d'un document (chemin, normalisation, ancrage, zone, contexte)."""

    def __init__(self, type_document: TypeDocument, document_id: str, extracteur: ExtracteurInfo,
                 vue: VueDocument, ids: IdGenerator | None = None) -> None:
        self.type_document = type_document
        self.document_id = document_id
        self.extracteur = extracteur
        self.vue = vue
        self.ids = ids

    def valeur(
        self, chemin: str, lecture: Lecture | None, *, confiance: float | None = None,
        type_valeur: TypeValeur | None = None, devise: str | None = None, brut: str | None = None,
        separateur: str | None = None,
    ) -> ValeurSourcee | None:
        if lecture is None:
            return None
        from controldone.extract.valeurs import valeur_sourcee

        conf = confiance_mots(lecture) if confiance is None else confiance
        brut_lu = brut if brut is not None else lecture.texte
        tv = type_valeur or type_valeur_pour(chemin)
        a_lire = brut_lu
        if tv in (TypeValeur.montant, TypeValeur.masse, TypeValeur.decimal, TypeValeur.quantite, TypeValeur.entier):
            a_lire = texte_nombre(brut_lu)
        v = valeur_sourcee(
            type_document=self.type_document,
            chemin=chemin,
            brut=a_lire,
            document_id=self.document_id,
            page=lecture.page,
            extracteur=self.extracteur,
            methode=lecture.methode,
            confiance=conf,
            textes_pages=self.vue.textes,
            zone=lecture.zone,
            texte_contexte=lecture.contexte,
            type_valeur=type_valeur,
            separateur_decimal=separateur or self.vue.separateur_decimal,
            devise=devise,
            id_valeur=self.ids.nouveau(Prefixe.valeur) if self.ids is not None else None,
        )
        if a_lire != brut_lu:  # lecture corrigée : la valeur brute reste celle lue sur la page
            from controldone.extract.base import anchor

            v = v.model_copy(update={"valeur_brute": brut_lu, "ancree": anchor(brut_lu, self.vue.textes.get(lecture.page)),
                                     "confiance": min(v.confiance, 0.85)})
        if v.valeur is None:
            return v.model_copy(update={"confiance": min(v.confiance, 0.3)})
        if not v.ancree:
            v = v.model_copy(update={"confiance": min(v.confiance, 0.75)})
        return v


def separateur_masse(vue: VueDocument, texte: str) -> tuple[str | None, bool]:
    """Séparateur décimal pour lire une masse, et vrai si c'est une présomption.

    Les masses s'impriment au gramme près (3 décimales, §5.2) : sans indice du document, « 350.353 kg »
    est lu 350,353 kg (présomption : confiance réduite par l'appelant)."""
    if vue.separateur_decimal:
        return vue.separateur_decimal, False
    m = re.search(r"(?<![\d.,])\d{1,3}([.,])\d{3}(?![\d.,])", texte)
    if m:
        return m.group(1), True
    return None, False
