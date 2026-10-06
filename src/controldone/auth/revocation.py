"""Registre persistant des sessions : révocations (D-3202, RS-17, table ``sessions_revoquees``) et sessions
ouvertes (D-3603, table ``sessions_actives`` : « mes sessions actives », « fermer mes autres sessions »).

Partagé par tous les processus web et conservé au redémarrage. Une base indisponible n'interrompt pas la
requête : la révocation locale du processus reste appliquée, l'incident est journalisé (nom d'exception
seulement) — et les pages authentifiées relisent de toute façon le compte en base (``web.securite.acteur_de``).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from controldone.storage.db import Database

__all__ = ["RegistreRevocations"]

log = logging.getLogger("controldone.auth.revocation")


class RegistreRevocations:
    def __init__(
        self, db: Database, *, horloge: Callable[[], float] = time.time, purge_toutes_s: float = 3600.0
    ) -> None:
        self.db = db
        self.horloge = horloge
        self.purge_toutes_s = purge_toutes_s
        self._prochaine_purge = 0.0
        self._verrou = threading.Lock()

    def _panne(self, operation: str, exc: BaseException) -> None:
        log.warning("revocation_base_indisponible operation=%s erreur=%s", operation, type(exc).__name__)

    def _purger_si_du(self) -> None:
        from controldone.storage.securite import purger_revocations

        maintenant = self.horloge()
        with self._verrou:
            if maintenant < self._prochaine_purge:
                return
            self._prochaine_purge = maintenant + self.purge_toutes_s
        try:
            purger_revocations(self.db, maintenant=maintenant)
        except Exception as exc:
            self._panne("purge", exc)

    def revoquer(self, sid: str, *, expire: float) -> None:
        from controldone.storage.securite import revoquer_session

        try:
            revoquer_session(self.db, sid, expire=expire)
        except Exception as exc:
            self._panne("revoquer", exc)
        self._purger_si_du()

    def revoquer_utilisateur(self, user_id: str, *, apres: float, expire: float) -> None:
        from controldone.storage.securite import revoquer_sessions_utilisateur

        try:
            revoquer_sessions_utilisateur(self.db, user_id, apres=apres, expire=expire)
        except Exception as exc:
            self._panne("revoquer_utilisateur", exc)

    def ouvrir(
        self,
        sid: str,
        user_id: str,
        *,
        debut: float,
        vu: float,
        expire: float,
        appareil: str = "",
        reseau: str = "",
    ) -> None:
        from controldone.storage.securite import enregistrer_session

        try:
            enregistrer_session(
                self.db,
                sid=sid,
                user_id=user_id,
                debut=debut,
                vu=vu,
                expire=expire,
                appareil=appareil,
                reseau=reseau,
            )
        except Exception as exc:
            self._panne("ouvrir", exc)

    def toucher(self, sid: str, *, vu: float, expire: float) -> None:
        from controldone.storage.securite import toucher_session

        try:
            toucher_session(self.db, sid, vu=vu, expire=expire)
        except Exception as exc:
            self._panne("toucher", exc)

    def sessions(self, user_id: str, *, maintenant: float, sid_courant: str | None = None) -> list:
        """``storage.securite.SessionActive`` de ``user_id`` (liste vide si la base est indisponible)."""
        from controldone.storage.securite import sessions_utilisateur

        try:
            return sessions_utilisateur(self.db, user_id, maintenant=maintenant, sid_courant=sid_courant)
        except Exception as exc:
            self._panne("lister", exc)
            return []

    def est_revoquee(self, sid: str, user_id: str, debut: float) -> bool:
        from controldone.storage.securite import session_revoquee

        try:
            return session_revoquee(self.db, sid=sid, user_id=user_id, debut=debut)
        except Exception as exc:
            self._panne("lire", exc)
            return False
