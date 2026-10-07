"""Liste d'exclusion (groupes exclus par consigne du fondateur, ``config/prospection.yaml``).

Comparaison sans casse ni accents, apostrophes et tirets neutralisés, par **mots entiers** (« eres » ne bloque pas
« fereres », « barrie » ne bloque pas « barrière ») ; un motif de plusieurs mots est aussi cherché collé (« sol de
janeiro » dans le domaine ``soldejaneiro.com``). Un nom de domaine (``www.marque-groupe.fr``,
``contact@marque.com``) est découpé en mots. Le script ``commercial/scripts/prospection_sirene.py`` cherchait les
motifs longs comme sous-chaînes : trop large (« barrie » bloquait toute « barrière »), D-5003. Le motif
trouvé n'est jamais affiché dans l'interface : seul le fait « liste d'exclusion » l'est."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from controldone.normalize.text import sans_accents
from controldone.prospection.config import ConfigProspection

__all__ = ["Exclusion", "chercher_exclusion", "normaliser_nom", "textes_a_verifier"]

_NON_ALNUM = re.compile(r"[^a-z0-9&]+")
#: Formes juridiques retirées du nom normalisé (dédoublonnage) ; jamais de la recherche d'exclusion.
_FORMES = re.compile(
    r"\b(sas|sasu|sarl|eurl|sa|sca|snc|sci|ei|eirl|scop|gie|selarl|ltd|gmbh|ag|sagl|srl|bv|nv|inc|llc)\b"
)


@dataclass(frozen=True)
class Exclusion:
    groupe: str
    motif: str


def _mots(texte: str) -> str:
    t = sans_accents(texte or "").casefold().replace("'", " ").replace("’", " ")
    return " ".join(_NON_ALNUM.sub(" ", t).split())


def normaliser_nom(raison_sociale: str) -> str:
    """Nom comparable pour le dédoublonnage : sans accents, ponctuation ni forme juridique."""
    return " ".join(_FORMES.sub(" ", _mots(raison_sociale)).split())


def chercher_exclusion(textes: Iterable[str | None], config: ConfigProspection) -> Exclusion | None:
    """Premier groupe exclu auquel correspond l'un des ``textes`` (noms, enseignes, domaines), sinon ``None``."""
    candidats = [f" {_mots(t)} " for t in textes if t and t.strip()]
    if not candidats:
        return None
    for g in config.exclusions:
        for motif in g.motifs:
            m = _mots(motif)
            if not m:
                continue
            colle = m.replace(" ", "")
            for c in candidats:
                if f" {m} " in c or f" {colle} " in c:
                    return Exclusion(g.groupe, motif)
    return None


def textes_a_verifier(
    *,
    raison_sociale: str | None = None,
    enseignes: Iterable[str] = (),
    groupe: str | None = None,
    site_web: str | None = None,
    adresses: Iterable[str | None] = (),
    dirigeants: Iterable[str] = (),
) -> list[str]:
    """Textes comparés à la liste : dénomination, enseignes, groupe déclaré, dirigeants personnes morales,
    domaine du site et des adresses (jamais les textes libres : une note qui cite la consigne ne bloque rien)."""
    sortie = [raison_sociale or "", groupe or "", *enseignes, *dirigeants]
    for a in [site_web, *adresses]:
        if not a:
            continue
        hote = a.split("@", 1)[1] if "@" in a else re.sub(r"^[a-z]+://", "", a.strip().lower()).split("/")[0]
        sortie.append(hote.replace(".", " ").replace("-", " "))
    return [x for x in sortie if x]
