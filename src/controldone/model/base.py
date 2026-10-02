"""Classes de base du modèle et versionnement du schéma (SPEC §6.2, §6.4)."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from controldone import SCHEMA_VERSION

__all__ = [
    "NOM_SCHEMA_DOSSIER",
    "Enregistrement",
    "ErreurSchema",
    "Modele",
    "VersionSchema",
    "horodatage",
    "set_horloge",
    "verifier_schema",
]

NOM_SCHEMA_DOSSIER = "controldone.dossier"

_horloge: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def horodatage() -> datetime:
    """Horodatage UTC courant (remplaçable par ``set_horloge`` pour des sorties reproductibles)."""
    return _horloge()


def set_horloge(fn: Callable[[], datetime]) -> None:
    global _horloge
    _horloge = fn


class Modele(BaseModel):
    """Base de tous les objets du modèle.

    ``extra="ignore"`` : un lecteur accepte un document de version mineure supérieure en ignorant
    les champs inconnus (§6.4). ``validate_assignment`` garde les objets cohérents après mutation.
    """

    model_config = ConfigDict(
        extra="ignore",
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=False,
        ser_json_inf_nan="constants",
    )


class Enregistrement(Modele):
    """Entité persistée : ``id`` (UUID v7 préfixé), ``client_id``, ``cree_le``, ``modifie_le`` (§6.2)."""

    PREFIXE: ClassVar[str] = ""

    id: str
    client_id: str | None = None
    cree_le: datetime = Field(default_factory=horodatage)
    modifie_le: datetime = Field(default_factory=horodatage)


# --- Versionnement ------------------------------------------------------------------------------

_SCHEMA_RE = re.compile(r"^(?P<nom>[a-z][a-z0-9_.]*)/(?P<maj>\d+)\.(?P<min>\d+)\.(?P<cor>\d+)$")


class ErreurSchema(ValueError):
    """Document de schéma inconnu ou de version majeure supérieure à celle du lecteur."""


class VersionSchema(Modele):
    nom: str
    majeure: int
    mineure: int
    correctif: int

    @classmethod
    def lire(cls, chaine: str) -> VersionSchema:
        m = _SCHEMA_RE.match(chaine or "")
        if not m:
            raise ErreurSchema(f"identifiant de schéma invalide : {chaine!r}")
        return cls(nom=m["nom"], majeure=int(m["maj"]), mineure=int(m["min"]), correctif=int(m["cor"]))

    def __str__(self) -> str:
        return f"{self.nom}/{self.majeure}.{self.mineure}.{self.correctif}"


def chaine_schema(nom: str, version: str = SCHEMA_VERSION) -> str:
    """Ex. ``chaine_schema("controldone.dossier")`` -> ``"controldone.dossier/2.0.0"``."""
    return f"{nom}/{version}"


def verifier_schema(chaine: str, nom_attendu: str, version_lecteur: str) -> VersionSchema:
    """Vérifie la chaîne ``schema`` d'un JSON lu (§6.4).

    - nom différent : refus ;
    - version majeure supérieure à celle du lecteur : refus ;
    - mineure ou correctif supérieurs : acceptés (les champs inconnus sont ignorés par ``Modele``).
    """
    v = VersionSchema.lire(chaine)
    if v.nom != nom_attendu:
        raise ErreurSchema(f"schéma {v.nom!r} inattendu (attendu {nom_attendu!r})")
    maj_lecteur = int(version_lecteur.split(".")[0])
    if v.majeure > maj_lecteur:
        raise ErreurSchema(
            f"version majeure {v.majeure} supérieure à celle du lecteur ({version_lecteur}) : refus"
        )
    return v


def dump_canonique(obj: Any) -> str:
    """JSON canonique (clés triées, séparateurs compacts, UTF-8) pour empreintes et comparaisons."""
    import json

    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


__all__ += ["chaine_schema", "dump_canonique"]
