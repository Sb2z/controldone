"""Contexte partagé des services : base, coffre, clés maîtresses, limites de dépôt."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from controldone.auth.roles import Acteur, Action, Ressource, peut
from controldone.ingest.reception import Limites
from controldone.storage.db import Database
from controldone.storage.vault import FileVault

__all__ = ["Interdit", "Plateforme", "RequeteInvalide", "exiger"]


class Interdit(PermissionError):
    """Action refusée pour le rôle de l'acteur (HTTP 403). Un objet d'un autre client ou inexistant
    donne ``AccesRefuse`` (HTTP 404, même réponse dans les deux cas)."""


class RequeteInvalide(ValueError):
    """Données fournies invalides (HTTP 400 / 422) ; le message est écrit par notre code."""


def exiger(acteur: Acteur, action: Action, tenant_id: str | None) -> None:
    if not peut(acteur, action, Ressource("donnees", tenant_id)):
        raise Interdit(f"action « {action.value} » non autorisée pour ce compte")


@dataclass
class Plateforme:
    db: Database
    vault: FileVault
    cles_maitresses: list[bytes]
    limites: Limites = field(default_factory=Limites)
    #: Dossier de l'expéditeur fichier (mise à disposition des rapports et dossiers de réclamation).
    dossier_sorties: Path | None = None

    @classmethod
    def depuis_env(cls) -> Plateforme:
        from controldone.config import get_settings
        from controldone.storage.cles import charger_cles_maitresses

        data_dir = get_settings().data_dir
        cles = charger_cles_maitresses(data_dir=data_dir)
        return cls(db=Database(), vault=FileVault(Path(data_dir) / "coffre", cles), cles_maitresses=cles,
                   dossier_sorties=Path(data_dir) / "outbox_envoyee")
