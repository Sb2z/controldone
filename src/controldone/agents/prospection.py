"""Agent ``prospection`` (plateforme, quotidien) : prépare les étapes suivantes **échues** des séquences de
prospection, en brouillon dans la file de validation (D-5008).

Il n'approuve ni n'envoie rien. Les règles d'arrêt (réponse, opposition, rebond, changement de statut, brouillon
refusé), la liste d'exclusion, la liste d'opposition et le plafond quotidien sont appliqués par le service de
prospection, que l'agent appelle par son seul outil. Aucun modèle de langage : les textes viennent des modèles
de la séquence et de faits enregistrés.
"""

from __future__ import annotations

from .base import Agent, ContexteAgent, RapportAgent

__all__ = ["AgentProspection"]


class AgentProspection(Agent):
    nom = "prospection"
    role = (
        "Prépare, en brouillon pour la file de validation, les étapes suivantes échues des séquences de "
        "prospection du fondateur (aucun envoi, aucune approbation)."
    )
    outils = ("preparer_etapes_prospection",)
    plateforme = True
    periode = "jour"

    def _executer(self, ctx: ContexteAgent, rapport: RapportAgent) -> None:
        ids = self.appeler(ctx, "preparer_etapes_prospection")
        rapport.propositions += list(ids)
        rapport.notes.append(f"etapes_preparees:{len(ids)}")
