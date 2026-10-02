"""Journal d'audit append-only chaîné (SPEC §20.1).

Chaque entrée porte ``prev_hash`` (hash de l'entrée précédente, ``"0"*64`` pour la première) et
``hash = sha256(prev_hash | contenu canonique)``. ``prev_hash`` est unique : deux écritures concurrentes
qui liraient la même tête ne peuvent pas créer de fourche (la seconde échoue et est rejouée).
``verifier_chaine`` détecte toute modification, suppression ou insertion au milieu de la chaîne.
Aucun contenu de document dans ``details`` : identifiants, compteurs, motifs courts seulement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controldone.storage.coltypes import maintenant
from controldone.storage.models import AuditLog

__all__ = ["GENESE", "Anomalie", "calculer_hash", "journaliser", "verifier_chaine"]

GENESE = "0" * 64


def _ts_canonique(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def calculer_hash(
    prev_hash: str, *, ts: datetime, actor: str, role: str, tenant_id: str | None, action: str,
    target: str | None, ip: str | None, details: dict[str, Any] | None,
) -> str:
    contenu = json.dumps(
        {
            "ts": _ts_canonique(ts), "actor": actor, "role": role, "tenant": tenant_id, "action": action,
            "target": target, "ip": ip, "details": details or {},
        },
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(f"{prev_hash}|{contenu}".encode()).hexdigest()


def journaliser(
    session: Session,
    *,
    actor: str,
    role: str,
    action: str,
    tenant_id: str | None = None,
    target: str | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
    ts: datetime | None = None,
) -> AuditLog:
    """Ajoute une entrée dans la transaction de ``session`` (atomique avec l'action journalisée)."""
    ts = ts or maintenant()
    details = json.loads(json.dumps(details or {}, default=str))
    for essai in range(3):
        session.flush()
        prev = session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
        prev = prev or GENESE
        h = calculer_hash(prev, ts=ts, actor=actor, role=str(role), tenant_id=tenant_id, action=action,
                          target=target, ip=ip, details=details)
        entree = AuditLog(ts=ts, actor=actor, role=str(role), tenant_id=tenant_id, action=action,
                          target=target, ip=ip, details=details, prev_hash=prev, hash=h)
        try:
            with session.begin_nested():
                session.add(entree)
            return entree
        except IntegrityError:  # écriture concurrente sur la même tête (PostgreSQL) : rejouer
            if essai == 2:
                raise
    raise RuntimeError("inaccessible")  # pragma: no cover


@dataclass(frozen=True)
class Anomalie:
    id: int | None
    motif: str


def verifier_chaine(session: Session) -> list[Anomalie]:
    """Relit tout le journal ; liste vide si la chaîne est intacte."""
    anomalies: list[Anomalie] = []
    prev = GENESE
    for e in session.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        if e.prev_hash != prev:
            anomalies.append(Anomalie(e.id, "chainage rompu (entrée supprimée ou insérée)"))
        attendu = calculer_hash(e.prev_hash, ts=e.ts, actor=e.actor, role=e.role, tenant_id=e.tenant_id,
                                action=e.action, target=e.target, ip=e.ip, details=e.details)
        if attendu != e.hash:
            anomalies.append(Anomalie(e.id, "contenu modifié"))
        prev = e.hash
    return anomalies
