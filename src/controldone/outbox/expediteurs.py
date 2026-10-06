"""Expéditeurs (``Expediteur``) : le seul livré écrit des fichiers **chiffrés** dans ``var/outbox_envoyee/``
(``storage.traces_envoi``, D-4106) — **aucun envoi réel** (courriel, réseau social, plateforme) n'existe dans le
code."""

from __future__ import annotations

import re
from collections.abc import Sequence
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
    """Écrit ``<racine>/<kind>/<id>.json.enc`` : JSON chiffré par la clé dérivée ``outbox_envoyee`` de la clé
    maîtresse (idempotent : réécrit la même trace au même endroit). ``cles`` : clés maîtresses (défaut : celles
    de l'environnement)."""

    nom = "fichier"

    def __init__(self, racine: Path | str | None = None, *, cles: Sequence[bytes] | None = None) -> None:
        from controldone.storage.traces_envoi import TracesEnvoi, racine_par_defaut

        self.racine = Path(racine) if racine is not None else racine_par_defaut()
        self.traces = TracesEnvoi(self.racine, cles) if cles else TracesEnvoi.depuis_env(self.racine)

    def envoyer(self, action: ActionSortante) -> str:
        contenu = {
            "id": action.id,
            "kind": action.kind.value,
            "tenant_id": action.tenant_id,
            "statut_avant_envoi": action.statut.value,
            "decide_par": action.decide_par,
            "payload": action.payload_effectif,
            "corrige": action.payload_corrige is not None,
        }
        cible = self.traces.ecrire_json(
            _NOM_RE.sub("_", action.kind.value), _NOM_RE.sub("_", action.id), contenu
        )
        return f"fichier:{cible}"
