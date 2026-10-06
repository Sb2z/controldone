"""Compte de l'utilisateur connecté : sessions actives (« fermer mes autres sessions », D-3804) et langue de
l'interface (D-3803).

Les sessions viennent de l'API du bloc sécurité (``GestionnaireSessions.sessions_actives``,
``fermer_session``, ``fermer_autres_sessions``, D-3603). Une session est désignée dans la page par une
**référence** (HMAC tronqué de son identifiant) : l'identifiant de session n'est jamais écrit dans le HTML, et une
référence ne désigne qu'une session du compte connecté."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response

from controldone.web.i18n import COOKIE_LANGUE, LANGUES
from controldone.web.rendu import page, redirection, retour_sur
from controldone.web.securite import EtatSecurite, acteur_de, formulaire_sync

routeur = APIRouter()

#: Préférence de langue conservée un an (aucune donnée personnelle).
DUREE_LANGUE_S = 365 * 24 * 3600


def _etat(request: Request) -> EtatSecurite:
    return request.app.state.securite


def _ref(etat: EtatSecurite, sid: str) -> str:
    return hmac.new((etat.secret_signature + "|session-ref").encode(), sid.encode(), hashlib.sha256).hexdigest()[:24]


def _sessions(request: Request) -> tuple[Any, list[Any]]:
    acteur_de(request)
    s = request.state.session
    lister = getattr(_etat(request).sessions, "sessions_actives", None)
    liste = list(lister(s.user_id, sid_courant=s.sid)) if lister is not None else []
    return s, liste


def _instant(x: float | None) -> datetime | None:
    return datetime.fromtimestamp(x, tz=UTC) if x else None


@routeur.get("/compte/sessions")
def sessions(request: Request) -> Response:
    s, liste = _sessions(request)
    etat = _etat(request)
    vues = [{"ref": _ref(etat, x.sid), "courante": x.sid == s.sid or bool(getattr(x, "courante", False)),
             "debut": _instant(x.debut), "vu": _instant(x.vu), "appareil": x.appareil or "",
             "reseau": x.reseau or ""} for x in liste]
    if not any(v["courante"] for v in vues):  # session ouverte avant l'enregistrement des sessions
        vues.insert(0, {"ref": _ref(etat, s.sid), "courante": True, "debut": _instant(s.debut),
                        "vu": _instant(s.emis), "appareil": "", "reseau": ""})
    vues.sort(key=lambda v: not v["courante"])
    return page(request, "compte/sessions.html.j2", titre="Mes sessions actives", nav="sessions", sessions=vues,
                autres=sum(1 for v in vues if not v["courante"]))


@routeur.post("/compte/sessions/fermer-autres")
def fermer_autres(request: Request) -> Response:
    acteur = acteur_de(request)
    formulaire_sync(request)
    s = request.state.session
    etat = _etat(request)
    fermer = getattr(etat.sessions, "fermer_autres_sessions", None)
    if fermer is not None:
        n = fermer(acteur.id, s.sid)
        return redirection(request, "/compte/sessions", message="{n} autre(s) session(s) fermée(s).", n=n)
    # repli sans registre des sessions : toutes les sessions sont coupées, celle-ci est remplacée (D-3202)
    etat.sessions.revoquer_utilisateur(acteur.id)
    rep = redirection(request, "/compte/sessions", message="Vos autres sessions sont fermées.")
    etat.ouvrir_session(request, rep, acteur, deux_facteurs=s.deux_facteurs)
    return rep


@routeur.post("/compte/sessions/{ref}/fermer")
def fermer_une(request: Request, ref: str) -> Response:
    acteur = acteur_de(request)
    formulaire_sync(request)
    s, liste = _sessions(request)
    etat = _etat(request)
    cible = next((x for x in liste if hmac.compare_digest(_ref(etat, x.sid), ref[:64]) and x.sid != s.sid), None)
    fermer = getattr(etat.sessions, "fermer_session", None)
    if cible is None or fermer is None or not fermer(acteur.id, cible.sid):
        return redirection(request, "/compte/sessions", erreur="Session introuvable ou déjà fermée.")
    return redirection(request, "/compte/sessions", message="Session fermée.")


@routeur.post("/preferences/langue")
def choisir_langue(request: Request) -> Response:
    """Langue de l'interface (cookie de préférence) ; formulaire avec jeton CSRF, connecté ou non."""
    form = formulaire_sync(request)
    langue = form.get("langue")
    retour = retour_sur(form.get("retour"), "/")
    if not isinstance(langue, str) or langue not in LANGUES:
        return redirection(request, retour)
    request.state.langue = langue  # message dans la langue choisie
    etat = _etat(request)
    rep = redirection(request, retour)
    nom = ("__Host-" if etat.prod else "") + COOKIE_LANGUE
    rep.set_cookie(nom, langue, max_age=DUREE_LANGUE_S, httponly=True, secure=etat.cookie["secure"],
                   samesite="lax", path="/")
    return rep
