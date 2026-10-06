"""État de sécurité partagé entre processus (niveau plateforme, **sans** ``TenantMixin``) — D-3201, D-3202.

- ``debit_compteurs`` : seaux à jetons de la limitation de débit (connexion par adresse IP et par compte,
  second facteur, clés d'API). Partagés par tous les processus qui ouvrent la base, conservés au redémarrage.
  La clé est ``<portée>:<HMAC-SHA256>`` de l'identifiant (adresse, courriel, préfixe de clé) : aucune adresse
  ni aucun courriel en clair dans la table (minimisation). Table **bornée** : une ligne expire quand son seau
  est de nouveau plein (elle ne porte alors plus aucune information) ; ``purger_debit`` supprime les lignes
  expirées puis, au-delà de ``max_lignes``, les plus proches de l'expiration.
- ``sessions_revoquees`` : révocations de sessions (déconnexion d'un ``sid`` ; « toutes les sessions de cet
  utilisateur ouvertes avant t » au changement de mot de passe). Une ligne expire quand aucun jeton qu'elle
  vise ne peut plus être valide (durée absolue de session).

Mise à jour atomique : sous SQLite, chaque transaction commence par ``BEGIN IMMEDIATE`` (un seul écrivain) ;
sous PostgreSQL, la ligne est lue ``FOR UPDATE`` et une insertion concurrente (clé primaire) est rejouée.
Horloge : secondes depuis l'époque (``time.time``), commune aux processus.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Float, String, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from controldone.storage.audit import journaliser
from controldone.storage.db import Database
from controldone.storage.models import Base

__all__ = [
    "CompteurDebit",
    "LigneDebit",
    "RevocationSession",
    "assurer_tables_securite",
    "consommer_jetons",
    "crediter_jetons",
    "effacer_debit",
    "jetons_disponibles",
    "lister_debit",
    "purger_debit",
    "purger_revocations",
    "revoquer_session",
    "revoquer_sessions_utilisateur",
    "session_revoquee",
]


class CompteurDebit(Base):
    __tablename__ = "debit_compteurs"

    #: ``<portée>:<hmac hex>`` (portée : nom du limiteur, ex. ``connexion_ip``).
    cle: Mapped[str] = mapped_column(String(120), primary_key=True)
    portee: Mapped[str] = mapped_column(String(40), index=True)
    jetons: Mapped[float] = mapped_column(Float)
    #: Dernière mise à jour (époque, secondes).
    maj: Mapped[float] = mapped_column(Float)
    #: Instant où le seau est de nouveau plein : au-delà, la ligne équivaut à son absence.
    expire: Mapped[float] = mapped_column(Float, index=True)


class RevocationSession(Base):
    __tablename__ = "sessions_revoquees"

    #: ``sid:<identifiant de session>`` ou ``user:<identifiant d'utilisateur>``.
    cle: Mapped[str] = mapped_column(String(120), primary_key=True)
    #: ``user:`` : sessions **commencées** strictement avant cet instant révoquées ; ``sid:`` : 0.
    apres: Mapped[float] = mapped_column(Float, default=0.0)
    expire: Mapped[float] = mapped_column(Float, index=True)


_TABLES = (CompteurDebit.__table__, RevocationSession.__table__)


def assurer_tables_securite(db: Database) -> None:
    """Crée les deux tables si elles manquent (base créée par une version antérieure, sans migration : ce sont
    des tables nouvelles, jamais des colonnes ajoutées)."""
    for table in _TABLES:
        table.create(db.engine, checkfirst=True)


# --- limitation de débit ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LigneDebit:
    cle: str
    portee: str
    jetons: float
    expire: float


def _jetons_courants(ligne: CompteurDebit | None, capacite: float, par_seconde: float, maintenant: float) -> float:
    if ligne is None or ligne.expire <= maintenant:
        return capacite
    return min(capacite, ligne.jetons + max(0.0, maintenant - ligne.maj) * par_seconde)


def _ecrire(s, ligne: CompteurDebit | None, cle: str, portee: str, jetons: float, capacite: float,
            par_seconde: float, maintenant: float) -> None:
    expire = maintenant + max(0.0, capacite - jetons) / par_seconde
    if ligne is None:
        s.add(CompteurDebit(cle=cle, portee=portee, jetons=jetons, maj=maintenant, expire=expire))
    else:
        ligne.jetons, ligne.maj, ligne.expire = jetons, maintenant, expire


def _modifier(db: Database, cle: str, portee: str, capacite: float, par_seconde: float, maintenant: float,
              delta: float, *, conditionnel: bool) -> tuple[bool, float]:
    """Ajoute ``delta`` jetons (négatif : consommation) au seau, de façon atomique. ``conditionnel`` : refus (et
    aucune écriture) si le seau n'a pas assez de jetons."""
    for essai in range(3):
        try:
            with db.transaction_systeme() as s:
                ligne = s.execute(select(CompteurDebit).where(CompteurDebit.cle == cle)
                                  .with_for_update()).scalar_one_or_none()
                jetons = _jetons_courants(ligne, capacite, par_seconde, maintenant)
                if conditionnel and jetons + delta < 0:
                    return False, jetons
                jetons = min(capacite, jetons + delta)
                if ligne is None and jetons >= capacite:
                    return True, jetons  # seau plein : rien à mémoriser
                _ecrire(s, ligne, cle, portee, jetons, capacite, par_seconde, maintenant)
                return True, jetons
        except IntegrityError:  # insertion concurrente de la même clé (PostgreSQL) : on relit
            if essai == 2:
                raise
    raise AssertionError("inatteignable")


def consommer_jetons(db: Database, cle: str, *, portee: str, capacite: float, par_seconde: float, cout: float,
                     maintenant: float) -> tuple[bool, float]:
    """``(autorisé, jetons restants)`` ; consomme ``cout`` jetons si le seau en a assez."""
    return _modifier(db, cle, portee, capacite, par_seconde, maintenant, -cout, conditionnel=True)


def crediter_jetons(db: Database, cle: str, *, portee: str, capacite: float, par_seconde: float, cout: float,
                    maintenant: float) -> None:
    """Rend ``cout`` jetons (sans dépasser la capacité) — ex. connexion réussie."""
    _modifier(db, cle, portee, capacite, par_seconde, maintenant, cout, conditionnel=False)


def _lecture(db: Database):
    """Session de lecture (transaction différée : ne prend pas le verrou d'écriture SQLite). Tables de plateforme
    sans données client : le garde du cloisonnement ne s'applique pas."""
    return db.session(lecture=True)


def jetons_disponibles(db: Database, cle: str, *, capacite: float, par_seconde: float, maintenant: float) -> float:
    with _lecture(db) as s:
        ligne = s.get(CompteurDebit, cle)
        return _jetons_courants(ligne, capacite, par_seconde, maintenant)


def effacer_debit(db: Database, *, cles: list[str] | None = None, portee: str | None = None, tout: bool = False,
                  acteur: str = "systeme", motif: str = "", journal: bool = True) -> int:
    """Supprime des seaux (remise à zéro du compteur : déblocage). Journalisé dans le journal d'audit (sauf
    ``journal=False`` : remise à zéro automatique après une connexion réussie). Renvoie le nombre de lignes."""
    if not (cles or portee or tout):
        return 0
    with db.transaction_systeme() as s:
        req = delete(CompteurDebit)
        if cles:
            req = req.where(CompteurDebit.cle.in_(cles))
        if portee:
            req = req.where(CompteurDebit.portee == portee)
        n = s.execute(req).rowcount or 0
        if not journal:
            return n
        journaliser(s, actor=acteur, role="systeme", action="debit_effacer", target="debit_compteurs",
                    details={"portee": portee or "", "cles": len(cles or []), "tout": tout, "lignes": n,
                             "motif": motif[:200]})
        return n


def lister_debit(db: Database, *, maintenant: float, limite: int = 200) -> list[LigneDebit]:
    """Seaux non expirés, les plus vides d'abord."""
    with _lecture(db) as s:
        lignes = s.execute(select(CompteurDebit).where(CompteurDebit.expire > maintenant)
                           .order_by(CompteurDebit.jetons, CompteurDebit.cle).limit(limite)).scalars()
        return [LigneDebit(x.cle, x.portee, x.jetons, x.expire) for x in lignes]


def purger_debit(db: Database, *, maintenant: float, max_lignes: int) -> int:
    """Supprime les seaux expirés puis, au-delà de ``max_lignes``, ceux qui expirent le plus tôt."""
    with db.transaction_systeme() as s:
        n = s.execute(delete(CompteurDebit).where(CompteurDebit.expire <= maintenant)).rowcount or 0
        total = s.execute(select(func.count()).select_from(CompteurDebit)).scalar_one()
        if total > max_lignes:
            exces = select(CompteurDebit.cle).order_by(CompteurDebit.expire).limit(total - max_lignes)
            cles = list(s.execute(exces).scalars())
            n += s.execute(delete(CompteurDebit).where(CompteurDebit.cle.in_(cles))).rowcount or 0
        return n


# --- révocation des sessions ------------------------------------------------------------------------------------


def _poser_revocation(db: Database, cle: str, apres: float, expire: float) -> None:
    for essai in range(3):
        try:
            with db.transaction_systeme() as s:
                ligne = s.get(RevocationSession, cle, with_for_update=True)
                if ligne is None:
                    s.add(RevocationSession(cle=cle, apres=apres, expire=expire))
                else:
                    ligne.apres, ligne.expire = max(ligne.apres, apres), max(ligne.expire, expire)
                return
        except IntegrityError:
            if essai == 2:
                raise


def revoquer_session(db: Database, sid: str, *, expire: float) -> None:
    _poser_revocation(db, f"sid:{sid}"[:120], 0.0, expire)


def revoquer_sessions_utilisateur(db: Database, user_id: str, *, apres: float, expire: float) -> None:
    """Toute session de ``user_id`` commencée strictement avant ``apres`` est révoquée."""
    _poser_revocation(db, f"user:{user_id}"[:120], apres, expire)


def session_revoquee(db: Database, *, sid: str, user_id: str, debut: float) -> bool:
    cles = [f"sid:{sid}"[:120], f"user:{user_id}"[:120]]
    with _lecture(db) as s:
        for r in s.execute(select(RevocationSession).where(RevocationSession.cle.in_(cles))).scalars():
            if r.cle.startswith("sid:") or debut < r.apres:
                return True
    return False


def purger_revocations(db: Database, *, maintenant: float) -> int:
    with db.transaction_systeme() as s:
        return s.execute(delete(RevocationSession).where(RevocationSession.expire <= maintenant)).rowcount or 0
