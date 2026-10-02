"""Limitation de débit en mémoire (seau à jetons), par clé (IP, compte, clé d'API)."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

__all__ = ["LimiteurDebit"]


class LimiteurDebit:
    """``capacite`` jetons, rechargés de ``par_seconde`` ; au plus ``max_cles`` clés suivies (LRU)."""

    def __init__(self, capacite: float, par_seconde: float, *, max_cles: int = 10_000,
                 horloge: Callable[[], float] = time.monotonic) -> None:
        if capacite <= 0 or par_seconde <= 0:
            raise ValueError("capacité et recharge strictement positives")
        self.capacite = float(capacite)
        self.par_seconde = float(par_seconde)
        self.max_cles = max_cles
        self.horloge = horloge
        self._seaux: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._verrou = threading.Lock()

    def autoriser(self, cle: str, cout: float = 1.0) -> bool:
        with self._verrou:
            maintenant = self.horloge()
            jetons, dernier = self._seaux.pop(cle, (self.capacite, maintenant))
            jetons = min(self.capacite, jetons + (maintenant - dernier) * self.par_seconde)
            ok = jetons >= cout
            if ok:
                jetons -= cout
            self._seaux[cle] = (jetons, maintenant)
            while len(self._seaux) > self.max_cles:
                self._seaux.popitem(last=False)
            return ok

    def attente(self, cle: str, cout: float = 1.0) -> float:
        """Secondes avant qu'une requête de ``cout`` soit autorisée (0 si tout de suite)."""
        with self._verrou:
            jetons, dernier = self._seaux.get(cle, (self.capacite, self.horloge()))
            jetons = min(self.capacite, jetons + (self.horloge() - dernier) * self.par_seconde)
            return max(0.0, (cout - jetons) / self.par_seconde)
