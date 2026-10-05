"""Structure lue d'une déclaration (D-2210) : un « écart certain » de B2 ou B4 repose sur un tableau dont la
disposition lue est validée. Données fictives : chaque test reproduit un mode d'assemblage faux (ligne
d'article prise pour un total de catégorie, montant rangé sous un autre code, copie fusionnée, lignes d'une
seule page, masse brute d'un article prise pour le total), puis le cas vrai, qui reste certain."""

from decimal import Decimal as D

from controldone.controls._aides_befg import num
from controldone.controls.famille_b import b2_sommes_taxes, b4_masses
from controldone.controls.structure_declaration import (
    motifs_structure_masses,
    motifs_structure_taxes,
    totaux_par_categorie,
)
from controldone.guardrails import check_text
from controldone.model import ArticleDeclaration, CategorieTaxe, Outcome, PaiementNormalise, RaisonCode
from controldone.model.enums import RAISON_LIBELLES
from controldone.testing import contexte, declaration, taxation, vs

DEC = "doc_dec_fictif"


def dv(champ, val, **kw):
    return vs(f"declaration.{champ}", val, document_id=DEC, **kw)


def art(numero, **champs):
    return ArticleDeclaration(
        numero_article=dv("articles[].numero_article", numero) if numero else None,
        **{k: dv(f"articles[].{k}", v) for k, v in champs.items()},
    )


def droit(article, base, taux, montant, **kw):
    return taxation(DEC, article=article, type_taxe="A00", categorie=CategorieTaxe.droit, base=base, taux=taux,
                    montant=montant, paiement=PaiementNormalise.differe, **kw)


def tva(article, base, montant, **kw):
    return taxation(DEC, article=article, type_taxe="B00", categorie=CategorieTaxe.tva, base=base, taux="20",
                    montant=montant, paiement=PaiementNormalise.differe, **kw)


def dec(*taxations, total=None, n=None, articles=(), **champs):
    if total is not None:
        champs["total_droits_taxes"] = dv("total_droits_taxes", total)
    if n is not None:
        champs["nombre_articles"] = dv("nombre_articles", str(n))
    return declaration(id=DEC, taxations=list(taxations), articles=list(articles), **champs)


def constats(rs):
    return [r for r in rs if r.constat is not None]


def tol():
    return contexte([]).tol


# --- Raison ------------------------------------------------------------------------------------------


def test_libelle_raison_structure():
    lib = RAISON_LIBELLES[RaisonCode.structure_non_validee]
    assert lib.startswith("à vérifier") and check_text(lib) == []


# --- B2 : total de catégorie ---------------------------------------------------------------------------


def _quatre_articles(tva_art4_numero):
    # Article 4 : numéro non lu sur la ligne B00 (OCR) ; total des droits et taxes = Σ des 8 lignes.
    return dec(
        droit("1", "1000.00", "5", "50.00"), tva("1", "1050.00", "210.00"),
        droit("2", "500.00", "2", "10.00"), tva("2", "510.00", "102.00"),
        droit("3", "300.00", "4", "12.00"), tva("3", "312.00", "62.40"),
        droit("4", "2000.00", "3", "60.00"), tva(tva_art4_numero, "2060.00", "412.00"),
        total="918.40", n=4, articles=[art(str(k)) for k in range(1, 5)],
    )


def test_ligne_d_article_sans_numero_n_est_pas_un_total_de_categorie():
    d = _quatre_articles(None)
    assert totaux_par_categorie(d, num, tol()) == {}
    rs = b2_sommes_taxes(contexte([d]))
    assert [r.sous_controle for r in rs] == ["total"] and rs[0].outcome is Outcome.conforme


def test_vrai_total_de_categorie_faux_reste_certain():
    # Le code couvre tous les articles : la ligne sans article est bien le total A00 (imprimé 140, Σ 130).
    d = dec(
        droit("1", "1000.00", "5", "50.00"), droit("2", "2000.00", "4", "80.00"),
        droit(None, "3000.00", None, "140.00"),
        total="130.00", n=2, articles=[art("1"), art("2")],
    )
    (cat,) = [r for r in b2_sommes_taxes(contexte([d])) if r.sous_controle == "categorie"]
    assert cat.outcome is Outcome.ecart_certain and cat.constat.montant_en_jeu == D("10.00")


def test_total_de_categorie_dont_la_base_ne_reprend_pas_les_lignes():
    # Montants de droit rangés sous B00 : la base imprimée du total B00 n'est pas Σ bases des lignes « B00 ».
    d = dec(
        tva("1", "1000.00", "200.00"), tva("2", "500.00", "100.00"),
        tva(None, "59.35", "11.87"),
        n=2, articles=[art("1"), art("2")],
    )
    (cat,) = [r for r in b2_sommes_taxes(contexte([d])) if r.sous_controle == "categorie"]
    assert cat.outcome is Outcome.a_verifier
    assert RaisonCode.structure_non_validee in cat.constat.raisons
    assert any("base" in m for m in cat.details["structure_non_validee"])


def test_code_sans_ligne_pour_un_article_categorie_a_verifier():
    # A00 n'a pas de ligne pour l'article 3 (les autres codes en ont) : la ligne sans article peut être la sienne.
    d = dec(
        droit("1", "100.00", "5", "5.00"), droit("2", "100.00", "5", "5.00"), droit(None, "300.00", "5", "15.00"),
        tva("1", "105.00", "21.00"), tva("2", "105.00", "21.00"), tva("3", "315.00", "63.00"),
        n=3, articles=[art("1"), art("2"), art("3")],
    )
    (cat,) = [r for r in b2_sommes_taxes(contexte([d])) if r.sous_controle == "categorie"]
    assert cat.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in cat.constat.raisons


# --- B2 : total de la déclaration ----------------------------------------------------------------------


def test_ligne_dont_le_montant_ne_suit_pas_base_fois_taux():
    # Montant de droit lu dans la colonne voisine : la ligne ne vérifie pas base × taux = montant.
    d = dec(droit("1", "100.00", "5", "5.00"), tva("1", "105.00", "2100.00"),
            total="26.00", n=1, articles=[art("1")])
    (r,) = constats(b2_sommes_taxes(contexte([d])))
    assert r.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in r.constat.raisons


def test_copie_fusionnee_lignes_en_double():
    # Deux copies de la même déclaration lues comme une seule : chaque (article, code) apparaît deux fois.
    lignes = [droit("1", "500.00", "0", "0.00"), tva("1", "500.00", "100.00"),
              droit("2", "300.00", "0", "0.00"), tva("2", "300.00", "60.00")]
    d = dec(*lignes, *[droit("1", "500.00", "0", "0.00", page=2), tva("1", "500.00", "100.00", page=2),
                       droit("2", "300.00", "0", "0.00", page=2), tva("2", "300.00", "60.00", page=2)],
            total="160.00", n=2, articles=[art("1"), art("2"), art("1"), art("2")])
    (r,) = constats(b2_sommes_taxes(contexte([d])))
    assert r.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in r.constat.raisons
    assert motifs_structure_taxes(d, list(range(8)), num, tol())


def test_lignes_d_une_seule_page_contre_le_total_de_toutes_les_pages():
    # Déclaration de 3 pages : seules les lignes des articles 3 et 4 (dernière page) sont lues.
    d = dec(droit("3", "1000.00", "2", "20.00", page=3), tva("3", "1020.00", "204.00", page=3),
            droit("4", "500.00", "2", "10.00", page=3), tva("4", "510.00", "102.00", page=3),
            total="2947.08", n=4, articles=[art(str(k)) for k in range(1, 5)])
    (r,) = constats(b2_sommes_taxes(contexte([d])))
    assert r.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in r.constat.raisons
    assert any("1, 2" in m for m in r.details["structure_non_validee"])


def test_vrai_total_faux_reste_certain():
    d = dec(droit("1", "1000.00", "5", "50.00"), tva("1", "1050.00", "210.00"),
            droit("2", "200.00", "5", "10.00"), tva("2", "210.00", "42.00"),
            total="412.00", n=2, articles=[art("1"), art("2")])
    (r,) = constats(b2_sommes_taxes(contexte([d])))
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("100.00")
    assert "structure_non_validee" not in r.details


# --- B4 au total ---------------------------------------------------------------------------------------


def _nette_total(d):
    (r,) = [r for r in b4_masses(contexte([d])) if r.sous_controle == "nette_total"]
    return r


def test_masse_brute_totale_lue_sur_la_ligne_d_un_article():
    # Masse brute « totale » = celle de l'article 2 : Σ brutes des articles (80) ne la retrouve pas.
    d = declaration(id=DEC, masse_brute_totale=dv("masse_brute_totale", "50"), nombre_articles=dv("nombre_articles", "2"),
                    articles=[art("1", masse_nette="29.6", masse_brute="30"), art("2", masse_nette="49.6",
                                                                                  masse_brute="50")])
    r = _nette_total(d)
    assert r.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in r.constat.raisons


def test_masses_d_une_copie_fusionnee():
    arts = [art("1", masse_nette="27.5", masse_brute="39.385"), art("2", masse_nette="12.4", masse_brute="13.913")]
    d = declaration(id=DEC, masse_brute_totale=dv("masse_brute_totale", "53.298"),
                    nombre_articles=dv("nombre_articles", "2"), articles=arts + arts)
    r = _nette_total(d)
    assert r.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in r.constat.raisons
    assert motifs_structure_masses(d, num, tol())


def test_nette_totale_sans_masses_brutes_d_articles_reste_certaine():
    d = declaration(id=DEC, masse_brute_totale=dv("masse_brute_totale", "150"), nombre_articles=dv("nombre_articles", "2"),
                    articles=[art("1", masse_nette="100"), art("2", masse_nette="100")])
    assert _nette_total(d).outcome is Outcome.ecart_certain


def test_total_negatif_imprime_ne_fonde_pas_un_ecart_certain():
    # D-2711 : « -83,69 » au lieu de « 83,69 » (tiret lu comme signe) sur une déclaration d'import.
    d = dec(droit("1", "1000.00", "5", "50.00"), tva("1", "1050.00", "210.00"),
            total="-83.69", n=1, articles=[art("1")])
    (r,) = constats(b2_sommes_taxes(contexte([d])))
    assert r.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in r.constat.raisons
    assert any("négatif" in m for m in r.details["structure_non_validee"])
