"""Bloc M4 (D-4601 à D-4606) : gardes du tarif étendues à D6 / D7, montant établi des écarts de débours (C1 à C5),
rappel certain par corroboration indépendante (F3, A6, B1). Données entièrement fictives construites ici."""

from datetime import date
from decimal import Decimal as D

from controldone.controls.context import AutreDossier, ControlContext
from controldone.controls.corroboration import BASE_TVA, reseau
from controldone.controls.famille_a import BANDE_DEVISE_PAR_TAUX
from controldone.controls.framework import run_controls
from controldone.guardrails import check_text
from controldone.model import (
    CategorieTaxe,
    ChampsAvoir,
    GrilleTarifaire,
    LigneFactureTransitaire,
    ModePoste,
    NatureLigne,
    Outcome,
    Partie,
    PosteGrille,
    PrestationsHorsGrille,
    ProfilTolerances,
    RaisonCode,
    StatutGrille,
    TauxChangeSens,
    Transitaire,
    TypeDocument,
)
from controldone.model.champs import TotalTaxeCode
from controldone.model.enums import RAISON_LIBELLES, Methode
from controldone.taux_reference import TableTauxReference
from controldone.testing import (
    declaration,
    document,
    dossier_pour,
    facture_commerciale,
    facture_transitaire,
    taxation,
    vs,
)

N = NatureLigne
TVA_TRANSITAIRE = "FR11000555550"  # transitaire FICTIF
TVA_CLIENT = "FR68000458570"  # entité FICTIVE du client
MRN_A = "26FRAAAAAAAAAAAAA1"  # MRN FICTIFS
MRN_B = "26FRBBBBBBBBBBBBB2"
TRANSITAIRES = [Transitaire(id="tra_1", nom="Transit FICTIF", tva=TVA_TRANSITAIRE)]

GRILLE = GrilleTarifaire(
    transitaire_id="tra_1",
    reference="DEV-FICTIF-M4",
    statut=StatutGrille.validee,
    prestations_hors_grille=PrestationsHorsGrille.interdites,
    postes=[
        PosteGrille(code_poste="DEDOU", nature=N.frais_dedouanement, mode=ModePoste.forfait, prix=D("60.00")),
        PosteGrille(
            code_poste="MAG", nature=N.magasinage, mode=ModePoste.par_jour, prix=D("12.00"), franchise_jours=3
        ),
        PosteGrille(
            code_poste="MAGF",
            nature=N.manutention,
            mode=ModePoste.forfait,
            prix=D("40.00"),
            libelles_reconnus=[],
        ),
        PosteGrille(
            code_poste="SURETE",
            nature=N.surcharge,
            mode=ModePoste.forfait,
            prix=D("25.00"),
            libelles_reconnus=["surcharge sûreté"],
        ),
    ],
)
GRILLE_MAG_FORFAIT = GRILLE.model_copy(
    update={
        "postes": [
            PosteGrille(code_poste="MAG", nature=N.magasinage, mode=ModePoste.forfait, prix=D("40.00")),
            *[p for p in GRILLE.postes if p.code_poste != "MAG"],
        ]
    }
)


def _v(fid, nom, val, **kw):
    return None if val is None else vs(f"facture_transitaire.lignes[].{nom}", val, document_id=fid, **kw)


def ligne(nature, montant, *, fid="doc_ft1", libelle=None, mrn=None, **kw):
    return LigneFactureTransitaire(
        libelle=_v(fid, "libelle", libelle or nature.value.replace("_", " ")),
        nature=nature,
        montant_ht=_v(fid, "montant_ht", montant),
        mrn=_v(fid, "mrn", mrn),
        **{k: _v(fid, k, x) for k, x in kw.items()},
    )


def ft(*lignes, fid="doc_ft1", mrns=(MRN_A,), numero="FA-FICTIF-M4", devise=None, conf_devise=0.99, **totaux):
    champs = {k: vs(f"facture_transitaire.{k}", x, document_id=fid) for k, x in totaux.items()}
    if devise is not None:
        champs["devise"] = vs("facture_transitaire.devise", devise, document_id=fid, confiance=conf_devise)
    return facture_transitaire(
        id=fid,
        numero=vs("facture_transitaire.numero", numero, document_id=fid),
        date=vs("facture_transitaire.date", "2026-09-15", document_id=fid),
        emetteur=Partie(tva=vs("facture_transitaire.emetteur.tva", TVA_TRANSITAIRE, document_id=fid)),
        client_facture=Partie(tva=vs("facture_transitaire.client_facture.tva", TVA_CLIENT, document_id=fid)),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", m, document_id=fid) for m in mrns],
        lignes=list(lignes),
        **champs,
    )


def dec(did="doc_dec", mrn=MRN_A, droits="1000.00", *, version=None, totaux=()):
    d = declaration(
        id=did,
        mrn=mrn,
        version=version,
        taxations=[taxation(did, categorie=CategorieTaxe.droit, type_taxe="A00", montant=droits)],
    )
    d.dec.importateur = Partie(tva=vs("declaration.importateur.tva", TVA_CLIENT, document_id=did))
    d.dec.totaux_par_code = [
        TotalTaxeCode(
            type_taxe=vs("declaration.totaux_par_code[].type_taxe", code, document_id=did),
            montant=vs("declaration.totaux_par_code[].montant", m, document_id=did),
        )
        for code, m in totaux
    ]
    return d


def avoir(*lignes_av, aid="doc_av1", origine=None, mrns=()):
    return document(
        TypeDocument.avoir,
        ChampsAvoir(
            numero=vs("avoir.numero", "AV-FICTIF-M4", document_id=aid),
            emetteur=Partie(tva=vs("avoir.emetteur.tva", TVA_TRANSITAIRE, document_id=aid)),
            refs_facture_origine=[vs("avoir.refs_facture_origine[]", origine, document_id=aid)]
            if origine
            else [],
            refs_mrn=[vs("avoir.refs_mrn[]", m, document_id=aid) for m in mrns],
            lignes=list(lignes_av),
        ),
        id=aid,
    )


def ligne_av(nature, montant, aid="doc_av1", mrn=None):
    return LigneFactureTransitaire(
        libelle=vs("avoir.lignes[].libelle", nature.value.replace("_", " "), document_id=aid),
        nature=nature,
        montant_ht=vs("avoir.lignes[].montant_ht", montant, document_id=aid),
        mrn=vs("avoir.lignes[].mrn", mrn, document_id=aid) if mrn else None,
    )


def contexte(docs, *, grilles=(GRILLE,), autres=(), dossier_id="dos_a", lots=(), taux=None):
    dossier = dossier_pour(docs, id=dossier_id).model_copy(
        update={"transitaire_id": "tra_1", "lot_ids": list(lots)}
    )
    return ControlContext.construire(
        dossier,
        docs,
        ProfilTolerances(id="tol_test"),
        execution_id="exe_test",
        grilles=list(grilles),
        transitaires=TRANSITAIRES,
        autres_dossiers=list(autres),
        exiger_lecture_corroboree=False,
        taux_reference=taux,
    )


def resultats(docs, cid, **kw):
    return [r for r in run_controls(contexte(docs, **kw), controles=[cid]) if r.controle_id == cid]


def un(docs, cid, **kw):
    xs = [r for r in resultats(docs, cid, **kw) if r.constat is not None]
    assert len(xs) == 1, xs
    return xs[0]


def mag(montant, **kw):
    return ligne(N.magasinage, montant, libelle="Magasinage", **kw)


# =====================================================================================================
# D-4601 — D6 / D7 : gardes du tarif de D3 / D4
# =====================================================================================================


def test_libelle_de_la_raison_nouvelle():
    texte = RAISON_LIBELLES[RaisonCode.montant_non_etabli]
    assert texte.startswith("à vérifier") and "estimation" in texte and check_text(texte) == []


def test_d6_periode_imprimee_reste_certaine():
    # 10 jours − 3 de franchise = 7 × 12 = 84 ; quantité et prix unitaire non imprimés : l'attendu vient des dates.
    r = un([dec(), ft(mag("150.00", date_debut="2026-09-01", date_fin="2026-09-10"))], "D6")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("66.00")


def test_d6_forfait_quantite_superieure_a_un():
    r = un([dec(), ft(mag("80.00", quantite="2"))], "D6", grilles=(GRILLE_MAG_FORFAIT,))
    assert r.outcome is Outcome.a_verifier and RaisonCode.tarif_non_etabli in r.constat.raisons
    assert "quantite_sur_forfait" in r.details["tarif_non_etabli"]


def test_d6_avoir_non_impute_du_dossier():
    av = avoir(ligne_av(N.autre_prestation, "40.00"), origine="AUTRE-REF-FICTIVE")
    docs = [dec(), ft(mag("150.00", date_debut="2026-09-01", date_fin="2026-09-10")), av]
    r = un(docs, "D6")
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_impute in r.constat.raisons


def test_d6_ligne_d_un_autre_envoi():
    f = ft(mag("150.00", date_debut="2026-09-01", date_fin="2026-09-10", mrn=MRN_B), mrns=(MRN_B,))
    r = un([dec(), f], "D6")
    assert r.outcome is Outcome.a_verifier and r.details.get("envoi_hors_dossier") is True


def test_d6_ligne_repetee_comparee_une_fois():
    f = ft(
        mag("150.00", date_debut="2026-09-01", date_fin="2026-09-10"),
        mag("150.00", date_debut="2026-09-01", date_fin="2026-09-10"),
    )
    rs = resultats([dec(), f], "D6")
    assert len([r for r in rs if r.constat is not None]) == 1
    copie = [r for r in rs if r.outcome is Outcome.non_applicable]
    assert copie and copie[0].details["couvert_par"] == "D5"


def test_d6_devise_illisible_et_tva_comprise():
    illisible = ft(
        mag("150.00", date_debut="2026-09-01", date_fin="2026-09-10"), devise="EUR", conf_devise=0.2
    )
    r = un([dec(), illisible], "D6")
    assert r.outcome is Outcome.a_verifier and RaisonCode.devise_incertaine in r.constat.raisons
    # 84 × 1,2 = 100,80 : TVA de la ligne imprimée = 16,80 -> le montant lu est TVA comprise.
    ttc = ft(
        mag("100.80", date_debut="2026-09-01", date_fin="2026-09-10", montant_tva="16.80", taux_tva="20")
    )
    r2 = un([dec(), ttc], "D6")
    assert r2.outcome is Outcome.a_verifier and r2.details.get("montant_peut_etre_ttc") is True


def test_d7_forfait_autre_version_de_la_facture():
    s = ligne(N.surcharge, "40.00", libelle="Surcharge sûreté")
    docs = [
        dec(),
        ft(s),
        ft(ligne(N.surcharge, "25.00", libelle="Surcharge sûreté", fid="doc_ft2"), fid="doc_ft2"),
    ]
    rs = [r for r in resultats(docs, "D7") if r.constat is not None]
    assert rs and all(r.outcome is Outcome.a_verifier for r in rs)
    assert any("autre_version_de_la_facture" in r.details.get("tarif_non_etabli", []) for r in rs)
    seule = un([dec(), ft(ligne(N.surcharge, "40.00", libelle="Surcharge sûreté"))], "D7")
    assert seule.outcome is Outcome.ecart_certain and seule.constat.montant_en_jeu == D("15.00")


def test_d7_ligne_negative_de_credit():
    f = ft(
        ligne(N.surcharge, "40.00", libelle="Surcharge sûreté"),
        ligne(N.autre_prestation, "-15.00", libelle="Remise commerciale"),
    )
    r = un([dec(), f], "D7")
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_impute in r.constat.raisons


# =====================================================================================================
# D-4603 — C1 à C5 : montant de l'écart établi
# =====================================================================================================


def _droits(montant, **kw):
    return ligne(N.debours_droits, montant, libelle="Droits de douane", **kw)


def test_c1_certain_avec_avoir_rattache_par_le_mrn():
    av = avoir(ligne_av(N.debours_droits, "50.00", mrn=MRN_A), origine="FA-FICTIF-M4")
    r = un([dec(), ft(_droits("1200.00")), av], "C1")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("150.00")


def test_c1_avoir_d_un_autre_envoi_n_est_pas_deduit():
    """Facture de deux envois répartie entre deux dossiers : l'avoir cite le MRN de l'autre envoi ; il n'est pas
    déduit ici (il l'était, faussant le montant)."""
    db = dec("doc_dec_b", MRN_B, "500.00")
    f = ft(_droits("1000.00", mrn=MRN_A), _droits("600.00", mrn=MRN_B), mrns=(MRN_A, MRN_B))
    av = avoir(ligne_av(N.debours_droits, "100.00", mrn=MRN_B), origine="FA-FICTIF-M4")
    autre = AutreDossier(
        dossier=dossier_pour([db, f, av], id="dos_b"), documents={x.id: x for x in (db, f, av)}
    )
    rs = resultats([dec(), f, av], "C1", autres=[autre])
    assert all(r.outcome is Outcome.conforme for r in rs), rs


def test_c1_avoir_au_mrn_sans_correspondance_montant_non_etabli():
    av = avoir(ligne_av(N.debours_droits, "50.00", mrn="26FRZZZZZZZZZZZZZ9"), origine="FA-FICTIF-M4")
    r = un([dec(), ft(_droits("1200.00")), av], "C1")
    assert r.outcome is Outcome.a_verifier and RaisonCode.montant_non_etabli in r.constat.raisons
    assert r.details["montant_non_etabli"] == ["avoir_rattachement_non_etabli"]
    assert "estimation" in r.constat.libelle and check_text(r.constat.libelle) == []


def test_c1_avoir_non_ventile_rattache_a_la_facture():
    av = document(
        TypeDocument.avoir,
        ChampsAvoir(
            numero=vs("avoir.numero", "AV-FICTIF-M4", document_id="doc_av1"),
            emetteur=Partie(tva=vs("avoir.emetteur.tva", TVA_TRANSITAIRE, document_id="doc_av1")),
            refs_facture_origine=[vs("avoir.refs_facture_origine[]", "FA-FICTIF-M4", document_id="doc_av1")],
            total_credite_ht=vs("avoir.total_credite_ht", "80.00", document_id="doc_av1"),
        ),
        id="doc_av1",
    )
    r = un([dec(), ft(_droits("1200.00")), av], "C1")
    assert r.outcome is Outcome.a_verifier and "avoir_non_impute" in r.details["montant_non_etabli"]


def test_c1_avoir_orphelin_dans_le_lot():
    av = avoir(ligne_av(N.debours_droits, "50.00"), aid="doc_av9")
    orphelin = AutreDossier(
        dossier=dossier_pour([av], id="dos_orphelin").model_copy(update={"lot_ids": ["lot_1"]}),
        documents={av.id: av},
    )
    r = un([dec(), ft(_droits("1200.00"))], "C1", autres=[orphelin], lots=["lot_1"])
    assert r.outcome is Outcome.a_verifier and "avoir_hors_dossier" in r.details["montant_non_etabli"]


def test_c1_versions_de_la_declaration():
    v1 = dec("doc_dec_v1", droits="900.00", version="1")
    v2 = dec("doc_dec_v2", droits="1000.00", version="2")
    r = un([v1, v2, ft(_droits("1200.00"))], "C1")
    assert r.outcome is Outcome.a_verifier and "versions_de_la_declaration" in r.details["montant_non_etabli"]


def test_c1_totaux_par_code_discordants():
    r = un([dec(totaux=[("A00", "1100.00")]), ft(_droits("1200.00"))], "C1")
    assert (
        r.outcome is Outcome.a_verifier and "totaux_par_code_discordants" in r.details["montant_non_etabli"]
    )
    ok = un([dec(totaux=[("A00", "1000.00")]), ft(_droits("1200.00"))], "C1")
    assert ok.outcome is Outcome.ecart_certain


def test_c1_devise_de_la_facture_autre_que_l_euro():
    r = un([dec(), ft(_droits("1200.00"), devise="CHF")], "C1")
    assert r.outcome is Outcome.a_verifier and RaisonCode.devise_incertaine in r.constat.raisons


def test_c1_ligne_de_regularisation_sans_signe():
    f = ft(_droits("1200.00"), ligne(N.debours_droits, "50.00", libelle="Régularisation droits de douane"))
    r = un([dec(), f], "C1")
    assert r.outcome is Outcome.a_verifier and "ligne_de_credit_sans_signe" in r.details["montant_non_etabli"]


def test_c5_factures_de_meme_numero():
    f1 = ft(_droits("1200.00"))
    f2 = ft(ligne(N.debours_tva, "10.00", fid="doc_ft2", libelle="TVA import"), fid="doc_ft2")
    rs = [r for r in resultats([dec(), f1, f2], "C5") if r.constat is not None]
    assert rs and all(
        r.outcome is Outcome.a_verifier and "factures_de_meme_numero" in r.details["montant_non_etabli"]
        for r in rs
    )


# =====================================================================================================
# D-4604 à D-4606 — rappel certain : corroboration indépendante
# =====================================================================================================


def _ft_f3(fid, numero, conf_mrn, d):
    return facture_transitaire(
        id=fid,
        numero=vs("facture_transitaire.numero", numero, document_id=fid),
        date=vs("facture_transitaire.date", d, document_id=fid),
        emetteur=Partie(tva=vs("facture_transitaire.emetteur.tva", TVA_TRANSITAIRE, document_id=fid)),
        lignes=[
            LigneFactureTransitaire(
                libelle=vs("facture_transitaire.lignes[].libelle", "Droits", document_id=fid),
                nature=N.debours_droits,
                montant_ht=vs("facture_transitaire.lignes[].montant_ht", "300.00", document_id=fid),
                mrn=vs(
                    "facture_transitaire.lignes[].mrn",
                    MRN_A,
                    document_id=fid,
                    confiance=conf_mrn,
                    methode=Methode.ocr,
                ),
            )
        ],
    )


def _f3(conf_mrn, mrn_dec=MRN_A):
    d = dec(droits="300.00")
    d.dec.mrn = vs("declaration.mrn", mrn_dec, document_id=d.id)
    ancienne = _ft_f3("doc_ft_old", "FA-FICTIF-001", conf_mrn, "2026-09-01")
    recente = _ft_f3("doc_ft_new", "FA-FICTIF-002", conf_mrn, "2026-09-20")
    autre = AutreDossier(dossier=dossier_pour([ancienne], id="dos_x"), documents={ancienne.id: ancienne})
    rs = run_controls(contexte([d, recente], autres=[autre]), controles=["F3"])
    return [r for r in rs if r.controle_id == "F3" and r.constat is not None]


def test_f3_mrn_sous_le_seuil_confirme_par_la_declaration():
    (r,) = _f3(0.8)
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("300.00")


def test_f3_mrn_sous_le_seuil_sans_seconde_lecture():
    # MRN de la déclaration lu autrement (un caractère) : pas de seconde lecture concordante.
    (r,) = _f3(0.8, mrn_dec="26FRAAAAAAAAAAAAA7")
    assert r.outcome is Outcome.a_verifier
    (r2,) = _f3(0.6)  # sous C_LECTURE_CONFIRMABLE : jamais confirmé
    assert r2.outcome is Outcome.a_verifier


def _a6(conf_devise, taux, sens="devise_par_eur"):
    d = declaration(id="doc_dec", mrn=MRN_A)
    d.dec.devise_facture = vs("declaration.devise_facture", "EUR", document_id="doc_dec")
    d.dec.montant_total_facture = vs("declaration.montant_total_facture", "12500.00", document_id="doc_dec")
    d.dec.taux_change = vs("declaration.taux_change", taux, document_id="doc_dec")
    d.dec.taux_change_sens = vs("declaration.taux_change_sens", sens, document_id="doc_dec")
    d.dec.date_acceptation = vs("declaration.date_acceptation", "2026-09-10", document_id="doc_dec")
    d.dec.references_factures = [
        vs("declaration.references_factures[]", "INV-FICTIF-1", document_id="doc_dec")
    ]
    fc = facture_commerciale(
        id="doc_fc",
        numero=vs("facture_commerciale.numero", "INV-FICTIF-1", document_id="doc_fc"),
        devise=vs(
            "facture_commerciale.devise",
            "USD",
            document_id="doc_fc",
            confiance=conf_devise,
            methode=Methode.ocr,
        ),
        total_facture=vs("facture_commerciale.total_facture", "12500.00", document_id="doc_fc"),
    )
    table = TableTauxReference({"USD": {date(2026, 9, 10): D("1.1500")}})
    rs = run_controls(contexte([d, fc], taux=table), controles=["A6"])
    return [r for r in rs if r.controle_id == "A6" and r.constat is not None]


def test_a6_devise_corroboree_par_le_taux_imprime():
    (r,) = _a6(0.92, "1.1100")
    assert r.outcome is Outcome.ecart_certain and r.details["devise_corroboree_par_taux"] is True
    assert TauxChangeSens.devise_par_eur.value == "devise_par_eur"


def test_a6_taux_imprime_sans_rapport_avec_la_devise_lue():
    # 1,40 s'écarte de plus de BANDE_DEVISE_PAR_TAUX du taux de référence du dollar : pas de corroboration.
    assert abs(D("1.40") - D("1.15")) / D("1.15") > BANDE_DEVISE_PAR_TAUX
    (r,) = _a6(0.92, "1.4000")
    assert r.outcome is Outcome.a_verifier and RaisonCode.devise_incertaine in r.constat.raisons
    (r2,) = _a6(0.85, "1.1100")  # devise lue sous c_min_certain : jamais corroborée
    assert r2.outcome is Outcome.a_verifier


def _dec_b1(base_tva):
    did = "doc_dec"
    return declaration(
        id=did,
        mrn=MRN_A,
        taxations=[
            taxation(did, article="1", base="4159.83", taux="2.7", montant="130.52", methode=Methode.ocr),
            taxation(
                did,
                article="1",
                type_taxe="B00",
                categorie=CategorieTaxe.tva,
                base=base_tva,
                taux="20",
                montant=str((D(base_tva) * D("0.2")).quantize(D("0.01"))),
                methode=Methode.ocr,
            ),
        ],
    )


def test_identite_base_de_tva():
    ctx = contexte([_dec_b1("4272.15")])
    ids = [i for i in reseau(ctx.documents["doc_dec"], ctx.utilisable, ctx.tol) if i.nature == BASE_TVA]
    assert len(ids) == 1 and ids[0].tient
    # 4 159,83 + 112,32 (droit calculé) = 4 272,15 ; une base de TVA qui comprend d'autres frais ne tient pas.
    ctx2 = contexte([_dec_b1("4390.15")])
    ids2 = [i for i in reseau(ctx2.documents["doc_dec"], ctx2.utilisable, ctx2.tol) if i.nature == BASE_TVA]
    assert ids2 and not ids2[0].tient
