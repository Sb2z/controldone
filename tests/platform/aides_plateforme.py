"""Constantes partagées des tests de plateforme (données fictives)."""

from __future__ import annotations

from datetime import UTC, datetime

from controldone.auth.roles import Acteur, Role

FONDATEUR = Acteur("usr_fondateur", Role.fondateur)
SYSTEME = Acteur.systeme("tests")
MDP = "phrase-de-passe-FICTIVE-123"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
