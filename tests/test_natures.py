"""Table unique des natures de ligne (D-1213) : PDF et exports structurés donnent la même nature."""

import pytest

from controldone.extract.deterministe.facture_transitaire import classer_nature
from controldone.ingest.structure import nature_ligne
from controldone.model import NatureLigne

N = NatureLigne


@pytest.mark.parametrize(
    ("libelle", "nature"),
    [
        # divergences relevées par l'audit (P0-3)
        ("Forfait dédouanement", N.frais_dedouanement),
        ("Dédouanement import - forfait", N.frais_dedouanement),
        ("TVA", N.debours_tva),
        ("Frais de stockage", N.magasinage),
        ("Fret aérien", N.transport),
        ("Chargement camion", N.manutention),
        ("Other duties and taxes", N.debours_autres_taxes),
        ("Av. fonds", N.frais_avance_fonds),
        ("Dédouan.", N.frais_dedouanement),
        # « forfait » exige un contexte petits envois
        ("Droit forfaitaire petits envois", N.debours_forfait_petits_envois),
        ("Forfait par article", N.debours_forfait_petits_envois),
        ("Flat duty low-value parcels", N.debours_forfait_petits_envois),
        ("Forfait transport", N.transport),
        # formes courantes
        ("Droits de douane", N.debours_droits),
        ("Droits et taxes (débours)", N.debours_combines),
        ("TVA à l'importation", N.debours_tva),
        ("Frais d'avance de fonds", N.frais_avance_fonds),
        ("Lignes supplémentaires / Additional lines", N.frais_ligne_supplementaire),
        ("Surcharge carburant / Fuel surcharge", N.surcharge),
        ("Livraison / Delivery", N.transport),
    ],
)
def test_meme_nature_pdf_et_structure(libelle, nature):
    assert classer_nature(libelle) is nature
    assert nature_ligne(libelle) is nature


@pytest.mark.parametrize("libelle", ["Ouverture de dossier", "Forfait", "Frais de dossier informatique"])
def test_libelle_non_reconnu(libelle):
    assert classer_nature(libelle) is None
    assert nature_ligne(libelle) is N.autre_prestation
