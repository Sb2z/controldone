"""Images des pages (vignettes, pleine page) et extraits de preuve, rendus depuis le coffre chiffré.

PDF : ``pypdfium2`` (licence permissive, D-005) ouvert **en mémoire** (jamais d'écriture du clair sur
disque) ; images : Pillow. Aucune exécution de JavaScript de PDF (pdfium ne l'exécute pas sans
formulaire actif). Toute erreur de rendu donne « pas d'image » (jamais bloquant). Un cache borné garde
les PNG produits (octets compressés seulement).
"""

from __future__ import annotations

import io
import logging
import threading
from collections import OrderedDict

__all__ = ["extrait_png", "page_png"]

log = logging.getLogger("controldone.services.vignettes")

_CACHE: OrderedDict[tuple, bytes | None] = OrderedDict()
_VERROU = threading.Lock()
_MAX = 128
_LARGEURS = {"mini": 220, "moyen": 640, "grand": 1240}


def _cache(cle: tuple, fabrique) -> bytes | None:
    with _VERROU:
        if cle in _CACHE:
            _CACHE.move_to_end(cle)
            return _CACHE[cle]
    valeur = fabrique()
    with _VERROU:
        _CACHE[cle] = valeur
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return valeur


def _image_page(contenu: bytes, mime: str, numero: int, largeur: int):
    """Image PIL RGB de la page ``numero`` (1-based) à ``largeur`` pixels."""
    if mime.startswith("image/"):
        from PIL import Image

        img = Image.open(io.BytesIO(contenu))
        if numero > 1:
            img.seek(numero - 1)
        img = img.convert("RGB")
        ratio = largeur / max(1, img.width)
        return img.resize((largeur, max(1, int(img.height * ratio))))
    if mime == "application/pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(contenu)
        try:
            if numero < 1 or numero > len(pdf):
                return None
            page = pdf[numero - 1]
            w, _h = page.get_size()
            img = page.render(scale=largeur / max(1.0, w)).to_pil().convert("RGB")
            page.close()
            return img
        finally:
            pdf.close()
    return None


def _png(img) -> bytes:
    sortie = io.BytesIO()
    img.save(sortie, format="PNG", optimize=True)
    return sortie.getvalue()


def page_png(cle_contenu: str, contenu_fn, mime: str, numero: int, taille: str = "mini") -> bytes | None:
    """PNG de la page. ``cle_contenu`` identifie le contenu (client + empreinte) pour le cache ;
    ``contenu_fn()`` lit les octets dans le coffre seulement si nécessaire."""
    largeur = _LARGEURS.get(taille, _LARGEURS["mini"])

    def fabriquer() -> bytes | None:
        try:
            img = _image_page(contenu_fn(), mime, numero, largeur)
            return _png(img) if img is not None else None
        except Exception as e:
            log.debug("rendu_page_en_erreur exception=%s", type(e).__name__)
            return None

    return _cache(("page", cle_contenu, numero, largeur), fabriquer)


def _zone_par_recherche(contenu: bytes, numero: int, valeur: str) -> tuple[float, float, float, float] | None:
    import pypdfium2 as pdfium

    v = " ".join(valeur.split())
    if len(v) < 2:
        return None
    pdf = pdfium.PdfDocument(contenu)
    try:
        page = pdf[numero - 1]
        largeur, hauteur = page.get_size()
        tp = page.get_textpage()
        for texte in dict.fromkeys([v, valeur.strip()]):
            occ = tp.search(texte, match_case=False).get_next()
            if occ is None:
                continue
            index, nombre = occ
            rects = [tp.get_rect(i) for i in range(tp.count_rects(index, nombre))]
            if rects:
                g, b = min(r[0] for r in rects), min(r[1] for r in rects)
                d, h = max(r[2] for r in rects), max(r[3] for r in rects)
                return (g / largeur, 1 - h / hauteur, d / largeur, 1 - b / hauteur)
    finally:
        pdf.close()
    return None


def extrait_png(cle_contenu: str, contenu_fn, mime: str, numero: int, *,
                zone: tuple[float, float, float, float] | None = None, valeur: str | None = None) -> bytes | None:
    """Rognage autour de la valeur lue (zone de la valeur sourcée, sinon recherche littérale dans la couche
    texte du PDF), valeur encadrée. ``None`` si la zone est introuvable."""

    def fabriquer() -> bytes | None:
        try:
            contenu = contenu_fn()
            z = zone
            if z is None and valeur and mime == "application/pdf":
                z = _zone_par_recherche(contenu, numero, valeur)
            if z is None:
                return None
            img = _image_page(contenu, mime, numero, 1240)
            if img is None:
                return None
            from PIL import ImageDraw

            x0, y0, x1, y1 = z
            cx = (x0 + x1) / 2
            demi = max((x1 - x0) / 2 + 0.12, 0.3)
            gx0, gx1 = max(0.0, cx - demi), min(1.0, cx + demi)
            gy0, gy1 = max(0.0, y0 - 0.045), min(1.0, y1 + 0.045)
            w, h = img.size
            boite = (int(gx0 * w), int(gy0 * h), int(gx1 * w), int(gy1 * h))
            if boite[2] - boite[0] < 10 or boite[3] - boite[1] < 10:
                return None
            rogne = img.crop(boite).copy()
            ImageDraw.Draw(rogne).rectangle(
                (int(x0 * w) - boite[0] - 4, int(y0 * h) - boite[1] - 4,
                 int(x1 * w) - boite[0] + 4, int(y1 * h) - boite[1] + 4), outline=(176, 96, 0), width=3)
            return _png(rogne)
        except Exception as e:
            log.debug("extrait_en_erreur exception=%s", type(e).__name__)
            return None

    return _cache(("extrait", cle_contenu, numero, zone, valeur), fabriquer)
