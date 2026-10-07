"""Score d'un prospect (0 à 100) : calcul **déterministe** et expliqué, sans modèle de langage (D-5004).

Six critères, chacun avec ses points et une explication (« pourquoi ce score ») :

======================  ======  =================================================================================
Critère                 Max     Règle
======================  ======  =================================================================================
Activité (NAF)          25      commerce de gros typique des importateurs (liste de la configuration) 25 ; autre
                                commerce de gros (46) 15 ; commerce de détail (47) ou conditionnement (82.92Z) 8
Taille                  20      50-199 salariés 20 ; 10-49 15 ; 200-249 12 ; 250 et plus 5 (service douane
                                interne probable) ; moins de 10 ou inconnue 0
Preuve d'import hors UE 25      citation **avec** l'URL de la page de l'entreprise 25 ; citation sans URL 8 ; rien 0
Dépendance transitaire  10      aucun service douane apparent 10 ; inconnu 0 ; service douane interne -10
Contact                 15      adresse générique publiée (avec source) 15 ; adresse nominative avec source 10 ;
                                formulaire seul 5 ; aucun 0
Région                  5       département d'une plate-forme logistique ou portuaire (configuration) 5
======================  ======  =================================================================================

Les libellés sont des gabarits français à paramètres (traduits à l'affichage, ``web/i18n_prospection_en.py``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from controldone.prospection.config import ConfigProspection
from controldone.prospection.contacts import url_valide

__all__ = ["LIBELLES_SCORE", "FaitsScore", "LigneScore", "Score", "calculer_score"]

LIBELLES_SCORE = {
    "naf_importateur": "Activité {naf} : commerce de gros typique des importateurs",
    "naf_gros": "Activité {naf} : commerce de gros",
    "naf_detail": "Activité {naf} : commerce de détail ou conditionnement",
    "naf_autre": "Activité {naf} : hors cible principale",
    "naf_inconnu": "Activité inconnue",
    "taille_coeur": "Taille {tranche} salariés : cœur de cible",
    "taille_pme": "Taille {tranche} salariés : PME",
    "taille_grande_pme": "Taille {tranche} salariés",
    "taille_grande": "Taille {tranche} salariés : service douane interne probable",
    "taille_petite": "Taille {tranche} salariés : trop petite",
    "taille_inconnue": "Taille inconnue",
    "preuve_verifiee": "Import hors UE écrit par l'entreprise, page source enregistrée",
    "preuve_sans_source": "Import hors UE cité sans page source : à vérifier",
    "preuve_absente": "Aucune preuve d'import hors UE enregistrée",
    "douane_absente": "Aucun service douane interne apparent",
    "douane_interne": "Service douane interne",
    "douane_inconnue": "Service douane : inconnu",
    "contact_generique": "Adresse générique publiée par l'entreprise",
    "contact_nominatif": "Adresse nominative avec source",
    "contact_formulaire": "Formulaire de contact seulement",
    "contact_absent": "Aucun contact enregistré",
    "region_prioritaire": "Département {departement} : plate-forme logistique ou portuaire",
    "region_autre": "Département hors zones prioritaires",
    "region_inconnue": "Département inconnu",
}


@dataclass(frozen=True)
class FaitsScore:
    naf: str | None = None
    tranche_effectif: str | None = None
    preuve_import: str | None = None
    preuve_url: str | None = None
    sans_service_douane: str = "inconnu"
    natures_contacts: tuple[str, ...] = ()
    departement: str | None = None


@dataclass(frozen=True)
class LigneScore:
    critere: str
    code: str
    points: int
    maximum: int
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def libelle(self) -> str:
        return LIBELLES_SCORE[self.code]

    def en_dict(self) -> dict[str, Any]:
        return {
            "critere": self.critere,
            "code": self.code,
            "points": self.points,
            "maximum": self.maximum,
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class Score:
    total: int
    lignes: tuple[LigneScore, ...]

    def detail(self) -> list[dict[str, Any]]:
        return [x.en_dict() for x in self.lignes]


def _naf(naf: str | None, config: ConfigProspection) -> LigneScore:
    n = (naf or "").strip().upper()
    if not n:
        return LigneScore("naf", "naf_inconnu", 0, 25)
    if n in config.naf_importateurs:
        return LigneScore("naf", "naf_importateur", 25, 25, {"naf": n})
    if n.startswith("46"):
        return LigneScore("naf", "naf_gros", 15, 25, {"naf": n})
    if n.startswith("47") or n == "82.92Z":
        return LigneScore("naf", "naf_detail", 8, 25, {"naf": n})
    return LigneScore("naf", "naf_autre", 0, 25, {"naf": n})


def _taille(code: str | None) -> LigneScore:
    from controldone.prospection.statuts import LIBELLES_TRANCHE

    lib = LIBELLES_TRANCHE.get(code or "")
    if lib is None:
        return LigneScore("taille", "taille_inconnue", 0, 20)
    p = {"tranche": lib}
    if code in ("21", "22"):
        return LigneScore("taille", "taille_coeur", 20, 20, p)
    if code in ("11", "12"):
        return LigneScore("taille", "taille_pme", 15, 20, p)
    if code == "31":
        return LigneScore("taille", "taille_grande_pme", 12, 20, p)
    if code in ("00", "01", "02", "03"):
        return LigneScore("taille", "taille_petite", 0, 20, p)
    return LigneScore("taille", "taille_grande", 5, 20, p)


def _preuve(texte: str | None, url: str | None) -> LigneScore:
    if texte and texte.strip() and url_valide(url):
        return LigneScore("preuve", "preuve_verifiee", 25, 25)
    if texte and texte.strip():
        return LigneScore("preuve", "preuve_sans_source", 8, 25)
    return LigneScore("preuve", "preuve_absente", 0, 25)


def _douane(signal: str) -> LigneScore:
    if signal == "oui":
        return LigneScore("douane", "douane_absente", 10, 10)
    if signal == "non":
        return LigneScore("douane", "douane_interne", -10, 10)
    return LigneScore("douane", "douane_inconnue", 0, 10)


def _contact(natures: Iterable[str]) -> LigneScore:
    n = set(natures)
    if "generique" in n:
        return LigneScore("contact", "contact_generique", 15, 15)
    if "nominative" in n:
        return LigneScore("contact", "contact_nominatif", 10, 15)
    if "formulaire" in n:
        return LigneScore("contact", "contact_formulaire", 5, 15)
    return LigneScore("contact", "contact_absent", 0, 15)


def _region(dep: str | None, config: ConfigProspection) -> LigneScore:
    d = (dep or "").strip()
    if not d:
        return LigneScore("region", "region_inconnue", 0, 5)
    if d in config.departements_prioritaires:
        return LigneScore("region", "region_prioritaire", 5, 5, {"departement": d})
    return LigneScore("region", "region_autre", 0, 5)


def calculer_score(f: FaitsScore, config: ConfigProspection) -> Score:
    lignes = (
        _naf(f.naf, config),
        _taille(f.tranche_effectif),
        _preuve(f.preuve_import, f.preuve_url),
        _douane(f.sans_service_douane),
        _contact(f.natures_contacts),
        _region(f.departement, config),
    )
    return Score(max(0, min(100, sum(x.points for x in lignes))), lignes)
