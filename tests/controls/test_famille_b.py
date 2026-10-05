"""Famille B (B2 à B5) — cohérence interne de la déclaration (SPEC §11). Données fictives.

B1 est testé dans ``tests/test_famille_b1.py`` (contrôle de référence, inchangé).
"""

from decimal import Decimal as D

from controldone.controls.famille_b import (
    ACTION_B,
    b1_base_taux_montant,
    b2_sommes_taxes,
    b3_somme_montants_articles,
    b4_masses,
    b5_colis,
)
from controldone.controls.framework import run_controls
from controldone.guardrails import PHRASE_RENVOI, check_text
from controldone.model import (
    ArticleDeclaration,
    CategorieTaxe,
    ForceLien,
    Methode,
    NatureMontant,
    Outcome,
    PaiementNormalise,
    QualiteTexte,
    RaisonCode,
    RolePreuve,
)
from controldone.testing import contexte, declaration, taxation, vs

DEC = "doc_dec1"


def dv(champ, val, doc=DEC, **kw):
    return vs(f"declaration.{champ}", val, document_id=doc, **kw)


def art(numero, doc=DEC, **champs):
    return ArticleDeclaration(
        numero_article=dv("articles[].numero_article", numero, doc),
        **{k: dv(f"articles[].{k}", v, doc) for k, v in champs.items()},
    )


def tax(montant, *, article="1", code="A00", cat=CategorieTaxe.droit, doc=DEC, **kw):
    return taxation(doc, article=article, type_taxe=code, categorie=cat, base="100", taux="10", montant=montant, **kw)


def dec_b2(*taxes, total=None, total_a_payer=None, n_articles=2, articles=2, doc=DEC, **kw):
    champs = {}
    if total is not None:
        champs["total_droits_taxes"] = dv("total_droits_taxes", total, doc)
    if total_a_payer is not None:
        champs["total_a_payer"] = dv("total_a_payer", total_a_payer, doc)
    if n_articles is not None:
        champs["nombre_articles"] = dv("nombre_articles", str(n_articles), doc)
    champs["articles"] = [art(str(i + 1), doc) for i in range(articles)]
    return declaration(id=doc, taxations=list(taxes), **champs, **kw)


def esp(s):
    """Espaces insécables des montants formatés ramenées à des espaces simples."""
    return s.replace("\xa0", " ")


def textes_propres(r):
    c = r.constat
    assert check_text(c.libelle) == [] and check_text(c.prochaine_action) == []


def par_sous(rs, sous):
    return [r for r in rs if r.sous_controle == sous]


# --- B2 ------------------------------------------------------------------------------------------------


def test_b2_conforme_et_piege_d_arrondi_t_somme():
    # 3 lignes : T_SOMME = 0,03 ; un écart de 0,03 est admis, 0,04 ne l'est pas.
    taxes = [tax("10.01"), tax("20.01", article="2"), tax("30.01", article="2", code="A10")]
    r = b2_sommes_taxes(contexte([dec_b2(*taxes, total="60.00")]))
    (tot,) = par_sous(r, "total")
    assert tot.outcome is Outcome.conforme and tot.tolerance_appliquee == D("0.03")
    r = b2_sommes_taxes(contexte([dec_b2(*taxes, total="59.99")]))
    (tot,) = par_sous(r, "total")
    assert tot.outcome is Outcome.a_verifier
    assert tot.constat.raisons == [RaisonCode.ecart_sous_seuil]
    assert tot.constat.montant_en_jeu == D("-0.04")


def test_b2_ecart_certain():
    d = dec_b2(tax("100.00"), tax("50.00", article="2"), total="250.00")
    (r,) = b2_sommes_taxes(contexte([d]))
    assert r.outcome is Outcome.ecart_certain and r.constat.raisons == []
    c = r.constat
    assert c.montant_en_jeu == D("100.00") and c.nature_montant is NatureMontant.arithmetique_declaration
    assert "250,00 EUR" in esp(c.libelle) and "150,00 EUR" in esp(c.libelle) and "MRN" in c.libelle
    assert c.prochaine_action == ACTION_B and PHRASE_RENVOI in c.prochaine_action
    assert [p.role for p in c.preuves] == [RolePreuve.valeur_b, RolePreuve.operande, RolePreuve.operande,
                                           RolePreuve.valeur_a]
    textes_propres(r)


def test_b2_articles_non_tous_lus_reste_a_verifier():
    d = dec_b2(tax("100.00"), total="250.00", n_articles=3, articles=2)
    (r,) = b2_sommes_taxes(contexte([d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.valeur_absente in r.constat.raisons
    assert "une ligne non lue" in r.constat.libelle
    textes_propres(r)


def test_b2_tva_autoliquidee_deux_hypotheses():
    taxes = [tax("100.00"), tax("200.00", code="B00", cat=CategorieTaxe.tva, paiement=PaiementNormalise.autoliquide)]
    for total in ("100.00", "300.00"):
        (r,) = b2_sommes_taxes(contexte([dec_b2(*taxes, total=total)]))
        assert r.outcome is Outcome.conforme, total
    (r,) = b2_sommes_taxes(contexte([dec_b2(*taxes, total="150.00")]))
    assert r.outcome is Outcome.ecart_certain
    assert r.details["hypothese"] == "tva_autoliquidee_exclue" and r.constat.montant_en_jeu == D("50.00")


def test_b2_total_a_payer_si_pas_de_total_droits_taxes():
    (r,) = b2_sommes_taxes(contexte([dec_b2(tax("10.00"), total_a_payer="10.00")]))
    assert r.outcome is Outcome.conforme and r.details["total"] == "total_a_payer"


def test_b2_total_de_categorie():
    taxes = [tax("10.00"), tax("20.00", article="2"), tax("35.00", article=None)]
    rs = b2_sommes_taxes(contexte([dec_b2(*taxes, total="65.00")]))
    (cat,) = par_sous(rs, "categorie")
    (tot,) = par_sous(rs, "total")
    assert cat.outcome is Outcome.ecart_certain and cat.constat.montant_en_jeu == D("5.00")
    assert "taxe A00" in cat.constat.libelle
    # la ligne de total de catégorie n'est pas comptée deux fois dans la somme générale
    assert tot.details["lignes"] == [0, 1]
    assert tot.outcome is Outcome.ecart_certain and tot.constat.montant_en_jeu == D("35.00")
    textes_propres(cat)


def test_b2_non_verifiable_non_applicable_document_manquant():
    d = dec_b2(tax("10.00", confiance=0.3), total="10.00")
    (r,) = b2_sommes_taxes(contexte([d]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.confiance_insuffisante
    (r,) = b2_sommes_taxes(contexte([dec_b2(tax("10.00"))]))
    assert r.outcome is Outcome.non_applicable
    (r,) = b2_sommes_taxes(contexte([]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.document_manquant


def test_b2_lecture_ocr_douteuse():
    total = dv("total_droits_taxes", "158.00", methode=Methode.ocr)
    d = declaration(id=DEC, taxations=[tax("100.00"), tax("50.00", article="2")], total_droits_taxes=total,
                    nombre_articles=dv("nombre_articles", "2"), articles=[art("1"), art("2")],
                    qualite=QualiteTexte.ocr)
    (r,) = b2_sommes_taxes(contexte([d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.lecture_douteuse in r.constat.raisons


def test_b2_rattachement_faible():
    d = dec_b2(tax("100.00"), tax("50.00", article="2"), total="250.00")
    (r,) = b2_sommes_taxes(contexte([d], force=ForceLien.faible))
    assert r.outcome is Outcome.a_verifier and RaisonCode.rattachement_faible in r.constat.raisons


def test_b2_versions_rectificatives_seule_la_derniere():
    v1 = dec_b2(tax("100.00", doc="doc_v1"), total="999.00", doc="doc_v1", version="1",
                mrn="26FR00000000000001")
    v2 = dec_b2(tax("100.00", doc="doc_v2"), total="100.00", doc="doc_v2", version="2",
                mrn="26FR00000000000001")
    rs = b2_sommes_taxes(contexte([v1, v2]))
    assert len(rs) == 1 and rs[0].outcome is Outcome.conforme and rs[0].documents_concernes == ["doc_v2"]


# --- B3 ------------------------------------------------------------------------------------------------


def dec_b3(montants, total, *, devise="EUR", n_articles=None, **kw):
    arts = [art(str(i + 1), montant_facture_article=m) for i, m in enumerate(montants)]
    return declaration(
        id=DEC, articles=arts, montant_total_facture=dv("montant_total_facture", total),
        devise_facture=dv("devise_facture", devise),
        nombre_articles=dv("nombre_articles", str(n_articles if n_articles is not None else len(montants))), **kw,
    )


def test_b3_conforme_arrondi():
    # 3 × 33,33 = 99,99 contre 100,00 : 0,01 ≤ T_SOMME(3) = 0,03.
    (r,) = b3_somme_montants_articles(contexte([dec_b3(["33.33"] * 3, "100.00")]))
    assert r.outcome is Outcome.conforme


def test_b3_ecart_certain_eur():
    (r,) = b3_somme_montants_articles(contexte([dec_b3(["1000.00", "250.00"], "1520.00")]))
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("270.00")
    assert "1 520,00 EUR" in esp(r.constat.libelle) and "1 250,00 EUR" in esp(r.constat.libelle)
    textes_propres(r)


def test_b3_devise_convertie_au_taux_imprime():
    d = dec_b3(["1000.00", "250.00"], "1350.00", devise="USD",
               taux_change=dv("taux_change", "1.25000"), taux_change_sens=dv("taux_change_sens", "devise_par_eur"))
    (r,) = b3_somme_montants_articles(contexte([d]))
    assert r.outcome is Outcome.ecart_certain
    assert r.constat.montant_en_jeu == D("80.00")  # 100 USD / 1,25
    assert RaisonCode.montant_converti in r.constat.raisons
    assert "1 350,00 USD" in esp(r.constat.libelle)


def test_b3_sans_taux_montant_nul_et_a_verifier():
    (r,) = b3_somme_montants_articles(contexte([dec_b3(["1000.00"], "1100.00", devise="USD")]))
    assert r.outcome is Outcome.a_verifier and r.constat.montant_en_jeu is None


def test_b3_articles_incomplets():
    d = dec_b3(["10.00"], "20.00")
    d.dec.articles.append(art("2"))
    (r,) = b3_somme_montants_articles(contexte([d]))
    assert r.outcome is Outcome.non_verifiable


def test_b3_non_applicable_sans_montants():
    d = declaration(id=DEC, articles=[art("1")])
    (r,) = b3_somme_montants_articles(contexte([d]))
    assert r.outcome is Outcome.non_applicable


# --- B4 ------------------------------------------------------------------------------------------------


def test_b4_nette_superieure_a_brute_certain():
    d = declaration(id=DEC, articles=[art("1", masse_nette="120.0", masse_brute="100.0")])
    (r,) = b4_masses(contexte([d]))
    assert r.sous_controle == "nette_brute" and r.outcome is Outcome.ecart_certain
    assert r.constat.montant_en_jeu is None and "(120 kg)" in esp(r.constat.libelle) and "(0,6 kg)" in esp(r.constat.libelle)
    textes_propres(r)


def test_b4_tolerance_masse():
    # T_MASSE = max(0,5 kg ; 0,5 %) : 100,4 contre 100 -> conforme ; 100,6 -> constat.
    d = declaration(id=DEC, articles=[art("1", masse_nette="100.4", masse_brute="100.0")])
    assert b4_masses(contexte([d]))[0].outcome is Outcome.conforme
    d = declaration(id=DEC, articles=[art("1", masse_nette="100.6", masse_brute="100.0")])
    assert b4_masses(contexte([d]))[0].outcome is Outcome.ecart_certain


def test_b4_somme_brute_a_verifier_seulement():
    d = declaration(id=DEC, masse_brute_totale=dv("masse_brute_totale", "500.0"),
                    articles=[art("1", masse_nette="90", masse_brute="100"),
                              art("2", masse_nette="90", masse_brute="100")])
    rs = b4_masses(contexte([d]))
    (somme,) = par_sous(rs, "somme_brute")
    assert somme.outcome is Outcome.a_verifier
    assert RaisonCode.controle_signal_seulement in somme.constat.raisons
    (tot,) = par_sous(rs, "nette_total")
    assert tot.outcome is Outcome.conforme
    assert [r.outcome for r in par_sous(rs, "nette_brute")] == [Outcome.conforme, Outcome.conforme]


def test_b4_nette_totale_superieure():
    d = declaration(id=DEC, masse_brute_totale=dv("masse_brute_totale", "150"),
                    articles=[art("1", masse_nette="100"), art("2", masse_nette="100")])
    (tot,) = par_sous(b4_masses(contexte([d])), "nette_total")
    assert tot.outcome is Outcome.ecart_certain


def test_b4_total_consequence_d_un_article_deja_constate_pas_de_second_constat():
    # D-2201 : article 1 nette 3,715 > brute 0,715 (constaté) ; au total Σ nettes 7,195 > brute 4,517, mais sans
    # l'excédent de l'article 1 (3,000) le total tient : un seul constat pour un seul fait.
    d = declaration(id=DEC, masse_brute_totale=dv("masse_brute_totale", "4.517"),
                    articles=[art("1", masse_nette="3.715", masse_brute="0.715"),
                              art("2", masse_nette="3.000", masse_brute="3.291"),
                              art("3", masse_nette="0.480", masse_brute="0.511")])
    rs = b4_masses(contexte([d]))
    assert [r.outcome for r in par_sous(rs, "nette_brute")] == [Outcome.ecart_certain, Outcome.conforme,
                                                                  Outcome.conforme]
    (tot,) = par_sous(rs, "nette_total")
    assert tot.outcome is Outcome.non_applicable and tot.raison_code is RaisonCode.couvert_par_autre_controle
    # Un article seul : même fait au total et sur l'article.
    d = declaration(id=DEC, masse_brute_totale=dv("masse_brute_totale", "281.765"),
                    articles=[art("1", masse_nette="287.4", masse_brute="281.765")])
    rs = b4_masses(contexte([d]))
    assert [r.outcome for r in rs if r.outcome.est_constat] == [Outcome.ecart_certain]


def test_b4_total_au_dela_des_articles_constates_reste_constate():
    # L'excédent au total dépasse celui des articles constatés : le total garde son propre constat.
    d = declaration(id=DEC, masse_brute_totale=dv("masse_brute_totale", "100"),
                    articles=[art("1", masse_nette="60", masse_brute="50"), art("2", masse_nette="80")])
    (tot,) = par_sous(b4_masses(contexte([d])), "nette_total")
    assert tot.outcome is Outcome.ecart_certain


def test_b4_sans_masse():
    (r,) = b4_masses(contexte([declaration(id=DEC, articles=[art("1")])]))
    assert r.outcome is Outcome.non_applicable


# --- B5 ------------------------------------------------------------------------------------------------


def test_b5():
    d = declaration(id=DEC, nombre_colis_total=dv("nombre_colis_total", "5"),
                    articles=[art("1", nombre_colis="2"), art("2", nombre_colis="3")])
    assert b5_colis(contexte([d]))[0].outcome is Outcome.conforme
    d = declaration(id=DEC, nombre_colis_total=dv("nombre_colis_total", "6"),
                    articles=[art("1", nombre_colis="2"), art("2", nombre_colis="3")])
    (r,) = b5_colis(contexte([d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.controle_signal_seulement in r.constat.raisons
    textes_propres(r)
    d = declaration(id=DEC, articles=[art("1", nombre_colis="2")])
    assert b5_colis(contexte([d]))[0].outcome is Outcome.non_applicable
    d = declaration(id=DEC, nombre_colis_total=dv("nombre_colis_total", "6"),
                    articles=[art("1", nombre_colis="2"), art("2")])
    assert b5_colis(contexte([d]))[0].outcome is Outcome.non_verifiable


# --- moteur et B1 inchangé ------------------------------------------------------------------------------


def test_moteur_et_b1_inchange():
    d = dec_b2(taxation(DEC, article="3", base="2091.00", taux="2.5", montant="418.20"), total="418.20")
    ctx = contexte([d])
    (b1,) = b1_base_taux_montant(ctx)
    assert b1.outcome is Outcome.ecart_certain and b1.constat.montant_en_jeu == D("365.93")
    rs = run_controls(ctx, controles=["B1", "B2", "B3", "B4", "B5"])
    assert {r.controle_id for r in rs} == {"B1", "B2", "B3", "B4", "B5"}
    for r in rs:
        if r.constat is not None:
            assert r.constat.motif_blocage is None
