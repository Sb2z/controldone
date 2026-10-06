"""Rognages de page pour les preuves (SPEC §18.3 point 5, §6.2.9 ``extrait_image``).

Rendu des PDF avec ``pypdfium2`` (licence permissive, D-005). La zone vient de la valeur sourcée
(coordonnées relatives, origine en haut à gauche) ; à défaut, la valeur lue est recherchée littéralement
dans la couche texte de la page. Le rognage montre la ligne de la valeur avec un peu de contexte et
encadre la valeur. Toute erreur de rendu donne simplement « pas d'image » (jamais bloquant).
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache

__all__ = ["rogner", "vider_cache", "zone_par_recherche"]

log = logging.getLogger("controldone.rapport.images")

ECHELLE = 2.0  # 144 dpi
#: Plafond de pixels d'une page rendue pour un rognage (≈ A3 à 144 dpi) : une page au format aberrant (2 × 5 m,
#: zone maximale d'un PDF) réclamait sinon un bitmap de plusieurs gigaoctets, gardé de surcroît dans le cache
#: (D-1605, même défaut que RS-04 pour les vignettes).
MAX_PIXELS = 2 * 1684 * 2384
MARGE_VERTICALE = 0.045  # fraction de hauteur au-dessus et au-dessous de la zone
LARGEUR_MIN = 0.6  # fraction de largeur minimale du rognage


@lru_cache(maxsize=64)
def _page_image(chemin: str, numero: int):
    """Image PIL de la page (mise en cache) et dimensions en points.

    Une page rendue pèse ~9 Mo : ``generer_rapport`` vide ce cache en fin de rapport (``vider_cache``, D-1406)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(chemin)
    try:
        page = pdf[numero - 1]
        largeur, hauteur = page.get_size()
        img = page.render(scale=_echelle(largeur, hauteur)).to_pil().convert("RGB")
        page.close()
    finally:
        pdf.close()
    return img, largeur, hauteur


def _echelle(largeur: float, hauteur: float) -> float:
    """``ECHELLE``, réduite si la page rendue dépasserait ``MAX_PIXELS``."""
    surface = max(1.0, float(largeur)) * max(1.0, float(hauteur))
    if surface * ECHELLE * ECHELLE <= MAX_PIXELS:
        return ECHELLE
    return (MAX_PIXELS / surface) ** 0.5 * 0.9  # marge pour les arrondis au pixel


def vider_cache() -> None:
    """Libère les pages rendues (images de pièces client déchiffrées) gardées par ``_page_image``."""
    _page_image.cache_clear()


def zone_par_recherche(chemin: str, numero: int, valeur: str) -> tuple[float, float, float, float] | None:
    """Zone relative (x0, y0, x1, y1, origine en haut à gauche) de la première occurrence de ``valeur``
    dans la couche texte de la page ; ``None`` si absente."""
    import pypdfium2 as pdfium

    v = " ".join(valeur.split())
    if len(v) < 2:
        return None
    pdf = None
    try:
        pdf = pdfium.PdfDocument(chemin)
        page = pdf[numero - 1]
        largeur, hauteur = page.get_size()
        tp = page.get_textpage()
        for texte in dict.fromkeys([v, valeur.strip()]):
            cherche = tp.search(texte, match_case=False)
            occ = cherche.get_next()
            if occ is None:
                continue
            index, nombre = occ
            n = tp.count_rects(index, nombre)
            rects = [tp.get_rect(i) for i in range(n)]
            if not rects:
                continue
            g = min(r[0] for r in rects)
            b = min(r[1] for r in rects)
            d = max(r[2] for r in rects)
            h = max(r[3] for r in rects)
            return (g / largeur, 1 - h / hauteur, d / largeur, 1 - b / hauteur)
    except Exception as e:
        log.debug("recherche_zone_en_erreur exception=%s", type(e).__name__)
    finally:
        if pdf is not None:
            pdf.close()
    return None


def rogner(
    chemin: str | None,
    numero: int | None,
    *,
    zone: tuple[float, float, float, float] | None = None,
    valeur: str | None = None,
    type_mime: str | None = "application/pdf",
) -> bytes | None:
    """PNG du rognage autour de la valeur (ou ``None``)."""
    if not chemin or not numero:
        return None
    try:
        if type_mime and type_mime.startswith("image/"):
            from PIL import Image

            img = Image.open(chemin)
            if numero > 1:
                img.seek(numero - 1)
            if img.width * img.height > MAX_PIXELS:
                img.draft("RGB", (img.width // 4, img.height // 4))  # JPEG : décodage réduit
                ratio = (MAX_PIXELS / (img.width * img.height)) ** 0.5 * 0.9
                img = img.resize(
                    (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))), reducing_gap=2.0
                )
            img = img.convert("RGB")
        elif type_mime in (None, "application/pdf"):
            if zone is None and valeur:
                zone = zone_par_recherche(chemin, numero, valeur)
            img, _l, _h = _page_image(chemin, numero)
        else:
            return None
        if zone is None:
            return None
        from PIL import ImageDraw

        x0, y0, x1, y1 = zone
        cx = (x0 + x1) / 2
        demi = max((x1 - x0) / 2 + 0.12, LARGEUR_MIN / 2)
        gx0, gx1 = max(0.0, cx - demi), min(1.0, cx + demi)
        gy0, gy1 = max(0.0, y0 - MARGE_VERTICALE), min(1.0, y1 + MARGE_VERTICALE)
        w, h = img.size
        boite = (int(gx0 * w), int(gy0 * h), int(gx1 * w), int(gy1 * h))
        if boite[2] - boite[0] < 10 or boite[3] - boite[1] < 10:
            return None
        rogne = img.crop(boite).copy()
        dessin = ImageDraw.Draw(rogne)
        pad = 4
        dessin.rectangle(
            (
                int(x0 * w) - boite[0] - pad,
                int(y0 * h) - boite[1] - pad,
                int(x1 * w) - boite[0] + pad,
                int(y1 * h) - boite[1] + pad,
            ),
            outline=(196, 120, 0),
            width=3,
        )
        sortie = io.BytesIO()
        rogne.save(sortie, format="PNG")  # sans ``optimize`` : 3x plus rapide, même image (D-1406)
        return sortie.getvalue()
    except Exception as e:  # rendu impossible : pas d'image, jamais bloquant
        log.debug("rognage_en_erreur exception=%s", type(e).__name__)
        return None
