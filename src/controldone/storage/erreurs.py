"""Erreurs de la couche de stockage."""

from __future__ import annotations

__all__ = ["AccesRefuse", "CleManquante", "ErreurCoffre", "ErreurIntegrite"]


class AccesRefuse(PermissionError):
    """Accès refusé : autre client, rôle insuffisant, objet introuvable dans le périmètre.

    Un objet d'un autre client et un objet inexistant donnent **la même** erreur (pas d'oracle
    d'existence par devinette d'identifiant)."""


class ErreurIntegrite(RuntimeError):
    """Journal d'audit altéré, contenu du coffre altéré."""


class ErreurCoffre(ValueError):
    """Référence ou identifiant invalide pour le coffre de fichiers."""


class CleManquante(RuntimeError):
    """Clé maîtresse absente en mode production : le service refuse de démarrer."""
