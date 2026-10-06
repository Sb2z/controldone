"""Registre des agents d'exploitation."""

from __future__ import annotations

from .accueil import AgentAccueil
from .base import Agent
from .controle import AgentControle
from .facturation import AgentFacturation
from .litiges import AgentLitiges
from .questions_clients import AgentQuestionsClients
from .veille import AgentVeille

__all__ = ["AGENTS", "obtenir_agent"]

AGENTS: dict[str, type[Agent]] = {
    a.nom: a
    for a in (
        AgentAccueil,
        AgentControle,
        AgentLitiges,
        AgentFacturation,
        AgentQuestionsClients,
        AgentVeille,
    )
}


def obtenir_agent(nom: str) -> Agent:
    try:
        return AGENTS[nom]()
    except KeyError as exc:
        raise ValueError(f"agent inconnu : {nom}") from exc
