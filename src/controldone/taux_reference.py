"""Table locale datée des taux de référence BCE (``ref/taux_bce.csv``, SPEC §8.7).

Format CSV : ``date,devise,devise_par_eur`` (convention BCE : unités de devise pour 1 EUR).
Usage **limité** (§8.7) : déterminer le sens d'un taux imprimé sans libellé, et A7 (ordre de grandeur).
Jamais pour calculer un montant en jeu.

Le fichier livré est vide (en-tête seul) : il est alimenté par une tâche d'import hors ligne.
"""

from __future__ import annotations

import csv
from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

__all__ = ["TableTauxReference"]


class TableTauxReference:
    """Accès en lecture aux taux de référence, par devise et par date."""

    #: Écart maximal entre la date demandée et la dernière publication (week-ends, jours fériés).
    ANCIENNETE_MAX = timedelta(days=7)

    def __init__(self, taux: dict[str, dict[date, Decimal]] | None = None) -> None:
        self._taux: dict[str, list[tuple[date, Decimal]]] = {
            dev.upper(): sorted(par_date.items()) for dev, par_date in (taux or {}).items()
        }

    @classmethod
    def depuis_csv(cls, chemin: Path | str) -> TableTauxReference:
        donnees: dict[str, dict[date, Decimal]] = {}
        with open(chemin, encoding="utf-8", newline="") as f:
            for ligne in csv.DictReader(f):
                donnees.setdefault(ligne["devise"].upper(), {})[date.fromisoformat(ligne["date"])] = Decimal(
                    ligne["devise_par_eur"]
                )
        return cls(donnees)

    def devise_par_eur(self, devise: str, le: date) -> Decimal | None:
        """Taux publié le jour ``le`` ou au plus 7 jours avant ; ``None`` sinon. EUR -> 1."""
        devise = devise.upper()
        if devise == "EUR":
            return Decimal(1)
        serie = self._taux.get(devise)
        if not serie:
            return None
        i = bisect_right(serie, (le, Decimal("Infinity"))) - 1
        if i < 0:
            return None
        d, t = serie[i]
        return t if le - d <= self.ANCIENNETE_MAX else None

    def eur_par_devise(self, devise: str, le: date) -> Decimal | None:
        t = self.devise_par_eur(devise, le)
        return None if t is None or t == 0 else Decimal(1) / t
