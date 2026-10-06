"""Verrou de maintenance partagé par la sauvegarde, la purge et la restauration (D-3504).

Une purge lancée à la main pendant la copie d'une sauvegarde pouvait retirer du coffre un objet que l'instantané
de la base référence encore (« contenu référencé absent » au contrôle approfondi). Les trois opérations prennent
désormais le même verrou exclusif : ``<data_dir>/.verrou-maintenance`` (``fcntl.flock``), où ``data_dir`` est le
répertoire qui contient le coffre (``CONTROLDONE_DATA_DIR``).

- Le verrou est **consultatif** et lié au descripteur : il disparaît avec le processus (aucun verrou orphelin
  après un ``kill -9`` ou un redémarrage de conteneur).
- Les conteneurs ``web``, ``worker`` et ``scheduler`` montent le même volume ``/app/var`` sur un seul hôte :
  ``flock`` y est partagé. Plusieurs hôtes (PostgreSQL partagé, volumes distincts) ne sont **pas** couverts :
  voir ``docs/backlog/production.md``.
- Le fichier contient l'opération en cours, le PID et l'heure (diagnostic : « purge en cours depuis … »). Il ne
  contient aucune donnée client.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["NOM_VERROU", "VerrouOccupe", "chemin_verrou", "detenteur", "verrou_maintenance"]

NOM_VERROU = ".verrou-maintenance"


class VerrouOccupe(RuntimeError):
    """Une autre opération de maintenance (sauvegarde, purge, restauration) détient le verrou."""

    def __init__(self, operation: str, detenteur: dict[str, object] | None) -> None:
        self.operation = operation
        self.detenteur = detenteur or {}
        en_cours = self.detenteur.get("operation", "opération inconnue")
        depuis = self.detenteur.get("depuis", "?")
        super().__init__(f"{operation} impossible pour l'instant : {en_cours} en cours depuis {depuis}")


def chemin_verrou(data_dir: Path | str) -> Path:
    return Path(data_dir) / NOM_VERROU


def detenteur(data_dir: Path | str) -> dict[str, object] | None:
    """Contenu du fichier de verrou (dernière opération qui l'a pris), ou ``None``."""
    try:
        return json.loads(chemin_verrou(data_dir).read_text(encoding="utf-8") or "null")
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def verrou_maintenance(
    data_dir: Path | str, operation: str, *, attente_s: float = 0.0, intervalle_s: float = 1.0
) -> Iterator[Path]:
    """Prend le verrou exclusif (attend au plus ``attente_s`` secondes), sinon lève ``VerrouOccupe``."""
    chemin = chemin_verrou(data_dir)
    chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(chemin, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fin = time.monotonic() + max(0.0, attente_s)
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
