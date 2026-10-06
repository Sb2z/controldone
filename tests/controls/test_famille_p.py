"""Famille P — préalables (SPEC §9). Données fictives."""

from controldone.controls import famille_p as fp
from controldone.controls.context import ControlContext
from controldone.controls.framework import run_controls
from controldone.findings_io import statut_global_depuis_resultats
from controldone.guardrails import check_text
from controldone.model import (
    ChampsDeclaration,
    ChampsFactureCommerciale,
    Dossier,
    Entite,
    ForceLien,
    LienDocument,
    MotifNonExploitable,
    NatureMontant,
    Outcome,
    Partie,
    ProfilTolerances,
    RaisonCode,
    RoleLien,
    SignalLien,
    StatutGlobal,
    TypeDocument,
)
from controldone.normalize.fiscal import tva_fr_depuis_siren
from controldone.testing import contexte, document, facture_transitaire, vs

FC, DEC = "doc_fc1", "doc_dec1"
SIREN_A = "123456782"
TVA_A = tva_fr_depuis_siren(SIREN_A)
TVA_AUTRE = tva_fr_depuis_siren("999000001")  # entité fictive hors client
ENTITES = [
    Entite(id="ent_a", raison_sociale="ALPHA IMPORT FICTIF", tva=TVA_A, siren=SIREN_A, alias=["Alpha Import"])
]


def facture(id=FC, *, tva=TVA_A, confiance=0.99, nom=None, **champs):
    c = ChampsFactureCommerciale(
        numero=vs("facture_commerciale.numero", "INV-1", document_id=id),
        devise=vs("facture_commerciale.devise", "USD", document_id=id),
        total_facture=vs("facture_commerciale.total_facture", "100.00", document_id=id),
        acheteur=Partie(
            tva=vs("facture_commerciale.acheteur.tva", tva, document_id=id, confiance=confiance)
            if tva
            else None,
            nom=vs("facture_commerciale.acheteur.nom", nom, document_id=id) if nom else None,
        ),
        **champs,
    )
    return document(TypeDocument.facture_commerciale, c, id=id)


def declaration(id=DEC, *, tva=TVA_A, devise="USD", taux="0.92", **champs):
    c = ChampsDeclaration(
        mrn=vs("declaration.mrn", "26FR00000000000001", document_id=id),
        importateur=Partie(tva=vs("declaration.importateur.tva", tva, document_id=id) if tva else None),
        devise_facture=vs("declaration.devise_facture", devise, document_id=id) if devise else None,
        montant_total_facture=vs("declaration.montant_total_facture", "100.00", document_id=id),
        taux_change=vs("declaration.taux_change", taux, document_id=id) if taux else None,
        **champs,
    )
    return document(TypeDocument.declaration, c, id=id)


def non_exploitable(id="doc_ne", motif=MotifNonExploitable.pre_alerte):
    return document(
        TypeDocument.document_non_exploitable, None, id=id, motif_non_exploitable=motif, pages=(1, 2)
    )


def un(fn, ctx):
    rs = fn(ctx)
    assert len(rs) == 1
    return rs[0]


def constat_propre(r):
    c = r.constat
    assert c is not None and c.niveau.value == "a_verifier"
    assert c.montant_en_jeu is None and c.nature_montant is NatureMontant.aucun
    assert check_text(c.libelle) == [] and check_text(c.prochaine_action) == []
    assert c.raisons
    return c


# --- P1 -------------------------------------------------------------------------------------------------


def test_p1_conforme_et_facture_transitaire_absente():
    r = un(fp.p1_completude, contexte([facture(), declaration()]))
    assert r.outcome is Outcome.conforme and r.details["facture_transitaire_absente"] is True
    ft = facture_transitaire(id="doc_ft", numero=vs("facture_transitaire.numero", "T1", document_id="doc_ft"))
    r = un(fp.p1_completude, contexte([facture(), declaration(), ft]))
    assert r.details["facture_transitaire_absente"] is False


def test_p1_declaration_manquante():
    r = un(fp.p1_completude, contexte([facture()]))
    assert r.outcome is Outcome.a_verifier
    c = constat_propre(r)
    assert c.raisons == [RaisonCode.document_manquant] and r.attendu == "declaration"
    assert "déclaration" in c.libelle
    assert statut_global_depuis_resultats([r]) is StatutGlobal.document_manquant


def test_p1_facture_presente_mais_non_exploitable():
    r = un(fp.p1_completude, contexte([non_exploitable(), declaration()]))
    c = constat_propre(r)
    assert set(c.raisons) == {RaisonCode.document_manquant, RaisonCode.document_non_exploitable}
    assert "présente mais non exploitable : pré-alerte" in c.libelle
    assert c.preuves[0].document_id == "doc_ne" and c.preuves[0].valeur_brute == "pre_alerte"
    assert r.details["documents_manquants"] == ["facture_commerciale"]


def test_p1_les_deux_manquent():
    r = un(fp.p1_completude, contexte([non_exploitable(motif=MotifNonExploitable.devis)]))
    assert r.attendu == "facture_commerciale,declaration" and "devis" in r.constat.libelle


# --- P2 -------------------------------------------------------------------------------------------------


def test_p2():
    rs = fp.p2_document_non_exploitable(contexte([facture(), non_exploitable()]))
    par = {r.documents_concernes[0]: r for r in rs}
    assert par[FC].outcome is Outcome.conforme
    r = par["doc_ne"]
    assert r.outcome is Outcome.a_verifier and r.details["motif"] == "pre_alerte"
    c = constat_propre(r)
    assert c.raisons == [RaisonCode.document_non_exploitable]
    assert "« pré-alerte »" in c.libelle and "pages 1 à 2" in c.libelle


def test_p2_libelles_de_motif():
    assert set(fp.LIBELLES_MOTIF) == set(MotifNonExploitable)
    for t in fp.LIBELLES_MOTIF.values():
        assert check_text(t) == []


# --- P3 -------------------------------------------------------------------------------------------------


def test_p3_champs_cles_illisibles():
    f = facture(tva=None, confiance=0.3)
    d = declaration(taux=None)  # devise USD : le taux est un champ clé
    rs = fp.p3_champ_cle_illisible(contexte([f, d]))
    champs = {(r.documents_concernes[0], r.details["champ"]): r for r in rs}
    assert all(r.outcome is Outcome.non_verifiable and r.constat is None for r in rs)
    assert champs[(FC, "acheteur.tva")].raison_code is RaisonCode.valeur_absente
    assert (DEC, "taux_change") in champs
    assert len(rs) == 2


def test_p3_confiance_et_taux_inutile_en_eur():
    f = facture(confiance=0.4)
    rs = fp.p3_champ_cle_illisible(contexte([f, declaration(devise="EUR", taux=None)]))
    assert [(r.details["champ"], r.raison_code) for r in rs] == [
        ("acheteur.tva", RaisonCode.confiance_insuffisante)
    ]
    assert fp.champs_cles_illisibles(contexte([facture()]), facture()) == []


# --- P4 -------------------------------------------------------------------------------------------------


def test_p4_rattachement_faible():
    docs = [facture(), declaration()]
    dossier = Dossier(
        id="dos_test",
        liens=[
            LienDocument(
                document_id=FC,
                role=RoleLien.facture_commerciale,
                force=ForceLien.forte,
                signaux=[SignalLien.graine],
            ),
            LienDocument(
                document_id=DEC,
                role=RoleLien.declaration,
                force=ForceLien.faible,
                signaux=[SignalLien.montant_egal, SignalLien.nom_fichier],
            ),
        ],
    )
    ctx = ControlContext.construire(dossier, docs, ProfilTolerances(id="tol_test"))
    par = {r.documents_concernes[0]: r for r in fp.p4_rattachement_faible(ctx)}
    assert par[FC].outcome is Outcome.conforme
    r = par[DEC]
    assert r.outcome is Outcome.a_verifier and r.details["signaux"] == ["montant_egal", "nom_fichier"]
    c = constat_propre(r)
    assert c.raisons == [RaisonCode.rattachement_faible]
    assert "montant égal, nom de fichier" in c.libelle


def test_p4_moyenne_pas_de_constat():
    rs = fp.p4_rattachement_faible(contexte([facture(), declaration()], force=ForceLien.moyenne))
    assert all(r.outcome is Outcome.conforme for r in rs)


# --- P5 -------------------------------------------------------------------------------------------------


def test_p5_non_concerne_arrete_le_moteur():
    ctx = contexte([facture(tva=TVA_AUTRE), declaration(tva=TVA_AUTRE)], entites=ENTITES)
    r = un(fp.p5_dossier_non_concerne, ctx)
    assert r.outcome is Outcome.non_applicable and r.raison_code is RaisonCode.dossier_non_concerne
    assert r.details["non_concerne"] is True and r.constat is None
    rs = run_controls(ctx)
    assert rs[-1].controle_id == "P5" and not any(x.controle_id.startswith("A") for x in rs)
    assert statut_global_depuis_resultats(rs) is StatutGlobal.non_concerne


def test_p5_concerne():
    cas = [
        ([facture(), declaration()], ENTITES),  # tout est au client
        ([facture(tva=TVA_AUTRE, confiance=0.85), declaration(tva=TVA_AUTRE)], ENTITES),  # lecture < 0,90
        ([facture(tva=TVA_AUTRE), declaration(tva=TVA_A)], ENTITES),  # TVA client déclarée
        (
            [facture(tva=TVA_AUTRE, nom="Alpha Import"), declaration(tva=TVA_AUTRE)],
            ENTITES,
        ),  # alias du client
        ([facture(tva=TVA_AUTRE), declaration(tva=None)], ENTITES),  # importateur illisible
    ]
    for docs, entites in cas:
        r = un(fp.p5_dossier_non_concerne, contexte(docs, entites=entites))
        assert r.outcome is Outcome.conforme and not r.details.get("non_concerne")


def test_p5_non_verifiable():
    r = un(fp.p5_dossier_non_concerne, contexte([facture(), declaration()]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.valeur_absente
    r = un(fp.p5_dossier_non_concerne, contexte([facture()], entites=ENTITES))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.document_manquant


# --- identification des entités -----------------------------------------------------------------------------


def test_identification():
    ctx = contexte([facture(), declaration()], entites=ENTITES)
    assert fp.identifier_partie(ctx, Partie(tva=vs("x.tva", TVA_A))).methode == "tva"
    assert fp.identifier_partie(ctx, Partie(tva=vs("x.tva", "FR99" + SIREN_A))).methode == "siren"
    assert fp.identifier_partie(ctx, Partie(siren=vs("x.siren", "123 456 782"))).methode == "siren"
    i = fp.identifier_partie(ctx, Partie(nom=vs("x.nom", "ALPHA IMPORT SARL")))
    assert i.methode == "alias" and i.entite.id == "ent_a"
    i = fp.identifier_partie(ctx, Partie(tva=vs("x.tva", TVA_AUTRE)))
    assert i.entite is None and i.tva_hors_client is not None


# --- garde-fous -------------------------------------------------------------------------------------------


def test_p_jamais_certain_ni_montant():
    ctx = contexte([non_exploitable(), facture(tva=None)], force=ForceLien.faible, entites=ENTITES)
    rs = run_controls(ctx, controles=["P1", "P2", "P3", "P4", "P5"])
    constats = [r.constat for r in rs if r.constat is not None]
    assert {c.controle_id for c in constats} == {"P1", "P2", "P4"}
    for c in constats:
        assert c.niveau.value == "a_verifier" and c.montant_en_jeu is None and c.motif_blocage is None
    for gabarit in (fp.ACTION_P1, fp.ACTION_P2, fp.ACTION_P4):
        assert check_text(gabarit) == []


# --- Mise au point du rappel (D-801, D-802) -------------------------------------------------------------


def test_p1_cite_les_documents_presents():
    """Le constat P1 cite le document resté sans contrepartie (et le non exploitable qui tient lieu de facture)."""
    r = un(fp.p1_completude, contexte([facture()]))
    assert r.constat.documents_concernes == [FC]
    r = un(fp.p1_completude, contexte([declaration()]))
    assert r.constat.documents_concernes == [DEC]
    r = un(fp.p1_completude, contexte([non_exploitable(), declaration()]))
    assert set(r.constat.documents_concernes) == {DEC, "doc_ne"}


def test_p4_copie_doublon_sans_constat():
    """La copie d'un fichier déjà reçu (doublon_de) suit le lien de l'original : pas de second P4."""
    copie = facture(id="doc_fc_copie").model_copy(update={"doublon_de": FC})
    docs = [facture(), copie, declaration()]
    dossier = Dossier(
        id="dos_test",
        liens=[
            LienDocument(
                document_id=FC,
                role=RoleLien.facture_commerciale,
                force=ForceLien.faible,
                signaux=[SignalLien.meme_dossier_source],
            ),
            LienDocument(
                document_id="doc_fc_copie",
                role=RoleLien.facture_commerciale,
                force=ForceLien.faible,
                signaux=[SignalLien.meme_dossier_source],
            ),
            LienDocument(
                document_id=DEC, role=RoleLien.declaration, force=ForceLien.forte, signaux=[SignalLien.graine]
            ),
        ],
    )
    ctx = ControlContext.construire(dossier, docs, ProfilTolerances(id="tol_test"))
    par = {r.documents_concernes[0]: r for r in fp.p4_rattachement_faible(ctx)}
    assert par[FC].outcome is Outcome.a_verifier
    assert par["doc_fc_copie"].outcome is Outcome.non_applicable
    assert par["doc_fc_copie"].raison_code is RaisonCode.couvert_par_autre_controle
