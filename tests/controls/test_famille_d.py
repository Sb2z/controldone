"""Famille D — facture du transitaire contre grille tarifaire (SPEC §13). Données fictives."""

from decimal import Decimal as D

from controldone.controls.famille_d import ACTION_D8, d1_arithmetique, rapprocher_poste
from controldone.controls.framework import run_controls
from controldone.guardrails import check_text
from controldone.model import (
    ArticleDeclaration,
    BasePourcentage,
    CategorieTaxe,
    GrilleTarifaire,
    LigneFactureTransitaire,
    Methode,
    ModePoste,
    NatureLigne,
    NatureMontant,
    Niveau,
    Outcome,
    Partie,
    PosteGrille,
    PrestationsHorsGrille,
    RaisonCode,
    StatutGrille,
    Transitaire,
)
from controldone.testing import contexte, declaration, facture_transitaire, taxation, vs

N = NatureLigne
TVA_TRANSITAIRE = "FR11000555550"
TRANSITAIRES = [Transitaire(id="tra_1", nom="Transit FICTIF", tva=TVA_TRANSITAIRE)]
D_IDS = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]


def ligne(nature, montant, *, libelle=None, fid="doc_ft1", confiance=0.99, **kw):
    def v(nom, val):
        if val is None:
            return None
        return vs(f"facture_transitaire.lignes[].{nom}", val, document_id=fid, confiance=confiance)

    return LigneFactureTransitaire(
        libelle=v("libelle", libelle or nature.value.replace("_", " ")),
        nature=nature,
        montant_ht=v("montant_ht", montant),
        **{k: v(k, x) for k, x in kw.items()},
    )


def ft(*lignes, fid="doc_ft1", date="2026-09-15", **totaux):
    return facture_transitaire(
        id=fid,
        numero=vs("facture_transitaire.numero", "FT-FICTIF-001", document_id=fid),
        date=vs("facture_transitaire.date", date, document_id=fid),
        emetteur=Partie(tva=vs("facture_transitaire.emetteur.tva", TVA_TRANSITAIRE, document_id=fid)),
        lignes=list(lignes),
        **{k: vs(f"facture_transitaire.{k}", x, document_id=fid) for k, x in totaux.items()},
    )


def poste(code, nature, mode=ModePoste.forfait, prix=None, **kw):
    return PosteGrille(code_poste=code, nature=nature, mode=mode, prix=D(prix) if prix else None, **kw)


def grille(*postes, hors=PrestationsHorsGrille.interdites, statut=StatutGrille.validee):
    return GrilleTarifaire(
        transitaire_id="tra_1",
        reference="DEV-FICTIF-2026",
        statut=statut,
        postes=list(postes),
        prestations_hors_grille=hors,
    )


POSTES = (
    poste("DEDOU", N.frais_dedouanement, prix="50.00", libelles_reconnus=["dédouanement import"], inclus=5),
    poste("LIGNE", N.frais_ligne_supplementaire, ModePoste.unitaire, prix="5.00", unite_base="article"),
    poste(
        "FAF",
        N.frais_avance_fonds,
        ModePoste.pourcentage,
        pourcentage=D("2.5"),
        minimum=D("15.00"),
        base_pourcentage=BasePourcentage.debours_total,
    ),
    poste("MAG", N.magasinage, ModePoste.par_jour, prix="12.00", franchise_jours=3),
    poste(
        "CARB",
        N.surcharge,
        ModePoste.pourcentage,
        pourcentage=D("10"),
        base_pourcentage=BasePourcentage.autre,
        libelles_reconnus=["surcharge carburant"],
    ),
    poste("TRANS", N.transport, ModePoste.forfait, prix="200.00"),
    poste("DOSSIER", N.autre_prestation, prix="20.00", libelles_reconnus=["frais de dossier"]),
)


def run(docs, *, g=None, controles=D_IDS, **kw):
    ctx = contexte(docs, grilles=[g or grille(*POSTES)], transitaires=TRANSITAIRES, **kw)
    return run_controls(ctx, controles=controles)


def par_id(rs, cid):
    return [r for r in rs if r.controle_id == cid]


def un(rs, cid):
    xs = par_id(rs, cid)
    assert len(xs) == 1, xs
    return xs[0]


def lib(c):
    return c.libelle.replace("\xa0", " ")


def textes_propres(rs):
    for r in rs:
        if r.constat is not None:
            texte = r.constat.libelle + " " + r.constat.prochaine_action
            assert check_text(texte) == [], texte
            assert "droit du" not in texte.lower() and r.constat.motif_blocage is None
            assert "erreur" not in texte.lower() and "fraud" not in texte.lower()


# --- grille absente ou non validée -------------------------------------------------------------------


def test_sans_grille_validee_non_applicable():
    f = ft(ligne(N.frais_dedouanement, "80.00"))
    for g in (None, grille(*POSTES, statut=StatutGrille.brouillon)):
        ctx = contexte([f], grilles=[g] if g else [], transitaires=TRANSITAIRES)
        rs = run_controls(ctx, controles=D_IDS)
        for cid in D_IDS[1:]:
            r = un(rs, cid)
            assert r.outcome is Outcome.non_applicable and r.raison_code is RaisonCode.aucune_grille_validee
        assert un(rs, "D1").outcome is not Outcome.non_applicable


def test_grille_hors_periode_ou_autre_transitaire():
    f = ft(ligne(N.frais_dedouanement, "80.00"), date="2025-01-10")
    g = grille(*POSTES)
    g.valide_du = __import__("datetime").date(2026, 1, 1)
    assert un(run([f], g=g), "D3").raison_code is RaisonCode.aucune_grille_validee
    f2 = ft(ligne(N.frais_dedouanement, "80.00"))
    f2.ft.emetteur.tva = vs("facture_transitaire.emetteur.tva", "FR99000777770", document_id="doc_ft1")
    assert un(run([f2]), "D3").raison_code is RaisonCode.aucune_grille_validee


def test_sans_facture_transitaire():
    rs = run([declaration(id="doc_dec1")])
    for cid in D_IDS:
        assert un(rs, cid).raison_code is RaisonCode.facture_transitaire_absente


# --- D1 -----------------------------------------------------------------------------------------------


def test_d1_conforme_et_arrondi():
    f = ft(
        ligne(
            N.frais_dedouanement,
            "50.00",
            quantite="1",
            prix_unitaire="50.00",
            taux_tva="20",
            montant_tva="10.00",
        ),
        ligne(N.transport, "33.33", quantite="3", prix_unitaire="11.11"),
        ligne(N.debours_droits, "100.00"),
        total_debours="100.00",
        total_ht="183.34",
        total_tva="10.00",
        total_ttc="193.34",
    )
    rs = d1_arithmetique(contexte([f]))
    assert {r.sous_controle for r in rs} == {"ligne", "tva_ligne", "total_debours", "total_ht", "total_ttc"}
    assert all(r.outcome is Outcome.conforme for r in rs)  # 0,01 d'arrondi sous T_SOMME(3)


def test_d1_total_ht_superieur_a_la_somme():
    # D-4202 : débours prouvés complets (total des débours imprimé) et prestations (TVA de chaque ligne).
    f = ft(
        ligne(N.frais_dedouanement, "50.00", taux_tva="20", montant_tva="10.00"),
        ligne(N.debours_droits, "100.00"),
        total_debours="100.00",
        total_ht="155.00",
        total_tva="10.00",
        total_ttc="165.00",
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ht")
    c = r.constat
    assert r.outcome is Outcome.ecart_certain and c.montant_en_jeu == D("5.00")
    assert c.nature_montant is NatureMontant.recouvrable and "155,00 EUR" in lib(c)
    textes_propres([r])


def test_d1_total_ht_lignes_non_prouvees_completes():
    # D-4202 : rien ne prouve que toutes les lignes sont lues : une ligne non lue de 5,00 expliquerait l'écart.
    f = ft(ligne(N.frais_dedouanement, "50.00"), ligne(N.debours_droits, "100.00"), total_ht="155.00")
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ht")
    assert r.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in r.constat.raisons
    assert r.details["structure_non_validee"] == ["lignes_non_prouvees_completes"]


def test_d1_total_ht_prouve_par_le_ttc():
    # TTC imprimé = somme des lignes + TVA : les lignes sont complètes, le total HT est la valeur isolée.
    f = ft(
        ligne(N.frais_dedouanement, "50.00"),
        ligne(N.debours_droits, "100.00"),
        total_ht="155.00",
        total_tva="10.00",
        total_ttc="160.00",
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ht")
    assert r.outcome is Outcome.ecart_certain


def test_d1_total_prouve_seulement_par_un_total_imprime():
    # Un total TTC déduit ne prouve rien (D-4202).
    f = ft(
        ligne(N.frais_dedouanement, "50.00"),
        ligne(N.debours_droits, "100.00"),
        total_ht="155.00",
        total_tva="10.00",
        total_ttc="160.00",
    )
    f.ft.total_ttc = f.ft.total_ttc.model_copy(
        update={"methode": Methode.derive, "regle_derivation": "ht + tva"}
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ht")
    assert r.outcome is Outcome.a_verifier


def test_d1_total_debours_nature_de_ligne_ambigue():
    # D-4203 : l'écart du total des débours est le montant d'une ligne lue comme prestation (libellé mal lu).
    f = ft(
        ligne(N.debours_droits, "100.00"),
        ligne(N.autre_prestation, "80.00", libelle="TVA al'imp FICTIF"),
        ligne(N.transport, "50.00", taux_tva="20", montant_tva="10.00"),
        total_debours="180.00",
        total_ht="230.00",
        total_tva="10.00",
        total_ttc="240.00",
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_debours")
    assert r.outcome is Outcome.non_verifiable and r.details["explications"] == ["nature_de_ligne"]


def test_d1_ttc_avec_total_des_debours_hors_ht():
    # D-4204 : TTC = HT des prestations + TVA + total des débours imprimé, lignes de débours non toutes lues.
    f = ft(
        ligne(N.transport, "50.00", taux_tva="20", montant_tva="10.00"),
        total_debours="300.00",
        total_ht="50.00",
        total_tva="10.00",
        total_ttc="360.00",
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ttc")
    assert r.outcome is Outcome.conforme


def test_d1_tva_ligne_colonne_ttc():
    # D-4203 : TVA lue = montant TVA comprise de la ligne (colonne « TTC » lue comme TVA).
    f = ft(ligne(N.frais_dedouanement, "59.00", taux_tva="20", montant_tva="70.80"))
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "tva_ligne")
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.montant_tva_comprise


def test_d1_ligne_colonne_ttc_ou_quantite_du_libelle():
    f = ft(
        ligne(N.transport, "36.00", quantite="1", prix_unitaire="30.00", taux_tva="20"),
        ligne(
            N.manutention, "15.00", quantite="2", prix_unitaire="3.00", libelle="Manutention 5 colis FICTIF"
        ),
    )
    rs = [r for r in d1_arithmetique(contexte([f])) if r.sous_controle == "ligne"]
    assert [r.outcome for r in rs] == [Outcome.non_verifiable, Outcome.non_verifiable]
    assert rs[0].details["explications"] == ["colonne_ttc"] and rs[1].details["explications"] == [
        "quantite_libelle"
    ]


def test_d1_ligne_de_debours_non_jugee():
    # D-4203 : le produit d'une ligne de débours (forfait par article) est celui de la déclaration (G1).
    f = ft(ligne(N.debours_forfait_petits_envois, "15.00", quantite="2", prix_unitaire="3.00"))
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "ligne")
    assert r.outcome is Outcome.non_applicable and r.details["motif"] == "ligne_de_debours_reproduite"


def test_d1_total_ht_presentation_sans_debours():
    f = ft(
        ligne(N.frais_dedouanement, "50.00"),
        ligne(N.debours_droits, "100.00"),
        total_ht="50.00",
        total_tva="10.00",
        total_ttc="160.00",
    )
    rs = d1_arithmetique(contexte([f]))
    assert all(r.outcome is Outcome.conforme for r in rs)


def test_d1_ligne_et_total_inferieur_sans_montant():
    f = ft(ligne(N.transport, "40.00", quantite="3", prix_unitaire="11.11"), total_ht="30.00")
    rs = {r.sous_controle: r for r in d1_arithmetique(contexte([f]))}
    assert rs["ligne"].constat.montant_en_jeu is None and rs["ligne"].outcome is Outcome.ecart_certain
    c = rs["total_ht"].constat
    assert c.montant_en_jeu is None and c.niveau is Niveau.a_verifier
    assert RaisonCode.ecart_en_faveur_client in c.raisons


def test_d1_net_a_payer_et_sous_seuil():
    f = ft(
        ligne(N.transport, "100.00"),
        total_ht="100.00",
        total_tva="20.00",
        total_ttc="120.00",
        acomptes="50.00",
        net_a_payer="70.50",
    )
    rs = {r.sous_controle: r for r in d1_arithmetique(contexte([f]))}
    c = rs["net_a_payer"].constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.ecart_sous_seuil in c.raisons
    assert c.montant_en_jeu == D("0.50")


def test_d1_aucun_calcul_non_verifiable():
    f = ft(ligne(N.transport, "100.00"))
    r = d1_arithmetique(contexte([f]))[0]
    assert r.outcome is Outcome.non_verifiable


# --- rapprochement ligne ↔ poste -------------------------------------------------------------------------


def test_rapprochement_par_nature_puis_libelle():
    g = grille(*POSTES)
    p, amb = rapprocher_poste(g, ligne(N.autre_prestation, "20.00", libelle="Frais de dossier FICTIF"))
    assert p.code_poste == "DOSSIER" and not amb
    p, amb = rapprocher_poste(g, ligne(N.manutention, "20.00", libelle="Manutention"))
    assert p is None and not amb
    g2 = grille(
        poste("D1", N.frais_dedouanement, prix="50.00", libelles_reconnus=["import"]),
        poste("D2", N.frais_dedouanement, prix="70.00", libelles_reconnus=["export"]),
    )
    assert rapprocher_poste(g2, ligne(N.frais_dedouanement, "50.00", libelle="Dédouanement"))[1] is True


def test_ligne_ambigue_a_verifier():
    g = grille(
        poste("D1", N.frais_dedouanement, prix="50.00", libelles_reconnus=["import"]),
        poste("D2", N.frais_dedouanement, prix="70.00", libelles_reconnus=["export"]),
    )
    r = un(run([ft(ligne(N.frais_dedouanement, "90.00", libelle="Dédouanement"))], g=g), "D3")
    assert r.outcome is Outcome.a_verifier and RaisonCode.confiance_insuffisante in r.constat.raisons
    assert r.constat.montant_en_jeu is None


# --- D2 -----------------------------------------------------------------------------------------------------


def test_d2_hors_grille_interdites_et_tolerees():
    f = ft(ligne(N.manutention, "45.00", libelle="Manutention FICTIVE", montant_tva="9.00"))
    r = un(run([f]), "D2")
    c = r.constat
    assert r.outcome is Outcome.ecart_certain and c.montant_en_jeu == D("45.00")
    assert c.montant_tva_associee == D("9.00") and c.composante.value == "prestation"
    assert "ne correspond à aucun poste" in lib(c) and "DEV-FICTIF-2026" in lib(c)
    textes_propres([r])
    r2 = un(run([f], g=grille(*POSTES, hors=PrestationsHorsGrille.tolerees)), "D2")
    assert r2.outcome is Outcome.a_verifier and r2.constat.montant_en_jeu == D("45.00")


def test_d2_libelle_peu_sur():
    f = ft(ligne(N.manutention, "45.00", confiance=0.7))
    c = un(run([f]), "D2").constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.confiance_insuffisante in c.raisons


# --- D3 -----------------------------------------------------------------------------------------------------


def test_d3_forfait():
    rs = run([ft(ligne(N.frais_dedouanement, "65.00"))])
    r = un(rs, "D3")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("15.00")
    assert r.unite == "ft:doc_ft1|ligne:0" and "forfait de 50,00 EUR" in lib(r.constat)
    textes_propres(rs)
    assert un(run([ft(ligne(N.frais_dedouanement, "45.00"))]), "D3").outcome is Outcome.conforme
    assert un(run([ft(ligne(N.frais_dedouanement, "50.01"))]), "D3").outcome is Outcome.conforme
    c = un(run([ft(ligne(N.frais_dedouanement, "50.06"))]), "D3").constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.ecart_sous_seuil in c.raisons


def test_d3_unitaire_et_quantite_absente():
    g = grille(poste("MAN", N.manutention, ModePoste.unitaire, prix="10.00", unite_base="colis"))
    r = un(run([ft(ligne(N.manutention, "36.00", quantite="3", prix_unitaire="12.00"))], g=g), "D3")
    assert r.constat.montant_en_jeu == D("6.00") and r.outcome is Outcome.ecart_certain
    # D-4213 : sans prix unitaire imprimé, l'unité de la quantité n'est pas établie.
    r1 = un(run([ft(ligne(N.manutention, "36.00", quantite="3"))], g=g), "D3")
    assert r1.outcome is Outcome.a_verifier and RaisonCode.tarif_non_etabli in r1.constat.raisons
    r2 = un(run([ft(ligne(N.manutention, "16.00"))], g=g), "D3")
    assert r2.outcome is Outcome.a_verifier and RaisonCode.valeur_absente in r2.constat.raisons


# --- D4 (et non-double-comptage avec C6) ------------------------------------------------------------------


def _dec(montant):
    return declaration(
        id="doc_dec1", taxations=[taxation("doc_dec1", categorie=CategorieTaxe.droit, montant=montant)]
    )


def test_d4_faf_contre_grille():
    f = ft(
        ligne(N.debours_droits, "1000.00"),
        ligne(N.frais_avance_fonds, "30.00", libelle="Avance de fonds"),
        total_debours="1000.00",
    )
    rs = run([_dec("1000.00"), f], controles=["C1", "C5", "C6", "D4"])
    r = un(rs, "D4")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("5.00")
    assert "2,5 %" in lib(r.constat)
    textes_propres(rs)
    f_min = ft(ligne(N.debours_droits, "100.00"), ligne(N.frais_avance_fonds, "15.00"))
    assert un(run([_dec("100.00"), f_min], controles=["D4"]), "D4").outcome is Outcome.conforme


def test_d4_assiette_corrigee_sans_double_comptage_c6():
    f = ft(ligne(N.debours_droits, "1000.00"), ligne(N.frais_avance_fonds, "25.00"))
    rs = run([_dec("600.00"), f], controles=["C1", "C5", "C6", "D4"])
    c6 = un(rs, "C6")
    assert c6.outcome is Outcome.ecart_certain and c6.constat.montant_en_jeu == D("10.00")
    d4 = un(rs, "D4")
    assert d4.outcome is Outcome.conforme and d4.details["deduit_c6"] == "10.00"


def test_d4_faf_sur_debours_sans_declaration():
    f = ft(ligne(N.debours_droits, "1000.00"), ligne(N.frais_avance_fonds, "40.00"))
    r = un(run([f], controles=["D4"]), "D4")
    assert r.constat.montant_en_jeu == D("15.00")


# --- D5 ---------------------------------------------------------------------------------------------------------


def test_d5_ligne_en_double():
    f = ft(
        ligne(N.transport, "200.00", libelle="Livraison"), ligne(N.transport, "200.00", libelle="LIVRAISON")
    )
    rs = run([f])
    r = un(rs, "D5")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("200.00")
    assert r.unite == "ft:doc_ft1|lignes:0+1"
    textes_propres(rs)
    assert un(run([ft(ligne(N.transport, "200.00"))]), "D5").outcome is Outcome.conforme


def test_d5_poste_a_quantite_multiple_a_verifier():
    g = grille(poste("MAN", N.manutention, ModePoste.unitaire, prix="10.00"))
    f = ft(ligne(N.manutention, "10.00"), ligne(N.manutention, "10.00"))
    r = un(run([f], g=g), "D5")
    assert r.outcome is Outcome.a_verifier


def test_d5_references_differentes_pas_un_doublon():
    f = ft(
        ligne(N.transport, "200.00", ref_transport="999-11112222"),
        ligne(N.transport, "200.00", ref_transport="999-33334444"),
    )
    assert un(run([f]), "D5").outcome is Outcome.conforme


# --- D6 ------------------------------------------------------------------------------------------------------------


def test_d6_magasinage_franchise():
    f = ft(
        ligne(
            N.magasinage,
            "120.00",
            libelle="Magasinage",
            date_debut="2026-09-01",
            date_fin="2026-09-10",
            quantite="10",
        )
    )
    rs = run([f])
    r = un(rs, "D6")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("36.00")
    assert r.details["jours_attendus"] == 7 and "franchise" in lib(r.constat)
    textes_propres(rs)
    ok = ft(ligne(N.magasinage, "84.00", date_debut="2026-09-01", date_fin="2026-09-10"))
    assert un(run([ok]), "D6").outcome is Outcome.conforme
    franchise = ft(ligne(N.magasinage, "24.00", date_debut="2026-09-01", date_fin="2026-09-02"))
    assert un(run([franchise]), "D6").constat.montant_en_jeu == D("24.00")


def test_d6_dates_peu_sures_ou_absentes():
    f = ft(ligne(N.magasinage, "120.00", date_debut="2026-09-01", date_fin="2026-09-10", confiance=0.8))
    assert un(run([f]), "D6").outcome is Outcome.a_verifier
    sans_dates = ft(ligne(N.magasinage, "120.00", quantite="10"))
    assert un(run([sans_dates]), "D6").outcome is Outcome.conforme  # 10 × 12 : prix seulement
    rien = ft(ligne(N.magasinage, "120.00"))
    assert un(run([rien]), "D6").outcome is Outcome.non_verifiable


# --- D7 --------------------------------------------------------------------------------------------------------------


def test_d7_surcharge_pourcentage_et_hors_grille():
    f = ft(ligne(N.transport, "200.00"), ligne(N.surcharge, "25.00", libelle="Surcharge carburant"))
    rs = run([f])
    r = un(rs, "D7")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("5.00")
    textes_propres(rs)
    g = grille(*[p for p in POSTES if p.code_poste != "CARB"])
    r2 = un(run([ft(ligne(N.surcharge, "18.00", libelle="Surcharge sûreté"))], g=g), "D7")
    assert r2.outcome is Outcome.ecart_certain and r2.constat.montant_en_jeu == D("18.00")
    assert "aucun poste" in lib(r2.constat)
    assert not par_id(run([ft(ligne(N.surcharge, "18.00"))], g=g), "D2")[1:]


def test_d7_autre_surcharge_que_celle_de_la_grille_est_sans_poste():
    # D-2203 : la grille ne prévoit qu'une surcharge carburant ; une surcharge haute saison n'est pas « la »
    # surcharge de la grille : elle est sans poste (montant entier), pas comparée au tarif carburant.
    f = ft(ligne(N.transport, "200.00"), ligne(N.surcharge, "45.00", libelle="Peak season surcharge"))
    r = un(run([f]), "D7")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("45.00")
    assert "aucun poste" in lib(r.constat)
    # Deux surcharges dans la grille, libellé d'aucune des deux : sans poste (et non « plusieurs postes »).
    g = grille(*POSTES, poste("SUR", N.surcharge, prix="6.00", libelles_reconnus=["surcharge sûreté"]))
    r = un(run([ft(ligne(N.surcharge, "48.00", libelle="Surcharge haute saison"))], g=g), "D7")
    assert r.constat.montant_en_jeu == D("48.00") and "aucun poste" in lib(r.constat)
    # Libellé reconnu : comparé au tarif du poste, comme avant.
    r = un(run([ft(ligne(N.surcharge, "10.00", libelle="Surcharge sûreté"))], g=g), "D7")
    assert r.constat.montant_en_jeu == D("4.00")


# --- D8 ----------------------------------------------------------------------------------------------------------------


def test_d8_tva_sur_debours_toujours_a_verifier():
    f = ft(ligne(N.debours_droits, "100.00", montant_tva="20.00"), ligne(N.debours_tva, "220.00"))
    rs = run([f])
    rs8 = par_id(rs, "D8")
    assert [r.outcome for r in rs8] == [Outcome.a_verifier, Outcome.conforme]
    c = rs8[0].constat
    assert c.montant_en_jeu == D("20.00") and c.raisons == [RaisonCode.point_fiscal]
    assert c.prochaine_action == ACTION_D8 and "expert-comptable" in c.prochaine_action
    textes_propres(rs)


def test_d8_taux_sans_montant():
    f = ft(ligne(N.debours_autres_taxes, "50.00", taux_tva="20"))
    assert par_id(run([f]), "D8")[0].constat.montant_en_jeu == D("10.00")


# --- D9 ----------------------------------------------------------------------------------------------------------------


def _dec_articles(n=None, articles=0):
    d = declaration(id="doc_dec1")
    if n is not None:
        d.dec.nombre_articles = vs("declaration.nombre_articles", str(n), document_id="doc_dec1")
    d.dec.articles = [
        ArticleDeclaration(
            numero_article=vs("declaration.articles[].numero_article", str(i + 1), document_id="doc_dec1")
        )
        for i in range(articles)
    ]
    return d


def test_d9_lignes_supplementaires():
    f = ft(ligne(N.frais_ligne_supplementaire, "30.00", quantite="6", libelle="Lignes supplémentaires"))
    rs = run([_dec_articles(8), f])
    r = un(rs, "D9")
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("15.00")
    assert r.details["inclus"] == 5 and r.attendu == "3"
    textes_propres(rs)
    ok = ft(ligne(N.frais_ligne_supplementaire, "15.00", quantite="3"))
    assert un(run([_dec_articles(8), ok]), "D9").outcome is Outcome.conforme


def test_d9_articles_comptes_a_verifier_et_sans_declaration():
    f = ft(ligne(N.frais_ligne_supplementaire, "30.00"))
    c = un(run([_dec_articles(articles=8), f]), "D9").constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.total_reconstruit in c.raisons
    assert un(run([f]), "D9").outcome is Outcome.non_verifiable


def test_d1_total_superieur_a_la_somme_lue_sous_le_seuil_d3703():
    # Scan : lignes lues sous C_MIN_CERTAIN, total HT imprimé supérieur à leur somme -> des lignes non lues
    # expliquent l'écart : non vérifiable (et non « à vérifier »).
    f = ft(
        ligne(N.frais_dedouanement, "50.00", confiance=0.80),
        ligne(N.debours_droits, "100.00", confiance=0.80),
        total_ht="455.00",
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ht")
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.confiance_insuffisante
    assert r.details["motif"] == "lignes_possiblement_non_lues"
    # écart de sens contraire (total inférieur) : une ligne non lue ne l'explique pas -> constat conservé
    f = ft(
        ligne(N.frais_dedouanement, "50.00", confiance=0.80),
        ligne(N.debours_droits, "100.00", confiance=0.80),
        total_ht="120.00",
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ht")
    assert r.outcome is Outcome.a_verifier


def test_d1_total_ht_avant_remise_en_ligne_negative():
    # D-4204 : total HT imprimé avant la remise portée en ligne négative : présentation, pas une erreur.
    f = ft(
        ligne(N.frais_dedouanement, "100.00", taux_tva="20", montant_tva="20.00"),
        ligne(N.autre_prestation, "-10.00", libelle="Remise FICTIF"),
        total_ht="100.00",
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ht")
    assert r.outcome is Outcome.conforme
    # Une présentation qui ne redonne pas le total exactement ne sert jamais de référence au montant.
    f = ft(
        ligne(N.frais_dedouanement, "100.00", taux_tva="20", montant_tva="18.00"),
        ligne(N.autre_prestation, "-10.00", libelle="Remise FICTIF", taux_tva="20", montant_tva="-2.00"),
        total_ht="115.00",
        total_tva="18.00",
        total_ttc="133.00",
    )
    r = next(x for x in d1_arithmetique(contexte([f])) if x.sous_controle == "total_ht")
    assert r.ecart == D("25.00")
