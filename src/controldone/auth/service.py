"""Ouverture de session : mot de passe + second facteur TOTP obligatoire pour le fondateur."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from functools import cache
from typing import TYPE_CHECKING

from controldone.auth.motdepasse import hacher_mot_de_passe, verifier_mot_de_passe
from controldone.auth.roles import Acteur, Role
from controldone.auth.totp import verifier_totp

if TYPE_CHECKING:
    from controldone.storage.db import Database

__all__ = [
    "EchecAuthentification",
    "acteur_client",
    "authentifier",
    "verifier_mot_de_passe_compte",
    "verifier_second_facteur",
]


@cache
def _leurre() -> str:
    """Empreinte réelle d'un mot de passe aléatoire : un compte inconnu coûte un vrai calcul Argon2."""
    return hacher_mot_de_passe(secrets.token_urlsafe(24))


class EchecAuthentification(PermissionError):
    """Message unique, quel que soit le motif (pas d'énumération des comptes)."""

    def __init__(self) -> None:
        super().__init__("identifiants invalides")


def authentifier(
    db: Database,
    email: str,
    mot_de_passe: str,
    *,
    cles_maitresses: Sequence[bytes],
    code_totp: str | None = None,
    tenant_id: str | None = None,
    ip: str | None = None,
    t: float | None = None,
) -> Acteur:
    """Renvoie l'``Acteur`` authentifié. Rôle client : ``tenant_id`` doit désigner un client dont
    l'utilisateur est membre (s'il n'en a qu'un, il est choisi d'office)."""
    from controldone.storage.cles import dechiffrer_secret
    from controldone.storage.comptes import (
        marquer_connexion,
        roles_utilisateur,
        utilisateur_par_email,
        utiliser_pas_totp,
    )

    compte = utilisateur_par_email(db, email)
    if compte is None:
        verifier_mot_de_passe(_leurre(), mot_de_passe)  # temps comparable
        raise EchecAuthentification()
    if not compte.actif or not verifier_mot_de_passe(compte.mot_de_passe_hash, mot_de_passe):
        raise EchecAuthentification()
    if compte.role == Role.fondateur.value:
        if not compte.totp_secret_chiffre or not code_totp:
            raise EchecAuthentification()
        secret = dechiffrer_secret(cles_maitresses, compte.totp_secret_chiffre)
        pas = verifier_totp(secret, code_totp, t)
        if pas is None or not utiliser_pas_totp(db, compte.id, pas):
            raise EchecAuthentification()
        marquer_connexion(db, compte.id, ip=ip, role=Role.fondateur.value)
        return Acteur(compte.id, Role.fondateur, None, ip)
    roles = roles_utilisateur(db, compte.id)
    if tenant_id is None and len(roles) == 1:
        tenant_id = next(iter(roles))
    if tenant_id is None or tenant_id not in roles:
        raise EchecAuthentification()
    role = Role(roles[tenant_id])
    marquer_connexion(db, compte.id, ip=ip, role=role.value)
    return Acteur(compte.id, role, tenant_id, ip)


def verifier_mot_de_passe_compte(db: Database, email: str, mot_de_passe: str) -> tuple[str, str]:
    """Premier facteur seul (connexion en deux étapes de l'interface web) : renvoie ``(user_id, role)``.
    Même message d'échec et même coût qu'``authentifier``. Ne crée aucune session : pour le fondateur,
    l'appelant exige ensuite ``verifier_second_facteur``."""
    from controldone.storage.comptes import utilisateur_par_email

    compte = utilisateur_par_email(db, email)
    if compte is None:
        verifier_mot_de_passe(_leurre(), mot_de_passe)
        raise EchecAuthentification()
    if not compte.actif or not verifier_mot_de_passe(compte.mot_de_passe_hash, mot_de_passe):
        raise EchecAuthentification()
    return compte.id, compte.role


def verifier_second_facteur(
    db: Database,
    user_id: str,
    code: str,
    *,
    cles_maitresses: Sequence[bytes],
    ip: str | None = None,
    t: float | None = None,
) -> Acteur:
    """Second facteur du fondateur (TOTP, anti-rejeu) après ``verifier_mot_de_passe_compte``."""
    from controldone.storage.cles import dechiffrer_secret
    from controldone.storage.comptes import marquer_connexion, utilisateur, utiliser_pas_totp

    compte = utilisateur(db, user_id)
    if (
        compte is None
        or not compte.actif
        or compte.role != Role.fondateur.value
        or not compte.totp_secret_chiffre
    ):
        raise EchecAuthentification()
    secret = dechiffrer_secret(cles_maitresses, compte.totp_secret_chiffre)
    pas = verifier_totp(secret, code or "", t)
    if pas is None or not utiliser_pas_totp(db, compte.id, pas):
        raise EchecAuthentification()
    marquer_connexion(db, compte.id, ip=ip, role=Role.fondateur.value)
    return Acteur(compte.id, Role.fondateur, None, ip)


def acteur_client(
    db: Database, user_id: str, *, tenant_id: str | None = None, ip: str | None = None
) -> Acteur:
    """Acteur d'un utilisateur client après le premier facteur (son client, s'il n'en a qu'un)."""
    from controldone.storage.comptes import marquer_connexion, roles_utilisateur

    roles = roles_utilisateur(db, user_id)
    if tenant_id is None and len(roles) == 1:
        tenant_id = next(iter(roles))
    if tenant_id is None or tenant_id not in roles:
        raise EchecAuthentification()
    role = Role(roles[tenant_id])
    marquer_connexion(db, user_id, ip=ip, role=role.value)
    return Acteur(user_id, role, tenant_id, ip)
