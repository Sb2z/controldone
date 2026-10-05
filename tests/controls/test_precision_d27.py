"""Écarts certains sur g4 : TVA comprise, rattachement des lignes par MRN, assiette du FAF, doublons, facture d'un
autre envoi (D-2701 à D-2708). Données entièrement fictives construites ici."""

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
from controldone.model.enums import RAISON_LIBELLES, Methode
from controldone.recouvrement.imputation import REGLE_HT_DEPUIS_TTC, montant_net_ligne
from controldone.testing import (
    declaration,
    dossier_pour,
    facture_commerciale,
    facture_transitaire,
    taxation,
    vs,
)

N = NatureLigne
TVA_TRANSITAIRE = "FR11000555550"  # transitaire FICTIF
TVA_CLIENT = "FR68000458570"  # entité FICTIVE du client
TVA_CLIENT_2 = "FR41000561381"  # autre entité FICTIVE du client
MRN_A = "26FRAAAAAAAAAAAAA1"
MRN_B = "26FRBBBBBBBBBBBBB2"
MRN_C = "26FR1M2SENIHZJNV34"  # lu « 26FRIM2… » par l'OCR (confusion 1/I)
MRN_C_LU = "26FRIM2SENIHZJNV34"
ENTITES = [Entite(id="ent_1", raison_sociale="Maison FICTIVE SAS", tva=TVA_CLIENT),
           Entite(id="ent_2", raison_sociale="Atelier FICTIF SAS", tva=TVA_CLIENT_2)]
TRANSITAIRES = [Transitaire(id="tra_1", nom="Transit FICTIF", tva=TVA_TRANSITAIRE)]


def _grille(*postes, maximum=None):
    return GrilleTarifaire(
        transitaire_id="tra_1", reference="DEV-FICTIF-2027", statut=StatutGrille.validee,
        prestations_hors_grille=PrestationsHorsGrille.interdites,
        postes=[
            PosteGrille(code_poste="DEDOU", nature=N.frais_dedouanement, mode=ModePoste.forfait, prix=D("60.00")),
            PosteGrille(code_poste="FAF", nature=N.frais_avance_fonds, mode=ModePoste.pourcentage,
                        pourcentage=D("2"), minimum=D("15.00"), maximum=maximum,
                        base_pourcentage=BasePourcentage.debours_total),
            *postes,
        ],
    )


GRILLE = _grille()


def _v(fid, nom, val, **kw):
    return None if val is None else vs(f"facture_transitaire.lignes[].{nom}", val, document_id=fid, **kw)


def ligne(nature, montant, *, libelle=None, mrn=None, mrn_conf=0.99, fid="doc_ft1", page=1, **kw):
    return LigneFactureTransitaire(
        libelle=_v(fid, "libelle", libelle or nature.value.replace("_", " "), page=page), nature=nature,
        montant_ht=_v(fid, "montant_ht", montant, page=page),
        mrn=_v(fid, "mrn", mrn, confiance=mrn_conf, page=page),
        **{k: _v(fid, k, x, page=page) for k, x in kw.items()},
    )


def ft(*lignes, fid="doc_ft1", mrns=(MRN_A,), client_tva=TVA_CLIENT, transports=(), releve=False, **totaux):
    champs = {k: vs(f"facture_transitaire.{k}", x, document_id=fid) for k, x in totaux.items()}
    return facture_transitaire(
        id=fid, numero=vs("facture_transitaire.numero", "FA-FICTIF-27", document_id=fid),
        date=vs("facture_transitaire.date", "2026-09-15", document_id=fid),
        emetteur=Partie(tva=vs("facture_transitaire.emetteur.tva", TVA_TRANSITAIRE, document_id=fid)),
        client_facture=Partie(tva=vs("facture_transitaire.client_facture.tva", client_tva, document_id=fid)),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", m, document_id=fid) for m in mrns],
        refs_transport=[vs("facture_transitaire.refs_transport[]", t, document_id=fid) for t in transports],
        est_releve=releve, lignes=list(lignes), **champs,
    )


def dec(did="doc_dec", mrn=MRN_A, *, droits="1000.00", autres=None, tva=None, importateur=TVA_CLIENT):
    tx = [taxation(did, categorie=CategorieTaxe.droit, type_taxe="A00", montant=droits)]
    if autres is not None:
        tx.append(taxation(did, categorie=CategorieTaxe.autre_taxe, type_taxe="A30", montant=autres))
    if tva is not None:
        tx.append(taxation(did, categorie=CategorieTaxe.tva, type_taxe="B00", montant=tva))
    d = declaration(id=did, mrn=mrn, taxations=tx)
    d.dec.importateur = Partie(tva=vs("declaration.importateur.tva", importateur, document_id=did))
    return d


def ctx_de(docs, *, autres=(), grille=GRILLE, dossier_id="dos_a"):
    return ControlContext.construire(
        dossier_pour(docs, id=dossier_id), docs, ProfilTolerances(id="tol_test"), execution_id="exe_test",
        grilles=[grille], entites=ENTITES, transitaires=TRANSITAIRES, autres_dossiers=list(autres),
        exiger_lecture_corroboree=False,
    )


def resultats(docs, cid, **kw):
    return [r for r in run_controls(ctx_de(docs, **kw), controles=[cid]) if r.controle_id == cid]


def constats(docs, cid, **kw):
    return [r for r in resultats(docs, cid, **kw) if r.constat is not None]


def un_constat(docs, cid, **kw):
    xs = constats(docs, cid, **kw)
    assert len(xs) == 1, xs
    return xs[0]


# --- D-2701 : lignes TVA comprise -------------------------------------------------------------------------------


def _ligne_ttc(ttc, taux, *, derive=True, fid="doc_ft1", nature=N.frais_dedouanement, libelle="Desalfandegamento"):
    v_ttc = vs("facture_transitaire.lignes[].montant_ttc", ttc, document_id=fid, confiance=0.97)
    v_taux = vs("facture_transitaire.lignes[].taux_tva", taux, document_id=fid, confiance=0.95)
    ht = None
    if derive:
        net = (D(ttc) / (1 + D(taux) / 100)).quantize(D("0.01"))
        ht = vs("facture_transitaire.lignes[].montant_ht", str(net), document_id=fid, methode=Methode.derive,
                confiance=0.60, page=None, derivee_de=[v_ttc.id, v_taux.id], regle_derivation=REGLE_HT_DEPUIS_TTC)
    return LigneFactureTransitaire(libelle=_v(fid, "libelle", libelle), nature=nature, montant_ht=ht,
                                   montant_ttc=v_ttc, taux_tva=v_taux)


def test_ht_deduit_du_ttc_marque_et_jamais_certain():
    lg = _ligne_ttc("96.00", "20")
    v = montant_net_ligne(lg)
    assert v is not None and v.valeur == "80.00" and RaisonCode.montant_tva_comprise in v.raisons
    assert v.confiance <= 0.60
    r = un_constat([dec(), ft(_ligne_ttc("120.00", "20"))], "D3")  # 100,00 HT contre 60,00 : écart 40,00
    assert r.outcome is Outcome.a_verifier and RaisonCode.montant_tva_comprise in r.constat.raisons
    assert r.constat.montant_en_jeu == D("40.00")


def test_ttc_sans_ht_n_est_net_que_sans_tva():
    exoneree = _ligne_ttc("60.00", "0", derive=False)
    assert montant_net_ligne(exoneree) is exoneree.montant_ttc
    taxee = _ligne_ttc("96.00", "20", derive=False)
    v = montant_net_ligne(taxee)
    assert v is not None and v.valeur == "96.00" and RaisonCode.montant_tva_comprise in v.raisons
    r = un_constat([dec(), ft(taxee)], "D3")
    assert r.outcome is Outcome.a_verifier and RaisonCode.montant_tva_comprise in r.constat.raisons


def test_ligne_ht_lue_inchangee():
    lg = ligne(N.frais_dedouanement, "80.00")
    assert montant_net_ligne(lg) is lg.montant_ht
    assert RAISON_LIBELLES[RaisonCode.montant_tva_comprise].startswith("à vérifier")


# --- D-2702 : rattachement d'une ligne de débours à une déclaration -----------------------------------------------


def _releve_deux_dossiers(mrn_b_conf):
    """Relevé FICTIF de deux envois ; la ligne d'autres taxes de l'envoi B a un MRN lu sous ``C_MIN_UTILE``."""
    f = ft(ligne(N.debours_autres_taxes, "50.00", mrn=MRN_A), ligne(N.debours_autres_taxes, "30.00", mrn=MRN_B,
                                                                     mrn_conf=mrn_b_conf),
           mrns=(MRN_A, MRN_B), total_debours="80.00")
    da = dec("doc_a", MRN_A, droits="0.00", autres="50.00")
    db = dec("doc_b", MRN_B, droits="0.00", autres="30.00")
    autre = AutreDossier(dossier=dossier_pour([db, f], id="dos_b"), documents={"doc_b": db, f.id: f})
    return [da, f], [autre]


def test_c2_ligne_au_mrn_illisible_d_un_autre_dossier_non_attribuee():
    docs, autres = _releve_deux_dossiers(0.45)
    rs = resultats(docs, "C2", autres=autres)
    assert [r.outcome for r in rs] == [Outcome.conforme]


def test_c2_mrn_lu_a_une_confusion_pres_sur_facture_multi_mrn_a_verifier():
    f = ft(ligne(N.debours_autres_taxes, "52.20", mrn=MRN_C_LU), ligne(N.debours_droits, "10.00", mrn=MRN_B),
           mrns=(MRN_C_LU, MRN_B), total_debours="62.20")
    r = un_constat([dec("doc_c", MRN_C, droits="0.00", autres="50.00"), f], "C2")
    assert r.outcome is Outcome.a_verifier and RaisonCode.attribution_non_univoque in r.constat.raisons
    assert r.constat.montant_en_jeu == D("2.20")


def test_c2_mrn_lu_a_une_confusion_pres_sur_facture_d_un_envoi_reste_certain():
    f = ft(ligne(N.debours_autres_taxes, "52.20", mrn=MRN_C_LU), mrns=(MRN_C_LU,), total_debours="52.20")
    r = un_constat([dec("doc_c", MRN_C, droits="0.00", autres="50.00"), f], "C2")
    assert r.outcome is Outcome.ecart_certain


def test_c2_ligne_sans_mrn_d_un_releve_multi_envois_a_verifier():
    """Ligne sans MRN d'une facture qui cite aussi l'envoi d'un autre dossier : la rattacher à la seule déclaration
    du dossier est une hypothèse."""
    f = ft(ligne(N.debours_autres_taxes, "60.00"), mrns=(MRN_A, MRN_B), total_debours="60.00")
    db = dec("doc_b", MRN_B)
    autre = AutreDossier(dossier=dossier_pour([db, f], id="dos_b"), documents={"doc_b": db, f.id: f})
    r = un_constat([dec("doc_a", MRN_A, droits="0.00", autres="50.00"), f], "C2", autres=[autre])
    assert r.outcome is Outcome.a_verifier and RaisonCode.attribution_non_univoque in r.constat.raisons


# --- D-2703 : assiette du FAF ------------------------------------------------------------------------------------


def test_d4_ligne_de_debours_perdue_assiette_non_confirmee():
    """Télécopie FICTIVE : la ligne de droits (1 000,00) n'est pas lue ; le total des débours imprimé (3 000,00)
    ne reprend pas les lignes lues. 2 % × 3 000 = 60,00 est le FAF facturé."""
    f = ft(ligne(N.debours_tva, "2000.00", mrn=MRN_A), ligne(N.frais_avance_fonds, "60.00", mrn=MRN_A),
           total_debours="3000.00")
    r = un_constat([dec(droits="1000.00", tva="2000.00"), f], "D4")
    assert r.outcome is Outcome.a_verifier
    assert RaisonCode.valeur_absente in r.constat.raisons and RaisonCode.assiette_alternative in r.constat.raisons
    assert r.details["assiette_non_confirmee"] == "total_des_debours_non_retrouve"


def test_d4_sans_total_imprime_pas_certain():
    f = ft(ligne(N.debours_droits, "1000.00", mrn=MRN_A), ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A))
    r = un_constat([dec(droits="1000.00"), f], "D4")
    assert r.outcome is Outcome.a_verifier and RaisonCode.valeur_absente in r.constat.raisons


def test_d4_assiette_complete_reste_certain():
    f = ft(ligne(N.debours_droits, "1000.00", mrn=MRN_A), ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A),
           total_debours="1000.00")
    r = un_constat([dec(droits="1000.00"), f], "D4")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("25.00")


def test_d4_au_maximum_completude_non_exigee():
    g = _grille(maximum=D("20.00"))
    f = ft(ligne(N.debours_droits, "1000.00", mrn=MRN_A), ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A))
    r = un_constat([dec(droits="1000.00"), f], "D4", grille=g)
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("25.00")


def test_d4_releve_mrn_de_ligne_sans_declaration_a_verifier():
    """Relevé FICTIF de deux envois ; le MRN de la ligne FAF ne correspond à aucune déclaration lue : les débours
    retenus (même MRN lu) ne sont pas établis."""
    autre_mrn = "26FRZZZZZZZZZZZZZ9"
    f = ft(ligne(N.debours_droits, "1000.00", mrn=autre_mrn), ligne(N.debours_droits, "500.00", mrn=MRN_B),
           ligne(N.frais_avance_fonds, "45.00", mrn=autre_mrn), mrns=(autre_mrn, MRN_B), total_debours="1500.00")
    r = un_constat([dec("doc_a", MRN_A), dec("doc_b", MRN_B, droits="500.00"), f], "D4")
    assert r.outcome is Outcome.a_verifier and RaisonCode.attribution_non_univoque in r.constat.raisons


# --- D-2704 : C6 et ligne « droits et taxes » combinée -------------------------------------------------------------


def test_c6_ligne_combinee_faf_au_maximum_conforme():
    """Ligne combinée 10 018,75 (droits + TVA) contre 10 000,00 liquidés : excédent 18,75 ; FAF à son maximum
    (200,00) avant comme après correction : aucun effet sur le FAF."""
    g = _grille(maximum=D("200.00"))
    g.postes[1].base_pourcentage = BasePourcentage.debours_hors_tva
    f = ft(ligne(N.debours_combines, "10018.75", mrn=MRN_A), ligne(N.frais_avance_fonds, "200.00", mrn=MRN_A),
           total_debours="10018.75")
    rs = resultats([dec(droits="2000.00", tva="8000.00"), f], "C6", grille=g)
    assert [r.outcome for r in rs] == [Outcome.conforme]
    assert rs[0].details["excedent_debours"] == "18.75"


# --- D-2705 : D2 une fois par prestation -------------------------------------------------------------------------


def test_d2_prestation_imprimee_deux_fois_relevee_une_fois():
    f = ft(ligne(N.autre_prestation, "25.00", libelle="Kontrola dokumentów FICTIF"),
           ligne(N.autre_prestation, "25.00", libelle="Kontrola dokumentów FICTIF"))
    rs = resultats([dec(), f], "D2")
    cs = [r for r in rs if r.constat is not None]
    assert len(cs) == 1 and cs[0].constat.montant_en_jeu == D("25.00")
    copie = [r for r in rs if r.outcome is Outcome.non_applicable]
    assert len(copie) == 1 and copie[0].details["couvert_par"] == "D5"


# --- D-2706 : D5 et MRN de ligne non établis ----------------------------------------------------------------------


def test_d5_meme_mrn_lu_sans_certitude_sur_facture_multi_envois():
    f = ft(ligne(N.frais_dedouanement, "55.00", libelle="Customs clearance", mrn=MRN_A, mrn_conf=0.75),
           ligne(N.frais_dedouanement, "55.00", libelle="Customs clearance", mrn=MRN_A, mrn_conf=0.76),
           mrns=(MRN_A, MRN_B))
    r = un_constat([dec("doc_a", MRN_A), dec("doc_b", MRN_B), f], "D5")
    assert r.outcome is Outcome.a_verifier and RaisonCode.doublon_non_etabli in r.constat.raisons
    assert "reference_d_envoi_non_etablie" in r.details["doublon_non_etabli"]
    assert "une_ligne_par_envoi" in r.details["doublon_non_etabli"]


def test_d5_meme_mrn_lu_surement_reste_certain():
    f = ft(ligne(N.transport, "90.00", libelle="Consegna FICTIVA", mrn=MRN_A),
           ligne(N.transport, "90.00", libelle="Consegna FICTIVA", mrn=MRN_A), mrns=(MRN_A, MRN_B))
    r = un_constat([dec("doc_a", MRN_A), dec("doc_b", MRN_B), f], "D5")
    assert r.outcome is Outcome.ecart_certain


# --- D-2707 : C8, facture d'un autre envoi ------------------------------------------------------------------------


def test_c8_facture_d_un_autre_envoi_a_verifier():
    f = ft(ligne(N.debours_droits, "10.00", mrn=MRN_B), mrns=(MRN_B,), client_tva=TVA_CLIENT_2,
           transports=("999-11112222",))
    r = un_constat([dec(importateur=TVA_CLIENT), f], "C8")
    assert r.outcome is Outcome.a_verifier and RaisonCode.entite_facturee_attestee in r.constat.raisons
    assert "facture_non_rattachee_a_l_envoi" in r.details["entite_facturee_attestee"]


def test_c8_facture_de_l_envoi_reste_certaine():
    f = ft(ligne(N.debours_droits, "10.00", mrn=MRN_A), mrns=(MRN_A,), client_tva=TVA_CLIENT_2)
    r = un_constat([dec(importateur=TVA_CLIENT), f], "C8")
    assert r.outcome is Outcome.ecart_certain


# --- D-2708 : C6, FAF par envoi sur des débours non ventilés -------------------------------------------------------


def test_c6_faf_par_envoi_additionnes_sur_unite_non_ventilee():
    """Deux envois, débours « droits et taxes » sans MRN (unité commune) et un FAF par envoi : l'excédent de 50,00
    sur la somme donne 1,00 de FAF (2 %), évalué une fois sur la somme des deux FAF."""
    g = _grille()
    f = ft(ligne(N.debours_droits, "1050.00"), ligne(N.frais_avance_fonds, "21.00"),
           ligne(N.debours_droits, "1000.00"), ligne(N.frais_avance_fonds, "20.00"),
           mrns=(MRN_A, MRN_B), total_debours="2050.00")
    rs = resultats([dec("doc_a", MRN_A), dec("doc_b", MRN_B), f], "C6", grille=g)
    cs = [r for r in rs if r.constat is not None]
    assert len(cs) == 1 and cs[0].constat.montant_en_jeu == D("1.00")
    assert RaisonCode.attribution_non_univoque in cs[0].constat.raisons
    assert any(r.outcome is Outcome.non_applicable and r.details.get("motif") == "faf_additionnes_par_unite"
               for r in rs)


# --- D-2710 : C8, importateur déclaré illisible ---------------------------------------------------------------------


def test_c8_importateur_declare_illisible_reste_a_verifier():
    # La déclaration porte un numéro d'importateur illisible ; seul l'acheteur de la facture commerciale est lu.
    d = dec(importateur=TVA_CLIENT)
    d.dec.importateur = Partie(tva=vs("declaration.importateur.tva", "FR07000711922", document_id="doc_dec",
                                      confiance=0.02, methode=Methode.ocr))
    fc = facture_commerciale(id="doc_fc", acheteur=Partie(tva=vs("facture_commerciale.acheteur.tva", TVA_CLIENT,
                                                                  document_id="doc_fc")))
    f = ft(ligne(N.debours_droits, "10.00", mrn=MRN_A), mrns=(MRN_A,), client_tva=TVA_CLIENT_2)
    r = un_constat([d, fc, f], "C8")
    assert r.outcome is Outcome.a_verifier and RaisonCode.entite_facturee_attestee in r.constat.raisons
    assert "importateur_declare_non_lu" in r.details["entite_facturee_attestee"]
