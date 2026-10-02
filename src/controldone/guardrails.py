"""Garde-fous juridiques (SPEC §3).

- ``PHRASE_RENVOI`` (§3.3) et ``AVERTISSEMENT`` (§3.4) : chaînes constantes **exactes** ;
- ``check_text(texte)`` : liste des formulations interdites trouvées (§3.2), insensible à la casse,
  aux accents, au pluriel et au féminin ;
- ``assert_clean(texte)`` : lève ``FormulationInterdite`` si le texte en contient une.

La liste vient de ``config/formulations_interdites.yaml`` (versionnée, enrichissable sans code).

Conséquence assumée de l'insensibilité aux accents (D-014) : « droit dû » bloque aussi « droit du »
(sans accent) ; les gabarits évitent donc la tournure « droit du … ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from controldone.normalize.text import sans_accents

__all__ = [
    "AVERTISSEMENT",
    "MOTIF_FORMULATION_INTERDITE",
    "PHRASE_RENVOI",
    "FormulationInterdite",
    "Violation",
    "assert_clean",
    "charger_formulations",
    "check_text",
    "contient_phrase_renvoi",
]

#: §3.3 — à reproduire **exactement**.
PHRASE_RENVOI = (
    "Ce point relève d'une appréciation réglementaire : il est à faire vérifier par un représentant "
    "en douane enregistré ou un avocat. ControlDOne ne se prononce pas sur ce point."
)

#: §3.4 — à reproduire **exactement**.
AVERTISSEMENT = (
    "Ce document est un contrôle technique de cohérence entre documents et de calcul. Il ne constitue ni "
    "un conseil juridique, fiscal ou douanier, ni un avis sur la conformité des opérations. Les montants "
    "indiqués sont des écarts constatés entre documents ; ils ne préjugent pas des sommes légalement dues."
)

MOTIF_FORMULATION_INTERDITE = "formulation_interdite"


@dataclass(frozen=True, slots=True)
class Violation:
    expression: str  # expression interdite de la liste
    categorie: str
    extrait: str  # passage du texte qui a déclenché
    debut: int
    fin: int
    motif: str = MOTIF_FORMULATION_INTERDITE


class FormulationInterdite(ValueError):
    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        super().__init__(
            "formulation interdite : " + ", ".join(f"« {v.expression} » ({v.extrait!r})" for v in violations)
        )


def _normaliser(texte: str) -> str:
    """Minuscules, sans accents, apostrophes droites, tirets -> espace. Longueur conservée (index)."""
    sortie = []
    for c in texte:
        s = sans_accents(c).casefold()
        if c in "’‘`":
            s = "'"
        elif c in "-‐‑‒–—" or c in "    ":
            s = " "
        # garder une correspondance 1 caractère -> 1 caractère pour retrouver l'extrait
        sortie.append(s[:1] if s else " ")
    return "".join(sortie)


def _variantes(mot: str) -> str:
    """Motif d'un mot avec ses formes plurielles et féminines."""
    m = re.escape(mot)
    if mot.endswith("eux"):
        return f"{re.escape(mot[:-1])}(?:x|se|ses)"
    if mot.endswith("al"):
        return f"{m}(?:e|es|s)?|{re.escape(mot[:-2])}aux"
    if mot.endswith("er"):
        return f"{m}(?:s|e|es)?|{re.escape(mot[:-2])}ere(?:s)?"
    if mot.endswith("if"):
        return f"{m}s?|{re.escape(mot[:-2])}ive(?:s)?"
    if mot.endswith("e"):
        # « mandaté » -> mandate, mandatee(s) ; « taxe » -> taxes
        return f"{m}(?:e|s|es)?"
    if mot.endswith(("s", "x")):
        return f"{m}(?:e|es)?"
    return f"{m}(?:s|e|es|x)?"


_MOTS_INVARIABLES = frozenset({"le", "la", "les", "de", "du", "des", "a", "en", "au", "aux", "par", "est",
                               "nous", "vous", "il", "faut", "une", "un", "notre", "the"})


def _compiler(expression: str) -> re.Pattern[str]:
    norm = _normaliser(expression).strip()
    mots = norm.split()
    parties = []
    for i, mot in enumerate(mots):
        # les mots grammaticaux restent invariables, sauf « du » final (« droit dû » -> du/dus/due/dues)
        if mot in _MOTS_INVARIABLES and not (mot == "du" and i == len(mots) - 1):
            parties.append(re.escape(mot))
        else:
            parties.append(f"(?:{_variantes(mot)})")
    # « sous-évaluation » : tiret normalisé en espace, espace optionnelle (« sousevaluation »)
    motif = r"\s*".join(parties) if "-" in expression else r"\s+".join(parties)
    return re.compile(rf"(?<![a-z0-9]){motif}(?![a-z0-9])")


@dataclass(frozen=True, slots=True)
class _Regle:
    expression: str
    categorie: str
    motif: re.Pattern[str]


@lru_cache(maxsize=8)
def _regles(chemin: str | None) -> tuple[_Regle, ...]:
    data = charger_formulations(Path(chemin) if chemin else None)
    regles = []
    for cat in data["categories"]:
        for expr in cat["expressions"]:
            regles.append(_Regle(expr, cat["id"], _compiler(expr)))
    return tuple(regles)


def _chemin_defaut() -> Path:
    from controldone.config import get_settings

    return Path(get_settings().config_dir) / "formulations_interdites.yaml"


def charger_formulations(chemin: Path | None = None) -> dict:
    """Charge le YAML des formulations interdites (``config/formulations_interdites.yaml``)."""
    p = chemin or _chemin_defaut()
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "categories" not in data:
        raise ValueError(f"fichier de formulations invalide : {p}")
    return data


def check_text(texte: str | None, *, chemin: Path | None = None) -> list[Violation]:
    """Formulations interdites trouvées dans ``texte`` (liste vide si le texte est propre)."""
    if not texte:
        return []
    norm = _normaliser(texte)
    trouvees: list[Violation] = []
    for regle in _regles(str(chemin) if chemin else None):
        for m in regle.motif.finditer(norm):
            trouvees.append(
                Violation(
                    expression=regle.expression,
                    categorie=regle.categorie,
                    extrait=texte[m.start(): m.end()],
                    debut=m.start(),
                    fin=m.end(),
                )
            )
    trouvees.sort(key=lambda v: (v.debut, v.expression))
    return trouvees


def assert_clean(texte: str | None, *, chemin: Path | None = None) -> None:
    """Lève ``FormulationInterdite`` si ``texte`` contient une formulation interdite."""
    violations = check_text(texte, chemin=chemin)
    if violations:
        raise FormulationInterdite(violations)


def contient_phrase_renvoi(texte: str | None) -> bool:
    """Vrai si la phrase de renvoi figure **exactement** dans le texte (§3.5)."""
    return bool(texte) and PHRASE_RENVOI in texte
