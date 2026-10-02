"""Clés d'API par client : ``cdk_<préfixe>_<secret>`` ; seule l'empreinte SHA-256 du secret est stockée,
la clé complète n'est montrée **qu'une fois** à la création. Le préfixe (public) sert à retrouver la clé."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from controldone.auth.roles import Acteur, Role

if TYPE_CHECKING:
    from controldone.storage.db import Database
    from controldone.storage.scope import TenantScope

__all__ = ["CleApiCreee", "creer_cle_api", "empreinte", "revoquer_cle_api", "verifier_cle_api"]


@dataclass(frozen=True)
class CleApiCreee:
    id: str
    prefixe: str
    cle: str  # à afficher une seule fois


def empreinte(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def creer_cle_api(scope: TenantScope, nom: str, *, role: Role = Role.client_admin) -> CleApiCreee:
    prefixe = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    cle_id = "key_" + secrets.token_hex(16)
    scope.creer_cle_api(cle_id, nom, prefixe, empreinte(secret), role)
    return CleApiCreee(id=cle_id, prefixe=prefixe, cle=f"cdk_{prefixe}_{secret}")


def revoquer_cle_api(scope: TenantScope, cle_id: str) -> None:
    scope.revoquer_cle_api(cle_id)


def verifier_cle_api(db: Database, cle: str) -> Acteur | None:
    """Acteur (rôle client, rattaché au client de la clé) si la clé est valide et non révoquée."""
    from controldone.storage.comptes import cle_api_par_prefixe, marquer_usage_cle

    if not cle or not cle.startswith("cdk_"):
        return None
    _, _, reste = cle.partition("_")
    prefixe, sep, secret = reste.partition("_")
    if not sep or not prefixe or not secret:
        return None
    info = cle_api_par_prefixe(db, prefixe)
    attendu = info.hash if info else empreinte("leurre-temps-constant")
    if not hmac.compare_digest(attendu, empreinte(secret)) or info is None or info.revoquee_le is not None:
        return None
    marquer_usage_cle(db, info.id)
    return Acteur(id=f"api:{info.id}", role=Role(info.role), tenant_id=info.tenant_id)
