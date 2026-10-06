"""Sources officielles suivies par l'agent ``veille`` et téléchargement sous liste blanche.

Sources reprises des briefs ``docs/recherche/*.md`` (2 octobre 2026), limitées aux domaines officiels de
la liste blanche ; les sources citées par les briefs hors liste blanche (site de l'autorité allemande,
presse, cabinets) ne sont pas téléchargées. Le contenu téléchargé est une **donnée** : il n'est ni
interprété ni résumé par un modèle ; seule son empreinte (texte visible normalisé) est comparée.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

__all__ = [
    "DOMAINES_AUTORISES",
    "SOURCES",
    "TAILLE_MAX_REPONSE",
    "THEMES",
    "DomaineNonAutorise",
    "Source",
    "domaine_autorise",
    "empreinte_contenu",
    "telecharger",
]

#: Taille maximale d'une page téléchargée (lue en flux ; au-delà : ``non_verifie``, motif ``trop_volumineux``).
#: Les pages officielles suivies font moins de 1 Mo (RS-19).
TAILLE_MAX_REPONSE = 10 * 1024 * 1024

DOMAINES_AUTORISES: tuple[str, ...] = (
    "eur-lex.europa.eu",
    "douane.gouv.fr",
    "taxation-customs.ec.europa.eu",
    "impots.gouv.fr",
    "economie.gouv.fr",
    "legifrance.gouv.fr",
)

THEMES = {
    "forfait_petits_envois": "Droit de douane forfaitaire par article sur les petits envois",
    "macf_cbam": "Mécanisme d'ajustement carbone aux frontières (MACF / CBAM)",
    "reforme_cdu": "Réforme du code des douanes de l'Union",
    "facturation_electronique": "Facturation électronique (plateformes agréées)",
}


@dataclass(frozen=True)
class Source:
    theme: str
    url: str
    origine: str  # brief qui la cite, ou « complément officiel »

    def en_dict(self) -> dict[str, str]:
        return asdict(self)


SOURCES: tuple[Source, ...] = (
    Source("forfait_petits_envois",
           "https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-"
           "imports-which-will-apply-until-1-july-2028-2026-06-08_en", "docs/recherche/customs.md §3"),
    Source("forfait_petits_envois", "https://eur-lex.europa.eu/eli/reg/2026/382/oj",
           "docs/recherche/customs.md §3 (règlement 2026/382, page non lue lors du brief)"),
    Source("macf_cbam", "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism_en",
           "complément officiel (le brief cite l'autorité allemande, hors liste blanche)"),
    Source("macf_cbam", "https://eur-lex.europa.eu/eli/reg/2023/956/oj", "complément officiel (règlement MACF)"),
    Source("reforme_cdu", "https://taxation-customs.ec.europa.eu/customs/eu-customs-reform_en",
           "docs/recherche/customs.md §5"),
    Source("reforme_cdu",
           "https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/"
           "eu-customs-data-model-eucdm_en", "docs/recherche/customs.md §1"),
    Source("facturation_electronique", "https://www.impots.gouv.fr/facturation-electronique-et-plateformes-agreees",
           "docs/recherche/einvoice.md"),
    Source("facturation_electronique", "https://www.douane.gouv.fr/demarche/beneficier-automatiquement-de-"
           "lautoliquidation-de-la-tva-limport", "docs/recherche/customs.md §2"),
)


class DomaineNonAutorise(PermissionError):
    pass


def domaine_autorise(url: str) -> bool:
    """HTTPS et hôte égal à un domaine de la liste blanche ou sous-domaine de celui-ci."""
    parties = urlsplit(url)
    hote = (parties.hostname or "").lower().rstrip(".")
    if parties.scheme != "https" or not hote or parties.username or parties.password:
        return False
    if parties.port not in (None, 443):
        return False
    return any(hote == d or hote.endswith("." + d) for d in DOMAINES_AUTORISES)


_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.I | re.S)
_BALISE_RE = re.compile(r"<[^>]+>")
_TITRE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def empreinte_contenu(contenu: str) -> tuple[str, int]:
    """Empreinte du texte visible (balises, scripts et espaces normalisés) et sa longueur."""
    texte = _BALISE_RE.sub(" ", _SCRIPT_RE.sub(" ", contenu))
    texte = " ".join(html.unescape(texte).split())
    return hashlib.sha256(texte.encode("utf-8")).hexdigest(), len(texte)


def _lire_borne(http: Any, url: str, taille_max: int) -> tuple[int, str | None, str | None]:
    """``(statut, location, texte)`` : corps lu **en flux** (jamais en entier en mémoire au-delà de
    ``taille_max`` octets, ``Content-Length`` annoncé ou non) ; ``texte`` vaut ``None`` au-delà, ou pour une
    réponse autre que 200."""
    with http.stream("GET", url) as rep:
        if rep.status_code != 200:
            return rep.status_code, rep.headers.get("location"), None
        annonce = rep.headers.get("content-length", "")
        if annonce.isascii() and annonce.isdigit() and int(annonce) > taille_max:
            return 200, None, None
        corps = bytearray()
        for morceau in rep.iter_bytes():
            corps += morceau
            if len(corps) > taille_max:
                return 200, None, None
        return 200, None, bytes(corps).decode(rep.charset_encoding or "utf-8", errors="replace")


def telecharger(url: str, *, client: Any = None, max_redirections: int = 3, timeout: float = 20.0,
                taille_max: int = TAILLE_MAX_REPONSE) -> dict[str, Any]:
    """Télécharge ``url`` si elle est sous liste blanche (chaque redirection est revérifiée).

    Renvoie ``{"url", "statut": "ok", "sha256", "taille", "titre"}`` ou ``{"statut": "non_verifie",
    "motif"}`` (erreur réseau, code HTTP, redirection hors liste blanche — jamais suivie, réponse au-delà de
    ``taille_max`` octets — lue en flux et abandonnée, RS-19).
    ``DomaineNonAutorise`` si l'URL demandée sort de la liste blanche.
    """
    import httpx

    if not domaine_autorise(url):
        raise DomaineNonAutorise(f"domaine hors liste blanche : {urlsplit(url).hostname}")
    propre = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=False,
                                  headers={"User-Agent": "ControlDOne-veille/1.0 (lecture seule)"})
    courante = url
    try:
        for _ in range(max_redirections + 1):
            try:
                lu = _lire_borne(http, courante, taille_max)
            except Exception as exc:
                return {"url": url, "statut": "non_verifie", "motif": type(exc).__name__}
            statut, location, corps = lu
            if statut in (301, 302, 303, 307, 308) and location:
                suivante = urljoin(courante, location)
                if not domaine_autorise(suivante):
                    return {"url": url, "statut": "non_verifie", "motif": "redirection_hors_liste_blanche"}
                courante = suivante
                continue
            if statut != 200:
                return {"url": url, "statut": "non_verifie", "motif": f"http_{statut}"}
            if corps is None:
                return {"url": url, "statut": "non_verifie", "motif": "trop_volumineux"}
            contenu = corps
            sha, taille = empreinte_contenu(contenu)
            m = _TITRE_RE.search(contenu)
            titre = " ".join(html.unescape(m.group(1)).split())[:150] if m else None
            return {"url": url, "statut": "ok", "sha256": sha, "taille": taille, "titre": titre}
        return {"url": url, "statut": "non_verifie", "motif": "trop_de_redirections"}
    finally:
        if propre:
            http.close()
