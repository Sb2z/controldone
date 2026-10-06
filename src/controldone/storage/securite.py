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
- ``sessions_actives`` (D-3603) : sessions ouvertes, pour la liste « mes sessions actives » et « fermer mes autres
  sessions ». Une ligne par connexion réussie, mise à jour à chaque rotation du jeton (au plus toutes les
  15 minutes), supprimée à la déconnexion, à la révocation ou à l'expiration. Minimisation : appareil réduit au
  navigateur et au système (« Firefox · Linux »), réseau tronqué (``/24`` IPv4, ``/48`` IPv6), jamais le
  ``User-Agent`` complet ni l'adresse entière.

Mise à jour atomique : sous SQLite, chaque transaction commence par ``BEGIN IMMEDIATE`` (un seul écrivain) ;
sous PostgreSQL, la ligne est lue ``FOR UPDATE`` et une insertion concurrente (clé primaire) est rejouée.
Horloge : secondes depuis l'époque (``time.time``), commune aux processus.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Float, String, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from controldone.storage.audit import journaliser
from controldone.storage.db import Database
from controldone.storage.models import Base

__all__ = [
    "CompteurDebit",
    "LigneDebit",
    "RevocationSession",
    "SessionActive",
    "SessionOuverte",
    "assurer_tables_securite",
    "chiffrement_volume",
    "consommer_jetons",
    "crediter_jetons",
    "effacer_debit",
    "enregistrer_session",
    "jetons_disponibles",
    "lister_debit",
    "oublier_session",
    "purger_debit",
    "purger_revocations",
    "reduire_appareil",
    "reduire_reseau",
    "revoquer_session",
    "revoquer_sessions_utilisateur",
    "session_revoquee",
    "sessions_utilisateur",
    "signaler_volume_non_chiffre",
    "toucher_session",
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


class SessionOuverte(Base):
    __tablename__ = "sessions_actives"

    sid: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    #: Début de la session (connexion), dernière émission du jeton (rotation) : époque, secondes.
    debut: Mapped[float] = mapped_column(Float)
    vu: Mapped[float] = mapped_column(Float)
    #: Au-delà, la session ne peut plus être valide (min(début + durée absolue, vu + inactivité)).
    expire: Mapped[float] = mapped_column(Float, index=True)
    appareil: Mapped[str] = mapped_column(String(80), default="")
    reseau: Mapped[str] = mapped_column(String(64), default="")


_TABLES = (CompteurDebit.__table__, RevocationSession.__table__, SessionOuverte.__table__)


def assurer_tables_securite(db: Database) -> None:
    """Crée les tables si elles manquent (base créée par une version antérieure, sans migration : ce sont
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
    oublier_session(db, sid)


def revoquer_sessions_utilisateur(db: Database, user_id: str, *, apres: float, expire: float) -> None:
    """Toute session de ``user_id`` commencée strictement avant ``apres`` est révoquée."""
    _poser_revocation(db, f"user:{user_id}"[:120], apres, expire)
    with db.transaction_systeme() as s:
        s.execute(delete(SessionOuverte).where(SessionOuverte.user_id == user_id, SessionOuverte.debut < apres))


def session_revoquee(db: Database, *, sid: str, user_id: str, debut: float) -> bool:
    cles = [f"sid:{sid}"[:120], f"user:{user_id}"[:120]]
    with _lecture(db) as s:
        for r in s.execute(select(RevocationSession).where(RevocationSession.cle.in_(cles))).scalars():
            if r.cle.startswith("sid:") or debut < r.apres:
                return True
    return False


def purger_revocations(db: Database, *, maintenant: float) -> int:
    """Révocations devenues sans objet et sessions actives expirées."""
    with db.transaction_systeme() as s:
        n = s.execute(delete(RevocationSession).where(RevocationSession.expire <= maintenant)).rowcount or 0
        return n + (s.execute(delete(SessionOuverte).where(SessionOuverte.expire <= maintenant)).rowcount or 0)


# --- sessions actives (D-3603) ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionActive:
    """Session ouverte d'un compte, telle que la montre la page « mes sessions actives »."""

    sid: str
    debut: float
    vu: float
    appareil: str
    reseau: str
    #: Session de la requête qui demande la liste.
    courante: bool = False


_NAVIGATEURS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                ("Chromium/", "Chromium"), ("Safari/", "Safari"), ("curl/", "curl"))
_SYSTEMES = (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iOS"),
             ("Mac OS X", "macOS"), ("Macintosh", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux"))


def reduire_appareil(user_agent: str | None) -> str:
    """« Navigateur · Système » d'après le ``User-Agent`` (listes fermées : aucun texte du client n'est conservé)."""
    ua = (user_agent or "")[:512]
    nav = next((nom for motif, nom in _NAVIGATEURS if motif in ua), "Navigateur inconnu")
    sys_ = next((nom for motif, nom in _SYSTEMES if motif in ua), "système inconnu")
    return f"{nav} · {sys_}"


def reduire_reseau(ip: str | None) -> str:
    """Adresse tronquée (``203.0.113.0/24``, ``2001:db8:1::/48``) ; chaîne vide si illisible."""
    try:
        adresse = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return ""
    prefixe = 24 if adresse.version == 4 else 48
    return str(ipaddress.ip_network(f"{adresse}/{prefixe}", strict=False))


def enregistrer_session(db: Database, *, sid: str, user_id: str, debut: float, vu: float, expire: float,
                        appareil: str = "", reseau: str = "") -> None:
    """Nouvelle session (connexion réussie)."""
    for essai in range(3):
        try:
            with db.transaction_systeme() as s:
                ligne = s.get(SessionOuverte, sid[:64])
                if ligne is None:
                    s.add(SessionOuverte(sid=sid[:64], user_id=user_id[:64], debut=debut, vu=vu, expire=expire,
                                         appareil=appareil[:80], reseau=reseau[:64]))
                else:
                    ligne.vu, ligne.expire = vu, expire
                return
        except IntegrityError:
            if essai == 2:
                raise


def toucher_session(db: Database, sid: str, *, vu: float, expire: float) -> None:
    """Rotation du jeton : dernière activité connue. Sans effet si la session n'est pas enregistrée (ouverte
    avant la version qui les enregistre)."""
    with db.transaction_systeme() as s:
        s.execute(update(SessionOuverte).where(SessionOuverte.sid == sid[:64]).values(vu=vu, expire=expire))


def oublier_session(db: Database, sid: str) -> None:
    with db.transaction_systeme() as s:
        s.execute(delete(SessionOuverte).where(SessionOuverte.sid == sid[:64]))


def sessions_utilisateur(db: Database, user_id: str, *, maintenant: float, sid_courant: str | None = None,
                         limite: int = 100) -> list[SessionActive]:
    """Sessions non expirées et non révoquées de ``user_id``, la plus récemment active d'abord."""
    with _lecture(db) as s:
        lignes = list(s.execute(
            select(SessionOuverte).where(SessionOuverte.user_id == user_id, SessionOuverte.expire > maintenant)
            .order_by(SessionOuverte.vu.desc(), SessionOuverte.sid).limit(limite)).scalars())
        cles = [f"user:{user_id}"[:120]] + [f"sid:{x.sid}"[:120] for x in lignes]
        revoc = {r.cle: r for r in s.execute(select(RevocationSession).where(RevocationSession.cle.in_(cles)))
                 .scalars()}
    coupure = revoc[f"user:{user_id}"[:120]].apres if f"user:{user_id}"[:120] in revoc else float("-inf")
    return [SessionActive(x.sid, x.debut, x.vu, x.appareil, x.reseau, courante=(x.sid == sid_courant))
            for x in lignes if f"sid:{x.sid}"[:120] not in revoc and x.debut >= coupure]


# --- chiffrement du volume de la base (RS-21, D-3605) -------------------------------------------------------------


def _peripherique(chemin: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(chemin)
    except OSError:
        return None
    return os.major(st.st_dev), os.minor(st.st_dev)


def chiffrement_volume(chemin: Path | str, *, sys_dir: Path | str = "/sys") -> str:
    """``chiffre`` si le fichier ou répertoire ``chemin`` est sur un volume dm-crypt (LUKS), ou sur un
    périphérique logique (LVM) construit au-dessus d'un tel volume ; ``non_chiffre`` si le périphérique est
    identifié et ne l'est pas ; ``inconnu`` sinon (système de fichiers réseau, superposition sans périphérique,
    autre système d'exploitation). Lecture seule de ``/sys`` : aucun privilège nécessaire."""
    dev = _peripherique(Path(chemin))
    if dev is None or dev == (0, 0):
        return "inconnu"
    base = Path(sys_dir) / "dev" / "block" / f"{dev[0]}:{dev[1]}"
    if not base.exists():
        return "inconnu"  # ex. overlay / tmpfs (majeur 0) ou /sys non monté
    vus: set[str] = set()
    a_voir = [base]
    while a_voir:
        courant = a_voir.pop()
        try:
            reel = courant.resolve()
        except OSError:
            continue
        if str(reel) in vus:
            continue
        vus.add(str(reel))
        try:
            uuid = (reel / "dm" / "uuid").read_text().strip()
        except OSError:
            uuid = ""
        if uuid.upper().startswith("CRYPT-"):
            return "chiffre"
        esclaves = reel / "slaves"
        if esclaves.is_dir():
            a_voir.extend(sorted(esclaves.iterdir()))
    return "non_chiffre"


def signaler_volume_non_chiffre(db: Database, *, mode: str | None = None, sys_dir: Path | str = "/sys") -> str:
    """Au démarrage du service web (``controldone serve``) en production : la base SQLite vivante contient en
    clair métadonnées, valeurs extraites et constats (RS-21) ; elle doit être sur un volume chiffré (LUKS,
    ``docs/DEPLOIEMENT.md``). Volume identifié comme **non** chiffré : avertissement journalisé et alerte
    ``volume_non_chiffre`` pour le fondateur (une par mois). ``CONTROLDONE_VOLUME_CHIFFRE=1`` déclare un
    chiffrement invisible depuis la machine (disque chiffré par l'hébergeur). Renvoie l'état constaté
    (``chiffre``, ``non_chiffre``, ``inconnu``, ``declare``, ``hors_sqlite``, ``hors_prod``)."""
    import logging
    from datetime import UTC, datetime

    from controldone.config import env
    from controldone.storage.cles import mode_execution

    log = logging.getLogger("controldone.storage.securite")
    if (mode or mode_execution()) != "prod":
        return "hors_prod"
    chemin = db.chemin_sqlite()
    if chemin is None:
        return "hors_sqlite"  # PostgreSQL : chiffrement au repos à la charge de l'hôte de la base
    if env("CONTROLDONE_VOLUME_CHIFFRE", "").strip() == "1":
        return "declare"
    etat = chiffrement_volume(chemin.parent if not chemin.exists() else chemin, sys_dir=sys_dir)
    if etat == "non_chiffre":
        log.warning("volume_non_chiffre base=sqlite : la base vivante n'est pas sur un volume chiffré (RS-21)")
        try:
            from controldone.storage.alertes import emettre_alerte

            with db.transaction_systeme() as s:
                emettre_alerte(s, cle=f"volume_non_chiffre:{datetime.now(UTC):%Y-%m}", kind="volume_non_chiffre",
                               message="La base de données n'est pas sur un volume chiffré (LUKS) : métadonnées, "
                                       "valeurs extraites et constats y sont en clair. Voir docs/DEPLOIEMENT.md.")
        except Exception as exc:  # jamais bloquant au démarrage
            log.warning("alerte_volume_impossible erreur=%s", type(exc).__name__)
    elif etat == "inconnu":
        log.info("volume_chiffrement_inconnu : vérifier que la base est sur un volume chiffré (RS-21)")
    return etat
