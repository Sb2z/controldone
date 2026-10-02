"""Agent ``accueil`` : réception d'un nouveau lot.

Vérifie la complétude des dossiers du lot (dossiers incomplets et résultats P1, §9) et, s'il manque des
pièces, rédige un brouillon de courriel « pièces manquantes » au client (validation du fondateur).
Aucun brouillon si le lot est complet. Lots non encore traités : rien (l'agent ``controle`` demande
leur traitement).
"""

from __future__ import annotations

from typing import Any

from controldone.guardrails import AVERTISSEMENT

from .base import Agent, ContexteAgent, RapportAgent

__all__ = ["LIBELLES_PIECES", "AgentAccueil", "corps_pieces_manquantes"]

LIBELLES_PIECES = {
    "facture_commerciale": "la facture commerciale du fournisseur",
    "declaration": "la déclaration en douane (DAU ou export de déclaration)",
    "facture_transitaire": "la facture du transitaire",
    "avoir": "l'avoir du transitaire",
}


def _cles(d: dict[str, Any]) -> str:
    cles = d.get("cles") or {}
    morceaux = []
    for cle, libelle in (("num_facture_transitaire", "facture transitaire"), ("ref_transport", "transport"),
                         ("mrn", "MRN"), ("num_facture_commerciale", "facture commerciale")):
        if cles.get(cle):
            morceaux.append(f"{libelle} {', '.join(cles[cle])}")
    return f" ({' ; '.join(morceaux)})" if morceaux else ""


def corps_pieces_manquantes(date_lot: str, dossiers: list[dict[str, Any]]) -> str:
    lignes = []
    for d in dossiers:
        pieces = ", ".join(LIBELLES_PIECES.get(x, x) for x in d["documents_manquants"]) or "pièce à préciser"
        lignes.append(f"- Dossier {d['reference'] or d['dossier_id']}{_cles(d)} : {pieces}")
    return (
        f"Bonjour,\n\nNous avons bien reçu votre dépôt du {date_lot}. Pour terminer le contrôle de cohérence, "
        "il nous manque les pièces suivantes :\n\n" + "\n".join(lignes) + "\n\n"
        "Vous pouvez les déposer dans votre espace ou les envoyer à votre adresse de dépôt habituelle ; le "
        "contrôle reprendra automatiquement à réception.\n\nBien cordialement,\n\n" + AVERTISSEMENT
    )


class AgentAccueil(Agent):
    nom = "accueil"
    role = ("Accueille chaque nouveau lot : vérifie la complétude des dossiers (P1) et propose au fondateur "
            "un courriel « pièces manquantes » au client.")
    outils = ("lister_lots", "lire_dossiers_du_lot", "proposer_courriel_client")
    periode = "heure"

    def _executer(self, ctx: ContexteAgent, rapport: RapportAgent, lot_id: str | None = None) -> None:
        lots = self.appeler(ctx, "lister_lots", statut="traite")
        if lot_id is not None:
            lots = [x for x in lots if x["id"] == lot_id]
        for lot in lots:
            dossiers = self.appeler(ctx, "lire_dossiers_du_lot", lot_id=lot["id"])
            incomplets = [d for d in dossiers if d["incomplet"] and d["documents_manquants"]]
            if not incomplets:
                rapport.notes.append(f"lot_complet:{lot['id']}")
                continue
            date_lot = (lot["recu_le"] or "")[:10]
            if len(date_lot) == 10:
                date_lot = f"{date_lot[8:10]}/{date_lot[5:7]}/{date_lot[0:4]}"
            out = self.appeler(ctx, "proposer_courriel_client",
                               objet="Pièces manquantes pour terminer le contrôle de votre dépôt",
                               corps=corps_pieces_manquantes(date_lot, incomplets),
                               cle=f"accueil:pieces_manquantes:{ctx.tenant_id}:{lot['id']}",
                               donnees={"lot_id": lot["id"], "dossiers": [d["dossier_id"] for d in incomplets]})
            rapport.propositions.append(out)
