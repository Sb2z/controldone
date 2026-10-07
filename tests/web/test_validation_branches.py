"""Couverture des décisions du fondateur et des corrections de valeurs (``services.validation``, bloc O4, D-4901),
sur la base de démonstration (vrai pipeline, données fictives) : motif obligatoire, double décision refusée,
rétrogradation impossible, écart ouvert une seule fois, composante inconnue, correction hors dossier, valeur
inconnue ou illisible, recontrôle idempotent."""

from __future__ import annotations

from decimal import Decimal

import pytest

from controldone.auth.roles import Acteur, Role
from controldone.model.documents import Document as DocumentModele
from controldone.model.enums import TypeValeur
from controldone.services import validation as val
from controldone.services.plateforme import RequeteInvalide
from controldone.storage import AccesRefuse
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import Constat, Document, Dossier, Ecart

A = "demo_ateliers"
FONDATEUR = Acteur("usr_fondateur_demo", Role.fondateur)
SYSTEME = Acteur.systeme("tests")


def _scope(op, motif="décision (test FICTIF)"):
    return op.client(A, motif)


def _propose(monde, niveau: str | None = None) -> str:
    with monde.pf.db.tenant(A, SYSTEME, lecture=True) as sc:
        for c in sc.lister(Constat, statut_validation="propose", ordre=Constat.id):
            if niveau is None or c.niveau == niveau:
                return c.id
    pytest.skip(f"aucun constat proposé {niveau or ''} dans la démonstration")


def test_rejet_motif_obligatoire_et_decision_unique(monde):
    cid = _propose(monde)
    with monde.pf.db.operateur(FONDATEUR) as op:
        sc = _scope(op)
        with pytest.raises(RequeteInvalide, match="motif"):
            val.rejeter(sc, cid, "  ")
        c = val.rejeter(sc, cid, "  doublon " + "x" * 2000)
        assert c.statut_validation == "rejete" and len(c.commentaire_validation) == 1000
        with pytest.raises(RequeteInvalide, match="déjà"):
            val.rejeter(sc, cid, "encore")
        with pytest.raises(RequeteInvalide, match="déjà"):
            val.valider(sc, cid)


def test_retrogradation(monde):
    with monde.pf.db.operateur(FONDATEUR) as op:
        sc = _scope(op)
        with pytest.raises(RequeteInvalide, match="motif"):
            val.retrograder(sc, "peu_importe", "")
    cid = _propose(monde, "a_verifier")
    with monde.pf.db.operateur(FONDATEUR) as op, pytest.raises(RequeteInvalide, match="écart certain"):
        val.retrograder(_scope(op), cid, "motif FICTIF")


def _constat_recouvrable(monde, **contenu) -> str:
    """Constat proposé rendu ``recouvrable`` de montant positif (contenu complété pour le test)."""
    cid = _propose(monde)
    with monde.pf.db.tenant(A, SYSTEME) as sc:
        c = sc.obtenir(Constat, cid)
        c.nature_montant, c.montant_en_jeu = "recouvrable", Decimal("42.00")
        c.contenu = {**(c.contenu or {}), **contenu}
    return cid


def test_ecart_ouvert_une_seule_fois_composante_inconnue(monde):
    cid = _constat_recouvrable(
        monde, composante="inconnue_fictive", documents_concernes=["doc_absent_fictif"]
    )
    with monde.pf.db.operateur(FONDATEUR) as op:
        sc = _scope(op)
        c = val.valider(sc, cid, "  ")
        assert c.commentaire_validation is None
        assert val.ouvrir_ecart(sc, c) is None  # déjà ouvert : idempotent
        (e,) = sc.lister(Ecart, constat_id=cid)
        assert e.contenu["composante"] == "prestation" and e.reste == Decimal("42.00")
        assert e.contenu["facture_transitaire_id"] is None


def test_pas_d_ecart_sans_montant_recouvrable(monde):
    cid = _propose(monde)
    with monde.pf.db.tenant(A, SYSTEME) as sc:
        c = sc.obtenir(Constat, cid)
        c.nature_montant, c.montant_en_jeu = "recouvrable", Decimal("-3.00")
    with monde.pf.db.operateur(FONDATEUR) as op:
        sc = _scope(op)
        val.valider(sc, cid)
        assert sc.lister(Ecart, constat_id=cid) == []


# --- corrections de valeurs ------------------------------------------------------------------------------------------


def _valeur(monde, type_valeur: TypeValeur | None = None):
    """(dossier, document, valeur) d'une valeur extraite d'un document rattaché à un dossier."""
    with monde.pf.db.tenant(A, SYSTEME, lecture=True) as sc:
        for d in sc.lister(Dossier, ordre=Dossier.id):
            for lien in (d.contenu or {}).get("liens", []):
                doc = DocumentModele.model_validate(sc.obtenir(Document, lien["document_id"]).contenu)
                for v in doc.valeurs():
                    if type_valeur is None or v.type is type_valeur:
                        return d.id, doc.id, v.id
    pytest.skip("aucune valeur extraite dans la démonstration")


@pytest.mark.parametrize(
    "nouvelle, motif, attendu",
    [("1", " ", "motif"), ("", "motif FICTIF", "vide"), ("9" * 301, "motif FICTIF", "trop longue")],
)
def test_correction_saisie_refusee(monde, nouvelle, motif, attendu):
    dos, doc, v = _valeur(monde)
    with monde.pf.db.operateur(FONDATEUR) as op, pytest.raises(RequeteInvalide, match=attendu):
        val.corriger_valeur(_scope(op), dos, doc, v, nouvelle, motif)


def test_correction_document_hors_dossier_ou_valeur_inconnue(monde):
    dos, doc, v = _valeur(monde)
    with monde.pf.db.tenant(A, SYSTEME, lecture=True) as sc:
        autre = next(d.id for d in sc.lister(Document) if d.dossier_id != dos)
    with monde.pf.db.operateur(FONDATEUR) as op:
        sc = _scope(op)
        with pytest.raises(AccesRefuse):
            val.corriger_valeur(sc, dos, autre, v, "1", "motif FICTIF")
        with pytest.raises(AccesRefuse):
            val.corriger_valeur(sc, dos, doc, "val_inconnue_fictive", "1", "motif FICTIF")


def test_correction_valeur_illisible(monde):
    dos, doc, v = _valeur(monde, TypeValeur.montant)
    with monde.pf.db.operateur(FONDATEUR) as op, pytest.raises(RequeteInvalide, match="illisible"):
        val.corriger_valeur(_scope(op), dos, doc, v, "pas un montant", "motif FICTIF")


def test_correction_puis_recontrole_idempotent(monde):
    dos, doc, v = _valeur(monde, TypeValeur.montant)
    with monde.pf.db.operateur(FONDATEUR) as op:
        version = val.corriger_valeur(_scope(op), dos, doc, v, "1 234,56", "relu sur la pièce FICTIVE")
    store = JobStore(monde.pf.db)
    avant = store.compter(statut="pending")
    jid = val.mettre_en_file_recontrole(monde.pf, A, dos, version)  # déjà en file : même tâche
    assert store.compter(statut="pending") == avant and jid
    assert val.cle_recontrole(A, dos, version) == f"recontroler_dossier:{A}:{dos}:v{version}"
