"""Couverture du rendu des pages et des extraits de preuve (``services.vignettes``, bloc O4, D-4901), exécuté ici
dans le processus courant (``rendu_local`` : le service l'appelle dans le processus isolé, non mesuré). Plafond de
pixels (RS-04), page hors document, extrait autour d'une valeur trouvée dans la couche texte, cache borné, toute
erreur de rendu = « pas d'image ». Documents générés en mémoire, contenu fictif."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from controldone.services import vignettes as v


def _pdf(texte: str = "TOTAL FACTURE 1 234,56 EUR FICTIF", pages: int = 1, taille=(595, 842)) -> bytes:
    from reportlab.pdfgen import canvas

    sortie = io.BytesIO()
    c = canvas.Canvas(sortie, pagesize=taille)
    for _ in range(pages):
        c.setFont("Helvetica", 12)
        c.drawString(72, taille[1] - 100, texte)
        c.showPage()
    c.save()
    return sortie.getvalue()


def _png(w: int, h: int) -> bytes:
    sortie = io.BytesIO()
    Image.new("L", (w, h), 200).save(sortie, format="PNG")
    return sortie.getvalue()


def _taille(png: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(png)).size


@pytest.fixture(autouse=True)
def _cache_vide(monkeypatch):
    v._CACHE.clear()
    monkeypatch.setattr(v, "ISOLER", False)
    yield
    v._CACHE.clear()


# --- échelle et plafond de pixels ------------------------------------------------------------------------------------


def test_echelle_normale_et_plafonnee():
    assert v._echelle(620, 877, 1240) == 2.0
    e = v._echelle(1, 14_000, 1240)  # 1 pt de large sur 5 m de haut
    assert 1 * 14_000 * e * e <= v.MAX_PIXELS
    assert v._echelle(0, 0, 220) == 220  # dimensions nulles : bornées à 1


# --- pages -------------------------------------------------------------------------------------------------------------


def test_page_pdf_aux_trois_largeurs():
    pdf = _pdf()
    for taille, largeur in v._LARGEURS.items():
        assert _taille(v.rendu_local(contenu=pdf, mime="application/pdf", numero=1, largeur=largeur))[0] in (
            largeur,
            largeur - 1,
        ), taille


def test_page_pdf_hors_document():
    pdf = _pdf(pages=2)
    assert v.rendu_local(contenu=pdf, mime="application/pdf", numero=3) is None
    assert v.rendu_local(contenu=pdf, mime="application/pdf", numero=0) is None
    assert v.rendu_local(contenu=pdf, mime="application/pdf", numero=2) is not None


def test_page_pdf_aberrante_plafonnee():
    png = v.rendu_local(contenu=_pdf(taille=(2, 14_000)), mime="application/pdf", numero=1, largeur=1240)
    w, h = _taille(png)
    assert w * h <= v.MAX_PIXELS


def test_image_redimensionnee_et_multipage():
    assert _taille(v.rendu_local(contenu=_png(1000, 500), mime="image/png", numero=1, largeur=220)) == (
        220,
        110,
    )
    tiff = io.BytesIO()
    Image.new("RGB", (100, 100)).save(
        tiff, format="TIFF", save_all=True, append_images=[Image.new("RGB", (50, 200))]
    )
    assert _taille(v.rendu_local(contenu=tiff.getvalue(), mime="image/tiff", numero=2, largeur=25)) == (
        25,
        100,
    )


def test_type_inconnu_pas_d_image():
    assert v.rendu_local(contenu=b"texte", mime="text/plain", numero=1) is None


# --- extraits de preuve -----------------------------------------------------------------------------------------------


def test_extrait_par_recherche_dans_le_texte():
    pdf = _pdf()
    png = v.rendu_local(contenu=pdf, mime="application/pdf", numero=1, valeur=" 1 234,56 ", extrait=True)
    w, h = _taille(png)
    assert w < 1240 and h < 300  # rognage autour de la ligne, pas la page entière


def test_extrait_valeur_absente_ou_trop_courte():
    pdf = _pdf()
    assert (
        v.rendu_local(contenu=pdf, mime="application/pdf", numero=1, valeur="9 999,99", extrait=True) is None
    )
    assert v.rendu_local(contenu=pdf, mime="application/pdf", numero=1, valeur=" 1 ", extrait=True) is None
    assert v.rendu_local(contenu=pdf, mime="application/pdf", numero=1, extrait=True) is None


def test_extrait_par_zone_sur_une_image():
    png = v.rendu_local(
        contenu=_png(800, 1000), mime="image/png", numero=1, zone=(0.4, 0.5, 0.6, 0.52), extrait=True
    )
    assert png is not None


def test_extrait_zone_degeneree_ou_type_inconnu():
    assert (
        v.rendu_local(
            contenu=_png(800, 1000), mime="image/png", numero=1, zone=(0.5, 1.2, 0.5, 1.3), extrait=True
        )
        is None
    )
    assert (
        v.rendu_local(contenu=b"x", mime="text/plain", numero=1, zone=(0.1, 0.1, 0.2, 0.2), extrait=True)
        is None
    )


# --- cache et erreurs -------------------------------------------------------------------------------------------------


def test_page_png_cache_et_lecture_unique():
    lectures = []

    def contenu():
        lectures.append(1)
        return _pdf()

    a = v.page_png("cli_a:sha", contenu, "application/pdf", 1, "inconnue")  # taille inconnue : mini
    b = v.page_png("cli_a:sha", contenu, "application/pdf", 1, "mini")
    assert a == b and a is not None and len(lectures) == 1


def test_cache_borne(monkeypatch):
    monkeypatch.setattr(v, "_MAX", 3)
    for i in range(5):
        v._cache(("k", i), lambda: b"x")
    assert list(v._CACHE) == [("k", 2), ("k", 3), ("k", 4)]


def test_erreur_de_rendu_pas_d_image():
    def illisible():
        raise OSError("coffre FICTIF indisponible")

    assert v.page_png("cli_a:x", illisible, "application/pdf", 1) is None
    assert v.extrait_png("cli_a:x", illisible, "application/pdf", 1, valeur="12") is None
    assert v.page_png("cli_a:y", lambda: b"%PDF-1.4 tronque", "application/pdf", 1) is None
    assert v.extrait_png("cli_a:y", lambda: b"pas une image", "image/png", 1, zone=(0, 0, 1, 1)) is None


def test_rendu_isole_en_echec_journalise(monkeypatch, caplog):
    import controldone.ingest.pages as pages

    monkeypatch.setattr(v, "ISOLER", True)
    monkeypatch.setattr(pages, "executer_isole", lambda cible, kwargs: (None, "delai_depasse"))
    with caplog.at_level("WARNING", "controldone.services.vignettes"):
        assert v.page_png("cli_a:z", _pdf, "application/pdf", 1) is None
    assert "motif=delai_depasse" in caplog.text
