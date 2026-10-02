"""Comptes utilisateurs et clés d'API : accès plateforme (avant tout périmètre client).

Les fonctions renvoient des instantanés détachés (``CompteInfo``, ``CleApiInfo``), jamais des objets ORM.
Le hachage des mots de passe et des clés est fait par ``controldone.auth`` ; ici on ne stocke que des
empreintes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update

from controldone.auth.roles import ROLES_CLIENT, Acteur, Role
from controldone.storage.audit import journaliser
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import CleApi, Membership, User

__all__ = [
    "CleApiInfo",
    "CompteInfo",
    "changer_mot_de_passe",
    "cle_api_par_prefixe",
    "creer_utilisateur",
    "desactiver_utilisateur",
    "enregistrer_totp",
    "marquer_connexion",
    "marquer_usage_cle",
    "roles_utilisateur",
    "utilisateur",
    "utilisateur_par_email",
    "utiliser_pas_totp",
]


@dataclass(frozen=True)
class CompteInfo:
    id: str
    email: str
    role: str
    mot_de_passe_hash: str
    totp_secret_chiffre: str | None
    totp_dernier_pas: int | None
    actif: bool


@dataclass(frozen=True)
class CleApiInfo:
    id: str
    tenant_id: str
    prefixe: str
    hash: str
    role: str
    revoquee_le: datetime | None


def _info(u: User) -> CompteInfo:
    return CompteInfo(u.id, u.email, u.role, u.mot_de_passe_hash, u.totp_secret_chiffre, u.totp_dernier_pas,
                      u.actif)


def _email(email: str) -> str:
    return email.strip().lower()


def creer_utilisateur(db: Database, *, user_id: str, email: str, mot_de_passe_hash: str, role: Role,
                      acteur: Acteur, nom: str | None = None) -> CompteInfo:
    """Création d'un compte. Fondateur : tout rôle ; ``client_admin`` : rôles client seulement (le
    rattachement au client se fait ensuite par ``TenantScope.ajouter_membre``)."""
    role = Role(role)
    if role is Role.systeme:
        raise AccesRefuse("rôle système non attribuable")
    if acteur.role is Role.client_admin:
        if role not in ROLES_CLIENT:
            raise AccesRefuse("un administrateur client ne crée que des comptes client")
    elif acteur.role is not Role.fondateur:
        raise AccesRefuse("création de compte refusée")
    with db.transaction_systeme() as s:
        u = User(id=user_id, email=_email(email), nom=nom, role=role.value, mot_de_passe_hash=mot_de_passe_hash)
        s.add(u)
        s.flush()
        journaliser(s, actor=acteur.id, role=acteur.role.value, action="creer_utilisateur",
                    tenant_id=acteur.tenant_id, target=f"users:{user_id}", ip=acteur.ip,
                    details={"role": role.value})
        return _info(u)


def utilisateur_par_email(db: Database, email: str) -> CompteInfo | None:
    with db.transaction_systeme() as s:
        u = s.execute(select(User).where(User.email == _email(email))).scalar_one_or_none()
        return _info(u) if u else None


def utilisateur(db: Database, user_id: str) -> CompteInfo | None:
    with db.transaction_systeme() as s:
        u = s.get(User, user_id)
        return _info(u) if u else None


def roles_utilisateur(db: Database, user_id: str) -> dict[str, str]:
    """Clients dont l'utilisateur est membre -> rôle."""
    with db.transaction_systeme() as s:
        lignes = s.execute(select(Membership).where(Membership.user_id == user_id)).scalars()
        return {m.tenant_id: m.role for m in lignes}


def enregistrer_totp(db: Database, user_id: str, secret_chiffre: str | None, *, acteur: Acteur) -> None:
    if acteur.role is not Role.fondateur and acteur.id != user_id:
        raise AccesRefuse("second facteur : modification refusée")
    with db.transaction_systeme() as s:
        u = s.get(User, user_id)
        if u is None:
            raise AccesRefuse("introuvable")
        u.totp_secret_chiffre, u.totp_dernier_pas = secret_chiffre, None
        journaliser(s, actor=acteur.id, role=acteur.role.value, action="enregistrer_totp",
                    target=f"users:{user_id}", ip=acteur.ip, details={"actif": secret_chiffre is not None})


def utiliser_pas_totp(db: Database, user_id: str, pas: int) -> bool:
    """Consomme un pas TOTP (anti-rejeu) : ``False`` si un pas égal ou ultérieur a déjà servi."""
    with db.transaction_systeme() as s:
        res = s.execute(
            update(User)
            .where(User.id == user_id)
            .where((User.totp_dernier_pas.is_(None)) | (User.totp_dernier_pas < pas))
            .values(totp_dernier_pas=pas)
        )
        return res.rowcount == 1


def marquer_connexion(db: Database, user_id: str, *, ip: str | None = None, role: str = "") -> None:
    with db.transaction_systeme() as s:
        u = s.get(User, user_id)
        if u is not None:
            u.derniere_connexion = maintenant()
            journaliser(s, actor=user_id, role=role or u.role, action="connexion", target=f"users:{user_id}",
                        ip=ip)


def cle_api_par_prefixe(db: Database, prefixe: str) -> CleApiInfo | None:
    with db.transaction_systeme() as s:
        c = s.execute(select(CleApi).where(CleApi.prefixe == prefixe)).scalar_one_or_none()
        if c is None:
            return None
        return CleApiInfo(c.id, c.tenant_id, c.prefixe, c.hash, c.role, c.revoquee_le)


def marquer_usage_cle(db: Database, cle_id: str) -> None:
    with db.transaction_systeme() as s:
        c = s.get(CleApi, cle_id)
        if c is not None:
            c.dernier_usage = maintenant()


def changer_mot_de_passe(db: Database, user_id: str, nouveau_hash: str, *, acteur: Acteur) -> None:
    """Nouveau mot de passe (empreinte Argon2 calculée par ``controldone.auth``) : l'utilisateur lui-même
    ou le fondateur."""
    if acteur.role is not Role.fondateur and acteur.id != user_id:
        raise AccesRefuse("changement de mot de passe refusé")
    with db.transaction_systeme() as s:
        u = s.get(User, user_id)
        if u is None:
            raise AccesRefuse("introuvable")
        u.mot_de_passe_hash = nouveau_hash
        journaliser(s, actor=acteur.id, role=acteur.role.value, action="changer_mot_de_passe",
                    tenant_id=acteur.tenant_id, target=f"users:{user_id}", ip=acteur.ip)


def desactiver_utilisateur(db: Database, user_id: str, *, acteur: Acteur, actif: bool = False) -> None:
    """Désactive (ou réactive) un compte : connexion refusée et sessions en cours rejetées à la requête
    suivante (``web.securite.acteur_de``). Fondateur seulement."""
    if acteur.role is not Role.fondateur:
        raise AccesRefuse("désactivation d'un compte réservée au fondateur")
    with db.transaction_systeme() as s:
        u = s.get(User, user_id)
        if u is None:
            raise AccesRefuse("introuvable")
        u.actif = bool(actif)
        journaliser(s, actor=acteur.id, role=acteur.role.value, action="activer_utilisateur" if actif
                    else "desactiver_utilisateur", target=f"users:{user_id}", ip=acteur.ip)
