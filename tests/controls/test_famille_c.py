"""Famille C — facture du transitaire contre déclaration (SPEC §12). Données fictives."""

from decimal import Decimal as D

from controldone.controls.famille_c import (
    ACTION_C,
    ACTION_C3,
    c1_droits,
    c3_tva_autoliquidee,
    c7_references,
    c8_client_facture,
    reference_declaration,
    unites_c,
)
from controldone.controls.framework import run_controls
from controldone.guardrails import check_text
from controldone.model import (
    Allocation,
    CategorieTaxe,
    ChampsAvoir,
    Entite,
    ForceLien,
    IndiceAutoliquidation,
    LigneFactureTransitaire,
    MethodeAllocation,
    NatureLigne,
    NatureMontant,
    Niveau,
    Outcome,
    PaiementNormalise,
    Partie,
    QualiteTexte,
    RaisonCode,
    Sens,
    TypeDocument,
    TypeIndiceAutoliquidation,
)
from controldone.testing import contexte, declaration, document, facture_transitaire, taxation, vs

MRN_A = "26FR00000000000001"
MRN_B = "26FRK7Q2ZX9PLM3VB2"  # distinct de MRN_A (caractères aléatoires, D-3104)
TVA_CLIENT = "FR32000123459"
TVA_AUTRE = "FR61000999990"
C_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]


# --- fabriques -----------------------------------------------------------------------------------


def ligne(fid, nature, montant, *, mrn=None, libelle=None, methode="texte_natif", confiance=0.99, brut=None,
          pourcentage=None, page=1, **kw):
    def v(nom, val, b=None):
        if val is None:
            return None
        return vs(f"facture_transitaire.lignes[].{nom}", val, brut=b, document_id=fid, methode=methode,
                  confiance=confiance, page=page)

    return LigneFactureTransitaire(
        libelle=v("libelle", libelle or nature.value), nature=nature, montant_ht=v("montant_ht", montant, brut),
        mrn=v("mrn", mrn), pourcentage=v("pourcentage", pourcentage),
        **{k: v(k, x) for k, x in kw.items()},
    )


def ft(fid, *lignes, numero="FT-FICTIF-001", refs_mrn=(), client_tva=TVA_CLIENT, qualite=QualiteTexte.natif,
       **kw):
    f = facture_transitaire(
        id=fid, numero=vs("facture_transitaire.numero", numero, document_id=fid),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", m, document_id=fid) for m in refs_mrn],
        client_facture=Partie(tva=vs("facture_transitaire.client_facture.tva", client_tva, document_id=fid))
        if client_tva else Partie(),
        lignes=list(lignes), **kw,
    )
    if qualite is not QualiteTexte.natif:
        for p in f.pages:
            p.qualite_texte = qualite
    return f


def dec(did, *taxes, mrn=MRN_A, total=None, indices=(), version=None, articles=None, tva_imp=TVA_CLIENT):
    """``taxes`` : (categorie, montant[, paiement])."""
    tx = []
    for t in taxes:
        cat, montant = t[0], t[1]
        paiement = t[2] if len(t) > 2 else PaiementNormalise.comptant
        code = {CategorieTaxe.droit: "A00", CategorieTaxe.tva: "B00"}.get(cat, "C00")
        tx.append(taxation(did, categorie=cat, type_taxe=code, montant=montant, paiement=paiement))
    champs = {}
    if total is not None:
        champs["total_a_payer"] = vs("declaration.total_a_payer", total, document_id=did)
    if articles is not None:
        champs["nombre_articles"] = vs("declaration.nombre_articles", str(articles), document_id=did)
    if tva_imp:
        champs["importateur"] = Partie(tva=vs("declaration.importateur.tva", tva_imp, document_id=did))
    return declaration(id=did, mrn=mrn, taxations=tx, version=version,
                       indices_autoliquidation=list(indices), **champs)


def indice_1008(did, confiance=0.99):
    return IndiceAutoliquidation(
        type=TypeIndiceAutoliquidation.code_1008,
        valeur=vs("declaration.indices_autoliquidation[].valeur", "1008", document_id=did, confiance=confiance),
        tva=vs("declaration.indices_autoliquidation[].tva", TVA_CLIENT, document_id=did, confiance=confiance),
    )


def run(docs, controles=C_IDS, **kw):
    ctx = contexte(docs, **kw)
    return run_controls(ctx, controles=controles)


def par_id(rs, cid):
    return [r for r in rs if r.controle_id == cid]


def un(rs, cid):
    xs = par_id(rs, cid)
    assert len(xs) == 1, xs
    return xs[0]


def lib(c):
    """Libellé avec espaces insécables ramenées à des espaces (lisibilité des assertions)."""
    return c.libelle.replace("\xa0", " ")


def textes_propres(rs):
    for r in rs:
        if r.constat is not None:
            texte = r.constat.libelle + " " + r.constat.prochaine_action
            assert check_text(texte) == [], texte
            assert "droit du" not in texte.lower()
            assert r.constat.motif_blocage is None
            assert r.constat.preuves


DROIT, AUTRE, TVA = CategorieTaxe.droit, CategorieTaxe.autre_taxe, CategorieTaxe.tva
N = NatureLigne


def dossier_simple(droits="100.00", tva="220.00", ref_droits="100.00", ref_tva="220.00"):
    d = dec("doc_dec1", (DROIT, ref_droits), (TVA, ref_tva))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, droits), ligne("doc_ft1", N.debours_tva, tva))
    return d, f


# --- conforme, arrondis ---------------------------------------------------------------------------


def test_tout_conforme():
    rs = run(list(dossier_simple()))
    for cid in ("C1", "C2", "C4", "C5"):
        assert un(rs, cid).outcome is Outcome.conforme, cid
    assert un(rs, "C3").outcome is Outcome.non_applicable
    assert un(rs, "C1").unite == "dec:doc_dec1|ft:doc_ft1"
    assert not [r for r in rs if r.constat is not None]


def test_arrondi_sous_tolerance_est_conforme():
    rs = run(list(dossier_simple(droits="100.04")))
    r = un(rs, "C1")
    assert r.outcome is Outcome.conforme and r.tolerance_appliquee == D("0.05")


def test_ecart_sous_seuil_a_verifier():
    rs = run(list(dossier_simple(droits="100.60")))
    c = un(rs, "C1").constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.ecart_sous_seuil in c.raisons
    assert c.montant_en_jeu == D("0.60")


def test_tolerance_par_nombre_d_articles():
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "220.00"), articles=30)
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.25"), ligne("doc_ft1", N.debours_tva, "220.00"))
    r = un(run([d, f]), "C1")
    assert r.outcome is Outcome.conforme and r.tolerance_appliquee == D("0.30")


# --- écarts certains, montants, signes -------------------------------------------------------------


def test_c1_ecart_certain_et_c5_sans_montant():
    rs = run(list(dossier_simple(droits="150.00")))
    r = un(rs, "C1")
    c = r.constat
    assert r.outcome is Outcome.ecart_certain and c.raisons == []
    assert c.montant_en_jeu == D("50.00") and c.nature_montant is NatureMontant.recouvrable
    assert c.sens is Sens.defaveur_client and c.composante.value == "droit"
    assert "150,00 EUR" in lib(c) and "100,00 EUR" in lib(c) and "MRN " + MRN_A in lib(c)
    assert c.prochaine_action == ACTION_C
    assert {p.document_id for p in c.preuves} == {"doc_ft1", "doc_dec1"}
    c5 = un(rs, "C5").constat
    assert c5.niveau is Niveau.ecart_certain and c5.montant_en_jeu is None
    assert RaisonCode.doublon_composantes in c5.raisons and c5.montant_brut == D("50.00")
    textes_propres(rs)


def test_ecart_en_faveur_du_client_a_verifier_negatif():
    rs = run(list(dossier_simple(tva="200.00")))
    c = un(rs, "C4").constat
    assert c.niveau is Niveau.a_verifier and c.montant_en_jeu == D("-20.00")
    assert RaisonCode.ecart_en_faveur_client in c.raisons and c.sens is Sens.faveur_client
    textes_propres(rs)


def test_c2_autres_taxes_non_liquidees():
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "220.00"), total="320.00")
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), ligne("doc_ft1", N.debours_autres_taxes, "35.00"),
           ligne("doc_ft1", N.debours_tva, "220.00"))
    rs = run([d, f])
    c = un(rs, "C2").constat
    assert c.niveau is Niveau.ecart_certain and c.montant_en_jeu == D("35.00")
    assert "aucun montant liquidé" in lib(c)
    textes_propres(rs)


def test_composante_absente_sans_total_reste_a_verifier():
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "220.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), ligne("doc_ft1", N.debours_autres_taxes, "35.00"),
           ligne("doc_ft1", N.debours_tva, "220.00"))
    c = un(run([d, f]), "C2").constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.valeur_absente in c.raisons


# --- C3 / C4 : autoliquidation ----------------------------------------------------------------------


def _dec_autoliquidee(conf=0.99):
    return dec("doc_dec1", (DROIT, "100.00"), (TVA, "1240.00", PaiementNormalise.autoliquide),
               indices=[indice_1008("doc_dec1", conf)])


def test_c3_tva_refacturee_malgre_autoliquidation():
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), ligne("doc_ft1", N.debours_tva, "1240.00"))
    rs = run([_dec_autoliquidee(), f])
    r = un(rs, "C3")
    c = r.constat
    assert r.outcome is Outcome.ecart_certain and c.montant_en_jeu == D("1240.00")
    assert c.composante.value == "tva"
    assert "1 240,00 EUR de TVA à l'importation" in lib(c)
    assert "indiquée comme autoliquidée" in lib(c) and "code document 1008 suivi du numéro " + TVA_CLIENT in lib(c)
    assert "applicab" not in lib(c)  # le libellé ne dit rien de l'applicabilité
    assert c.prochaine_action == ACTION_C3
    assert un(rs, "C4").outcome is Outcome.non_applicable
    c5 = un(rs, "C5")
    assert c5.outcome is Outcome.conforme and c5.details["tva_exclue"] == "C3"
    textes_propres(rs)


def test_autoliquidation_sans_tva_refacturee_aucun_constat():
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"))
    rs = run([_dec_autoliquidee(), f])
    assert un(rs, "C3").outcome is Outcome.conforme
    assert not [r for r in rs if r.constat is not None]


def test_c3_indice_peu_sur_a_verifier():
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), ligne("doc_ft1", N.debours_tva, "1240.00"))
    d = dec("doc_dec1", (DROIT, "100.00"), indices=[indice_1008("doc_dec1", 0.7)])
    c = un(run([d, f]), "C3").constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.confiance_insuffisante in c.raisons
    assert c.montant_en_jeu == D("1240.00")


def test_reference_declaration_autoliquidation():
    r = reference_declaration(contexte([_dec_autoliquidee()]), _dec_autoliquidee())
    assert r.autoliquide and r.liquide[TVA] == 0 and r.liquide[DROIT] == D("100.00")


def test_c3_non_applicable_sans_autoliquidation():
    rs = run(list(dossier_simple()))
    assert un(rs, "C3").raison_code is RaisonCode.couvert_par_autre_controle


# --- C5 : débours combinés, complétude ----------------------------------------------------------


def test_ligne_combinee_droits_et_taxes():
    d = dec("doc_dec1", (DROIT, "100.00"), (AUTRE, "50.00"), (TVA, "200.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_combines, "400.00", libelle="Droits et taxes"))
    rs = run([d, f])
    for cid in ("C1", "C2", "C4"):
        assert un(rs, cid).outcome is Outcome.non_verifiable, cid
    c5 = un(rs, "C5").constat
    assert c5.niveau is Niveau.ecart_certain and c5.montant_en_jeu == D("50.00")
    assert RaisonCode.doublon_composantes not in c5.raisons
    assert "droits et taxes combinés" in lib(c5)
    textes_propres(rs)


def test_ligne_combinee_conforme():
    d = dec("doc_dec1", (DROIT, "100.00"), (AUTRE, "50.00"), (TVA, "200.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_combines, "350.00"))
    assert un(run([d, f]), "C5").outcome is Outcome.conforme


def test_regle_de_completude():
    # « autres taxes » non extraites : le total à payer (350) dépasse la somme lue (300).
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "200.00"), total="350.00")
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), ligne("doc_ft1", N.debours_autres_taxes, "50.00"),
           ligne("doc_ft1", N.debours_tva, "200.00"))
    rs = run([d, f])
    assert un(rs, "C2").outcome is Outcome.non_verifiable
    assert un(rs, "C1").outcome is Outcome.conforme
    c5 = un(rs, "C5")
    assert c5.outcome is Outcome.conforme and c5.attendu == "350.00"
    # Même dossier avec 80 EUR d'autres taxes refacturés : C5 porte seul le montant.
    f2 = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), ligne("doc_ft1", N.debours_autres_taxes, "80.00"),
            ligne("doc_ft1", N.debours_tva, "200.00"))
    c = un(run([d, f2]), "C5").constat
    assert c.niveau is Niveau.ecart_certain and c.montant_en_jeu == D("30.00")
    assert "total à payer imprimé" in lib(c)


def test_total_coherent_avec_tva_autoliquidee_incluse():
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "200.00", PaiementNormalise.autoliquide), total="300.00",
            indices=[indice_1008("doc_dec1")])
    r = reference_declaration(contexte([d]), d)
    assert r.complet_verifie and not r.total_utilise and r.liquide_total == D("100.00")


# --- §12.2 : multi-MRN, factures séparées, complémentaires --------------------------------------


def test_releve_multi_mrn_ventile_par_ligne():
    d1 = dec("doc_dec1", (DROIT, "100.00"), mrn=MRN_A)
    d2 = dec("doc_dec2", (DROIT, "60.00"), mrn=MRN_B)
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00", mrn=MRN_A),
           ligne("doc_ft1", N.debours_droits, "80.00", mrn=MRN_B), refs_mrn=[MRN_A, MRN_B], est_releve=True)
    rs = run([d1, d2, f])
    c1 = {r.unite: r for r in par_id(rs, "C1")}
    assert set(c1) == {"dec:doc_dec1|ft:doc_ft1", "dec:doc_dec2|ft:doc_ft1"}
    assert c1["dec:doc_dec1|ft:doc_ft1"].outcome is Outcome.conforme
    c = c1["dec:doc_dec2|ft:doc_ft1"].constat
    assert c.niveau is Niveau.ecart_certain and c.montant_en_jeu == D("20.00") and MRN_B in lib(c)
    assert MRN_A not in lib(c)


def test_multi_mrn_sans_ventilation_somme_des_declarations():
    d1 = dec("doc_dec1", (DROIT, "100.00"), mrn=MRN_A)
    d2 = dec("doc_dec2", (DROIT, "60.00"), mrn=MRN_B)
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "190.00"), refs_mrn=[MRN_A, MRN_B])
    rs = run([d1, d2, f])
    r = un(rs, "C1")
    assert r.unite == "dec:doc_dec1+doc_dec2|ft:doc_ft1"
    assert r.constat.montant_en_jeu == D("30.00") and MRN_A in lib(r.constat) and MRN_B in lib(r.constat)


def test_allocation_prorata_ignoree_comparaison_sur_la_somme():
    # §12.2, D-1207 : une ligne non ventilée répartie au prorata par le regroupement est comparée sur la
    # somme des déclarations couvertes ; plus de paire d'écarts +X / -X fictifs.
    d1 = dec("doc_dec1", (DROIT, "100.00"), mrn=MRN_A)
    d2 = dec("doc_dec2", (DROIT, "60.00"), mrn=MRN_B)
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "160.00"), refs_mrn=[MRN_A, MRN_B])
    ctx = contexte([d1, d2, f])
    ctx.dossier.allocations.extend([
        Allocation(source_document_id="doc_ft1", source_ligne=0, cible_document_id="doc_dec1",
                   montant_alloue=D("60.00"), methode=MethodeAllocation.prorata),
        Allocation(source_document_id="doc_ft1", source_ligne=0, cible_document_id="doc_dec2",
                   montant_alloue=D("100.00"), methode=MethodeAllocation.prorata),
    ])
    rs = run_controls(ctx, controles=["C1"])
    assert [(r.unite, r.outcome) for r in rs] == [("dec:doc_dec1+doc_dec2|ft:doc_ft1", Outcome.conforme)]


def test_allocation_prorata_ecart_sur_la_somme_reste_a_verifier():
    d1 = dec("doc_dec1", (DROIT, "100.00"), mrn=MRN_A)
    d2 = dec("doc_dec2", (DROIT, "60.00"), mrn=MRN_B)
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "200.00"), refs_mrn=[MRN_A, MRN_B])
    ctx = contexte([d1, d2, f])
    ctx.dossier.allocations.extend([
        Allocation(source_document_id="doc_ft1", source_ligne=0, cible_document_id="doc_dec1",
                   montant_alloue=D("100.00"), methode=MethodeAllocation.prorata),
        Allocation(source_document_id="doc_ft1", source_ligne=0, cible_document_id="doc_dec2",
                   montant_alloue=D("100.00"), methode=MethodeAllocation.prorata),
    ])
    rs = run_controls(ctx, controles=["C1"])
    assert len(rs) == 1 and rs[0].unite == "dec:doc_dec1+doc_dec2|ft:doc_ft1"
    c = rs[0].constat
    assert c.montant_en_jeu == D("40.00") and c.niveau is Niveau.a_verifier
    assert RaisonCode.allocation_prorata in c.raisons


def test_allocation_prorata_designe_les_declarations_couvertes():
    # D-1207 : la facture ne cite lisiblement qu'un MRN ; le regroupement a réparti la ligne sans MRN au
    # prorata sur les deux déclarations : la ligne est comparée à leur somme (100 + 60 = 160).
    d1 = dec("doc_dec1", (DROIT, "100.00"), mrn=MRN_A)
    d2 = dec("doc_dec2", (DROIT, "60.00"), mrn=MRN_B)
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "160.00"), refs_mrn=[MRN_A])
    ctx = contexte([d1, d2, f])
    ctx.dossier.allocations.extend([
        Allocation(source_document_id="doc_ft1", source_ligne=0, cible_document_id="doc_dec1",
                   montant_alloue=D("100.00"), methode=MethodeAllocation.prorata),
        Allocation(source_document_id="doc_ft1", source_ligne=0, cible_document_id="doc_dec2",
                   montant_alloue=D("60.00"), methode=MethodeAllocation.prorata),
    ])
    rs = run_controls(ctx, controles=["C1"])
    assert [(r.unite, r.outcome) for r in rs] == [("dec:doc_dec1+doc_dec2|ft:doc_ft1", Outcome.conforme)]


def test_allocation_explicite_respectee():
    d1 = dec("doc_dec1", (DROIT, "100.00"), mrn=MRN_A)
    d2 = dec("doc_dec2", (DROIT, "60.00"), mrn=MRN_B)
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "200.00"), refs_mrn=[MRN_A, MRN_B])
    ctx = contexte([d1, d2, f])
    ctx.dossier.allocations.extend([
        Allocation(source_document_id="doc_ft1", source_ligne=0, cible_document_id="doc_dec1",
                   montant_alloue=D("100.00"), methode=MethodeAllocation.reference_explicite),
        Allocation(source_document_id="doc_ft1", source_ligne=0, cible_document_id="doc_dec2",
                   montant_alloue=D("100.00"), methode=MethodeAllocation.reference_explicite),
    ])
    c1 = {r.unite: r for r in run_controls(ctx, controles=["C1"])}
    assert c1["dec:doc_dec2|ft:doc_ft1"].constat.montant_en_jeu == D("40.00")
    assert c1["dec:doc_dec1|ft:doc_ft1"].outcome is Outcome.conforme


def test_factures_debours_et_prestations_separees():
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "220.00"))
    f1 = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), ligne("doc_ft1", N.debours_tva, "220.00"),
            refs_mrn=[MRN_A])
    f2 = ft("doc_ft2", ligne("doc_ft2", N.frais_dedouanement, "65.00"), numero="FT-FICTIF-002", refs_mrn=[MRN_A])
    rs = run([d, f1, f2])
    assert [u.cle for u in unites_c(contexte([d, f1, f2]))] == ["dec:doc_dec1|ft:doc_ft1"]
    assert un(rs, "C1").outcome is Outcome.conforme and un(rs, "C5").outcome is Outcome.conforme
    assert not [r for r in rs if r.constat is not None]


def test_facture_complementaire_additionnee():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f1 = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "60.00"), refs_mrn=[MRN_A])
    f2 = ft("doc_ft2", ligne("doc_ft2", N.debours_droits, "40.00"), numero="FT-FICTIF-002", refs_mrn=[MRN_A])
    r = un(run([d, f1, f2]), "C1")
    assert r.unite == "dec:doc_dec1|ft:doc_ft1+doc_ft2" and r.outcome is Outcome.conforme


def test_meme_declaration_refacturee_deux_fois_excedent_en_c5():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f1 = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), refs_mrn=[MRN_A])
    f2 = ft("doc_ft2", ligne("doc_ft2", N.debours_droits, "100.00"), numero="FT-FICTIF-002", refs_mrn=[MRN_A])
    rs = run([d, f1, f2])
    assert un(rs, "C1").constat.montant_brut == D("100.00")
    assert "Les factures du transitaire" in lib(un(rs, "C1").constat)


def test_ligne_non_rattachee_a_un_autre_dossier_ecartee():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00", mrn=MRN_A),
           ligne("doc_ft1", N.debours_droits, "999.00", mrn=MRN_B), est_releve=True)
    assert un(run([d, f]), "C1").outcome is Outcome.conforme


# --- versions rectificatives, avoirs ------------------------------------------------------------------


def test_derniere_version_rectificative_seulement():
    v1 = dec("doc_dec1", (DROIT, "150.00"), version="1", mrn="26FR00000000000001")
    v2 = dec("doc_dec2", (DROIT, "100.00"), version="2", mrn="26FR00000000000017")
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "150.00"))
    rs = run([v1, v2, f])
    r = un(rs, "C1")
    assert r.unite == "dec:doc_dec2|ft:doc_ft1" and r.attendu == "100.00"
    c = r.constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.version_rectificative in c.raisons
    assert c.montant_en_jeu == D("50.00")


def test_avoir_deja_recu_deduit_montant_brut_conserve():
    d, f = dossier_simple(droits="150.00")
    a = document(TypeDocument.avoir, ChampsAvoir(
        numero=vs("avoir.numero", "AV-FICTIF-1", document_id="doc_av1"),
        refs_facture_origine=[vs("avoir.refs_facture_origine[]", "FT-FICTIF-001", document_id="doc_av1")],
        lignes=[ligne("doc_av1", N.debours_droits, "30.00")],
    ), id="doc_av1")
    rs = run([d, f, a])
    c = un(rs, "C1").constat
    assert c.montant_en_jeu == D("20.00") and c.montant_brut == D("50.00")
    assert "avoir déjà reçu" in lib(c) and "doc_av1" in c.documents_concernes
    # Avoir couvrant tout l'écart : conforme.
    a.av.lignes[0].montant_ht = vs("avoir.lignes[].montant_ht", "50.00", document_id="doc_av1")
    assert un(run([d, f, a]), "C1").outcome is Outcome.conforme


def test_avoir_d_un_autre_emetteur_non_deduit():
    # D-1210 (§17.2, D-304) : même émetteur exigé, comme en famille E.
    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "150.00"),
           emetteur=Partie(tva=vs("facture_transitaire.emetteur.tva", "FR11000555550", document_id="doc_ft1")))
    a = document(TypeDocument.avoir, ChampsAvoir(
        numero=vs("avoir.numero", "AV-FICTIF-1", document_id="doc_av1"),
        emetteur=Partie(tva=vs("avoir.emetteur.tva", TVA_AUTRE, document_id="doc_av1")),
        refs_facture_origine=[vs("avoir.refs_facture_origine[]", "FT-FICTIF-001", document_id="doc_av1")],
        lignes=[ligne("doc_av1", N.debours_droits, "30.00")],
    ), id="doc_av1")
    c = un(run([d, f, a]), "C1").constat
    assert c.montant_en_jeu == D("50.00") and "doc_av1" not in c.documents_concernes


# --- à vérifier : chaque raison --------------------------------------------------------------------


def test_lecture_ocr_douteuse():
    d = dec("doc_dec1", (DROIT, "108.00"), (TVA, "220.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "168.00", methode="ocr", confiance=0.95),
           ligne("doc_ft1", N.debours_tva, "220.00"), qualite=QualiteTexte.ocr)
    c = un(run([d, f]), "C1").constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.lecture_douteuse in c.raisons
    assert c.montant_en_jeu == D("60.00")


def test_transposition_reste_certaine():
    d = dec("doc_dec1", (DROIT, "108.00"), (TVA, "220.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "180.00", methode="ocr", confiance=0.95),
           ligne("doc_ft1", N.debours_tva, "220.00"), qualite=QualiteTexte.ocr)
    assert un(run([d, f]), "C1").outcome is Outcome.ecart_certain


def test_confiance_insuffisante_et_rattachement_faible():
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "220.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "150.00", confiance=0.8),
           ligne("doc_ft1", N.debours_tva, "220.00"))
    assert RaisonCode.confiance_insuffisante in un(run([d, f]), "C1").constat.raisons
    d2, f2 = dossier_simple(droits="150.00")
    c = un(run([d2, f2], force=ForceLien.faible), "C1").constat
    assert c.niveau is Niveau.a_verifier and RaisonCode.rattachement_faible in c.raisons


# --- non vérifiable, non applicable --------------------------------------------------------------


def test_sans_facture_transitaire_non_applicable():
    rs = run([dec("doc_dec1", (DROIT, "100.00"))])
    for cid in C_IDS:
        r = un(rs, cid)
        assert r.outcome is Outcome.non_applicable and r.raison_code is RaisonCode.facture_transitaire_absente


def test_sans_declaration_non_verifiable():
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"))
    r = c1_droits(contexte([f]))[0]
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.document_manquant


def test_ligne_illisible_non_verifiable():
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "220.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "150.00", confiance=0.3),
           ligne("doc_ft1", N.debours_tva, "220.00"))
    rs = run([d, f])
    assert un(rs, "C1").raison_code is RaisonCode.confiance_insuffisante
    assert un(rs, "C5").outcome is Outcome.non_verifiable
    assert un(rs, "C4").outcome is Outcome.conforme


def test_facture_sans_debours_non_applicable():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.frais_dedouanement, "65.00"))
    r = c3_tva_autoliquidee(contexte([d, f]))[0]
    assert r.outcome is Outcome.non_applicable and r.details["motif"] == "aucune_ligne_de_debours"


def test_declaration_sans_taxation_ni_total_non_verifiable():
    d = dec("doc_dec1")
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"))
    rs = run([d, f])
    assert un(rs, "C1").outcome is Outcome.non_verifiable and un(rs, "C5").outcome is Outcome.non_verifiable


# --- C6 -----------------------------------------------------------------------------------------------


def test_c6_faf_sur_excedent_seulement():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "1100.00"),
           ligne("doc_ft1", N.frais_avance_fonds, "27.50", pourcentage="2.5", libelle="Avance de fonds"))
    rs = run([d, f])
    assert un(rs, "C1").outcome is Outcome.ecart_certain
    r = un(rs, "C6")
    c = r.constat
    assert r.unite == "ft:doc_ft1|ligne:1"
    assert c.niveau is Niveau.ecart_certain and c.montant_en_jeu == D("25.00")
    assert c.composante.value == "prestation" and "2,5 %" in lib(c)
    textes_propres(rs)


def test_c6_faf_corrige_arrondi_avant_la_difference():
    # D-1212 : 2,5 % × 3 444,20 = 86,105 -> 86,11 (facturé) ; 2,5 % × 3 382,02 = 84,5505 -> 84,55 ;
    # excédent = 86,11 − 84,55 = 1,56 (et non 1,5545 arrondi à 1,55).
    d = dec("doc_dec1", (DROIT, "3382.02"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "3444.20"),
           ligne("doc_ft1", N.frais_avance_fonds, "86.11", pourcentage="2.5", libelle="Avance de fonds"))
    assert un(run([d, f]), "C6").constat.montant_en_jeu == D("1.56")


def test_c6_faf_au_minimum_sans_excedent():
    from controldone.model import GrilleTarifaire, ModePoste, PosteGrille, StatutGrille, Transitaire

    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "300.00"),
           ligne("doc_ft1", N.frais_avance_fonds, "15.00"),
           emetteur=Partie(tva=vs("facture_transitaire.emetteur.tva", "FR11000555550", document_id="doc_ft1")))
    g = GrilleTarifaire(transitaire_id="tra_1", reference="DEV-FICTIF-1", statut=StatutGrille.validee, postes=[
        PosteGrille(code_poste="FAF", nature=N.frais_avance_fonds, mode=ModePoste.pourcentage,
                    pourcentage=D("2.5"), minimum=D("15.00")),
    ])
    rs = run([d, f], grilles=[g], transitaires=[Transitaire(id="tra_1", nom="Transit FICTIF", tva="FR11000555550")])
    assert un(rs, "C1").outcome is Outcome.ecart_certain
    assert un(rs, "C6").outcome is Outcome.conforme


def test_c6_depend_d_un_constat_a_verifier():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "1100.00", confiance=0.8),
           ligne("doc_ft1", N.frais_avance_fonds, "27.50", pourcentage="2.5"))
    c = un(run([d, f]), "C6").constat
    assert c.niveau is Niveau.a_verifier and c.montant_en_jeu == D("25.00")


def test_c6_taux_inconnu_non_verifiable():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "1100.00"), ligne("doc_ft1", N.frais_avance_fonds, "27.50"))
    assert un(run([d, f]), "C6").outcome is Outcome.non_verifiable


# --- C7, C8 ------------------------------------------------------------------------------------------------


def test_c7_mrn_cite_inconnu():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), refs_mrn=[MRN_A, MRN_B])
    r = c7_references(contexte([d, f]))[0]
    assert r.outcome is Outcome.a_verifier and MRN_B in lib(r.constat) and MRN_A not in lib(r.constat)
    assert r.constat.montant_en_jeu is None
    textes_propres([r])
    f2 = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), refs_mrn=["26 FR 0000000000000 1"])
    assert c7_references(contexte([d, f2]))[0].outcome is Outcome.conforme


def test_c7_reference_transport():
    from controldone.model import DocumentReference

    d = dec("doc_dec1", (DROIT, "100.00"))
    d.dec.documents_references.append(DocumentReference(
        type_code=vs("declaration.documents_references[].type_code", "N740", document_id="doc_dec1"),
        reference=vs("declaration.documents_references[].reference", "999-11112222", document_id="doc_dec1")))
    ok = ft("doc_ft1", refs_transport=[vs("facture_transitaire.refs_transport[]", "999 1111 2222", document_id="doc_ft1")])
    assert c7_references(contexte([d, ok]))[0].outcome is Outcome.conforme
    ko = ft("doc_ft1", refs_transport=[vs("facture_transitaire.refs_transport[]", "176-55556666", document_id="doc_ft1")])
    r = c7_references(contexte([d, ko]))[0]
    assert r.outcome is Outcome.a_verifier and "176-55556666" in lib(r.constat)


def test_c8_client_facture():
    entites = [Entite(id="ent_1", raison_sociale="Société A FICTIVE", tva=TVA_CLIENT),
               Entite(id="ent_2", raison_sociale="Société B FICTIVE", tva=TVA_AUTRE)]
    d = dec("doc_dec1", (DROIT, "100.00"))
    ok = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"))
    assert c8_client_facture(contexte([d, ok], entites=entites))[0].outcome is Outcome.conforme
    ko = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), client_tva=TVA_AUTRE, refs_mrn=(MRN_A,))
    r = c8_client_facture(contexte([d, ko], entites=entites))[0]
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu is None
    assert "Société B FICTIVE" in lib(r.constat)
    textes_propres([r])
    sans = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "100.00"), client_tva=None)
    assert c8_client_facture(contexte([d, sans], entites=entites))[0].outcome is Outcome.non_verifiable


def test_c8_tva_peu_sure_a_verifier():
    d = dec("doc_dec1", (DROIT, "100.00"))
    f = ft("doc_ft1", client_tva=None)
    f.ft.client_facture.tva = vs("facture_transitaire.client_facture.tva", TVA_AUTRE, document_id="doc_ft1",
                                 confiance=0.7)
    r = c8_client_facture(contexte([d, f]))[0]
    assert r.outcome is Outcome.a_verifier and RaisonCode.confiance_insuffisante in r.constat.raisons


# --- D-902 : garde de complétude (lecture des lignes de taxation incomplète) ---------------------------


def _dec_lignes(did, lignes, *, total=None, total_conf=0.83, articles=None):
    """``lignes`` : (article, categorie, montant)."""
    code = {DROIT: "A00", TVA: "B00", AUTRE: "A30"}
    tx = [taxation(did, article=a, categorie=cat, type_taxe=code[cat], montant=m) for a, cat, m in lignes]
    champs = {"importateur": Partie(tva=vs("declaration.importateur.tva", TVA_CLIENT, document_id=did))}
    if total is not None:
        champs["total_a_payer"] = vs("declaration.total_a_payer", total, document_id=did, confiance=total_conf)
    if articles is not None:
        champs["nombre_articles"] = vs("declaration.nombre_articles", str(articles), document_id=did)
    return declaration(id=did, mrn=MRN_A, taxations=tx, **champs)


def _ft_debours(droits, autres, tva):
    return ft("doc_ft1", ligne("doc_ft1", N.debours_droits, droits),
              ligne("doc_ft1", N.debours_autres_taxes, autres), ligne("doc_ft1", N.debours_tva, tva))


def test_total_imprime_contredit_la_somme_lue_composante_a_verifier():
    # Une ligne « autres taxes » (droit spécifique) n'a pas été lue et une ligne de TVA est mal lue
    # (somme lue > total) : le total à payer imprimé, lu à 0,83, ne concorde pas avec la somme des lignes.
    lignes = [("1", DROIT, "100.00"), ("1", AUTRE, "200.00"), ("1", TVA, "200000.00")]
    f = _ft_debours("100.00", "274.76", "2000.00")
    sans_total = un(run([_dec_lignes("doc_dec1", lignes), f]), "C2").constat
    assert sans_total.niveau is Niveau.ecart_certain  # aucun total imprimé lu : rien ne signale l'incomplétude
    rs = run([_dec_lignes("doc_dec1", lignes, total="2374.76"), f])
    c2 = un(rs, "C2")
    assert c2.constat.niveau is Niveau.a_verifier and RaisonCode.valeur_absente in c2.constat.raisons
    assert c2.details["lecture_incomplete"] == {"doc_dec1": "total_imprime_different_de_la_somme_des_lignes_lues"}
    assert un(rs, "C5").constat.niveau is Niveau.a_verifier
    textes_propres(rs)


def test_total_imprime_concordant_ecart_reste_certain():
    lignes = [("1", DROIT, "100.00"), ("1", AUTRE, "200.00"), ("1", TVA, "2000.00")]
    rs = run([_dec_lignes("doc_dec1", lignes, total="2300.00", total_conf=0.83),
              _ft_debours("100.00", "274.76", "2000.00")])
    assert un(rs, "C2").constat.niveau is Niveau.ecart_certain


def test_total_peu_lisible_ignore():
    # Total sous C_MIN_UTILE : inexploitable, il ne déclenche pas la garde.
    lignes = [("1", DROIT, "100.00"), ("1", AUTRE, "200.00"), ("1", TVA, "2000.00")]
    rs = run([_dec_lignes("doc_dec1", lignes, total="9999.99", total_conf=0.3),
              _ft_debours("100.00", "274.76", "2000.00")])
    assert un(rs, "C2").constat.niveau is Niveau.ecart_certain


def test_difference_expliquee_par_la_tva_autoliquidee():
    d = dec("doc_dec1", (DROIT, "100.00"), (TVA, "200.00", PaiementNormalise.autoliquide), total="300.00",
            indices=[indice_1008("doc_dec1")])
    assert reference_declaration(contexte([d]), d).lecture_incomplete is None
    d2 = dec("doc_dec1", (DROIT, "100.00"), (TVA, "200.00", PaiementNormalise.autoliquide), total="100.00",
             indices=[indice_1008("doc_dec1")])
    assert reference_declaration(contexte([d2]), d2).lecture_incomplete is None


def test_lignes_par_article_incompletes():
    f = ft("doc_ft1", ligne("doc_ft1", N.debours_droits, "150.00"), ligne("doc_ft1", N.debours_tva, "440.00"))
    complet = [("1", DROIT, "50.00"), ("1", TVA, "220.00"), ("2", DROIT, "50.00"), ("2", TVA, "220.00")]
    assert un(run([_dec_lignes("doc_dec1", complet), f]), "C1").constat.niveau is Niveau.ecart_certain
    # article 3 annoncé (nombre d'articles imprimé) mais sans aucune ligne lue
    d = _dec_lignes("doc_dec1", complet, articles=3)
    r = reference_declaration(contexte([d]), d)
    assert r.lecture_incomplete == "article_sans_ligne_de_taxation"
    c1 = un(run([d, f]), "C1").constat
    assert c1.niveau is Niveau.a_verifier and RaisonCode.valeur_absente in c1.raisons
    # article 2 sans ligne de TVA alors que les autres en ont une
    d = _dec_lignes("doc_dec1", [*complet[:3], ("3", DROIT, "0.00"), ("3", TVA, "10.00")])
    assert reference_declaration(contexte([d]), d).lecture_incomplete == "article_sans_ligne_de_sa_categorie"
