"""Handler ``controle_avant_paiement`` : traite le lot d'une facture reçue d'une plateforme agréée
(handler ``traiter_lot``, idempotent), puis propose au client le statut « en litige » si des écarts sont
constatés (brouillon ``statut_litige_pa``).

Si le job ``traiter_lot`` du même lot est **en file** ou **en cours** chez un autre worker (bail valide), le
pipeline n'est pas exécuté une seconde fois en parallèle (double coût IA) : le job est reporté (``Reporter``,
D-1321) et reprend une fois le lot traité. Le pipeline n'est lancé ici que si ce job n'existe pas ou est mort."""

from __future__ import annotations

from typing import Any

from controldone.auth.roles import Acteur
from controldone.jobs.registre import ErreurDefinitive, JobContext, Reporter, handler
from controldone.storage.coltypes import maintenant
from controldone.storage.file_jobs import JobStore
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
        en_cours = JobStore(ctx.db).par_cle(f"traiter_lot:{ctx.tenant_id}:{lot_id}")
        if en_cours is not None and en_cours.statut == "pending":
            raise Reporter("traitement du lot en file", delai_s=15)
        if (en_cours is not None and en_cours.statut == "running" and en_cours.locked_until is not None
                and en_cours.locked_until > maintenant()):
            raise Reporter("traitement du lot en cours", delai_s=30)
        traiter_lot(ctx)
    out = proposer_statut_litige(ctx.db, ctx.tenant_id, lot_id, pa_id, numero=ctx.payload.get("numero"),
                                 date_echeance=ctx.payload.get("date_echeance"))
    return {"lot_id": lot_id, "statut_litige_propose": out is not None, "outbox_id": out}
