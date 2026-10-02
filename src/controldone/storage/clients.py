"""Liste des clients actifs (identifiants seulement) pour les tâches planifiées de la plateforme
(planificateur des agents, relevé des connecteurs, référentiel). Aucune donnée client n'est lue ici :
chaque traitement ouvre ensuite le périmètre du client (``TenantScope``) avec son propre acteur."""

from __future__ import annotations

from sqlalchemy import select

from controldone.storage.db import Database
from controldone.storage.models import Tenant

__all__ = ["clients_actifs"]


def clients_actifs(db: Database) -> list[str]:
    """Identifiants des clients actifs, triés."""
    with db.transaction_systeme() as s:
        return list(s.execute(select(Tenant.id).where(Tenant.actif.is_(True)).order_by(Tenant.id)).scalars())
