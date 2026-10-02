"""Handler de job ``preparer_reclamation`` (demandé par l'agent ``litiges``) : prépare un dossier de
demande d'avoir **brouillon** pour un transitaire ; le fondateur le valide avant toute mise à disposition."""

from __future__ import annotations

from typing import Any

from controldone.auth.roles import Acteur
from controldone.jobs.registre import ErreurDefinitive, JobContext, handler

from .service import ServiceLitiges

__all__ = ["preparer_reclamation"]


@handler("preparer_reclamation")
def preparer_reclamation(ctx: JobContext) -> dict[str, Any]:
    tra = ctx.payload.get("transitaire_id")
    if not ctx.tenant_id or not tra:
        raise ErreurDefinitive("payload invalide (client et transitaire obligatoires)")
    service = ServiceLitiges(ctx.db, vault=ctx.services.get("vault"))
    try:
        d = service.preparer(Acteur.systeme("litiges"), ctx.tenant_id, tra)
    except ValueError:
        return {"prepare": False, "motif": "aucun_ecart"}
    return {"prepare": True, "reclamation_id": d.id, "lignes": len(d.lignes)}
