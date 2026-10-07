"""Langue de l'interface (D-3803) : français par défaut, anglais au choix.

- **Catalogue** : les textes de l'interface sont écrits en français dans les gabarits et le code
  (``_("Dossiers")``) ; ``CATALOGUE_EN`` (``web/i18n_en.py``) donne leur traduction anglaise. Paramètres nommés au
  format ``str.format`` : ``_("{n} fichier(s) reçu(s)", n=3)``. Un texte absent du catalogue reste en français
  (un test vérifie qu'aucun texte marqué n'y manque).
- **Choix de la langue** : cookie ``cd_langue`` (préférence du navigateur, posé par ``POST /preferences/langue``,
  sans donnée personnelle) ; à défaut, ``Accept-Language`` pour les pages sans session (connexion), français
  sinon.
- **Hors traduction** : le texte juridique exact (``AVERTISSEMENT``, ``PHRASE_RENVOI``) et les textes des
  constats, rapports et relevés d'écarts (soumis aux garde-fous en français, SPEC §3) restent en français ; en
  anglais, ils sont marqués ``lang="fr"`` et l'avertissement est suivi d'une traduction **de courtoisie**,
  signalée comme telle (``AVERTISSEMENT_EN``) — le texte français fait foi.

La langue courante est portée par une ``ContextVar`` (une par requête) : posée par le middleware de session, et
de nouveau par ``rendu.page`` avant le rendu.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from starlette.requests import Request

from controldone.web.i18n_en import CATALOGUE_EN, TEXTES_JS
from controldone.web.i18n_messages import traduire_message

__all__ = [
    "AVERTISSEMENT_EN",
    "COOKIE_LANGUE",
    "LANGUES",
    "N_",
    "PHRASE_RENVOI_EN",
    "activer",
    "courante",
    "langue_de",
    "negocier",
    "textes_js",
    "traduire",
    "traduire_erreur",
]

LANGUES = {"fr": "Français", "en": "English"}
DEFAUT = "fr"
COOKIE_LANGUE = "cd_langue"

#: Traductions de courtoisie (affichées sous le texte français, qui seul fait foi).
AVERTISSEMENT_EN = (
    "This document is a technical consistency check between documents and of calculations. It is neither legal, "
    "tax or customs advice, nor an opinion on whether the operations comply with regulations. The amounts shown "
    "are discrepancies observed between documents; they do not prejudge the sums legally owed."
)
PHRASE_RENVOI_EN = (
    "This point calls for a regulatory assessment: have it checked by a registered customs representative or a "
    "lawyer. ControlDOne does not give an opinion on this point."
)

_courante: ContextVar[str] = ContextVar("controldone_langue", default=DEFAUT)


def N_(texte: str) -> str:
    """Marque un texte à traduire **plus tard** (libellé de liste, titre passé à une fonction) : renvoie le texte
    tel quel ; la traduction se fait à l'affichage (``_()`` dans le gabarit ou la fonction appelée)."""
    return texte


def courante() -> str:
    return _courante.get()


def activer(langue: str) -> None:
    _courante.set(langue if langue in LANGUES else DEFAUT)


def traduire(texte: str, /, langue: str | None = None, **params: Any) -> str:
    """Traduction de ``texte`` (français) dans ``langue`` (défaut : langue courante), puis paramètres."""
    lg = langue or _courante.get()
    t = CATALOGUE_EN.get(texte, texte) if lg == "en" else texte
    return t.format(**params) if params else t


#: Paramètres d'un message qui portent eux-mêmes un message de service (motif d'un refus, garde-fous).
PARAMETRES_MESSAGES = frozenset({"motif", "motifs"})


def traduire_erreur(texte: str, /, langue: str | None = None, **params: Any) -> str:
    """Message affiché (flash, page d'erreur) : texte du catalogue de l'interface, sinon message d'un service
    (``web/i18n_messages.py``, D-4801 : texte exact ou message paramétré reconnu), sinon texte d'origine. Les
    paramètres ``motif``/``motifs`` (message d'un service) sont traduits de la même façon."""
    lg = langue or _courante.get()
    if lg == "en":
        if texte in CATALOGUE_EN:
            t = CATALOGUE_EN[texte]
        else:
            t = texte if params else (traduire_message(texte, lg) or texte)
        params = {
            k: (traduire_message(v, lg) or v) if k in PARAMETRES_MESSAGES and isinstance(v, str) else v
            for k, v in params.items()
        }
    else:
        t = texte
    return t.format(**params) if params else t


def negocier(entete: str | None) -> str:
    """Langue préférée d'un en-tête ``Accept-Language`` parmi ``LANGUES`` (français si rien ne correspond)."""
    meilleure, poids = DEFAUT, -1.0
    for i, morceau in enumerate((entete or "")[:500].split(",")[:20]):
        nom, _, reste = morceau.strip().partition(";")
        code = nom.strip().lower().split("-")[0]
        q = 1.0
        reste = reste.strip()
        if reste.startswith("q="):
            try:
                q = float(reste[2:])
            except ValueError:
                q = 0.0
        if code in LANGUES and q > 0 and q - i * 1e-6 > poids:
            meilleure, poids = code, q - i * 1e-6
    return meilleure


def langue_de(request: Request) -> str:
    """Langue d'une requête : cookie de préférence, sinon ``Accept-Language`` sans session, sinon français."""
    deja = getattr(request.state, "langue", None)
    if deja in LANGUES:
        return deja
    choix = request.cookies.get(COOKIE_LANGUE) or request.cookies.get("__Host-" + COOKIE_LANGUE)
    if choix in LANGUES:
        lg = choix
    elif getattr(request.state, "session", None) is None:
        lg = negocier(request.headers.get("accept-language"))
    else:
        lg = DEFAUT
    request.state.langue = lg
    return lg


def textes_js(langue: str) -> dict[str, str]:
    """Textes du JavaScript de l'interface (``static/app.js``), traduits : bloc JSON inerte dans la page."""
    return {k: traduire(k, langue) for k in TEXTES_JS}
