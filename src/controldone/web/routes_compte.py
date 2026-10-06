"""Compte de l'utilisateur connecté : page « Mon compte » (langue de l'interface enregistrée sur le compte, bloc
I3), sessions actives (« fermer mes autres sessions », D-3804) et choix de langue (D-3803).

Langue : le cookie ``cd_langue`` reste la préférence du navigateur (pages sans session, connexion) ; pour un
utilisateur connecté, le choix est **aussi** enregistré sur le compte (``users.langue``) et reposé dans le cookie à
chaque connexion, donc suivi d'un navigateur à l'autre.

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

from controldone.storage.comptes import definir_langue, utilisateur
from controldone.web.i18n import COOKIE_LANGUE, LANGUES
from controldone.web.rendu import page, redirection, retour_sur
from controldone.web.securite import EtatSecurite, NonConnecte, acteur_de, formulaire_sync

routeur = APIRouter()

#: Préférence de langue conservée un an (aucune donnée personnelle).
DUREE_LANGUE_S = 365 * 24 * 3600


def _etat(request: Request) -> EtatSecurite:
    return request.app.state.securite


def _ref(etat: EtatSecurite, sid: str) -> str:
    return hmac.new(
        (etat.secret_signature + "|session-ref").encode(), sid.encode(), hashlib.sha256
    ).hexdigest()[:24]


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
    vues = [
        {
            "ref": _ref(etat, x.sid),
            "courante": x.sid == s.sid or bool(getattr(x, "courante", False)),
            "debut": _instant(x.debut),
            "vu": _instant(x.vu),
            "appareil": x.appareil or "",
            "reseau": x.reseau or "",
        }
        for x in liste
    ]
    if not any(v["courante"] for v in vues):  # session ouverte avant l'enregistrement des sessions
        vues.insert(
            0,
            {
                "ref": _ref(etat, s.sid),
                "courante": True,
                "debut": _instant(s.debut),
                "vu": _instant(s.emis),
                "appareil": "",
                "reseau": "",
            },
        )
    vues.sort(key=lambda v: not v["courante"])
    return page(
        request,
        "compte/sessions.html.j2",
        titre="Mes sessions actives",
        nav="sessions",
        sessions=vues,
        autres=sum(1 for v in vues if not v["courante"]),
    )


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
    cible = next(
        (x for x in liste if hmac.compare_digest(_ref(etat, x.sid), ref[:64]) and x.sid != s.sid), None
    )
    fermer = getattr(etat.sessions, "fermer_session", None)
    if cible is None or fermer is None or not fermer(acteur.id, cible.sid):
        return redirection(request, "/compte/sessions", erreur="Session introuvable ou déjà fermée.")
    return redirection(request, "/compte/sessions", message="Session fermée.")


def poser_langue(request: Request, reponse: Response, langue: str) -> None:
    """Cookie de préférence de langue (un an, ``__Host-`` en production) ; la réponse en cours (message flash)
    suit déjà la langue choisie."""
    request.state.langue = langue
    etat = _etat(request)
    nom = ("__Host-" if etat.prod else "") + COOKIE_LANGUE
    reponse.set_cookie(
        nom,
        langue,
        max_age=DUREE_LANGUE_S,
        httponly=True,
        secure=etat.cookie["secure"],
        samesite="lax",
        path="/",
    )


def langue_du_compte(request: Request, user_id: str) -> str | None:
    """Langue enregistrée sur le compte (``None`` : aucune préférence ; lue à la connexion)."""
    compte = utilisateur(request.app.state.plateforme.db, user_id)
    lg = compte.langue if compte is not None else None
    return lg if lg in LANGUES else None


def _enregistrer(request: Request, langue: str) -> bool:
    """Enregistre la langue sur le compte connecté ; ``False`` sans session valide."""
    if getattr(request.state, "session", None) is None:
        return False
    try:
        acteur = acteur_de(request)
    except NonConnecte:
        return False
    definir_langue(request.app.state.plateforme.db, acteur.id, langue, acteur=acteur)
    return True


@routeur.post("/preferences/langue")
def choisir_langue(request: Request) -> Response:
    """Langue de l'interface (bouton FR/EN de l'en-tête) ; formulaire avec jeton CSRF, connecté ou non. Connecté :
    le choix est aussi enregistré sur le compte."""
    form = formulaire_sync(request)
    langue = form.get("langue")
    retour = retour_sur(form.get("retour"), "/")
    if not isinstance(langue, str) or langue not in LANGUES:
        return redirection(request, retour)
    _enregistrer(request, langue)
    request.state.langue = langue  # message dans la langue choisie
    rep = redirection(request, retour)
    poser_langue(request, rep, langue)
    return rep


@routeur.get("/compte")
def compte(request: Request) -> Response:
    acteur = acteur_de(request)
    info = utilisateur(request.app.state.plateforme.db, acteur.id)
    return page(
        request,
        "compte/compte.html.j2",
        titre="Mon compte",
        nav="compte",
        email=info.email if info else "",
        langue_compte=info.langue if info else None,
    )


@routeur.post("/compte/langue")
def langue_compte(request: Request) -> Response:
    """Langue de l'interface enregistrée sur le compte (page « Mon compte »)."""
    acteur_de(request)
    form = formulaire_sync(request)
    langue = form.get("langue")
    if not isinstance(langue, str) or langue not in LANGUES:
        return redirection(request, "/compte", erreur="Langue inconnue.")
    _enregistrer(request, langue)
    request.state.langue = langue
    rep = redirection(request, "/compte", message="Langue de l'interface enregistrée.")
    poser_langue(request, rep, langue)
    return rep
