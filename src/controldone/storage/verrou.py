"""Verrou de maintenance partagé par la sauvegarde, la purge, la restauration et l'effacement d'un client
(D-3504, D-4103, D-4701).

Une purge lancée à la main pendant la copie d'une sauvegarde pouvait retirer du coffre un objet que l'instantané
de la base référence encore (« contenu référencé absent » au contrôle approfondi). Ces opérations prennent
désormais le même verrou exclusif, à deux étages :

1. **Fichier** ``<data_dir>/.verrou-maintenance`` (``fcntl.flock``), où ``data_dir`` est le répertoire qui
   contient le coffre (``CONTROLDONE_DATA_DIR``). Toujours pris. Les conteneurs ``web``, ``worker`` et
   ``scheduler`` montent le même volume ``/app/var`` sur un seul hôte : ``flock`` y est partagé.
2. **PostgreSQL** (D-4701), quand la base de la plateforme est PostgreSQL (``base_url``) : verrou consultatif
   de **session** ``pg_try_advisory_lock(CLE_PG)`` sur une connexion dédiée, tenue pendant toute l'opération.
   Il couvre plusieurs hôtes qui partagent la même base (volumes distincts : le fichier ne les voit pas). La
   connexion porte ``application_name = cd-maint|<opération>|<depuis>|<hôte>`` : un autre hôte qui trouve le
   verrou pris sait qui le tient (``pg_locks`` + ``pg_stat_activity``). SQLite : le fichier suffit (une base
   SQLite ne se partage pas entre hôtes).

- Les deux verrous sont **consultatifs** et liés au processus : le fichier disparaît avec le descripteur, le
  verrou PostgreSQL avec la connexion (aucun verrou orphelin après un ``kill -9``, un redémarrage de conteneur
  ou une coupure réseau ; le serveur libère le verrou d'une session fermée).
- Attente commune : ``attente_s`` borne la prise des **deux** verrous (fichier d'abord, puis PostgreSQL avec le
  temps restant). Au-delà : ``VerrouOccupe`` (« sauvegarde en cours depuis … sur <hôte> »).
- Serveur PostgreSQL injoignable : ``VerrouIndisponible`` (l'opération n'a pas lieu), sauf
  ``pg_injoignable_tolere=True`` (restauration après sinistre : le serveur peut être neuf ou absent ; seul le
  fichier est pris, avertissement sur la sortie d'erreur).
- Le fichier contient l'opération en cours, le PID et l'heure (diagnostic). Ni le fichier ni ``application_name``
  ne contiennent de donnée client.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import socket
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "CLE_PG",
    "NOM_VERROU",
    "VerrouIndisponible",
    "VerrouOccupe",
    "chemin_verrou",
    "detenteur",
    "detenteur_pg",
    "verrou_maintenance",
]

NOM_VERROU = ".verrou-maintenance"
#: Clé fixe du verrou consultatif PostgreSQL (« CDMAINT » ; celle des migrations est « CDS », D-3503).
CLE_PG = 0x43444D41494E54
_PREFIXE_APP = "cd-maint"


class VerrouOccupe(RuntimeError):
    """Une autre opération de maintenance (sauvegarde, purge, restauration) détient le verrou."""

    def __init__(self, operation: str, detenteur: dict[str, object] | None) -> None:
        self.operation = operation
        self.detenteur = detenteur or {}
        en_cours = self.detenteur.get("operation", "opération inconnue")
        depuis = self.detenteur.get("depuis", "?")
        hote = self.detenteur.get("hote")
        super().__init__(
            f"{operation} impossible pour l'instant : {en_cours} en cours depuis {depuis}"
            + (f" sur {hote}" if hote else "")
        )


class VerrouIndisponible(RuntimeError):
    """Le verrou PostgreSQL n'a pas pu être demandé (serveur injoignable) : l'opération n'a pas lieu."""


def chemin_verrou(data_dir: Path | str) -> Path:
    return Path(data_dir) / NOM_VERROU


def detenteur(data_dir: Path | str) -> dict[str, object] | None:
    """Contenu du fichier de verrou (dernière opération qui l'a pris), ou ``None``."""
    try:
        return json.loads(chemin_verrou(data_dir).read_text(encoding="utf-8") or "null")
    except (OSError, ValueError):
        return None


def _est_postgresql(url: str | None) -> bool:
    if not url:
        return False
    from sqlalchemy.engine import make_url

    try:
        return make_url(url).get_backend_name() == "postgresql"
    except Exception:  # URL illisible : pas de verrou PostgreSQL (la base échouera ailleurs, plus clairement)
        return False


def _cle_pg_parties() -> tuple[int, int]:
    """``(classid, objid)`` de ``CLE_PG`` dans ``pg_locks`` (clé bigint : 32 bits hauts, 32 bits bas)."""
    return CLE_PG >> 32, CLE_PG & 0xFFFFFFFF


_SQL_DETENTEUR = """
SELECT a.application_name, a.backend_start, a.pid
FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.locktype = 'advisory' AND l.granted AND l.classid = :hi AND l.objid = :lo AND l.objsubid = 1
  AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
LIMIT 1
"""


def _lire_detenteur(conn: Any) -> dict[str, object] | None:
    from sqlalchemy import text

    hi, lo = _cle_pg_parties()
    ligne = conn.execute(text(_SQL_DETENTEUR), {"hi": hi, "lo": lo}).first()
    if ligne is None:
        return None
    nom = ligne[0] or ""
    parties = nom.split("|")
    if len(parties) >= 3 and parties[0] == _PREFIXE_APP:
        return {
            "operation": parties[1],
            "depuis": parties[2],
            "hote": parties[3] if len(parties) > 3 else None,
            "pid_serveur": ligne[2],
        }
    debut = ligne[1].isoformat(timespec="seconds") if ligne[1] is not None else "?"
    return {"operation": "opération inconnue", "depuis": debut, "pid_serveur": ligne[2]}


def detenteur_pg(base_url: str) -> dict[str, object] | None:
    """Qui tient le verrou PostgreSQL (opération, depuis, hôte), ou ``None`` s'il est libre."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    moteur = create_engine(base_url, poolclass=NullPool, future=True)
    try:
        with moteur.connect() as conn:
            return _lire_detenteur(conn)
    finally:
        moteur.dispose()


@contextlib.contextmanager
def _verrou_fichier(data_dir: Path | str, operation: str, fin: float, intervalle_s: float) -> Iterator[Path]:
    chemin = chemin_verrou(data_dir)
    chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(chemin, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= fin:
                    raise VerrouOccupe(operation, detenteur(data_dir)) from None
                time.sleep(min(intervalle_s, max(0.01, fin - time.monotonic())))
        info = {
            "operation": operation,
            "pid": os.getpid(),
            "depuis": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps(info).encode(), 0)
        try:
            yield chemin
        finally:
            with contextlib.suppress(OSError):
                os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _nom_application(operation: str) -> str:
    """``cd-maint|<opération>|<depuis>|<hôte>``, tronqué à 63 octets (limite de ``application_name``)."""
    depuis = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    nom = f"{_PREFIXE_APP}|{operation[:20]}|{depuis}|{socket.gethostname()}"
    return nom.encode("ascii", "replace")[:63].decode("ascii")


@contextlib.contextmanager
def _verrou_pg(
    base_url: str, operation: str, fin: float, intervalle_s: float, *, tolere: bool
) -> Iterator[None]:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool

    # pg8000 : délai de connexion et de chaque échange (serveur muet : échec franc, jamais d'attente sans fin)
    options = {"timeout": 30} if make_url(base_url).get_driver_name() == "pg8000" else {}
    moteur = create_engine(
        base_url, poolclass=NullPool, future=True, isolation_level="AUTOCOMMIT", connect_args=options
    )
    try:
        conn = None
        try:
            conn = moteur.connect()
        except Exception as exc:
            message = (
                f"verrou de maintenance PostgreSQL impossible ({type(exc).__name__}) : serveur injoignable"
            )
            if not tolere:
                raise VerrouIndisponible(f"{operation} refusée : {message}") from exc
            print(f"avertissement : {message} ; verrou du fichier seulement", file=sys.stderr)
        if conn is None:
            yield None
            return
        try:
            # Session tenue pendant toute l'opération : jamais coupée pour inactivité (PostgreSQL ≥ 14).
            with contextlib.suppress(Exception):
                conn.execute(text("SELECT set_config('idle_session_timeout', '0', false)"))
            conn.execute(
                text("SELECT set_config('application_name', :n, false)"), {"n": _nom_application(operation)}
            )
            while True:
                if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": CLE_PG}).scalar_one():
                    break
                if time.monotonic() >= fin:
                    raise VerrouOccupe(operation, _lire_detenteur(conn))
                time.sleep(min(intervalle_s, max(0.01, fin - time.monotonic())))
            try:
                yield None
            finally:
                # connexion perdue entre-temps : le serveur a déjà libéré le verrou avec la session
                with contextlib.suppress(Exception):
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": CLE_PG})
        finally:
            with contextlib.suppress(Exception):
                conn.close()
    finally:
        moteur.dispose()


@contextlib.contextmanager
def verrou_maintenance(
    data_dir: Path | str,
    operation: str,
    *,
    attente_s: float = 0.0,
    intervalle_s: float = 1.0,
    base_url: str | None = None,
    pg_injoignable_tolere: bool = False,
) -> Iterator[Path]:
    """Prend le verrou exclusif (attend au plus ``attente_s`` secondes), sinon lève ``VerrouOccupe``.

    ``base_url`` : URL de la base de la plateforme ; PostgreSQL -> verrou consultatif en plus du fichier
    (plusieurs hôtes, D-4701). SQLite ou ``None`` : fichier seulement."""
    fin = time.monotonic() + max(0.0, attente_s)
    with _verrou_fichier(data_dir, operation, fin, intervalle_s) as chemin:
        if not _est_postgresql(base_url):
            yield chemin
            return
        with _verrou_pg(base_url, operation, fin, intervalle_s, tolere=pg_injoignable_tolere):  # type: ignore[arg-type]
            yield chemin
