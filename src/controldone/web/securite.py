"""Sécurité HTTP de l'interface : session (cookie signé, rotation), CSRF sur chaque POST, en-têtes de
sécurité, limite de taille des corps de requête, messages flash signés.

- Le client (``tenant_id``) vient **toujours** de la session authentifiée (``Acteur``), jamais d'un
  paramètre. Le fondateur désigne un client dans l'URL, mais chaque ouverture passe par
  ``OperatorScope.client`` (journal d'audit avec motif).
- CSRF : jeton ``nonce.HMAC(secret, sid|nonce)`` lié à la session (``auth.jetons``) ; avant connexion, lié
  à un identifiant de pré-session (cookie ``HttpOnly``).
- En-têtes : CSP ``default-src 'self'`` (aucune ressource externe, aucun script en ligne, Trusted Types sans
  politique : aucun puits HTML du DOM, D-3204), violations envoyées à ``/csp-rapport`` (``report-uri`` et ``report-to``), ``X-Frame-
  Options: DENY``, ``Referrer-Policy: same-origin``, ``X-Content-Type-Options: nosniff``, ``Permissions-Policy``
  (toutes les fonctions sensibles refusées), ``Cross-Origin-Opener-Policy`` / ``-Resource-Policy: same-origin``,
  HSTS si HTTPS ; ``Cache-Control: no-store`` sur les pages authentifiées.
- Limitation de débit : seaux partagés en base (``auth.LimiteurDebitPartage``, D-3201) dès que l'application a
  une plateforme ; seaux en mémoire sinon (tests unitaires).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from controldone.auth import (
    DonneesSession,
    GestionnaireSessions,
    Limiteur,
    LimiteurDebit,
    LimiteurDebitPartage,
    jeton_csrf,
    verifier_csrf,
)
from controldone.auth.roles import Acteur, Role

__all__ = [
    "CHEMIN_RAPPORT_CSP",
    "CSP",
    "PERMISSIONS_POLICY",
    "CsrfInvalide",
    "EnTetesSecurite",
    "EtatSecurite",
    "LimiteCorps",
    "ModeIncoherent",
    "NonConnecte",
    "hotes_autorises",
    "url_publique",
    "verifier_mode_service",
]

log = logging.getLogger("controldone.web.securite")

#: Point de réception des violations de CSP (journalisées sans donnée personnelle, débit et taille bornés).
CHEMIN_RAPPORT_CSP = "/csp-rapport"
_RAPPORT = f"report-uri {CHEMIN_RAPPORT_CSP}; report-to csp"
#: Interface : tout vient de l'application (``/static/theme.js`` synchrone, ``/static/vendor/motion.min.js``,
#: ``/static/app.js``), aucun script ni style en ligne. Trusted Types (D-3204) : aucune politique admise, donc
#: aucun puits HTML du DOM (``innerHTML``, ``insertAdjacentHTML``, ``document.write``, ``DOMParser``…) ni URL de
#: script calculée — le JavaScript de l'interface n'écrit que du ``textContent`` et le filtrage en direct reçoit un
#: document déjà analysé (``XMLHttpRequest``, ``responseType = "document"``). Test permanent :
#: ``tests/security/test_revue_securite_2.py``.
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
    "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; "
    "require-trusted-types-for 'script'; trusted-types 'none'; " + _RAPPORT
)
#: Rapport HTML affiché tel quel (gabarit maison, styles intégrés, aucun script) : CSP fermée.
CSP_RAPPORT = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'; "
    + _RAPPORT
)
#: Fonctions du navigateur toutes refusées (noms reconnus par les navigateurs actuels : un nom inconnu produit un
#: avertissement dans la console).
PERMISSIONS_POLICY = ", ".join(
    f"{f}=()"
    for f in (
        "accelerometer",
        "autoplay",
        "browsing-topics",
        "camera",
        "display-capture",
        "encrypted-media",
        "geolocation",
        "gyroscope",
        "hid",
        "idle-detection",
        "magnetometer",
        "microphone",
        "midi",
        "payment",
        "screen-wake-lock",
        "serial",
        "usb",
        "xr-spatial-tracking",
    )
)


# --- URL publique et hôtes admis (RS-18, D-3602) -------------------------------------------------------------------

_HOTE_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)


def _domaine_configure() -> str | None:
    from controldone.config import env

    d = env("CONTROLDONE_DOMAIN", "").strip().lower().rstrip(".")
    return d if d and _HOTE_RE.match(d) else None


def url_publique(request: Request | None = None) -> str:
    """URL publique du service (liens de paiement Stripe, liens envoyés aux clients) : ``CONTROLDONE_URL_PUBLIQUE``
    (``https://hôte[:port]``), sinon ``https://CONTROLDONE_DOMAIN``. **Jamais** l'en-tête ``Host`` de la requête
    en production (un ``Host`` forgé ne doit pas produire un lien vers un autre site, RS-18) ; en développement,
    à défaut de configuration, l'URL de la requête. ``ValueError`` si rien n'est configuré en production."""
    from controldone.config import env
    from controldone.storage.cles import mode_execution

    brut = env("CONTROLDONE_URL_PUBLIQUE", "").strip().rstrip("/")
    if brut:
        u = urlsplit(brut)
        if (
            u.scheme not in ("https", "http")
            or not u.hostname
            or not _HOTE_RE.match(u.hostname)
            or u.path
            or u.query
            or u.fragment
            or u.username
            or u.password
        ):
            raise ValueError("CONTROLDONE_URL_PUBLIQUE invalide (attendu : https://hôte[:port])")
        if u.scheme != "https" and mode_execution() == "prod":
            raise ValueError("CONTROLDONE_URL_PUBLIQUE doit être en https en production")
        return brut
    domaine = _domaine_configure()
    if domaine:
        return f"https://{domaine}"
    if mode_execution() == "prod" or request is None:
        raise ValueError(
            "URL publique non configurée : définir CONTROLDONE_DOMAIN (ou CONTROLDONE_URL_PUBLIQUE)"
        )
    return f"{request.url.scheme}://{request.url.netloc}"


def hotes_autorises() -> list[str] | None:
    """Hôtes admis dans l'en-tête ``Host`` (``TrustedHostMiddleware``) quand le domaine est configuré : le domaine,
    l'hôte de ``CONTROLDONE_URL_PUBLIQUE``, ``CONTROLDONE_HOTES_AUTORISES`` (liste séparée par des virgules) et la
    boucle locale (sonde de santé). ``None`` : aucun domaine configuré (développement), pas de filtrage."""
    from controldone.config import env

    hotes: list[str] = []
    if d := _domaine_configure():
        hotes.append(d)
    brut = env("CONTROLDONE_URL_PUBLIQUE", "").strip()
    if brut and (h := (urlsplit(brut).hostname or "").lower()) and _HOTE_RE.match(h):
        hotes.append(h)
    if not hotes:
        return None
    hotes += [h.strip().lower() for h in env("CONTROLDONE_HOTES_AUTORISES", "").split(",") if h.strip()]
    hotes += ["127.0.0.1", "localhost", "::1"]
    return list(dict.fromkeys(hotes))


# --- mode d'exécution du service web (RS-16, D-3601) -----------------------------------------------------------------


class ModeIncoherent(RuntimeError):
    """Le service web est lancé en mode ``dev``/``test`` dans une configuration de production."""


def _boucle_locale(hote: str) -> bool:
    import ipaddress

    h = hote.strip().strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def verifier_mode_service(
    *, hote: str, https: bool = False, proxy: bool = False, mode: str | None = None
) -> None:
    """Refuse (``ModeIncoherent``) de servir en mode ``dev``/``test`` — clé maîtresse générée sur le disque, cookies
    sans ``Secure`` ni ``__Host-``, pas de HSTS — sur une interface autre que la boucle locale, ou derrière un
    mandataire TLS (``--https`` / ``--proxy``) : c'est le signe d'un ``CONTROLDONE_ENV=prod`` oublié (RS-16).
    ``CONTROLDONE_DEV_RESEAU=1`` lève le refus (démonstration sur un réseau local de confiance), avec un
    avertissement."""
    from controldone.config import env
    from controldone.storage.cles import mode_execution

    mode = mode or mode_execution()
    if mode == "prod":
        return
    motifs = []
    if not _boucle_locale(hote):
        motifs.append(f"écoute sur {hote} (hors boucle locale)")
    if https:
        motifs.append("--https (servi derrière TLS)")
    if proxy:
        motifs.append("--proxy (derrière un mandataire)")
    if not motifs:
        return
    message = (
        f"mode {mode} ({'CONTROLDONE_ENV absent' if not env('CONTROLDONE_ENV', '').strip() else 'CONTROLDONE_ENV=' + mode}) "
        f"avec une configuration de production : {', '.join(motifs)}. Définir CONTROLDONE_ENV=prod "
        "(clé maîtresse et secret de session obligatoires), ou CONTROLDONE_DEV_RESEAU=1 pour une "
        "démonstration volontaire sur un réseau de confiance."
    )
    if env("CONTROLDONE_DEV_RESEAU", "").strip() == "1":
        log.warning("mode_dev_expose %s", message)
        return
    raise ModeIncoherent(message)


class NonConnecte(Exception):
    """Aucune session valide : redirection vers la connexion (pages) ou 401 (API)."""


class CsrfInvalide(Exception):
    pass


#: Seuils (capacité, recharge par seconde) : 10 tentatives de connexion par adresse et 5 par compte sur
#: 5 minutes ; API : 120 requêtes en rafale, 2 par seconde ensuite.
SEUILS: dict[str, tuple[float, float]] = {
    "connexion_ip": (10, 10 / 300),
    "connexion_compte": (5, 5 / 300),
    "api": (120, 2.0),
}


@dataclass
class EtatSecurite:
    sessions: GestionnaireSessions
    secret_csrf: str
    secret_signature: str
    prod: bool
    https: bool
    cookie: dict[str, Any]
    limiteur_connexion_ip: Limiteur = field(default_factory=lambda: LimiteurDebit(*SEUILS["connexion_ip"]))
    limiteur_connexion_compte: Limiteur = field(
        default_factory=lambda: LimiteurDebit(*SEUILS["connexion_compte"])
    )
    limiteur_api: Limiteur = field(default_factory=lambda: LimiteurDebit(*SEUILS["api"]))
    #: Rapports de violation CSP : par adresse, en mémoire du processus (aucune valeur à partager).
    limiteur_csp: Limiteur = field(default_factory=lambda: LimiteurDebit(20, 20 / 60))

    def partager_debit(self, db: Any, sel: bytes) -> None:
        """Seaux en base, partagés par les processus et conservés au redémarrage (D-3201). Seuils inchangés."""
        self.limiteur_connexion_ip = LimiteurDebitPartage(
            "connexion_ip", *SEUILS["connexion_ip"], db=db, sel=sel
        )
        self.limiteur_connexion_compte = LimiteurDebitPartage(
            "connexion_compte", *SEUILS["connexion_compte"], db=db, sel=sel
        )
        self.limiteur_api = LimiteurDebitPartage("api", *SEUILS["api"], db=db, sel=sel)

    @property
    def nom_cookie(self) -> str:
        return self.cookie["key"]

    @property
    def nom_presession(self) -> str:
        return "__Host-cd_pre" if self.prod else "cd_pre"

    #: Cookies secondaires (D-3604) : préfixe ``__Host-`` en production comme le cookie de session (``Secure``,
    #: ``Path=/``, sans ``Domain`` : ni un sous-domaine ni une page HTTP ne peuvent le poser ou l'écraser).
    @property
    def nom_2fa(self) -> str:
        return "__Host-cd_2fa" if self.prod else "cd_2fa"

    @property
    def nom_flash(self) -> str:
        return "__Host-cd_flash" if self.prod else "cd_flash"

    def _effacer(self, reponse: Response, nom: str, samesite: str) -> None:
        # un cookie ``__Host-`` n'est effacé que par un Set-Cookie ``Secure`` ``Path=/`` (sinon refusé)
        reponse.delete_cookie(nom, path="/", secure=self.cookie["secure"], httponly=True, samesite=samesite)

    def ouvrir_session(
        self, request: Request, reponse: Response, acteur: Acteur, *, deux_facteurs: bool = False
    ) -> str:
        """Nouvelle session (connexion, changement de mot de passe) : jeton posé sur ``reponse``, session
        enregistrée pour la liste « mes sessions actives » (appareil et réseau réduits, D-3603). Renvoie le
        ``sid``."""
        from controldone.storage.securite import reduire_appareil, reduire_reseau

        jeton = self.sessions.emettre(
            acteur,
            deux_facteurs=deux_facteurs,
            appareil=reduire_appareil(request.headers.get("user-agent")),
            reseau=reduire_reseau(request.client.host if request.client else None),
        )
        self.poser_session(reponse, jeton)
        return self.sessions.lire(jeton).sid

    def _ser(self, sel: str) -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(self.secret_signature, salt=sel)

    # --- session ---
    def poser_session(self, reponse: Response, jeton: str) -> None:
        reponse.set_cookie(**{**self.cookie, "value": jeton})

    def effacer_session(self, reponse: Response) -> None:
        reponse.delete_cookie(
            self.nom_cookie,
            path="/",
            secure=self.cookie["secure"],
            httponly=True,
            samesite=self.cookie["samesite"],
        )

    # --- second facteur en attente (5 minutes) ---
    def poser_2fa(self, reponse: Response, user_id: str) -> None:
        reponse.set_cookie(
            self.nom_2fa,
            self.jeton_2fa(user_id),
            max_age=300,
            httponly=True,
            secure=self.cookie["secure"],
            samesite="strict" if self.prod else "lax",
            path="/",
        )

    def lire_2fa_requete(self, request: Request) -> str | None:
        return self.lire_2fa(request.cookies.get(self.nom_2fa))

    def effacer_2fa(self, reponse: Response) -> None:
        self._effacer(reponse, self.nom_2fa, "strict" if self.prod else "lax")

    def jeton_2fa(self, user_id: str) -> str:
        return self._ser("controldone.2fa").dumps({"u": user_id, "n": secrets.token_urlsafe(8)})

    def lire_2fa(self, jeton: str | None) -> str | None:
        if not jeton:
            return None
        try:
            return self._ser("controldone.2fa").loads(jeton, max_age=300)["u"]
        except (BadSignature, KeyError, TypeError):
            return None

    # --- messages flash ---
    def flash(self, reponse: Response, message: str, *, erreur: bool = False) -> None:
        reponse.set_cookie(
            self.nom_flash,
            self._ser("controldone.flash").dumps({"m": message[:500], "e": erreur}),
            max_age=60,
            httponly=True,
            secure=self.cookie["secure"],
            samesite="lax",
            path="/",
        )

    def effacer_flash(self, reponse: Response) -> None:
        self._effacer(reponse, self.nom_flash, "lax")

    def lire_flash(self, request: Request) -> dict[str, Any] | None:
        brut = request.cookies.get(self.nom_flash)
        if not brut:
            return None
        try:
            return self._ser("controldone.flash").loads(brut, max_age=120)
        except BadSignature:
            return None

    # --- CSRF ---
    def sid_csrf(self, request: Request) -> str | None:
        s: DonneesSession | None = getattr(request.state, "session", None)
        if s is not None:
            return s.sid
        return request.cookies.get(self.nom_presession)

    def jeton(self, request: Request) -> str:
        sid = self.sid_csrf(request) or getattr(request.state, "presession", None)
        if not sid:
            sid = secrets.token_urlsafe(18)
            request.state.presession = sid
        return jeton_csrf(self.secret_csrf, sid)

    def poser_presession(self, request: Request, reponse: Response) -> None:
        sid = getattr(request.state, "presession", None)
        if sid and request.cookies.get(self.nom_presession) != sid:
            reponse.set_cookie(
                self.nom_presession,
                sid,
                httponly=True,
                secure=self.cookie["secure"],
                samesite="strict" if self.prod else "lax",
                path="/",
                max_age=3600,
            )

    def verifier(self, request: Request, jeton: str | None) -> None:
        sid = self.sid_csrf(request)
        if not sid or not verifier_csrf(self.secret_csrf, sid, jeton):
            raise CsrfInvalide()


async def formulaire(request: Request, *, fichiers: bool = False) -> FormData:
    """Formulaire de la requête, jeton CSRF vérifié (champ ``csrf``)."""
    etat: EtatSecurite = request.app.state.securite
    form = await request.form(max_files=2000 if fichiers else 0, max_fields=200, max_part_size=256 * 1024)
    etat.verifier(request, form.get("csrf") if isinstance(form.get("csrf"), str) else None)  # type: ignore[arg-type]
    return form


def depuis_boucle(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Depuis une route **synchrone** (exécutée hors de la boucle, dans le réservoir de fils de FastAPI),
    attend une coroutine de la requête sur la boucle d'événements (``request.form``, ``request.body``).
    Les routes font ainsi leur travail bloquant (base, Argon2, chiffrement, PDF) **hors** de la boucle :
    une requête lente ne gèle plus les autres (F-03, D-1304)."""
    import functools

    import anyio.from_thread

    return anyio.from_thread.run(functools.partial(fn, *args, **kwargs))


def formulaire_sync(request: Request, *, fichiers: bool = False) -> FormData:
    """``formulaire`` appelé depuis une route synchrone."""
    return depuis_boucle(formulaire, request, fichiers=fichiers)


def acteur_de(request: Request) -> Acteur:
    """Acteur de la session. Le compte est relu en base à chaque requête : un compte désactivé, supprimé ou
    dont le rôle fondateur a changé perd aussitôt ses sessions (le jeton signé seul ne suffit pas, RS-09).
    L'appartenance d'un rôle client à son client est vérifiée à l'ouverture de chaque ``TenantScope``."""
    s: DonneesSession | None = getattr(request.state, "session", None)
    if s is None:
        raise NonConnecte()
    plateforme = getattr(request.app.state, "plateforme", None)
    if plateforme is not None:
        from controldone.storage.comptes import utilisateur

        compte = utilisateur(plateforme.db, s.user_id)
        if (
            compte is None
            or not compte.actif
            or (s.role is Role.fondateur) != (compte.role == Role.fondateur.value)
        ):
            request.app.state.securite.sessions.revoquer(s.sid)
            raise NonConnecte()
    return s.acteur(ip=request.client.host if request.client else None)


class EnTetesSecurite:
    """Middleware ASGI : en-têtes de sécurité sur toutes les réponses (une réponse peut fixer sa propre
    CSP, plus stricte, ex. rapport HTML)."""

    def __init__(self, app: ASGIApp, *, https: bool) -> None:
        self.app = app
        self.https = https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        https = self.https or scope.get("scheme") == "https"

        async def envoyer(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = [(k.lower(), v) for k, v in message.get("headers", [])]
                noms = {k for k, _ in h}
                ajouts = {
                    b"content-security-policy": CSP.encode(),
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"same-origin",
                    b"x-content-type-options": b"nosniff",
                    b"permissions-policy": PERMISSIONS_POLICY.encode(),
                    b"reporting-endpoints": f'csp="{CHEMIN_RAPPORT_CSP}"'.encode(),
                    b"cross-origin-opener-policy": b"same-origin",
                    b"cross-origin-resource-policy": b"same-origin",
                }
                if https:
                    ajouts[b"strict-transport-security"] = b"max-age=63072000; includeSubDomains"
                if not scope["path"].startswith("/static/"):
                    ajouts.setdefault(b"cache-control", b"no-store")
                for k, v in ajouts.items():
                    if k not in noms:
                        h.append((k, v))
                message["headers"] = h
            await send(message)

        await self.app(scope, receive, envoyer)


class CorpsTropGros(Exception):
    pass


class LimiteCorps:
    """Middleware ASGI : refuse (413) un corps de requête au-delà de la limite, en flux (``Content-Length``
    absent ou mensonger compris). Dépôts : ``limite_depot`` ; toute autre requête : ``limite``."""

    def __init__(
        self, app: ASGIApp, *, limite: int, limite_depot: int, chemins_depot: tuple[str, ...]
    ) -> None:
        self.app = app
        self.limite = limite
        self.limite_depot = limite_depot
        self.chemins_depot = chemins_depot

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limite = self.limite_depot if scope["path"] in self.chemins_depot else self.limite
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > limite:
                        await _repondre_413(send, scope)
                        return
                except ValueError:
                    pass
        recu = 0
        demarre = False

        async def recevoir() -> Message:
            nonlocal recu
            message = await receive()
            if message["type"] == "http.request":
                recu += len(message.get("body", b""))
                if recu > limite:
                    raise CorpsTropGros()
            return message

        async def envoyer(message: Message) -> None:
            nonlocal demarre
            if message["type"] == "http.response.start":
                demarre = True
            await send(message)

        try:
            await self.app(scope, recevoir, envoyer)
        except CorpsTropGros:
            if not demarre:
                await _repondre_413(send, scope)


def _langue_brute(scope: Scope) -> str:
    """Langue d'une réponse produite avant l'application (413) : cookie ``cd_langue``, sinon
    ``Accept-Language`` (D-3803), lus dans les en-têtes bruts."""
    from http.cookies import CookieError, SimpleCookie

    from controldone.web.i18n import COOKIE_LANGUE, LANGUES, negocier

    entetes = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
    try:
        biscuits = SimpleCookie(entetes.get("cookie", "")[:4096])
    except CookieError:
        biscuits = SimpleCookie()
    for nom in (COOKIE_LANGUE, "__Host-" + COOKIE_LANGUE):
        if nom in biscuits and biscuits[nom].value in LANGUES:
            return biscuits[nom].value
    return negocier(entetes.get("accept-language"))


async def _repondre_413(send: Send, scope: Scope) -> None:
    from controldone.web.i18n import traduire_erreur

    corps = traduire_erreur("Requête trop volumineuse.", _langue_brute(scope)).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(corps)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": corps})


# --- rapports de violation de la CSP (D-3204) -----------------------------------------------------------------------

#: Taille maximale d'un envoi de rapports (un rapport réel fait moins de 2 Ko).
TAILLE_MAX_RAPPORT_CSP = 8 * 1024
#: Rapports journalisés par envoi au plus (``application/reports+json`` peut en grouper plusieurs).
RAPPORTS_MAX_PAR_ENVOI = 5
_TYPES_RAPPORT = ("application/csp-report", "application/reports+json", "application/json")
_SOURCES_MOTS = frozenset(
    {"inline", "eval", "wasm-eval", "data", "blob", "self", "trusted-types-policy", "trusted-types-sink"}
)


def _jeton_sur(valeur: Any, longueur: int = 48) -> str:
    """Valeur réduite à ``[a-z0-9-]`` (nom de directive, disposition) ; ``?`` sinon."""
    v = str(valeur or "").strip().lower()[:longueur]
    return v if v and all(c.isascii() and (c.isalnum() or c == "-") for c in v) else "?"


def _origine(valeur: Any, hote: str) -> str:
    """Source bloquée sans chemin, requête, fragment ni identifiants : ``inline``, ``eval``, ``self`` ou
    ``schéma://hôte[:port]`` (jamais d'URL complète : elle pourrait porter une donnée personnelle)."""
    v = str(valeur or "").strip()[:2048]
    if v.lower() in _SOURCES_MOTS:
        return v.lower()
    try:
        u = urlsplit(v)
        if not u.scheme:
            return "?"
        if u.scheme in ("data", "blob", "about", "chrome-extension", "moz-extension", "safari-extension"):
            return u.scheme
        if not u.hostname:
            return "?"
        if u.hostname == hote:
            return "self"
        port = f":{u.port}" if u.port else ""
    except ValueError:
        return "?"
    return f"{u.scheme}://{u.hostname}{port}"[:120]


def _chemin(valeur: Any) -> str:
    """Chemin du document (sans requête ni fragment), limité à des caractères sûrs."""
    try:
        p = urlsplit(str(valeur or "")[:2048]).path or "/"
    except ValueError:
        return "?"
    return "".join(c if c.isascii() and (c.isalnum() or c in "/_-.") else "_" for c in p)[:120]


def _rapports(donnees: Any) -> list[dict[str, Any]]:
    if isinstance(donnees, dict) and isinstance(
        donnees.get("csp-report"), dict
    ):  # report-uri (ancien format)
        r = donnees["csp-report"]
        return [
            {
                "directive": r.get("effective-directive") or r.get("violated-directive"),
                "bloque": r.get("blocked-uri"),
                "document": r.get("document-uri"),
                "disposition": r.get("disposition"),
            }
        ]
    sortie = []
    if isinstance(donnees, list):  # report-to (API Reporting)
        for x in donnees[:RAPPORTS_MAX_PAR_ENVOI]:
            corps = x.get("body") if isinstance(x, dict) else None
            if isinstance(x, dict) and x.get("type") == "csp-violation" and isinstance(corps, dict):
                sortie.append(
                    {
                        "directive": corps.get("effectiveDirective"),
                        "bloque": corps.get("blockedURL"),
                        "document": corps.get("documentURL"),
                        "disposition": corps.get("disposition"),
                    }
                )
    return sortie


async def _corps_borne(request: Request, limite: int) -> bytes | None:
    """Corps de la requête lu en flux, ``None`` au-delà de ``limite`` octets."""
    corps = bytearray()
    async for morceau in request.stream():
        corps += morceau
        if len(corps) > limite:
            return None
    return bytes(corps)


def recevoir_rapport_csp(request: Request) -> Response:
    """``POST /csp-rapport`` : violations de la CSP envoyées par le navigateur. Sans jeton CSRF (le navigateur
    n'en envoie pas) ; débit borné par adresse ; corps borné à ``TAILLE_MAX_RAPPORT_CSP`` ; journal réduit à la
    directive, à l'origine de la ressource bloquée et au chemin de la page — ni adresse IP, ni URL complète, ni
    extrait de script (``script-sample``)."""
    etat: EtatSecurite = request.app.state.securite
    ip = request.client.host if request.client else "?"
    if not etat.limiteur_csp.autoriser(ip):
        return Response(status_code=429)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() not in _TYPES_RAPPORT:
        return Response(status_code=415)
    corps = depuis_boucle(_corps_borne, request, TAILLE_MAX_RAPPORT_CSP)
    if corps is None:
        return Response(status_code=413)
    try:
        donnees = json.loads(corps)
    except (ValueError, RecursionError):
        return Response(status_code=400)
    hote = (request.url.hostname or "").lower()
    for r in _rapports(donnees)[:RAPPORTS_MAX_PAR_ENVOI]:
        log.warning(
            "csp_violation directive=%s bloque=%s document=%s disposition=%s",
            _jeton_sur(r["directive"]),
            _origine(r["bloque"], hote),
            _chemin(r["document"]),
            _jeton_sur(r["disposition"], 16),
        )
    return Response(status_code=204)
