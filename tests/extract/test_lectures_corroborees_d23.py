"""Lectures confirmées par une seconde lecture ou une clé de contrôle (D-2301, D-2302, D-2305, D-2308).
Données fictives."""

from types import SimpleNamespace

from controldone.extract.deterministe.facture_commerciale import _code_seul_relu
from controldone.extract.deterministe.facture_transitaire import (
    _DATE_RE,
    _RX_SEP_PERIODE,
    C_OCR_RECOUPEE,
    _conf_tva_cle_valide,
)
from controldone.model.enums import Methode, NatureLigne
from controldone.normalize.natures import nature_libelle, renvoie_a_une_annexe

TVA_CLE_JUSTE = "FR68000458570"  # clé FICTIVE juste
TVA_CLE_FAUSSE = "FR69000458570"


def _lt(norm, *, methode=Methode.ocr, conf_ocr=0.9, corrigee=False):
    return SimpleNamespace(norm=norm, corrigee=corrigee,
                           lu=SimpleNamespace(lecture=SimpleNamespace(methode=methode, confiance_ocr=conf_ocr)))


# --- D-2302 : clé de TVA ----------------------------------------------------------------------------------------

def test_tva_ocr_a_cle_juste_prend_la_confiance_de_l_attribution():
    assert _conf_tva_cle_valide(_lt(TVA_CLE_JUSTE), 0.97) == C_OCR_RECOUPEE
    assert _conf_tva_cle_valide(_lt(TVA_CLE_JUSTE), 0.8) == 0.8  # pavé non libellé : attribution incertaine


def test_tva_cle_fausse_corrigee_native_ou_ocr_faible_regle_ordinaire():
    assert _conf_tva_cle_valide(_lt(TVA_CLE_FAUSSE), 0.97) is None
    assert _conf_tva_cle_valide(_lt(TVA_CLE_JUSTE, corrigee=True), 0.97) is None
    assert _conf_tva_cle_valide(_lt(TVA_CLE_JUSTE, methode=Methode.texte_natif), 0.97) is None
    assert _conf_tva_cle_valide(_lt(TVA_CLE_JUSTE, conf_ocr=0.4), 0.97) is None
    assert _conf_tva_cle_valide(_lt("DE123456789"), 0.97) is None  # clé non vérifiable


# --- D-2305 : nature d'une ligne lue par OCR --------------------------------------------------------------------

def test_nature_tolerante_une_faute_par_mot():
    assert nature_libelle("Comisi6n por anticipo") is None
    assert nature_libelle("Comisi6n por anticipo", tolerant=True) is NatureLigne.frais_avance_fonds
    assert nature_libelle("Frais de dédauanement", tolerant=True) is NatureLigne.frais_dedouanement
    assert nature_libelle("Customs clearance", tolerant=True) is NatureLigne.frais_dedouanement


def test_nature_tolerante_sans_candidat_unique_rien():
    assert nature_libelle("Frais de dassier", tolerant=True) is None
    assert nature_libelle("Contrôle documentaire FICTIF", tolerant=True) is None


def test_renvoi_a_une_annexe():
    assert renvoie_a_une_annexe("Suplidos según anexo (página 2)")
    assert renvoie_a_une_annexe("Disbursements as per annex")
    assert not renvoie_a_une_annexe("Frais de dossier")


# --- D-2301 : période écrite dans le libellé --------------------------------------------------------------------

def test_periode_dans_le_libelle():
    for texte in ("Lagergeld (07/03/2026 – 15/03/2026)", "Storage 01/06/2026 to 05/06/2026",
                  "Almacenaje (05/07/2026 — 14/07/2026)"):
        dates = list(_DATE_RE.finditer(texte))
        assert len(dates) == 2
        assert _RX_SEP_PERIODE.fullmatch(texte[dates[0].end():dates[1].start()].strip("() ") or " ")


def test_deux_dates_sans_separateur_d_intervalle_ne_font_pas_une_periode():
    texte = "Magasinage 07/03/2026 facture du 15/03/2026"
    dates = list(_DATE_RE.finditer(texte))
    assert not _RX_SEP_PERIODE.fullmatch(texte[dates[0].end():dates[1].start()])


# --- D-2308 : devise relue ---------------------------------------------------------------------------------------

def test_seul_code_iso_relu_sur_deux_lignes():
    texte = "Currency:\nEUR\nTOTAL AMOUNT EUR 6, 442.30"
    assert _code_seul_relu(texte, "EUR", {"EUR"})
    assert not _code_seul_relu("Currency: EUR\nTOTAL 6 442,30", "EUR", {"EUR"})  # une seule ligne
    assert not _code_seul_relu(texte + "\nUSD 1.10", "EUR", {"EUR", "USD"})  # deux codes sur la page
