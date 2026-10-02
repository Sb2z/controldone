"""Expéditeurs (``Expediteur``) : le seul livré écrit des fichiers dans ``var/outbox_envoyee/`` —
**aucun envoi réel** (courriel, réseau social, plateforme) n'existe dans le code."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from controldone.outbox.modele import ActionSortante

__all__ = ["Expediteur", "ExpediteurFichier"]

_NOM_RE = re.compile(r"[^A-Za-z0-9_-]")


@runtime_checkable
class Expediteur(Protocol):
    nom: str

    def envoyer(self, action: ActionSortante) -> str:
        """Envoie (ou dépose) l'action ; renvoie une référence. Doit être idempotent par ``action.id``."""
        ...


class ExpediteurFichier:
    """Écrit ``<racine>/<kind>/<id>.json`` (idempotent : réécrit le même fichier au même endroit)."""

    nom = "fichier"

    def __init__(self, racine: Path | str | None = None) -> None:
        if racine is None:
            from controldone.config import get_settings

            racine = Path(get_settings().data_dir) / "outbox_envoyee"
        self.racine = Path(racine)

    def envoyer(self, action: ActionSortante) -> str:
        dossier = self.racine / _NOM_RE.sub("_", action.kind.value)
        dossier.mkdir(parents=True, exist_ok=True, mode=0o700)
        cible = dossier / f"{_NOM_RE.sub('_', action.id)}.json"
        contenu = {
            "id": action.id, "kind": action.kind.value, "tenant_id": action.tenant_id,
            "statut_avant_envoi": action.statut.value, "decide_par": action.decide_par,
            "payload": action.payload_effectif, "corrige": action.payload_corrige is not None,
        }
        fd, tmp = tempfile.mkstemp(dir=dossier, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(contenu, f, ensure_ascii=False, indent=2, default=str)
        os.chmod(tmp, 0o600)
        os.replace(tmp, cible)
        return f"fichier:{cible}"
