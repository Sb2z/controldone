import json
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from controldone import SCHEMA_VERSION
from controldone.model import (
    CHAMPS_CLES,
    RAISON_LIBELLES,
    ChampsDeclaration,
    ChampsFactureCommerciale,
    ChampsFactureTransitaire,
    Constat,
    Document,
    EcartARecouvrer,
    ErreurSchema,
    ErreurTolerance,
    ErreurTransition,
    ExtracteurInfo,
    GrilleTarifaire,
    Methode,
    NatureLigne,
    NatureMontant,
    Niveau,
    Outcome,
    ProfilTolerances,
    RaisonCode,
    ResultatControle,
    SigneImprime,
    StatutEcart,
    StatutGrille,
    TotalOrigine,
    TypeDocument,
    TypeValeur,
    ValeurSourcee,
    chaine_schema,
    chemin_generique,
    chemin_relatif,
    confiance_derivee,
    deriver_somme,
    transitionner,
    type_valeur_pour,
    verifier_schema,
)
from controldone.testing import vs

EX = ExtracteurInfo(type="deterministe", id="t", version="1")


def test_valeur_sourcee_lecture_typee():
    v = vs("facture_commerciale.total_facture", "12540.00", brut="USD 12,540.00")
    assert v.decimal() == D("12540.00")
    assert v.decimal_signe() == D("12540.00")
    n = vs("x.montant", "12.00", signe_imprime=SigneImprime.negatif)
    assert n.decimal_signe() == D("-12.00")
    assert vs("x.date", "2026-08-14").date_iso().day == 14
    assert vs("x.nombre", "3").entier() == 3
    with pytest.raises(ValueError):
        vs("x.n", "3.5").entier()
    with pytest.raises(ValueError):
        vs("x.n", None).decimal()
    assert vs("x.n", "abc").decimal_ou_none() is None


def test_llm_non_ancree_plafonnee():
    v = ValeurSourcee(chemin="a", valeur="1", extracteur=EX, methode=Methode.llm, confiance=0.95, ancree=False)
    assert v.confiance == 0.5
    v2 = ValeurSourcee(chemin="a", valeur="1", extracteur=EX, methode=Methode.llm, confiance=0.95, ancree=True)
    assert v2.confiance == 0.95


def test_derivee_exige_sources():
    with pytest.raises(ValidationError):
        ValeurSourcee(chemin="a", valeur="1", extracteur=EX, methode=Methode.derive, confiance=0.5)


def test_ancrage_suffisant():
    assert vs("a", "1", methode="xml_structure", ancree=False).ancrage_suffisant()
    assert vs("a", "1", methode="saisie_humaine", ancree=False).ancrage_suffisant()
    assert not vs("a", "1", methode="ocr", ancree=False).ancrage_suffisant()
    assert vs("a", "1", confiance=0.95).fiable_pour_certain(0.9)
    assert not vs("a", "1", confiance=0.85).fiable_pour_certain(0.9)


def test_confiance_derivee_8_5_2():
    a, b = vs("l.a", "1", confiance=0.95), vs("l.b", "2", confiance=0.9)
    assert confiance_derivee([a, b]) == 0.9  # f = 1,0 (toutes ancrées)
    o = vs("l.c", "2", confiance=0.9, methode="ocr")
    assert confiance_derivee([a, o]) == pytest.approx(0.54)  # f = 0,6
    assert confiance_derivee([a], 0.3) == pytest.approx(0.285)
    assert confiance_derivee([]) == 0.0


def test_deriver_somme_total_reconstruit():
    lignes = [vs(f"facture_commerciale.lignes[{i}].montant_ligne", m) for i, m in enumerate(["10.10", "20.205"])]
    t = deriver_somme("facture_commerciale.total_facture", lignes, document_id="d", extracteur=EX,
                      total_reconstruit=True)
    assert t.valeur == "30.305"  # aucune perte d'arrondi intermédiaire
    assert t.methode is Methode.derive and t.total_origine is TotalOrigine.reconstruit
    assert t.confiance <= 0.6 and t.derivee_de == [x.id for x in lignes]


def test_chemins_et_types():
    assert chemin_relatif("facture_commerciale.acheteur.tva") == "acheteur.tva"
    assert chemin_relatif("autre.x") == "autre.x"
    assert chemin_generique("lignes[3].montant_ht") == "lignes[].montant_ht"
    assert type_valeur_pour("facture_commerciale.total_facture") is TypeValeur.montant
    assert type_valeur_pour("lignes[2].masse_nette") is TypeValeur.masse
    assert type_valeur_pour("acheteur.tva") is TypeValeur.tva
    assert type_valeur_pour("refs_mrn[0]") is TypeValeur.reference
    assert type_valeur_pour("date_acceptation") is TypeValeur.date
    assert type_valeur_pour("description") is TypeValeur.texte


def test_champs_definir_obtenir_iterer():
    c = ChampsFactureTransitaire()
    v = vs("facture_transitaire.lignes[2].montant_ht", "12.00")
    c.definir("lignes[2].montant_ht", v)
    assert len(c.lignes) == 3 and c.obtenir("lignes[2].montant_ht") is v
    assert c.obtenir("lignes[7].montant_ht") is None
    c.definir("emetteur.tva", vs("facture_transitaire.emetteur.tva", "FR00000000000"))
    c.definir("refs_mrn[]", vs("facture_transitaire.refs_mrn[0]", "26FR0000000000001A"))
    c.definir("refs_mrn[1]", vs("facture_transitaire.refs_mrn[1]", "26FR0000000000002A"))
    assert len(c.refs_mrn) == 2
    assert len(list(c.iter_valeurs())) == 4
    with pytest.raises(KeyError):
        c.definir("inexistant", v)


def test_feuilles_et_champs_cles():
    chemins = {f.chemin for f in ChampsFactureCommerciale.feuilles()}
    assert {"numero", "acheteur.tva", "total_facture", "lignes[].montant_ligne", "sous_totaux[].montant"} <= chemins
    for td, cles in CHAMPS_CLES.items():
        from controldone.model import classe_champs

        cls = classe_champs(td)
        tous = {f.chemin for f in cls.feuilles()}
        assert cles <= tous, td
    nature = next(f for f in ChampsFactureTransitaire.feuilles() if f.chemin == "lignes[].nature")
    assert nature.enum is NatureLigne


def test_document_aller_retour_json_discriminant():
    c = ChampsDeclaration(mrn=vs("declaration.mrn", "26FR0000000000001A"))
    d = Document(type=TypeDocument.declaration, champs=c)
    d2 = Document.model_validate_json(d.model_dump_json())
    assert isinstance(d2.champs, ChampsDeclaration)
    assert d2.dec.mrn_prefixe == "26FR00000000000"
    with pytest.raises(TypeError):
        _ = d2.fc


def test_lecteur_ignore_champs_inconnus():
    d = Document(type=TypeDocument.facture_commerciale, champs=ChampsFactureCommerciale())
    data = json.loads(d.model_dump_json())
    data["champ_futur"] = 1
    data["champs"]["autre_champ_futur"] = {"x": 1}
    assert Document.model_validate(data).id == d.id


def test_nature_ligne():
    assert NatureLigne.debours_tva.est_debours
    assert NatureLigne.magasinage.est_prestation
    assert NatureLigne.debours_combines.composante is None
    assert NatureLigne.surcharge.composante.value == "prestation"


def test_versionnement_schema():
    s = chaine_schema("controldone.dossier")
    assert s == f"controldone.dossier/{SCHEMA_VERSION}"
    assert verifier_schema("controldone.dossier/2.9.1", "controldone.dossier", "2.0.0").mineure == 9
    with pytest.raises(ErreurSchema):
        verifier_schema("controldone.dossier/3.0.0", "controldone.dossier", "2.0.0")
    with pytest.raises(ErreurSchema):
        verifier_schema("controldone.autre/2.0.0", "controldone.dossier", "2.0.0")
    with pytest.raises(ErreurSchema):
        verifier_schema("n'importe quoi", "controldone.dossier", "2.0.0")


# --- profil de tolérances ------------------------------------------------------------------------------


def test_profil_defauts_8_3():
    p = ProfilTolerances()
    assert p.t_ligne == D("0.01") and p.s_debours == D("1.00") and p.c_min_certain == 0.90
    assert p.c_min_utile == 0.50 and p.s_tarif == D("0.10") and p.s_arith == D("1.00")


def test_empreinte_stable_et_sensible():
    a, b = ProfilTolerances(), ProfilTolerances()
    assert a.empreinte() == b.empreinte() and len(a.empreinte()) == 64
    assert ProfilTolerances(t_masse_kg=D("1.0")).empreinte() != a.empreinte()
    assert ProfilTolerances(version=7).empreinte() == a.empreinte()  # la version n'est pas du contenu


def test_surcharges_seulement_elargir_les_seuils():
    p = ProfilTolerances()
    p2 = p.appliquer_surcharges({"s_debours": "2.00", "c_min_certain": 0.95, "t_masse_kg": "0.2"})
    assert p2.version == p.version + 1 and p2.s_debours == D("2.00") and p2.t_masse_kg == D("0.2")
    for nom, val in [("s_debours", "0.50"), ("c_min_certain", 0.8), ("s_valeur_unites", "1"), ("s_tarif", "0.01")]:
        with pytest.raises(ErreurTolerance):
            p.appliquer_surcharges({nom: val})
    with pytest.raises(ErreurTolerance):
        p.appliquer_surcharges({"inconnu": 1})
    with pytest.raises(ValidationError):
        ProfilTolerances(t_ligne=D("-1"))


def test_grille_applicable():
    from datetime import date

    g = GrilleTarifaire(transitaire_id="tra_1", reference="DEV-1", statut=StatutGrille.validee,
                        valide_du=date(2026, 1, 1), valide_au=date(2026, 12, 31))
    assert g.applicable("tra_1", date(2026, 6, 1))
    assert not g.applicable("tra_2", date(2026, 6, 1))
    assert not g.applicable("tra_1", date(2027, 1, 1))
    assert not g.model_copy(update={"statut": StatutGrille.brouillon}).applicable("tra_1", date(2026, 6, 1))


# --- résultats et constats ---------------------------------------------------------------------------------


def _constat(**kw):
    base = dict(controle_id="C1", niveau=Niveau.a_verifier, raisons=[RaisonCode.ecart_sous_seuil],
                nature_montant=NatureMontant.recouvrable, montant_en_jeu=D("0.50"))
    base.update(kw)
    return Constat(**base)


def test_invariants_constat():
    _constat()
    with pytest.raises(ValidationError):  # renvoi avec montant
        _constat(controle_id="A12", nature_montant=NatureMontant.renvoi, renvoi=True)
    with pytest.raises(ValidationError):  # renvoi certain
        _constat(niveau=Niveau.ecart_certain, raisons=[], renvoi=True, montant_en_jeu=None)
    with pytest.raises(ValidationError):  # certain avec raison de doute
        _constat(niveau=Niveau.ecart_certain)
    _constat(niveau=Niveau.ecart_certain, raisons=[RaisonCode.doublon_composantes], montant_en_jeu=None)
    with pytest.raises(ValidationError):  # a_verifier sans raison
        _constat(raisons=[])
    with pytest.raises(ValidationError):  # montant sur nature aucun
        _constat(nature_montant=NatureMontant.aucun)


def test_invariants_resultat():
    with pytest.raises(ValidationError):
        ResultatControle(controle_id="C1", dossier_id="d", dossier_version=1, outcome=Outcome.a_verifier)
    with pytest.raises(ValidationError):
        ResultatControle(controle_id="C1", dossier_id="d", dossier_version=1, outcome=Outcome.non_verifiable)
    with pytest.raises(ValidationError):
        ResultatControle(controle_id="C1", dossier_id="d", dossier_version=1, outcome=Outcome.conforme,
                         constat=_constat())
    r = ResultatControle(controle_id="C1", dossier_id="d", dossier_version=1, outcome=Outcome.a_verifier,
                         constat=_constat())
    assert r.constat.niveau is Niveau.a_verifier


def test_libelles_de_toutes_les_raisons():
    assert set(RAISON_LIBELLES) == set(RaisonCode)


# --- recouvrement -----------------------------------------------------------------------------------------


def test_transitions_recouvrement():
    e = EcartARecouvrer(constat_id="f_1", composante="droit", montant_initial=D("10"), reste=D("10"))
    evt = transitionner(e, StatutEcart.reclame, auteur="u1")
    assert e.statut is StatutEcart.reclame and e.reclame_le is not None and evt.de is StatutEcart.ouvert
    transitionner(e, StatutEcart.conteste, auteur="u1")
    transitionner(e, StatutEcart.reclame, auteur="u1")  # relance
    transitionner(e, StatutEcart.partiellement_credite, auteur="sys", montant=D("4"))
    transitionner(e, StatutEcart.credite, auteur="sys")
    with pytest.raises(ErreurTransition):
        transitionner(e, StatutEcart.reclame, auteur="u1")  # terminal
    e2 = EcartARecouvrer(constat_id="f_2", composante="tva", montant_initial=D("1"), reste=D("1"))
    with pytest.raises(ErreurTransition):
        transitionner(e2, StatutEcart.abandonne, auteur="u1")  # motif obligatoire
    transitionner(e2, StatutEcart.abandonne, auteur="u1", commentaire="montant trop faible")
