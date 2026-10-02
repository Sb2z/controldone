"""Rendu des pages : environnement Jinja2 (échappement automatique **activé**), filtres en français,
contexte commun (acteur, jeton CSRF, bandeau « DONNÉES FICTIVES », avertissement de pied de page)."""

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

__all__ = ["page", "redirection", "texte_visible"]

_PARIS = ZoneInfo("Europe/Paris")
_MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def _montant(x: Any, devise: str | None = "EUR") -> str:
    if x is None or x == "":
        return "—"
    try:
        return format_montant(Decimal(str(x)), devise)
    except Exception:
        return str(x)


def _nombre(x: Any) -> str:
    if x is None:
        return "—"
    try:
        return format_nombre(Decimal(str(x)))
    except Exception:
        return str(x)


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
        txt = f"{x.day} {_MOIS[x.month - 1]} {x.year}"
        return f"{txt} à {x:%H:%M}" if heure else txt
    return str(x)


def _taille(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    for unite in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unite == "Go":
            return f"{n:.0f} {unite}" if unite == "o" else f"{n:.1f} {unite}".replace(".", ",")
        n /= 1024
    return str(n)


@lru_cache(maxsize=1)
def environnement() -> Environment:
    env = Environment(
        loader=PackageLoader("controldone.web", "templates"),
        autoescape=select_autoescape(["html", "j2"], default=True, default_for_string=True),
        trim_blocks=True, lstrip_blocks=True, undefined=StrictUndefined,
    )
    env.filters.update(montant=_montant, nombre=_nombre, date=_date, taille=_taille,
                       b64=lambda b: base64.b64encode(b).decode("ascii") if b else "")
    env.globals.update(AVERTISSEMENT=AVERTISSEMENT, PHRASE_RENVOI=PHRASE_RENVOI)
    return env


def page(request: Request, nom: str, *, titre: str, statut: int = 200, demo: bool = False,
         nav: str | None = None, **contexte: Any) -> HTMLResponse:
    etat = request.app.state.securite
    session = getattr(request.state, "session", None)
    flash = etat.lire_flash(request)
    acteur = session.acteur() if session is not None else None
    html = environnement().get_template(nom).render(
        request=request, titre=titre, acteur=acteur, csrf=etat.jeton(request), demo=demo, flash=flash, nav=nav,
        chemin=request.url.path, **contexte)
    rep = HTMLResponse(html, status_code=statut)
    if flash:
        rep.delete_cookie("cd_flash", path="/")
    etat.poser_presession(request, rep)
    return rep


def redirection(request: Request, url: str, *, message: str | None = None, erreur: str | None = None) -> Response:
    rep = RedirectResponse(url, status_code=303)
    if message or erreur:
        request.app.state.securite.flash(rep, erreur or message or "", erreur=bool(erreur))
    return rep


def retour_sur(valeur: Any, defaut: str) -> str:
    """URL de retour d'un formulaire : chemin relatif interne seulement (pas de redirection ouverte)."""
    if isinstance(valeur, str) and re.fullmatch(r"/[A-Za-z0-9/_\-.#?=&]*", valeur) and not valeur.startswith("//"):
        return valeur
    return defaut


def texte_visible(html: str) -> str:
    """Texte affiché d'une page (balises, styles, scripts et attributs retirés) : contrôle des garde-fous."""
    t = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()
