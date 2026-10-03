"""Handler ``referentiel_recalculer`` : recalcul périodique du référentiel anonymisé (job de plateforme,
clé recommandée ``referentiel:<AAAA-MM>``, une par mois)."""

from __future__ import annotations

from typing import Any

from controldone.jobs.registre import JobContext, handler

from .export import recalculer

__all__ = ["referentiel_recalculer"]


@handler("referentiel_recalculer")
def referentiel_recalculer(ctx: JobContext) -> dict[str, Any]:
    return recalculer(ctx.db, dossier_sortie=ctx.payload.get("dossier_sortie"))
