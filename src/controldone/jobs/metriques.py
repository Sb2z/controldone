"""Compteurs simples du worker (pour le futur point ``/metrics``)."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

__all__ = ["METRIQUES", "Metriques", "metriques", "texte_prometheus"]


class Metriques:
    def __init__(self) -> None:
        self._verrou = threading.Lock()
        self.compteurs: dict[str, int] = defaultdict(int)
        self.par_kind: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.durees: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0, "total_s": 0.0, "max_s": 0.0})

    def reinitialiser(self) -> None:
        with self._verrou:
            self.compteurs.clear()
            self.par_kind.clear()
            self.durees.clear()

    def incrementer(self, nom: str, kind: str | None = None, n: int = 1) -> None:
        with self._verrou:
            self.compteurs[nom] += n
            if kind:
                self.par_kind[nom][kind] += n

    def duree(self, kind: str, secondes: float) -> None:
        with self._verrou:
            d = self.durees[kind]
            d["n"] += 1
            d["total_s"] += secondes
            d["max_s"] = max(d["max_s"], secondes)

    def instantane(self) -> dict[str, Any]:
        with self._verrou:
            return {
                "compteurs": dict(self.compteurs),
                "par_kind": {k: dict(v) for k, v in self.par_kind.items()},
                "durees": {k: dict(v) for k, v in self.durees.items()},
            }


METRIQUES = Metriques()


def metriques() -> dict[str, Any]:
    """Instantané : ``jobs_ok``, ``jobs_echec`` (réessai prévu), ``jobs_mort`` (+ par kind), durées."""
    return METRIQUES.instantane()


def texte_prometheus() -> str:
    m = metriques()
    lignes = [f"controldone_{nom}_total {v}" for nom, v in sorted(m["compteurs"].items())]
    for nom, kinds in sorted(m["par_kind"].items()):
        lignes += [f'controldone_{nom}_par_kind_total{{kind="{k}"}} {v}' for k, v in sorted(kinds.items())]
    for kind, d in sorted(m["durees"].items()):
        lignes.append(f'controldone_job_duree_secondes_sum{{kind="{kind}"}} {d["total_s"]:.3f}')
        lignes.append(f'controldone_job_duree_secondes_count{{kind="{kind}"}} {int(d["n"])}')
        lignes.append(f'controldone_job_duree_secondes_max{{kind="{kind}"}} {d["max_s"]:.3f}')
    return "\n".join(lignes) + "\n"
