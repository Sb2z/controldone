"""Recherche de candidats dans l'API publique « Recherche d'entreprises » (DINUM, données SIRENE / RNE, sans clé).

Lancée **à la main** par le fondateur ; les résultats sont des candidats affichés, jamais ajoutés d'office.
Interface ``SourceEntreprises`` (un double en mémoire sert aux tests : aucun réseau dans les tests). Client réel :
``ClientRechercheEntreprises`` — appels séquentiels, pause entre deux appels (la documentation annonce 7 requêtes
par seconde et par adresse), nouvel essai sur 429/503 en respectant ``Retry-After`` (borné), 3 essais au plus ;
aucune redirection vers un autre hôte ; réponse bornée à 2 Mo.
Documentation : https://recherche-entreprises.api.gouv.fr/docs/
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "API_RECHERCHE",
    "CandidatEntreprise",
    "ClientRechercheEntreprises",
    "CriteresRecherche",
    "RechercheIndisponible",
    "ResultatRecherche",
    "SourceEntreprises",
    "url_annuaire",
]

API_RECHERCHE = "https://recherche-entreprises.api.gouv.fr/search"
USER_AGENT = "ControlDOne-prospection/1.0 (recherche manuelle du fondateur, faible volume)"
TAILLE_MAX = 2 * 1024 * 1024


class RechercheIndisponible(RuntimeError):
    """API injoignable, refus répétés (429/503) ou réponse illisible."""


def url_annuaire(siren: str) -> str:
    return f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"


@dataclass(frozen=True)
class CriteresRecherche:
    mots: str = ""
    naf: tuple[str, ...] = ()
    tranches: tuple[str, ...] = ()
    departement: str = ""
    region: str = ""
    page: int = 1

    def params(self) -> dict[str, str]:
        p = {"etat_administratif": "A", "per_page": "25", "page": str(max(1, min(self.page, 20)))}
        if self.mots:
            p["q"] = self.mots
        if self.naf:
            p["activite_principale"] = ",".join(self.naf)
        if self.tranches:
            p["tranche_effectif_salarie"] = ",".join(self.tranches)
        if self.departement:
            p["departement"] = self.departement
        if self.region:
            p["region"] = self.region
        return p


@dataclass(frozen=True)
class CandidatEntreprise:
    siren: str
    raison_sociale: str
    naf: str | None
    tranche_effectif: str | None
    annee_effectif: str | None
    ville: str | None
    departement: str | None
    enseignes: tuple[str, ...] = ()
    dirigeants_personnes_morales: tuple[str, ...] = ()

    @classmethod
    def depuis_api(cls, r: dict[str, Any]) -> CandidatEntreprise | None:
        siren = str(r.get("siren") or "")
        if not (len(siren) == 9 and siren.isdigit()):
            return None
        siege = r.get("siege") or {}
        dirigeants = tuple(
            str(d.get("denomination") or "")
            for d in r.get("dirigeants") or []
            if isinstance(d, dict) and d.get("type_dirigeant") == "personne morale" and d.get("denomination")
        )
        return cls(
            siren=siren,
            raison_sociale=str(r.get("nom_complet") or r.get("nom_raison_sociale") or siren)[:300],
            naf=(str(r.get("activite_principale")) or None) if r.get("activite_principale") else None,
            tranche_effectif=str(r.get("tranche_effectif_salarie"))
            if r.get("tranche_effectif_salarie")
            else None,
            annee_effectif=str(r.get("annee_tranche_effectif_salarie") or "") or None,
            ville=str(siege.get("libelle_commune") or "")[:200] or None,
            departement=str(siege.get("departement") or "")[:3] or None,
            enseignes=tuple(str(e) for e in (siege.get("liste_enseignes") or []) if e),
            dirigeants_personnes_morales=dirigeants,
        )


@dataclass
class ResultatRecherche:
    candidats: list[CandidatEntreprise] = field(default_factory=list)
    total: int = 0
    pages: int = 0
    url: str = ""


class SourceEntreprises(Protocol):
    def rechercher(self, criteres: CriteresRecherche) -> ResultatRecherche: ...


Transport = Callable[[str, float], tuple[int, dict[str, str], bytes]]


def _transport_urllib(url: str, delai: float) -> tuple[int, dict[str, str], bytes]:
    class _SansRedirection(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a: Any, **k: Any) -> None:  # aucune redirection suivie
            return None

    ouvreur = urllib.request.build_opener(_SansRedirection)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with ouvreur.open(req, timeout=delai) as rep:
            return rep.status, dict(rep.headers.items()), rep.read(TAILLE_MAX + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, b""


class ClientRechercheEntreprises:
    """Client de l'API (voir le module). ``transport`` et ``dormir`` sont remplaçables (tests)."""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        dormir: Callable[[float], None] = time.sleep,
        pause_s: float = 0.25,
        essais: int = 3,
        attente_max_s: float = 10.0,
        delai_s: float = 15.0,
    ) -> None:
        self.transport = transport or _transport_urllib
        self.dormir = dormir
        self.pause_s = pause_s
        self.essais = essais
        self.attente_max_s = attente_max_s
        self.delai_s = delai_s
        self._dernier: float | None = None

    def _appeler(self, url: str) -> dict[str, Any]:
        for essai in range(1, self.essais + 1):
            if self._dernier is not None:
                reste = self.pause_s - (time.monotonic() - self._dernier)
                if reste > 0:
                    self.dormir(reste)
            try:
                code, entetes, corps = self.transport(url, self.delai_s)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise RechercheIndisponible(f"API injoignable ({type(exc).__name__})") from None
            finally:
                self._dernier = time.monotonic()
            if code in (429, 503) and essai < self.essais:
                try:
                    attente = float({k.lower(): v for k, v in entetes.items()}.get("retry-after") or 2.0)
                except ValueError:
                    attente = 2.0
                self.dormir(min(max(attente, self.pause_s), self.attente_max_s) * essai)
                continue
            if code != 200:
                raise RechercheIndisponible(f"réponse {code}")
            if len(corps) > TAILLE_MAX:
                raise RechercheIndisponible("réponse trop volumineuse")
            try:
                donnees = json.loads(corps)
            except ValueError:
                raise RechercheIndisponible("réponse illisible") from None
            if not isinstance(donnees, dict):
                raise RechercheIndisponible("réponse illisible")
            return donnees
        raise RechercheIndisponible("refus répétés de l'API (limite de débit)")

    def rechercher(self, criteres: CriteresRecherche) -> ResultatRecherche:
        url = API_RECHERCHE + "?" + urllib.parse.urlencode(criteres.params())
        donnees = self._appeler(url)
        candidats = [
            c
            for r in donnees.get("results") or []
            if isinstance(r, dict) and (c := CandidatEntreprise.depuis_api(r)) is not None
        ]
        return ResultatRecherche(
            candidats=candidats,
            total=int(donnees.get("total_results") or len(candidats)),
            pages=int(donnees.get("total_pages") or 1),
            url=url,
        )
