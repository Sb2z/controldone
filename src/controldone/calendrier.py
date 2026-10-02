"""Calendrier de facturation (D-1308) : **une** frontière de mois, celle d'Europe/Paris.

Tout ce qui découpe par mois (échéance d'abonnement, plafond de coût IA, page « Finances », agent de
facturation, webhook Stripe) passe par ``mois_paris`` : la première heure du mois (heure de Paris) ne
donne plus deux clés d'idempotence différentes pour une même échéance.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

__all__ = ["PARIS", "aujourdhui_paris", "maintenant_paris", "mois_paris"]

PARIS = ZoneInfo("Europe/Paris")


def maintenant_paris(now: datetime | None = None) -> datetime:
    """Instant ``now`` (défaut : maintenant) exprimé à Paris ; un instant naïf est lu comme UTC."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(PARIS)


def aujourdhui_paris(now: datetime | None = None) -> date:
    return maintenant_paris(now).date()


def mois_paris(now: datetime | date | None = None) -> str:
    """``AAAA-MM`` du mois civil de Paris contenant ``now`` (une ``date`` est prise telle quelle)."""
    if isinstance(now, date) and not isinstance(now, datetime):
        return now.strftime("%Y-%m")
    return maintenant_paris(now).strftime("%Y-%m")
