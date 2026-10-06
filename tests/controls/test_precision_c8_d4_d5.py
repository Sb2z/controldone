"""Écart certain C8, D4, D5 seulement sur preuve solide (D-2211 à D-2213). Données fictives construites ici."""

from decimal import Decimal as D

from controldone.controls.context import AutreDossier, ControlContext
from controldone.controls.framework import run_controls
from controldone.model import (
    BasePourcentage,
    CategorieTaxe,
    Entite,
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
    Transitaire,
)
from controldone.testing import (
    declaration,
    dossier_pour,
    facture_commerciale,
    facture_transitaire,
    taxation,
    vs,
)

N = NatureLigne
TVA_TRANSITAIRE = "FR11000555550"
TRANSITAIRES = [Transitaire(id="tra_1", nom="Transit FICTIF", tva=TVA_TRANSITAIRE)]
MRN_A = "26FRAAAAAAAAAAAAA1"
MRN_B = "26FRBBBBBBBBBBBBB2"
TVA_CLIENT = "FR68000458570"  # entité FICTIVE du client
TVA_CLIENT_2 = "FR41000561381"  # autre entité FICTIVE du client
TVA_TIERS = "FR86000453241"  # société FICTIVE hors du client
ENTITES = [
    Entite(id="ent_1", raison_sociale="Maison FICTIVE SAS", tva=TVA_CLIENT),
    Entite(id="ent_2", raison_sociale="Atelier FICTIF SAS", tva=TVA_CLIENT_2),
]

GRILLE = GrilleTarifaire(
    transitaire_id="tra_1",
    reference="DEV-FICTIF-2026",
    statut=StatutGrille.validee,
    prestations_hors_grille=PrestationsHorsGrille.tolerees,
    postes=[
        PosteGrille(code_poste="DEDOU", nature=N.frais_dedouanement, mode=ModePoste.forfait, prix=D("60.00")),
        PosteGrille(code_poste="LIVR", nature=N.transport, mode=ModePoste.forfait, prix=D("90.00")),
        PosteGrille(
            code_poste="FAF",
            nature=N.frais_avance_fonds,
            mode=ModePoste.pourcentage,
            pourcentage=D("2"),
            minimum=D("15.00"),
            base_pourcentage=BasePourcentage.droits,
        ),
    ],
)


def ligne(nature, montant, *, libelle=None, mrn=None, page=1, fid="doc_ft1"):
    def v(nom, val):
        return (
            None
            if val is None
            else vs(f"facture_transitaire.lignes[].{nom}", val, document_id=fid, page=page)
        )

    return LigneFactureTransitaire(
        libelle=v("libelle", libelle or nature.value.replace("_", " ")),
        nature=nature,
        montant_ht=v("montant_ht", montant),
        mrn=v("mrn", mrn),
    )


def ft(
    *lignes,
    fid="doc_ft1",
    mrns=(MRN_A,),
    client_tva=TVA_CLIENT,
    transports=(),
    devise=None,
    total_ht=None,
    total_debours=None,
):
    champs = {}
    if total_debours:
        champs["total_debours"] = vs("facture_transitaire.total_debours", total_debours, document_id=fid)
    if devise:
        champs["devise"] = vs("facture_transitaire.devise", devise, document_id=fid)
    if total_ht:
        champs["total_ht"] = vs("facture_transitaire.total_ht", total_ht, document_id=fid)
    return facture_transitaire(
        id=fid,
        numero=vs("facture_transitaire.numero", "FA-FICTIF-1", document_id=fid),
        date=vs("facture_transitaire.date", "2026-09-15", document_id=fid),
        emetteur=Partie(tva=vs("facture_transitaire.emetteur.tva", TVA_TRANSITAIRE, document_id=fid)),
        client_facture=Partie(tva=vs("facture_transitaire.client_facture.tva", client_tva, document_id=fid)),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", m, document_id=fid) for m in mrns],
        refs_transport=[vs("facture_transitaire.refs_transport[]", t, document_id=fid) for t in transports],
        lignes=list(lignes),
        **champs,
    )


def dec(did="doc_dec", mrn=MRN_A, *, importateur=TVA_CLIENT, declarant=None, droits="1000.00", tva=None):
    tx = [taxation(did, categorie=CategorieTaxe.droit, montant=droits)]
    if tva is not None:
        tx.append(taxation(did, type_taxe="B00", categorie=CategorieTaxe.tva, montant=tva))
    d = declaration(id=did, mrn=mrn, taxations=tx)
    d.dec.importateur = Partie(tva=vs("declaration.importateur.tva", importateur, document_id=did))
    if declarant:
        d.dec.declarant = Partie(tva=vs("declaration.declarant.tva", declarant, document_id=did))
    return d


def fc(acheteur, fid="doc_fc"):
    return facture_commerciale(
        id=fid, acheteur=Partie(tva=vs("facture_commerciale.acheteur.tva", acheteur, document_id=fid))
    )


def ctx_de(docs, *, autres=(), dossier_id="dos_a"):
    return ControlContext.construire(
        dossier_pour(docs, id=dossier_id),
        docs,
        ProfilTolerances(id="tol_test"),
        execution_id="exe_test",
        grilles=[GRILLE],
        entites=ENTITES,
        transitaires=TRANSITAIRES,
        autres_dossiers=list(autres),
    )


def resultat(docs, cid, **kw):
    xs = [r for r in run_controls(ctx_de(docs, **kw), controles=[cid]) if r.controle_id == cid and r.constat]
    assert len(xs) == 1, xs
    return xs[0]


# --- D-2211 : C8 -------------------------------------------------------------------------------------------------


def test_c8_importateur_tiers_et_facture_au_client_acheteur_a_verifier():
    """La déclaration désigne une société hors du client ; le transitaire facture l'acheteur de la facture
    commerciale, entité du client : l'écart est sur la déclaration (A1), pas certain pour C8."""
    r = resultat([dec(importateur=TVA_TIERS), fc(TVA_CLIENT), ft(client_tva=TVA_CLIENT)], "C8")
    assert r.outcome is Outcome.a_verifier
    assert RaisonCode.entite_facturee_attestee in r.constat.raisons
    assert r.details["entite_facturee_attestee"] == ["acheteur_facture_commerciale_importateur_hors_client"]


def test_c8_autre_entite_du_groupe_reste_certain():
    """Importateur = entité du client ; facture adressée à une autre entité du groupe : constat certain."""
    r = resultat([dec(importateur=TVA_CLIENT), fc(TVA_CLIENT_2), ft(client_tva=TVA_CLIENT_2)], "C8")
    assert r.outcome is Outcome.ecart_certain


def test_c8_facture_a_un_tiers_reste_certain():
    r = resultat([dec(importateur=TVA_CLIENT), fc(TVA_CLIENT), ft(client_tva=TVA_TIERS)], "C8")
    assert r.outcome is Outcome.ecart_certain


def test_c8_importateur_d_une_autre_declaration_de_la_meme_facture():
    """Relevé couvrant deux envois répartis entre deux dossiers ; l'autre déclaration a pour importateur
    l'entité facturée."""
    f = ft(
        ligne(N.debours_droits, "10.00", mrn=MRN_A),
        ligne(N.debours_droits, "20.00", mrn=MRN_B),
        mrns=(MRN_A, MRN_B),
        client_tva=TVA_CLIENT_2,
    )
    da = dec("doc_a", MRN_A, importateur=TVA_CLIENT)
    db = dec("doc_b", MRN_B, importateur=TVA_CLIENT_2)
    autre = AutreDossier(dossier=dossier_pour([db, f], id="dos_b"), documents={"doc_b": db, f.id: f})
    r = resultat([da, f], "C8", autres=[autre], dossier_id="dos_a")
    assert r.outcome is Outcome.a_verifier
    assert "importateur_autre_declaration_de_la_facture" in r.details["entite_facturee_attestee"]


def test_c8_numero_du_declarant_lu_comme_client():
    r = resultat(
        [dec(importateur=TVA_CLIENT, declarant="FR29000667980"), ft(client_tva="FR29000667980")], "C8"
    )
    assert r.outcome is Outcome.a_verifier
    assert r.details["entite_facturee_attestee"] == ["numero_emetteur_ou_declarant"]


def test_c8_meme_siren_sous_deux_identifiants():
    """Numéro EORI (FR + SIREN + 00000) lu comme TVA de l'importateur : même société que la TVA facturée."""
    r = resultat([dec(importateur="FR00045857000000"), ft(client_tva=TVA_CLIENT)], "C8")
    assert r.outcome is Outcome.a_verifier and "meme_siren" in r.details["entite_facturee_attestee"]


# --- D-2212 : D5 -------------------------------------------------------------------------------------------------


def test_d5_meme_mrn_sur_les_deux_lignes_reste_certain():
    f = ft(
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A),
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A),
        total_ht="120.00",
    )
    r = resultat([dec(), f], "D5")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("60.00")


def test_d5_lignes_sans_mrn_sur_une_facture_de_plusieurs_envois():
    f = ft(ligne(N.frais_dedouanement, "60.00"), ligne(N.frais_dedouanement, "60.00"), mrns=(MRN_A, MRN_B))
    r = resultat([dec("doc_a", MRN_A), dec("doc_b", MRN_B), f], "D5")
    assert r.outcome is Outcome.a_verifier and RaisonCode.doublon_non_etabli in r.constat.raisons
    assert "plusieurs_envois_sans_reference_sur_la_ligne" in r.details["doublon_non_etabli"]


def test_d5_livraison_par_contenant():
    f = ft(
        ligne(N.transport, "90.00", libelle="Livraison", mrn=MRN_A),
        ligne(N.transport, "90.00", libelle="Livraison", mrn=MRN_A),
        transports=("MSKU0000001", "TGHU0000002"),
    )
    r = resultat([dec(), f], "D5")
    assert (
        r.outcome is Outcome.a_verifier and "plusieurs_titres_de_transport" in r.details["doublon_non_etabli"]
    )


def test_d5_ligne_annulee_par_une_correction_n_est_pas_un_doublon():
    f = ft(
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A),
        ligne(N.frais_dedouanement, "-60.00", mrn=MRN_A),
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A),
    )
    rs = [r for r in run_controls(ctx_de([dec(), f]), controles=["D5"]) if r.controle_id == "D5"]
    assert [r.outcome for r in rs] == [Outcome.conforme]


def test_d5_ligne_reportee_en_haut_de_la_page_suivante():
    f = ft(
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A, page=1),
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A, page=2),
    )
    r = resultat([dec(), f], "D5")
    assert r.outcome is Outcome.a_verifier
    assert "ligne_reportee_sur_la_page_suivante" in r.details["doublon_non_etabli"]


def test_d5_total_sans_la_repetition():
    f = ft(
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A),
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A),
        ligne(N.transport, "90.00", mrn=MRN_A),
        total_ht="150.00",
    )
    r = resultat([dec(), f], "D5")
    assert (
        r.outcome is Outcome.a_verifier and "repetition_absente_du_total" in r.details["doublon_non_etabli"]
    )


# --- D-2213 : D4 -------------------------------------------------------------------------------------------------


def _d4(faf, *, droits="1000.00", tva="2000.00", **kw):
    kw.setdefault("total_debours", str(D(droits) + D(tva)))
    f = ft(
        ligne(N.debours_droits, droits, mrn=MRN_A),
        ligne(N.debours_tva, tva, mrn=MRN_A),
        ligne(N.frais_avance_fonds, faf, mrn=MRN_A),
        **kw,
    )
    return resultat([dec(droits=droits, tva=tva), f], "D4")


def test_d4_faf_sur_droits_et_tva_au_lieu_des_droits():
    r = _d4("60.00")  # 2 % × 3 000 (droits + TVA) ; grille : 2 % des droits = 20,00
    assert r.outcome is Outcome.a_verifier and RaisonCode.assiette_alternative in r.constat.raisons
    assert r.constat.montant_en_jeu == D("40.00")


def test_d4_faf_arrondi_a_l_unite():
    r = _d4("25.00", droits="1234.56")  # 2 % × 1 234,56 = 24,69
    assert r.outcome is Outcome.a_verifier and r.details["assiette_alternative"] == "arrondi_a_l_unite"


def test_d4_minimum_applique_par_declaration():
    f = ft(
        ligne(N.debours_droits, "100.00", mrn=MRN_A),
        ligne(N.debours_droits, "200.00", mrn=MRN_B),
        ligne(N.frais_avance_fonds, "30.00"),
        mrns=(MRN_A, MRN_B),
    )  # 2 × minimum 15,00
    r = resultat([dec("doc_a", MRN_A, droits="100.00"), dec("doc_b", MRN_B, droits="200.00"), f], "D4")
    assert r.outcome is Outcome.a_verifier and RaisonCode.assiette_alternative in r.constat.raisons


def test_d4_ecart_sans_autre_explication_reste_certain():
    r = _d4("45.00")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("25.00")


def test_d4_facture_dans_une_autre_devise():
    r = _d4("45.00", devise="CHF")
    assert r.outcome is Outcome.a_verifier and RaisonCode.devise_incertaine in r.constat.raisons
