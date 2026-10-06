"""Rendu des pages : environnement Jinja2 (échappement automatique **activé**), filtres selon la langue
(français par défaut, anglais : ``web/i18n.py``, D-3803), contexte commun (acteur, jeton CSRF, bandeau « DONNÉES
FICTIVES », avertissement de pied de page)."""

from __future__ import annotations

import base64
import re
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from controldone.formatage import format_montant, format_nombre
from controldone.guardrails import AVERTISSEMENT, PHRASE_RENVOI
from controldone.web.i18n import (
    AVERTISSEMENT_EN,
    LANGUES,
    PHRASE_RENVOI_EN,
    activer,
    courante,
    langue_de,
    textes_js,
    traduire,
)

__all__ = ["page", "redirection", "retour_sur", "texte_visible"]

_PARIS = ZoneInfo("Europe/Paris")
_MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
_MOIS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _anglais(texte_fr: str) -> str:
    """Nombre formaté à la française (``1 234,56``) -> à l'anglaise (``1,234.56``) : mêmes chiffres exacts."""
    return texte_fr.replace(",", ".").replace("\u00a0", ",") if texte_fr else texte_fr


def _montant(x: Any, devise: str | None = "EUR") -> str:
    if x is None or x == "":
        return "—"
    try:
        texte = format_montant(Decimal(str(x)), devise)
    except Exception:
        return str(x)
    if courante() == "en":
        nombre, _sep, unite = texte.rpartition("\u00a0") if devise else (texte, "", "")
        return f"{_anglais(nombre)}\u00a0{unite}" if devise else _anglais(texte)
    return texte


def _nombre(x: Any) -> str:
    if x is None:
        return "—"
    try:
        texte = format_nombre(Decimal(str(x)))
    except Exception:
        return str(x)
    return _anglais(texte) if courante() == "en" else texte


def _date(x: Any, heure: bool = True) -> str:
    if not x:
        return "—"
    if isinstance(x, str):
        try:
            x = datetime.fromisoformat(x.replace("Z", "+00:00"))
        except ValueError:
            return x
    if isinstance(x, datetime):
        if x.tzinfo is None:
            from datetime import UTC

            x = x.replace(tzinfo=UTC)
        x = x.astimezone(_PARIS)
        if courante() == "en":
            txt = f"{x.day} {_MOIS_EN[x.month - 1]} {x.year}"
            return f"{txt}, {x:%H:%M}" if heure else txt
        txt = f"{x.day} {_MOIS[x.month - 1]} {x.year}"
        return f"{txt} à {x:%H:%M}" if heure else txt
    return str(x)


def _taille(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    en = courante() == "en"
    for unite in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unite == "Go":
            if en:
                u = {"o": "B", "Ko": "KB", "Mo": "MB", "Go": "GB"}[unite]
                return f"{n:.0f} {u}" if unite == "o" else f"{n:.1f} {u}"
            return f"{n:.0f} {unite}" if unite == "o" else f"{n:.1f} {unite}".replace(".", ",")
        n /= 1024
    return str(n)


@lru_cache(maxsize=1)
def environnement() -> Environment:
    env = Environment(
        loader=PackageLoader("controldone.web", "templates"),
        autoescape=select_autoescape(["html", "j2"], default=True, default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    env.filters.update(
        montant=_montant,
        nombre=_nombre,
        date=_date,
        taille=_taille,
        trad=lambda t: traduire(t),
        b64=lambda b: base64.b64encode(b).decode("ascii") if b else "",
    )
    from controldone.services.publication import formats_disponibles
    from controldone.web.listes_vues import ALERTES_GRAVES, libelle_alerte

    env.globals.update(
        AVERTISSEMENT=AVERTISSEMENT,
        PHRASE_RENVOI=PHRASE_RENVOI,
        formats=formats_disponibles,
        AVERTISSEMENT_EN=AVERTISSEMENT_EN,
        PHRASE_RENVOI_EN=PHRASE_RENVOI_EN,
        LANGUES=LANGUES,
        _=traduire,
        langue_courante=courante,
        libelle_alerte=libelle_alerte,
        ALERTES_GRAVES=ALERTES_GRAVES,
    )
    return env


def page(
    request: Request,
    nom: str,
    *,
    titre: str,
    statut: int = 200,
    demo: bool = False,
    nav: str | None = None,
    **contexte: Any,
) -> HTMLResponse:
    etat = request.app.state.securite
    session = getattr(request.state, "session", None)
    flash = etat.lire_flash(request)
    acteur = session.acteur() if session is not None else None
    langue = langue_de(request)
    activer(langue)
    for cle in ("message", "erreur"):  # messages d'erreur du code (textes connus du catalogue)
        if isinstance(contexte.get(cle), str):
            contexte[cle] = traduire(contexte[cle])
    html = (
        environnement()
        .get_template(nom)
        .render(
            request=request,
            titre=traduire(titre),
            acteur=acteur,
            csrf=etat.jeton(request),
            demo=demo,
            flash=flash,
            nav=nav,
            chemin=request.url.path,
            langue=langue,
            textes_js=textes_js(langue),
            retour_langue=_retour_langue(request, statut),
            **contexte,
        )
    )
    rep = HTMLResponse(html, status_code=statut)
    if flash:
        etat.effacer_flash(rep)
    etat.poser_presession(request, rep)
    return rep


def _retour_langue(request: Request, statut: int) -> str:
    """Adresse de retour du choix de langue : la page courante (chemin relatif validé par ``retour_sur``) ; pour une
    page d'erreur, l'accueil — une 404 ne doit rien renvoyer de l'adresse demandée (cloisonnement : réponse
    identique pour une ressource d'un autre client et une ressource inexistante)."""
    if statut >= 400:
        return "/"
    chemin = request.url.path
    return retour_sur(
        chemin + ("?" + request.url.query if request.url.query else ""), retour_sur(chemin, "/")
    )


def redirection(
    request: Request, url: str, *, message: str | None = None, erreur: str | None = None, **params: Any
) -> Response:
    """Redirection 303 avec message flash, traduit dans la langue de la requête (texte du catalogue, paramètres
    ``params`` au format ``str.format``)."""
    rep = RedirectResponse(url, status_code=303)
    if message or erreur:
        texte = traduire(erreur or message or "", langue_de(request), **params)
        request.app.state.securite.flash(rep, texte, erreur=bool(erreur))
    return rep


_CHEMIN = re.compile(r"/[A-Za-z0-9_\-./]*")
_REQUETE = re.compile(r"(?:[A-Za-z0-9_\-.~+=&]|%[0-9A-Fa-f]{2})*")
_ANCRE = re.compile(r"[A-Za-z0-9_\-]*")
RETOUR_MAX = 2000


def retour_sur(valeur: Any, defaut: str) -> str:
    """URL de retour d'un formulaire : chemin relatif **de cette application** seulement (pas de redirection
    ouverte), requête encodée admise pour revenir à une liste filtrée (D-3802).

    Refusés (``defaut``) : tout ce qui n'est pas une chaîne ASCII imprimable sans espace de 2 000 caractères au
    plus ; schéma ou hôte (``https:``, ``//hôte``, ``/\\hôte``) ; chemin hors ``[A-Za-z0-9_-./]`` (donc sans
    ``%`` : pas de ``%2F`` ni de ``%5C`` déguisés), ``//`` ou segment ``..`` ; requête hors caractères
    non réservés, ``+``, ``=``, ``&`` et ``%XX`` (hexadécimal), ou qui encode un caractère de contrôle
    (``%00``–``%1F``, ``%7F``) ; ancre hors ``[A-Za-z0-9_-]``. Admise, l'adresse est renvoyée telle quelle."""
    from urllib.parse import unquote, urlsplit

    if not isinstance(valeur, str) or not valeur or len(valeur) > RETOUR_MAX:
        return defaut
    if not all(0x21 <= ord(ch) <= 0x7E for ch in valeur) or "\\" in valeur:
        return defaut
    if not valeur.startswith("/") or valeur.startswith("//"):
        return defaut
    try:
        parts = urlsplit(valeur)
    except ValueError:
        return defaut
    if parts.scheme or parts.netloc:
        return defaut
    chemin, requete, ancre = parts.path, parts.query, parts.fragment
    if not _CHEMIN.fullmatch(chemin) or "//" in chemin or ".." in chemin.split("/"):
        return defaut
    if not _REQUETE.fullmatch(requete) or not _ANCRE.fullmatch(ancre):
        return defaut
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in unquote(requete)):
        return defaut
    return valeur


def texte_visible(html: str) -> str:
    """Texte affiché d'une page (balises, styles, scripts et attributs retirés) : contrôle des garde-fous."""
    t = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()
