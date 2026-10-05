"""Prétraitement OCR des pages scannées (D-2601 à D-2606) : images synthétiques générées dans les tests.

Tous les textes sont fictifs (marqués FICTIF)."""

from __future__ import annotations

import io
import random

import fabriques as fab
import pytest
from PIL import Image, ImageChops, ImageDraw

from controldone.ingest import OptionsPages, extraire_pages, ocr_disponible
from controldone.ingest import pretraitement as pt
from controldone.ingest.pages import REGLAGES_OCR, _pretraiter

LOCAL = OptionsPages(isoler=False)
ocr = pytest.mark.skipif(not ocr_disponible(), reason="Tesseract absent")


def _page_texte(w: int = 1200, h: int = 1700, lignes: int = 30, gris: int = 0) -> Image.Image:
    """Page « portrait » : lignes de texte horizontales (rectangles d'encre hachés comme des mots)."""
    im = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(im)
    for i in range(lignes):
        y = 100 + i * 45
        x = 80
        while x < w - 200:
            n = 30 + (i * 37 + x) % 90
            d.rectangle((x, y, x + n, y + 18), fill=gris)
            x += n + 25
    return im


def _scan(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, format="PNG", dpi=(200, 200))
    return b.getvalue()


# --- niveaux de gris : encre colorée atténuée (D-2601) --------------------------------------------------------


def test_gris_max_attenue_encre_coloree_garde_le_noir():
    im = Image.new("RGB", (200, 20), (255, 255, 255))  # papier blanc (fond majoritaire)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 9, 19), fill=(0, 0, 0))  # texte noir
    d.rectangle((10, 0, 19, 19), fill=(90, 90, 90))  # texte gris
    d.rectangle((20, 0, 29, 19), fill=(200, 120, 120))  # tampon rouge
    d.rectangle((30, 0, 39, 19), fill=(90, 120, 165))  # écriture bleue
    d.rectangle((40, 0, 49, 19), fill=(10, 30, 90))  # texte bleu marine foncé (document)
    g = pt.niveaux_de_gris(im)
    assert g.mode == "L"
    px = [g.getpixel((x, 10)) for x in (5, 15, 25, 35, 45, 55)]
    assert px[0] == 0 and px[1] == 90 and px[5] == 255
    lum = im.convert("L")
    assert px[2] >= 200 and px[3] >= 160  # au-dessus du seuil de binarisation (~128)
    assert lum.getpixel((25, 10)) < 150 and lum.getpixel((35, 10)) < 130  # la luminance les gardait sombres
    assert px[4] <= 100  # un texte coloré foncé reste du texte
    assert pt.niveaux_de_gris(g) is g
    # photo de document (fond brun) : luminance, le maximum des canaux effacerait le bord de la page
    photo = Image.new("RGB", (200, 20), (120, 80, 50))
    assert pt.niveaux_de_gris(photo).tobytes() == photo.convert("L").tobytes()


# --- traits de télécopie (D-2602) -----------------------------------------------------------------------------


def test_traits_traversants_effaces_texte_conserve():
    im = _page_texte()
    d = ImageDraw.Draw(im)
    d.rectangle((400, 0, 403, im.height), fill=0)  # trait vertical sur toute la hauteur
    d.rectangle((0, 820, im.width, 822), fill=0)  # trait horizontal sur toute la largeur
    propre, n = pt.retirer_traits(im)
    assert n == 2
    col = propre.crop((400, 0, 404, im.height)).convert("L")
    # le trait a disparu hors des mots qu'il traverse ; les mots traversés restent encrés (voisins encrés)
    noirs = sum(1 for v in col.tobytes() if v < 128) / (4 * im.height)
    assert noirs < 0.4
    rangee = propre.crop((0, 815, im.width, 828))
    assert min(rangee.crop((0, 5, 70, 8)).tobytes()) == 255  # marge gauche : plus d'encre
    # le reste de la page est intact
    assert propre.crop((500, 100, 1100, 800)).tobytes() == im.crop((500, 100, 1100, 800)).tobytes()


def test_filets_de_tableau_et_page_propre_inchanges():
    im = _page_texte()
    d = ImageDraw.Draw(im)
    d.rectangle((80, 600, im.width - 80, 602), fill=0)  # filet de tableau : s'arrête aux marges
    d.rectangle((80, 300, 82, 1400), fill=0)  # filet vertical de cadre (65 % de la hauteur)
    propre, n = pt.retirer_traits(im)
    assert n == 0 and propre is im


# --- bruit impulsionnel, contraste (D-2602, D-2603) -----------------------------------------------------------


def test_median_sur_telecopie_seulement():
    """Télécopie : page bitonale agrandie (≥ 2 000 px), points isolés et trous filtrés par le médian. Un scan en
    niveaux de gris (demi-teintes) ou une image bitonale en basse résolution n'est pas filtré."""
    propre = _page_texte(2000, 2800, lignes=50)
    bruite = propre.copy()
    rnd = random.Random(7)
    px = bruite.load()
    for _ in range(40_000):
        x, y = rnd.randrange(bruite.width), rnd.randrange(bruite.height)
        px[x, y] = 0 if px[x, y] > 128 else 255
    assert pt.page_telecopie(bruite)
    filtre, applique = pt.debruiter(bruite)
    assert applique

    def ecarts(a):
        return sum(1 for u, v in zip(a.tobytes(), propre.tobytes(), strict=True) if abs(u - v) > 128)

    assert ecarts(filtre) < ecarts(bruite) * 0.1
    # niveaux de gris : bords anticrénelés (demi-teintes) -> pas de médian
    grain = Image.effect_noise(propre.size, 40)  # scan en niveaux de gris : encre grise et grain
    gris = ImageChops.add(propre.point(lambda v: 70 if v < 128 else 235), grain, 1.0, -128)
    assert pt.debruiter(gris) == (gris, False)
    # bitonale mais en basse résolution (fax TIFF 200 dpi) -> pas de médian
    petit = bruite.resize((1600, 2240), Image.NEAREST)
    assert pt.debruiter(petit) == (petit, False)


def test_contraste_etire_page_pale_seulement():
    pale = _page_texte(gris=185).point(lambda v: 245 if v == 255 else v)
    etiree, ok = pt.etirer_contraste(pale)
    assert ok and min(etiree.tobytes()) == 0 and etiree.getpixel((5, 5)) == 255
    nette = _page_texte()
    assert pt.etirer_contraste(nette) == (nette, False)
    # photo mal éclairée : fond gris, encre foncée -> pas d'étirement (il amplifierait l'ombre)
    photo = _page_texte(gris=40).point(lambda v: 190 if v == 255 else v)
    assert pt.etirer_contraste(photo) == (photo, False)


# --- deux pages par feuille (D-2604) --------------------------------------------------------------------------


def _feuille_deux_pages(separateur: bool = True) -> Image.Image:
    g, d_ = _page_texte(1100, 1600), _page_texte(1100, 1600, lignes=12)
    feuille = Image.new("L", (2300, 1600), 255)
    feuille.paste(g, (20, 0))
    feuille.paste(d_, (1180, 0))
    if separateur:
        ImageDraw.Draw(feuille).line((1150, 0, 1150, 1600), fill=120, width=2)
    return feuille


def test_coupure_deux_pages_detectee():
    for sep in (True, False):
        c = pt.coupure_deux_pages(_feuille_deux_pages(sep))
        assert c is not None and 1100 <= c <= 1200


def test_coupure_refusee_page_portrait_paysage_ou_tournee():
    assert pt.coupure_deux_pages(_page_texte()) is None  # portrait
    tableau = Image.new("L", (2300, 1600), 255)  # paysage : lignes continues sur toute la largeur
    d = ImageDraw.Draw(tableau)
    for i in range(30):
        d.rectangle((60, 100 + i * 45, 2240, 118 + i * 45), fill=0)
    assert pt.coupure_deux_pages(tableau) is None
    # page portrait tournée de 90° (scan paysage non redressé) : lignes verticales, pas deux pages
    assert pt.coupure_deux_pages(_feuille_deux_pages().rotate(90, expand=True).resize((2300, 1600))) is None


@ocr
def test_ocr_deux_pages_par_feuille_meme_numero_lignes_par_moitie():
    """Convention (D-2604) : la feuille reste une page (numéro inchangé), la moitié gauche est lue avant la
    droite, aucune ligne ne mêle les deux moitiés, les boîtes sont relatives à la feuille entière."""
    gauche = Image.open(io.BytesIO(fab.image_scan(fab.pdf([fab.FACTURE_COMMERCIALE]), dpi=150)))
    droite = Image.open(io.BytesIO(fab.image_scan(fab.pdf([fab.FACTURE_TRANSITAIRE]), dpi=150)))
    w, h = gauche.size
    feuille = Image.new("L", (2 * w + 40, h), 255)
    feuille.paste(gauche, (0, 0))
    feuille.paste(droite, (w + 40, 0))
    ImageDraw.Draw(feuille).line((w + 20, 0, w + 20, h), fill=100, width=2)
    pages = extraire_pages(_scan(feuille) + b"", type_mime="image/png", options=LOCAL)
    assert len(pages) == 1 and pages[0].page.numero == 1
    t = pages[0].texte
    assert any(a.startswith("deux_pages_par_feuille") for a in t.avertissements)
    assert "12,540.00" in t.texte and "FT-2026-00042" in t.texte
    assert t.texte.index("INV-2026-0815") < t.texte.index("FT-2026-00042")
    milieu = (w + 20) / feuille.width
    for li in t.lignes:
        assert li.x1 <= milieu + 0.01 or li.x0 >= milieu - 0.01, li.texte
    z = t.zone_de("FT-2026-00042")
    assert z is not None and z.x0 > 0.5
    z = t.zone_de("INV-2026-0815")
    assert z is not None and z.x1 < 0.5


@ocr
def test_ocr_reglages_desactives_page_simple_inchangee():
    """Sans dégradation, le prétraitement ne change rien d'essentiel à la lecture."""
    scan = fab.image_scan(fab.pdf([fab.DECLARATION]))
    p = extraire_pages(scan, type_mime="image/png", options=LOCAL)[0]
    assert "26FR000000000001A1" in p.page.texte
    assert not any(a.startswith("deux_pages") for a in p.texte.avertissements)


# --- orientation (D-2605) -------------------------------------------------------------------------------------


@ocr
def test_osd_confiant_mais_faux_corrige_par_reessai(monkeypatch):
    """L'OSD rend un verdict confiant faux (180° sur une page droite) : la lecture après rotation est mauvaise
    (confiance < 0,40), les autres orientations sont essayées et la bonne (0°) l'emporte."""
    from controldone.ingest import pages as module_pages

    monkeypatch.setattr(module_pages, "_osd_rotation", lambda image: 180)
    scan = fab.image_scan(fab.pdf([fab.FACTURE_TRANSITAIRE]), dpi=300)
    p = extraire_pages(scan, type_mime="image/png", options=LOCAL)[0]
    assert p.page.rotation_appliquee == 0
    assert "dédouanement" in p.page.texte and p.page.score_ocr > 0.8
    monkeypatch.setitem(REGLAGES_OCR, "seuil_reessai_orientation", 0.0)
    p = extraire_pages(scan, type_mime="image/png", options=LOCAL)[0]
    assert p.page.rotation_appliquee == 180 and "dédouanement" not in p.page.texte


def test_pretraiter_trace_les_operations():
    im = _page_texte().convert("RGB")
    ImageDraw.Draw(im).rectangle((400, 0, 402, im.height), fill=(0, 0, 0))
    gris, notes = _pretraiter(im)
    assert gris.mode == "L" and notes == ["pretraitement:traits_effaces:1"]
