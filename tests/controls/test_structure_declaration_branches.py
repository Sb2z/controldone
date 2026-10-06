"""Structure lue d'une déclaration : branches non couvertes avant D-3902 (nature du taux déduite, numéros
d'article, nombre d'articles illisible, masses brutes partiellement lues). Données FICTIVES."""

from __future__ import annotations

from controldone.controls._aides_befg import num
from controldone.controls.structure_declaration import _nature_taux, motifs_structure_masses, numero_article
from controldone.model import ArticleDeclaration, TauxNature
from controldone.testing import contexte, declaration, taxation, vs

DEC = "doc_dec_fictif_br"


def dv(champ, val, **kw):
    return vs(f"declaration.{champ}", val, document_id=DEC, **kw)


def art(numero, **champs):
    return ArticleDeclaration(
        numero_article=dv("articles[].numero_article", numero),
        **{k: dv(f"articles[].{k}", v) for k, v in champs.items()},
    )


def _masses(*articles, total=None, nombre=None):
    champs = {"articles": list(articles)}
    if total is not None:
        champs["masse_brute_totale"] = dv("masse_brute_totale", total)
    if nombre is not None:
        champs["nombre_articles"] = dv("nombre_articles", nombre)
    d = declaration(id=DEC, **champs)
    return motifs_structure_masses(d, num, contexte([d]).tol)


def test_nature_du_taux_deduite_des_bases_lues():
    assert _nature_taux(taxation(DEC, base="100", nature=None)) is TauxNature.ad_valorem
    assert _nature_taux(taxation(DEC, base_quantite="12", nature=None)) is TauxNature.specifique
    assert _nature_taux(taxation(DEC, base="100", base_quantite="12", nature=None)) is None
    assert _nature_taux(taxation(DEC, nature=None)) is None
    assert _nature_taux(taxation(DEC, base="100", nature=TauxNature.specifique)) is TauxNature.specifique


def test_numero_article_normalise():
    assert numero_article(None) == ""
    assert numero_article(dv("articles[].numero_article", "007")) == "7"
    assert numero_article(dv("articles[].numero_article", "000")) == "0"
    assert numero_article(dv("articles[].numero_article", " 2a ")) == "2A"


def test_masses_coherentes_sans_motif():
    assert _masses(art("1", masse_brute="10"), art("2", masse_brute="15"), total="25", nombre="2") == []


def test_nombre_d_articles_illisible_ou_different():
    assert any(
        "nombre d'articles" in m for m in _masses(art("1", masse_brute="10"), total="10", nombre="trois")
    )
    assert any("nombre d'articles" in m for m in _masses(art("1", masse_brute="10"), total="10", nombre="2"))


def test_masses_brutes_partiellement_lues():
    # total inférieur aux seules masses lues : impossible, la lecture est en cause
    m = _masses(art("1", masse_brute="30"), art("2"), total="20")
    assert any("inférieure aux masses brutes" in x for x in m)
    # total qui reprend la masse d'un seul article (les autres non lues)
    m = _masses(art("1", masse_brute="20"), art("2"), total="20")
    assert any("un seul article" in x for x in m)
    # total supérieur aux masses lues, article non lu : rien à opposer
    assert _masses(art("1", masse_brute="10"), art("2"), total="25") == []


def test_masse_brute_totale_differente_de_la_somme():
    m = _masses(art("1", masse_brute="10"), art("2", masse_brute="15"), total="40")
    assert any("diffère de la somme" in x for x in m)


def test_articles_en_double():
    m = _masses(art("1", masse_brute="10"), art("01", masse_brute="10"), total="20")
    assert any(x.startswith("articles") for x in m)
