"""Rappel des écarts certains et bruit « à vérifier » (D-2303 à D-2316). Données fictives construites ici."""

from decimal import Decimal as D

from controldone.controls.context import (
    C_LECTURE_CONFIRMABLE,
    Confusion,
    ControlContext,
    lecture_improbable,
)
from controldone.controls.famille_a import _explique_par_pied
from controldone.controls.famille_b import b3_somme_montants_articles as b3_somme_articles
from controldone.controls.famille_b import b4_masses
from controldone.controls.famille_d import _libelles_concordants
from controldone.controls.framework import run_controls
from controldone.model import (
    Allocation,
    ArticleDeclaration,
    CategorieTaxe,
    ChampsFactureTransitaire,
    ForceLien,
    GrilleTarifaire,
    LienDocument,
    LigneFactureTransitaire,
    Methode,
    MethodeAllocation,
    ModePoste,
    NatureLigne,
    Outcome,
    Partie,
    PosteGrille,
    PrestationsHorsGrille,
    ProfilTolerances,
    QualiteTexte,
    RaisonCode,
    RoleLien,
    SignalLien,
    StatutGrille,
    Transitaire,
    TypeDocument,
)
from controldone.model.dossier import Dossier
from controldone.model.valeur import Zone
from controldone.testing import declaration, document, dossier_pour, taxation, vs

N = NatureLigne
FT = "doc_ft_fictif"
MRN_A = "26FRAAAAAAAAAAAAA1"
MRN_B = "26FRBBBBBBBBBBBBB2"


def v_ft(chemin, valeur, *, conf=0.99, methode=Methode.texte_natif, **kw):
    return vs(f"facture_transitaire.{chemin}", valeur, document_id=FT, confiance=conf, methode=methode, **kw)


def ligne(
    i,
    nature,
    montant,
    *,
    conf=0.99,
    methode=Methode.texte_natif,
    libelle=None,
    mrn=None,
    quantite=None,
    prix=None,
    q_methode=Methode.texte_natif,
):
    return _ligne(i, nature, montant, conf, methode, libelle, mrn, quantite, prix, q_methode)


def _ligne(i, nature, montant, conf, methode, libelle, mrn, quantite, prix, q_methode):
    return LigneFactureTransitaire(
        nature=nature,
        libelle=None
        if libelle == ""
        else v_ft(f"lignes[{i}].libelle", libelle or nature.value.replace("_", " ")),
        montant_ht=v_ft(f"lignes[{i}].montant_ht", montant, conf=conf, methode=methode),
        mrn=v_ft(f"lignes[{i}].mrn", mrn) if mrn else None,
        quantite=v_ft(
            f"lignes[{i}].quantite",
            quantite,
            methode=q_methode,
            **({"regle_derivation": "quantite_implicite"} if q_methode is Methode.derive else {}),
        )
        if quantite
        else None,
        prix_unitaire=v_ft(f"lignes[{i}].prix_unitaire", prix) if prix else None,
    )


def ft(*lignes, total_ht=None, total_conf=0.99, qualite=QualiteTexte.ocr, mrns=(MRN_A,)):
    champs = ChampsFactureTransitaire(
        numero=v_ft("numero", "FA-FICTIF-23"),
        date=v_ft("date", "2026-09-15"),
        emetteur=Partie(tva=v_ft("emetteur.tva", "FR11000555550")),
        client_facture=Partie(tva=v_ft("client_facture.tva", "FR68000458570")),
        refs_mrn=[v_ft(f"refs_mrn[{k}]", m) for k, m in enumerate(mrns)],
        lignes=list(lignes),
        total_ht=v_ft("total_ht", total_ht, conf=total_conf) if total_ht else None,
    )
    return document(TypeDocument.facture_transitaire, champs, id=FT, qualite=qualite)


def ctx(docs, **kw):
    return ControlContext.construire(
        dossier_pour(docs), docs, ProfilTolerances(id="tol_test"), execution_id="exe_test", **kw
    )


# --- D-2303 : une lecture confirmée par une identité imprimée n'est pas « douteuse » ---------------------------


def test_confusion_ecartee_quand_la_somme_imprimee_confirme_la_lecture():
    l0 = ligne(0, N.frais_dedouanement, "70.00", conf=0.92, methode=Methode.ocr)
    l1 = ligne(1, N.transport, "30.00", conf=0.92, methode=Methode.ocr)
    c = ctx([ft(l0, l1, total_ht="100.00")])
    # toute variante de lecture « expliquerait » l'écart : sans identité, le test serait positif
    assert c.confirmee_par_identite(l0.montant_ht)
    assert not c.lecture_douteuse([Confusion(l0.montant_ht, accepte=lambda x: x != D("70.00"))])


def test_confusion_maintenue_sans_identite_qui_confirme():
    l0 = ligne(0, N.frais_dedouanement, "70.00", conf=0.92, methode=Methode.ocr)
    c = ctx([ft(l0)])  # aucun total imprimé
    assert not c.confirmee_par_identite(l0.montant_ht)
    assert c.lecture_douteuse([Confusion(l0.montant_ht, accepte=lambda x: x != D("70.00"))])


# --- D-2314 : confiance remplie par une identité arithmétique hors calcul contesté ------------------------------


def test_lecture_sous_le_seuil_confirmee_par_une_somme_releve_la_confiance():
    l0 = ligne(0, N.frais_dedouanement, "70.00", conf=0.88, methode=Methode.ocr)
    l1 = ligne(1, N.transport, "30.00", conf=0.92, methode=Methode.ocr)
    c = ctx([ft(l0, l1, total_ht="100.00")])
    (sortie,) = c._confiance_par_identite([l0.montant_ht])
    assert sortie.confiance == c.profil.c_min_certain


def test_identite_contestee_ne_confirme_pas():
    l0 = ligne(0, N.frais_dedouanement, "70.00", conf=0.88, methode=Methode.ocr)
    l1 = ligne(1, N.transport, "30.00", conf=0.88, methode=Methode.ocr)
    doc = ft(l0, l1, total_ht="100.00", total_conf=0.88)
    c = ctx([doc])
    # toutes les valeurs de la somme sont valeurs clés : c'est le calcul contesté, il ne prouve rien
    sortie = c._confiance_par_identite([l0.montant_ht, l1.montant_ht, doc.ft.total_ht])
    assert all(v.confiance == 0.88 for v in sortie)


def test_lecture_trop_peu_sure_ou_derivee_non_relevee():
    l0 = ligne(0, N.frais_dedouanement, "70.00", conf=C_LECTURE_CONFIRMABLE - 0.05, methode=Methode.ocr)
    l1 = ligne(1, N.transport, "30.00", conf=0.92, methode=Methode.ocr)
    c = ctx([ft(l0, l1, total_ht="100.00")])
    (sortie,) = c._confiance_par_identite([l0.montant_ht])
    assert sortie.confiance < C_LECTURE_CONFIRMABLE


# --- D-2310 : écart expliqué par une confusion sur des lectures peu sûres : pas de constat -------------------------


def test_lecture_improbable_conjonction_seulement():
    r = RaisonCode
    assert lecture_improbable("B1", [r.lecture_douteuse, r.confiance_insuffisante])
    assert not lecture_improbable("B1", [r.lecture_douteuse])
    assert not lecture_improbable("B1", [r.confiance_insuffisante])
    assert not lecture_improbable("P1", [r.lecture_douteuse, r.confiance_insuffisante])


def test_b1_ocr_peu_sur_explique_par_confusion_non_verifiable():
    # base 100 × 10 % = 10,00 ; montant lu « 16,00 » (6 pour 0) à 0,80 : pas de constat
    did = "doc_dec_b1"
    d = declaration(
        id=did,
        qualite=QualiteTexte.ocr,
        taxations=[
            taxation(did, base="100.00", taux="10", montant="16.00", methode=Methode.ocr, confiance=0.8)
        ],
    )
    rs = [r for r in run_controls(ctx([d]), controles=["B1"]) if r.controle_id == "B1"]
    assert rs and all(r.constat is None for r in rs)
    nv = [r for r in rs if r.outcome is Outcome.non_verifiable]
    assert nv and nv[0].raison_code is RaisonCode.lecture_douteuse
    assert nv[0].details["motif"] == "ecart_explique_par_une_lecture_douteuse"


# --- D-2304 : allocations dont dépend la comparaison -------------------------------------------------------------


def _alloc(src, ligne_, cible, methode=MethodeAllocation.prorata, montant=D("1")):
    return Allocation(
        source_document_id=src,
        source_ligne=ligne_,
        cible_document_id=cible,
        methode=methode,
        montant_alloue=montant,
    )


def _ctx_alloc(docs, allocations):
    dos = dossier_pour(docs)
    dos = dos.model_copy(update={"allocations": allocations})
    return ControlContext.construire(dos, docs, ProfilTolerances(id="tol_test"), execution_id="exe_test")


def test_allocation_d_une_autre_ligne_ne_compte_pas():
    l0 = ligne(0, N.debours_droits, "100.00", mrn=MRN_A)
    l1 = ligne(1, N.debours_droits, "50.00")
    da, db = declaration(id="doc_da", mrn=MRN_A), declaration(id="doc_db", mrn=MRN_B)
    allocs = [_alloc(FT, 0, "doc_da", MethodeAllocation.ligne_par_mrn), _alloc(FT, 1, "doc_da", montant=None)]
    c = _ctx_alloc([ft(l0, l1, mrns=(MRN_A, "26FRCCCCCCCCCCCCC3")), da, db], allocs)
    garde = c._allocations_en_jeu(allocs, [l0.montant_ht], [FT, "doc_da"])
    assert [a.methode for a in garde] == [MethodeAllocation.ligne_par_mrn]


def test_controle_interne_a_un_document_ne_depend_d_aucune_allocation():
    d = declaration(id="doc_da", mrn=MRN_A)
    allocs = [_alloc(FT, 0, "doc_da")]
    c = _ctx_alloc([ft(ligne(0, N.debours_droits, "10.00")), d], allocs)
    assert c._allocations_en_jeu(allocs, [], ["doc_da"]) == []


def test_ligne_au_prorata_entre_declarations_toutes_comparees_neutre():
    l0 = ligne(0, N.debours_droits, "100.00")
    da, db = declaration(id="doc_da", mrn=MRN_A), declaration(id="doc_db", mrn=MRN_B)
    allocs = [_alloc(FT, 0, "doc_da", montant=D("60")), _alloc(FT, 0, "doc_db", montant=D("40"))]
    c = _ctx_alloc([ft(l0, mrns=(MRN_A, MRN_B)), da, db], allocs)
    assert c._allocations_en_jeu(allocs, [l0.montant_ht], [FT, "doc_da", "doc_db"]) == []
    # une seule des deux déclarations comparée : la clé de répartition compte
    assert len(c._allocations_en_jeu(allocs, [l0.montant_ht], [FT, "doc_da"])) == 1


def test_part_inconnue_ou_mrn_hors_dossier_reste_prorata():
    l0 = ligne(0, N.debours_droits, "100.00")
    da, db = declaration(id="doc_da", mrn=MRN_A), declaration(id="doc_db", mrn=MRN_B)
    allocs = [_alloc(FT, 0, "doc_da", montant=D("60")), _alloc(FT, 0, "doc_db", montant=D("40"))]
    c = _ctx_alloc([ft(l0, mrns=(MRN_A, MRN_B, "26FRCCCCCCCCCCCCC3")), da, db], allocs)
    assert len(c._allocations_en_jeu(allocs, [l0.montant_ht], [FT, "doc_da", "doc_db"])) == 2


# --- D-2315 : versions d'un même MRN aux confusions OCR près ------------------------------------------------------


def test_mrn_egaux_aux_confusions_ocr_pres_sont_deux_versions():
    d1 = declaration(id="doc_v1", mrn="26FREMPO5ICM40E0RW", version="1")
    d2 = declaration(id="doc_v2", mrn="26FREMPOSICM40ES19", version="2")
    c = ctx([d1, d2])
    assert [d.id for d in c.declarations()] == ["doc_v2"]
    assert [d.id for d in c.versions_anterieures(d2)] == ["doc_v1"]
    assert c.version_retenue(d1).id == "doc_v2"


def test_mrn_distincts_restent_deux_declarations():
    c = ctx([declaration(id="doc_a", mrn=MRN_A), declaration(id="doc_b", mrn=MRN_B)])
    assert len(c.declarations()) == 2


# --- D-2309 : lignes de pied signées ------------------------------------------------------------------------------


def test_fret_plus_assurance_moins_remise_explique_l_ecart():
    fret = vs("facture_commerciale.sous_totaux[0].montant", "485.04")
    assu = vs("facture_commerciale.sous_totaux[1].montant", "23.06")
    remise = vs("facture_commerciale.sous_totaux[2].montant", "112.80")
    pieds = [(fret, 1), (assu, 1), (remise, -1)]
    assert _explique_par_pied(pieds, D("-395.30"), D("0.05")) == [fret, assu, remise]
    assert _explique_par_pied(pieds, D("-620.90"), D("0.05")) == [
        fret,
        assu,
        remise,
    ]  # lecture en valeur absolue
    assert _explique_par_pied(pieds, D("-200.00"), D("0.05")) == []


# --- D-2307 : somme lue incomplète (B3, B4) -----------------------------------------------------------------------


def _dec_articles(did, *, montants=(), brutes=(), total=None, brute_totale=None, n=3):
    arts = [
        ArticleDeclaration(
            numero_article=vs("declaration.articles[].numero_article", str(k + 1), document_id=did),
            montant_facture_article=vs("declaration.articles[].montant_facture_article", m, document_id=did)
            if m
            else None,
            masse_brute=vs("declaration.articles[].masse_brute", b, document_id=did) if b else None,
        )
        for k, (m, b) in enumerate(
            zip(montants or [None] * len(brutes), brutes or [None] * len(montants), strict=True)
        )
    ]
    champs = dict(
        articles=arts,
        nombre_articles=vs("declaration.nombre_articles", str(n), document_id=did),
        devise_facture=vs("declaration.devise_facture", "EUR", document_id=did),
    )
    if total:
        champs["montant_total_facture"] = vs("declaration.montant_total_facture", total, document_id=did)
    if brute_totale:
        champs["masse_brute_totale"] = vs("declaration.masse_brute_totale", brute_totale, document_id=did)
    return declaration(id=did, **champs)


def test_b3_articles_non_lus_et_total_superieur_non_verifiable():
    d = _dec_articles("doc_b3", montants=("100.00", "200.00"), total="450.00")
    (r,) = b3_somme_articles(ctx([d]))
    assert r.outcome is Outcome.non_verifiable and r.details["motif"] == "articles_non_lus"


def test_b3_somme_lue_superieure_au_total_reste_constat():
    d = _dec_articles("doc_b3", montants=("100.00", "200.00"), total="250.00")
    (r,) = b3_somme_articles(ctx([d]))
    assert r.constat is not None and RaisonCode.valeur_absente in r.constat.raisons


def test_b4_somme_brute_incomplete_non_verifiable():
    d = _dec_articles("doc_b4", brutes=("10.000", "20.000"), brute_totale="45.000")
    rs = [r for r in b4_masses(ctx([d])) if r.sous_controle == "somme_brute"]
    assert rs and rs[0].outcome is Outcome.non_verifiable and rs[0].details["motif"] == "articles_non_lus"


# --- D-2306 / D-2311 / D-2313 / D-2316 : familles C et D ----------------------------------------------------------

GRILLE = GrilleTarifaire(
    transitaire_id="tra_1",
    reference="DEV-FICTIF-23",
    statut=StatutGrille.validee,
    prestations_hors_grille=PrestationsHorsGrille.interdites,
    postes=[
        PosteGrille(code_poste="DEDOU", nature=N.frais_dedouanement, mode=ModePoste.forfait, prix=D("50.00"))
    ],
)
TRANSITAIRES = [Transitaire(id="tra_1", nom="Transit FICTIF", tva="FR11000555550")]


def _resultats(docs, cid):
    c = ControlContext.construire(
        dossier_pour(docs),
        docs,
        ProfilTolerances(id="tol_test"),
        execution_id="exe_test",
        grilles=[GRILLE],
        transitaires=TRANSITAIRES,
    )
    return [r for r in run_controls(c, controles=[cid]) if r.controle_id == cid]


def test_d2_ligne_sans_libelle_non_verifiable():
    rs = _resultats([ft(ligne(0, N.autre_prestation, "76.52", libelle=""), qualite=QualiteTexte.natif)], "D2")
    assert rs and all(r.constat is None for r in rs)
    assert any(r.details.get("motif") == "libelle_absent" for r in rs)


def test_d2_ligne_qui_renvoie_a_une_annexe_non_verifiable():
    lg = ligne(0, N.autre_prestation, "876.20", libelle="Suplidos según anexo (página 2)")
    rs = _resultats([ft(lg, qualite=QualiteTexte.natif)], "D2")
    assert any(r.details.get("motif") == "renvoi_annexe" for r in rs) and all(r.constat is None for r in rs)


def test_d2_prestation_hors_grille_libellee_reste_constat():
    lg = ligne(0, N.autre_prestation, "18.00", libelle="Contrôle documentaire FICTIF")
    rs = _resultats([ft(lg, qualite=QualiteTexte.natif)], "D2")
    assert any(r.constat is not None for r in rs)


def test_d1_quantite_implicite_non_verifiable():
    lg = ligne(0, N.frais_dedouanement, "137.50", quantite="1", prix="12.50", q_methode=Methode.derive)
    rs = [r for r in _resultats([ft(lg, qualite=QualiteTexte.natif)], "D1") if r.sous_controle == "ligne"]
    assert rs and rs[0].outcome is Outcome.non_verifiable and rs[0].details["motif"] == "facteur_non_imprime"


def test_d1_confusion_sur_un_facteur_de_produit():
    # 7 × 72,00 lu pour 1 × 72,00 (7 et 1 de la même classe) : le facteur est remplacé, pas ajouté
    lg = LigneFactureTransitaire(
        nature=N.frais_dedouanement,
        libelle=v_ft("lignes[0].libelle", "Inklaring FICTIF"),
        montant_ht=v_ft("lignes[0].montant_ht", "72.00", conf=0.92, methode=Methode.ocr),
        quantite=v_ft("lignes[0].quantite", "7", conf=0.92, methode=Methode.ocr),
        prix_unitaire=v_ft("lignes[0].prix_unitaire", "72.00", conf=0.92, methode=Methode.ocr),
    )
    rs = [r for r in _resultats([ft(lg)], "D1") if r.sous_controle == "ligne"]
    assert rs and rs[0].constat is not None and RaisonCode.lecture_douteuse in rs[0].constat.raisons


def test_c4_aucune_ligne_de_tva_refacturee_non_verifiable():
    did = "doc_dec_c4"
    d = declaration(
        id=did,
        mrn=MRN_A,
        taxations=[
            taxation(did, montant="100.00"),
            taxation(did, type_taxe="B00", categorie=CategorieTaxe.tva, montant="220.00"),
        ],
    )
    f = ft(ligne(0, N.debours_droits, "100.00", mrn=MRN_A), qualite=QualiteTexte.natif)
    rs = _resultats([f, d], "C4")
    assert rs and all(r.constat is None for r in rs)
    assert any(r.details.get("motif") == "aucune_ligne_de_la_composante" for r in rs)


def _lib(i, texte, y, conf=0.88):
    return v_ft(
        f"lignes[{i}].libelle",
        texte,
        conf=conf,
        methode=Methode.ocr,
        zone=Zone(x0=0.1, y0=y, x1=0.5, y1=y + 0.01),
    )


def test_d5_deux_lectures_identiques_du_libelle_se_confirment():
    a, b = _lib(0, "Frais de dédouanement FICTIF", 0.40), _lib(1, "Frais de dédouanement FICTIF", 0.45)
    m = v_ft("lignes[0].montant_ht", "45.00", conf=0.92, methode=Methode.ocr)
    c = ctx([ft()])
    sortie = _libelles_concordants(c, [a, b], [a, m, b])
    assert [x.confiance for x in sortie] == [c.profil.c_min_certain, 0.92, c.profil.c_min_certain]


def test_d5_libelles_differents_ou_meme_endroit_non_confirmes():
    c = ctx([ft()])
    a, b = _lib(0, "Frais de dédouanement FICTIF", 0.40), _lib(1, "Frais de dedouanement FICTIF", 0.45)
    assert [x.confiance for x in _libelles_concordants(c, [a, b], [a, b])] == [0.88, 0.88]
    a2, b2 = _lib(0, "Frais de dédouanement FICTIF", 0.40), _lib(1, "Frais de dédouanement FICTIF", 0.40)
    assert [x.confiance for x in _libelles_concordants(c, [a2, b2], [a2, b2])] == [0.88, 0.88]


# --- D-2312 : liens faibles regroupés -----------------------------------------------------------------------------


def test_p4_plusieurs_liens_faibles_un_seul_constat():
    docs = [declaration(id="doc_d1", mrn=MRN_A), declaration(id="doc_d2", mrn=MRN_B), ft()]
    liens = [
        LienDocument(document_id=d.id, role=r, force=ForceLien.faible, signaux=[SignalLien.graine])
        for d, r in zip(
            docs, (RoleLien.declaration, RoleLien.declaration, RoleLien.facture_transitaire), strict=True
        )
    ]
    dos = Dossier(id="dos_p4", version=1, liens=liens)
    c = ControlContext.construire(dos, docs, ProfilTolerances(id="tol_test"), execution_id="exe_test")
    rs = [r for r in run_controls(c, controles=["P4"]) if r.controle_id == "P4"]
    constats = [r for r in rs if r.constat is not None]
    assert len(constats) == 1 and set(constats[0].constat.documents_concernes) == {d.id for d in docs}
    assert sum(r.raison_code is RaisonCode.couvert_par_autre_controle for r in rs) == 2
