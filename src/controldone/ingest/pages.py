"""Fichier -> pages avec texte (SPEC §5.1, §6.2.5, §7.3, §20.3).

- PDF : texte natif (pdfplumber, mots positionnés). Le texte **invisible** (mode de rendu invisible,
  blanc sans fond sombre, micro-police) est retiré du texte de la page et gardé à part pour l'audit
  (§20.2). Qualité : ``natif`` si ≥ 85 % des caractères forment des mots plausibles ou des nombres ;
  sinon OCR et l'on garde la meilleure des deux sources (``natif_faible`` si le natif l'emporte).
- OCR : rendu pypdfium2 à 300 dpi, orientation (OSD + essai 90/180/270), désinclinaison, Tesseract
  ``fra+eng``, mots et confiances conservés, ``score_ocr``.
- Images PNG/JPEG/TIFF multipage : OCR de chaque image.
- Tableurs XLSX/ODS et CSV : une page par feuille, cellules jointes par `` | `` ligne par ligne.
- XML : une page, texte brut conservé. Corps de courriel : une page de texte.

Le travail sur les octets du fichier (analyse PDF, rendu, OCR) tourne dans un **processus séparé** avec
limite de temps et de mémoire (``_worker``). Rien n'est persisté ici, sauf le cache disque facultatif
(clé : ``sha256 + n° page + version``).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from controldone.ids import IdGenerator, Prefixe, nouvel_id
from controldone.model import Fichier, Page
from controldone.model.enums import QualiteTexte

from .sniff import MIME_CSV, MIME_EML, MIME_ODS, MIME_PDF, MIME_TEXTE, MIME_XLSX, MIME_XML, decoder_texte
from .texte import Ligne, Mot, PageText, construire_lignes, score_texte

__all__ = [
    "VERSION_PAGES",
    "CachePagesDisque",
    "OptionsPages",
    "PageExtraite",
    "extraire_pages",
    "extraire_pages_local",
    "ocr_disponible",
    "version_ocr",
]

#: Version de l'algorithme de pages (entre dans la clé d'idempotence §7 étape 2 avec Tesseract).
VERSION_PAGES = "1.0.1"

SEUIL_NATIF = 0.85
SEUIL_NATIF_FAIBLE = 0.5
MIN_CARACTERES_NATIF = 25
SEUIL_ILLISIBLE_OCR = 0.45


@dataclass(frozen=True)
class OptionsPages:
    ocr: bool = True
    dpi: int = 300
    langues: str = "fra+eng"
    #: Forcer l'OCR même si le texte natif est bon (diagnostic).
    forcer_ocr: bool = False
    #: Temps alloué au processus isolé : ``base + par_page × pages``.
    timeout_base_s: float = 30.0
    timeout_par_page_s: float = 60.0
    memoire_mo: int = 3072
    #: Exécution dans un processus séparé (recommandé ; ``False`` pour déboguer).
    isoler: bool = True
    cache_dir: str | None = None
    max_pages: int = 300

    def empreinte(self) -> str:
        cle = f"{self.dpi}|{self.langues}|{self.ocr}|{self.forcer_ocr}"
        return hashlib.sha256(cle.encode()).hexdigest()[:8]


@dataclass
class PageExtraite:
    """Page du modèle (persistée par l'assemblage) + texte positionné (pour les extracteurs)."""

    page: Page
    texte: PageText


@lru_cache(maxsize=1)
def version_ocr() -> str:
    """Version de Tesseract (``indisponible`` si absent)."""
    try:
        import pytesseract

        return str(pytesseract.get_tesseract_version()).split()[0]
    except Exception:
        return "indisponible"


def ocr_disponible() -> bool:
    return version_ocr() != "indisponible"


def _cle_version(options: OptionsPages) -> str:
    return f"{VERSION_PAGES}+tess{version_ocr()}+{options.empreinte()}"


# --- cache disque -------------------------------------------------------------------------------------


class CachePagesDisque:
    """Cache ``PageText`` sur disque : un fichier JSON par (sha256, page, version).

    Le texte y est **en clair** (fichiers 0600, répertoires 0700) : réservé au banc et au développement ; le
    découpeur du service l'ignore en production (``CONTROLDONE_ENV=prod``, revue de sécurité RS-03)."""

    def __init__(self, dossier: str | Path) -> None:
        self.dossier = Path(dossier)

    def _chemin(self, sha: str, version: str, nom: str) -> Path:
        v = hashlib.sha256(version.encode()).hexdigest()[:12]
        return self.dossier / sha[:2] / f"{sha}_{v}_{nom}.json"

    def lire(self, sha: str, version: str) -> list[PageText] | None:
        idx = self._chemin(sha, version, "index")
        try:
            n = json.loads(idx.read_text("utf-8"))["pages"]
            return [PageText.from_dict(json.loads(self._chemin(sha, version, f"p{i}").read_text("utf-8")))
                    for i in range(1, n + 1)]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def ecrire(self, sha: str, version: str, pages: list[PageText]) -> None:
        try:
            for p in pages:
                c = self._chemin(sha, version, f"p{p.numero}")
                c.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                _ecrire_atomique(c, json.dumps(p.to_dict(), ensure_ascii=False))
            _ecrire_atomique(self._chemin(sha, version, "index"), json.dumps({"pages": len(pages)}))
        except OSError:
            pass  # le cache est une optimisation


def _ecrire_atomique(chemin: Path, contenu: str) -> None:
    """Écriture atomique, fichier privé (0600) : le cache contient du texte de document en clair."""
    tmp = chemin.with_suffix(f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(contenu)
    os.chmod(tmp, 0o600)
    tmp.replace(chemin)


# --- API publique -------------------------------------------------------------------------------------


def extraire_pages(
    contenu: bytes,
    *,
    fichier: Fichier | None = None,
    type_mime: str | None = None,
    options: OptionsPages | None = None,
    ids: IdGenerator | None = None,
) -> list[PageExtraite]:
    """``Fichier`` -> ``Page`` avec texte. Fonction pure (hors cache disque facultatif).

    Ne lève pas pour un fichier difficile : une page illisible porte ``qualite_texte = illisible``.
    """
    opts = options or OptionsPages()
    mime = type_mime or (fichier.type_mime if fichier else None)
    if mime is None:
        from .sniff import detecter_type

        mime = detecter_type(contenu)
    sha = fichier.sha256 if fichier else hashlib.sha256(contenu).hexdigest()
    version = _cle_version(opts)
    cache = CachePagesDisque(opts.cache_dir) if opts.cache_dir else None
    textes = cache.lire(sha, version) if cache else None
    if textes is None:
        if opts.isoler:
            n_pages = fichier.nombre_pages if fichier and fichier.nombre_pages else None
            textes = _extraire_isole(contenu, mime, opts, n_pages)
        else:
            textes = extraire_pages_local(contenu, mime, opts)
        if cache and textes and not any("timeout" in a for p in textes for a in p.avertissements):
            cache.ecrire(sha, version, textes)
    fid = fichier.id if fichier else "fic_inconnu"
    sortie = []
    for t in textes:
        pid = ids.nouveau(Prefixe.page) if ids is not None else nouvel_id(Prefixe.page)
        page = Page(
            id=pid,
            client_id=fichier.client_id if fichier else None,
            fichier_id=fid,
            numero=t.numero,
            rotation_appliquee=t.rotation,
            qualite_texte=t.qualite,
            score_ocr=None if t.score_ocr is None else round(min(1.0, max(0.0, t.score_ocr)), 4),
            texte=t.texte,
            sha256_texte=hashlib.sha256(t.texte.encode("utf-8")).hexdigest(),
            feuille=t.feuille,
            largeur=t.largeur,
            hauteur=t.hauteur,
        )
        sortie.append(PageExtraite(page=page, texte=t))
    return sortie


def _extraire_isole(contenu: bytes, mime: str, opts: OptionsPages, n_pages: int | None = None) -> list[PageText]:
    """Exécute ``extraire_pages_local`` dans un processus séparé (temps et mémoire bornés)."""
    n_estime = n_pages or _estimer_pages(contenu, mime)
    timeout = opts.timeout_base_s + opts.timeout_par_page_s * max(1, n_estime)
    with tempfile.TemporaryDirectory(prefix="cdo_pages_") as tmp:
        entree = Path(tmp) / "entree.bin"
        entree.write_bytes(contenu)
        sortie = Path(tmp) / "sortie.json"
        req = {"entree": str(entree), "sortie": str(sortie), "mime": mime,
               "options": {**asdict(opts), "isoler": False, "cache_dir": None}}
        env = {**os.environ, "OMP_THREAD_LIMIT": "1", "OPENBLAS_NUM_THREADS": "1"}
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "controldone.ingest._worker"],
                input=json.dumps(req).encode(),
                capture_output=True,
                timeout=timeout,
                env=env,
                preexec_fn=_limiteur_memoire(opts.memoire_mo) if os.name == "posix" else None,
                check=False,
            )
            if proc.returncode == 0 and sortie.exists():
                data = json.loads(sortie.read_text("utf-8"))
                return [PageText.from_dict(d) for d in data["pages"]]
            motif = f"processus_pages_code_{proc.returncode}"
        except subprocess.TimeoutExpired:
            motif = "timeout"
    # Échec ou délai dépassé : nouvel essai sans OCR (texte natif seulement), puis pages illisibles.
    if opts.ocr:
        pages = _extraire_isole(contenu, mime, replace(opts, ocr=False, timeout_par_page_s=5.0), n_pages)
        for p in pages:
            p.avertissements.append(f"ocr_abandonne:{motif}")
        return pages
    return [_page_illisible(i, motif) for i in range(1, max(1, n_estime) + 1)]


def _limiteur_memoire(memoire_mo: int):
    def _f():  # exécuté dans le processus enfant
        try:
            import resource

            octets = memoire_mo * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (octets, octets))
        except (ImportError, ValueError, OSError):
            pass

    return _f


def _estimer_pages(contenu: bytes, mime: str) -> int:
    if mime == MIME_PDF:
        return max(1, len(re.findall(rb"/Type\s*/Page[^s]", contenu)))
    if mime == "image/tiff":
        try:
            from PIL import Image

            with Image.open(io.BytesIO(contenu)) as im:
                return max(1, int(getattr(im, "n_frames", 1)))
        except Exception:
            return 1
    return 1


def _page_illisible(numero: int, motif: str, **kw) -> PageText:
    return PageText(numero=numero, texte="", qualite=QualiteTexte.illisible, source="aucune",
                    avertissements=[motif], **kw)


def extraire_pages_local(contenu: bytes, mime: str, options: OptionsPages | None = None) -> list[PageText]:
    """Extraction dans le processus courant (utilisée par le processus isolé)."""
    opts = options or OptionsPages()
    if mime == MIME_PDF:
        return _pages_pdf(contenu, opts)
    if mime.startswith("image/"):
        return _pages_image(contenu, opts)
    if mime == MIME_XLSX:
        return _pages_xlsx(contenu)
    if mime == MIME_ODS:
        return _pages_ods(contenu)
    if mime == MIME_CSV:
        return [_page_csv(contenu)]
    if mime == MIME_XML:
        return [_page_texte_brut(contenu, "xml")]
    if mime in (MIME_TEXTE, MIME_EML) or mime.startswith("text/"):
        return [_page_texte_brut(contenu, "texte")]
    return [_page_illisible(1, "type_non_lu")]


# --- PDF : texte natif ----------------------------------------------------------------------------------


def _couleur_blanche(c) -> bool:
    if c is None:
        return False
    if isinstance(c, (int, float)):
        c = (c,)
    try:
        vals = [float(x) for x in c]
    except (TypeError, ValueError):
        return False
    if len(vals) == 1:
        return vals[0] >= 0.95
    if len(vals) == 3:
        return all(v >= 0.95 for v in vals)
    if len(vals) == 4:
        return all(v <= 0.05 for v in vals)
    return False


def _fond_sombre(char: dict, rects: list[dict], images: list[dict]) -> bool:
    cx = (char["x0"] + char["x1"]) / 2
    cy = (char["top"] + char["bottom"]) / 2
    for r in rects:
        if r.get("fill") and not _couleur_blanche(r.get("non_stroking_color")) and \
                r["x0"] <= cx <= r["x1"] and r["top"] <= cy <= r["bottom"]:
            return True
    return any(im["x0"] <= cx <= im["x1"] and im["top"] <= cy <= im["bottom"] for im in images)


def _caracteres_invisibles(pdfium_page) -> list[tuple[float, float, float, float]]:
    """Boîtes (x0, top, x1, bottom, en points depuis le haut) des caractères en mode de rendu invisible."""
    import pypdfium2.raw as raw

    boites: list[tuple[float, float, float, float]] = []
    try:
        tp = pdfium_page.get_textpage()
    except Exception:
        return boites
    hauteur = pdfium_page.get_height()
    try:
        n = raw.FPDFText_CountChars(tp.raw)
        import ctypes

        for i in range(n):
            obj = raw.FPDFText_GetTextObject(tp.raw, i)
            if not obj:
                continue
            if raw.FPDFTextObj_GetTextRenderMode(obj) != raw.FPDF_TEXTRENDERMODE_INVISIBLE:
                continue
            g, d, b, h = (ctypes.c_double(), ctypes.c_double(), ctypes.c_double(), ctypes.c_double())
            if raw.FPDFText_GetCharBox(tp.raw, i, g, d, b, h):
                # boîte étendue à la hauteur de la police (la boîte d'un « . » est minuscule)
                corps = float(raw.FPDFText_GetFontSize(tp.raw, i) or 0) or (h.value - b.value)
                ox, oy = ctypes.c_double(), ctypes.c_double()
                base = oy.value if raw.FPDFText_GetCharOrigin(tp.raw, i, ox, oy) else b.value
                haut = max(h.value, base + corps)
                bas = min(b.value, base - 0.3 * corps)
                boites.append((g.value - 1, hauteur - haut - 1, d.value + 1, hauteur - bas + 1))
    finally:
        tp.close()
    return boites


def _dans(boites, char) -> bool:
    cx = (char["x0"] + char["x1"]) / 2
    cy = (char["top"] + char["bottom"]) / 2
    return any(x0 <= cx <= x1 and t <= cy <= b for x0, t, x1, b in boites)


def _texte_natif(page, pdfium_page) -> tuple[list[Ligne], str, float, float]:
    """Lignes visibles, texte masqué, largeur, hauteur."""
    largeur, hauteur = float(page.width), float(page.height)
    rects = page.rects
    images = page.images
    invisibles = _caracteres_invisibles(pdfium_page) if pdfium_page is not None else []

    def cache(obj) -> bool:
        if obj.get("object_type") != "char":
            return False
        if (obj.get("size") or 0) < 2.0:
            return True
        if _couleur_blanche(obj.get("non_stroking_color")) and not _fond_sombre(obj, rects, images):
            return True
        return bool(invisibles) and _dans(invisibles, obj)

    visible = page.filter(lambda o: not cache(o))
    masque = page.filter(lambda o: o.get("object_type") == "char" and cache(o))
    try:
        texte_masque = masque.extract_text() or ""
    except Exception:
        texte_masque = ""
    mots_bruts = visible.extract_words(x_tolerance=1.5, y_tolerance=2.5, keep_blank_chars=False,
                                       use_text_flow=False, extra_attrs=["size"])
    mots = []
    for w in mots_bruts:
        # Glyphe d'espace fine sans correspondance Unicode (police sous-ensemble) lu « \x00 » entre deux
        # chiffres : c'est un séparateur de milliers imprimé (« 1 405,44 »), restitué en espace fine.
        t = re.sub(r"(?<=\d)\x00(?=\d)", "\u202f", w["text"])
        if not t.strip():
            continue
        mots.append(Mot(texte=t, x0=w["x0"] / largeur, y0=w["top"] / hauteur, x1=w["x1"] / largeur,
                        y1=w["bottom"] / hauteur, confiance=None, taille=round(float(w.get("size") or 0), 2)))
    return construire_lignes(mots), texte_masque, largeur, hauteur


def _pages_pdf(contenu: bytes, opts: OptionsPages) -> list[PageText]:
    import pdfplumber
    import pypdfium2 as pdfium

    try:
        doc_pdfium = pdfium.PdfDocument(contenu)
    except Exception:
        doc_pdfium = None
    sortie: list[PageText] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(contenu))
    except Exception:
        if doc_pdfium is None:
            return [_page_illisible(1, "pdf_illisible")]
        pdf = None
    try:
        n = len(pdf.pages) if pdf is not None else len(doc_pdfium)
        n = min(n, opts.max_pages)
        for i in range(n):
            numero = i + 1
            lignes: list[Ligne] = []
            texte_masque = ""
            largeur = hauteur = None
            avert: list[str] = []
            try:
                pp = doc_pdfium[i] if doc_pdfium is not None else None
            except Exception:
                pp = None
            if pdf is not None:
                try:
                    lignes, texte_masque, largeur, hauteur = _texte_natif(pdf.pages[i], pp)
                except Exception:
                    avert.append("texte_natif_illisible")
            texte = "\n".join(li.texte for li in lignes)
            nb = sum(1 for c in texte if not c.isspace())
            score = score_texte(texte) if nb else 0.0
            natif = PageText(numero=numero, texte=texte, lignes=lignes, qualite=QualiteTexte.natif,
                             source="natif", score_natif=round(score, 4), largeur=largeur, hauteur=hauteur,
                             texte_masque=texte_masque, avertissements=avert)
            if nb >= MIN_CARACTERES_NATIF and score >= SEUIL_NATIF and not opts.forcer_ocr:
                sortie.append(natif)
                continue
            if not opts.ocr or pp is None or not ocr_disponible():
                if nb >= MIN_CARACTERES_NATIF and score >= SEUIL_NATIF_FAIBLE:
                    natif.qualite = QualiteTexte.natif_faible
                elif nb > 0 and score >= SEUIL_NATIF:
                    natif.qualite = QualiteTexte.natif_faible  # peu de texte, mais propre
                else:
                    natif.qualite = QualiteTexte.illisible
                    natif.avertissements.append("ocr_indisponible" if opts.ocr else "ocr_desactive")
                sortie.append(natif)
                continue
            try:
                image = pp.render(scale=opts.dpi / 72).to_pil()
                ocr = _ocr_image(image, opts, numero)
            except Exception as e:  # rendu impossible
                ocr = _page_illisible(numero, f"rendu_impossible:{type(e).__name__}")
            ocr.largeur, ocr.hauteur, ocr.texte_masque = largeur, hauteur, texte_masque
            ocr.score_natif = natif.score_natif
            sortie.append(_meilleure(natif, ocr, nb))
    finally:
        if pdf is not None:
            pdf.close()
        if doc_pdfium is not None:
            doc_pdfium.close()
    return sortie or [_page_illisible(1, "pdf_sans_page")]


def _meilleure(natif: PageText, ocr: PageText, nb_natif: int) -> PageText:
    """§7.3 : garder la meilleure des deux sources par page."""
    q_natif = (natif.score_natif or 0.0) if nb_natif >= MIN_CARACTERES_NATIF else 0.0
    q_ocr = (ocr.score_ocr or 0.0) * score_texte(ocr.texte) if ocr.texte.strip() else 0.0
    if q_natif >= SEUIL_NATIF_FAIBLE and q_natif >= q_ocr:
        natif.qualite = QualiteTexte.natif_faible
        natif.score_ocr = ocr.score_ocr
        return natif
    if q_natif > 0 and nb_natif > 0 and natif.score_natif and natif.score_natif >= SEUIL_NATIF \
            and ocr.qualite is QualiteTexte.illisible:
        natif.qualite = QualiteTexte.natif_faible
        return natif
    return ocr


# --- OCR ------------------------------------------------------------------------------------------------


def _osd_rotation(image) -> int | None:
    """Rotation à appliquer (0/90/180/270) d'après l'OSD de Tesseract ; ``None`` sans verdict fiable.

    Réglage par défaut d'abord (plus fiable), puis avec un seuil de caractères abaissé (pages peu denses).
    Une page en paysage (scan pivoté) accepte un verdict 90/270 de moindre confiance."""
    import pytesseract

    paysage = image.size[0] > image.size[1]
    for config in ("--psm 0", "--psm 0 -c min_characters_to_try=10"):
        try:
            osd = pytesseract.image_to_osd(image, config=config, output_type=pytesseract.Output.DICT, timeout=60)
        except Exception:
            continue
        rot = int(osd.get("rotate", 0)) % 360
        conf = float(osd.get("orientation_conf", 0.0))
        if rot in (90, 180, 270) and (conf >= 1.0 or (paysage and rot in (90, 270) and conf >= 0.5)):
            return rot
        if conf >= 1.0:
            return 0
    return None


def _angle_inclinaison(image) -> float:
    """Angle (degrés, sens trigonométrique) qui maximise la netteté du profil horizontal."""
    import numpy as np
    from PIL import Image

    petit = image.convert("L")
    w, h = petit.size
    facteur = 1000 / max(w, h)
    if facteur < 1:
        petit = petit.resize((max(1, int(w * facteur)), max(1, int(h * facteur))))
    tableau = np.asarray(petit)
    seuil = min(200, int(tableau.mean() * 0.8))
    binaire = Image.fromarray(((tableau < seuil) * 255).astype("uint8"))
    if (np.asarray(binaire) > 0).mean() < 0.002:
        return 0.0

    def score(angle: float) -> float:
        r = np.asarray(binaire.rotate(angle, resample=Image.NEAREST, expand=False, fillcolor=0), dtype=np.float32)
        profil = r.sum(axis=1)
        return float(((profil[1:] - profil[:-1]) ** 2).sum())

    meilleur = max((a / 2 for a in range(-10, 11)), key=score)
    fin = max((meilleur + a / 10 for a in range(-5, 6)), key=score)
    return round(fin, 2)


def _ocr_brut(image, opts: OptionsPages) -> tuple[list[Mot], float]:
    import pytesseract

    data = pytesseract.image_to_data(image, lang=opts.langues, config="--psm 3",
                                     output_type=pytesseract.Output.DICT, timeout=max(30, int(opts.timeout_par_page_s)))
    w, h = image.size
    mots: list[Mot] = []
    poids = 0
    somme = 0.0
    for i, t in enumerate(data["text"]):
        t = (t or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not t or conf < 0:
            continue
        x, y, ww, hh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        mots.append(Mot(texte=t, x0=x / w, y0=y / h, x1=(x + ww) / w, y1=(y + hh) / h,
                        confiance=round(conf / 100, 4), taille=round(hh / h, 5)))
        somme += conf / 100 * len(t)
        poids += len(t)
    return mots, (somme / poids if poids else 0.0)


def _ocr_image(image, opts: OptionsPages, numero: int) -> PageText:
    from PIL import Image

    # Tesseract multi-fils se dégrade fortement sous charge (plusieurs pages en parallèle) : un fil par OCR.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")

    image = image.convert("L")
    rotation = _osd_rotation(image)
    if rotation:
        image = image.rotate(-rotation, expand=True, fillcolor=255)
    angle = 0.0
    try:
        angle = _angle_inclinaison(image)
    except Exception:
        angle = 0.0
    if abs(angle) >= 0.3:
        image = image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
    mots, score = _ocr_brut(image, opts)
    rot_finale = rotation or 0
    if rotation is None and (score < 0.6 or len(mots) < 5):
        # OSD sans verdict : essai des trois autres orientations, on garde la meilleure confiance.
        meilleurs = (mots, score, 0, image)
        for essai in (180, 90, 270):
            im2 = image.rotate(-essai, expand=True, fillcolor=255)
            m2, s2 = _ocr_brut(im2, opts)
            if s2 * score_texte(" ".join(x.texte for x in m2)) > meilleurs[1] * score_texte(
                    " ".join(x.texte for x in meilleurs[0])) + 0.1:
                meilleurs = (m2, s2, essai, im2)
        mots, score, rot_finale, image = meilleurs
    lignes = construire_lignes(mots)
    texte = "\n".join(li.texte for li in lignes)
    qualite = QualiteTexte.ocr
    if not texte.strip() or score < SEUIL_ILLISIBLE_OCR or score_texte(texte) < 0.4:
        qualite = QualiteTexte.illisible
    return PageText(numero=numero, texte=texte, lignes=lignes, qualite=qualite, source="ocr",
                    score_ocr=round(score, 4), rotation=rot_finale, desinclinaison=angle)


def _pages_image(contenu: bytes, opts: OptionsPages) -> list[PageText]:
    from PIL import Image, ImageSequence

    sortie: list[PageText] = []
    try:
        im = Image.open(io.BytesIO(contenu))
        cadres = [c.copy() for c in ImageSequence.Iterator(im)][: opts.max_pages]
    except Exception:
        return [_page_illisible(1, "image_illisible")]
    for i, cadre in enumerate(cadres, start=1):
        if cadre.mode in ("RGBA", "LA", "P"):
            fond = Image.new("RGB", cadre.size, (255, 255, 255))
            cadre = cadre.convert("RGBA")
            fond.paste(cadre, mask=cadre.split()[-1])
            cadre = fond
        if not opts.ocr or not ocr_disponible():
            sortie.append(_page_illisible(i, "ocr_indisponible" if opts.ocr else "ocr_desactive",
                                          largeur=float(cadre.size[0]), hauteur=float(cadre.size[1])))
            continue
        dpi = cadre.info.get("dpi", (0, 0))[0] or 0
        if dpi and dpi < 150:  # agrandir une image basse résolution avant l'OCR
            f = min(3.0, 300 / dpi)
            cadre = cadre.resize((int(cadre.size[0] * f), int(cadre.size[1] * f)))
        try:
            p = _ocr_image(cadre, opts, i)
        except Exception as e:
            p = _page_illisible(i, f"ocr_echec:{type(e).__name__}")
        p.largeur, p.hauteur = float(cadre.size[0]), float(cadre.size[1])
        sortie.append(p)
    return sortie or [_page_illisible(1, "image_vide")]


# --- tableurs, CSV, XML, texte ----------------------------------------------------------------------


def _decimales_format(fmt: str | None) -> int | None:
    if not fmt or fmt == "General":
        return None
    m = re.search(r"0\.(0+)", fmt)
    if m:
        return len(m.group(1))
    if re.search(r"(^|[^.])0(?![.0])", fmt) or "#,##0" in fmt:
        return 0
    return None


def _cellule_texte(v, fmt: str | None = None) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "VRAI" if v else "FAUX"
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == time(0) else v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float, Decimal)):
        try:
            d = Decimal(repr(v)) if isinstance(v, float) else Decimal(v)
        except InvalidOperation:
            return str(v)
        n = _decimales_format(fmt)
        if n is not None and "%" not in (fmt or ""):
            d = d.quantize(Decimal(1).scaleb(-n)) if n else d.quantize(Decimal(1))
        s = format(d, "f")
        if isinstance(v, float) and n is None and s.endswith(".0"):
            s = s[:-2]
        return s
    return str(v).replace("\r", " ").replace("\n", " ").strip()


def _page_grille(numero: int, lignes_cellules: list[list[str]], *, source: str, feuille: str | None,
                 texte_brut: str | None = None) -> PageText:
    """Page à partir d'une grille de cellules : texte stable (cellules non vides jointes par `` | ``),
    mots positionnés sur une grille régulière."""
    lignes_cellules = [r for r in lignes_cellules]
    while lignes_cellules and not any(c for c in lignes_cellules[-1]):
        lignes_cellules.pop()
    nrows = max(1, len(lignes_cellules))
    ncols = max([len(r) for r in lignes_cellules] + [1])
    lignes: list[Ligne] = []
    for r, cellules in enumerate(lignes_cellules):
        mots = []
        for c, val in enumerate(cellules):
            if not val:
                continue
            mots.append(Mot(texte=val, x0=c / ncols, y0=r / nrows, x1=(c + 1) / ncols, y1=(r + 1) / nrows))
        if mots:
            lignes.append(Ligne(texte=" | ".join(m.texte for m in mots), mots=tuple(mots)))
    texte = texte_brut if texte_brut is not None else "\n".join(li.texte for li in lignes)
    return PageText(numero=numero, texte=texte, lignes=lignes, qualite=QualiteTexte.natif, source=source,
                    score_natif=1.0, feuille=feuille)


def _pages_xlsx(contenu: bytes) -> list[PageText]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
    except Exception:
        return [_page_illisible(1, "tableur_illisible")]
    sortie = []
    try:
        for i, ws in enumerate(wb.worksheets, start=1):
            grille: list[list[str]] = []
            for row in ws.iter_rows():
                grille.append([_cellule_texte(getattr(c, "value", None), getattr(c, "number_format", None))
                               for c in row])
                if len(grille) > 100_000:
                    break
            sortie.append(_page_grille(i, grille, source="tableur", feuille=ws.title))
    finally:
        wb.close()
    return sortie or [_page_illisible(1, "tableur_vide")]


_NS_ODS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}


def _pages_ods(contenu: bytes) -> list[PageText]:
    from lxml import etree

    try:
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            xml = z.read("content.xml")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        racine = etree.fromstring(xml, parser)
    except Exception:
        return [_page_illisible(1, "tableur_illisible")]
    t, o = "{{{}}}".format(_NS_ODS["table"]), "{{{}}}".format(_NS_ODS["office"])
    sortie = []
    for i, table in enumerate(racine.iter(f"{t}table"), start=1):
        grille: list[list[str]] = []
        for row in table.iter(f"{t}table-row"):
            cellules: list[str] = []
            for cell in row:
                if cell.tag not in (f"{t}table-cell", f"{t}covered-table-cell"):
                    continue
                rep = min(int(cell.get(f"{t}number-columns-repeated", "1")), 1000)
                vt = cell.get(f"{o}value-type")
                if vt in ("float", "currency", "percentage"):
                    val = cell.get(f"{o}value", "")
                elif vt == "date":
                    val = (cell.get(f"{o}date-value") or "")[:10]
                else:
                    val = " ".join("".join(p.itertext()) for p in cell.iter("{{{}}}p".format(_NS_ODS["text"]))).strip()
                cellules.extend([val] * (rep if val else min(rep, 50)))
            while cellules and not cellules[-1]:
                cellules.pop()
            rep_l = min(int(row.get(f"{t}number-rows-repeated", "1")), 1000 if cellules else 1)
            grille.extend([cellules] * rep_l)
        sortie.append(_page_grille(i, grille, source="tableur", feuille=table.get(f"{t}name")))
    return sortie or [_page_illisible(1, "tableur_vide")]


def _page_csv(contenu: bytes) -> PageText:
    import csv

    texte = decoder_texte(contenu)
    if texte is None:
        return _page_illisible(1, "csv_illisible")
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    lignes = [li for li in texte.split("\n")]
    try:
        dialecte = csv.Sniffer().sniff("\n".join(lignes[:20]), delimiters=";,\t|")
        grille = [[c.strip() for c in r] for r in csv.reader(lignes, dialecte)]
    except csv.Error:
        grille = [[li] for li in lignes]
    p = _page_grille(1, grille, source="csv", feuille=None, texte_brut=texte.rstrip("\n"))
    return p


def _page_texte_brut(contenu: bytes, source: str) -> PageText:
    texte = decoder_texte(contenu)
    if texte is None:
        try:
            texte = contenu.decode("utf-8", "replace")
        except Exception:
            return _page_illisible(1, "texte_illisible")
    texte = texte.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lignes_txt = texte.split("\n")
    n = max(1, len(lignes_txt))
    lignes = []
    for r, li in enumerate(lignes_txt):
        mots = []
        largeur_max = max(1, max((len(x) for x in lignes_txt), default=1))
        for m in re.finditer(r"\S+", li):
            mots.append(Mot(texte=m.group(), x0=m.start() / largeur_max, y0=r / n,
                            x1=min(1.0, m.end() / largeur_max), y1=(r + 1) / n))
        if mots:
            lignes.append(Ligne(texte=li.strip(), mots=tuple(mots)))
    return PageText(numero=1, texte=texte, lignes=lignes, qualite=QualiteTexte.natif, source=source,
                    score_natif=1.0)


__all__ += ["Ligne", "Mot", "PageText"]
