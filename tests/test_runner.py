"""Moteur : ordre, isolation des erreurs, garde-fous, règles de non-double-comptage (§8.6)."""

from decimal import Decimal as D

import pytest

from controldone.controls.framework import (
    ControlContext,
    cle_unite,
    control,
    preuve,
    registre_temporaire,
    run_controls,
)
from controldone.guardrails import PHRASE_RENVOI
from controldone.model import Niveau, Outcome, RaisonCode, RolePreuve
from controldone.testing import contexte, declaration, facture_transitaire, vs


@pytest.fixture
def ctx() -> ControlContext:
    return contexte([declaration(id="doc_dec"), facture_transitaire(id="doc_ft")])


def _constat(
    ctx, cid, unite, montant, *, ecart=None, renvoi=False, libelle="Le document A indique 1 ; B indique 2."
):
    cl = ctx.classify(
        cid,
        ecart=ecart if ecart is not None else montant,
        tolerance=D("0.05"),
        seuil_certitude=D("1"),
        valeurs_cles=[vs("x", "1", document_id="doc_ft")],
    )
    return ctx.constat(
        cid,
        cl,
        unite=unite,
        libelle=libelle,
        montant=montant,
        renvoi=renvoi,
        preuves=[preuve(vs("x", "1", document_id="doc_ft"), RolePreuve.valeur_b)],
    )


def test_cle_unite():
    assert cle_unite(ft="b", dec=["z", "a"]) == "dec:a+z|ft:b"
    assert cle_unite() == "dossier"
    assert cle_unite(dec="x", tax=3, autre=None) == "dec:x|tax:3"


def test_ordre_annexe_a_et_anterieurs(ctx):
    vus = []
    with registre_temporaire():

        @control("C5")
        def c5(c):
            vus.append(("C5", [r.controle_id for r in c.anterieurs()]))
            return [c.conforme("C5")]

        @control("A1")
        def a1(c):
            vus.append(("A1", [r.controle_id for r in c.anterieurs()]))
            return [c.conforme("A1")]

        rs = run_controls(ctx)
    assert [r.controle_id for r in rs] == ["A1", "C5"]
    assert vus == [("A1", []), ("C5", ["A1"])]


def test_controle_inconnu_refuse():
    with registre_temporaire(), pytest.raises(KeyError):
        control("Z9")


def test_double_enregistrement_refuse():
    with registre_temporaire():

        @control("A1")
        def un(c):
            return []

        with pytest.raises(ValueError):

            @control("A1")
            def deux(c):
                return []


def test_exception_isolee(ctx):
    with registre_temporaire():

        @control("A1")
        def casse(c):
            raise RuntimeError("contenu secret du document")

        @control("A2")
        def ok(c):
            return [c.conforme("A2")]

        rs = run_controls(ctx)
    assert rs[0].outcome is Outcome.non_verifiable and rs[0].raison_code is RaisonCode.erreur_interne
    assert rs[0].details == {"exception": "RuntimeError"}
    assert rs[1].outcome is Outcome.conforme


def test_sortie_invalide_devient_erreur_interne(ctx):
    with registre_temporaire():

        @control("A1")
        def mauvais(c):
            return [c.conforme("A2")]  # mauvais identifiant

        rs = run_controls(ctx)
    assert rs[0].raison_code is RaisonCode.erreur_interne


def test_garde_fous_non_eligible_et_renvoi(ctx):
    with registre_temporaire():

        @control("A12")
        def a12(c):
            # le contrôle oublie le renvoi et passe un montant : le moteur corrige
            cl = c.classify("A12", ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=[])
            return [
                c.constat(
                    "A12",
                    cl,
                    libelle="Le pays d'origine imprimé sur la facture (CN) diffère.",
                    montant=D("10"),
                )
            ]

        rs = run_controls(ctx)
    c = rs[0].constat
    assert c.niveau is Niveau.a_verifier and c.renvoi and c.montant_en_jeu is None
    assert PHRASE_RENVOI in c.prochaine_action
    assert RaisonCode.renvoi_reglementaire in c.raisons


def test_formulation_interdite_bloquee(ctx):
    with registre_temporaire():

        @control("C1")
        def c1(c):
            return [_constat(c, "C1", "u", D("10"), libelle="Surfacturation frauduleuse des droits dus.")]

        rs = run_controls(ctx)
    assert rs[0].constat.motif_blocage == "formulation_interdite"


def test_r1_c3_neutralise_c4_et_r2_c5(ctx):
    u = cle_unite(ft="doc_ft", dec=["doc_dec"])
    with registre_temporaire():

        @control("C1")
        def c1(c):
            return [c.conforme("C1", unite=u)]

        @control("C2")
        def c2(c):
            return [c.conforme("C2", unite=u)]

        @control("C3")
        def c3(c):
            return [_constat(c, "C3", u, D("1240.00"))]

        @control("C4")
        def c4(c):
            return [_constat(c, "C4", u, D("1240.00"))]

        @control("C5")
        def c5(c):
            return [_constat(c, "C5", u, D("1240.00"))]

        rs = {r.controle_id: r for r in run_controls(ctx)}
    assert rs["C3"].outcome is Outcome.ecart_certain and rs["C3"].constat.montant_en_jeu == D("1240.00")
    assert rs["C4"].outcome is Outcome.non_applicable and rs["C4"].details["couvert_par"] == "C3"
    c5 = rs["C5"].constat
    assert c5.niveau is Niveau.ecart_certain and c5.montant_en_jeu is None
    assert c5.montant_brut == D("1240.00") and RaisonCode.doublon_composantes in c5.raisons


def test_r2_c5_garde_son_montant_si_composante_non_evaluable(ctx):
    u = cle_unite(ft="doc_ft", dec=["doc_dec"])
    with registre_temporaire():

        @control("C1")
        def c1(c):
            return [c.conforme("C1", unite=u)]

        @control("C2")
        def c2(c):
            return [c.non_verifiable("C2", RaisonCode.valeur_absente, unite=u)]

        @control("C4")
        def c4(c):
            return [c.conforme("C4", unite=u)]

        @control("C5")
        def c5(c):
            return [_constat(c, "C5", u, D("50.00"))]

        rs = {r.controle_id: r for r in run_controls(ctx)}
    assert rs["C5"].constat.montant_en_jeu == D("50.00")


def _r2_composante_non_evaluable(ctx, c2, c4, c5):
    u = cle_unite(ft="doc_ft", dec=["doc_dec"])
    with registre_temporaire():

        @control("C1")
        def f1(c):
            return [c.non_verifiable("C1", RaisonCode.valeur_absente, unite=u)]

        @control("C2")
        def f2(c):
            return [_constat(c, "C2", u, c2)]

        @control("C4")
        def f4(c):
            return [_constat(c, "C4", u, c4)]

        @control("C5")
        def f5(c):
            return [_constat(c, "C5", u, c5)]

        return {r.controle_id: r for r in run_controls(ctx)}


def test_r2_c5_ne_porte_que_le_residu_des_composantes(ctx):
    # C1 non évaluable : C5 = 600,00 dont 150,00 (C2) et 400,00 (C4) déjà portés -> résidu 50,00 (D-1206)
    rs = _r2_composante_non_evaluable(ctx, D("150.00"), D("400.00"), D("600.00"))
    c5 = rs["C5"].constat
    assert c5.montant_en_jeu == D("50.00") and c5.montant_brut == D("600.00")
    assert RaisonCode.doublon_composantes in c5.raisons
    assert rs["C2"].constat.montant_en_jeu == D("150.00") and rs["C4"].constat.montant_en_jeu == D("400.00")


def test_r2_c5_sans_residu_n_a_pas_de_montant(ctx):
    rs = _r2_composante_non_evaluable(ctx, D("150.00"), D("400.00"), D("550.02"))
    c5 = rs["C5"].constat
    assert c5.montant_en_jeu is None and c5.montant_brut == D("550.02")


def test_r3_a6_neutralise_a5(ctx):
    u = cle_unite(fc=["doc_fc"], dec=["doc_dec"])
    with registre_temporaire():

        @control("A5")
        def a5(c):
            return [_constat(c, "A5", u, D("100"))]

        @control("A6")
        def a6(c):
            return [_constat(c, "A6", u, D("100"))]

        rs = {r.controle_id: r for r in run_controls(ctx)}
    assert rs["A5"].outcome is Outcome.non_applicable and rs["A6"].outcome.est_constat


def test_r4_g5_sans_montant_si_g4_porte_le_meme(ctx):
    with registre_temporaire():

        @control("G4")
        def g4(c):
            return [_constat(c, "G4", "ft:doc_ft|dec:doc_dec", D("6.00"))]

        @control("G5")
        def g5(c):
            return [_constat(c, "G5", "ft:doc_ft|ligne:2", D("6.00"))]

        rs = {r.controle_id: r for r in run_controls(ctx)}
    assert rs["G4"].constat.montant_en_jeu == D("6.00")
    assert (
        rs["G5"].constat.montant_en_jeu is None and RaisonCode.doublon_composantes in rs["G5"].constat.raisons
    )


def test_ecart_en_faveur_du_client_jamais_certain(ctx):
    with registre_temporaire():

        @control("C1")
        def c1(c):
            return [_constat(c, "C1", "u", D("-25.00"))]

        rs = run_controls(ctx)
    c = rs[0].constat
    assert (
        c.niveau is Niveau.a_verifier and c.montant_en_jeu == D("-25.00") and c.sens.value == "faveur_client"
    )


def test_p5_arrete_les_controles(ctx):
    with registre_temporaire():

        @control("P5")
        def p5(c):
            return [c.non_applicable("P5", RaisonCode.dossier_non_concerne, details={"non_concerne": True})]

        @control("A1")
        def a1(c):
            return [c.conforme("A1")]

        rs = run_controls(ctx)
    assert [r.controle_id for r in rs] == ["P5"]


def test_contexte_fige(ctx):
    doc = ctx.documents["doc_dec"]
    with pytest.raises(TypeError):
        ctx.documents["x"] = doc  # MappingProxyType
    source = declaration(id="doc_src")
    c = contexte([source])
    c.documents["doc_src"].dec.mrn = None
    assert source.dec.mrn is not None  # copie profonde : la source n'est pas modifiée


def test_identifiants_stables(ctx):
    r1 = ctx.conforme("A1", unite="x")
    r2 = contexte([declaration(id="doc_dec"), facture_transitaire(id="doc_ft")]).conforme("A1", unite="x")
    assert r1.id == r2.id
    assert ctx.conforme("A1", unite="y").id != r1.id
