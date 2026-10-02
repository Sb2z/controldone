"""Agent ``litiges`` : suivi des dossiers de demande d'avoir (§17).

- crée les brouillons de relance échus (J+15, J+30, J+45 par défaut), **adressés au client** ;
- détecte les litiges sans activité et propose au fondateur les prochaines étapes (alerte) ;
- signale les dossiers préparés en attente de validation et les dossiers crédités à clore ;
- demande la préparation d'un dossier (job ``preparer_reclamation``) quand des écarts validés ne sont
  repris dans aucun dossier actif — le dossier préparé reste un brouillon que le fondateur valide.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .base import Agent, ContexteAgent, RapportAgent

__all__ = ["PROCHAINES_ETAPES", "AgentLitiges"]

PROCHAINES_ETAPES = (
    "Prochaines étapes proposées : (1) demander au client si un avoir ou une réponse du transitaire a été "
    "reçu ; (2) si le transitaire conteste, enregistrer la contestation et ses motifs ; (3) sinon, proposer "
    "au client une nouvelle relance de sa part ou la clôture du dossier avec un motif."
)
DELAI_VALIDATION_JOURS = 7


def _date(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


class AgentLitiges(Agent):
    nom = "litiges"
    role = ("Suit les litiges : relances au client, litiges sans activité, dossiers à valider ou à clore, "
            "écarts validés à reprendre dans un dossier de demande d'avoir.")
    outils = ("lire_client", "planifier_relances", "lister_litiges", "lister_litiges_inactifs",
              "lister_ecarts_a_reclamer", "signaler_alerte", "demander_job")
    periode = "jour"

    def _executer(self, ctx: ContexteAgent, rapport: RapportAgent) -> None:
        now = ctx.maintenant()
        rapport.propositions += self.appeler(ctx, "planifier_relances")
        client = self.appeler(ctx, "lire_client")
        jours = client["litiges_inactivite_jours"]
        for rec_id in self.appeler(ctx, "lister_litiges_inactifs", jours=jours):
            cle = f"litige_inactif:{rec_id}:{now.strftime('%Y-%m')}"
            if self.appeler(ctx, "signaler_alerte", cle=cle, kind="litige_inactif",
                            message=f"Litige {rec_id} sans activité depuis plus de {jours} jours. {PROCHAINES_ETAPES}",
                            details={"reclamation_id": rec_id, "jours": jours}):
                rapport.alertes.append(cle)
        for lit in self.appeler(ctx, "lister_litiges"):
            cree = _date(lit["cree_le"])
            if lit["statut"] == "brouillon" and cree and cree < now - timedelta(days=DELAI_VALIDATION_JOURS):
                cle = f"litige_a_valider:{lit['id']}"
                if self.appeler(ctx, "signaler_alerte", cle=cle, kind="litige_a_valider",
                                message=f"Dossier de demande d'avoir {lit['id']} préparé depuis plus de "
                                        f"{DELAI_VALIDATION_JOURS} jours, en attente de votre validation.",
                                details={"reclamation_id": lit["id"]}):
                    rapport.alertes.append(cle)
            if lit["statut"] == "credite":
                cle = f"litige_a_clore:{lit['id']}"
                if self.appeler(ctx, "signaler_alerte", cle=cle, kind="litige_a_clore",
                                message=f"Dossier {lit['id']} entièrement crédité : il peut être clos.",
                                details={"reclamation_id": lit["id"]}):
                    rapport.alertes.append(cle)
        for groupe in self.appeler(ctx, "lister_ecarts_a_reclamer"):
            tra = groupe["transitaire_id"]
            job = self.appeler(ctx, "demander_job", kind="preparer_reclamation", payload={"transitaire_id": tra},
                               cle=f"preparer_reclamation:{ctx.tenant_id}:{tra}:{now.strftime('%Y-%m-%d')}")
            rapport.jobs.append(job)
            cle = f"litige_a_preparer:{tra}:{now.strftime('%Y-%m-%d')}"
            if self.appeler(ctx, "signaler_alerte", cle=cle, kind="litige_a_preparer",
                            message=f"{groupe['nombre']} écart(s) validé(s) ({groupe['total']} EUR) pour le "
                                    f"transitaire {tra} : dossier de demande d'avoir en préparation, à valider.",
                            details={"transitaire_id": tra, "nombre": groupe["nombre"]}):
                rapport.alertes.append(cle)
