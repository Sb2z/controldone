"""Agent ``controle`` : déclenche le traitement des lots reçus et signale au fondateur les dossiers dont
l'extraction est peu fiable (valeurs lues de confiance inférieure au seuil, défaut 0,70 = ``C_MIN_UTILE``
de §8.5). Il ne modifie aucune valeur, aucun niveau, aucun montant : il demande des jobs et émet des
alertes."""

from __future__ import annotations

from .base import Agent, ContexteAgent, RapportAgent

__all__ = ["AgentControle"]


class AgentControle(Agent):
    nom = "controle"
    role = (
        "Déclenche le traitement des lots reçus (job traiter_lot) et signale au fondateur les dossiers "
        "à revoir parce que des valeurs ont été lues avec une confiance faible."
    )
    outils = (
        "lire_client",
        "lister_lots",
        "demander_job",
        "lister_extractions_peu_fiables",
        "signaler_alerte",
    )
    periode = "heure"

    def _executer(self, ctx: ContexteAgent, rapport: RapportAgent, seuil: float | None = None) -> None:
        for lot in self.appeler(ctx, "lister_lots", statut="recu"):
            job = self.appeler(
                ctx,
                "demander_job",
                kind="traiter_lot",
                payload={"lot_id": lot["id"]},
                cle=f"traiter_lot:{ctx.tenant_id}:{lot['id']}",
            )
            rapport.jobs.append(job)
        if seuil is None:
            seuil = self.appeler(ctx, "lire_client")["seuil_confiance_revue"]
        for d in self.appeler(ctx, "lister_extractions_peu_fiables", seuil=seuil):
            cle = f"revue_extraction:{d['dossier_id']}:v{d['version']}"
            message = (
                f"Dossier {d['reference'] or d['dossier_id']} (version {d['version']}) : {d['nombre']} "
                f"valeur(s) lue(s) avec une confiance inférieure à {seuil:.2f}. Revue conseillée avant "
                "validation des constats."
            )
            if self.appeler(
                ctx,
                "signaler_alerte",
                cle=cle,
                kind="revue_extraction",
                message=message,
                details={"dossier_id": d["dossier_id"], "version": d["version"] or 0, "nombre": d["nombre"]},
            ):
                rapport.alertes.append(cle)
