"""Cadre des agents d'exploitation : rôle, outils autorisés, journal, contexte.

Principe (SPEC §1.1, §4, §20.2) : un agent **propose** et ne décide rien. Ses seules écritures passent
par des outils qui créent un brouillon sortant (validé par le fondateur), une alerte au fondateur ou une
demande de job. Il ne voit qu'**un** client (celui de son contexte, fixé à la construction et absent des
paramètres de ses outils) — ou aucun pour un agent de plateforme (``veille``). Il n'envoie rien, ne
modifie ni niveau ni montant de constat, n'écrit dans aucune table métier.

- ``Outil`` : fonction Python ``fn(ctx, **params)`` à paramètres typés ; les paramètres sont validés
  (pydantic ``TypeAdapter``) avant l'appel.
- ``Agent.outils`` : liste blanche explicite des noms d'outils ; tout autre appel lève
  ``OutilNonAutorise`` (et est journalisé).
- ``Agent.appeler(ctx, nom, **params)`` : seul chemin d'accès aux données et aux écritures.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from pydantic import TypeAdapter

from controldone.auth.roles import Acteur
from controldone.ids import nouvel_id
from controldone.storage.coltypes import maintenant

from .journal import JournalAgents, resumer

__all__ = ["Agent", "ContexteAgent", "Outil", "OutilNonAutorise", "RapportAgent"]


class OutilNonAutorise(PermissionError):
    """Outil hors de la liste blanche de l'agent."""


@dataclass(frozen=True)
class Outil:
    nom: str
    description: str
    fn: Callable[..., Any]

    def parametres(self) -> dict[str, Any]:
        indices = typing.get_type_hints(self.fn)
        sig = inspect.signature(self.fn)
        return {n: indices.get(n, Any) for n in list(sig.parameters)[1:]}

    def valider(self, params: dict[str, Any]) -> dict[str, Any]:
        sig = inspect.signature(self.fn)
        attendus = self.parametres()
        inconnus = set(params) - set(attendus)
        if inconnus:
            raise TypeError(f"{self.nom} : paramètres inconnus {sorted(inconnus)}")
        sortie: dict[str, Any] = {}
        for nom, type_ in attendus.items():
            if nom in params:
                sortie[nom] = TypeAdapter(type_).validate_python(params[nom])
            elif sig.parameters[nom].default is inspect.Parameter.empty:
                raise TypeError(f"{self.nom} : paramètre obligatoire « {nom} » absent")
        return sortie


@dataclass
class ContexteAgent:
    """Contexte d'une exécution. ``tenant_id`` est fixé ici et nulle part ailleurs."""

    db: Any
    tenant_id: str | None
    agent: str = ""
    execution_id: str = field(default_factory=lambda: nouvel_id("agx"))
    horloge: Callable[[], datetime] = maintenant
    journal: JournalAgents = field(default_factory=JournalAgents)
    llm: Any = None  # RedacteurLLM ou None (gabarits déterministes)
    reseau: bool = False
    services: dict[str, Any] = field(default_factory=dict)

    @property
    def acteur(self) -> Acteur:
        return Acteur.systeme(f"agent:{self.agent}")

    def maintenant(self) -> datetime:
        return self.horloge()


@dataclass
class RapportAgent:
    agent: str
    execution_id: str
    tenant_id: str | None
    propositions: list[str] = field(default_factory=list)  # brouillons sortants (identifiants)
    alertes: list[str] = field(default_factory=list)  # clés d'alerte
    jobs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # constats de l'agent (sans contenu de document)
    redaction: str = "gabarit"  # gabarit | llm

    def en_dict(self) -> dict[str, Any]:
        return {"agent": self.agent, "execution_id": self.execution_id, "tenant_id": self.tenant_id,
                "propositions": self.propositions, "alertes": self.alertes, "jobs": self.jobs,
                "notes": self.notes, "redaction": self.redaction}


class Agent:
    """Agent d'exploitation. Sous-classes : ``nom``, ``role``, ``outils``, ``plateforme``, ``_executer``."""

    nom: ClassVar[str] = ""
    role: ClassVar[str] = ""
    outils: ClassVar[tuple[str, ...]] = ()
    #: Agent de plateforme (aucun client) : ``veille``.
    plateforme: ClassVar[bool] = False
    #: Période du planificateur : ``heure``, ``jour``, ``semaine`` ou ``None`` (sur événement seulement).
    periode: ClassVar[str | None] = "jour"

    def __init__(self, catalogue: dict[str, Outil] | None = None) -> None:
        from .outils import CATALOGUE

        cat = catalogue if catalogue is not None else CATALOGUE
        manquants = [n for n in self.outils if n not in cat]
        if manquants:
            raise ValueError(f"outils inconnus pour {self.nom} : {manquants}")
        self._outils = {n: cat[n] for n in self.outils}

    def appeler(self, ctx: ContexteAgent, nom: str, **params: Any) -> Any:
        if nom not in self._outils:
            ctx.journal.ecrire(agent=self.nom, execution_id=ctx.execution_id, tenant_id=ctx.tenant_id,
                               evenement="refus_outil", outil=nom, quand=ctx.maintenant())
            raise OutilNonAutorise(f"l'agent {self.nom} n'a pas accès à l'outil {nom}")
        outil = self._outils[nom]
        valides = outil.valider(params)
        resultat = outil.fn(ctx, **valides)
        ctx.journal.ecrire(agent=self.nom, execution_id=ctx.execution_id, tenant_id=ctx.tenant_id,
                           evenement="outil", outil=nom, params=resumer(valides), resultat=resumer(resultat),
                           quand=ctx.maintenant())
        return resultat

    def executer(self, ctx: ContexteAgent, **params: Any) -> RapportAgent:
        if self.plateforme and ctx.tenant_id is not None:
            raise ValueError(f"{self.nom} est un agent de plateforme (sans client)")
        if not self.plateforme and not ctx.tenant_id:
            raise ValueError(f"{self.nom} exige un client")
        ctx.agent = self.nom
        rapport = RapportAgent(self.nom, ctx.execution_id, ctx.tenant_id)
        ctx.journal.ecrire(agent=self.nom, execution_id=ctx.execution_id, tenant_id=ctx.tenant_id,
                           evenement="debut", params=resumer(params), quand=ctx.maintenant())
        try:
            self._executer(ctx, rapport, **params)
        except Exception as exc:
            ctx.journal.ecrire(agent=self.nom, execution_id=ctx.execution_id, tenant_id=ctx.tenant_id,
                               evenement="erreur", erreur=type(exc).__name__, quand=ctx.maintenant())
            raise
        ctx.journal.ecrire(agent=self.nom, execution_id=ctx.execution_id, tenant_id=ctx.tenant_id,
                           evenement="fin", propositions=len(rapport.propositions), alertes=len(rapport.alertes),
                           jobs=len(rapport.jobs), redaction=rapport.redaction, quand=ctx.maintenant())
        return rapport

    def _executer(self, ctx: ContexteAgent, rapport: RapportAgent, **params: Any) -> None:  # pragma: no cover
        raise NotImplementedError

    @classmethod
    def description(cls) -> dict[str, Any]:
        return {"nom": cls.nom, "role": cls.role, "outils": list(cls.outils), "plateforme": cls.plateforme,
                "periode": cls.periode}
