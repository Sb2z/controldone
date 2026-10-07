"""Import CSV au format de ``commercial/prospects.csv`` (UTF-8, séparateur « ; » ou « , ») : analyse sans écrire.

Colonnes reconnues : ``raison_sociale`` (obligatoire), ``siren``, ``naf``, ``effectif_tranche``, ``ville``,
``site_web``, ``preuve_import``, ``contact_publie``, ``source_contact``, ``raison_ciblage``, ``canal``,
``exclusion_verifiee``, ``date_collecte``, et en plus ``pays``, ``departement``, ``groupe``, ``source_url``.

Chaque ligne reçoit un statut : ``nouveau`` (importable), ``doublon`` (même SIREN ou même nom normalisé, dans la
base ou plus haut dans le fichier), ``exclu`` (liste d'exclusion, ou colonne ``exclusion_verifiee`` qui commence par
« NON »), ``invalide`` (raison sociale absente, SIREN mal formé, aucune source). Une adresse sans page source est
ignorée (avertissement) : seules les adresses publiées, avec leur source, sont gardées.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from controldone.prospection.config import ConfigProspection
from controldone.prospection.contacts import (
    extraire_adresses,
    extraire_urls,
    nature_adresse,
    url_valide,
)
from controldone.prospection.exclusion import chercher_exclusion, normaliser_nom, textes_a_verifier
from controldone.prospection.statuts import LIBELLES_TRANCHE, tranche_depuis_libelle

__all__ = ["LIGNES_MAX", "LigneImport", "analyser_csv", "siren_valide"]

LIGNES_MAX = 2000
TAILLE_MAX = 512 * 1024
_NAF = re.compile(r"^\d{2}\.\d{2}[A-Z]$")
_DEP = re.compile(r"\((\d{2,3}|2[AB])\)")


@dataclass
class ContactImporte:
    genre: str  # courriel | formulaire
    adresse: str | None
    url_formulaire: str | None
    nature: str
    source_url: str


@dataclass
class LigneImport:
    numero: int
    statut: str  # nouveau | doublon | exclu | invalide
    motif: str | None = None  # code (libellé : web)
    raison_sociale: str = ""
    champs: dict[str, Any] = field(default_factory=dict)
    contacts: list[ContactImporte] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    doublon_de: str | None = None
    groupe_exclu: str | None = None


def siren_valide(siren: str) -> bool:
    """9 chiffres et clé de Luhn (numéro SIREN de l'INSEE)."""
    if not (len(siren) == 9 and siren.isascii() and siren.isdigit()):
        return False
    total = 0
    for i, ch in enumerate(reversed(siren)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _texte(ligne: dict[str, str], cle: str, n: int = 2000) -> str:
    return " ".join((ligne.get(cle) or "").split())[:n]


def _date(v: str, defaut: date) -> date:
    try:
        return date.fromisoformat(v.strip()[:10])
    except ValueError:
        return defaut


def _lire(contenu: bytes) -> list[dict[str, str]]:
    texte = contenu.decode("utf-8-sig")
    premiere = texte.split("\n", 1)[0]
    sep = ";" if premiere.count(";") >= premiere.count(",") else ","
    lecteur = csv.DictReader(io.StringIO(texte), delimiter=sep)
    if not lecteur.fieldnames or "raison_sociale" not in [c.strip() for c in lecteur.fieldnames]:
        raise ValueError("colonnes")
    lignes = []
    for i, brut in enumerate(lecteur):
        if i >= LIGNES_MAX:
            raise ValueError("lignes")
        lignes.append({(k or "").strip(): (v or "") for k, v in brut.items() if isinstance(v, str)})
    return lignes


def analyser_csv(
    contenu: bytes,
    config: ConfigProspection,
    *,
    existant: Callable[[str | None, str], str | None],
    aujourdhui: date,
) -> list[LigneImport]:
    """Analyse (aucune écriture). ``existant(siren, nom_normalise)`` : identifiant d'un prospect déjà en base.
    ``ValueError(code)`` : fichier refusé — ``encodage``, ``illisible``, ``colonnes`` (raison_sociale absente),
    ``lignes`` (plus de ``LIGNES_MAX``), ``taille`` (plus de ``TAILLE_MAX`` octets)."""
    if len(contenu) > TAILLE_MAX:
        raise ValueError("taille")
    try:
        lignes = _lire(contenu)
    except UnicodeDecodeError:
        raise ValueError("encodage") from None
    except csv.Error:
        raise ValueError("illisible") from None
    sortie: list[LigneImport] = []
    vus_siren: dict[str, int] = {}
    vus_nom: dict[str, int] = {}
    for n, ligne in enumerate(lignes, start=2):
        rs = _texte(ligne, "raison_sociale", 300)
        r = LigneImport(numero=n, statut="nouveau", raison_sociale=rs)
        sortie.append(r)
        if not rs:
            r.statut, r.motif = "invalide", "raison_sociale"
            continue
        siren_brut = re.sub(r"\s", "", ligne.get("siren") or "")
        siren = siren_brut if siren_brut.isdigit() else None
        if siren is not None and not siren_valide(siren):
            r.statut, r.motif = "invalide", "siren"
            continue
        if siren_brut and siren is None:
            r.avertissements.append("siren_a_verifier")
        naf = _texte(ligne, "naf", 10).upper() or None
        if naf and not _NAF.match(naf):
            r.avertissements.append("naf_illisible")
            naf = None
        tranche = tranche_depuis_libelle(ligne.get("effectif_tranche"))
        ville_brute = _texte(ligne, "ville", 200)
        dep = _texte(ligne, "departement", 3) or None
        if dep is None and (m := _DEP.search(ville_brute)):
            dep = m.group(1)
        ville = _DEP.split(ville_brute)[0].strip(" ;,") or None if ville_brute else None
        site = _texte(ligne, "site_web", 500) or None
        if site and not url_valide(site):
            r.avertissements.append("site_illisible")
            site = None
        preuve = (ligne.get("preuve_import") or "").strip()[:2000] or None
        urls_preuve = extraire_urls(preuve)
        sources_contact = extraire_urls(ligne.get("source_contact"))
        source_url = (
            _texte(ligne, "source_url", 1000)
            or (urls_preuve[0] if urls_preuve else "")
            or (site or "")
            or (f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}" if siren else "")
        )
        if not url_valide(source_url):
            r.statut, r.motif = "invalide", "source"
            continue
        # contacts publiés : adresses avec une page source ; sinon formulaire (URL de la colonne contact)
        contact_brut = ligne.get("contact_publie") or ""
        adresses = extraire_adresses(contact_brut)
        if adresses and not sources_contact:
            r.avertissements.append("adresse_sans_source")
        for a in adresses if sources_contact else []:
            r.contacts.append(ContactImporte("courriel", a, None, nature_adresse(a), sources_contact[0]))
        if not adresses:
            formulaires = extraire_urls(contact_brut) or (
                sources_contact if "formulaire" in contact_brut.lower() else []
            )
            if formulaires:
                r.contacts.append(
                    ContactImporte(
                        "formulaire", None, formulaires[0], "formulaire", (sources_contact or formulaires)[0]
                    )
                )
        pays = (_texte(ligne, "pays", 2) or "FR").upper()
        groupe = _texte(ligne, "groupe", 300) or None
        r.champs = {
            "raison_sociale": rs,
            "siren": siren,
            "naf": naf,
            "tranche_effectif": tranche,
            "effectif_libelle": _texte(ligne, "effectif_tranche", 200) or LIBELLES_TRANCHE.get(tranche or ""),
            "pays": pays if re.fullmatch(r"[A-Z]{2}", pays) else "FR",
            "departement": dep,
            "ville": ville,
            "site_web": site,
            "groupe": groupe,
            "preuve_import": preuve,
            "preuve_url": urls_preuve[0] if urls_preuve else None,
            "raison_ciblage": (ligne.get("raison_ciblage") or "").strip()[:2000] or None,
            "source_url": source_url,
            "collecte_le": _date(ligne.get("date_collecte") or "", aujourdhui),
        }
        verif = _texte(ligne, "exclusion_verifiee", 500).upper()
        exclusion = chercher_exclusion(
            textes_a_verifier(
                raison_sociale=rs, groupe=groupe, site_web=site, adresses=[c.adresse for c in r.contacts]
            ),
            config,
        )
        if exclusion is not None:
            r.statut, r.motif, r.groupe_exclu = "exclu", "liste_exclusion", exclusion.groupe
            continue
        if verif.startswith("NON"):
            r.statut, r.motif = "exclu", "verification_non"
            continue
        if pays in config.pays_bloques:
            r.statut, r.motif = "invalide", "pays_bloque"
            continue
        nom = normaliser_nom(rs)
        deja = existant(siren, nom)
        if deja:
            r.statut, r.motif, r.doublon_de = "doublon", "base", deja
            continue
        if (siren and siren in vus_siren) or nom in vus_nom:
            r.statut, r.motif = "doublon", "fichier"
            continue
        if siren:
            vus_siren[siren] = n
        vus_nom[nom] = n
    return sortie
