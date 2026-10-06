"""Limitation de débit (seau à jetons), par clé (IP, compte, clé d'API).

- ``LimiteurDebit`` : en mémoire du processus (tests, outils, et **secours** du limiteur partagé).
- ``LimiteurDebitPartage`` (D-3201) : seaux en base (``storage.securite``), partagés par tous les processus et
  conservés au redémarrage ; mise à jour atomique ; identifiants pseudonymisés (HMAC) ; table bornée (purge
  périodique des seaux pleins et plafond de lignes). Si la base est indisponible, le limiteur bascule sur son
  secours en mémoire (mêmes seuils) et le journalise — jamais d'exception vers la route.

Interface commune : ``autoriser(cle, cout)``, ``attente(cle, cout)``, ``rembourser(cle, cout)`` (une connexion
réussie rend son jeton), ``effacer(cle)`` (déblocage).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from controldone.storage.db import Database

__all__ = ["Limiteur", "LimiteurDebit", "LimiteurDebitPartage", "cle_debit", "sel_debit"]

log = logging.getLogger("controldone.auth.debit")


class Limiteur(Protocol):
    def autoriser(self, cle: str, cout: float = 1.0) -> bool: ...
    def attente(self, cle: str, cout: float = 1.0) -> float: ...
    def rembourser(self, cle: str, cout: float = 1.0) -> None: ...
    def effacer(self, cle: str) -> None: ...


class LimiteurDebit:
    """``capacite`` jetons, rechargés de ``par_seconde`` ; au plus ``max_cles`` clés suivies (LRU)."""

    def __init__(
        self,
        capacite: float,
        par_seconde: float,
        *,
        max_cles: int = 10_000,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacite <= 0 or par_seconde <= 0:
            raise ValueError("capacité et recharge strictement positives")
        self.capacite = float(capacite)
        self.par_seconde = float(par_seconde)
        self.max_cles = max_cles
        self.horloge = horloge
        self._seaux: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._verrou = threading.Lock()

    def _courant(self, cle: str, maintenant: float) -> float:
        jetons, dernier = self._seaux.pop(cle, (self.capacite, maintenant))
        return min(self.capacite, jetons + max(0.0, maintenant - dernier) * self.par_seconde)

    def _poser(self, cle: str, jetons: float, maintenant: float) -> None:
        self._seaux[cle] = (jetons, maintenant)
        while len(self._seaux) > self.max_cles:
            self._seaux.popitem(last=False)

    def autoriser(self, cle: str, cout: float = 1.0) -> bool:
        with self._verrou:
            maintenant = self.horloge()
            jetons = self._courant(cle, maintenant)
            ok = jetons >= cout
            if ok:
                jetons -= cout
            self._poser(cle, jetons, maintenant)
            return ok

    def attente(self, cle: str, cout: float = 1.0) -> float:
        """Secondes avant qu'une requête de ``cout`` soit autorisée (0 si tout de suite)."""
        with self._verrou:
            jetons, dernier = self._seaux.get(cle, (self.capacite, self.horloge()))
            jetons = min(self.capacite, jetons + (self.horloge() - dernier) * self.par_seconde)
            return max(0.0, (cout - jetons) / self.par_seconde)

    def rembourser(self, cle: str, cout: float = 1.0) -> None:
        with self._verrou:
            if cle not in self._seaux:
                return
            maintenant = self.horloge()
            self._poser(cle, min(self.capacite, self._courant(cle, maintenant) + cout), maintenant)

    def effacer(self, cle: str) -> None:
        with self._verrou:
            self._seaux.pop(cle, None)


def sel_debit(cles_maitresses: list[bytes] | tuple[bytes, ...]) -> bytes:
    """Sel de pseudonymisation des clés de débit, dérivé de la clé maîtresse courante (même valeur pour le web,
    le worker et la ligne de commande ``controldone debit``)."""
    return hashlib.sha256(b"controldone/debit|" + cles_maitresses[0]).digest()


def cle_debit(portee: str, identifiant: str, sel: bytes) -> str:
    """Clé stockée : ``<portée>:<HMAC-SHA256(sel, identifiant)>`` — l'adresse ou le courriel n'est jamais écrit
    en clair, et le sel (dérivé de la clé maîtresse) empêche de retrouver une adresse IPv4 par force brute."""
    mac = hmac.new(sel, f"{portee}|{identifiant}".encode(), hashlib.sha256).hexdigest()
    return f"{portee}:{mac}"


class LimiteurDebitPartage:
    """Seau à jetons en base, nommé ``portee`` (``connexion_ip``, ``connexion_compte``, ``api``…)."""

    def __init__(
        self,
        portee: str,
        capacite: float,
        par_seconde: float,
        *,
        db: Database,
        sel: bytes,
        horloge: Callable[[], float] = time.time,
        max_lignes: int = 100_000,
        purge_toutes_s: float = 60.0,
    ) -> None:
        if capacite <= 0 or par_seconde <= 0:
            raise ValueError("capacité et recharge strictement positives")
        if not sel:
            raise ValueError("sel de pseudonymisation requis")
        self.portee = portee
        self.capacite = float(capacite)
        self.par_seconde = float(par_seconde)
        self.db = db
        self.sel = sel
        self.horloge = horloge
        self.max_lignes = max_lignes
        self.purge_toutes_s = purge_toutes_s
        self._prochaine_purge = 0.0
        self.secours = LimiteurDebit(capacite, par_seconde)
        self._verrou = threading.Lock()

    def cle(self, identifiant: str) -> str:
        return cle_debit(self.portee, identifiant, self.sel)

    def _panne(self, operation: str, exc: BaseException) -> None:
        log.warning(
            "debit_base_indisponible portee=%s operation=%s erreur=%s",
            self.portee,
            operation,
            type(exc).__name__,
        )

    def _purger_si_du(self, maintenant: float) -> None:
        with self._verrou:
            if maintenant < self._prochaine_purge:
                return
            self._prochaine_purge = maintenant + self.purge_toutes_s
        from controldone.storage.securite import purger_debit

        try:
            purger_debit(self.db, maintenant=maintenant, max_lignes=self.max_lignes)
        except Exception as exc:  # la purge n'empêche jamais une requête
            self._panne("purge", exc)

    def autoriser(self, cle: str, cout: float = 1.0) -> bool:
        from controldone.storage.securite import consommer_jetons

        maintenant = self.horloge()
        try:
            ok, _ = consommer_jetons(
                self.db,
                self.cle(cle),
                portee=self.portee,
                capacite=self.capacite,
                par_seconde=self.par_seconde,
                cout=cout,
                maintenant=maintenant,
            )
        except Exception as exc:
            self._panne("consommer", exc)
            return self.secours.autoriser(cle, cout)
        self._purger_si_du(maintenant)
        return ok

    def attente(self, cle: str, cout: float = 1.0) -> float:
        from controldone.storage.securite import jetons_disponibles

        try:
            jetons = jetons_disponibles(
                self.db,
                self.cle(cle),
                capacite=self.capacite,
                par_seconde=self.par_seconde,
                maintenant=self.horloge(),
            )
        except Exception as exc:
            self._panne("attente", exc)
            return self.secours.attente(cle, cout)
        return max(0.0, (cout - jetons) / self.par_seconde)

    def rembourser(self, cle: str, cout: float = 1.0) -> None:
        from controldone.storage.securite import crediter_jetons

        try:
            crediter_jetons(
                self.db,
                self.cle(cle),
                portee=self.portee,
                capacite=self.capacite,
                par_seconde=self.par_seconde,
                cout=cout,
                maintenant=self.horloge(),
            )
        except Exception as exc:
            self._panne("rembourser", exc)
            self.secours.rembourser(cle, cout)

    def effacer(self, cle: str) -> None:
        from controldone.storage.securite import effacer_debit

        self.secours.effacer(cle)
        try:
            effacer_debit(self.db, cles=[self.cle(cle)], journal=False)
        except Exception as exc:
            self._panne("effacer", exc)
