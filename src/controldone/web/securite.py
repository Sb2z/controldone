"""Sécurité HTTP de l'interface : session (cookie signé, rotation), CSRF sur chaque POST, en-têtes de
sécurité, limite de taille des corps de requête, messages flash signés.

- Le client (``tenant_id``) vient **toujours** de la session authentifiée (``Acteur``), jamais d'un
  paramètre. Le fondateur désigne un client dans l'URL, mais chaque ouverture passe par
  ``OperatorScope.client`` (journal d'audit avec motif).
- CSRF : jeton ``nonce.HMAC(secret, sid|nonce)`` lié à la session (``auth.jetons``) ; avant connexion, lié
  à un identifiant de pré-session (cookie ``HttpOnly``).
- En-têtes : CSP ``default-src 'self'`` (aucune ressource externe, aucun script en ligne), ``X-Frame-Options:
  DENY``, ``Referrer-Policy: same-origin``, ``X-Content-Type-Options: nosniff``, ``Permissions-Policy``,
  HSTS si HTTPS ; ``Cache-Control: no-store`` sur les pages authentifiées.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from controldone.auth import DonneesSession, GestionnaireSessions, LimiteurDebit, jeton_csrf, verifier_csrf
from controldone.auth.roles import Acteur

__all__ = [
    "CSP",
    "CsrfInvalide",
    "EnTetesSecurite",
    "EtatSecurite",
    "LimiteCorps",
    "NonConnecte",
]

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
#: Rapport HTML affiché tel quel (gabarit maison, styles intégrés, aucun script) : CSP fermée.
CSP_RAPPORT = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'"


class NonConnecte(Exception):
    """Aucune session valide : redirection vers la connexion (pages) ou 401 (API)."""


class CsrfInvalide(Exception):
    pass


@dataclass
class EtatSecurite:
    sessions: GestionnaireSessions
    secret_csrf: str
    secret_signature: str
    prod: bool
    https: bool
    cookie: dict[str, Any]
    limiteur_connexion_ip: LimiteurDebit = field(default_factory=lambda: LimiteurDebit(10, 10 / 300))
    limiteur_connexion_compte: LimiteurDebit = field(default_factory=lambda: LimiteurDebit(5, 5 / 300))
    limiteur_api: LimiteurDebit = field(default_factory=lambda: LimiteurDebit(120, 2.0))

    @property
    def nom_cookie(self) -> str:
        return self.cookie["key"]

    @property
    def nom_presession(self) -> str:
        return "__Host-cd_pre" if self.prod else "cd_pre"

    def _ser(self, sel: str) -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(self.secret_signature, salt=sel)

    # --- session ---
    def poser_session(self, reponse: Response, jeton: str) -> None:
        reponse.set_cookie(**{**self.cookie, "value": jeton})

    def effacer_session(self, reponse: Response) -> None:
        reponse.delete_cookie(self.nom_cookie, path="/", secure=self.cookie["secure"], httponly=True,
                              samesite=self.cookie["samesite"])

    # --- second facteur en attente (5 minutes) ---
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
        reponse.set_cookie("cd_flash", self._ser("controldone.flash").dumps({"m": message[:500], "e": erreur}),
                           max_age=60, httponly=True, secure=self.cookie["secure"], samesite="lax", path="/")

    def lire_flash(self, request: Request) -> dict[str, Any] | None:
        brut = request.cookies.get("cd_flash")
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
            reponse.set_cookie(self.nom_presession, sid, httponly=True, secure=self.cookie["secure"],
                               samesite="strict" if self.prod else "lax", path="/", max_age=3600)

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


def acteur_de(request: Request) -> Acteur:
    s: DonneesSession | None = getattr(request.state, "session", None)
    if s is None:
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
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=()",
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

    def __init__(self, app: ASGIApp, *, limite: int, limite_depot: int, chemins_depot: tuple[str, ...]) -> None:
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
                        await _repondre_413(send)
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
                await _repondre_413(send)


async def _repondre_413(send: Send) -> None:
    corps = "Requête trop volumineuse.".encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(corps)).encode())]})
    await send({"type": "http.response.body", "body": corps})
