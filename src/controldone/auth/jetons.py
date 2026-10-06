"""Jetons de session signés (itsdangerous), avec rotation, expiration d'inactivité et durée absolue ;
paramètres de cookie ``httponly`` ; jeton CSRF lié à la session.

- Signature HMAC (itsdangerous) avec une **liste** de secrets : le dernier signe, tous vérifient
  (rotation du secret sans déconnecter tout le monde).
- ``rafraichir`` réémet un jeton (nouvel horodatage d'émission) au-delà de ``rotation_s`` ; l'identifiant
  de session (``sid``) et le début de session sont conservés.
- Révocation : ``revoquer(sid)`` (déconnexion) et ``revoquer_utilisateur(user_id)`` (toutes les sessions
  ouvertes avant maintenant : changement de mot de passe). En mémoire du processus **et**, si un ``registre``
  est fourni (``auth.revocation.RegistreRevocations``, D-3202), en base : la révocation vaut pour tous les
  processus et survit au redémarrage (RS-17). La copie locale est **bornée** (``MAX_REVOCATIONS_LOCALES``,
  entrées expirées d'abord, puis les plus anciennes) : la base fait foi (D-3604).
- Sessions actives (D-3603) : avec un registre, chaque connexion est enregistrée (appareil et réseau réduits),
  chaque rotation met à jour la dernière activité ; ``sessions_actives`` les liste, ``fermer_autres_sessions``
  et ``fermer_session`` les révoquent (page « mes sessions actives »).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from itsdangerous import BadSignature, URLSafeSerializer

from controldone.auth.roles import Acteur, Role
from controldone.config import env

__all__ = [
    "DonneesSession",
    "GestionnaireSessions",
    "SessionInvalide",
    "jeton_csrf",
    "parametres_cookie",
    "secrets_session_depuis_env",
    "verifier_csrf",
]


#: Inactivité maximale et durée absolue d'une session (secondes).
INACTIVITE_S = 30 * 60
DUREE_ABSOLUE_S = 8 * 3600
#: Taille maximale de la copie locale des révocations (``sid`` et coupures par utilisateur), chacune : quelques
#: Mo au plus. Au-delà, les entrées expirées partent d'abord, puis les plus anciennes (la base fait foi).
MAX_REVOCATIONS_LOCALES = 10_000


class SessionInvalide(PermissionError):
    pass


class Registre(Protocol):
    """Révocations persistantes (voir ``auth.revocation.RegistreRevocations``)."""

    def revoquer(self, sid: str, *, expire: float) -> None: ...
    def revoquer_utilisateur(self, user_id: str, *, apres: float, expire: float) -> None: ...
    def est_revoquee(self, sid: str, user_id: str, debut: float) -> bool: ...
    # Facultatives (sessions actives, D-3603) : ``ouvrir``, ``toucher``, ``sessions`` (voir ``RegistreRevocations``).


@dataclass(frozen=True)
class DonneesSession:
    sid: str
    user_id: str
    role: Role
    tenant_id: str | None
    debut: float
    emis: float
    deux_facteurs: bool

    def acteur(self, ip: str | None = None) -> Acteur:
        return Acteur(self.user_id, self.role, self.tenant_id, ip)


def secrets_session_depuis_env(mode: str | None = None) -> list[str]:
    """``CONTROLDONE_SECRET_KEY`` (plusieurs valeurs séparées par des virgules, la dernière signe).
    Absente : refus en production ; en développement, secret dérivé de la clé maîtresse."""
    from controldone.storage.cles import charger_cles_maitresses, mode_execution
    from controldone.storage.erreurs import CleManquante

    brut = env("CONTROLDONE_SECRET_KEY", "").strip()
    if brut:
        return [s.strip() for s in brut.split(",") if s.strip()]
    if (mode or mode_execution()) == "prod":
        raise CleManquante("CONTROLDONE_SECRET_KEY absente : démarrage refusé en production")
    cle = charger_cles_maitresses(mode=mode)[0]
    return [hashlib.sha256(b"controldone/session|" + cle).hexdigest()]


class GestionnaireSessions:
    def __init__(self, secrets_: str | Sequence[str], *, inactivite_s: int = INACTIVITE_S,
                 duree_absolue_s: int = DUREE_ABSOLUE_S, rotation_s: int = 15 * 60,
                 horloge: Callable[[], float] = time.time, registre: Registre | None = None,
                 max_revocations_locales: int = MAX_REVOCATIONS_LOCALES) -> None:
        cles = [secrets_] if isinstance(secrets_, str) else list(secrets_)
        if not cles or any(len(c) < 32 for c in cles):
            raise ValueError("secret de session trop court (32 caractères minimum)")
        self._ser = URLSafeSerializer(cles, salt="controldone.session")
        self.inactivite_s = inactivite_s
        self.duree_absolue_s = duree_absolue_s
        self.rotation_s = rotation_s
        self.horloge = horloge
        #: sid -> instant au-delà duquel la révocation est sans objet (copie locale bornée, D-3604).
        self._revoquees: OrderedDict[str, float] = OrderedDict()
        #: user_id -> instant : sessions commencées strictement avant révoquées (copie locale du registre).
        self._revoquees_avant: OrderedDict[str, float] = OrderedDict()
        self.max_revocations_locales = max(1, max_revocations_locales)
        self.registre = registre

    # --- copie locale bornée des révocations ---
    def _borner(self, table: OrderedDict[str, float], expiration: Callable[[float], float]) -> None:
        if len(table) <= self.max_revocations_locales:
            return
        maintenant = self.horloge()
        for cle in [k for k, v in table.items() if expiration(v) <= maintenant]:
            del table[cle]
        while len(table) > self.max_revocations_locales:
            table.popitem(last=False)

    def _noter_revocation(self, sid: str, expire: float) -> None:
        self._revoquees[sid] = expire
        self._revoquees.move_to_end(sid)
        self._borner(self._revoquees, lambda v: v)

    def _noter_coupure(self, user_id: str, apres: float) -> None:
        self._revoquees_avant[user_id] = max(apres, self._revoquees_avant.get(user_id, apres))
        self._revoquees_avant.move_to_end(user_id)
        # une coupure ne vise que des sessions commencées avant elle : sans objet après la durée absolue
        self._borner(self._revoquees_avant, lambda v: v + self.duree_absolue_s)

    def emettre(self, acteur: Acteur, *, deux_facteurs: bool = False, sid: str | None = None,
                debut: float | None = None, appareil: str = "", reseau: str = "") -> str:
        """Jeton de session. Sans ``sid`` : nouvelle session (connexion), enregistrée dans le registre avec
        ``appareil`` et ``reseau`` déjà réduits (``storage.securite.reduire_appareil`` / ``reduire_reseau``)."""
        if acteur.role is Role.systeme:
            raise ValueError("pas de session pour le système")
        maintenant = self.horloge()
        nouvelle = sid is None
        sid = sid or secrets.token_urlsafe(18)
        debut = debut if debut is not None else maintenant
        jeton = self._ser.dumps({
            "sid": sid, "u": acteur.id, "r": acteur.role.value, "t": acteur.tenant_id, "d": debut,
            "e": maintenant, "2f": bool(deux_facteurs),
        })
        ouvrir = getattr(self.registre, "ouvrir", None)
        if nouvelle and ouvrir is not None:
            ouvrir(sid, acteur.id, debut=debut, vu=maintenant, expire=self._expiration(debut, maintenant),
                   appareil=appareil, reseau=reseau)
        return jeton

    def _expiration(self, debut: float, vu: float) -> float:
        return min(debut + self.duree_absolue_s, vu + self.inactivite_s)

    def lire(self, jeton: str) -> DonneesSession:
        try:
            p: dict[str, Any] = self._ser.loads(jeton)
            d = DonneesSession(sid=p["sid"], user_id=p["u"], role=Role(p["r"]), tenant_id=p.get("t"),
                               debut=float(p["d"]), emis=float(p["e"]), deux_facteurs=bool(p.get("2f")))
        except (BadSignature, KeyError, ValueError, TypeError) as exc:
            raise SessionInvalide("jeton de session invalide") from exc
        maintenant = self.horloge()
        if d.sid in self._revoquees or d.debut < self._revoquees_avant.get(d.user_id, float("-inf")):
            raise SessionInvalide("session révoquée")
        if maintenant - d.emis > self.inactivite_s:
            raise SessionInvalide("session expirée (inactivité)")
        if maintenant - d.debut > self.duree_absolue_s:
            raise SessionInvalide("session expirée (durée maximale)")
        if d.role is Role.fondateur and not d.deux_facteurs:
            raise SessionInvalide("second facteur exigé pour le fondateur")
        if self.registre is not None and self.registre.est_revoquee(d.sid, d.user_id, d.debut):
            self._noter_revocation(d.sid, d.debut + self.duree_absolue_s + 60)
            raise SessionInvalide("session révoquée")
        return d

    def rafraichir(self, jeton: str) -> tuple[DonneesSession, str | None]:
        """Valide le jeton ; renvoie un nouveau jeton si la rotation est due (sinon ``None``)."""
        d = self.lire(jeton)
        if self.horloge() - d.emis < self.rotation_s:
            return d, None
        nouveau = self.emettre(Acteur(d.user_id, d.role, d.tenant_id), deux_facteurs=d.deux_facteurs,
                               sid=d.sid, debut=d.debut)
        toucher = getattr(self.registre, "toucher", None)
        if toucher is not None:
            vu = self.horloge()
            toucher(d.sid, vu=vu, expire=self._expiration(d.debut, vu))
        return d, nouveau

    def revoquer(self, sid: str, *, debut: float | None = None) -> None:
        """Déconnexion : le ``sid`` est refusé partout (registre) jusqu'à l'expiration absolue de la session."""
        depart = self.horloge() if debut is None else debut
        self._noter_revocation(sid, depart + self.duree_absolue_s + 60)
        if self.registre is not None:
            self.registre.revoquer(sid, expire=depart + self.duree_absolue_s + 60)

    def revoquer_utilisateur(self, user_id: str) -> float:
        """Toutes les sessions de ``user_id`` ouvertes jusqu'à maintenant sont révoquées (changement de mot de
        passe). Renvoie l'instant de coupure : une session émise ensuite (``emettre``) reste valable."""
        apres = self.horloge()
        self._noter_coupure(user_id, apres)
        if self.registre is not None:
            self.registre.revoquer_utilisateur(user_id, apres=apres, expire=apres + self.duree_absolue_s + 60)
        return apres

    # --- sessions actives (D-3603) ---
    def sessions_actives(self, user_id: str, *, sid_courant: str | None = None) -> list[Any]:
        """Sessions ouvertes de ``user_id`` (``storage.securite.SessionActive`` : ``sid``, ``debut``, ``vu``,
        ``appareil``, ``reseau``, ``courante``), la plus récemment active d'abord. Liste vide sans registre."""
        lister = getattr(self.registre, "sessions", None)
        if lister is None:
            return []
        maintenant = self.horloge()
        return [x for x in lister(user_id, maintenant=maintenant, sid_courant=sid_courant)
                if x.sid not in self._revoquees
                and x.debut >= self._revoquees_avant.get(user_id, float("-inf"))
                and maintenant - x.vu <= self.inactivite_s and maintenant - x.debut <= self.duree_absolue_s]

    def fermer_session(self, user_id: str, sid: str) -> bool:
        """Ferme **une** session de ``user_id`` (``False`` si ce ``sid`` n'est pas une de ses sessions ouvertes :
        un utilisateur ne peut pas fermer la session d'un autre)."""
        for x in self.sessions_actives(user_id):
            if hmac.compare_digest(x.sid.encode(), sid.encode()):
                self.revoquer(x.sid, debut=x.debut)
                return True
        return False

    def fermer_autres_sessions(self, user_id: str, sid_courant: str) -> int:
        """Ferme toutes les sessions ouvertes de ``user_id`` sauf ``sid_courant`` ; renvoie leur nombre."""
        n = 0
        for x in self.sessions_actives(user_id, sid_courant=sid_courant):
            if x.sid != sid_courant:
                self.revoquer(x.sid, debut=x.debut)
                n += 1
        return n


def parametres_cookie(*, prod: bool = True, max_age: int = DUREE_ABSOLUE_S) -> dict[str, Any]:
    """Paramètres du cookie de session (à passer à ``response.set_cookie``). En production, préfixe
    ``__Host-`` (impose ``Secure``, ``Path=/``, pas de ``Domain``)."""
    return {
        "key": "__Host-cd_session" if prod else "cd_session",
        "httponly": True,
        "secure": prod,
        "samesite": "strict" if prod else "lax",
        "path": "/",
        "max_age": max_age,
    }


def jeton_csrf(secret: str, sid: str) -> str:
    """Jeton CSRF lié à la session : ``nonce.hmac(secret, sid|nonce)``."""
    nonce = secrets.token_urlsafe(16)
    mac = hmac.new(secret.encode(), f"csrf|{sid}|{nonce}".encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{mac}"


def verifier_csrf(secret: str, sid: str, jeton: str | None) -> bool:
    if not jeton or "." not in jeton:
        return False
    nonce, _, mac = jeton.partition(".")
    attendu = hmac.new(secret.encode(), f"csrf|{sid}|{nonce}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, mac)
