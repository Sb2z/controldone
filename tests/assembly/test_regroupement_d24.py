"""Regroupement : corroboration d'un lien de déclaration et sous-dossiers frères (D-2407, D-2408) — fictif."""

from __future__ import annotations

from test_regroupement import MRN1, Lot, _dossier_de, _lien

from controldone.model import ForceLien, SignalLien


def test_declaration_sans_reference_corroboree_par_la_facture_du_transitaire():
    # La déclaration ne cite ni la facture ni son transport (repli « même dossier source », faible) ; la facture du
    # transitaire, rattachée à la facture par le titre de transport, cite le MRN de la déclaration.
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", transport="CMR-FICTIF-0001", total="999.00")
    lot.dec("dec1", "docs/dec.pdf", refs=[], tva="FR00000000000")
    lot.ft("ft1", "docs/ft.pdf", mrns=(MRN1,), transports=("CMR-FICTIF-0001",))
    d = _dossier_de(lot.regrouper(), "dec1")
    lien = _lien(d, "dec1")
    assert lien.force is ForceLien.forte and SignalLien.mrn_cite in lien.signaux


def test_sans_relais_explicite_le_lien_reste_faible():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", transport="CMR-FICTIF-0001", total="999.00")
    lot.dec("dec1", "docs/dec.pdf", refs=[], tva="FR00000000000")
    lot.ft("ft1", "docs/ft.pdf", mrns=("26FR0000000000ZZZ9",))  # cite un autre MRN, rattachée par repli
    d = _dossier_de(lot.regrouper(), "dec1")
    assert _lien(d, "dec1").force is ForceLien.faible


def test_sous_dossiers_freres_reunis_par_un_titre_de_transport_cite():
    # pièces d'un même envoi rangées dans deux sous-dossiers mixtes : la déclaration cite le transport de la facture
    lot = Lot()
    lot.fc("fc1", "docs/a/fc.pdf", transport="999-00000001")
    lot.support("sup1", "docs/a/colisage.pdf")
    lot.dec("dec1", "docs/b/dec.pdf", refs=[("N740", "999-00000001")], tva="FR00000000000", montant=None)
    lot.ft("ft1", "docs/b/ft.pdf", mrns=(MRN1,))
    res = lot.regrouper()
    d = _dossier_de(res, "dec1")
    assert d.lien("fc1") is not None and SignalLien.ref_transport in _lien(d, "dec1").signaux


def test_sous_dossiers_freres_sans_reference_commune_restent_distincts():
    lot = Lot()
    lot.fc("fc1", "docs/a/fc.pdf", transport="999-00000001")
    lot.support("sup1", "docs/a/colisage.pdf")
    lot.dec("dec1", "docs/b/dec.pdf", refs=[("N380", "INV-99999")])  # cite une autre facture
    lot.ft("ft1", "docs/b/ft.pdf", mrns=(MRN1,))
    res = lot.regrouper()
    assert _dossier_de(res, "dec1").lien("fc1") is None


def test_sous_dossiers_freres_reunis_par_le_numero_de_facture_cite():
    lot = Lot()
    lot.fc("fc1", "docs/a/fc.pdf")
    lot.support("sup1", "docs/a/colisage.pdf")
    lot.dec("dec1", "docs/b/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/b/ft.pdf", mrns=(MRN1,))
    d = _dossier_de(lot.regrouper(), "dec1")
    assert d.lien("fc1") is not None and SignalLien.ref_facture_citee in _lien(d, "dec1").signaux
