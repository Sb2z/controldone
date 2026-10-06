"""Notifications poussées des alertes du fondateur : webhook et courriel (D-3502).

Les alertes (``storage.alertes``) ne se voyaient qu'en se connectant à ``/admin/alertes``. Ce module les pousse
vers l'extérieur, avec trois garde-fous :

1. **Rien n'est envoyé par défaut.** Un canal n'existe que s'il est configuré explicitement dans l'environnement
   (``CONTROLDONE_NOTIF_*``, voir ``deploy/.env.prod.example``), et seulement en production
   (``CONTROLDONE_ENV=prod``) : en ``dev`` et en ``test``, aucune configuration ne déclenche d'envoi.
2. **Aucune donnée client** dans ce qui part : type d'alerte, libellé fixe, nombre, horodatage et chemin
   ``/admin/alertes``. Jamais le message de l'alerte, ni l'identifiant d'un client, ni un nom de fichier.
3. **Une notification par type et par jour** (table ``notifications_alertes``), comme les alertes de
   sauvegarde elles-mêmes ; les alertes suivantes du même type et du même jour sont regroupées sans envoi. Les
   alertes de plus de 24 h (ou déjà lues) ne sont jamais envoyées : activer les notifications ne déverse pas
   l'historique. Un envoi en échec est retenté au passage suivant, 5 fois par jour au plus.

Canaux :

- **webhook** : ``POST`` JSON sur ``CONTROLDONE_NOTIF_WEBHOOK_URL`` (HTTPS obligatoire, sauf boucle locale) —
  compatible Slack / Mattermost (champ ``text``), Healthchecks (URL ``…/fail``), ntfy (format ``texte`` : corps en
  texte brut). Aucune redirection suivie ; 10 s de délai.
- **courriel** : SMTP (``smtplib``, STARTTLS par défaut ou TLS implicite), vers une liste fixe de destinataires
  tenue dans l'environnement — aucun agent, aucun client ne peut choisir l'adresse. La file des actions sortantes
  (approbation par le fondateur) ne convient pas à une alerte qui doit partir sans attendre (D-459, D-3502).

Appelé par ``controldone alertes notifier`` (planificateur Docker, toutes les 5 minutes). L'URL du webhook et le mot
de passe SMTP ne sont jamais journalisés.
"""

from __future__ import annotations

import ipaddress
import logging
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any, Protocol
from urllib.parse import urlsplit

from controldone.config import env

__all__ = [
    "LIBELLES",
    "CanalCourriel",
    "CanalWebhook",
    "ConfigNotifications",
    "HistoriqueNotifications",
    "RapportNotifications",
    "charge_utile",
    "envoyer_essai",
    "historique",
    "notifier_alertes",
]

log = logging.getLogger("controldone.notifications")

LIEN = "/admin/alertes"
FENETRE = timedelta(hours=24)
ESSAIS_MAX_PAR_JOUR = 5

#: Libellés fixes (aucune donnée variable) ; un type inconnu est envoyé sous son nom technique.
LIBELLES = {
    "job_mort": "Tâche en échec définitif",
    "cout_ia_alerte": "Coût IA à 80 % du plafond",
    "cout_ia_plafond": "Plafond de coût IA atteint",
    "sauvegarde_echec": "Sauvegarde en échec",
    "sauvegarde_verification_echec": "Sauvegarde non conforme",
    "sauvegarde_absente": "Aucune sauvegarde récente",
    "sauvegarde_hors_site_echec": "Copie hors site en échec",
    "volume_non_chiffre": "Base hors volume chiffré",
    "essai": "Essai de notification",
}


def _boucle_locale(hote: str | None) -> bool:
    if not hote:
        return False
    if hote == "localhost":
        return True
    try:
        return ipaddress.ip_address(hote).is_loopback
    except ValueError:
        return False


def charge_utile(kind: str, nombre: int, quand: datetime) -> dict[str, Any]:
    """Ce qui part : **rien d'autre** que le type, son libellé fixe, le nombre, l'heure et le chemin."""
    libelle = LIBELLES.get(kind, kind)
    horodatage = quand.astimezone(UTC).isoformat(timespec="seconds")
    return {
        "source": "controldone",
        "evenement": "alerte",
        "kind": kind,
        "libelle": libelle,
        "nombre": nombre,
        "horodatage": horodatage,
        "lien": LIEN,
        "text": f"ControlDOne — {libelle} ({nombre}) — {horodatage} — voir {LIEN}",
    }


class Canal(Protocol):
    nom: str

    def envoyer(self, charge: dict[str, Any]) -> None:
        """Lève une exception si l'envoi échoue."""
        ...


@dataclass
class CanalWebhook:
    url: str = field(repr=False)  # le nom du sujet ntfy vaut mot de passe : jamais affiché ni journalisé
    format: str = "json"  # json | texte
    transport: Any = None  # httpx.BaseTransport (essais)
    nom: str = "webhook"
    jeton: str = field(default="", repr=False)  # ntfy : jeton d'accès (Authorization: Bearer), D-4104
    priorite: int = 4  # ntfy (format texte) : 1 à 5 ; l'essai part en 3

    def envoyer(self, charge: dict[str, Any]) -> None:
        import httpx

        entetes: dict[str, str] = {}
        if self.jeton:
            entetes["Authorization"] = f"Bearer {self.jeton}"
        with httpx.Client(timeout=10, follow_redirects=False, transport=self.transport) as client:
            if self.format == "texte":  # ntfy : titre, priorité et étiquette par en-têtes
                priorite = 3 if charge.get("kind") == "essai" else self.priorite
                entetes.update(
                    {
                        "Content-Type": "text/plain; charset=utf-8",
                        "Title": "ControlDOne",
                        "Priority": str(priorite),
                        "Tags": "warning" if priorite >= 4 else "bell",
                    }
                )
                r = client.post(self.url, content=charge["text"].encode(), headers=entetes)
            else:
                r = client.post(self.url, json=charge, headers=entetes)
        if not 200 <= r.status_code < 300:
            raise RuntimeError(f"webhook : réponse {r.status_code}")


@dataclass
class CanalCourriel:
    hote: str
    port: int
    expediteur: str
    destinataires: list[str]
    securite: str = "starttls"  # starttls | ssl | aucune (boucle locale seulement)
    utilisateur: str = ""
    mot_de_passe: str = field(default="", repr=False)
    fabrique: Callable[..., Any] | None = None  # essais : remplace smtplib.SMTP / SMTP_SSL
    nom: str = "courriel"

    def envoyer(self, charge: dict[str, Any]) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"[ControlDOne] {charge['libelle']} ({charge['nombre']})"
        msg["From"] = self.expediteur
        msg["To"] = ", ".join(self.destinataires)
        msg.set_content(
            f"{charge['libelle']} : {charge['nombre']} alerte(s) de type « {charge['kind']} ».\n"
            f"Horodatage : {charge['horodatage']}\n\n"
            f"Le détail est dans l'application, après connexion : {charge['lien']}\n"
            "(Ce message ne contient volontairement aucune donnée client.)\n"
        )
        contexte = ssl.create_default_context()
        if self.fabrique is not None:
            serveur = self.fabrique(self.hote, self.port, timeout=15)
        elif self.securite == "ssl":
            serveur = smtplib.SMTP_SSL(self.hote, self.port, timeout=15, context=contexte)
        else:
            serveur = smtplib.SMTP(self.hote, self.port, timeout=15)
        with serveur as s:
            if self.securite == "starttls":
                s.starttls(context=contexte)
            if self.utilisateur:
                s.login(self.utilisateur, self.mot_de_passe)
            s.send_message(msg)


@dataclass
class ConfigNotifications:
    mode: str = "dev"
    canaux: list[Any] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)
    types: frozenset[str] | None = None  # None : tous

    @property
    def actif(self) -> bool:
        return self.mode == "prod" and bool(self.canaux)

    def motif_inactif(self) -> str:
        if self.mode != "prod":
            return f"mode {self.mode} : aucune notification n'est envoyée hors production"
        if not self.canaux:
            return "aucun canal configuré (CONTROLDONE_NOTIF_WEBHOOK_URL, CONTROLDONE_NOTIF_SMTP_HOTE)"
        return ""

    @classmethod
    def depuis_env(cls) -> ConfigNotifications:
        from controldone.storage.cles import mode_execution

        cfg = cls(mode=mode_execution())
        url = env("CONTROLDONE_NOTIF_WEBHOOK_URL").strip()
        if url:
            parties = urlsplit(url)
            fmt = env("CONTROLDONE_NOTIF_WEBHOOK_FORMAT", "json").strip().lower()
            if parties.scheme != "https" and not (
                parties.scheme == "http" and _boucle_locale(parties.hostname)
            ):
                cfg.erreurs.append("CONTROLDONE_NOTIF_WEBHOOK_URL : HTTPS obligatoire (sauf boucle locale)")
            elif fmt not in ("json", "texte"):
                cfg.erreurs.append("CONTROLDONE_NOTIF_WEBHOOK_FORMAT : json ou texte")
            else:
                try:
                    priorite = int(env("CONTROLDONE_NOTIF_NTFY_PRIORITE", "4"))
                except ValueError:
                    priorite = 0
                if not 1 <= priorite <= 5:
                    cfg.erreurs.append("CONTROLDONE_NOTIF_NTFY_PRIORITE : 1 à 5 (4 retenu)")
                    priorite = 4
                cfg.canaux.append(
                    CanalWebhook(
                        url=url,
                        format=fmt,
                        priorite=priorite,
                        jeton=env("CONTROLDONE_NOTIF_WEBHOOK_JETON").strip(),
                    )
                )
        hote = env("CONTROLDONE_NOTIF_SMTP_HOTE").strip()
        if hote:
            securite = env("CONTROLDONE_NOTIF_SMTP_SECURITE", "starttls").strip().lower()
            de = env("CONTROLDONE_NOTIF_COURRIEL_DE").strip()
            a = [x.strip() for x in env("CONTROLDONE_NOTIF_COURRIEL_A").split(",") if x.strip()]
            try:
                port = int(env("CONTROLDONE_NOTIF_SMTP_PORT", "465" if securite == "ssl" else "587"))
            except ValueError:
                port = 0
            if securite not in ("starttls", "ssl", "aucune") or (
                securite == "aucune" and not _boucle_locale(hote)
            ):
                cfg.erreurs.append(
                    "CONTROLDONE_NOTIF_SMTP_SECURITE : starttls ou ssl (aucune : relais local seulement)"
                )
            elif not de or not a or not all("@" in x for x in [de, *a]) or not 0 < port < 65536:
                cfg.erreurs.append(
                    "courriel : CONTROLDONE_NOTIF_COURRIEL_DE, CONTROLDONE_NOTIF_COURRIEL_A et "
                    "CONTROLDONE_NOTIF_SMTP_PORT requis"
                )
            else:
                cfg.canaux.append(
                    CanalCourriel(
                        hote=hote,
                        port=port,
                        expediteur=de,
                        destinataires=a,
                        securite=securite,
                        utilisateur=env("CONTROLDONE_NOTIF_SMTP_UTILISATEUR").strip(),
                        mot_de_passe=env("CONTROLDONE_NOTIF_SMTP_MOT_DE_PASSE"),
                    )
                )
        types = {t.strip() for t in env("CONTROLDONE_NOTIF_TYPES").split(",") if t.strip()}
        cfg.types = frozenset(types) if types else None
        return cfg


@dataclass
class RapportNotifications:
    actif: bool = False
    motif: str = ""
    envoyees: dict[str, int] = field(default_factory=dict)  # kind -> nombre d'alertes notifiées
    regroupees: int = 0  # alertes d'un type déjà notifié aujourd'hui
    ecartees: int = 0  # type exclu par CONTROLDONE_NOTIF_TYPES
    echecs: dict[str, list[str]] = field(default_factory=dict)  # kind -> canaux en échec

    def lignes(self) -> list[str]:
        if not self.actif:
            return [f"notifications inactives : {self.motif}"]
        sortie = [f"notifiées : {k} ({n})" for k, n in sorted(self.envoyees.items())]
        sortie += [f"échec : {k} ({', '.join(c)})" for k, c in sorted(self.echecs.items())]
        sortie.append(
            f"regroupées (déjà notifiées aujourd'hui) : {self.regroupees} ; écartées : {self.ecartees}"
        )
        return sortie


def _envoyer(canaux: list[Any], charge: dict[str, Any]) -> tuple[list[str], list[str]]:
    reussis, rates = [], []
    for canal in canaux:
        try:
            canal.envoyer(charge)
            reussis.append(canal.nom)
        except Exception as exc:  # jamais l'URL ni le mot de passe : nom de classe seulement
            rates.append(canal.nom)
            log.warning(
                "notification_echec canal=%s kind=%s erreur=%s", canal.nom, charge["kind"], type(exc).__name__
            )
    return reussis, rates


def notifier_alertes(
    db: Any, config: ConfigNotifications | None = None, *, now: datetime | None = None
) -> RapportNotifications:
    """Pousse les alertes récentes non traitées : une notification par type et par jour, sur tous les canaux."""
    from controldone.storage.alertes import (
        a_notifier,
        enregistrer_notification,
        etat_notification,
        marquer_notifiees,
    )

    config = config or ConfigNotifications.depuis_env()
    now = now or datetime.now(UTC)
    rapport = RapportNotifications(actif=config.actif, motif=config.motif_inactif())
    if not config.actif:  # aucune écriture : les alertes restent à traiter si les notifications s'activent
        return rapport
    with db.transaction_systeme() as s:
        groupes = a_notifier(s, depuis=now - FENETRE, quand=now)
    for kind, ids in sorted(groupes.items()):
        if config.types is not None and kind not in config.types:
            with db.transaction_systeme() as s:
                marquer_notifiees(s, ids, now)
            rapport.ecartees += len(ids)
            continue
        cle = f"{kind}:{now.astimezone(UTC):%Y-%m-%d}"
        with db.transaction_systeme() as s:
            statut, essais = etat_notification(s, cle)
            if statut == "envoyee" or essais >= ESSAIS_MAX_PAR_JOUR:
                marquer_notifiees(s, ids, now)
                rapport.regroupees += len(ids)
                continue
        reussis, rates = _envoyer(config.canaux, charge_utile(kind, len(ids), now))  # hors transaction
        with db.transaction_systeme() as s:
            essais = enregistrer_notification(
                s,
                cle=cle,
                kind=kind,
                nombre=len(ids),
                canaux=_resultats(reussis, rates),
                envoyee=bool(reussis),
                quand=now,
            )
            if reussis or essais >= ESSAIS_MAX_PAR_JOUR:
                marquer_notifiees(s, ids, now)
        if reussis:
            rapport.envoyees[kind] = len(ids)
        if rates:
            rapport.echecs[kind] = rates
    return rapport


def _resultats(reussis: list[str], rates: list[str]) -> list[str]:
    """Canaux et résultat, pour l'historique : ``["webhook:ok", "courriel:echec"]`` (D-4104)."""
    return [f"{c}:ok" for c in reussis] + [f"{c}:echec" for c in rates]


def envoyer_essai(
    config: ConfigNotifications | None = None, *, now: datetime | None = None, db: Any = None
) -> tuple[list[str], list[str]]:
    """Notification d'essai (type ``essai``) sur chaque canal configuré. Lancée **seulement** par le fondateur
    (``controldone alertes essai``). Avec ``db`` : l'essai est inscrit dans l'historique (clé
    ``essai:<horodatage>``, aucune alerte touchée) ; une base injoignable n'empêche pas l'essai."""
    config = config or ConfigNotifications.depuis_env()
    if not config.actif:
        return [], []
    now = now or datetime.now(UTC)
    reussis, rates = _envoyer(config.canaux, charge_utile("essai", 1, now))
    if db is not None:
        try:
            from controldone.storage.alertes import enregistrer_notification

            with db.transaction_systeme() as s:
                enregistrer_notification(
                    s,
                    cle=f"essai:{now.astimezone(UTC).isoformat(timespec='seconds')}",
                    kind="essai",
                    nombre=1,
                    canaux=_resultats(reussis, rates),
                    envoyee=bool(reussis),
                    quand=now,
                )
        except Exception as exc:  # l'essai a eu lieu ; seule son inscription manque
            log.warning("notification_essai_non_inscrite erreur=%s", type(exc).__name__)
    return reussis, rates


# --- historique (lecture, D-4104) : pour la page /admin/alertes et « controldone alertes historique » ---------


@dataclass(frozen=True)
class HistoriqueNotifications:
    """Ce que l'interface affiche : la configuration (sans URL ni adresse), l'état de chaque canal et les
    dernières notifications (``storage.alertes.NotificationEnvoyee``)."""

    actif: bool
    motif_inactif: str
    canaux_configures: tuple[str, ...]
    erreurs_configuration: tuple[str, ...]
    canaux: dict[str, Any]  # {nom: storage.alertes.EtatCanal}
    notifications: list[Any]  # [storage.alertes.NotificationEnvoyee], la plus récente d'abord

    def libelle(self, kind: str) -> str:
        return LIBELLES.get(kind, kind)


def historique(
    db: Any,
    *,
    limite: int = 50,
    jours: int = 30,
    config: ConfigNotifications | None = None,
    now: datetime | None = None,
) -> HistoriqueNotifications:
    """Historique des notifications des ``jours`` derniers jours et santé des canaux. Lecture seule ; aucune
    URL de webhook, aucun jeton ni aucune adresse dans le résultat."""
    from controldone.storage.alertes import etat_canaux, historique_notifications

    config = config or ConfigNotifications.depuis_env()
    depuis = (now or datetime.now(UTC)) - timedelta(days=jours)
    with db.transaction_systeme() as s:
        lignes = historique_notifications(s, limite=limite, depuis=depuis)
        canaux = etat_canaux(s, depuis=depuis)
    return HistoriqueNotifications(
        actif=config.actif,
        motif_inactif=config.motif_inactif(),
        canaux_configures=tuple(c.nom for c in config.canaux),
        erreurs_configuration=tuple(config.erreurs),
        canaux=canaux,
        notifications=lignes,
    )
