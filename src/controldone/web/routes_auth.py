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
from controldone.auth.roles import Acteur, Role
from controldone.auth.service import acteur_client, verifier_mot_de_passe_compte, verifier_second_facteur
from controldone.storage.comptes import changer_mot_de_passe, utilisateur
from controldone.web.rendu import page, redirection
from controldone.web.routes_compte import langue_du_compte, poser_langue
from controldone.web.securite import EtatSecurite, acteur_de, formulaire_sync

routeur = APIRouter()


def _etat(request: Request) -> EtatSecurite:
    return request.app.state.securite


def _ip(request: Request) -> str:
    return request.client.host if request.client else "inconnue"


def _ouvrir_session(request: Request, acteur, *, deux_facteurs: bool) -> Response:
    etat = _etat(request)
    rep = redirection(request, "/admin" if acteur.role is Role.fondateur else "/espace")
    etat.ouvrir_session(request, rep, acteur, deux_facteurs=deux_facteurs)  # enregistrée (sessions actives)
    etat.effacer_2fa(rep)
    langue = langue_du_compte(
        request, acteur.id
    )  # préférence du compte, reposée dans ce navigateur (bloc I3)
    if langue is not None:
        poser_langue(request, rep, langue)
    return rep


def _succes(etat: EtatSecurite, request: Request, cle_compte: str) -> None:
    """Identifiants valides : le compteur du compte repart à zéro et l'adresse récupère son jeton — seuls les
    échecs épuisent la limite (D-3201 : des connexions de test réussies ne bloquent plus le fondateur)."""
    etat.limiteur_connexion_compte.effacer(cle_compte)
    etat.limiteur_connexion_ip.rembourser(_ip(request))


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
def connexion(request: Request) -> Response:
    form = formulaire_sync(request)
    etat = _etat(request)
    email = str(form.get("email") or "").strip().lower()[:320]
    mdp = str(form.get("mot_de_passe") or "")[:1024]
    if not (
        etat.limiteur_connexion_ip.autoriser(_ip(request))
        and etat.limiteur_connexion_compte.autoriser(email or "-")
    ):
        return page(
            request,
            "connexion.html.j2",
            titre="Connexion",
            statut=429,
            erreur="Trop de tentatives. Patientez quelques minutes avant de réessayer.",
        )
    pf = request.app.state.plateforme
    try:
        user_id, role = verifier_mot_de_passe_compte(pf.db, email, mdp)
        _succes(etat, request, email or "-")
        if role == Role.fondateur.value:
            rep = redirection(request, "/connexion/totp")
            etat.poser_2fa(rep, user_id)  # __Host-cd_2fa en production (D-3604)
            return rep
        acteur = acteur_client(pf.db, user_id, ip=_ip(request))
    except EchecAuthentification:
        return page(
            request,
            "connexion.html.j2",
            titre="Connexion",
            statut=401,
            email=email,
            erreur="Identifiants invalides.",
        )
    return _ouvrir_session(request, acteur, deux_facteurs=False)


@routeur.get("/connexion/totp")
def totp_form(request: Request) -> Response:
    if _etat(request).lire_2fa_requete(request) is None:
        return redirection(request, "/connexion")
    return page(request, "totp.html.j2", titre="Code de vérification")


@routeur.post("/connexion/totp")
def totp(request: Request) -> Response:
    form = formulaire_sync(request)
    etat = _etat(request)
    user_id = etat.lire_2fa_requete(request)
    if user_id is None:
        return redirection(request, "/connexion", erreur="Étape expirée : reconnectez-vous.")
    if not etat.limiteur_connexion_compte.autoriser("2fa:" + user_id):
        return page(
            request,
            "totp.html.j2",
            titre="Code de vérification",
            statut=429,
            erreur="Trop de tentatives. Patientez quelques minutes.",
        )
    pf = request.app.state.plateforme
    try:
        acteur = verifier_second_facteur(
            pf.db,
            user_id,
            str(form.get("code") or "")[:12],
            cles_maitresses=pf.cles_maitresses,
            ip=_ip(request),
        )
    except EchecAuthentification:
        return page(
            request, "totp.html.j2", titre="Code de vérification", statut=401, erreur="Code invalide."
        )
    etat.limiteur_connexion_compte.effacer("2fa:" + user_id)
    return _ouvrir_session(request, acteur, deux_facteurs=True)


@routeur.post("/deconnexion")
def deconnexion(request: Request) -> Response:
    formulaire_sync(request)
    etat = _etat(request)
    s = getattr(request.state, "session", None)
    if s is not None:
        etat.sessions.revoquer(s.sid, debut=s.debut)  # tous les processus, jusqu'à l'expiration (D-3202)
    rep = redirection(request, "/connexion", message="Vous êtes déconnecté.")
    etat.effacer_session(rep)
    return rep


@routeur.get("/compte/mot-de-passe")
def mdp_form(request: Request) -> Response:
    acteur_de(request)
    return page(request, "mot_de_passe.html.j2", titre="Changer de mot de passe")


@routeur.post("/compte/mot-de-passe")
def mdp(request: Request) -> Response:
    acteur = acteur_de(request)
    form = formulaire_sync(request)
    pf = request.app.state.plateforme
    etat = _etat(request)
    if not etat.limiteur_connexion_compte.autoriser("mdp:" + acteur.id):
        return page(
            request,
            "mot_de_passe.html.j2",
            titre="Changer de mot de passe",
            statut=429,
            erreur="Trop de tentatives. Patientez quelques minutes avant de réessayer.",
        )
    actuel, nouveau, confirmation = (
        str(form.get(k) or "")[:1024] for k in ("actuel", "nouveau", "confirmation")
    )
    compte = utilisateur(pf.db, acteur.id)
    if compte is None or not verifier_mot_de_passe(compte.mot_de_passe_hash, actuel):
        return page(
            request,
            "mot_de_passe.html.j2",
            titre="Changer de mot de passe",
            statut=400,
            erreur="Mot de passe actuel incorrect.",
        )
    if nouveau != confirmation:
        return page(
            request,
            "mot_de_passe.html.j2",
            titre="Changer de mot de passe",
            statut=400,
            erreur="Les deux saisies du nouveau mot de passe diffèrent.",
        )
    try:
        empreinte = hacher_mot_de_passe(nouveau)
    except MotDePasseFaible:
        return page(
            request,
            "mot_de_passe.html.j2",
            titre="Changer de mot de passe",
            statut=400,
            erreur="Le nouveau mot de passe doit comporter au moins 12 caractères.",
        )
    changer_mot_de_passe(pf.db, acteur.id, empreinte, acteur=acteur)
    # Toutes les sessions ouvertes avec l'ancien mot de passe sont révoquées (autres navigateurs, cookie volé) ;
    # celle-ci est remplacée par une session neuve (D-3202, RS-17).
    s = request.state.session
    etat.sessions.revoquer_utilisateur(acteur.id)
    etat.limiteur_connexion_compte.effacer("mdp:" + acteur.id)
    rep = redirection(request, "/", message="Mot de passe modifié. Vos autres sessions sont fermées.")
    etat.ouvrir_session(request, rep, Acteur(s.user_id, s.role, s.tenant_id), deux_facteurs=s.deux_facteurs)
    return rep
