"""Recherche, filtres, tri et pagination des listes (D-3401).

Tout passe par des paramètres GET (pages utilisables sans JavaScript, adresses à mettre en favori). Chaque liste
déclare ses paramètres ; ``lire_requete`` les valide **strictement** :

- noms connus seulement (les autres sont ignorés, jamais réémis dans les liens) ;
- ``choix`` : valeur dans une liste fermée ; ``texte`` : 80 caractères au plus, sans caractère de contrôle ;
  ``montant`` : ``montant_saisi`` (Decimal exact) ; ``date`` : AAAA-MM-JJ ;
- ``page`` : entier de 1 à 10 000 ; ``taille`` : 25, 50 ou 100 ; ``tri`` : clé de la liste fermée.

Une valeur invalide donne ``RequeteInvalide`` (page 400 lisible), jamais une requête SQL : les filtres sont
appliqués en Python sur des lignes déjà lues dans le périmètre du client, ou passés à l'ORM comme paramètres liés.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, TypeVar
from urllib.parse import urlencode

from starlette.requests import Request

from controldone.services.plateforme import RequeteInvalide
from controldone.services.saisie import montant_saisi
from controldone.web.i18n import N_
from controldone.web.i18n import traduire as _

__all__ = [
    "Page",
    "Param",
    "Requete",
    "contient",
    "decalage",
    "lire_requete",
    "montant_dans",
    "normaliser",
    "paginer",
    "trier",
]

T = TypeVar("T")

TAILLES = (25, 50, 100)
TAILLE_DEFAUT = 25
PAGE_MAX = 10_000
TEXTE_MAX = 80
_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Param:
    """Paramètre de filtre : ``genre`` parmi ``texte``, ``choix``, ``montant``, ``date``."""

    libelle: str
    genre: str = "texte"
    choix: tuple[str, ...] = ()


@dataclass
class Requete:
    """Paramètres validés d'une liste. ``filtres`` : valeurs typées ; ``brut`` : textes réémis dans les liens."""

    filtres: dict[str, Any]
    brut: dict[str, str]
    tri: str
    tri_defaut: str
    page: int
    taille: int
    ancre: str = ""

    @property
    def actif(self) -> bool:
        """Un filtre est appliqué (lien « Réinitialiser », message de liste vide adapté)."""
        return bool(self.brut)

    def _params(self, **changes: Any) -> dict[str, str]:
        p: dict[str, str] = dict(self.brut)
        if self.tri != self.tri_defaut:
            p["tri"] = self.tri
        if self.taille != TAILLE_DEFAUT:
            p["taille"] = str(self.taille)
        if self.page != 1:
            p["page"] = str(self.page)
        for k, v in changes.items():
            p.pop(k, None)
            if (
                v is not None
                and v != ""
                and not (k == "page" and v == 1)
                and not (k == "tri" and v == self.tri_defaut)
                and not (k == "taille" and v == TAILLE_DEFAUT)
            ):
                p[k] = str(v)
        return p

    def url(self, **changes: Any) -> str:
        """Adresse relative (``?…``) de la même liste avec ``changes`` ; un changement de filtre ou de tri
        ramène à la page 1."""
        if any(k != "page" for k in changes):
            changes.setdefault("page", 1)
        q = urlencode(self._params(**changes))
        return ("?" + q if q else "?") + self.ancre

    def url_tri(self, cle: str) -> str:
        """Lien d'un en-tête de colonne : bascule croissant / décroissant."""
        return self.url(tri=("-" + cle) if self.tri == cle else cle)

    def sens(self, cle: str) -> str:
        """Valeur ``aria-sort`` de la colonne ``cle``."""
        if self.tri == cle:
            return "ascending"
        if self.tri == "-" + cle:
            return "descending"
        return "none"

    def champs_caches(self, *exclus: str) -> list[tuple[str, str]]:
        """Paramètres à conserver dans le formulaire de filtres (tri, taille), hors champs du formulaire."""
        return [(k, v) for k, v in self._params(page=1).items() if k not in exclus and k not in self.brut]


@dataclass
class Page:
    elements: list[Any]
    total: int
    page: int
    pages: int
    taille: int
    debut: int = 0
    fin: int = 0
    numeros: list[int | None] = field(default_factory=list)


def _texte(nom: str, libelle: str, v: str) -> str:
    v = v.strip()
    if len(v) > TEXTE_MAX:
        raise RequeteInvalide(_("{libelle} : {n} caractères au plus", libelle=_(libelle), n=TEXTE_MAX))
    if _CONTROLE.search(v):
        raise RequeteInvalide(_("{libelle} : caractère non admis", libelle=_(libelle)))
    return v


def lire_requete(
    request: Request, params: dict[str, Param], tris: Sequence[str], tri_defaut: str, *, ancre: str = ""
) -> Requete:
    """Valide les paramètres GET d'une liste (voir le module)."""
    qp = request.query_params
    filtres: dict[str, Any] = {}
    brut: dict[str, str] = {}
    for nom, spec in params.items():
        valeurs = qp.getlist(nom)
        if len(valeurs) > 1:
            raise RequeteInvalide(_("{libelle} : une seule valeur attendue", libelle=_(spec.libelle)))
        v = valeurs[0] if valeurs else ""
        v = _texte(nom, spec.libelle, v)
        if not v:
            continue
        if spec.genre == "choix":
            if v not in spec.choix:
                raise RequeteInvalide(_("{libelle} : valeur inconnue", libelle=_(spec.libelle)))
            filtres[nom] = v
        elif spec.genre == "montant":
            filtres[nom] = montant_saisi(v, nom=spec.libelle, zero=True)
        elif spec.genre == "date":
            try:
                d = date.fromisoformat(v)
            except ValueError:
                raise RequeteInvalide(
                    _("{libelle} : date attendue (AAAA-MM-JJ)", libelle=_(spec.libelle))
                ) from None
            if not 2000 <= d.year <= 2100:
                raise RequeteInvalide(_("{libelle} : date hors limites", libelle=_(spec.libelle)))
            filtres[nom] = d
        else:
            filtres[nom] = v
        brut[nom] = v
    tri = _texte("tri", N_("Tri"), qp.get("tri", "")) or tri_defaut
    if tri not in tris:
        raise RequeteInvalide(_("Tri : valeur inconnue"))
    page = _entier(qp.get("page", ""), N_("Page"), 1, PAGE_MAX, 1)
    taille = _entier(qp.get("taille", ""), N_("Taille de page"), 1, max(TAILLES), TAILLE_DEFAUT)
    if taille not in TAILLES:
        raise RequeteInvalide(_("Taille de page : 25, 50 ou 100"))
    return Requete(
        filtres=filtres, brut=brut, tri=tri, tri_defaut=tri_defaut, page=page, taille=taille, ancre=ancre
    )


def _entier(v: str, libelle: str, mini: int, maxi: int, defaut: int) -> int:
    v = v.strip()
    if not v:
        return defaut
    if (
        not (v.isascii() and v.isdigit()) or len(v) > 6
    ):  # « ² » est un chiffre pour isdigit, pas pour int (REV2-05)
        raise RequeteInvalide(_("{libelle} : nombre entier attendu", libelle=_(libelle)))
    n = int(v)
    if not mini <= n <= maxi:
        raise RequeteInvalide(_("{libelle} : hors limites", libelle=_(libelle)))
    return n


def normaliser(s: Any) -> str:
    """Texte comparable : minuscules, sans accents ni espaces superflus."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(t.casefold().split())


def contient(q: str | None, *champs: Any) -> bool:
    """Chaque mot de ``q`` figure dans l'un des ``champs`` (recherche simple, insensible aux accents)."""
    if not q:
        return True
    foin = " ".join(normaliser(c) for c in champs)
    return all(mot in foin for mot in normaliser(q).split())


def trier(elements: Iterable[T], tri: str, cles: dict[str, Callable[[T], Any]]) -> list[T]:
    """Tri stable selon ``tri`` (``cle`` croissant, ``-cle`` décroissant) ; les valeurs ``None`` en dernier."""
    nom = tri.lstrip("-")
    fn = cles[nom]
    desc = tri.startswith("-")
    presents = [e for e in elements if fn(e) is not None]
    absents = [e for e in elements if fn(e) is None]
    return sorted(presents, key=fn, reverse=desc) + absents


def paginer(elements: Sequence[T] | None, req: Requete, *, total: int | None = None) -> Page:
    """Découpe ``elements`` (ou, si ``total`` est donné, prend ``elements`` comme la page déjà lue en SQL).
    Une page au-delà de la dernière est ramenée à la dernière."""
    elements = list(elements or [])
    n = len(elements) if total is None else total
    pages = max(1, -(-n // req.taille))
    page = min(req.page, pages)
    if total is None:
        debut = (page - 1) * req.taille
        vue = elements[debut : debut + req.taille]
    else:
        debut = (page - 1) * req.taille
        vue = elements
    req.page = page
    return Page(
        elements=vue,
        total=n,
        page=page,
        pages=pages,
        taille=req.taille,
        debut=debut + 1 if n else 0,
        fin=debut + len(vue),
        numeros=_numeros(page, pages),
    )


def decalage(req: Requete, total: int) -> int:
    """Décalage SQL de la page demandée (ramenée à la dernière page existante)."""
    pages = max(1, -(-total // req.taille))
    return (min(req.page, pages) - 1) * req.taille


def _numeros(page: int, pages: int) -> list[int | None]:
    """Numéros affichés : premier, dernier, et deux de part et d'autre de la page courante (``None`` = …)."""
    garde = {1, pages} | set(range(max(1, page - 2), min(pages, page + 2) + 1))
    out: list[int | None] = []
    for n in sorted(garde):
        if out and n - (out[-1] or 0) > 1:
            out.append(None)
        out.append(n)
    return out


def montant_dans(m: Decimal | None, mini: Decimal | None, maxi: Decimal | None) -> bool:
    if mini is None and maxi is None:
        return True
    if m is None:
        return False
    return (mini is None or m >= mini) and (maxi is None or m <= maxi)
