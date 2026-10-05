"""Prétraitement des images de pages scannées avant l'OCR (PIL seul, sans numpy : D-1404).

Fonctions pures sur des images PIL, appelées par ``ingest.pages._ocr_image`` dans le processus isolé de pages
(D-2601 à D-2606) :

- ``niveaux_de_gris`` : gris = **maximum** des canaux R, V, B. Le noir et le gris neutres sont inchangés ; une
  encre colorée claire ou moyenne (tampon rouge, écriture bleue) devient claire et tombe du côté du fond à la
  binarisation de Tesseract, alors que la luminance la gardait au niveau du texte ;
- ``retirer_traits`` : traits parasites rectilignes qui traversent toute la page (bandes de télécopie) ;
- ``debruiter`` : filtre médian 3 × 3 sur une page de télécopie (bitonale agrandie : points isolés, trous) ;
- ``etirer_contraste`` : étirement linéaire encre -> noir, fond -> blanc d'une page pâle ;
- ``coupure_deux_pages`` : feuille paysage portant deux pages portrait côte à côte (« 2 pages par feuille »).

Toutes travaillent en mode ``L`` et sont bornées en coût (opérations PIL en C, profils calculés sur une
réduction ou par ``resize`` BOX) : quelques dixièmes de seconde par page A4 à 300 dpi.
"""

from __future__ import annotations

from itertools import pairwise

__all__ = [
    "coupure_deux_pages",
    "debruiter",
    "etirer_contraste",
    "niveaux_de_gris",
    "page_telecopie",
    "retirer_traits",
]

#: Part minimale de la hauteur (de la largeur) couverte d'encre pour qu'une colonne (une rangée) soit un trait
#: parasite traversant la page. Un filet de tableau ou un cadre s'arrête aux marges (< 90 %).
PART_TRAIT = 0.92
#: Épaisseur maximale d'un trait parasite (pixels à 300 dpi) ; au-delà : bloc imprimé, laissé tel quel.
EPAISSEUR_MAX_TRAIT = 12
#: Télécopie : part maximale de demi-teintes parmi les pixels d'encre ; côté minimal (pixels) pour le médian.
PART_DEMI_TEINTES_FAX = 0.55
TAILLE_MIN_MEDIAN = 2000
#: Contraste : écart minimal encre/fond au-dessous duquel la page est étirée.
ECART_CONTRASTE = 150
#: Contraste : l'encre la plus foncée (centile 0,5 %) doit être plus claire que ce niveau (encre pâle). Une photo
#: mal éclairée (fond gris 180–200, encre 20–80) ou une compression JPEG lourde (encre ~100) ne sont pas
#: étirées : l'étirement y amplifie l'ombre et les artefacts (mesure D-2603).
ENCRE_PALE = 140
#: Gris par maximum des canaux : fond de page (médiane de luminance) au moins aussi clair (papier blanc scanné).
FOND_PAPIER = 215


def niveaux_de_gris(image):
    """Image ``L`` : maximum des canaux pour un scan en couleur sur papier blanc (encre colorée atténuée), sinon
    luminance. Une photo de document (fond gris ou coloré : bureau, ombre ; médiane de luminance < 215) garde la
    luminance : le maximum des canaux y efface le contraste entre la page et un fond brun (mesure D-2601)."""
    from PIL import ImageChops

    if image.mode == "L":
        return image
    if image.mode not in ("RGB", "RGBA", "CMYK", "P", "LA", "YCbCr"):
        return image.convert("L")
    rgb = image.convert("RGB")
    luminance = rgb.convert("L")
    if _centile(luminance.histogram(), 0.5) < FOND_PAPIER:
        return luminance
    r, v, b = rgb.split()
    return ImageChops.lighter(ImageChops.lighter(r, v), b)


def _centile(histogramme: list[int], q: float) -> int:
    total = sum(histogramme)
    cible = q * total
    cumul = 0
    for v, n in enumerate(histogramme):
        cumul += n
        if cumul >= cible and n:
            return v
    return 255


def _seuil_encre(gris) -> int:
    """Seuil encre/fond : milieu entre l'encre (centile 0,5 %) et le fond (médiane)."""
    h = gris.histogram()
    encre, fond = _centile(h, 0.005), _centile(h, 0.5)
    return max(1, min(220, (encre + fond) // 2))


def _masque_encre(gris, seuil: int):
    """Masque ``L`` : encre = 255, fond = 0."""
    return gris.point([255 if v < seuil else 0 for v in range(256)])


def _profil(masque, axe: str) -> list[float]:
    """Part d'encre par colonne (``axe='x'``) ou par rangée (``'y'``), 0–1, par réduction BOX (exacte)."""
    from PIL import Image

    w, h = masque.size
    if axe == "x":
        p = masque.resize((w, 1), Image.BOX)
        return [v / 255 for v in p.tobytes()]
    p = masque.resize((1, h), Image.BOX)
    return [v / 255 for v in p.tobytes()]


def _bandes(profil: list[float], seuil: float, epaisseur_max: int) -> list[tuple[int, int]]:
    """Suites d'indices consécutifs dont la valeur dépasse ``seuil`` (bornes incluses), minces seulement."""
    bandes = []
    debut = None
    for i, v in enumerate([*profil, 0.0]):
        if v >= seuil and debut is None:
            debut = i
        elif v < seuil and debut is not None:
            if i - debut <= epaisseur_max:
                bandes.append((debut, i - 1))
            debut = None
    return bandes


def retirer_traits(gris) -> tuple[object, int]:
    """Efface les traits minces qui traversent toute la page (colonne ou rangée presque entièrement encrée).

    Chaque pixel du trait reçoit le plus clair de ses deux voisins hors du trait (gauche/droite pour un trait
    vertical, dessus/dessous pour un trait horizontal) : un caractère que le trait traverse garde sa continuité
    (encre des deux côtés), le reste du trait devient fond. Rend l'image et le nombre de traits effacés."""
    from PIL import ImageChops

    w, h = gris.size
    if w < 50 or h < 50:
        return gris, 0
    masque = _masque_encre(gris, _seuil_encre(gris))
    verticaux = _bandes(_profil(masque, "x"), PART_TRAIT, EPAISSEUR_MAX_TRAIT)
    horizontaux = _bandes(_profil(masque, "y"), PART_TRAIT, EPAISSEUR_MAX_TRAIT)
    if not verticaux and not horizontaux:
        return gris, 0
    sortie = gris.copy()
    for x0, x1 in verticaux:
        g, d = max(0, x0 - 1), min(w - 1, x1 + 1)
        voisin = ImageChops.lighter(sortie.crop((g, 0, g + 1, h)), sortie.crop((d, 0, d + 1, h)))
        sortie.paste(voisin.resize((x1 - x0 + 1, h)), (x0, 0))
    for y0, y1 in horizontaux:
        haut, bas = max(0, y0 - 1), min(h - 1, y1 + 1)
        voisin = ImageChops.lighter(sortie.crop((0, haut, w, haut + 1)), sortie.crop((0, bas, w, bas + 1)))
        sortie.paste(voisin.resize((w, y1 - y0 + 1)), (0, y0))
    return sortie, len(verticaux) + len(horizontaux)


def page_telecopie(gris) -> bool:
    """Page bitonale agrandie (télécopie rendue à 300 dpi) : peu de demi-teintes parmi les pixels d'encre
    (bords nets, interpolation seulement) et assez de pixels (≥ 2 000 px de côté) pour que les traits des
    caractères fassent au moins 3 pixels.

    Un scan en niveaux de gris a ≥ 58 % de demi-teintes (48–207) parmi ses pixels non blancs (anticrénelage,
    grain) ; une télécopie rendue ≤ 50 %. Une image bitonale native en basse résolution (TIFF fax à 200 dpi)
    est exclue par la taille : un médian 3 × 3 y ronge les traits fins (mesure D-2602)."""
    if min(gris.size) < TAILLE_MIN_MEDIAN:
        return False
    h = gris.histogram()
    encre = sum(h[:208])
    if encre < 0.002 * gris.size[0] * gris.size[1]:
        return False
    return sum(h[48:208]) / encre < PART_DEMI_TEINTES_FAX


def debruiter(gris):
    """Filtre médian 3 × 3 sur une page de télécopie (points isolés, trous dans les traits) ; sinon inchangée."""
    from PIL import ImageFilter

    if not page_telecopie(gris):
        return gris, False
    return gris.filter(ImageFilter.MedianFilter(3)), True


def etirer_contraste(gris):
    """Étire une page pâle : encre (centile 0,5 %) -> 0, fond (médiane) -> 255. Inchangée si l'encre est foncée
    ou la page contrastée."""
    h = gris.histogram()
    encre, fond = _centile(h, 0.005), _centile(h, 0.5)
    if encre < ENCRE_PALE or fond - encre >= ECART_CONTRASTE or fond - encre < 25:
        return gris, False
    lut = [max(0, min(255, round((v - encre) * 255 / (fond - encre)))) for v in range(256)]
    return gris.point(lut), True


def _nettete(profil: list[float]) -> float:
    return sum((b - a) ** 2 for a, b in pairwise(profil))


def coupure_deux_pages(gris) -> int | None:
    """Abscisse (pixels) de la séparation d'une feuille « deux pages par feuille », ou ``None``.

    Conditions : feuille paysage (largeur ≥ 1,2 × hauteur) ; dans la bande centrale (40–60 % de la largeur), une
    gouttière sans texte (colonnes presque blanches sur ≥ 1,5 % de la largeur, ou filet séparateur mince bordé
    de blanc) ; de l'encre des deux côtés ; dans chaque moitié, des lignes de texte horizontales (profil des
    rangées plus net que celui des colonnes : une page tournée de 90° n'est pas coupée)."""
    from PIL import Image

    w, h = gris.size
    if w < 1.2 * h or h < 200:
        return None
    f = 800 / w
    petit = gris.resize((800, max(1, int(h * f))), Image.BOX) if f < 1 else gris
    pw, ph = petit.size
    masque = _masque_encre(petit, _seuil_encre(petit))
    colonnes = _profil(masque, "x")
    debut, fin = int(0.40 * pw), int(0.60 * pw)
    vide = [c < 0.004 for c in colonnes]
    filet = [c > 0.5 for c in colonnes]
    meilleure: tuple[int, int] | None = None  # (longueur, centre)
    i = debut
    while i < fin:
        if vide[i] or filet[i]:
            j = i
            while j < fin and (vide[j] or filet[j]):
                j += 1
            blancs = sum(vide[i:j])
            if blancs >= max(3, int(0.015 * pw)) and (meilleure is None or j - i > meilleure[0]):
                meilleure = (j - i, (i + j) // 2)
            i = j
        else:
            i += 1
    if meilleure is None:
        return None
    coupe = meilleure[1]
    for x0, x1 in ((0, coupe), (coupe, pw)):
        moitie = masque.crop((x0, 0, x1, ph))
        if moitie.histogram()[255] < 0.003 * moitie.size[0] * ph:
            return None
        if _nettete(_profil(moitie, "y")) <= _nettete(_profil(moitie, "x")):
            return None
    return round(coupe / pw * w)
