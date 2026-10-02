"""Démonstration de bout en bout sur un jeu **fictif** (``controldone demo``).

``executer_demo(sortie="var/demo")`` : génère le jeu sous ``demo/`` (3 dossiers, un sous-dossier chacun),
exécute le pipeline (deux passes : chaque dossier comme un lot, puis contrôles avec tous les dossiers du
client pour la famille F) et écrit le rapport (HTML, PDF, JSON, XLSX) dans ``sortie``.

Composants (``moteur``) :

- ``auto`` (défaut) : composants publiés par les équipes ingestion / extraction ; à défaut d'extracteur
  ``deterministe`` publié, l'extracteur de démonstration (``ExtracteurDemo``) ;
- ``reel`` : uniquement les composants publiés ;
- ``demo`` : uniquement les doubles de démonstration (résultat stable, indépendant des autres équipes).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from controldone.demo.doubles import DecoupeurDemo, ExtracteurDemo
from controldone.demo.generateur import generer_demo
from controldone.pipeline import (
    Composants,
    OptionsPipeline,
    autres_dossiers_de,
    composants_par_defaut,
    controler_lot,
    preparer_lot,
)
from controldone.rapport import SortiesRapport, generer_rapport
from controldone.referentiel_io import charger_grilles, charger_profil_client

__all__ = ["composants_demo", "executer_demo", "generer_demo"]

RACINE_DEMO = Path("demo")


def composants_demo(moteur: str = "auto") -> Composants:
    if moteur == "demo":
        return Composants(decoupeur=DecoupeurDemo(), extracteurs=[ExtracteurDemo()])
    reels = composants_par_defaut()
    if moteur == "reel":
        return reels
    extracteurs = list(reels.extracteurs)
    if not any(e.type == "deterministe" for e in extracteurs):
        extracteurs.append(ExtracteurDemo())
    return Composants(decoupeur=reels.decoupeur or DecoupeurDemo(), extracteurs=extracteurs,
                      normaliseur=reels.normaliseur)


def executer_demo(
    sortie: Path | str = Path("var/demo"),
    *,
    racine: Path | str = RACINE_DEMO,
    moteur: str = "auto",
    date_rapport: date | None = None,
) -> SortiesRapport:
    racine = generer_demo(racine)
    profil = charger_profil_client(racine / "clients" / "DEMO" / "profil.json")
    grilles = charger_grilles(racine / "clients" / "DEMO" / "grilles", client_id=profil.client_id)
    comp = composants_demo(moteur)
    prepares = []
    numero = 0
    for n, d in enumerate(sorted(p for p in (racine / "dossiers").iterdir() if p.is_dir())):
        opts = OptionsPipeline(seed=1000 + n, annee=2026, llm=False)
        p = preparer_lot(d / "docs", profil, grilles, options=opts, composants=comp)
        # références lisibles distinctes d'un lot à l'autre (D-2026-00001, -00002…)
        for dos in p.dossiers:
            numero += 1
            dos.reference = f"D-2026-{numero:05d}"
        prepares.append((p, opts))
    resultats = []
    for p, opts in prepares:
        autres = autres_dossiers_de([q for q, _o in prepares if q is not p])
        resultats.extend(controler_lot(p, autres_dossiers=autres, options=opts))
    return generer_rapport(resultats, profil, sortie, titre="Rapport de diagnostic", date_rapport=date_rapport)
