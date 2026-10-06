"""Bloc moteur M3 (D-4201 à D-4210) : A13 regroupé, C5 sous-facturation expliquée, P1 et P4 portés une fois par
lot, A2 et références lues par OCR, F3 lien établi par le MRN, statut du dossier. Données fictives."""

from decimal import Decimal as D

from controldone.controls import famille_a as fa
from controldone.controls import famille_p as fp
from controldone.controls.context import AutreDossier, ControlContext
from controldone.controls.framework import run_controls
from controldone.findings_io import statut_global_depuis_resultats
from controldone.guardrails import PHRASE_RENVOI, check_text
from controldone.model import (
    Allocation,
    ArticleDeclaration,
    CategorieTaxe,
    ChampsDeclaration,
    ChampsFactureCommerciale,
    DocumentReference,
    ForceLien,
    LienDocument,
    LigneFactureCommerciale,
    LigneFactureTransitaire,
    MethodeAllocation,
    NatureLigne,
    Niveau,
    Outcome,
    PaiementNormalise,
    Partie,
    ProfilTolerances,
    RaisonCode,
    RoleLien,
    SignalLien,
    StatutGlobal,
    TypeDocument,
)
from controldone.normalize.refs import ref_compatibles_ocr, ref_facture_proches
from controldone.testing import (
    contexte,
    declaration,
    document,
    dossier_pour,
    facture_transitaire,
    taxation,
    vs,
)

TVA_CLIENT = "FR32000123459"


def ligne(fid, nature, montant, *, mrn=None, methode="texte_natif", confiance=0.99):
    def v(nom, val):
        return (
            None
            if val is None
            else vs(
                f"facture_transitaire.lignes[].{nom}",
                val,
                document_id=fid,
                methode=methode,
                confiance=confiance,
            )
        )

    return LigneFactureTransitaire(
        libelle=v("libelle", nature.value),
        nature=nature,
        montant_ht=v("montant_ht", montant),
        mrn=v("mrn", mrn),
    )


def ft(fid, *lignes, **kw):
    return facture_transitaire(
        id=fid,
        numero=vs("facture_transitaire.numero", "FT-FICTIF-001", document_id=fid),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", "26FR00000000000001", document_id=fid)],
        client_facture=Partie(tva=vs("facture_transitaire.client_facture.tva", TVA_CLIENT, document_id=fid)),
        lignes=list(lignes),
        **kw,
    )


def dec(did, *taxes):
    tx = [
        taxation(
            did,
            categorie=cat,
            type_taxe={CategorieTaxe.droit: "A00", CategorieTaxe.tva: "B00"}[cat],
            montant=m,
            paiement=PaiementNormalise.comptant,
        )
        for cat, m in taxes
    ]
    return declaration(
        id=did,
        mrn="26FR00000000000001",
        taxations=tx,
        importateur=Partie(tva=vs("declaration.importateur.tva", TVA_CLIENT, document_id=did)),
    )


# --- A13 : un seul constat par dossier (D-4201) ----------------------------------------------------------------


def _fc(fid, numero, *codes):
    lignes = [
        LigneFactureCommerciale(
            code_marchandise_imprime=vs(
                "facture_commerciale.lignes[].code_marchandise_imprime", c, document_id=fid
            )
        )
        for c in codes
    ]
    return document(
        TypeDocument.facture_commerciale,
        ChampsFactureCommerciale(
            numero=vs("facture_commerciale.numero", numero, document_id=fid),
            devise=vs("facture_commerciale.devise", "EUR", document_id=fid),
            total_facture=vs("facture_commerciale.total_facture", "100.00", document_id=fid),
            lignes=lignes,
        ),
        id=fid,
    )


def _dec(did, mrn, *codes):
    arts = [
        ArticleDeclaration(
            numero_article=vs("declaration.articles[].numero_article", str(i + 1), document_id=did),
            code_marchandise=vs("declaration.articles[].code_marchandise", c, document_id=did),
        )
        for i, c in enumerate(codes)
    ]
    return document(
        TypeDocument.declaration,
        ChampsDeclaration(mrn=vs("declaration.mrn", mrn, document_id=did), articles=arts),
        id=did,
    )


def test_a13_un_constat_par_dossier_tous_les_couples():
    f1, f2 = _fc("doc_fc1", "INV-FICTIF-1", "8471300000"), _fc("doc_fc2", "INV-FICTIF-2", "9401710000")
    d1 = _dec("doc_dec1", "26FRK7Q2ZX9PLM3VB2", "8517620000")
    d2 = _dec("doc_dec2", "26FRW3H8JN5TQ4CX7M", "9401710000", "7318159590")
    allocs = [
        Allocation(
            id="alc_1",
            source_document_id="doc_fc1",
            cible_document_id="doc_dec1",
            methode=MethodeAllocation.reference_explicite,
        ),
        Allocation(
            id="alc_2",
            source_document_id="doc_fc2",
            cible_document_id="doc_dec2",
            methode=MethodeAllocation.reference_explicite,
        ),
    ]
    docs = [f1, f2, d1, d2]
    dossier = dossier_pour(docs).model_copy(update={"allocations": allocs})
    ctx = ControlContext.construire(dossier, docs, ProfilTolerances(id="tol_test"))
    assert len(fa.couples(ctx)) == 2
    rs = fa.a13_codes_marchandise(ctx)
    constats = [r for r in rs if r.constat is not None]
    assert len(constats) == 1
    c = constats[0].constat
    assert c.niveau is Niveau.a_verifier and c.renvoi and c.montant_en_jeu is None
    assert c.libelle.startswith("Codes marchandise à rapprocher manuellement : ")
    assert PHRASE_RENVOI in c.libelle and check_text(c.libelle) == []
    for code in ("8471300000", "8517620000", "7318159590"):
        assert code in c.libelle
    assert set(c.documents_concernes) == {"doc_fc1", "doc_fc2", "doc_dec1", "doc_dec2"}
    d = constats[0].details
    assert d["sh6_declaration_seuls"] == ["731815", "851762"] and d["a_sens_unique"] is False
    assert [x["croise"] for x in d["couples"]] == [True, False]


def test_a13_sens_unique_signale_a_verifier():
    r = [
        x
        for x in fa.a13_codes_marchandise(
            contexte(
                [
                    _fc("doc_fc1", "INV-FICTIF-1", "8471300000"),
                    _dec("doc_dec1", "26FRK7Q2ZX9PLM3VB2", "8471300000", "9401710000"),
                ]
            )
        )
        if x.constat is not None
    ]
    assert len(r) == 1 and r[0].details["a_sens_unique"] is True and r[0].outcome is Outcome.a_verifier


# --- C5 : écart en faveur du client qu'une lecture explique (D-4205) ------------------------------------------


def _c5(docs):
    return next(
        r
        for r in run_controls(contexte(docs), controles=["C1", "C2", "C3", "C4", "C5"])
        if r.controle_id == "C5"
    )


def test_c5_tva_non_refacturee_non_verifiable():
    f = ft("doc_ft1", ligne("doc_ft1", NatureLigne.debours_droits, "100.00", mrn="26FR00000000000001"))
    d = dec("doc_dec1", (CategorieTaxe.droit, "100.00"), (CategorieTaxe.tva, "50.00"))
    r = _c5([f, d])
    assert r.outcome is Outcome.non_verifiable and r.details["motif"] == "tva_non_refacturee"


def test_c5_debours_possiblement_non_lus():
    f = ft(
        "doc_ft1",
        ligne(
            "doc_ft1",
            NatureLigne.debours_droits,
            "100.00",
            mrn="26FR00000000000001",
            methode="ocr",
            confiance=0.7,
        ),
    )
    d = dec("doc_dec1", (CategorieTaxe.droit, "130.00"))
    r = _c5([f, d])
    assert r.outcome is Outcome.non_verifiable and r.details["motif"] == "debours_possiblement_non_lus"


def test_c5_debours_prouves_complets_reste_a_verifier():
    f = ft(
        "doc_ft1",
        ligne(
            "doc_ft1",
            NatureLigne.debours_droits,
            "100.00",
            mrn="26FR00000000000001",
            methode="ocr",
            confiance=0.7,
        ),
        total_debours=vs("facture_transitaire.total_debours", "100.00", document_id="doc_ft1"),
    )
    d = dec("doc_dec1", (CategorieTaxe.droit, "130.00"))
    r = _c5([f, d])
    assert r.outcome is Outcome.a_verifier and RaisonCode.ecart_en_faveur_client in r.constat.raisons


def test_c5_surfacturation_jamais_concernee():
    f = ft(
        "doc_ft1",
        ligne(
            "doc_ft1",
            NatureLigne.debours_droits,
            "160.00",
            mrn="26FR00000000000001",
            methode="ocr",
            confiance=0.7,
        ),
    )
    d = dec("doc_dec1", (CategorieTaxe.droit, "130.00"))
    assert _c5([f, d]).outcome is Outcome.a_verifier


# --- P1 et P4 : portés une fois par lot (D-4206, D-4210) ------------------------------------------------------


def _fc_simple(fid):
    return document(
        TypeDocument.facture_commerciale,
        ChampsFactureCommerciale(numero=vs("facture_commerciale.numero", fid.upper(), document_id=fid)),
        id=fid,
    )


def _ctx_lot(docs_ici, autres, *, lot="lot_1", dossier_id="dos_b", force=ForceLien.forte):
    dossier = dossier_pour(docs_ici, force=force).model_copy(update={"id": dossier_id, "lot_ids": [lot]})
    return ControlContext.construire(
        dossier, docs_ici, ProfilTolerances(id="tol_test"), autres_dossiers=autres
    )


def _autre(docs, dossier_id, lot="lot_1", force=ForceLien.forte):
    d = dossier_pour(docs, force=force).model_copy(update={"id": dossier_id, "lot_ids": [lot]})
    return AutreDossier(dossier=d, documents={x.id: x for x in docs})


def test_p1_manque_commun_du_lot_porte_une_fois():
    f_a, f_b = _fc_simple("doc_fca"), _fc_simple("doc_fcb")
    autres = [_autre([f_a], "dos_a")]
    # dos_b n'est pas le premier dossier du lot : renvoi, mais le dossier reste incomplet
    r = fp.p1_completude(_ctx_lot([f_b], autres))[0]
    assert r.outcome is Outcome.non_applicable and r.details["dossier"] == "dos_a"
    assert statut_global_depuis_resultats([r]) is StatutGlobal.document_manquant
    # dos_a porte le constat, cite les documents des deux dossiers et dit que le manque est commun
    r = fp.p1_completude(_ctx_lot([f_a], [_autre([f_b], "dos_b")], dossier_id="dos_a"))[0]
    assert r.outcome is Outcome.a_verifier and set(r.constat.documents_concernes) == {"doc_fca", "doc_fcb"}
    assert "même manque pour 1 autre dossier du lot" in r.constat.libelle
    assert check_text(r.constat.libelle) == []


def test_p1_type_present_ailleurs_dans_le_lot_reste_signale():
    f_b = _fc_simple("doc_fcb")
    d_a = _dec("doc_deca", "26FRK7Q2ZX9PLM3VB2", "8471300000")
    r = fp.p1_completude(_ctx_lot([f_b], [_autre([_fc_simple("doc_fca"), d_a], "dos_a")]))[0]
    assert r.outcome is Outcome.a_verifier  # défaut d'appariement : chaque dossier le signale


def test_p1_autre_lot_ignore():
    f_b = _fc_simple("doc_fcb")
    r = fp.p1_completude(_ctx_lot([f_b], [_autre([_fc_simple("doc_fca")], "dos_a", lot="lot_2")]))[0]
    assert r.outcome is Outcome.a_verifier and "même manque" not in r.constat.libelle


def test_p4_lien_faible_partage_porte_une_fois():
    f_b, f_a = _fc_simple("doc_fcb"), _fc_simple("doc_fca")
    av = document(TypeDocument.avoir, None, id="doc_av")
    lien_faible = LienDocument(
        document_id="doc_av",
        role=RoleLien.avoir,
        force=ForceLien.faible,
        signaux=[SignalLien.meme_fichier_source],
    )
    dos_a = dossier_pour([f_a], force=ForceLien.forte).model_copy(
        update={"id": "dos_a", "lot_ids": ["lot_1"]}
    )
    dos_a.liens.append(lien_faible)
    autres = [AutreDossier(dossier=dos_a, documents={"doc_fca": f_a, "doc_av": av})]
    dos_b = dossier_pour([f_b], force=ForceLien.forte).model_copy(
        update={"id": "dos_b", "lot_ids": ["lot_1"]}
    )
    dos_b.liens.append(lien_faible.model_copy())
    ctx = ControlContext.construire(dos_b, [f_b, av], ProfilTolerances(id="tol_test"), autres_dossiers=autres)
    par = {r.documents_concernes[0]: r for r in fp.p4_rattachement_faible(ctx)}
    assert par["doc_av"].outcome is Outcome.non_applicable and par["doc_av"].details["dossier"] == "dos_a"
    # le premier dossier du lot porte le constat
    ctx_a = ControlContext.construire(
        dos_a,
        [f_a, av],
        ProfilTolerances(id="tol_test"),
        autres_dossiers=[AutreDossier(dossier=dos_b, documents={"doc_fcb": f_b, "doc_av": av})],
    )
    par = {r.documents_concernes[0]: r for r in fp.p4_rattachement_faible(ctx_a)}
    assert par["doc_av"].outcome is Outcome.a_verifier


# --- A2 et références lues par OCR (D-4207) -------------------------------------------------------------------


def test_references_facture_ocr():
    assert ref_compatibles_ocr("OMS001011", "0MS001011") and ref_compatibles_ocr("GI-26-0592", "G1-26-0592")
    assert ref_compatibles_ocr("FT PIC2026/3215", "1C20263215")  # troncature lue par OCR
    assert not ref_compatibles_ocr("INV-2026-00042", "INV-2026-00043")
    assert ref_facture_proches("NIH-2026-06934", "NIH-2026-06933")
    assert not ref_facture_proches("INV-2826-88690", "INV-2026-00690")  # quatre caractères d'écart
    assert not ref_facture_proches("INV-1", "INV-2")  # trop court


def _a2(numero, cite, *, methode="ocr"):
    fc = document(
        TypeDocument.facture_commerciale,
        ChampsFactureCommerciale(numero=vs("facture_commerciale.numero", numero, document_id="doc_fc1")),
        id="doc_fc1",
    )
    d = document(
        TypeDocument.declaration,
        ChampsDeclaration(
            mrn=vs("declaration.mrn", "26FRK7Q2ZX9PLM3VB2", document_id="doc_dec1"),
            documents_references=[
                DocumentReference(
                    type_code=vs(
                        "declaration.documents_references[].type_code", "N380", document_id="doc_dec1"
                    ),
                    reference=vs(
                        "declaration.documents_references[].reference",
                        cite,
                        document_id="doc_dec1",
                        methode=methode,
                        confiance=0.95,
                    ),
                )
            ],
        ),
        id="doc_dec1",
    )
    return fa.a2_reference_facture(contexte([fc, d]))[0]


def test_a2_reference_lue_par_ocr():
    assert _a2("OMS001011", "0MS001011").outcome is Outcome.conforme
    r = _a2("NIH-2026-06934", "NIH-2026-06933")
    assert r.outcome is Outcome.non_verifiable and r.details["motif"] == "reference_proche"
    # texte natif des deux côtés : un caractère d'écart reste un constat
    assert _a2("NIH-2026-06934", "NIH-2026-06933", methode="texte_natif").outcome is Outcome.a_verifier
    assert _a2("INV-2026-00042", "RE-2026-8722").outcome is Outcome.a_verifier


# --- F3 : lien établi par le MRN (D-4209) ---------------------------------------------------------------------


def test_classify_liens_etablis():
    f = ft("doc_ft1", ligne("doc_ft1", NatureLigne.debours_droits, "100.00"))
    ctx = contexte([f], force=ForceLien.faible)
    v = f.ft.lignes[0].montant_ht
    kw = dict(ecart=D("100"), tolerance=None, seuil_certitude=D("1"), valeurs_cles=[v], montant=D("100"))
    assert RaisonCode.rattachement_faible in ctx.classify("F3", **kw).raisons
    assert ctx.classify("F3", **kw, liens_etablis=["doc_ft1"]).niveau is Niveau.ecart_certain
