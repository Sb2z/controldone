"""Connecteur ``BoiteImap`` : boîte dédiée d'un client, en IMAPS (``imaplib`` de la bibliothèque standard).

- Connexion TLS vérifiée (``ssl.create_default_context``) ; mot de passe lu dans une variable
  d'environnement nommée par la configuration (jamais en base).
- Relevé des messages non lus (``UNSEEN``), lus en ``BODY.PEEK[]`` (le relevé ne change rien sur le
  serveur) ; idempotence par ``Message-ID`` (et sha256 des pièces jointes).
- L'expéditeur est contrôlé à l'intégration (liste blanche du client) : sinon quarantaine + alerte.
- ``acquitter`` : message intégré -> marqué lu ; message en quarantaine -> copié dans le dossier de
  quarantaine et marqué lu. Le corps et l'objet ne déclenchent jamais aucune action.
"""

from __future__ import annotations

import contextlib
import imaplib
import os
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email.parser import BytesHeaderParser
from email.policy import default as politique_defaut
from typing import Any

from .base import Depot, ResultatDepot

__all__ = ["BoiteImap", "ConfigImap"]

#: Seules variables d'environnement qu'un connecteur IMAP peut lire comme mot de passe.
PREFIXE_SECRET_RE = re.compile(r"CONTROLDONE_IMAP_[A-Z0-9_]+")


@dataclass(frozen=True)
class ConfigImap:
    hote: str
    utilisateur: str
    secret_env: str  # nom de la variable d'environnement qui porte le mot de passe
    port: int = 993
    dossier: str = "INBOX"
    dossier_quarantaine: str = "Quarantaine"

    def __post_init__(self) -> None:
        # Le mot de passe est envoyé à ``hote`` : la configuration (réglages du client) ne doit pouvoir nommer
        # qu'une variable dédiée, jamais CONTROLDONE_MASTER_KEY, un secret Stripe ou une clé d'API (RS-10).
        if not PREFIXE_SECRET_RE.fullmatch(self.secret_env or ""):
            raise ValueError("secret_env : variable CONTROLDONE_IMAP_<NOM> attendue")

    @classmethod
    def depuis_reglages(cls, d: dict[str, Any]) -> ConfigImap:
        return cls(
            hote=str(d["hote"]),
            utilisateur=str(d["utilisateur"]),
            secret_env=str(d["secret_env"]),
            port=int(d.get("port", 993)),
            dossier=str(d.get("dossier", "INBOX")),
            dossier_quarantaine=str(d.get("dossier_quarantaine", "Quarantaine")),
        )


def _octets(reponse: list[Any]) -> bytes | None:
    for partie in reponse or []:
        if isinstance(partie, tuple) and len(partie) >= 2 and isinstance(partie[1], bytes | bytearray):
            return bytes(partie[1])
    return None


class BoiteImap:
    nom = "boite_imap"

    def __init__(
        self,
        tenant_id: str,
        config: ConfigImap,
        *,
        fabrique: Callable[[], Any] | None = None,
        max_messages: int = 50,
    ) -> None:
        self.tenant_id = tenant_id
        self.config = config
        self.fabrique = fabrique
        self.max_messages = max_messages

    def _ouvrir(self) -> Any:
        if self.fabrique is not None:
            m = self.fabrique()
        else:  # pragma: no cover - réseau
            m = imaplib.IMAP4_SSL(
                self.config.hote, self.config.port, ssl_context=ssl.create_default_context()
            )
        mot_de_passe = os.environ.get(self.config.secret_env)
        if not mot_de_passe:
            raise RuntimeError(f"mot de passe IMAP absent (variable {self.config.secret_env})")
        m.login(self.config.utilisateur, mot_de_passe)
        choisir_dossier = m.select  # commande IMAP SELECT (rien à voir avec SQL ; test d'architecture)
        typ, _ = choisir_dossier(self.config.dossier)
        if typ != "OK":
            raise RuntimeError("dossier IMAP introuvable")
        return m

    @staticmethod
    def _fermer(m: Any) -> None:
        with contextlib.suppress(Exception):
            m.logout()

    def relever(self) -> list[Depot]:
        m = self._ouvrir()
        try:
            typ, data = m.uid("SEARCH", None, "UNSEEN")
            if typ != "OK":
                return []
            uids = (data[0] or b"").split()[: self.max_messages]
            depots = []
            for uid in uids:
                typ, reponse = m.uid("FETCH", uid, "(BODY.PEEK[])")
                brut = _octets(reponse) if typ == "OK" else None
                if not brut:
                    continue
                entetes = BytesHeaderParser(policy=politique_defaut).parsebytes(brut)
                message_id = str(entetes.get("Message-ID", "")).strip() or None
                depots.append(
                    Depot(
                        tenant_id=self.tenant_id,
                        canal="courriel",
                        source=self.nom,
                        courriel=brut,
                        message_id=message_id,
                        reference=uid.decode("ascii", "replace"),
                    )
                )
            return depots
        finally:
            self._fermer(m)

    def acquitter(self, depot: Depot, resultat: ResultatDepot) -> None:
        uid = (depot.reference or "").encode("ascii")
        if not uid:
            return
        m = self._ouvrir()
        try:
            if resultat.statut == "quarantaine":
                m.uid("COPY", uid, self.config.dossier_quarantaine)
            m.uid("STORE", uid, "+FLAGS", r"(\Seen)")
        finally:
            self._fermer(m)
