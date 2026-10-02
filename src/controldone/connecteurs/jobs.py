"""Handler ``controle_avant_paiement`` : traite le lot d'une facture reçue d'une plateforme agréée
(handler ``traiter_lot``, idempotent), puis propose au client le statut « en litige » si des écarts sont
constatés (brouillon ``statut_litige_pa``)."""

from __future__ import annotations

from typing import Any

from controldone.auth.roles import Acteur
from controldone.jobs.registre import ErreurDefinitive, JobContext, handler
from controldone.storage.models import Lot

from .plateforme_agreee import proposer_statut_litige

__all__ = ["controle_avant_paiement"]


@handler("controle_avant_paiement")
def controle_avant_paiement(ctx: JobContext) -> dict[str, Any]:
    from controldone.jobs.handlers import traiter_lot

    lot_id, pa_id = ctx.payload.get("lot_id"), ctx.payload.get("facture_pa_id")
    if not ctx.tenant_id or not lot_id or not pa_id:
        raise ErreurDefinitive("payload invalide (client, lot et facture PA obligatoires)")
    with ctx.db.tenant(ctx.tenant_id, Acteur.systeme("controle_avant_paiement"), lecture=True) as sc:
        deja = sc.obtenir(Lot, lot_id).statut == "traite"
    if not deja:
        traiter_lot(ctx)
    out = proposer_statut_litige(ctx.db, ctx.tenant_id, lot_id, pa_id, numero=ctx.payload.get("numero"),
                                 date_echeance=ctx.payload.get("date_echeance"))
    return {"lot_id": lot_id, "statut_litige_propose": out is not None, "outbox_id": out}
