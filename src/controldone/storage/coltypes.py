"""Types de colonnes portables SQLite / PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.types import TypeDecorator

__all__ = ["DecimalTexte", "UTCDateTime", "maintenant"]


def maintenant() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Horodatage toujours en UTC : stocké sans fuseau (UTC), relu avec ``tzinfo=UTC``.
    Un horodatage naïf est refusé (ambigu)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError("UTCDateTime attend un datetime")
        if value.tzinfo is None:
            raise ValueError("horodatage naïf refusé : préciser le fuseau (UTC)")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class DecimalTexte(TypeDecorator):
    """Montant exact stocké en texte (jamais de flottant ; SQLite n'a pas de décimal natif)."""

    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("montant flottant refusé : utiliser Decimal")
        return str(Decimal(value))

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return None if value is None else Decimal(value)
