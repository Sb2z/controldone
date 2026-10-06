"""File de validation des actions sortantes : brouillon -> approuvé/corrigé/refusé -> envoyé."""

from __future__ import annotations

import json

import pytest
from aides_plateforme import FONDATEUR, SYSTEME

from controldone.outbox import (
    ActionBloquee,
    ExpediteurFichier,
    FileSortante,
    ModeAutonomie,
    StatutAction,
    TransitionInterdite,
    TypeAction,
)
from controldone.storage import AccesRefuse, verifier_chaine
from controldone.storage.models import AuditLog

PROPRE = {"objet": "Rapport de diagnostic disponible", "corps": "Votre rapport (FICTIF) est disponible.",
          "destinataires": ["compta@client-fictif.test"]}
INTERDIT = {"objet": "Réclamation", "corps": "Le transitaire vous a facturé un droit dû illégal."}


@pytest.fixture
def file(monde):
    return FileSortante(monde.db)


@pytest.fixture
def expediteur(tmp_path):
    return ExpediteurFichier(tmp_path / "outbox_envoyee")


def _audits(monde, prefixe="outbox_"):
    with monde.db.transaction_systeme() as s:
        return [e.action for e in s.query(AuditLog).order_by(AuditLog.id) if e.action.startswith(prefixe)]


def test_tous_les_types_en_manuel_par_defaut(file):
    assert {file.autonomie(k) for k in TypeAction} == {ModeAutonomie.manuel}


def test_cycle_complet_approbation_et_envoi(monde, file, expediteur):
    a = file.proposer(TypeAction.rapport_publication, PROPRE, SYSTEME, tenant_id="cli_a")
    assert a.statut is StatutAction.brouillon and a.tenant_id == "cli_a" and not a.auto
    assert not expediteur.racine.exists()  # rien n'est écrit avant approbation et envoi
    with pytest.raises(TransitionInterdite):
        file.envoyer(a.id, expediteur, FONDATEUR)  # pas d'envoi d'un brouillon
    a = file.approuver(a.id, FONDATEUR)
    assert a.statut is StatutAction.approuve and a.decide_par == FONDATEUR.id
    with pytest.raises(TransitionInterdite):
        file.approuver(a.id, FONDATEUR)
    a = file.envoyer(a.id, expediteur, FONDATEUR)
    assert a.statut is StatutAction.envoye and a.reference_envoi.startswith("fichier:")
    fichiers = list(expediteur.racine.glob("rapport_publication/*"))
    assert len(fichiers) == 1 and fichiers[0].name.endswith(".json.enc")  # chiffrée au repos (D-4106)
    assert b"Rapport de diagnostic" not in fichiers[0].read_bytes()
    assert json.loads(expediteur.traces.lire(fichiers[0]))["payload"] == PROPRE
    with pytest.raises(TransitionInterdite):
        file.envoyer(a.id, expediteur, FONDATEUR)  # pas de double envoi
    assert _audits(monde) == ["outbox_proposer", "outbox_approuver", "outbox_envoyer"]
    with monde.db.transaction_systeme() as s:
        assert verifier_chaine(s) == []


def test_garde_fous_bloquent_l_approbation(monde, file):
    a = file.proposer(TypeAction.reclamation_dossier, INTERDIT, SYSTEME, tenant_id="cli_a")
    assert a.statut is StatutAction.brouillon and "droit dû" in a.motif_blocage
    with pytest.raises(ActionBloquee) as exc:
        file.approuver(a.id, FONDATEUR)
    assert any("illégal" in m for m in exc.value.motifs)
    a = file.obtenir(a.id, FONDATEUR)
    assert a.statut is StatutAction.brouillon and a.motif_blocage
    assert "outbox_bloque" in _audits(monde)


def test_correction_passe_les_garde_fous(monde, file, expediteur):
    a = file.proposer(TypeAction.reclamation_dossier, INTERDIT, SYSTEME, tenant_id="cli_a")
    with pytest.raises(ActionBloquee):
        file.corriger(a.id, FONDATEUR, {"objet": "Demande d'avoir", "corps": "Ce texte reste un droit dû."})
    corrige = {"objet": "Demande d'avoir", "corps": "Le montant refacturé diffère du montant liquidé indiqué."}
    a = file.corriger(a.id, FONDATEUR, corrige)
    assert a.statut is StatutAction.corrige and a.payload == INTERDIT and a.payload_corrige == corrige
    assert a.motif_blocage is None
    a = file.envoyer(a.id, expediteur, FONDATEUR)
    envoye = json.loads(expediteur.traces.lire(next(expediteur.racine.glob("**/*.json.enc"))))
    assert envoye["payload"] == corrige and envoye["corrige"] is True


def test_refus_avec_motif_obligatoire(monde, file, expediteur):
    a = file.proposer(TypeAction.post_linkedin, {"corps": "Publication FICTIVE"}, FONDATEUR)
    assert a.tenant_id is None
    with pytest.raises(ValueError):
        file.refuser(a.id, FONDATEUR, "  ")
    a = file.refuser(a.id, FONDATEUR, "ton inadapté")
    assert a.statut is StatutAction.refuse and a.motif_refus == "ton inadapté"
    for tentative in (lambda: file.approuver(a.id, FONDATEUR), lambda: file.envoyer(a.id, expediteur, FONDATEUR)):
        with pytest.raises(TransitionInterdite):
            tentative()


def test_autonomie_reservee_au_fondateur_et_auditee(monde, file):
    for acteur in (SYSTEME, monde.acteurs["admin_a"]):
        with pytest.raises(AccesRefuse):
            file.definir_autonomie(TypeAction.relance, ModeAutonomie.auto, acteur)
    file.definir_autonomie(TypeAction.relance, ModeAutonomie.auto, FONDATEUR)
    assert file.autonomie(TypeAction.relance) is ModeAutonomie.auto
    assert file.autonomie(TypeAction.email_client) is ModeAutonomie.manuel
    assert "outbox_autonomie" in _audits(monde)


def test_mode_auto_approuve_si_garde_fous_ok(monde, file, expediteur):
    file.definir_autonomie(TypeAction.relance, ModeAutonomie.auto, FONDATEUR)
    a = file.proposer(TypeAction.relance, PROPRE, SYSTEME, tenant_id="cli_a")
    assert a.statut is StatutAction.approuve and a.auto and a.decide_par == "systeme:autonomie"
    b = file.proposer(TypeAction.relance, INTERDIT, SYSTEME, tenant_id="cli_a", idempotency_key="r2")
    assert b.statut is StatutAction.brouillon and b.motif_blocage
    envoyes = file.envoyer_approuves(expediteur, SYSTEME)
    assert [x.id for x in envoyes] == [a.id]


def test_seul_le_fondateur_decide(monde, file):
    a = file.proposer(TypeAction.email_client, PROPRE, SYSTEME, tenant_id="cli_a")
    for acteur in (SYSTEME, monde.acteurs["admin_a"], monde.acteurs["lecteur_a"], monde.acteurs["admin_b"]):
        for decision in (lambda ac: file.approuver(a.id, ac), lambda ac: file.corriger(a.id, ac, PROPRE),
                         lambda ac: file.refuser(a.id, ac, "x")):
            with pytest.raises(AccesRefuse):
                decision(acteur)
    with pytest.raises(AccesRefuse):
        file.proposer(TypeAction.email_client, PROPRE, monde.acteurs["admin_a"], tenant_id="cli_a")


def test_visibilite_client(monde, file, expediteur):
    a = file.proposer(TypeAction.reclamation_dossier, PROPRE, SYSTEME, tenant_id="cli_a")
    b = file.proposer(TypeAction.reclamation_dossier, PROPRE, SYSTEME, tenant_id="cli_b")
    file.proposer(TypeAction.email_prospection, PROPRE, FONDATEUR)
    admin_a = monde.acteurs["admin_a"]
    assert file.lister(admin_a) == []  # brouillons invisibles du client
    file.approuver(a.id, FONDATEUR)
    file.envoyer(a.id, expediteur, FONDATEUR)
    file.approuver(b.id, FONDATEUR)
    file.envoyer(b.id, expediteur, FONDATEUR)
    assert [x.id for x in file.lister(admin_a)] == [a.id]
    with pytest.raises(AccesRefuse):
        file.obtenir(b.id, admin_a)
    with pytest.raises(AccesRefuse):
        file.lister(admin_a, tenant_id="cli_b")
    assert len(file.lister(FONDATEUR)) == 5  # dont l'action de la fixture de chaque client


def test_idempotence_et_client_inconnu(file):
    a = file.proposer(TypeAction.facture_emise, PROPRE, SYSTEME, tenant_id="cli_a", idempotency_key="fac-1")
    b = file.proposer(TypeAction.facture_emise, {"corps": "autre"}, SYSTEME, tenant_id="cli_a",
                      idempotency_key="fac-1")
    assert a.id == b.id and b.payload == PROPRE
    with pytest.raises(AccesRefuse):
        file.proposer(TypeAction.facture_emise, PROPRE, SYSTEME, tenant_id="cli_inexistant")
    with pytest.raises(ValueError):
        file.proposer("envoi_sms", PROPRE, SYSTEME)


def test_garde_fous_reverifies_a_l_envoi(monde, file, expediteur, monkeypatch):
    a = file.approuver(file.proposer(TypeAction.email_client, PROPRE, SYSTEME, tenant_id="cli_a").id, FONDATEUR)
    import controldone.outbox.service as svc

    monkeypatch.setattr(svc, "verifier_textes", lambda contenu: ["liste enrichie entre-temps"])
    with pytest.raises(ActionBloquee):
        file.envoyer(a.id, expediteur, FONDATEUR)
    assert not expediteur.racine.exists() or not list(expediteur.racine.glob("**/*.json*"))


def test_aucun_envoi_reel_dans_le_code():
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2] / "src" / "controldone" / "outbox"
    code = "\n".join(p.read_text() for p in racine.glob("*.py"))
    for interdit in ("smtplib", "requests", "httpx", "urllib.request", "socket"):
        assert interdit not in code
