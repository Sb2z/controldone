"""Imputation déterministe des avoirs (SPEC §17.2). Données fictives."""

from datetime import date, datetime
from decimal import Decimal as D

import pytest

from controldone.model import (
    ChampsAvoir,
    Composante,
    EcartARecouvrer,
    LigneFactureTransitaire,
    NatureLigne,
    Partie,
    StatutEcart,
    Transitaire,
    TypeDocument,
)
from controldone.recouvrement import (
    EcartImputable,
    LigneCredit,
    cle_emetteur,
    composantes_de_nature,
    imputer_avoirs,
    lignes_credit_depuis_avoir,
)
from controldone.testing import document, vs

MRN = "26FR00000000000001"
TRA = "tra_fictif"


def lc(
    montant,
    nature=NatureLigne.debours_droits,
    *,
    avoir="av1",
    ligne=0,
    origine=("FT-001",),
    mrns=(),
    transport=(),
    emetteur=TRA,
    le=date(2026, 9, 1),
    numero="AV-1",
):
    return LigneCredit(
        avoir_id=avoir,
        ligne=ligne,
        nature=nature,
        montant=D(montant),
        emetteur=emetteur,
        date_avoir=le,
        numero_avoir=numero,
        factures_origine=tuple(origine),
        mrns=tuple(mrns),
        refs_transport=tuple(transport),
    )


def ec(
    id_,
    reste,
    comp=Composante.droit,
    *,
    statut=StatutEcart.ouvert,
    quand=None,
    facture="FT-001",
    mrn=None,
    transport=None,
    emetteur=TRA,
    constat="",
):
    return EcartImputable(
        id=id_,
        composante=comp,
        reste=D(reste),
        emetteur=emetteur,
        statut=statut,
        date_constat=quand,
        constat_id=constat or id_,
        facture_ref=facture,
        mrn=mrn,
        ref_transport=transport,
    )


def test_imputation_totale_et_statut_credite():
    r = imputer_avoirs([lc("40.00")], [ec("e1", "40.00")])
    assert r.credit_pour("e1") == D("40.00")
    assert r.ecarts["e1"].reste == D("0.00") and r.ecarts["e1"].statut is StatutEcart.credite
    assert r.reliquats == () and r.imputations[0].palier == "facture"


def test_imputation_partielle_et_reste_sous_t_debours():
    r = imputer_avoirs([lc("30.00")], [ec("e1", "40.00")])
    assert r.ecarts["e1"].reste == D("10.00") and r.ecarts["e1"].statut is StatutEcart.partiellement_credite
    # reste de 0,04 ≤ T_DEBOURS (0,05) : crédité (écart d'arrondi)
    r = imputer_avoirs([lc("39.96")], [ec("e1", "40.00")], t_debours=D("0.05"))
    assert r.ecarts["e1"].reste == D("0.04") and r.ecarts["e1"].statut is StatutEcart.credite


def test_reliquat_et_arrondi_au_centime():
    r = imputer_avoirs([lc("50.005")], [ec("e1", "40.00")])  # avoir arrondi au centime : 50,01
    assert r.credit_pour("e1") == D("40.00")
    assert r.reliquat_avoir("av1") == D("10.01")


def test_ordre_reclame_avant_ouvert_puis_date_puis_constat():
    ecarts = [
        ec("ouvert_ancien", "10.00", quand=datetime(2026, 1, 1)),
        ec("reclame_recent", "10.00", statut=StatutEcart.reclame, quand=datetime(2026, 6, 1)),
        ec("reclame_ancien_b", "10.00", statut=StatutEcart.reclame, quand=datetime(2026, 3, 1), constat="b"),
        ec("reclame_ancien_a", "10.00", statut=StatutEcart.reclame, quand=datetime(2026, 3, 1), constat="a"),
    ]
    r = imputer_avoirs([lc("25.00")], ecarts)
    assert [(i.ecart_id, i.montant) for i in r.imputations] == [
        ("reclame_ancien_a", D("10.00")),
        ("reclame_ancien_b", D("10.00")),
        ("reclame_recent", D("5.00")),
    ]
    assert r.credit_pour("ouvert_ancien") == D("0.00")
    # déterminisme : l'ordre d'entrée est indifférent
    r2 = imputer_avoirs([lc("25.00")], list(reversed(ecarts)))
    assert r2.imputations == r.imputations


def test_statuts_non_imputables_et_autres_emetteurs_ou_composantes():
    ecarts = [
        ec("credite", "10.00", statut=StatutEcart.credite),
        ec("abandonne", "10.00", statut=StatutEcart.abandonne),
        ec("autre_emetteur", "10.00", emetteur="tra_autre"),
        ec("tva", "10.00", comp=Composante.tva),
        ec("conteste", "10.00", statut=StatutEcart.conteste),
    ]
    r = imputer_avoirs([lc("50.00")], ecarts)
    assert [i.ecart_id for i in r.imputations] == ["conteste"]
    assert r.reliquat_avoir("av1") == D("40.00")


def test_paliers_facture_puis_mrn_puis_transport():
    # L'avoir cite une facture sans écart : à défaut, rattachement par MRN.
    e_mrn = ec("par_mrn", "20.00", facture="FT-999", mrn=MRN)
    e_tr = ec("par_transport", "20.00", facture=None, transport="999-11112222")
    r = imputer_avoirs(
        [lc("15.00", origine=("FT-001",), mrns=(MRN[:15] + "XYZ",), transport=("99911112222",))],
        [e_mrn, e_tr],
    )
    assert [(i.ecart_id, i.palier) for i in r.imputations] == [("par_mrn", "mrn")]
    r = imputer_avoirs([lc("15.00", origine=(), transport=("999 1111 2222",))], [e_mrn, e_tr])
    assert [(i.ecart_id, i.palier) for i in r.imputations] == [("par_transport", "transport")]
    # aucun rattachement : rien n'est imputé
    r = imputer_avoirs([lc("15.00", origine=())], [e_mrn, e_tr])
    assert r.imputations == () and r.reliquat_avoir("av1") == D("15.00")


def test_facture_d_origine_ref_compatibles():
    r = imputer_avoirs([lc("5.00", origine=("FT-000123",))], [ec("e1", "5.00", facture="FT123")])
    assert r.credit_pour("e1") == D("5.00")


def test_ligne_combinee_droit_autre_taxe_tva_forfait():
    ecarts = [
        ec("tva", "30.00", comp=Composante.tva),
        ec("forfait", "30.00", comp=Composante.forfait_petits_envois),
        ec("droit", "10.00", comp=Composante.droit),
        ec("autre", "10.00", comp=Composante.autre_taxe),
        ec("prestation", "10.00", comp=Composante.prestation),
    ]
    r = imputer_avoirs([lc("45.00", NatureLigne.debours_combines)], ecarts)
    assert [(i.ecart_id, i.montant) for i in r.imputations] == [
        ("droit", D("10.00")),
        ("autre", D("10.00")),
        ("tva", D("25.00")),
    ]
    assert composantes_de_nature(NatureLigne.magasinage) == (Composante.prestation,)
    assert composantes_de_nature(None) == ()


def test_plusieurs_avoirs_par_date_puis_lignes_par_nature():
    lignes = [
        lc("10.00", NatureLigne.frais_dedouanement, avoir="av2", ligne=0, le=date(2026, 9, 5), numero="AV-2"),
        lc("10.00", NatureLigne.debours_droits, avoir="av2", ligne=1, le=date(2026, 9, 5), numero="AV-2"),
        lc("8.00", NatureLigne.debours_droits, avoir="av1", ligne=0, le=date(2026, 9, 1)),
    ]
    ecarts = [ec("d", "12.00"), ec("p", "50.00", comp=Composante.prestation)]
    r = imputer_avoirs(lignes, ecarts)
    assert [(i.avoir_id, i.ecart_id, i.montant) for i in r.imputations] == [
        ("av1", "d", D("8.00")),
        ("av2", "d", D("4.00")),
        ("av2", "p", D("10.00")),
    ]
    assert r.reliquat_avoir("av2") == D("6.00") and r.reliquat_avoir("av1") == D("0.00")


def test_ligne_sans_nature_jamais_imputee_et_identifiants_uniques():
    r = imputer_avoirs([lc("10.00", None)], [ec("e1", "10.00")])
    assert r.imputations == () and r.reliquats[0].montant == D("10.00")
    with pytest.raises(ValueError):
        imputer_avoirs([], [ec("e1", "1"), ec("e1", "2")])


def test_depuis_ecart_registre():
    e = EcartARecouvrer(
        constat_id="f_1",
        transitaire_id=TRA,
        composante=Composante.droit,
        montant_initial=D("40.00"),
        montant_credite=D("10.00"),
        reste=D("30.00"),
        statut=StatutEcart.reclame,
        mrn=MRN,
    )
    ei = EcartImputable.depuis_ecart(e, facture_ref="FT-001")
    assert ei.reste == D("30.00") and ei.emetteur == TRA and ei.statut is StatutEcart.reclame
    assert EcartImputable.depuis_ecart(e, reste=e.montant_initial).reste == D("40.00")
    r = imputer_avoirs([lc("35.00")], [ei])
    assert r.ecarts[e.id].reste == D("0.00") and r.reliquat_avoir("av1") == D("5.00")


def _avoir(lignes=(), **champs):
    c = ChampsAvoir(
        numero=vs("avoir.numero", "AV-9", document_id="doc_av"),
        date=vs("avoir.date", "2026-09-10", document_id="doc_av"),
        emetteur=Partie(nom=vs("avoir.emetteur.nom", "Transit Fictif SA", document_id="doc_av")),
        refs_facture_origine=[vs("avoir.refs_facture_origine[]", "FT-001", document_id="doc_av")],
        refs_mrn=[vs("avoir.refs_mrn[]", MRN, document_id="doc_av")],
        lignes=list(lignes),
        **champs,
    )
    return document(TypeDocument.avoir, c, id="doc_av")


def test_lignes_credit_depuis_avoir_et_cle_emetteur():
    ligne = LigneFactureTransitaire(
        nature=NatureLigne.debours_tva,
        montant_ht=vs("avoir.lignes[].montant_ht", "12.50", document_id="doc_av"),
    )
    doc = _avoir([ligne])
    t = Transitaire(id="tra_x", nom="TRANSIT FICTIF SA")
    cle = cle_emetteur(doc.av.emetteur, [t])
    assert cle == "tra_x"
    assert cle_emetteur(doc.av.emetteur) == "nom:transit fictif sa"
    (l1,) = lignes_credit_depuis_avoir(doc, emetteur=cle)
    assert l1.nature is NatureLigne.debours_tva and l1.montant == D("12.50") and l1.mrns == (MRN,)
    assert l1.factures_origine == ("FT-001",) and l1.date_avoir == date(2026, 9, 10)
    # avoir sans ligne : une ligne sans nature, au total crédité
    doc = _avoir(total_credite_ht=vs("avoir.total_credite_ht", "99.00", document_id="doc_av"))
    (l2,) = lignes_credit_depuis_avoir(doc)
    assert l2.nature is None and l2.montant == D("99.00")


def test_prestation_de_meme_nature_imputee_d_abord():
    # D-2208 : deux écarts « prestation » de la même facture ; la ligne d'avoir « dédouanement » va d'abord à
    # l'écart dont la ligne facturée est de même nature, quel que soit l'ordre des identifiants.
    surcharge = EcartImputable(
        id="a_surcharge",
        composante=Composante.prestation,
        reste=D("45.00"),
        emetteur=TRA,
        facture_ref="FT-001",
        nature=NatureLigne.surcharge,
    )
    dedou = EcartImputable(
        id="b_dedou",
        composante=Composante.prestation,
        reste=D("15.00"),
        emetteur=TRA,
        facture_ref="FT-001",
        nature=NatureLigne.frais_dedouanement,
    )
    r = imputer_avoirs([lc("15.00", NatureLigne.frais_dedouanement)], [surcharge, dedou])
    assert r.credit_pour("b_dedou") == D("15.00") and r.credit_pour("a_surcharge") == D("0.00")
