"""Expéditeurs des courriels de prospection (interface ``outbox.Expediteur``, D-5006).

- **Aucun envoi par défaut.** ``expediteur_configure()`` renvoie ``None`` tant que la messagerie de prospection
  n'est pas configurée dans l'environnement (``CONTROLDONE_PROSPECTION_SMTP_*``) **et** que le service n'est pas en
  production : une action approuvée reste alors « approuvée, envoi non configuré ». Jamais de faux envoi.
- ``ExpediteurSmtp`` : un message ``text/plain`` par destinataire, en-têtes ``List-Unsubscribe`` et
  ``List-Unsubscribe-Post`` (désinscription en un clic, RFC 8058) quand le lien existe ; aucun pixel, aucun lien
  suivi. Le mot de passe n'est jamais journalisé.
- ``ExpediteurDeclaration`` : le fondateur **déclare** avoir envoyé le message lui-même depuis sa messagerie
  (pratique actuelle : envois un par un). Rien ne part ; la référence le dit (``declaration:…``).
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from controldone.outbox.modele import ActionSortante
from controldone.storage.coltypes import maintenant

__all__ = ["ExpediteurDeclaration", "ExpediteurSmtp", "construire_message", "expediteur_configure"]


def construire_message(action: ActionSortante, expediteur: str) -> EmailMessage:
    p = action.payload_effectif
    msg = EmailMessage()
    msg["Subject"] = str(p.get("objet") or "")
    msg["From"] = expediteur
    msg["To"] = ", ".join(p.get("destinataires") or [])
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=expediteur.rpartition("@")[2] or None)
    lien = p.get("lien_desinscription")
    if lien:
        msg["List-Unsubscribe"] = f"<{lien}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(str(p.get("corps") or ""))
    return msg


@dataclass
class ExpediteurSmtp:
    hote: str
    port: int
    expediteur: str
    securite: str = "starttls"  # starttls | ssl
    utilisateur: str = ""
    mot_de_passe: str = field(default="", repr=False)
    fabrique: Callable[..., Any] | None = None  # tests : remplace smtplib.SMTP / SMTP_SSL
    nom: str = "smtp"

    def envoyer(self, action: ActionSortante) -> str:
        msg = construire_message(action, self.expediteur)
        contexte = ssl.create_default_context()
        if self.fabrique is not None:
            serveur = self.fabrique(self.hote, self.port, timeout=20)
        elif self.securite == "ssl":
            serveur = smtplib.SMTP_SSL(self.hote, self.port, timeout=20, context=contexte)
        else:
            serveur = smtplib.SMTP(self.hote, self.port, timeout=20)
        with serveur as s:
            if self.securite == "starttls":
                s.starttls(context=contexte)
            if self.utilisateur:
                s.login(self.utilisateur, self.mot_de_passe)
            s.send_message(msg)
        return f"smtp:{msg['Message-ID']}"


class ExpediteurDeclaration:
    """Envoi fait par le fondateur depuis sa propre messagerie, déclaré dans l'application (rien ne part)."""

    nom = "declaration"

    def __init__(self, acteur_id: str) -> None:
        self.acteur_id = acteur_id

    def envoyer(self, action: ActionSortante) -> str:
        return f"declaration:{self.acteur_id}:{maintenant().isoformat()}"


def expediteur_configure(env: dict[str, str] | None = None, mode: str | None = None) -> ExpediteurSmtp | None:
    """Messagerie de prospection configurée (production seulement), sinon ``None`` : rien ne peut partir."""
    import os

    from controldone.config import charger_fichier_env
    from controldone.storage.cles import mode_execution

    charger_fichier_env()
    e = dict(os.environ) if env is None else env
    if (mode or mode_execution()) != "prod":
        return None
    hote = (e.get("CONTROLDONE_PROSPECTION_SMTP_HOTE") or "").strip()
    de = (e.get("CONTROLDONE_PROSPECTION_COURRIEL_DE") or "").strip()
    securite = (e.get("CONTROLDONE_PROSPECTION_SMTP_SECURITE") or "starttls").strip().lower()
    if not hote or "@" not in de or securite not in ("starttls", "ssl"):
        return None
    try:
        port = int(e.get("CONTROLDONE_PROSPECTION_SMTP_PORT") or ("465" if securite == "ssl" else "587"))
    except ValueError:
        return None
    if not 0 < port < 65536:
        return None
    return ExpediteurSmtp(
        hote=hote,
        port=port,
        expediteur=de,
        securite=securite,
        utilisateur=(e.get("CONTROLDONE_PROSPECTION_SMTP_UTILISATEUR") or "").strip(),
        mot_de_passe=e.get("CONTROLDONE_PROSPECTION_SMTP_MOT_DE_PASSE") or "",
    )
