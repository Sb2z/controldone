"""Famille G — petits envois, droit forfaitaire par article (SPEC §16). Données fictives."""

from decimal import Decimal as D

import pytest

from controldone.controls.famille_g import (
    ACTION_G_RENVOI,
    g1_nombre_articles_montant,
    g2_base_nombre_articles,
    g3_base_codes_distincts,
    g4_forfait_refacture,
    g5_base_refacturation,
    g6_applicabilite,
)
from controldone.controls.framework import run_controls
from controldone.guardrails import PHRASE_RENVOI, check_text
from controldone.model import (
    ArticleDeclaration,
    CategorieTaxe,
    ChampsAvoir,
    LigneFactureTransitaire,
    Methode,
    NatureLigne,
    NatureMontant,
    Outcome,
    ParametresPetitsEnvois,
    Partie,
    QualiteTexte,
    RaisonCode,
    TauxNature,
    TypeDocument,
)
from controldone.testing import contexte, declaration, document, facture_transitaire, taxation, vs

DEC, FT, AV = "doc_dec1", "doc_ft1", "doc_av1"
MRN = "26FR00000000000001"
CODES = ("6109100010", "6109100090", "6203420000")


def esp(s):
    return s.replace("\xa0", " ")


def dv(champ, val, doc=DEC, **kw):
    return vs(f"declaration.{champ}", val, document_id=doc, **kw)


def forfait(base="3", taux="3.00", montant="9.00", *, doc=DEC, **kw):
    return taxation(
        doc,
        article=None,
        type_taxe="F00",
        categorie=CategorieTaxe.forfait_petits_envois,
        base_quantite=base,
        taux=taux,
        montant=montant,
        nature=TauxNature.specifique,
        **kw,
    )


def dec_g(
    *taxes, n_articles="3", codes=CODES, date_acc="2026-08-01", devise="EUR", total="120.00", doc=DEC, **kw
):
    arts = [
        ArticleDeclaration(
            numero_article=dv("articles[].numero_article", str(i + 1), doc),
            code_marchandise=dv("articles[].code_marchandise", c, doc),
        )
        for i, c in enumerate(codes)
    ]
    champs = dict(articles=arts)
    if n_articles is not None:
        champs["nombre_articles"] = dv("nombre_articles", n_articles, doc)
    if date_acc is not None:
        champs["date_acceptation"] = dv("date_acceptation", date_acc, doc)
    if total is not None:
        champs["montant_total_facture"] = dv("montant_total_facture", total, doc)
        champs["devise_facture"] = dv("devise_facture", devise, doc)
    champs.update(kw)
    return declaration(id=doc, mrn=MRN, taxations=list(taxes or [forfait()]), **champs)


def ftv(champ, val, doc=FT):
    return vs(f"facture_transitaire.{champ}", val, document_id=doc)


def ligne_ft(
    montant, nature=NatureLigne.debours_forfait_petits_envois, *, quantite=None, pu=None, mrn=MRN, doc=FT
):
    return LigneFactureTransitaire(
        nature=nature,
        montant_ht=ftv("lignes[].montant_ht", montant, doc),
        quantite=ftv("lignes[].quantite", quantite, doc) if quantite else None,
        prix_unitaire=ftv("lignes[].prix_unitaire", pu, doc) if pu else None,
        mrn=ftv("lignes[].mrn", mrn, doc) if mrn else None,
    )


def ft_g(*lignes, numero="FT-001"):
    return facture_transitaire(
        id=FT,
        numero=ftv("numero", numero),
        date=ftv("date", "2026-08-05"),
        emetteur=Partie(nom=ftv("emetteur.nom", "Transit Fictif SA")),
        lignes=list(lignes),
    )


def avoir_g(montant, nature=NatureLigne.debours_forfait_petits_envois):
    def av(champ, val):
        return vs(f"avoir.{champ}", val, document_id=AV)

    c = ChampsAvoir(
        numero=av("numero", "AV-001"),
        date=av("date", "2026-09-01"),
        emetteur=Partie(nom=av("emetteur.nom", "Transit Fictif SA")),
        refs_facture_origine=[av("refs_facture_origine[]", "FT-001")],
        lignes=[LigneFactureTransitaire(nature=nature, montant_ht=av("lignes[].montant_ht", montant))],
    )
    return document(TypeDocument.avoir, c, id=AV)


def propre(r):
    assert check_text(r.constat.libelle) == [] and check_text(r.constat.prochaine_action) == []
    assert "droit du" not in r.constat.libelle.lower()


# --- absence de forfait ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [
        g1_nombre_articles_montant,
        g2_base_nombre_articles,
        g3_base_codes_distincts,
        g4_forfait_refacture,
        g5_base_refacturation,
        g6_applicabilite,
    ],
)
def test_sans_forfait_non_applicable(fn):
    d = dec_g(taxation(DEC, base="100", taux="10", montant="10.00"))
    (r,) = fn(contexte([d]))
    assert r.outcome is Outcome.non_applicable
    (r,) = fn(contexte([]))
    assert r.outcome is Outcome.non_verifiable


def test_detection_par_code_configure():
    t = taxation(
        DEC,
        article=None,
        type_taxe="Q99",
        categorie=CategorieTaxe.inconnue,
        base_quantite="3",
        taux="3.00",
        montant="9.00",
        nature=TauxNature.specifique,
    )
    params = ParametresPetitsEnvois(codes_forfait_petits_envois=["Q99"])
    (r,) = g1_nombre_articles_montant(contexte([dec_g(t)], parametres_petits_envois=params))
    assert r.outcome is Outcome.conforme


# --- G1 ---------------------------------------------------------------------------------------------------


def test_g1():
    (r,) = g1_nombre_articles_montant(contexte([dec_g(forfait())]))
    assert r.outcome is Outcome.conforme
    (r,) = g1_nombre_articles_montant(contexte([dec_g(forfait(montant="15.00"))]))
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("6.00")
    assert r.constat.nature_montant is NatureMontant.arithmetique_declaration
    assert "3 × 3,00 EUR = 9,00 EUR" in esp(r.constat.libelle) and PHRASE_RENVOI in r.constat.prochaine_action
    propre(r)
    # Piège d'arrondi : tolérance 0,01 EUR stricte (pas d'arrondi à l'euro admis comme en B1).
    (r,) = g1_nombre_articles_montant(contexte([dec_g(forfait(base="3", taux="2.995", montant="8.99"))]))
    assert r.outcome is Outcome.conforme  # 8,985 -> 0,005
    (r,) = g1_nombre_articles_montant(contexte([dec_g(forfait(montant="9.50"))]))
    assert r.outcome is Outcome.a_verifier and r.constat.raisons == [RaisonCode.ecart_sous_seuil]
    (r,) = g1_nombre_articles_montant(contexte([dec_g(forfait(taux=None))]))
    assert r.outcome is Outcome.non_verifiable


def test_g1_lecture_douteuse():
    t = forfait(montant="99.00", methode=Methode.ocr, brut_montant="99,00")
    (r,) = g1_nombre_articles_montant(contexte([dec_g(t, qualite=QualiteTexte.ocr)]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.lecture_douteuse in r.constat.raisons


# --- G2 ---------------------------------------------------------------------------------------------------


def test_g2():
    (r,) = g2_base_nombre_articles(contexte([dec_g(forfait())]))
    assert r.outcome is Outcome.conforme
    (r,) = g2_base_nombre_articles(contexte([dec_g(forfait(base="5", montant="15.00"))]))
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("6.00")
    assert "(5 articles)" in r.constat.libelle and PHRASE_RENVOI in r.constat.prochaine_action
    propre(r)


def test_g2_blocs_articles_jamais_certain():
    (r,) = g2_base_nombre_articles(contexte([dec_g(forfait(base="5", montant="15.00"), n_articles=None)]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.valeur_absente in r.constat.raisons
    assert r.details["source_nombre_articles"] == "blocs_articles"


def test_g2_versions_rectificatives():
    v1 = dec_g(forfait(base="5", montant="15.00", doc="doc_v1"), doc="doc_v1", version="1")
    v2 = dec_g(forfait(doc="doc_v2"), doc="doc_v2", version="2")
    rs = g2_base_nombre_articles(contexte([v1, v2]))
    assert len(rs) == 1 and rs[0].outcome is Outcome.conforme and rs[0].documents_concernes == ["doc_v2"]


# --- G3 ---------------------------------------------------------------------------------------------------


def test_g3_renvoi():
    for base in ("3", "2"):  # 3 codes complets distincts, 2 codes à 6 chiffres
        (r,) = g3_base_codes_distincts(contexte([dec_g(forfait(base=base))]))
        assert r.outcome is Outcome.conforme, base
    (r,) = g3_base_codes_distincts(contexte([dec_g(forfait(base="5", montant="15.00"))]))
    c = r.constat
    assert r.outcome is Outcome.a_verifier and c.renvoi and c.montant_en_jeu is None
    assert c.nature_montant is NatureMontant.renvoi and RaisonCode.renvoi_reglementaire in c.raisons
    assert c.prochaine_action == ACTION_G_RENVOI and PHRASE_RENVOI in c.prochaine_action
    assert "3 en code complet, 2 à 6 chiffres" in c.libelle
    propre(r)


def test_g3_code_illisible():
    d = dec_g(forfait(), codes=("6109100010", "61"))
    (r,) = g3_base_codes_distincts(contexte([d]))
    assert r.outcome is Outcome.non_verifiable


# --- G4 ---------------------------------------------------------------------------------------------------


def test_g4_conforme_et_ecart():
    (r,) = g4_forfait_refacture(contexte([dec_g(), ft_g(ligne_ft("9.00"))]))
    assert r.outcome is Outcome.conforme and r.unite == f"dec:{DEC}|ft:{FT}"
    (r,) = g4_forfait_refacture(contexte([dec_g(), ft_g(ligne_ft("15.00"))]))
    c = r.constat
    assert r.outcome is Outcome.ecart_certain and c.montant_en_jeu == D("6.00")
    assert c.nature_montant is NatureMontant.recouvrable and c.sens.value == "defaveur_client"
    assert "montant liquidé indiqué sur la déclaration" in c.libelle
    propre(r)


def test_g4_t_debours_et_seuil():
    (r,) = g4_forfait_refacture(contexte([dec_g(), ft_g(ligne_ft("9.05"))]))
    assert r.outcome is Outcome.conforme  # T_DEBOURS = 0,05
    (r,) = g4_forfait_refacture(contexte([dec_g(), ft_g(ligne_ft("9.80"))]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.ecart_sous_seuil in r.constat.raisons


def test_g4_en_faveur_du_client():
    (r,) = g4_forfait_refacture(contexte([dec_g(), ft_g(ligne_ft("3.00"))]))
    assert r.outcome is Outcome.a_verifier and r.constat.montant_en_jeu == D("-6.00")
    assert RaisonCode.ecart_en_faveur_client in r.constat.raisons


def test_g4_net_des_avoirs():
    (r,) = g4_forfait_refacture(contexte([dec_g(), ft_g(ligne_ft("15.00")), avoir_g("6.00")]))
    assert r.outcome is Outcome.conforme and r.details["credit_impute"] == "6.00"
    (r,) = g4_forfait_refacture(contexte([dec_g(), ft_g(ligne_ft("15.00")), avoir_g("4.00")]))
    assert r.outcome is Outcome.ecart_certain
    assert r.constat.montant_en_jeu == D("2.00") and r.constat.montant_brut == D("6.00")


def test_g4_ligne_de_droits_si_seul_droit():
    (r,) = g4_forfait_refacture(contexte([dec_g(), ft_g(ligne_ft("15.00", NatureLigne.debours_droits))]))
    assert r.outcome is Outcome.ecart_certain and r.details["nature_refacturee"] == "debours_droits"
    # la déclaration porte aussi un droit ad valorem : la ligne de droits n'est pas prise pour le forfait
    d = dec_g(forfait(), taxation(DEC, base="100", taux="10", montant="10.00"))
    (r,) = g4_forfait_refacture(contexte([d, ft_g(ligne_ft("15.00", NatureLigne.debours_droits))]))
    assert r.outcome is Outcome.a_verifier and r.constat.montant_en_jeu == D("-9.00")


def test_g4_sans_facture_transitaire():
    (r,) = g4_forfait_refacture(contexte([dec_g()]))
    assert r.outcome is Outcome.non_applicable and r.raison_code is RaisonCode.facture_transitaire_absente


# --- G5 ---------------------------------------------------------------------------------------------------


def test_g5_base_du_transitaire():
    ft = ft_g(ligne_ft("15.00", quantite="5", pu="3.00"))
    (r,) = g5_base_refacturation(contexte([dec_g(), ft]))
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("6.00")
    assert "5 × 3,00 EUR" in esp(r.constat.libelle)
    propre(r)
    (r,) = g5_base_refacturation(contexte([dec_g(), ft_g(ligne_ft("9.00", quantite="3", pu="3.00"))]))
    assert r.outcome is Outcome.conforme
    # ligne sans base imprimée : G5 ne s'applique pas
    (r,) = g5_base_refacturation(contexte([dec_g(), ft_g(ligne_ft("9.00"))]))
    assert r.outcome is Outcome.non_applicable


def test_g4_g5_pas_de_double_comptage():
    ctx = contexte([dec_g(), ft_g(ligne_ft("15.00", quantite="5", pu="3.00"))])
    rs = {r.controle_id: r for r in run_controls(ctx, controles=["G4", "G5"])}
    assert rs["G4"].constat.montant_en_jeu == D("6.00")
    assert (
        rs["G5"].constat.montant_en_jeu is None and RaisonCode.doublon_composantes in rs["G5"].constat.raisons
    )


# --- G6 ---------------------------------------------------------------------------------------------------


def test_g6_conforme_et_non_verifiable():
    (r,) = g6_applicabilite(contexte([dec_g()]))
    assert r.outcome is Outcome.conforme
    (r,) = g6_applicabilite(contexte([dec_g(date_acc=None, total=None)]))
    assert r.outcome is Outcome.non_verifiable


def test_g6_date_hors_periode():
    (r,) = g6_applicabilite(contexte([dec_g(date_acc="2026-06-30")]))
    c = r.constat
    assert r.outcome is Outcome.a_verifier and c.renvoi and c.montant_en_jeu is None
    assert "30/06/2026" in c.libelle and PHRASE_RENVOI in c.prochaine_action
    propre(r)


def test_g6_seuil_converti_au_taux_imprime():
    def d(total):
        return dec_g(
            devise="USD",
            total=total,
            taux_change=dv("taux_change", "1.10000"),
            taux_change_sens=dv("taux_change_sens", "devise_par_eur"),
        )

    (r,) = g6_applicabilite(contexte([d("160.00")]))  # 145,45 EUR
    assert r.outcome is Outcome.conforme
    (r,) = g6_applicabilite(contexte([d("180.00")]))  # 163,64 EUR > 150
    assert r.outcome is Outcome.a_verifier and r.constat.renvoi
    assert "163,64 EUR au taux imprimé" in esp(r.constat.libelle) and "150,00 EUR" in esp(r.constat.libelle)
    propre(r)
    # sans taux imprimé ni date lisible : impossible de conclure
    (r,) = g6_applicabilite(contexte([dec_g(devise="USD", total="180.00", date_acc=None)]))
    assert r.outcome is Outcome.non_verifiable
