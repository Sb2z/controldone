from decimal import Decimal as D

from controldone.controls.framework import (
    Classement,
    classify,
    eur_par_devise,
    montant_arithmetique,
    montant_ecart_documentaire,
    montant_pour_spec,
    montant_recouvrable,
    sens_pour,
)
from controldone.model import (
    Allocation,
    ForceLien,
    LienDocument,
    MethodeAllocation,
    NatureMontant,
    Niveau,
    Outcome,
    RaisonCode,
    RoleLien,
    Sens,
    TotalOrigine,
)
from controldone.testing import vs

FORTE = LienDocument(document_id="d1", role=RoleLien.declaration, force=ForceLien.forte)
FAIBLE = LienDocument(document_id="d2", role=RoleLien.facture_transitaire, force=ForceLien.faible)


def c(spec="C1", ecart=D("10"), tol=D("0.05"), seuil=D("1"), valeurs=None, **kw):
    return classify(
        spec,
        ecart=ecart,
        tolerance=tol,
        seuil_certitude=seuil,
        valeurs_cles=valeurs if valeurs is not None else [vs("a", "1"), vs("b", "2")],
        c_min_certain=0.9,
        liens=kw.pop("liens", [FORTE]),
        **kw,
    )


def test_conforme_dans_la_tolerance():
    r = c(ecart=D("0.05"))
    assert r == Classement(None, ()) and r.outcome is Outcome.conforme and not r.est_constat
    assert c(ecart=D("-0.04")).niveau is None


def test_certain_quand_tout_est_rempli():
    r = c()
    assert r.niveau is Niveau.ecart_certain and r.raisons == () and r.outcome is Outcome.ecart_certain


def test_condition_1_eligibilite():
    assert c("A2").raisons == (RaisonCode.controle_signal_seulement,)
    assert c("B4", eligible=False).niveau is Niveau.a_verifier
    assert c("B4").niveau is Niveau.ecart_certain


def test_condition_2_seuil():
    r = c(ecart=D("0.80"))
    assert r.niveau is Niveau.a_verifier and r.raisons == (RaisonCode.ecart_sous_seuil,)
    assert c(ecart=D("1.00")).niveau is Niveau.a_verifier  # strictement supérieur exigé
    assert c(ecart=D("1.01")).niveau is Niveau.ecart_certain


def test_condition_3_confiance_et_ancrage():
    r = c(valeurs=[vs("a", "1", confiance=0.89)])
    assert RaisonCode.confiance_insuffisante in r.raisons
    r = c(valeurs=[vs("a", "1", methode="ocr", ancree=False)])
    assert r.raisons == (RaisonCode.valeur_non_ancree,)
    assert c(valeurs=[vs("a", "1", methode="xml_structure", ancree=False)]).niveau is Niveau.ecart_certain
    r = c(valeurs=[vs("a", "1", raisons=[RaisonCode.extracteurs_en_desaccord])])
    assert RaisonCode.extracteurs_en_desaccord in r.raisons


def test_condition_4_total_reconstruit():
    r = c(valeurs=[vs("t", "1", total_origine=TotalOrigine.reconstruit)])
    assert r.raisons == (RaisonCode.total_reconstruit,)


def test_condition_5_rattachement_et_prorata():
    assert c(liens=[FORTE, FAIBLE]).raisons == (RaisonCode.rattachement_faible,)
    manuel = LienDocument(document_id="d3", role=RoleLien.avoir, force=ForceLien.manuelle)
    assert c(liens=[manuel]).niveau is Niveau.ecart_certain
    moyen = LienDocument(document_id="d3", role=RoleLien.avoir, force=ForceLien.moyenne)
    assert c(liens=[moyen]).niveau is Niveau.a_verifier
    pro = Allocation(source_document_id="fc", cible_document_id="d1", methode=MethodeAllocation.prorata)
    assert c(allocations=[pro]).raisons == (RaisonCode.allocation_prorata,)


def test_conditions_6_7_8():
    assert c(lecture_douteuse=True).raisons == (RaisonCode.lecture_douteuse,)
    r = c(explication=RaisonCode.ecart_explique_par_ligne_de_pied)
    assert r.raisons == (RaisonCode.ecart_explique_par_ligne_de_pied,)
    assert c(renvoi=True).raisons == (RaisonCode.renvoi_reglementaire,)
    # un renvoi est un constat même sans écart chiffré
    assert (
        classify(
            "A12",
            ecart=None,
            tolerance=None,
            seuil_certitude=None,
            valeurs_cles=[],
            c_min_certain=0.9,
            renvoi=True,
        ).niveau
        is Niveau.a_verifier
    )


def test_ecart_en_faveur_du_client():
    r = c(ecart=D("-10"))
    assert r.niveau is Niveau.a_verifier and r.raisons == (RaisonCode.ecart_en_faveur_client,)
    assert c("B1", ecart=D("-10")).niveau is Niveau.ecart_certain  # pas recouvrable


def test_raisons_triees_et_uniques():
    r = c(
        ecart=D("0.5"),
        valeurs=[vs("a", "1", confiance=0.5), vs("b", "1", confiance=0.6)],
        lecture_douteuse=True,
        raisons_supplementaires=[RaisonCode.devise_incertaine],
    )
    assert r.raisons == (
        RaisonCode.ecart_sous_seuil,
        RaisonCode.confiance_insuffisante,
        RaisonCode.lecture_douteuse,
        RaisonCode.devise_incertaine,
    )


def test_constat_qualitatif():
    r = classify(
        "A1",
        ecart=None,
        tolerance=None,
        seuil_certitude=None,
        valeurs_cles=[vs("a", "FR1")],
        c_min_certain=0.9,
    )
    assert r.niveau is Niveau.ecart_certain


def test_montants_8_6():
    assert montant_recouvrable(D("1240.004"), D("0")) == D("1240.00")
    assert montant_recouvrable(D("100"), D("100.50")) == D("-0.50")
    assert montant_arithmetique(D("418.20"), D("52.275")) == D("365.93")
    assert montant_ecart_documentaire(D("12450"), D("12540"), devise="EUR") == D("-90.00")
    assert montant_ecart_documentaire(D("12450"), D("12540"), devise="USD") is None
    assert montant_ecart_documentaire(D("100"), D("90"), devise="USD", taux_eur_par_devise=D("0.9")) == D(
        "9.00"
    )
    assert eur_par_devise(D("1.08"), "devise_par_eur") == D(1) / D("1.08")
    assert eur_par_devise(D("0.92"), "eur_par_devise") == D("0.92")


def test_montant_pour_spec_et_sens():
    assert montant_pour_spec("A12", D("10")) is None  # renvoi
    assert montant_pour_spec("A1", D("10")) is None  # aucun
    assert montant_pour_spec("C1", D("10.005")) == D("10.01")
    assert montant_pour_spec("C1", D("10"), renvoi=True) is None
    assert sens_pour(NatureMontant.recouvrable, D("1")) is Sens.defaveur_client
    assert sens_pour(NatureMontant.recouvrable, D("-1")) is Sens.faveur_client
    assert sens_pour(NatureMontant.ecart_documentaire, D("1")) is None
