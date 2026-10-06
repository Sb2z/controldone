"""Bloc P3 (production) : traces d'envoi chiffrées au repos (D-4106), effacement d'un client sous le verrou de
maintenance (D-4103). Données FICTIVES."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from aides_plateforme import FONDATEUR
from cryptography.fernet import Fernet

from controldone.config import reset_settings
from controldone.storage import ErreurIntegrite, supprimer_client
from controldone.storage.controle_restauration import controler
from controldone.storage.sauvegarde import restaurer, sauvegarder
from controldone.storage.traces_envoi import MAGIE, TracesEnvoi, chiffrer_en_clair
from controldone.storage.verrou import VerrouOccupe, verrou_maintenance

NOW = datetime(2026, 10, 6, 2, 15, tzinfo=UTC)
SECRET = "Rapport FICTIF du CLIENT A — 1 234,56 EUR"


def _trace_json(traces: TracesEnvoi, tenant: str, ident: str) -> None:
    traces.ecrire_json(
        "rapport_publication", ident, {"id": ident, "tenant_id": tenant, "payload": {"corps": SECRET}}
    )


# --- traces chiffrées -------------------------------------------------------------------------------------


def test_trace_chiffree_illisible_sans_la_cle(tmp_path, cles):
    traces = TracesEnvoi(tmp_path / "outbox_envoyee", cles)
    _trace_json(traces, "cli_a", "out_1")
    (chemin,) = traces.lister()
    assert chemin.name == "out_1.json.enc" and chemin.stat().st_mode & 0o777 == 0o600
    brut = chemin.read_bytes()
    assert brut.startswith(MAGIE) and SECRET.encode() not in brut and b"cli_a" not in brut
    assert traces.lire_json(chemin)["payload"] == {"corps": SECRET}
    with pytest.raises(ErreurIntegrite):
        TracesEnvoi(tmp_path / "outbox_envoyee", [Fernet.generate_key()]).lire(chemin)
    chemin.write_bytes(brut[:-3] + b"xyz")  # altération
    with pytest.raises(ErreurIntegrite):
        traces.lire(chemin)


def test_noms_assainis_et_pas_de_traversee(tmp_path, cles):
    traces = TracesEnvoi(tmp_path / "o", cles)
    p = traces.ecrire("../../evasion", "../x/../../y.pdf", b"FICTIF")
    assert p.resolve().is_relative_to((tmp_path / "o").resolve())


def test_migration_des_traces_en_clair_idempotente(tmp_path, cles):
    racine = tmp_path / "outbox_envoyee"
    (racine / "rapport_publication").mkdir(parents=True)
    (racine / "facture_emise").mkdir()
    clair_json = racine / "rapport_publication" / "out_1.json"
    clair_json.write_text(json.dumps({"id": "out_1", "tenant_id": "cli_a", "note": SECRET}), encoding="utf-8")
    pdf = racine / "facture_emise" / "F-2026-0001.pdf"
    pdf.write_bytes(b"%PDF-1.7 FICTIF")
    (racine / "rapport_publication" / ".tmp-reste").write_bytes(b"temporaire")
    traces = TracesEnvoi(racine, cles)
    assert chiffrer_en_clair(racine, cles) == 2
    assert not clair_json.exists() and not pdf.exists()
    assert traces.en_clair() == []
    assert traces.lire(racine / "facture_emise" / "F-2026-0001.pdf.enc") == b"%PDF-1.7 FICTIF"
    assert traces.lire_json(racine / "rapport_publication" / "out_1.json.enc")["note"] == SECRET
    assert chiffrer_en_clair(racine, cles) == 0  # idempotent : rien n'est rechiffré


def test_rotation_des_cles_des_traces(tmp_path, cles):
    traces = TracesEnvoi(tmp_path / "o", cles)
    _trace_json(traces, "cli_a", "out_1")
    nouvelle = Fernet.generate_key()
    assert traces.tourner_cles([nouvelle, *cles]) == 1
    (chemin,) = traces.lister()
    assert TracesEnvoi(tmp_path / "o", [nouvelle]).lire_json(chemin)["id"] == "out_1"


def test_cli_migrer_chiffre_les_traces_en_clair(tmp_path, monkeypatch, capsys):
    from controldone.cli import main
    from controldone.storage import Database

    data = tmp_path / "var"
    url = f"sqlite:///{data}/m.db"
    db = Database(url)
    db.creer_schema()
    db.fermer()
    d = data / "outbox_envoyee" / "rapport_publication"
    d.mkdir(parents=True)
    (d / "out_1.json").write_text('{"id": "out_1", "tenant_id": "cli_a"}', encoding="utf-8")
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", url)
    reset_settings()
    try:
        assert main(["migrer", "--etat"]) == 0
        assert "traces d'envoi en clair à chiffrer : 1" in capsys.readouterr().out
        assert (d / "out_1.json").exists()  # --etat ne touche à rien
        assert main(["migrer"]) == 0  # schéma déjà à jour : seule l'étape des traces s'exécute
        assert "traces d'envoi chiffrées : 1" in capsys.readouterr().out
        assert not (d / "out_1.json").exists() and (d / "out_1.json.enc").exists()
        assert main(["migrer"]) == 0
        assert "chiffrées" not in capsys.readouterr().out
    finally:
        reset_settings()


def test_sauvegarde_restauration_et_controle_des_traces(monde, tmp_path, cles):
    sorties = tmp_path / "var" / "outbox_envoyee"
    traces = TracesEnvoi(sorties, cles)
    _trace_json(traces, "cli_a", "out_1")
    traces.ecrire("facture_emise", "F-2026-0001.pdf", b"%PDF FICTIF")
    archive = sauvegarder(
        monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "sauv", cles, now=NOW, sorties=sorties
    )
    cible = tmp_path / "restauree"
    restaurer(archive, cible, cles)
    rapport = controler(cible, cles)
    assert rapport.ok, rapport.problemes
    assert rapport.traces_dechiffrees == 2 and rapport.traces_en_clair == 0
    assert any("traces d'envoi      : 2 déchiffrées" in ligne for ligne in rapport.lignes())
    # une trace restaurée qui ne se déchiffre plus (autre clé) est un problème du contrôle
    autre = cible / "outbox_envoyee" / "rapport_publication" / "out_2.json.enc"
    TracesEnvoi(cible / "outbox_envoyee", [Fernet.generate_key()]).ecrire_json(
        "rapport_publication", "out_2", {}
    )
    assert autre.exists()
    rapport = controler(cible, cles)
    assert not rapport.ok and any("out_2.json.enc" in p for p in rapport.problemes)


# --- effacement d'un client sous le verrou de maintenance -------------------------------------------------


def test_effacement_client_refuse_pendant_une_sauvegarde(monde, tmp_path):
    data_dir = monde.vault.racine.parent
    with verrou_maintenance(data_dir, "sauvegarde"), pytest.raises(VerrouOccupe, match="sauvegarde en cours"):
        supprimer_client(
            monde.db,
            monde.vault,
            "cli_a",
            FONDATEUR,
            "demande RGPD (FICTIF)",
            dossier_sorties=tmp_path / "o",
            attente_verrou_s=0.2,
        )
    assert "cli_a" in monde.vault.clients()  # rien n'a été effacé
    comptes = supprimer_client(
        monde.db, monde.vault, "cli_a", FONDATEUR, "demande RGPD (FICTIF)", dossier_sorties=tmp_path / "o"
    )
    assert comptes["lots"] == 1 and "cli_a" not in monde.vault.clients()


def test_effacement_client_supprime_ses_traces_chiffrees_seulement(monde, tmp_path, cles):
    sorties = tmp_path / "o"
    traces = TracesEnvoi(sorties, monde.vault.cles_maitresses)
    _trace_json(traces, "cli_a", "out_a")
    _trace_json(traces, "cli_b", "out_b")
    traces.ecrire("facture_emise", "F-2026-0001.pdf", b"%PDF FICTIF")  # obligation de conservation
    (sorties / "rapport_publication" / "ancien.json").write_text('{"tenant_id": "cli_a"}', encoding="utf-8")
    comptes = supprimer_client(
        monde.db, monde.vault, "cli_a", FONDATEUR, "demande RGPD (FICTIF)", dossier_sorties=sorties
    )
    assert comptes["traces_envoi"] == 2
    restants = sorted(p.name for p in sorties.rglob("*") if p.is_file())
    assert restants == ["F-2026-0001.pdf.enc", "out_b.json.enc"]
