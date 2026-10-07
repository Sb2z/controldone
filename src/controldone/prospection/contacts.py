"""Adresses de contact : validation, nature (générique ou nominative), empreinte pour la liste d'opposition.

Une adresse n'est **jamais** construite ni devinée par le code (aucun ``prenom.nom@``) : elle vient d'une page
publiée par l'entreprise (import, recherche) ou d'une saisie du fondateur, toujours avec l'URL de sa source. La
nature est déduite de la partie locale : une liste fermée de boîtes de service est « générique », tout le reste
est traité comme **nominatif** (prudence : une boîte inconnue est supposée désigner une personne)."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

__all__ = [
    "BOITES_GENERIQUES",
    "adresse_valide",
    "domaine",
    "empreinte",
    "extraire_adresses",
    "extraire_urls",
    "nature_adresse",
    "normaliser_adresse",
    "url_valide",
]

_ADRESSE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_DANS_TEXTE = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://[^\s;,()«»\"<>]+")

#: Boîtes de service (partie locale, sans chiffres ni séparateurs) : adresses impersonnelles d'une organisation.
BOITES_GENERIQUES = frozenset(
    """
    contact contacts info infos information informations accueil bonjour hello hola commercial commerciale
    commerciaux vente ventes sales sale service services serviceclient clients client achat achats purchasing
    import imports export exports importexport logistique logistics transport douane customs direction
    administration admin compta comptabilite accounting finance finances office secretariat support aide pro
    pros professionnel professionnels b2b com communication marketing presse press rh jobs recrutement
    commandes commande order orders devis shop boutique magasin general team equipe hq siege
    """.split()
)


def normaliser_adresse(adresse: str) -> str:
    return (adresse or "").strip().strip("<>").lower()


def adresse_valide(adresse: str) -> bool:
    a = normaliser_adresse(adresse)
    return len(a) <= 254 and bool(_ADRESSE.match(a))


def empreinte(adresse: str) -> str:
    """SHA-256 de l'adresse normalisée (liste d'opposition et lien de désinscription : aucune adresse en clair)."""
    return hashlib.sha256(normaliser_adresse(adresse).encode("utf-8")).hexdigest()


def domaine(adresse: str) -> str:
    return normaliser_adresse(adresse).rpartition("@")[2]


def nature_adresse(adresse: str) -> str:
    """``generique`` si la partie locale est une boîte de service connue, sinon ``nominative``."""
    locale = normaliser_adresse(adresse).partition("@")[0]
    simple = re.sub(r"[^a-z]", "", locale)
    return "generique" if simple in BOITES_GENERIQUES else "nominative"


def extraire_adresses(texte: str | None) -> list[str]:
    """Adresses écrites telles quelles dans un texte (colonne d'import), dans l'ordre, sans doublon."""
    vues: list[str] = []
    for m in _DANS_TEXTE.finditer(texte or ""):
        a = normaliser_adresse(m.group(0).rstrip("."))
        if adresse_valide(a) and a not in vues:
            vues.append(a)
    return vues


def extraire_urls(texte: str | None) -> list[str]:
    vues: list[str] = []
    for m in _URL.finditer(texte or ""):
        u = m.group(0).rstrip(".")
        if url_valide(u) and u not in vues:
            vues.append(u)
    return vues


def url_valide(url: str | None) -> bool:
    """URL ``http(s)://hôte/…`` sans identifiants ni espace (source d'une preuve ou d'un contact)."""
    if not url or len(url) > 1000 or any(c.isspace() for c in url):
        return False
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    return (
        u.scheme in ("http", "https")
        and bool(u.hostname)
        and "." in (u.hostname or "")
        and not (u.username or u.password)
    )
