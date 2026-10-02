"""Stockage de la plateforme (niveau 2) : base (SQLAlchemy 2), cloisonnement par client, audit chaîné,
coffre chiffré, conservation/effacement/restitution, sauvegardes.

Règle : hors de ce paquet, aucune session ni requête SQL brute ; tout accès aux données client passe par
``TenantScope`` (ou ``OperatorScope`` pour le fondateur, accès tracé). Voir ``docs/SECURITY.md``.
"""

from controldone.storage import garde as _garde
from controldone.storage.audit import verifier_chaine
from controldone.storage.cles import charger_cles_maitresses, mode_execution, nouvelle_cle
from controldone.storage.db import Database
from controldone.storage.erreurs import AccesRefuse, CleManquante, ErreurCoffre, ErreurIntegrite
from controldone.storage.retention import RapportPurge, exporter_client, purger_expires, supprimer_client
from controldone.storage.scope import OperatorScope, TenantScope
from controldone.storage.vault import FileVault

_garde.installer()

__all__ = [
    "AccesRefuse",
    "CleManquante",
    "Database",
    "ErreurCoffre",
    "ErreurIntegrite",
    "FileVault",
    "OperatorScope",
    "RapportPurge",
    "TenantScope",
    "charger_cles_maitresses",
    "exporter_client",
    "mode_execution",
    "nouvelle_cle",
    "purger_expires",
    "supprimer_client",
    "verifier_chaine",
]
