"""Fabrique de l'application : ``create_app(parametres)``."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from controldone.auth import (
    GestionnaireSessions,
    SessionInvalide,
    parametres_cookie,
    secrets_session_depuis_env,
)
from controldone.ingest.reception import Limites
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide
from controldone.storage.erreurs import AccesRefuse
from controldone.web.rendu import page
from controldone.web.securite import CsrfInvalide, EnTetesSecurite, EtatSecurite, LimiteCorps, NonConnecte

__all__ = ["ParametresWeb", "create_app"]

log = logging.getLogger("controldone.web")
STATIQUE = Path(__file__).parent / "static"
CHEMINS_DEPOT = ("/espace/depot", "/api/v1/lots", "/api/v1/einvoices")


@dataclass
class ParametresWeb:
    """Paramètres de l'application (``None`` : valeur lue dans l'environnement)."""

    plateforme: Plateforme | None = None
    secrets_session: list[str] | None = None
    #: Production : cookie ``__Host-`` + ``Secure`` + ``SameSite=Strict``. Défaut : ``CONTROLDONE_ENV=prod``.
    prod: bool | None = None
    #: En-tête HSTS (derrière un mandataire TLS). Défaut : ``prod``.
    https: bool | None = None
    limites: Limites = field(default_factory=Limites)
    #: Worker intégré (fil d'exécution) pour la démonstration : ``controldone serve`` l'active.
    worker_integre: bool = False


def _middleware_session(app: FastAPI):
    async def session(request: Request, call_next: Any) -> Response:
        etat: EtatSecurite = app.state.securite
        request.state.session = None
        jeton = request.cookies.get(etat.nom_cookie)
        nouveau = None
        invalide = False
        if jeton:
            try:
                request.state.session, nouveau = etat.sessions.rafraichir(jeton)
            except SessionInvalide:
                invalide = True
        reponse = await call_next(request)
        if nouveau:
            etat.poser_session(reponse, nouveau)
        elif invalide:
            etat.effacer_session(reponse)
        return reponse

    return session


def create_app(parametres: ParametresWeb | None = None) -> FastAPI:
    from controldone.storage.cles import mode_execution

    p = parametres or ParametresWeb()
    plateforme = p.plateforme or Plateforme.depuis_env()
    plateforme.limites = p.limites
    prod = (mode_execution() == "prod") if p.prod is None else p.prod
    https = prod if p.https is None else p.https
    secrets_ = p.secrets_session or secrets_session_depuis_env()
    etat = EtatSecurite(
        sessions=GestionnaireSessions(secrets_), secret_csrf=secrets_[-1] + "|csrf",
        secret_signature=secrets_[-1] + "|signature", prod=prod, https=https,
        cookie=parametres_cookie(prod=prod),
    )
    worker = _worker(plateforme) if p.worker_integre else None

    @asynccontextmanager
    async def cycle(_app: FastAPI) -> AsyncIterator[None]:
        fil = None
        if worker is not None:  # pragma: no cover - exercé par ``controldone serve``
            fil = threading.Thread(target=worker.boucle, name="worker-integre", daemon=True)
            fil.start()
        yield
        if worker is not None:  # pragma: no cover
            worker.arreter()

    app = FastAPI(title="ControlDOne", docs_url=None, redoc_url=None, openapi_url=None, lifespan=cycle)
    app.state.plateforme = plateforme
    app.state.securite = etat

    from controldone.api import creer_api
    from controldone.web import routes_admin, routes_auth, routes_client

    app.include_router(routes_auth.routeur)
    app.include_router(routes_admin.routeur)
    app.include_router(routes_client.routeur)
    app.mount("/api/v1", creer_api(plateforme, etat))
    app.mount("/static", StaticFiles(directory=STATIQUE), name="static")

    @app.get("/sante", include_in_schema=False)
    def sante() -> JSONResponse:
        return JSONResponse({"statut": "ok"})

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.exception_handler(NonConnecte)
    async def _non_connecte(request: Request, exc: NonConnecte) -> Response:
        from controldone.web.rendu import redirection

        return redirection(request, "/connexion")

    @app.exception_handler(AccesRefuse)
    async def _introuvable(request: Request, exc: AccesRefuse) -> Response:
        return page(request, "erreur.html.j2", titre="Page introuvable", statut=404,
                    message="Cette page n'existe pas ou n'est pas accessible avec votre compte.")

    @app.exception_handler(Interdit)
    async def _interdit(request: Request, exc: Interdit) -> Response:
        return page(request, "erreur.html.j2", titre="Action non autorisée", statut=403,
                    message="Cette action n'est pas autorisée pour votre compte.")

    @app.exception_handler(CsrfInvalide)
    async def _csrf(request: Request, exc: CsrfInvalide) -> Response:
        return page(request, "erreur.html.j2", titre="Formulaire expiré", statut=403,
                    message="Le formulaire a expiré ou n'a pas été émis par cette application. "
                            "Rechargez la page puis recommencez.")

    @app.exception_handler(RequeteInvalide)
    async def _invalide(request: Request, exc: RequeteInvalide) -> Response:
        return page(request, "erreur.html.j2", titre="Requête invalide", statut=400, message=str(exc))

    @app.exception_handler(404)
    async def _404(request: Request, exc: Exception) -> Response:
        return page(request, "erreur.html.j2", titre="Page introuvable", statut=404,
                    message="Cette page n'existe pas ou n'est pas accessible avec votre compte.")

    app.add_middleware(BaseHTTPMiddleware, dispatch=_middleware_session(app))
    app.add_middleware(LimiteCorps, limite=2 * 1024 * 1024, limite_depot=p.limites.taille_lot + 16 * 1024 * 1024,
                       chemins_depot=CHEMINS_DEPOT)
    app.add_middleware(EnTetesSecurite, https=https)

    return app


def _worker(plateforme: Plateforme) -> Any:
    """Worker de démonstration dans un fil d'exécution (production : ``python -m controldone.jobs.worker``)."""
    import controldone.jobs.handlers  # noqa: F401  (handlers intégrés + recontrôle)
    from controldone.jobs.worker import Worker

    return Worker(plateforme.db, worker_id="web-integre", lease_s=120, poll_s=1.0,
                  services={"vault": plateforme.vault})
