"""Rôles, acteurs et matrice des permissions (SPEC §4).

Fonction pure, sans base ni réseau : ``peut(user, action, ressource) -> bool``.

- ``fondateur`` (opérateur) : tous les droits, sur tous les clients, mais l'accès à un client passe par
  ``OperatorScope`` (journal d'audit de chaque accès) ;
- ``client_admin`` : lecture/écriture sur les données de **son** client (dépôt, corrections, déclaration
  d'envoi d'une réclamation, utilisateurs, clés d'API, export) ;
- ``client_lecteur`` : lecture seule des données de son client (constats publiés seulement) ;
- ``systeme`` : le worker (pipeline) ; écrit les données d'un client, ne valide ni ne publie rien.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "ACTIONS_CLIENT_ADMIN",
    "ACTIONS_CLIENT_LECTEUR",
    "ACTIONS_SYSTEME",
    "ROLES_CLIENT",
    "Acteur",
    "Action",
    "Ressource",
    "Role",
    "peut",
]


class Role(StrEnum):
    fondateur = "fondateur"
    client_admin = "client_admin"
    client_lecteur = "client_lecteur"
    systeme = "systeme"


ROLES_CLIENT = frozenset({Role.client_admin, Role.client_lecteur})


class Action(StrEnum):
    lire = "lire"
    lire_constats_proposes = "lire_constats_proposes"  # constats non encore validés (file de validation)
    ecrire = "ecrire"  # écriture générique sur les données du client
    deposer = "deposer"
    corriger = "corriger"
    valider_constat = "valider_constat"
    publier_rapport = "publier_rapport"
    valider_grille = "valider_grille"
    declarer_recouvrement = "declarer_recouvrement"  # envoi d'une réclamation, réception d'un avoir
    gerer_utilisateurs = "gerer_utilisateurs"
    gerer_cles_api = "gerer_cles_api"
    exporter = "exporter"
    supprimer_client = "supprimer_client"
    proposer_sortie = "proposer_sortie"
    approuver_sortie = "approuver_sortie"
    envoyer_sortie = "envoyer_sortie"
    changer_autonomie = "changer_autonomie"
    acces_admin = "acces_admin"
    voir_couts = "voir_couts"
    relancer_job = "relancer_job"


ACTIONS_CLIENT_LECTEUR = frozenset({Action.lire})
ACTIONS_CLIENT_ADMIN = frozenset(
    {
        Action.lire,
        Action.ecrire,
        Action.deposer,
        Action.corriger,
        Action.declarer_recouvrement,
        Action.gerer_utilisateurs,
        Action.gerer_cles_api,
        Action.exporter,
    }
)
ACTIONS_SYSTEME = frozenset(
    {
        Action.lire,
        Action.lire_constats_proposes,
        Action.ecrire,
        Action.deposer,
        Action.proposer_sortie,
        Action.envoyer_sortie,
        Action.voir_couts,
    }
)
_MATRICE: dict[Role, frozenset[Action]] = {
    Role.fondateur: frozenset(Action),
    Role.client_admin: ACTIONS_CLIENT_ADMIN,
    Role.client_lecteur: ACTIONS_CLIENT_LECTEUR,
    Role.systeme: ACTIONS_SYSTEME,
}


@dataclass(frozen=True, slots=True)
class Acteur:
    """Qui agit. ``tenant_id`` : client de rattachement (rôles client) ; ``None`` pour fondateur/système."""

    id: str
    role: Role
    tenant_id: str | None = None
    ip: str | None = None

    @classmethod
    def systeme(cls, nom: str = "systeme") -> Acteur:
        return cls(id=f"systeme:{nom}", role=Role.systeme)

    @property
    def est_fondateur(self) -> bool:
        return self.role is Role.fondateur

    @property
    def est_client(self) -> bool:
        return self.role in ROLES_CLIENT


@dataclass(frozen=True, slots=True)
class Ressource:
    """Ressource visée : type libre (``dossier``, ``constat``, ``outbox`` …) et client propriétaire
    (``None`` = ressource de niveau plateforme, ex. prospection du fondateur)."""

    type: str
    tenant_id: str | None = None


def _tenant_de(ressource: Any) -> tuple[bool, str | None]:
    if ressource is None:
        return False, None
    if isinstance(ressource, Ressource):
        return True, ressource.tenant_id
    if hasattr(ressource, "tenant_id"):
        return True, ressource.tenant_id
    return False, None


def peut(user: Acteur | None, action: Action | str, ressource: Any = None) -> bool:
    """Vrai si ``user`` peut faire ``action`` sur ``ressource``. Refus par défaut (rôle ou action inconnus,
    utilisateur absent, ressource d'un autre client, ressource de plateforme pour un rôle client)."""
    if user is None:
        return False
    try:
        role = Role(user.role)
        act = Action(action)
    except ValueError:
        return False
    if act not in _MATRICE.get(role, frozenset()):
        return False
    if role in (Role.fondateur, Role.systeme):
        return True
    # Rôles client : uniquement sur une ressource de leur propre client.
    connue, tenant = _tenant_de(ressource)
    if not connue or tenant is None or user.tenant_id is None:
        return False
    return tenant == user.tenant_id
