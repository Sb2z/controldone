"""Famille E — avoirs (SPEC §14), avec l'imputation de §17.2. Données fictives."""

from decimal import Decimal as D

import pytest

from controldone.controls.context import AutreDossier
from controldone.controls.famille_e import (
    e1_rattachement,
    e2_avoir_superieur_origine,
    e3_avoir_recu_deux_fois,
    e4_arithmetique_avoir,
    e5_avoir_sans_ecart,
    e6_avoir_partiel,
)
from controldone.controls.framework import run_controls
from controldone.guardrails import check_text
from controldone.model import (
    ChampsAvoir,
    Composante,
    EcartARecouvrer,
    LigneFactureTransitaire,
    NatureLigne,
    NatureMontant,
    Outcome,
    Partie,
    RaisonCode,
    StatutEcart,
    TypeDocument,
)
from controldone.testing import contexte, declaration, document, dossier_pour, facture_transitaire, vs

FT, DEC = "doc_ft1", "doc_dec1"
MRN = "26FR00000000000001"
EMETTEUR = "Transit Fictif SA"


def esp(s):
    return s.replace("\xa0", " ")


def ft_e(*lignes, numero="FT-001", id=FT, emetteur=EMETTEUR, total_ht=None):
    def f(champ, val):
        return vs(f"facture_transitaire.{champ}", val, document_id=id)

    lignes = lignes or (LigneFactureTransitaire(nature=NatureLigne.debours_droits,
                                                montant_ht=f("lignes[].montant_ht", "50.00"),
                                                mrn=f("lignes[].mrn", MRN)),)
    return facture_transitaire(id=id, numero=f("numero", numero), date=f("date", "2026-08-05"),
                               emetteur=Partie(nom=f("emetteur.nom", emetteur)), lignes=list(lignes),
                               total_ht=f("total_ht", total_ht) if total_ht else None)


def ligne_av(doc, montant, nature=NatureLigne.debours_droits, *, quantite=None, pu=None):
    def a(champ, val):
        return vs(f"avoir.{champ}", val, document_id=doc)

    return LigneFactureTransitaire(nature=nature, montant_ht=a("lignes[].montant_ht", montant),
                                   quantite=a("lignes[].quantite", quantite) if quantite else None,
                                   prix_unitaire=a("lignes[].prix_unitaire", pu) if pu else None)


def avoir(id, *lignes, numero="AV-001", origine=("FT-001",), mrns=(), date="2026-09-01", emetteur=EMETTEUR,
          total_ht=None, total_tva=None, total_ttc=None, montant="30.00"):
    def a(champ, val):
        return vs(f"avoir.{champ}", val, document_id=id)

    if not lignes:
        lignes = (ligne_av(id, montant),)
    c = ChampsAvoir(
        numero=a("numero", numero) if numero else None, date=a("date", date) if date else None,
        emetteur=Partie(nom=a("emetteur.nom", emetteur)),
        refs_facture_origine=[a("refs_facture_origine[]", o) for o in origine],
        refs_mrn=[a("refs_mrn[]", m) for m in mrns], lignes=list(lignes),
        total_credite_ht=a("total_credite_ht", total_ht) if total_ht else None,
        total_tva=a("total_tva", total_tva) if total_tva else None,
        total_credite_ttc=a("total_credite_ttc", total_ttc) if total_ttc else None,
    )
    return document(TypeDocument.avoir, c, id=id)


def dec_e():
    return declaration(id=DEC, mrn=MRN)


def un(rs, unite=None):
    rs = [r for r in rs if unite is None or r.unite == unite]
    assert len(rs) == 1, rs
    return rs[0]


def propre(r):
    assert check_text(r.constat.libelle) == [] and check_text(r.constat.prochaine_action) == []


def ecart_registre(montant="40.00", statut=StatutEcart.reclame, comp=Composante.droit, id="eca_1"):
    return EcartARecouvrer(id=id, constat_id="f_origine", transitaire_id="tra_fictif", facture_transitaire_id=FT,
                           mrn=MRN, composante=comp, montant_initial=D(montant), reste=D(montant), statut=statut)


@pytest.mark.parametrize("fn", [e1_rattachement, e2_avoir_superieur_origine, e3_avoir_recu_deux_fois,
                                e4_arithmetique_avoir, e5_avoir_sans_ecart, e6_avoir_partiel])
def test_sans_avoir_non_applicable(fn):
    (r,) = fn(contexte([dec_e(), ft_e()]))
    assert r.outcome is Outcome.non_applicable


# --- E1 ---------------------------------------------------------------------------------------------------


def test_e1_rattache_a_la_facture_d_origine():
    r = un(e1_rattachement(contexte([dec_e(), ft_e(), avoir("doc_av1")])))
    assert r.outcome is Outcome.conforme and r.details["factures_origine"] == [FT]


def test_e1_ref_compatible_et_autre_emetteur():
    r = un(e1_rattachement(contexte([ft_e(numero="FT-000123"), avoir("doc_av1", origine=("FT123",))])))
    assert r.outcome is Outcome.conforme
    r = un(e1_rattachement(contexte([ft_e(), avoir("doc_av1", emetteur="Autre Transit Fictif")])))
    assert r.outcome is Outcome.a_verifier


def test_e1_rattachement_par_mrn():
    r = un(e1_rattachement(contexte([dec_e(), ft_e(), avoir("doc_av1", origine=("FT-999",), mrns=(MRN,))])))
    assert r.outcome is Outcome.a_verifier and RaisonCode.rattachement_faible in r.constat.raisons
    assert "FT-999" in r.constat.libelle and "le MRN" in r.constat.libelle
    assert r.constat.montant_en_jeu is None and r.constat.nature_montant is NatureMontant.aucun
    propre(r)


def test_e1_avoir_non_rattache():
    r = un(e1_rattachement(contexte([dec_e(), ft_e(), avoir("doc_av1", origine=())])))
    assert r.outcome is Outcome.a_verifier and "avoir non rattaché" in r.constat.libelle
    propre(r)


# --- E2 ---------------------------------------------------------------------------------------------------


def test_e2():
    r = un(e2_avoir_superieur_origine(contexte([ft_e(), avoir("doc_av1", montant="50.00")])))
    assert r.outcome is Outcome.conforme
    r = un(e2_avoir_superieur_origine(contexte([ft_e(), avoir("doc_av1", montant="60.00")])))
    assert r.outcome is Outcome.a_verifier and r.ecart == D("10.00")
    assert "60,00 EUR crédités pour 50,00 EUR facturés" in esp(r.constat.libelle)
    propre(r)


def test_e2_plusieurs_avoirs_et_tolerance():
    docs = [ft_e(), avoir("doc_av1", montant="30.00"), avoir("doc_av2", numero="AV-002", montant="20.01",
                                                              date="2026-09-20")]
    rs = e2_avoir_superieur_origine(contexte(docs))
    assert all(r.outcome is Outcome.conforme for r in rs)  # 0,01 ≤ T_SOMME(3)
    docs[2] = avoir("doc_av2", numero="AV-002", montant="25.00", date="2026-09-20")
    rs = e2_avoir_superieur_origine(contexte(docs))
    assert all(r.outcome is Outcome.a_verifier for r in rs)


def test_e2_origine_introuvable():
    r = un(e2_avoir_superieur_origine(contexte([avoir("doc_av1")])))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.document_manquant


# --- E3 ---------------------------------------------------------------------------------------------------


def test_e3_meme_numero():
    docs = [ft_e(), avoir("doc_av1"), avoir("doc_av2", date="2026-09-03")]
    rs = e3_avoir_recu_deux_fois(contexte(docs))
    premier, second = un(rs, "av:doc_av1"), un(rs, "av:doc_av2")
    assert premier.outcome is Outcome.conforme
    assert second.outcome is Outcome.a_verifier and second.details["motif"] == "meme_numero"
    assert "n'est pas imputé une seconde fois" in second.constat.libelle
    propre(second)


def test_e3_meme_montant_meme_origine_moins_de_7_jours():
    a1 = avoir("doc_av1", total_ttc="30.00")
    a2 = avoir("doc_av2", numero="AV-777", date="2026-09-07", total_ttc="30.00")
    r = un(e3_avoir_recu_deux_fois(contexte([a1, a2])), "av:doc_av2")
    assert r.outcome is Outcome.a_verifier
    a2 = avoir("doc_av2", numero="AV-777", date="2026-09-08", total_ttc="30.00")  # 7 jours : hors critère
    assert un(e3_avoir_recu_deux_fois(contexte([a1, a2])), "av:doc_av2").outcome is Outcome.conforme


def test_e3_dans_un_autre_dossier():
    ailleurs = avoir("doc_av0", date="2026-08-30")
    autre = AutreDossier(dossier_pour([ailleurs], id="dos_autre"), {ailleurs.id: ailleurs})
    r = un(e3_avoir_recu_deux_fois(contexte([ft_e(), avoir("doc_av1")], autres_dossiers=[autre])))
    assert r.outcome is Outcome.a_verifier and r.constat.autres_dossiers == ["dos_autre"]
    assert "dos_autre" in r.constat.libelle


# --- E4 ---------------------------------------------------------------------------------------------------


def test_e4():
    av = avoir("doc_av1", ligne_av("doc_av1", "30.00", quantite="3", pu="10.00"), total_ht="30.00",
               total_tva="6.00", total_ttc="36.00")
    rs = e4_arithmetique_avoir(contexte([av]))
    assert {r.sous_controle for r in rs} == {"ligne", "total_ht", "total_ttc"}
    assert all(r.outcome is Outcome.conforme for r in rs)
    av = avoir("doc_av1", ligne_av("doc_av1", "35.00", quantite="3", pu="10.00"), total_ht="30.00",
               total_tva="6.00", total_ttc="38.00")
    rs = {r.sous_controle: r for r in e4_arithmetique_avoir(contexte([av]))}
    assert rs["ligne"].outcome is Outcome.a_verifier  # E4 n'est jamais certain
    assert RaisonCode.controle_signal_seulement in rs["ligne"].constat.raisons
    assert rs["total_ht"].outcome is Outcome.a_verifier and rs["total_ht"].ecart == D("-5.00")
    assert rs["total_ttc"].outcome is Outcome.a_verifier
    assert rs["ligne"].constat.montant_en_jeu is None
    for r in rs.values():
        propre(r)


# --- E5 ---------------------------------------------------------------------------------------------------


def test_e5_reliquat_sans_ecart():
    r = un(e5_avoir_sans_ecart(contexte([dec_e(), ft_e(), avoir("doc_av1")])))
    assert r.outcome is Outcome.a_verifier and r.ecart == D("30.00")
    assert "reliquat de 30,00 EUR" in esp(r.constat.libelle)
    propre(r)


def test_e5_avoir_impute_sur_un_ecart_du_registre():
    ctx = contexte([dec_e(), ft_e(), avoir("doc_av1")], ecarts_recouvrement=[ecart_registre()])
    r = un(e5_avoir_sans_ecart(ctx))
    assert r.outcome is Outcome.conforme and r.details["impute"] == "30.00"


def test_e5_reliquat_dans_t_somme():
    ctx = contexte([ft_e(), avoir("doc_av1", montant="40.01")], ecarts_recouvrement=[ecart_registre()])
    assert un(e5_avoir_sans_ecart(ctx)).outcome is Outcome.conforme


def test_e5_seconde_reception_non_imputee():
    docs = [ft_e(), avoir("doc_av1"), avoir("doc_av2", date="2026-09-03")]
    ctx = contexte(docs, ecarts_recouvrement=[ecart_registre("30.00")])
    rs = e5_avoir_sans_ecart(ctx)
    assert un(rs, "av:doc_av1").outcome is Outcome.conforme
    r2 = un(rs, "av:doc_av2")
    assert r2.outcome is Outcome.non_applicable and r2.raison_code is RaisonCode.couvert_par_autre_controle


def test_e5_avoir_non_ventile():
    av = avoir("doc_av1", total_ht="30.00")
    av.av.lignes.clear()
    r = un(e5_avoir_sans_ecart(contexte([ft_e(), av], ecarts_recouvrement=[ecart_registre()])))
    assert r.outcome is Outcome.a_verifier and "pas ventilé" in r.constat.libelle


# --- E6 ---------------------------------------------------------------------------------------------------


def test_e6_avoir_partiel():
    ctx = contexte([dec_e(), ft_e(), avoir("doc_av1")], ecarts_recouvrement=[ecart_registre("40.00")])
    r = un(e6_avoir_partiel(ctx))
    c = r.constat
    assert r.outcome is Outcome.a_verifier and r.unite == "ecart:eca_1"
    assert c.montant_en_jeu == D("10.00") and c.nature_montant is NatureMontant.recouvrable
    assert c.composante is Composante.droit and r.details["remplace_constat_id"] == "f_origine"
    assert "reste 10,00 EUR" in esp(c.libelle)
    propre(r)


def test_e6_entierement_credite_et_ecart_non_reclame():
    ctx = contexte([ft_e(), avoir("doc_av1", montant="40.00")], ecarts_recouvrement=[ecart_registre("40.00")])
    assert un(e6_avoir_partiel(ctx)).outcome is Outcome.conforme
    ctx = contexte([ft_e(), avoir("doc_av1")],
                   ecarts_recouvrement=[ecart_registre("40.00", statut=StatutEcart.ouvert)])
    assert un(e6_avoir_partiel(ctx)).outcome is Outcome.non_applicable


def test_e6_reste_sous_t_debours():
    ctx = contexte([ft_e(), avoir("doc_av1", montant="39.96")], ecarts_recouvrement=[ecart_registre("40.00")])
    assert un(e6_avoir_partiel(ctx)).outcome is Outcome.conforme


def test_moteur_famille_e():
    ctx = contexte([dec_e(), ft_e(), avoir("doc_av1")], ecarts_recouvrement=[ecart_registre("40.00")])
    rs = run_controls(ctx, controles=["E1", "E2", "E3", "E4", "E5", "E6"])
    for r in rs:
        assert r.outcome is not Outcome.ecart_certain
        if r.constat is not None:
            assert r.constat.motif_blocage is None
