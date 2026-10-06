"""Écarts au tarif (D3, D4) certains seulement si la ligne de grille, la quantité, l'unité, l'assiette et les avoirs du
dossier sont établis sans ambiguïté (D-4212 à D-4214). Données entièrement fictives construites ici."""

from datetime import date
from decimal import Decimal as D

from controldone.controls.context import ControlContext
from controldone.controls.framework import run_controls
from controldone.guardrails import check_text
from controldone.model import (
    BasePourcentage,
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
    SigneImprime,
    StatutGrille,
    Transitaire,
    TypeDocument,
)
from controldone.model.enums import RAISON_LIBELLES, Methode
from controldone.testing import declaration, document, dossier_pour, facture_transitaire, taxation, vs

N = NatureLigne
TVA_TRANSITAIRE = "FR11000555550"  # transitaire FICTIF
TVA_CLIENT = "FR68000458570"  # entité FICTIVE du client
MRN_A = "26FRAAAAAAAAAAAAA1"
MRN_B = "26FRBBBBBBBBBBBBB2"
MRN_X = "26FRXQXQXQXQXQXQX7"  # MRN FICTIF d'un envoi dont la déclaration n'est pas au dossier
TRANSITAIRES = [Transitaire(id="tra_1", nom="Transit FICTIF", tva=TVA_TRANSITAIRE)]


def _postes(dedou="60.00"):
    return [
        PosteGrille(code_poste="DEDOU", nature=N.frais_dedouanement, mode=ModePoste.forfait, prix=D(dedou)),
        PosteGrille(
            code_poste="MANUT", nature=N.manutention, mode=ModePoste.unitaire, prix=D("0.15"), unite_base="kg"
        ),
        PosteGrille(
            code_poste="FAF",
            nature=N.frais_avance_fonds,
            mode=ModePoste.pourcentage,
            pourcentage=D("2"),
            minimum=D("15.00"),
            base_pourcentage=BasePourcentage.debours_total,
        ),
    ]


def _grille(dedou="60.00", du=None, au=None, ref="DEV-FICTIF-42"):
    return GrilleTarifaire(
        transitaire_id="tra_1",
        reference=ref,
        statut=StatutGrille.validee,
        prestations_hors_grille=PrestationsHorsGrille.interdites,
        valide_du=du,
        valide_au=au,
        postes=_postes(dedou),
    )


GRILLE = _grille()


def _v(fid, nom, val, **kw):
    return None if val is None else vs(f"facture_transitaire.lignes[].{nom}", val, document_id=fid, **kw)


def ligne(nature, montant, *, fid="doc_ft1", libelle=None, negatif=False, **kw):
    m = _v(fid, "montant_ht", montant)
    if negatif and m is not None:
        m = m.model_copy(update={"signe_imprime": SigneImprime.negatif})
    return LigneFactureTransitaire(
        libelle=_v(fid, "libelle", libelle or nature.value.replace("_", " ")),
        nature=nature,
        montant_ht=m,
        **{k: _v(fid, k, x) for k, x in kw.items()},
    )


def ft(
    *lignes, fid="doc_ft1", mrns=(MRN_A,), numero="FA-FICTIF-42", date="2026-09-15", emetteur=True, **totaux
):
    champs = {k: vs(f"facture_transitaire.{k}", x, document_id=fid) for k, x in totaux.items()}
    em = (
        Partie(tva=vs("facture_transitaire.emetteur.tva", TVA_TRANSITAIRE, document_id=fid))
        if emetteur
        else Partie()
    )
    return facture_transitaire(
        id=fid,
        numero=vs("facture_transitaire.numero", numero, document_id=fid),
        date=vs("facture_transitaire.date", date, document_id=fid),
        emetteur=em,
        client_facture=Partie(tva=vs("facture_transitaire.client_facture.tva", TVA_CLIENT, document_id=fid)),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", m, document_id=fid) for m in mrns],
        lignes=list(lignes),
        **champs,
    )


def dec(did="doc_dec", mrn=MRN_A, *, droits="1000.00", date=None):
    d = declaration(
        id=did,
        mrn=mrn,
        taxations=[taxation(did, categorie=CategorieTaxe.droit, type_taxe="A00", montant=droits)],
    )
    d.dec.importateur = Partie(tva=vs("declaration.importateur.tva", TVA_CLIENT, document_id=did))
    if date is not None:
        d.dec.date_acceptation = vs("declaration.date_acceptation", date, document_id=did)
    return d


def avoir(*lignes_av, aid="doc_av1", origine=None, mrns=()):
    return document(
        TypeDocument.avoir,
        ChampsAvoir(
            numero=vs("avoir.numero", "AV-FICTIF-42", document_id=aid),
            emetteur=Partie(tva=vs("avoir.emetteur.tva", TVA_TRANSITAIRE, document_id=aid)),
            refs_facture_origine=[vs("avoir.refs_facture_origine[]", origine, document_id=aid)]
            if origine
            else [],
            refs_mrn=[vs("avoir.refs_mrn[]", m, document_id=aid) for m in mrns],
            lignes=list(lignes_av),
        ),
        id=aid,
    )


def ligne_av(nature, montant, aid="doc_av1"):
    return LigneFactureTransitaire(
        libelle=vs("avoir.lignes[].libelle", nature.value.replace("_", " "), document_id=aid),
        nature=nature,
        montant_ht=vs("avoir.lignes[].montant_ht", montant, document_id=aid),
    )


def resultats(docs, cid, *, grilles=(GRILLE,)):
    dossier = dossier_pour(docs, id="dos_a").model_copy(update={"transitaire_id": "tra_1"})
    ctx = ControlContext.construire(
        dossier,
        docs,
        ProfilTolerances(id="tol_test"),
        execution_id="exe_test",
        grilles=list(grilles),
        transitaires=TRANSITAIRES,
        exiger_lecture_corroboree=False,
    )
    return [r for r in run_controls(ctx, controles=[cid]) if r.controle_id == cid]


def un(docs, cid="D3", **kw):
    xs = [r for r in resultats(docs, cid, **kw) if r.constat is not None]
    assert len(xs) == 1, xs
    return xs[0]


def dedou(montant, **kw):
    return ft(ligne(N.frais_dedouanement, montant), **kw)


def test_libelles_des_raisons_nouvelles():
    for code in (RaisonCode.avoir_non_impute, RaisonCode.tarif_non_etabli):
        texte = RAISON_LIBELLES[code]
        assert texte.startswith("à vérifier") and check_text(texte) == []


def test_d3_forfait_etabli_reste_certain():
    r = un([dec(), dedou("75.00")])
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("15.00")


# --- D-4212 : avoirs et crédits non imputés -----------------------------------------------------------------------


def test_d3_avoir_rattache_par_la_facture_deduit():
    r = [
        x
        for x in resultats(
            [dec(), dedou("75.00"), avoir(ligne_av(N.frais_dedouanement, "15.00"), origine="FA-FICTIF-42")],
            "D3",
        )
    ]
    assert [x.outcome for x in r] == [Outcome.conforme]


def test_d3_avoir_non_rattache_rend_l_ecart_a_verifier():
    """Avoir FICTIF du même transitaire, sans référence lisible de facture ni de MRN : l'imputation ne le rattache
    pas, mais il peut solder l'écart (piège « écart soldé par un avoir rattaché par le seul MRN » mal lu)."""
    r = un([dec(), dedou("75.00"), avoir(ligne_av(N.frais_dedouanement, "15.00"))])
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_impute in r.constat.raisons
    assert r.details["avoirs_non_imputes"] == ["doc_av1"]


def test_d3_avoir_d_une_autre_nature_rend_l_ecart_a_verifier():
    r = un([dec(), dedou("75.00"), avoir(ligne_av(N.autre_prestation, "15.00"), origine="FA-FICTIF-42")])
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_impute in r.constat.raisons


def test_d3_avoir_de_debours_seul_laisse_l_ecart_certain():
    r = un([dec(), dedou("75.00"), avoir(ligne_av(N.debours_droits, "15.00"), origine="FA-FICTIF-42")])
    assert r.outcome is Outcome.ecart_certain


def test_d3_ligne_negative_sur_la_facture():
    f = ft(
        ligne(N.frais_dedouanement, "75.00"),
        ligne(N.autre_prestation, "15.00", libelle="Remise", negatif=True),
    )
    r = un([dec(), f])
    assert r.outcome is Outcome.a_verifier and RaisonCode.avoir_non_impute in r.constat.raisons


def test_d3_ligne_de_meme_nature_egale_a_l_ecart_sur_une_autre_facture():
    """Avoir lu comme une facture (montant sans signe) : ligne de dédouanement de 15,00 = l'écart."""
    autre = ft(ligne(N.frais_dedouanement, "15.00", fid="doc_ft2"), fid="doc_ft2", numero="AV-LU-FICTIF")
    r = [x for x in resultats([dec(), dedou("75.00"), autre], "D3") if x.constat is not None]
    assert len(r) == 1 and r[0].outcome is Outcome.a_verifier
    assert RaisonCode.avoir_non_impute in r[0].constat.raisons


# --- D-4213 : quantité, unité, grille, version ---------------------------------------------------------------------


def test_d3_forfait_facture_deux_fois_sur_une_ligne():
    r = un([dec(), dedou("120.00")])
    assert r.outcome is Outcome.a_verifier and r.details["tarif_non_etabli"] == ["multiple_du_forfait"]
    f = ft(ligne(N.frais_dedouanement, "130.00", quantite="2"))
    r = un([dec(), f])
    assert r.outcome is Outcome.a_verifier and r.details["tarif_non_etabli"] == ["quantite_sur_forfait"]


def test_d3_unitaire_au_kilo_quantite_non_imprimee():
    """Manutention FICTIVE au kilo : 308,25 sans quantité imprimée (quantité déduite à 1) : jamais certain."""
    f = ft(ligne(N.manutention, "308.25", prix_unitaire="0.15"))
    f.ft.lignes[0].quantite = vs(
        "facture_transitaire.lignes[].quantite",
        "1",
        document_id="doc_ft1",
        methode=Methode.derive,
        regle_derivation="quantite_par_defaut",
    )
    r = un([dec(), f])
    assert r.outcome is Outcome.a_verifier
    assert "quantite_non_lue" in r.details["tarif_non_etabli"]


def test_d3_unitaire_au_kilo_quantite_incoherente():
    """Quantité « 2.055 » lue avec le point des milliers : 2,055 × 0,15 ≠ 308,25 : l'unité n'est pas établie."""
    f = ft(ligne(N.manutention, "308.25", quantite="2.055", prix_unitaire="0.15"))
    r = un([dec(), f])
    assert r.outcome is Outcome.a_verifier
    assert r.details["tarif_non_etabli"] == ["quantite_prix_montant_incoherents"]


def test_d3_unitaire_au_kilo_etabli_reste_certain():
    f = ft(ligne(N.manutention, "411.00", quantite="2055", prix_unitaire="0.20"))
    r = un([dec(), f])
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("102.75")


def test_d3_masse_brute_arrondie_conforme():
    f = ft(ligne(N.manutention, "308.25", quantite="2055", prix_unitaire="0.15"))
    assert [r.outcome for r in resultats([dec(), f], "D3")] == [Outcome.conforme]


def test_d3_deux_grilles_selon_la_date_de_prestation():
    """Grille FICTIVE renouvelée au 1er septembre : la facture (15/09) tombe dans la nouvelle, la déclaration (28/08)
    dans l'ancienne, au forfait différent : la grille applicable n'est pas établie."""
    ancienne = _grille("75.00", du=date(2026, 1, 1), au=date(2026, 8, 31), ref="A")
    nouvelle = _grille("60.00", du=date(2026, 9, 1), au=date(2026, 12, 31), ref="B")
    r = un([dec(date="2026-08-28"), dedou("75.00")], grilles=(ancienne, nouvelle))
    assert (
        r.outcome is Outcome.a_verifier and "plusieurs_grilles_applicables" in r.details["tarif_non_etabli"]
    )
    r = un([dec(date="2026-09-10"), dedou("75.00")], grilles=(ancienne, nouvelle))
    assert r.outcome is Outcome.ecart_certain


def test_d3_emetteur_non_identifie():
    r = un([dec(), dedou("75.00", emetteur=False)])
    assert r.outcome is Outcome.a_verifier and RaisonCode.grille_non_attestee in r.constat.raisons


def test_d3_autre_version_de_la_facture():
    v2 = ft(ligne(N.frais_dedouanement, "60.00", fid="doc_ft2"), fid="doc_ft2")
    r = un([dec(), dedou("75.00"), v2])
    assert r.outcome is Outcome.a_verifier and "autre_version_de_la_facture" in r.details["tarif_non_etabli"]


def test_d3_montants_lus_tva_comprise():
    """Facture FICTIVE qui n'imprime que des montants TTC : Σ lignes lues = total TTC ≠ total HT."""
    f = ft(
        ligne(N.frais_dedouanement, "72.00", taux_tva="20"),
        ligne(N.debours_droits, "100.00"),
        total_ht="160.00",
        total_tva="12.00",
        total_ttc="172.00",
    )
    r = un([dec(droits="100.00"), f])
    assert r.outcome is Outcome.a_verifier and RaisonCode.montant_tva_comprise in r.constat.raisons


def test_d3_ligne_d_un_autre_envoi():
    f = ft(ligne(N.frais_dedouanement, "75.00", mrn=MRN_X), mrns=(MRN_A, MRN_X))
    r = un([dec(), f])
    assert r.outcome is Outcome.a_verifier and RaisonCode.attribution_non_univoque in r.constat.raisons


def test_d3_ligne_repetee_comparee_une_fois():
    f = ft(ligne(N.frais_dedouanement, "75.00"), ligne(N.frais_dedouanement, "75.00"))
    rs = resultats([dec(), f], "D3")
    assert [r.outcome for r in rs] == [Outcome.ecart_certain, Outcome.non_applicable]
    assert rs[1].details["couvert_par"] == "D5"


# --- D-4214 : FAF ---------------------------------------------------------------------------------------------------


def _faf(montant, *autres, mrns=(MRN_A,), **kw):
    return ft(
        ligne(N.debours_droits, "1000.00"),
        ligne(N.frais_avance_fonds, montant, **kw),
        *autres,
        mrns=mrns,
        total_debours="1000.00",
    )


def test_d4_faf_etabli_reste_certain():
    r = un([dec(), _faf("40.00")], "D4")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("20.00")


def test_d4_faf_quantite_deux():
    r = un([dec(), _faf("40.00", quantite="2")], "D4")
    assert r.outcome is Outcome.a_verifier and "faf_par_envoi_quantite" in r.details["assiette_non_etablie"]


def test_d4_envois_hors_assiette():
    r = un([dec(), _faf("40.00", mrns=(MRN_A, MRN_B))], "D4")
    assert r.outcome is Outcome.a_verifier and "envois_hors_assiette" in r.details["assiette_non_etablie"]


def test_d4_faf_sur_les_debours_d_une_facture_complementaire():
    """FAF FICTIF de 2 % sur 1 000,00 + 500,00 de droits refacturés par une facture complémentaire du même
    transitaire, sans déclaration au dossier : l'autre assiette explique le montant."""
    compl = ft(
        ligne(N.debours_droits, "500.00", fid="doc_ft2"),
        fid="doc_ft2",
        numero="FA-FICTIF-43",
        total_debours="500.00",
    )
    r = un([_faf("30.00"), compl], "D4")
    assert r.outcome is Outcome.a_verifier and RaisonCode.assiette_alternative in r.constat.raisons
