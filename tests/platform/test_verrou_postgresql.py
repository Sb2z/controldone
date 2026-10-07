"""Verrou de maintenance à plusieurs hôtes : verrou consultatif PostgreSQL en plus du fichier (D-4701).

- Sans serveur : choix du verrou selon l'URL, nom de session borné, serveur injoignable (refus ou tolérance).
- Avec un serveur jetable (``CONTROLDONE_TEST_PG_URL``, ``scripts/pg_jetable.sh`` ; ``make test-pg-verrou``) :
  deux « hôtes » (deux répertoires de données distincts, donc deux fichiers de verrou qui ne se voient pas) qui
  partagent la même base s'excluent ; le détenteur est identifié ; le verrou disparaît avec le processus.
"""

from __future__ import annotations

import multiprocessing
import os
import socket
import time
from datetime import timedelta

import pytest
from aides_pg import base_pg  # noqa: F401  (fixture)

from controldone.config import reset_settings
from controldone.storage import sauvegarde as sv
from controldone.storage import verrou
from controldone.storage.verrou import (
    VerrouIndisponible,
    VerrouOccupe,
    detenteur_pg,
    verrou_maintenance,
)

# --- sans serveur -----------------------------------------------------------------------------------------


def test_sqlite_ou_absent_fichier_seulement(tmp_path, monkeypatch):
    appels = []
    monkeypatch.setattr(verrou, "_verrou_pg", lambda *a, **k: appels.append(a))
    for url in (None, "", f"sqlite:///{tmp_path}/x.db", "pas une url ::"):
        with verrou_maintenance(tmp_path, "sauvegarde", base_url=url):
            pass
    assert appels == []
    assert verrou._est_postgresql("postgresql+pg8000://u@h/db")


def test_nom_de_session_borne_et_sans_donnee(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "hote-" + "x" * 200)
    nom = verrou._nom_application("effacement_client")
    assert len(nom.encode()) <= 63
    assert nom.startswith("cd-maint|effacement_client|20")


def test_message_avec_hote():
    exc = VerrouOccupe("purge", {"operation": "sauvegarde", "depuis": "2026-10-07T02:15:00Z", "hote": "h2"})
    assert "sauvegarde en cours depuis 2026-10-07T02:15:00Z sur h2" in str(exc)


def _port_ferme() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_serveur_injoignable_refus_puis_tolerance(tmp_path, capsys):
    pytest.importorskip("pg8000")
    url = f"postgresql+pg8000://cd@127.0.0.1:{_port_ferme()}/postgres"
    with (
        pytest.raises(VerrouIndisponible, match="sauvegarde refusée"),
        verrou_maintenance(tmp_path, "sauvegarde", base_url=url),
    ):
        pytest.fail("l'opération ne doit pas avoir lieu sans le verrou PostgreSQL")
    with verrou_maintenance(tmp_path, "purge"):  # le fichier a été libéré malgré l'échec
        pass
    passe = False
    with verrou_maintenance(tmp_path, "restauration", base_url=url, pg_injoignable_tolere=True):
        passe = True
    assert passe
    assert "verrou du fichier seulement" in capsys.readouterr().err


# --- serveur PostgreSQL jetable ---------------------------------------------------------------------------


@pytest.mark.postgresql
def test_deux_hotes_s_excluent(tmp_path, base_pg):  # noqa: F811
    hote_a, hote_b = tmp_path / "a", tmp_path / "b"  # volumes distincts : les fichiers ne se voient pas
    assert detenteur_pg(base_pg) is None
    with verrou_maintenance(hote_a, "sauvegarde", base_url=base_pg):
        d = detenteur_pg(base_pg)
        assert d is not None and d["operation"] == "sauvegarde" and d["hote"]
        with (
            pytest.raises(VerrouOccupe, match="sauvegarde en cours depuis") as exc,
            verrou_maintenance(hote_b, "purge", base_url=base_pg),
        ):
            pytest.fail("deux hôtes en maintenance en même temps")
        assert exc.value.detenteur["operation"] == "sauvegarde"
        debut = time.monotonic()
        with (
            pytest.raises(VerrouOccupe),
            verrou_maintenance(hote_b, "purge", base_url=base_pg, attente_s=0.6, intervalle_s=0.1),
        ):
            pass
        assert time.monotonic() - debut >= 0.5
        with verrou_maintenance(hote_b, "purge"):  # sans base_url : fichier de B seulement, libre
            pass
    assert detenteur_pg(base_pg) is None
    with verrou_maintenance(hote_b, "purge", base_url=base_pg):  # libéré à la sortie
        pass


@pytest.mark.postgresql
def test_attente_jusqu_a_liberation(tmp_path, base_pg):  # noqa: F811
    ctx = multiprocessing.get_context("fork")
    pret, fin = ctx.Event(), ctx.Event()
    p = ctx.Process(target=_tenir, args=(str(tmp_path / "a"), base_pg, pret, fin, 0.8))
    p.start()
    try:
        assert pret.wait(20)
        debut = time.monotonic()
        with verrou_maintenance(tmp_path / "b", "purge", base_url=base_pg, attente_s=15, intervalle_s=0.1):
            assert time.monotonic() - debut >= 0.3
    finally:
        fin.set()
        p.join(20)


def _tenir(data_dir: str, url: str, pret, fin, duree: float | None = None) -> None:
    with verrou_maintenance(data_dir, "sauvegarde", base_url=url):
        pret.set()
        if duree is not None:
            time.sleep(duree)
        else:
            fin.wait(30)


@pytest.mark.postgresql
def test_verrou_libere_a_la_mort_du_processus(tmp_path, base_pg):  # noqa: F811
    ctx = multiprocessing.get_context("fork")
    pret, fin = ctx.Event(), ctx.Event()
    p = ctx.Process(target=_tenir, args=(str(tmp_path / "a"), base_pg, pret, fin))
    p.start()
    try:
        assert pret.wait(20)
        with pytest.raises(VerrouOccupe), verrou_maintenance(tmp_path / "b", "purge", base_url=base_pg):
            pass
    finally:
        p.kill()  # mort brutale : la connexion se ferme, le serveur libère le verrou de la session
        p.join(10)
    with verrou_maintenance(tmp_path / "b", "purge", base_url=base_pg, attente_s=10, intervalle_s=0.1):
        pass


@pytest.mark.postgresql
def test_purge_d_un_autre_hote_reportee(tmp_path, base_pg, monkeypatch):  # noqa: F811
    from cryptography.fernet import Fernet

    from controldone.storage import Database, FileVault, purger_expires
    from controldone.storage.coltypes import maintenant

    db = Database(base_pg)
    try:
        db.creer_schema()
        vault = FileVault(tmp_path / "b" / "coffre", [Fernet.generate_key()])
        with (
            verrou_maintenance(tmp_path / "a", "sauvegarde", base_url=base_pg),
            pytest.raises(VerrouOccupe, match="sauvegarde en cours"),
        ):
            purger_expires(db, vault, maintenant() + timedelta(days=10000))
        purger_expires(db, vault, maintenant())  # verrou libre : la purge passe
    finally:
        db.fermer()


@pytest.mark.postgresql
def test_sauvegarde_refusee_pendant_l_operation_d_un_autre_hote(tmp_path, base_pg, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", base_pg)
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "b"))
    monkeypatch.setenv("BACKUP_VERROU_ATTENTE_S", "0")
    reset_settings()
    alertes = []
    monkeypatch.setattr(sv, "alerter", lambda kind, message, details=None: alertes.append(kind))
    monkeypatch.setattr(sv, "sauvegarder_postgresql", lambda *a, **k: pytest.fail("copie sans verrou"))
    try:
        with verrou_maintenance(tmp_path / "a", "purge", base_url=base_pg):
            code = sv.main(["sauvegarder", "--destination", str(tmp_path / "sv")])
        assert code == sv.ECHEC_CREATION
        assert alertes == ["sauvegarde_echec"]
    finally:
        reset_settings()
        os.environ.pop("BACKUP_VERROU_ATTENTE_S", None)
