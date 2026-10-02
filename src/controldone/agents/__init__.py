"""Agents d'exploitation (voir ``docs/AGENTS.md``) : ils **proposent** (brouillons sortants, alertes,
demandes de job) et ne décident rien. Agents : ``accueil``, ``controle``, ``litiges``, ``facturation``,
``questions_clients``, ``veille``. Planificateur : ``python -m controldone.agents.planificateur``."""

from controldone.agents.base import Agent, ContexteAgent, Outil, OutilNonAutorise, RapportAgent
from controldone.agents.journal import JournalAgents
from controldone.agents.llm import RedacteurLLM, texte_acceptable
from controldone.agents.outils import CATALOGUE
from controldone.agents.registre import AGENTS, obtenir_agent

__all__ = [
    "AGENTS",
    "CATALOGUE",
    "Agent",
    "ContexteAgent",
    "JournalAgents",
    "Outil",
    "OutilNonAutorise",
    "RapportAgent",
    "RedacteurLLM",
    "obtenir_agent",
    "texte_acceptable",
]
