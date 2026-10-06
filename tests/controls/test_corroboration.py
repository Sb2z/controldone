"""Lecture corroborée (D-1700) : une lecture fausse sur une mise en page inconnue ne devient jamais un
« écart certain ». Données fictives : chaque test reproduit un mode de lecture fausse observé sur un corpus de
mises en page inconnues (séparateur de milliers perdu, colonne « à payer » prise pour le montant, lignes non
lues, colonne voisine), puis le cas vrai correspondant, qui reste certain."""

from decimal import Decimal as D

from controldone.controls import corroboration
from controldone.controls.famille_b import b1_base_taux_montant, b2_sommes_taxes, b3_somme_montants_articles
from controldone.controls.famille_c import c5_total_debours
from controldone.controls.famille_d import d1_arithmetique
from controldone.guardrails import check_text
from controldone.model import (
    ArticleDeclaration,
    CategorieTaxe,
    LigneFactureTransitaire,
    NatureLigne,
    Outcome,
    PaiementNormalise,
    RaisonCode,
    Zone,
)
from controldone.model.enums import RAISON_LIBELLES
from controldone.testing import contexte, declaration, facture_transitaire, taxation, vs

DEC = "doc_dec1"
FT = "doc_ft1"


def _tva(article, base, montant, *, paiement=PaiementNormalise.differe, **kw):
    return taxation(DEC, article=article, type_taxe="B00", categorie=CategorieTaxe.tva, base=base, taux="20",
                    montant=montant, paiement=paiement, **kw)


def _droit(article, base, taux, montant, **kw):
    return taxation(DEC, article=article, base=base, taux=taux, montant=montant,
                    paiement=PaiementNormalise.differe, **kw)


def _dec(*taxations, total=None, a_payer=None, **champs):
    if total is not None:
        champs["total_droits_taxes"] = vs("declaration.total_droits_taxes", total, document_id=DEC)
    if a_payer is not None:
        champs["total_a_payer"] = vs("declaration.total_a_payer", a_payer, document_id=DEC)
    return declaration(id=DEC, taxations=taxations, **champs)


def _par_unite(rs):
    return {r.unite: r for r in rs}


def _constats(rs):
    return [r for r in rs if r.constat is not None]


# =====================================================================================================
# Déclaration — B1, B2
# =====================================================================================================


def test_libelle_raison():
    lib = RAISON_LIBELLES[RaisonCode.lecture_non_corroboree]
    assert lib.startswith("à vérifier") and check_text(lib) == []


def test_b1_vrai_ecart_confirme_par_le_total():
    """Montant imprimé faux, totaux imprimés qui le reprennent : le montant est confirmé, écart certain."""
    d = _dec(
        _droit("1", "23.84", "2.7", "18.84"),  # 23,84 × 2,7 % = 0,64 : écart vrai
        _tva("1", "24.48", "4.90"),
        _droit("2", "111.58", "2.7", "3.01"),
        _tva("2", "114.59", "22.92"),
        total="49.67",
    )
    rs = [r for r in b1_base_taux_montant(contexte([d])) if r.constat is not None]
    assert len(rs) == 1 and rs[0].outcome is Outcome.ecart_certain


def test_b1_separateur_de_milliers_perdu():
    """« 2 450,57 » lu « 450,57 » : B1 et B2 échouent ensemble ; aucun ne devient certain."""
    d = _dec(
        _droit("1", "111.58", "2.7", "3.01"),
        _tva("1", "12252.83", "450.57"),  # imprimé 2 450,57
        total="2453.58",
        nombre_articles=vs("declaration.nombre_articles", "1", document_id=DEC),
    )
    ctx = contexte([d])
    for r in _constats(b1_base_taux_montant(ctx)):
        assert r.outcome is Outcome.a_verifier
        assert RaisonCode.lecture_non_corroboree in r.constat.raisons
    for r in _constats(b2_sommes_taxes(ctx)):
        # B2 : la ligne sommée ne vérifie pas base × taux = montant, la structure n'est pas validée (D-2210).
        assert r.outcome is Outcome.a_verifier
        assert {RaisonCode.lecture_non_corroboree, RaisonCode.structure_non_validee} & set(r.constat.raisons)


def test_b1_colonne_a_payer_prise_pour_le_montant():
    """TVA autoliquidée : la colonne « à payer » (0,00) lue comme montant. Le total à payer concorde, mais
    il exclut ces lignes : rien ne confirme le 0,00 lu, B1 reste à vérifier."""
    d = _dec(
        _droit("1", "245.88", "6", "14.75"),
        _tva("1", "260.63", "0.00", paiement=PaiementNormalise.autoliquide),
        _droit("2", "684.96", "2.7", "18.49"),
        _tva("2", "703.45", "0.00", paiement=PaiementNormalise.autoliquide),
        total="226.06", a_payer="33.24",
    )
    rs = _constats(b1_base_taux_montant(contexte([d])))
    assert len(rs) == 2
    assert all(r.outcome is Outcome.a_verifier and RaisonCode.lecture_non_corroboree in r.constat.raisons
               for r in rs)


def test_b1_sans_total_imprime_a_verifier():
    d = _dec(_droit("3", "2091.00", "2.5", "418.20"), _droit("4", "100.00", "2.5", "2.50"))
    r = _constats(b1_base_taux_montant(contexte([d])))[0]
    assert r.outcome is Outcome.a_verifier and RaisonCode.lecture_non_corroboree in r.constat.raisons
    # Le même contexte sans l'exigence (tests unitaires de logique) : certain.
    r = _constats(b1_base_taux_montant(contexte([d], exiger_lecture_corroboree=False)))[0]
    assert r.outcome is Outcome.ecart_certain


def test_b1_valeurs_structurees_dispensees():
    d = _dec(_droit("3", "2091.00", "2.5", "418.20", methode="xml_structure", confiance=1.0))
    r = _constats(b1_base_taux_montant(contexte([d])))[0]
    assert r.outcome is Outcome.ecart_certain


def test_b2_vrai_total_faux_lignes_confirmees_par_b1():
    d = _dec(
        _droit("1", "1000.00", "2.7", "27.00"),
        _tva("1", "1027.00", "205.40"),
        a_payer="300.00",  # somme 232,40
        nombre_articles=vs("declaration.nombre_articles", "1", document_id=DEC),
    )
    r = _constats(b2_sommes_taxes(contexte([d])))[0]
    assert r.outcome is Outcome.ecart_certain


# =====================================================================================================
# Déclaration — B3 : colonne des montants facturés
# =====================================================================================================


def _article(n, montant, vstat, *, x_montant=0.50, x_vstat=0.70, methode="texte_natif"):
    def v(nom, val, x):
        return vs(f"declaration.articles[].{nom}", val, document_id=DEC, methode=methode,
                  zone=Zone(x0=x, y0=0.1 * n, x1=x + 0.08, y1=0.1 * n + 0.02))

    return ArticleDeclaration(
        numero_article=vs("declaration.articles[].numero_article", str(n), document_id=DEC),
        montant_facture_article=v("montant_facture_article", montant, x_montant),
        valeur_statistique=v("valeur_statistique", vstat, x_vstat),
    )


def _dec_b3(*articles, total):
    return _dec(
        articles=list(articles),
        montant_total_facture=vs("declaration.montant_total_facture", total, document_id=DEC),
        devise_facture=vs("declaration.devise_facture", "EUR", document_id=DEC),
        nombre_articles=vs("declaration.nombre_articles", str(len(articles)), document_id=DEC),
    )


def test_b3_colonne_voisine_lue():
    """Montants des articles lus dans une colonne voisine (100 partout) : aucun n'est confirmé."""
    d = _dec_b3(_article(1, "100", "4.21"), _article(2, "100", "35.77"), _article(3, "100", "87.30"),
                total="6792.00")
    r = _constats(b3_somme_montants_articles(contexte([d])))[0]
    assert r.outcome is Outcome.a_verifier and RaisonCode.lecture_non_corroboree in r.constat.raisons


def test_b3_vrai_un_article_modifie():
    """Un article augmenté sans changer le total ; les autres sont confirmés par leur valeur statistique."""
    d = _dec_b3(_article(1, "4730.32", "4730.32"), _article(2, "5363.15", "5161.38"),
                _article(3, "7245.78", "7245.78"), total="17137.48")
    r = _constats(b3_somme_montants_articles(contexte([d])))[0]
    assert r.outcome is Outcome.ecart_certain


def test_echo_meme_zone_non_probant():
    """Deux champs lus au même endroit (même colonne lue deux fois) ne se confirment pas."""
    d = _dec_b3(_article(1, "4730.32", "4730.32", x_vstat=0.50), _article(2, "5363.15", "5161.38"),
                total="4730.32")
    reseau = corroboration.reseau(d, lambda v: v is not None, contexte([d]).tol)
    assert not [i for i in reseau if i.genre == "echo"]


# =====================================================================================================
# Facture du transitaire — D1
# =====================================================================================================


def _ligne(nature, montant, *, taux=None, tva=None, quantite=None, pu=None):
    def v(nom, val):
        return None if val is None else vs(f"facture_transitaire.lignes[].{nom}", val, document_id=FT)

    return LigneFactureTransitaire(
        libelle=v("libelle", nature.value), nature=nature, montant_ht=v("montant_ht", montant),
        taux_tva=v("taux_tva", taux), montant_tva=v("montant_tva", tva), quantite=v("quantite", quantite),
        prix_unitaire=v("prix_unitaire", pu),
    )


def _ft(*lignes, **totaux):
    champs = {k: vs(f"facture_transitaire.{k}", x, document_id=FT) for k, x in totaux.items()}
    return facture_transitaire(id=FT, numero=vs("facture_transitaire.numero", "FT-FICTIF-1", document_id=FT),
                               lignes=list(lignes), **champs)


def _d1(f, sous):
    return [r for r in d1_arithmetique(contexte([f])) if r.sous_controle == sous and r.constat is not None]


def test_d1_lignes_de_prestation_non_lues():
    """Seules les lignes de débours ont été lues : le total HT ne peut pas être certain (le total de TVA
    imprimé ne correspond pas aux lignes lues)."""
    f = _ft(_ligne(NatureLigne.debours_droits, "11.17", taux="0", tva="0.00"),
            _ligne(NatureLigne.debours_tva, "74.63", taux="0", tva="0.00"),
            total_debours="85.80", total_ht="268.00", total_tva="36.44", total_ttc="304.44")
    for r in _d1(f, "total_ht"):
        assert r.outcome is not Outcome.ecart_certain


def test_d1_lignes_de_debours_non_lues():
    f = _ft(_ligne(NatureLigne.debours_droits, "65.00", taux="0", tva="0.00"),
            total_debours="1532.86", total_ht="1644.85", total_tva="22.40", total_ttc="1667.25")
    for sous in ("total_debours", "total_ht"):
        for r in _d1(f, sous):
            assert r.outcome is not Outcome.ecart_certain


def test_d1_vrai_total_ht_faux_lignes_completes():
    """Total HT augmenté ; débours confirmés par leur total, prestations par le total de TVA : certain."""
    f = _ft(_ligne(NatureLigne.debours_droits, "473.40"), _ligne(NatureLigne.debours_tva, "795.47"),
            _ligne(NatureLigne.frais_dedouanement, "62.50", taux="20"),
            _ligne(NatureLigne.transport, "140.00", taux="20"),
            total_debours="1268.87", total_ht="1512.23", total_tva="40.50", total_ttc="1552.73")
    rs = _d1(f, "total_ht")
    assert len(rs) == 1 and rs[0].outcome is Outcome.ecart_certain
    assert rs[0].constat.montant_en_jeu == D("40.86")


def test_d1_ligne_montant_ttc_lu_comme_ht():
    """Montant TTC de la ligne lu à la place du HT : la ligne n'est confirmée par aucun total."""
    f = _ft(_ligne(NatureLigne.debours_droits, "59.65", quantite="2", pu="24.855"),
            _ligne(NatureLigne.debours_tva, "465.60"),
            total_debours="515.31", total_ht="669.31", total_tva="38.74", total_ttc="708.05")
    for r in _d1(f, "ligne"):
        assert r.outcome is Outcome.a_verifier and RaisonCode.lecture_non_corroboree in r.constat.raisons


# =====================================================================================================
# Contrôles entre documents
# =====================================================================================================


def test_c5_declaration_sans_ligne_de_taxation_lue():
    """La déclaration (mise en page inconnue) ne livre que son total à payer : rien ne le confirme."""
    d = _dec(a_payer="3.00")
    f = facture_transitaire(
        id=FT, numero=vs("facture_transitaire.numero", "FT-FICTIF-2", document_id=FT),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", "26FR00000000000001", document_id=FT)],
        lignes=[_ligne(NatureLigne.debours_forfait_petits_envois, "9.00")],
        total_debours=vs("facture_transitaire.total_debours", "9.00", document_id=FT),
        total_ht=vs("facture_transitaire.total_ht", "9.00", document_id=FT),
    )
    for r in _constats(c5_total_debours(contexte([d, f]))):
        assert r.outcome is not Outcome.ecart_certain


def test_feuilles_derivees_ramenees_aux_sources():
    a = vs("facture_transitaire.lignes[].montant_ht", "10.00", document_id=FT)
    b = vs("facture_transitaire.lignes[].montant_ht", "5.00", document_id=FT)
    s = vs("facture_transitaire.total_debours", "15.00", document_id=FT, methode="derive",
           derivee_de=[a.id, b.id])
    index = {a.id: a, b.id: b}
    feuilles = corroboration._feuilles([s], index.get)
    assert {v.id for v in feuilles} == {a.id, b.id}


# =====================================================================================================
# Totaux imprimés par code de taxe (D-3101)
# =====================================================================================================


def _total_code(code, montant):
    from controldone.model import TotalTaxeCode

    return TotalTaxeCode(type_taxe=vs("declaration.totaux_par_code[].type_taxe", code, document_id=DEC),
                         montant=vs("declaration.totaux_par_code[].montant", montant, document_id=DEC))


def test_identites_des_totaux_par_code():
    """Σ lignes du code = total du code ; Σ totaux par code = total des droits et taxes : deux identités du réseau."""
    d = _dec(_droit("1", "100.00", "10", "10.00"), _droit("2", "200.00", "10", "20.00"),
             _tva("1", "110.00", "22.00"), _tva("2", "220.00", "44.00"), total="96.00",
             totaux_par_code=[_total_code("A00", "30.00"), _total_code("B00", "66.00")])
    reseau = {i.cle: i for i in corroboration.reseau(d, lambda v: v is not None, contexte([d]).tol)}
    assert reseau["dec:code:A00"].tient and reseau["dec:code:B00"].tient
    assert reseau["dec:codes:total_droits_taxes"].tient
    # les totaux par code ne sont jamais des lignes : la somme des lignes reste celle des quatre taxations
    assert len(reseau["dec:total_droits_taxes:incluse"].operandes) == 4


def test_b2_code_certain_avec_lecture_corroboree():
    """Total A00 imprimé faux (40 au lieu de 30) : les lignes sommées sont confirmées (base × taux, total général) ;
    le total du code est la valeur mise en cause."""
    d = _dec(_droit("1", "100.00", "10", "10.00"), _droit("2", "200.00", "10", "20.00"),
             _tva("1", "110.00", "22.00"), _tva("2", "220.00", "44.00"), total="96.00",
             nombre_articles=vs("declaration.nombre_articles", "2", document_id=DEC),
             totaux_par_code=[_total_code("A00", "40.00"), _total_code("B00", "66.00")])
    rs = [r for r in b2_sommes_taxes(contexte([d])) if r.sous_controle == "code"]
    assert [r.outcome for r in rs] == [Outcome.ecart_certain, Outcome.conforme]
    assert rs[0].constat.montant_en_jeu == D("10.00")


def test_total_par_code_deduit_hors_du_reseau_d3710():
    # Un total déduit (D-3706) ne corrobore ni les lignes de son code ni le total des droits et taxes.
    from controldone.model.champs import REGLE_TOTAL_CODE_SANS_LIGNE

    b00 = _total_code("B00", "66.00")
    b00.montant = b00.montant.model_copy(update={"regle_derivation": REGLE_TOTAL_CODE_SANS_LIGNE})
    d = _dec(_droit("1", "100.00", "10", "10.00"), _droit("2", "200.00", "10", "20.00"),
             _tva("1", "110.00", "22.00"), _tva("2", "220.00", "44.00"), total="96.00",
             totaux_par_code=[_total_code("A00", "30.00"), b00])
    reseau = {i.cle for i in corroboration.reseau(d, lambda v: v is not None, contexte([d]).tol)}
    assert "dec:code:A00" in reseau and "dec:code:B00" not in reseau
    assert not any(k.startswith("dec:codes:") for k in reseau)
