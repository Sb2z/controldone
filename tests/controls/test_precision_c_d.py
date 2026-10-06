"""Mise au point de la précision (D-701 à D-711) : familles B, C, D. Données fictives construites ici."""

from decimal import Decimal as D

from controldone.controls.context import AutreDossier, ControlContext
from controldone.controls.famille_c import refs_confondables
from controldone.controls.framework import run_controls
from controldone.model import (
    ArticleDeclaration,
    BasePourcentage,
    CategorieTaxe,
    GrilleTarifaire,
    IndiceAutoliquidation,
    LigneFactureTransitaire,
    ModePoste,
    NatureLigne,
    Outcome,
    PaiementNormalise,
    Partie,
    PosteGrille,
    PrestationsHorsGrille,
    ProfilTolerances,
    QualiteTexte,
    RaisonCode,
    StatutGrille,
    Transitaire,
    TypeDocument,
    TypeIndiceAutoliquidation,
)
from controldone.model.champs import ChampsAvoir
from controldone.testing import declaration, document, dossier_pour, facture_transitaire, taxation, vs

N = NatureLigne
TVA_TRANSITAIRE = "FR11000555550"
TRANSITAIRES = [Transitaire(id="tra_1", nom="Transit FICTIF", tva=TVA_TRANSITAIRE)]
MRN_A = "26FRAAAAAAAAAAAAA1"
MRN_B = "26FRBBBBBBBBBBBBB2"


def ligne(nature, montant, *, libelle=None, mrn=None, fid="doc_ft1", **kw):
    def v(nom, val):
        return None if val is None else vs(f"facture_transitaire.lignes[].{nom}", val, document_id=fid)

    return LigneFactureTransitaire(
        libelle=v("libelle", libelle or nature.value.replace("_", " ")),
        nature=nature,
        montant_ht=v("montant_ht", montant),
        mrn=v("mrn", mrn),
        **{k: v(k, x) for k, x in kw.items()},
    )


def ft(*lignes, fid="doc_ft1", numero="REL-FICTIF-001", mrns=(), client_tva=None, transports=(), **totaux):
    return facture_transitaire(
        id=fid,
        numero=vs("facture_transitaire.numero", numero, document_id=fid),
        date=vs("facture_transitaire.date", "2026-09-15", document_id=fid),
        emetteur=Partie(tva=vs("facture_transitaire.emetteur.tva", TVA_TRANSITAIRE, document_id=fid)),
        client_facture=Partie(tva=vs("facture_transitaire.client_facture.tva", client_tva, document_id=fid))
        if client_tva
        else Partie(),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", m, document_id=fid) for m in mrns],
        refs_transport=[vs("facture_transitaire.refs_transport[]", t, document_id=fid) for t in transports],
        lignes=list(lignes),
        **{k: vs(f"facture_transitaire.{k}", x, document_id=fid) for k, x in totaux.items()},
    )


def dec(did, mrn, droits, *, articles=None, **kw):
    d = declaration(
        id=did, mrn=mrn, taxations=[taxation(did, categorie=CategorieTaxe.droit, montant=droits)], **kw
    )
    if articles is not None:
        d.dec.nombre_articles = vs("declaration.nombre_articles", str(articles), document_id=did)
    return d


def poste(code, nature, mode=ModePoste.forfait, prix=None, **kw):
    return PosteGrille(code_poste=code, nature=nature, mode=mode, prix=D(prix) if prix else None, **kw)


GRILLE = GrilleTarifaire(
    transitaire_id="tra_1",
    reference="DEV-FICTIF-2026",
    statut=StatutGrille.validee,
    prestations_hors_grille=PrestationsHorsGrille.interdites,
    postes=[
        poste("DEDOU", N.frais_dedouanement, prix="60.00"),
        poste(
            "LIGNE",
            N.frais_ligne_supplementaire,
            ModePoste.unitaire,
            prix="8.00",
            unite_base="article",
            inclus=3,
        ),
        poste(
            "FAF",
            N.frais_avance_fonds,
            ModePoste.pourcentage,
            pourcentage=D("2"),
            minimum=D("15.00"),
            base_pourcentage=BasePourcentage.debours_hors_tva,
        ),
        poste("DOSSIER", N.autre_prestation, prix="12.00", libelles_reconnus=["Ouverture de dossier"]),
    ],
)


def ctx_de(docs, *, autres=(), dossier_id="dos_test", grilles=(GRILLE,)):
    return ControlContext.construire(
        dossier_pour(docs, id=dossier_id),
        docs,
        ProfilTolerances(id="tol_test"),
        execution_id="exe_test",
        grilles=list(grilles),
        transitaires=TRANSITAIRES,
        autres_dossiers=list(autres),
    )


def constats(rs, cid):
    return [r for r in rs if r.controle_id == cid and r.constat is not None]


def un(rs, cid, **filtre):
    xs = [r for r in rs if r.controle_id == cid and all(getattr(r, k) == v for k, v in filtre.items())]
    assert len(xs) == 1, xs
    return xs[0]


# --- D-701 : relevé ventilé par MRN ---------------------------------------------------------------------------


def _releve():
    """Relevé correctement facturé : FAF et lignes supplémentaires calculés envoi par envoi (par MRN)."""
    return ft(
        ligne(N.debours_droits, "1712.35", mrn=MRN_A),
        ligne(N.frais_avance_fonds, "34.25", mrn=MRN_A),  # 2 % × 1712,35
        ligne(N.frais_ligne_supplementaire, "16.00", mrn=MRN_A, quantite="2"),  # 5 articles − 3 inclus
        ligne(N.debours_droits, "155.90", mrn=MRN_B),
        ligne(N.frais_avance_fonds, "15.00", mrn=MRN_B),  # minimum
        mrns=(MRN_A, MRN_B),
    )


def test_releve_faf_et_lignes_sup_par_mrn_dans_un_meme_dossier():
    docs = [dec("doc_a", MRN_A, "1712.35", articles=5), dec("doc_b", MRN_B, "155.90", articles=2), _releve()]
    rs = run_controls(ctx_de(docs), controles=["C1", "C5", "C6", "D4", "D9"])
    assert not constats(rs, "D4") and not constats(rs, "D9") and not constats(rs, "C6")
    assert {r.outcome for r in rs if r.controle_id in ("D4", "D9")} == {Outcome.conforme}


def test_releve_reparti_entre_dossiers_chaque_ligne_jugee_une_fois():
    """Le même relevé est rattaché à deux dossiers (un par envoi) : chaque ligne n'est jugée que dans le
    dossier de son MRN ; les contrôles de niveau facture (D1, C7, C8) dans le seul dossier principal."""
    f = _releve()
    da, db = dec("doc_a", MRN_A, "1712.35", articles=5), dec("doc_b", MRN_B, "155.90", articles=2)
    autre_b = AutreDossier(dossier=dossier_pour([db, f], id="dos_b"), documents={"doc_b": db, f.id: f})
    autre_a = AutreDossier(dossier=dossier_pour([da, f], id="dos_a"), documents={"doc_a": da, f.id: f})
    ids = ["C6", "C7", "C8", "D1", "D3", "D4", "D9"]
    rs_a = run_controls(ctx_de([da, f], autres=[autre_b], dossier_id="dos_a"), controles=ids)
    rs_b = run_controls(ctx_de([db, f], autres=[autre_a], dossier_id="dos_b"), controles=ids)
    for rs in (rs_a, rs_b):
        assert not [r for r in rs if r.constat is not None], [r.constat.libelle for r in rs if r.constat]
    # D4 : une ligne évaluée par dossier (la sienne), jamais celle de l'autre envoi
    assert len([r for r in rs_a if r.controle_id == "D4"]) == 1
    assert len([r for r in rs_b if r.controle_id == "D4"]) == 1
    assert un(rs_b, "D1").outcome is Outcome.non_applicable  # « dos_a » < « dos_b » : dossier principal = a
    assert un(rs_b, "C7").outcome is Outcome.non_applicable


def test_faf_sans_mrn_sur_facture_couvrant_un_envoi_hors_dossier():
    """FAF global d'une facture qui couvre aussi un MRN d'un autre dossier : assiette = débours de la facture."""
    f = ft(
        ligne(N.debours_droits, "75.23", mrn=MRN_A),
        ligne(N.debours_droits, "1279.31", mrn=MRN_B),
        ligne(N.frais_avance_fonds, "27.09"),
        mrns=(MRN_A, MRN_B),
    )  # 2 % × 1354,54
    rs = run_controls(ctx_de([dec("doc_a", MRN_A, "75.23"), f]), controles=["D4"])
    assert un(rs, "D4").outcome is Outcome.conforme


# --- D-703 : montant net des avoirs déjà reçus ----------------------------------------------------------------


def test_d3_ecart_net_de_l_avoir_deja_recu():
    f = ft(ligne(N.frais_dedouanement, "83.34", libelle="Frais de dédouanement"), numero="FA-FICTIF-7")
    av = document(
        TypeDocument.avoir,
        ChampsAvoir(
            numero=vs("avoir.numero", "AV-FICTIF-7", document_id="doc_av"),
            refs_facture_origine=[vs("avoir.refs_facture_origine[]", "FA-FICTIF-7", document_id="doc_av")],
            lignes=[ligne(N.frais_dedouanement, "11.30", fid="doc_av")],
        ),
        id="doc_av",
    )
    r = un(run_controls(ctx_de([f, av]), controles=["D3"]), "D3")
    assert r.constat.montant_en_jeu == D("12.04") and r.constat.montant_brut == D("23.34")
    assert "doc_av" in r.constat.documents_concernes


# --- D-704 : « autre prestation » rapprochée par libellé seulement ---------------------------------------------


def test_autre_prestation_sans_libelle_reconnu_est_hors_grille():
    f = ft(ligne(N.autre_prestation, "25.00", libelle="Frais de traitement documentaire"))
    rs = run_controls(ctx_de([f]), controles=["D2", "D3"])
    assert un(rs, "D2").constat is not None and not constats(rs, "D3")
    ok = ft(ligne(N.autre_prestation, "12.00", libelle="Ouverture de dossier"))
    assert un(run_controls(ctx_de([ok]), controles=["D3"]), "D3").outcome is Outcome.conforme


# --- D-706 : D1, ligne non lue et acomptes ---------------------------------------------------------------------


def test_d1_meme_ecart_sur_deux_totaux_imprimes_ligne_non_lue():
    f = ft(
        ligne(N.debours_droits, "100.00"),
        ligne(N.frais_dedouanement, "60.00"),
        total_debours="327.03",
        total_ht="387.03",
    )  # une ligne de débours de 227,03 non lue
    rs = run_controls(ctx_de([f]), controles=["D1"])
    assert not constats(rs, "D1")
    assert un(rs, "D1", sous_controle="total_ht").outcome is Outcome.non_verifiable


def test_d1_total_tva_confirme_le_total_ht_imprime():
    f = ft(
        ligne(N.frais_dedouanement, "62.50", taux_tva="20"),
        ligne(N.frais_ligne_supplementaire, "30.00", taux_tva="20"),
        total_ht="130.00",
        total_tva="26.00",
    )  # 20 % × 130,00 : une prestation de 37,50 non lue
    assert not constats(run_controls(ctx_de([f]), controles=["D1"]), "D1")
    gonfle = ft(ligne(N.frais_dedouanement, "62.50", taux_tva="20"), total_ht="80.00", total_tva="12.50")
    assert constats(run_controls(ctx_de([gonfle]), controles=["D1"]), "D1")


def test_d1_acompte_imprime_avec_un_signe_moins():
    f = ft(
        ligne(N.frais_dedouanement, "100.00"),
        total_ht="100.00",
        total_tva="0.00",
        total_ttc="100.00",
        acomptes="-40.00",
        net_a_payer="60.00",
    )
    assert (
        un(run_controls(ctx_de([f]), controles=["D1"]), "D1", sous_controle="net_a_payer").outcome
        is Outcome.conforme
    )


# --- D-705 : composante dont l'écart s'explique par une ligne de taxation non lue -----------------------------


def test_c4_non_verifiable_si_le_total_a_payer_contient_des_lignes_non_lues():
    d = declaration(
        id="doc_d",
        mrn=MRN_A,
        taxations=[
            taxation("doc_d", categorie=CategorieTaxe.droit, montant="366.40"),
            taxation("doc_d", type_taxe="B00", categorie=CategorieTaxe.tva, montant="683.95"),
        ],
        total_a_payer=vs("declaration.total_a_payer", "2277.07", document_id="doc_d"),
    )  # TVA 1226,72 non lue
    f = ft(ligne(N.debours_droits, "366.40", mrn=MRN_A), ligne(N.debours_tva, "1910.67", mrn=MRN_A))
    rs = run_controls(ctx_de([d, f]), controles=["C4", "C5"])
    assert un(rs, "C4").outcome is Outcome.non_verifiable
    assert un(rs, "C5").outcome is Outcome.conforme


# --- D-702 : assiette hors TVA avec une ligne de catégorie inconnue et TVA autoliquidée ----------------------


def test_c6_assiette_hors_tva_quand_une_taxe_n_est_pas_ventilee():
    d = declaration(
        id="doc_d",
        mrn=MRN_A,
        taxations=[
            taxation("doc_d", categorie=CategorieTaxe.droit, montant="1000.00"),
            taxation("doc_d", type_taxe="X99", categorie=CategorieTaxe.inconnue, montant="200.00"),
            taxation(
                "doc_d",
                type_taxe="B00",
                categorie=CategorieTaxe.tva,
                montant="400.00",
                paiement=PaiementNormalise.autoliquide,
            ),
        ],
    )
    f = ft(
        ligne(N.debours_droits, "1100.00", mrn=MRN_A),
        ligne(N.debours_autres_taxes, "200.00", mrn=MRN_A),
        ligne(N.frais_avance_fonds, "26.00", mrn=MRN_A),
    )  # 2 % × 1300 ; excédent 100 -> 2,00
    r = un(run_controls(ctx_de([d, f]), controles=["C1", "C5", "C6"]), "C6")
    assert r.outcome is not Outcome.non_verifiable and r.constat.montant_en_jeu == D("2.00")


# --- D-707 : C8 un constat par numéro de TVA facturé -----------------------------------------------------------


def test_c8_deux_factures_du_meme_envoi_un_seul_constat():
    imp = "FR86000453241"
    d = declaration(id="doc_d", mrn=MRN_A)
    d.dec.importateur = Partie(tva=vs("declaration.importateur.tva", imp, document_id="doc_d"))
    f1 = ft(ligne(N.debours_droits, "10.00"), fid="doc_f1", numero="FD-1", client_tva="FR68000458570")
    f2 = ft(
        ligne(N.frais_dedouanement, "60.00", fid="doc_f2"),
        fid="doc_f2",
        numero="FP-2",
        client_tva="FR68000458570",
    )
    cs = constats(run_controls(ctx_de([d, f1, f2]), controles=["C8"]), "C8")
    assert len(cs) == 1 and {"doc_f1", "doc_f2"} <= set(cs[0].constat.documents_concernes)


# --- D-709 : C7 -------------------------------------------------------------------------------------------------


def test_refs_confondables():
    assert refs_confondables("DEMOB10063149", "DEMO810063149")
    assert refs_confondables("26FRP8MOGSNIDSK", "26FRP8MOG5NJDSK")
    assert not refs_confondables("DEMO810063149", "DEMO810063149")
    assert not refs_confondables("99967662475", "99912345678")


def test_c7_mrn_d_un_dossier_sans_lien_reste_signale_et_reference_mal_lue_toleree():
    d = declaration(id="doc_d", mrn=MRN_A, documents_references=[])
    autre_dec = declaration(id="doc_x", mrn=MRN_B)
    autre = AutreDossier(dossier=dossier_pour([autre_dec], id="dos_x"), documents={"doc_x": autre_dec})
    f = ft(ligne(N.debours_droits, "10.00"), mrns=(MRN_A, MRN_B))
    c = un(run_controls(ctx_de([d, f], autres=[autre]), controles=["C7"]), "C7")
    assert c.constat is not None and MRN_B in c.constat.libelle
    # MRN lu par OCR avec une confusion S/5 : pas signalé comme « sans correspondance »
    d2 = declaration(id="doc_d2", mrn="26FRS000000000AA1")
    lu = vs(
        "facture_transitaire.refs_mrn[]",
        "26FR5000000000AA1",
        document_id="doc_ft1",
        methode="ocr",
        confiance=0.8,
    )
    f2 = ft(ligne(N.debours_droits, "10.00"))
    f2.ft.refs_mrn = [lu]
    f2.pages[0].qualite_texte = QualiteTexte.ocr
    assert un(run_controls(ctx_de([d2, f2]), controles=["C7"]), "C7").outcome is Outcome.conforme


def test_c7_sans_declaration_les_mrn_ne_sont_pas_juges():
    f = ft(ligne(N.debours_droits, "10.00"), mrns=(MRN_A,))
    assert not constats(run_controls(ctx_de([f]), controles=["C7"]), "C7")


# --- D-710 : B2, TVA autoliquidée indiquée par le code 1008 ----------------------------------------------------


def test_b2_total_a_payer_hors_tva_autoliquidee_signalee_par_1008():
    d = declaration(
        id="doc_d",
        mrn=MRN_A,
        taxations=[
            taxation(
                "doc_d", categorie=CategorieTaxe.droit, montant="143.61", paiement=PaiementNormalise.inconnu
            ),
            taxation(
                "doc_d",
                article="2",
                categorie=CategorieTaxe.droit,
                montant="80.22",
                paiement=PaiementNormalise.inconnu,
            ),
            taxation(
                "doc_d",
                type_taxe="B00",
                categorie=CategorieTaxe.tva,
                montant="1396.46",
                paiement=PaiementNormalise.inconnu,
            ),
            taxation(
                "doc_d",
                article="2",
                type_taxe="B00",
                categorie=CategorieTaxe.tva,
                montant="959.82",
                paiement=PaiementNormalise.inconnu,
            ),
        ],
        total_a_payer=vs("declaration.total_a_payer", "223.83", document_id="doc_d"),
        indices_autoliquidation=[
            IndiceAutoliquidation(
                type=TypeIndiceAutoliquidation.code_1008,
                valeur=vs("declaration.indices_autoliquidation[].valeur", "1008", document_id="doc_d"),
                tva=vs("declaration.indices_autoliquidation[].tva", "FR15000100008", document_id="doc_d"),
            )
        ],
    )
    d.dec.articles = [
        ArticleDeclaration(
            numero_article=vs("declaration.articles[].numero_article", "1", document_id="doc_d")
        )
    ]
    rs = run_controls(ctx_de([d]), controles=["B2"])
    assert not constats(rs, "B2")


# --- D-711 : C5 et forfait petits envois ----------------------------------------------------------------------


def test_c5_forfait_non_lu_sur_la_declaration_n_est_pas_retire_de_la_seule_facture():
    d = declaration(
        id="doc_d",
        mrn=MRN_A,
        taxations=[
            taxation("doc_d", type_taxe="B00", categorie=CategorieTaxe.tva, montant="42.64"),
        ],
        total_a_payer=vs("declaration.total_a_payer", "50.14", document_id="doc_d"),
    )  # forfait 7,50 non lu
    f = ft(
        ligne(N.debours_forfait_petits_envois, "7.50", mrn=MRN_A), ligne(N.debours_tva, "42.64", mrn=MRN_A)
    )
    assert un(run_controls(ctx_de([d, f]), controles=["C5"]), "C5").outcome is Outcome.conforme


def test_raisons_utilisees_existent():
    assert RaisonCode.couvert_par_autre_controle and RaisonCode.valeur_absente


# --- D-1210 : imputation unique des avoirs (§17.2) pour C, D et E ------------------------------------------


def _avoir(aid, *lignes, numero="AV-FICTIF-7", origine="FA-FICTIF-7", emetteur_tva=None):
    from controldone.model import Partie

    em = Partie(tva=vs("avoir.emetteur.tva", emetteur_tva, document_id=aid)) if emetteur_tva else Partie()
    return document(
        TypeDocument.avoir,
        ChampsAvoir(
            numero=vs("avoir.numero", numero, document_id=aid),
            emetteur=em,
            refs_facture_origine=[vs("avoir.refs_facture_origine[]", origine, document_id=aid)]
            if origine
            else [],
            lignes=list(lignes),
        ),
        id=aid,
    )


def test_d3_avoir_citant_la_facture_impute_malgre_un_mrn_de_ligne_mal_lu():
    # F7 : MRN de la ligne de facture lu « …O… » et celui de l'avoir « …0… » : l'avoir cite la facture,
    # il est imputé (comme en E6).
    f = ft(
        ligne(N.frais_dedouanement, "83.34", libelle="Frais de dédouanement", mrn="26FRBIOXUODIVBQIS3"),
        numero="FA-FICTIF-7",
    )
    av = _avoir("doc_av", ligne(N.frais_dedouanement, "11.30", fid="doc_av", mrn="26FRBI0XUODIVBQIS3"))
    r = un(run_controls(ctx_de([f, av]), controles=["D3"]), "D3")
    assert r.constat.montant_en_jeu == D("12.04") and r.constat.montant_brut == D("23.34")


def test_d3_avoir_d_un_autre_transitaire_non_impute():
    # D-304 : même émetteur exigé (C, D et E appliquent la même règle).
    f = ft(ligne(N.frais_dedouanement, "83.34", libelle="Frais de dédouanement"), numero="FA-FICTIF-7")
    av = _avoir("doc_av", ligne(N.frais_dedouanement, "11.30", fid="doc_av"), emetteur_tva="FR61000999990")
    r = un(run_controls(ctx_de([f, av]), controles=["D3"]), "D3")
    assert r.constat.montant_en_jeu == D("23.34") and "doc_av" not in r.constat.documents_concernes


def test_d3_meme_numero_d_avoir_sans_meme_emetteur_n_est_pas_un_doublon():
    # Avant : C et D ne gardaient qu'un avoir par numéro ; désormais la règle E3 (même émetteur et même
    # numéro) vaut partout : l'avoir dont l'émetteur est illisible n'est pas tenu pour un doublon (D-305).
    f = ft(ligne(N.frais_dedouanement, "83.34", libelle="Frais de dédouanement"), numero="FA-FICTIF-7")
    a1 = _avoir(
        "doc_av1",
        ligne(N.frais_dedouanement, "5.00", fid="doc_av1"),
        numero="AV-001",
        emetteur_tva=TVA_TRANSITAIRE,
    )
    a2 = _avoir("doc_av2", ligne(N.frais_dedouanement, "6.30", fid="doc_av2"), numero="AV-001")
    r = un(run_controls(ctx_de([f, a1, a2]), controles=["D3"]), "D3")
    assert r.constat.montant_en_jeu == D("12.04")


def test_avoir_peu_lisible_non_impute():
    # C_MIN_UTILE appliqué aux lignes d'avoir pour C, D et E (D-1210).
    from controldone.controls import _aides_befg as aides

    peu_lisible = LigneFactureTransitaire(
        nature=N.frais_dedouanement,
        montant_ht=vs("avoir.lignes[].montant_ht", "11.30", document_id="doc_av", confiance=0.3),
    )
    av = _avoir("doc_av", peu_lisible)
    ctx = ctx_de([ft(ligne(N.frais_dedouanement, "83.34")), av])
    assert aides.lignes_credit_du_dossier(ctx) == []


# --- D-2205 / D-2206 : avoirs rattachés par le MRN ou le transport ; avoir non ventilé ----------------------


def _avoir_tete(aid, *lignes, mrns=(), transports=(), total_ht=None):
    return document(
        TypeDocument.avoir,
        ChampsAvoir(
            numero=vs("avoir.numero", "AV-FICTIF-9", document_id=aid),
            refs_mrn=[vs("avoir.refs_mrn[]", m, document_id=aid) for m in mrns],
            refs_transport=[vs("avoir.refs_transport[]", t, document_id=aid) for t in transports],
            total_credite_ht=vs("avoir.total_credite_ht", total_ht, document_id=aid) if total_ht else None,
            lignes=list(lignes),
        ),
        id=aid,
    )


def test_d3_avoir_sans_facture_d_origine_rattache_par_le_mrn_de_l_en_tete():
    # D-2206 : l'avoir ne cite que le MRN ; la ligne de la facture n'en porte pas, l'en-tête oui (§12.2).
    f = ft(
        ligne(N.frais_dedouanement, "80.00", libelle="Frais de dédouanement"),
        numero="FA-FICTIF-9",
        mrns=(MRN_A,),
    )
    av = _avoir_tete("doc_av", ligne(N.frais_dedouanement, "20.00", fid="doc_av"), mrns=(MRN_A,))
    assert un(run_controls(ctx_de([f, av]), controles=["D3"]), "D3").outcome is Outcome.conforme
    # Rattachement par la référence de transport seulement (troisième palier).
    f = ft(
        ligne(N.frais_dedouanement, "80.00", libelle="Frais de dédouanement"),
        numero="FA-FICTIF-9",
        transports=("999-12345675",),
    )
    av = _avoir_tete(
        "doc_av", ligne(N.frais_dedouanement, "20.00", fid="doc_av"), transports=("999-12345675",)
    )
    assert un(run_controls(ctx_de([f, av]), controles=["D3"]), "D3").outcome is Outcome.conforme


def test_avoir_non_ventile_rattache_a_la_facture_jamais_certain():
    # D-2205 (§8.5.1 condition 7) : un avoir du même transitaire, rattaché par le MRN, dont ni les lignes ni le
    # total n'ont pu être lus : rien n'exclut qu'il solde l'écart -> à vérifier, raison avoir_non_ventile.
    f = ft(
        ligne(N.frais_dedouanement, "80.00", libelle="Frais de dédouanement"),
        numero="FA-FICTIF-9",
        mrns=(MRN_A,),
    )
    r = un(run_controls(ctx_de([f]), controles=["D3"]), "D3")
    assert r.outcome is Outcome.ecart_certain
    av = _avoir_tete("doc_av", mrns=(MRN_A,))
    r = un(run_controls(ctx_de([f, av]), controles=["D3"]), "D3")
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_ventile in r.constat.raisons
    assert r.constat.montant_en_jeu == D("20.00")
    # Total lu mais aucune ligne ventilée : même prudence.
    av = _avoir_tete("doc_av", mrns=(MRN_A,), total_ht="20.00")
    r = un(run_controls(ctx_de([f, av]), controles=["D3"]), "D3")
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_ventile in r.constat.raisons
    # Avoir du dossier sans lien établi avec cette facture (autre MRN lu) : D-4212, rien n'exclut une référence mal
    # lue (avoir rattaché par le seul MRN) ; jamais certain, raison avoir_non_impute.
    av = _avoir_tete("doc_av", mrns=(MRN_B,))
    r = un(run_controls(ctx_de([f, av]), controles=["D3"]), "D3")
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_impute in r.constat.raisons
    # C1 sur la même facture : même règle.
    fc = ft(ligne(N.debours_droits, "150.00", mrn=MRN_A), numero="FA-FICTIF-9", mrns=(MRN_A,))
    d = dec("doc_dec", MRN_A, "100.00")
    assert un(run_controls(ctx_de([d, fc]), controles=["C1"]), "C1").outcome is Outcome.ecart_certain
    r = un(run_controls(ctx_de([d, fc, _avoir_tete("doc_av", mrns=(MRN_A,))]), controles=["C1"]), "C1")
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_ventile in r.constat.raisons


def test_avoir_deja_deduit_par_d3_n_est_pas_reimpute_sur_un_autre_ecart():
    # D-2208 : l'avoir de 15,00 (dédouanement) solde l'écart D3 (75,00 facturés, 60,00 au tarif) ; il ne doit
    # pas être imputé une seconde fois par E6 sur l'écart D2 (ligne hors grille) de la même facture.
    f = ft(
        ligne(N.frais_dedouanement, "75.00", libelle="Frais de dédouanement"),
        ligne(N.surcharge, "45.00", libelle="Surcharge haute saison"),
        numero="FA-FICTIF-7",
    )
    av = _avoir("doc_av", ligne(N.frais_dedouanement, "15.00", fid="doc_av"))
    rs = run_controls(ctx_de([f, av]), controles=["D3", "D7", "E5", "E6"])
    assert un(rs, "D3").outcome is Outcome.conforme
    assert un(rs, "D7").constat.montant_en_jeu == D("45.00")
    assert not constats(rs, "E6") and not constats(rs, "E5")
