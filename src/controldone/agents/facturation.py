"""Agent ``facturation`` : propose les factures (brouillons ``facture_emise``) que le fondateur valide.

- **Diagnostic** (offre ``diagnostic``) : un forfait (390 EUR par défaut, ``reglages["diagnostic_prix_eur"]``)
  une fois le premier lot traité — une seule proposition par client ;
- **Abonnement** (offre ``continu``) : une proposition par mois (99 EUR par défaut,
  ``reglages["abonnement_mensuel_eur"]``) ;
- **Commissions** (§17.4) : filet de sécurité — toute ligne de commission d'un litige sans brouillon de
  facture en reçoit un (même clé d'idempotence que le service des litiges : jamais de doublon).
"""

from __future__ import annotations

from decimal import Decimal

from controldone.litiges import commission_cle

from .base import Agent, ContexteAgent, RapportAgent

__all__ = ["AgentFacturation"]


class AgentFacturation(Agent):
    nom = "facturation"
    role = "Propose les factures de diagnostic, d'abonnement et de commission (brouillons à valider)."
    outils = ("lire_client", "lister_lots", "lister_litiges", "proposer_facture")
    periode = "jour"

    def _executer(self, ctx: ContexteAgent, rapport: RapportAgent) -> None:
        client = self.appeler(ctx, "lire_client")
        if client["offre"] == "diagnostic":
            lots = self.appeler(ctx, "lister_lots", statut="traite")
            if lots:
                out = self.appeler(ctx, "proposer_facture", type_facture="diagnostic",
                                   lignes=[{"libelle": f"Diagnostic de cohérence documentaire — lot du "
                                                       f"{(lots[0]['recu_le'] or '')[:10]}",
                                            "prix_unitaire_ht": client["diagnostic_prix_eur"]}],
                                   cle=f"facture:diagnostic:{ctx.tenant_id}",
                                   references={"lot_id": lots[0]["id"]})
                rapport.propositions.append(out)
        elif client["offre"] == "continu":
            mois = ctx.maintenant().strftime("%Y-%m")
            out = self.appeler(ctx, "proposer_facture", type_facture="abonnement",
                               lignes=[{"libelle": f"Contrôle continu — abonnement {mois}",
                                        "prix_unitaire_ht": client["abonnement_mensuel_eur"]}],
                               cle=f"facture:abonnement:{ctx.tenant_id}:{mois}", references={"mois": mois})
            rapport.propositions.append(out)
        for lit in self.appeler(ctx, "lister_litiges"):
            for c in lit["commissions"]:
                if c["outbox_id"]:
                    continue
                pct = f"{(Decimal(c['taux']) * 100).normalize():f}"
                out = self.appeler(ctx, "proposer_facture", type_facture="commission",
                                   lignes=[{"libelle": f"Commission de {pct} % sur avoir obtenu ({c['avoir_id']}, "
                                                       f"base {c['base']} EUR)", "prix_unitaire_ht": c["montant"]}],
                                   cle=commission_cle(ctx.tenant_id or "", c["avoir_id"]),
                                   references={"avoir_id": c["avoir_id"], "reclamation_id": lit["id"]})
                rapport.propositions.append(out)
