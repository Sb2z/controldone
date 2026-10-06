"""Verrou de maintenance partagé par la sauvegarde, la purge et la restauration (D-3504)."""

from __future__ import annotations

import multiprocessing
import os
import time
from datetime import timedelta

import pytest

from controldone.config import reset_settings
from controldone.storage import purger_expires
from controldone.storage import sauvegarde as sv
from controldone.storage.coltypes import maintenant
from controldone.storage.verrou import VerrouOccupe, detenteur, verrou_maintenance


def test_verrou_exclusif_et_libere(tmp_path):
    with verrou_maintenance(tmp_path, "sauvegarde"):
        assert detenteur(tmp_path)["operation"] == "sauvegarde"
        with pytest.raises(VerrouOccupe, match="sauvegarde en cours"), verrou_maintenance(tmp_path, "purge"):
            pass
        debut = time.monotonic()
        with pytest.raises(VerrouOccupe), verrou_maintenance(tmp_path, "purge", attente_s=0.3, intervalle_s=0.05):
            pass
        assert time.monotonic() - debut >= 0.25
    with verrou_maintenance(tmp_path, "purge"):  # libéré à la sortie
        pass


def _tenir(chemin: str, pret, fin) -> None:
    with verrou_maintenance(chemin, "sauvegarde"):
        pret.set()
        fin.wait(10)


def test_verrou_partage_entre_processus_et_libere_a_la_mort(tmp_path):
    ctx = multiprocessing.get_context("fork")
    pret, fin = ctx.Event(), ctx.Event()
    p = ctx.Process(target=_tenir, args=(str(tmp_path), pret, fin))
    p.start()
    try:
        assert pret.wait(10)
        with pytest.raises(VerrouOccupe), verrou_maintenance(tmp_path, "purge"):
            pass
    finally:
        p.kill()  # mort brutale : le verrou disparaît avec le descripteur
        p.join(10)
    with verrou_maintenance(tmp_path, "purge", attente_s=2):
        pass


def test_purge_refusee_pendant_une_sauvegarde(monde):
    data_dir = monde.vault.racine.parent
    with verrou_maintenance(data_dir, "sauvegarde"), pytest.raises(VerrouOccupe):
        purger_expires(monde.db, monde.vault, maintenant() + timedelta(days=10000))
    purger_expires(monde.db, monde.vault, maintenant())  # verrou libre : la purge passe


def test_job_de_purge_reporte_pendant_une_sauvegarde(monde):
    from controldone.jobs.handlers import purger_retention
    from controldone.jobs.registre import JobContext, Reporter

    ctx = JobContext(job=None, db=monde.db, services={"vault": monde.vault})  # type: ignore[arg-type]
    with verrou_maintenance(monde.vault.racine.parent, "sauvegarde"), pytest.raises(Reporter) as exc:
        purger_retention(ctx)
    assert exc.value.delai_s == 600


def test_sauvegarde_attend_puis_echoue_si_le_verrou_reste_pris(monde, tmp_path, monkeypatch):
    data_dir = tmp_path / "var"
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", f"sqlite:///{monde.db.chemin_sqlite()}")
    monkeypatch.setenv("BACKUP_VERROU_ATTENTE_S", "0")
    reset_settings()
    alertes = []
    monkeypatch.setattr(sv, "alerter", lambda kind, message, details=None: alertes.append(kind))
    try:
        with verrou_maintenance(data_dir, "purge"):
            assert sv.main(["sauvegarder", "--destination", str(tmp_path / "sv")]) == sv.ECHEC_CREATION
        assert alertes == ["sauvegarde_echec"]
        assert not list((tmp_path / "sv").glob("controldone-*.tar.gz.enc"))
        assert sv.main(["sauvegarder", "--destination", str(tmp_path / "sv")]) == sv.OK
    finally:
        reset_settings()


def test_restauration_refusee_pendant_une_purge(monde, tmp_path, monkeypatch):
    data_dir = tmp_path / "var"
    archive = sv.sauvegarder(monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "sv",
                             [os.environ["CONTROLDONE_MASTER_KEY"].encode()])
    monkeypatch.setattr(sv, "ATTENTE_RESTAURATION_S", 0.0)
    reset_settings()
    try:
        with verrou_maintenance(data_dir, "purge"):
            assert sv.main(["restaurer", str(archive), str(tmp_path / "r")]) == sv.ECHEC_CONFIGURATION
        assert sv.main(["restaurer", str(archive), str(tmp_path / "r")]) == sv.OK
    finally:
        reset_settings()


def test_restauration_dans_le_repertoire_de_donnees_tolere_le_verrou(monde, tmp_path, monkeypatch):
    """La cible peut être le répertoire de données lui-même (seul fichier présent : le verrou)."""
    archive = sv.sauvegarder(monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "sv",
                             [os.environ["CONTROLDONE_MASTER_KEY"].encode()])
    cible = tmp_path / "donnees"
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(cible))
    reset_settings()
    try:
        assert sv.main(["restaurer", str(archive), str(cible)]) == sv.OK
        assert (cible / "base" / "controldone.db").is_file()
    finally:
        reset_settings()
