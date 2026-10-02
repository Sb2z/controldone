"""Interfaces des connecteurs entrants.

Un connecteur **relève** des dépôts (``relever() -> list[Depot]``) pour un client ; l'intégration
(``connecteurs.depot.integrer_depot``) les transforme en lot (coffre chiffré + métadonnées) et met en file
le traitement ; le connecteur peut ensuite **acquitter** le dépôt (archiver le fichier, marquer le
courriel lu, accuser réception) selon le résultat. Un connecteur ne lit ni n'interprète le contenu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = ["ConnecteurEntrant", "Depot", "ResultatDepot"]


@dataclass
class Depot:
    tenant_id: str
    canal: str  # depot | courriel | api
    source: str  # nom du connecteur
    elements: list[tuple[str, bytes]] = field(default_factory=list)  # (chemin relatif, octets)
    courriel: bytes | None = None  # message brut de la boîte dédiée (jamais interprété)
    message_id: str | None = None
    reference: str | None = None  # référence propre au connecteur (uid IMAP, identifiant PA…)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultatDepot:
    #: ``lot_cree`` | ``deja_recu`` (idempotence : sha256 ou Message-ID) | ``quarantaine`` | ``vide``
    statut: str
    lot_id: str | None = None
    jobs: list[str] = field(default_factory=list)
    fichiers: int = 0
    doublons: int = 0
    refuses: int = 0
    motif: str | None = None

    def en_dict(self) -> dict[str, Any]:
        return {"statut": self.statut, "lot_id": self.lot_id, "jobs": self.jobs, "fichiers": self.fichiers,
                "doublons": self.doublons, "refuses": self.refuses, "motif": self.motif}


@runtime_checkable
class ConnecteurEntrant(Protocol):
    nom: str
    tenant_id: str

    def relever(self) -> list[Depot]:
        """Dépôts prêts à intégrer (sans effet de bord sur la source : voir ``acquitter``)."""
        ...
