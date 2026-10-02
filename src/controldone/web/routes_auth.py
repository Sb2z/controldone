"""Connexion (mot de passe, puis second facteur TOTP pour le fondateur), déconnexion, mot de passe."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response

from controldone.auth import (
    EchecAuthentification,
    MotDePasseFaible,
    hacher_mot_de_passe,
    verifier_mot_de_passe,
)
from controldone.auth.roles import Role
from controldone.auth.service import acteur_client, verifier_mot_de_passe_compte, verifier_second_facteur
from controldone.storage.comptes import changer_mot_de_passe, utilisateur
from controldone.web.rendu import page, redirection
from controldone.web.securite import EtatSecurite, acteur_de, formulaire

routeur = APIRouter()
COOKIE_2FA = "cd_2fa"


def _etat(request: Request) -> EtatSecurite:
    return request.app.state.securite


def _ip(request: Request) -> str:
    return request.client.host if request.client else "inconnue"


def _ouvrir_session(request: Request, acteur, *, deux_facteurs: bool) -> Response:
    etat = _etat(request)
    jeton = etat.sessions.emettre(acteur, deux_facteurs=deux_facteurs)
    rep = redirection(request, "/admin" if acteur.role is Role.fondateur else "/espace")
    etat.poser_session(rep, jeton)
    rep.delete_cookie(COOKIE_2FA, path="/")
    return rep


@routeur.get("/")
def accueil(request: Request) -> Response:
    s = getattr(request.state, "session", None)
    if s is None:
        return redirection(request, "/connexion")
    return redirection(request, "/admin" if s.role is Role.fondateur else "/espace")


@routeur.get("/connexion")
def connexion_form(request: Request) -> Response:
    return page(request, "connexion.html.j2", titre="Connexion")


@routeur.post("/connexion")
async def connexion(request: Request) -> Response:
    form = await formulaire(request)
    etat = _etat(request)
    email = str(form.get("email") or "").strip().lower()[:320]
    mdp = str(form.get("mot_de_passe") or "")[:1024]
    if not (etat.limiteur_connexion_ip.autoriser(_ip(request))
            and etat.limiteur_connexion_compte.autoriser(email or "-")):
        return page(request, "connexion.html.j2", titre="Connexion", statut=429,
                    erreur="Trop de tentatives. Patientez quelques minutes avant de réessayer.")
    pf = request.app.state.plateforme
    try:
        user_id, role = verifier_mot_de_passe_compte(pf.db, email, mdp)
        if role == Role.fondateur.value:
            rep = redirection(request, "/connexion/totp")
            rep.set_cookie(COOKIE_2FA, etat.jeton_2fa(user_id), max_age=300, httponly=True,
                           secure=etat.cookie["secure"], samesite="strict" if etat.prod else "lax", path="/")
            return rep
        acteur = acteur_client(pf.db, user_id, ip=_ip(request))
    except EchecAuthentification:
        return page(request, "connexion.html.j2", titre="Connexion", statut=401, email=email,
                    erreur="Identifiants invalides.")
    return _ouvrir_session(request, acteur, deux_facteurs=False)


@routeur.get("/connexion/totp")
def totp_form(request: Request) -> Response:
    if _etat(request).lire_2fa(request.cookies.get(COOKIE_2FA)) is None:
        return redirection(request, "/connexion")
    return page(request, "totp.html.j2", titre="Code de vérification")


@routeur.post("/connexion/totp")
async def totp(request: Request) -> Response:
    form = await formulaire(request)
    etat = _etat(request)
    user_id = etat.lire_2fa(request.cookies.get(COOKIE_2FA))
    if user_id is None:
        return redirection(request, "/connexion", erreur="Étape expirée : reconnectez-vous.")
    if not etat.limiteur_connexion_compte.autoriser("2fa:" + user_id):
        return page(request, "totp.html.j2", titre="Code de vérification", statut=429,
                    erreur="Trop de tentatives. Patientez quelques minutes.")
    pf = request.app.state.plateforme
    try:
        acteur = verifier_second_facteur(pf.db, user_id, str(form.get("code") or "")[:12],
                                         cles_maitresses=pf.cles_maitresses, ip=_ip(request))
    except EchecAuthentification:
        return page(request, "totp.html.j2", titre="Code de vérification", statut=401, erreur="Code invalide.")
    return _ouvrir_session(request, acteur, deux_facteurs=True)


@routeur.post("/deconnexion")
async def deconnexion(request: Request) -> Response:
    await formulaire(request)
    etat = _etat(request)
    s = getattr(request.state, "session", None)
    if s is not None:
        etat.sessions.revoquer(s.sid)
    rep = redirection(request, "/connexion", message="Vous êtes déconnecté.")
    etat.effacer_session(rep)
    return rep


@routeur.get("/compte/mot-de-passe")
def mdp_form(request: Request) -> Response:
    acteur_de(request)
    return page(request, "mot_de_passe.html.j2", titre="Changer de mot de passe")


@routeur.post("/compte/mot-de-passe")
async def mdp(request: Request) -> Response:
    acteur = acteur_de(request)
    form = await formulaire(request)
    pf = request.app.state.plateforme
    actuel, nouveau, confirmation = (str(form.get(k) or "")[:1024] for k in ("actuel", "nouveau", "confirmation"))
    compte = utilisateur(pf.db, acteur.id)
    if compte is None or not verifier_mot_de_passe(compte.mot_de_passe_hash, actuel):
        return page(request, "mot_de_passe.html.j2", titre="Changer de mot de passe", statut=400,
                    erreur="Mot de passe actuel incorrect.")
    if nouveau != confirmation:
        return page(request, "mot_de_passe.html.j2", titre="Changer de mot de passe", statut=400,
                    erreur="Les deux saisies du nouveau mot de passe diffèrent.")
    try:
        empreinte = hacher_mot_de_passe(nouveau)
    except MotDePasseFaible:
        return page(request, "mot_de_passe.html.j2", titre="Changer de mot de passe", statut=400,
                    erreur="Le nouveau mot de passe doit comporter au moins 12 caractères.")
    changer_mot_de_passe(pf.db, acteur.id, empreinte, acteur=acteur)
    return redirection(request, "/", message="Mot de passe modifié.")
