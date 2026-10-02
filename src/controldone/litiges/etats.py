"""Machine d'état d'un dossier de demande d'avoir (« réclamation », SPEC §17).

Le statut de la réclamation résume celui de ses écarts (§17.1) et ajoute les étapes propres au dossier :
préparation, validation par le fondateur, déclaration d'envoi par le client, clôture.

```
brouillon ──> valide ──> envoyee ──> partiellement_credite ──> credite ──> clos
   │            │          │  ▲              │                   ▲
   │            │          ▼  │              ▼                   │
   │            │        conteste ───────────┴───────────────────┘
   └────────────┴──────────┴─────────────────┴──> abandonnee (motif obligatoire)
                envoyee | partiellement_credite | conteste ──> clos (motif obligatoire : le reste est abandonné)
```

Fonctions pures, testées (``tests/ops/test_litiges_etats.py``).
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from controldone.model.enums import StatutEcart

__all__ = [
    "STATUTS_ACTIFS",
    "STATUTS_TERMINAUX",
    "TRANSITIONS_RECLAMATION",
    "TransitionReclamationInterdite",
    "StatutReclamation",
    "exige_motif",
    "statut_depuis_ecarts",
    "verifier_transition",
]


class StatutReclamation(StrEnum):
    brouillon = "brouillon"  # préparé par le système, en attente du fondateur
    valide = "valide"  # validé par le fondateur, mis à disposition du client
    envoyee = "envoyee"  # le client déclare l'avoir envoyé lui-même à son transitaire
    partiellement_credite = "partiellement_credite"
    credite = "credite"
    conteste = "conteste"  # le transitaire refuse ; reste ouvert à la relance
    clos = "clos"
    abandonnee = "abandonnee"


S = StatutReclamation

TRANSITIONS_RECLAMATION: dict[StatutReclamation, frozenset[StatutReclamation]] = {
    S.brouillon: frozenset({S.valide, S.abandonnee}),
    # Un avoir peut arriver avant que le client ne déclare l'envoi (relance orale…).
    S.valide: frozenset({S.envoyee, S.partiellement_credite, S.credite, S.abandonnee}),
    S.envoyee: frozenset({S.partiellement_credite, S.credite, S.conteste, S.clos, S.abandonnee}),
    S.partiellement_credite: frozenset({S.partiellement_credite, S.credite, S.conteste, S.clos, S.abandonnee}),
    S.conteste: frozenset({S.envoyee, S.partiellement_credite, S.credite, S.clos, S.abandonnee}),
    S.credite: frozenset({S.clos}),
    S.clos: frozenset(),
    S.abandonnee: frozenset(),
}

STATUTS_TERMINAUX = frozenset({S.clos, S.abandonnee})
#: Statuts dans lesquels un litige est « en cours » chez le transitaire (relances, détection d'inactivité).
STATUTS_ACTIFS = frozenset({S.envoyee, S.partiellement_credite, S.conteste})


class TransitionReclamationInterdite(ValueError):
    pass


def exige_motif(de: StatutReclamation, vers: StatutReclamation) -> bool:
    """Abandon, et clôture d'un dossier qui n'est pas entièrement crédité : motif obligatoire."""
    return vers is S.abandonnee or (vers is S.clos and de is not S.credite)


def verifier_transition(de: StatutReclamation | str, vers: StatutReclamation | str, motif: str | None = None) -> None:
    de, vers = StatutReclamation(de), StatutReclamation(vers)
    if vers not in TRANSITIONS_RECLAMATION[de]:
        raise TransitionReclamationInterdite(f"transition interdite : {de.value} -> {vers.value}")
    if exige_motif(de, vers) and not (motif and motif.strip()):
        raise TransitionReclamationInterdite(f"{de.value} -> {vers.value} exige un motif")


def statut_depuis_ecarts(actuel: StatutReclamation | str, statuts_ecarts: Iterable[StatutEcart | str]) -> StatutReclamation:
    """Statut de la réclamation après une imputation d'avoir (§17.2) : ``credite`` si tous les écarts
    non abandonnés sont crédités, ``partiellement_credite`` si au moins un crédit est intervenu, sinon
    inchangé."""
    actuel = StatutReclamation(actuel)
    statuts = [StatutEcart(s) for s in statuts_ecarts]
    vivants = [s for s in statuts if s is not StatutEcart.abandonne]
    if not vivants:
        return actuel
    if all(s is StatutEcart.credite for s in vivants):
        return S.credite
    if any(s in (StatutEcart.credite, StatutEcart.partiellement_credite) for s in vivants):
        return S.partiellement_credite
    return actuel
