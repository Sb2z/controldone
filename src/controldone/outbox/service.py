"""File de validation des actions sortantes (``ActionSortante``).

Cycle : ``brouillon -> approuve | corrige | refuse``, puis ``approuve | corrige -> envoye``.

- Tout texte (objet, corps, et toute chaîne du contenu) passe ``guardrails.check_text`` avant de pouvoir
  être approuvé ou corrigé ; sinon ``ActionBloquee`` (le motif est enregistré sur l'action).
- Autonomie par type (``manuel`` par défaut pour TOUS les types ; ``auto`` = approbation automatique si les
  garde-fous passent) : modifiable par le fondateur seulement. L'envoi reste un appel explicite.
- Approuver, corriger, refuser, envoyer : réservés au fondateur (l'envoi aussi au système, pour une action
  déjà approuvée). Chaque transition écrit une entrée d'audit dans la même transaction.
- Envoi : par un ``Expediteur`` enfichable ; seul ``ExpediteurFichier`` est livré (aucun envoi réel).
  L'appel à l'expéditeur (dépôt sur une plateforme agréée, réseau) se fait **hors** de toute transaction
  (D-1323) : l'action est d'abord réservée (``reference_envoi = "envoi_en_cours:…"``, transaction courte),
  puis l'expéditeur est appelé, puis l'envoi est enregistré (transaction courte). Un second envoi pendant
  la réservation est refusé ; une réservation abandonnée (processus tué) expire après
  ``RESERVATION_ENVOI_S``.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from controldone.auth.roles import Acteur, Action, Ressource, Role, peut
from controldone.guardrails import check_text
from controldone.ids import nouvel_id
from controldone.outbox.expediteurs import Expediteur
from controldone.outbox.modele import (
    TRANSITIONS,
    ActionBloquee,
    ActionSortante,
    ModeAutonomie,
    StatutAction,
    TransitionInterdite,
    TypeAction,
)
from controldone.storage import sorties
from controldone.storage.audit import journaliser
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import Outbox

__all__ = ["RESERVATION_ENVOI_S", "FileSortante", "textes_du_contenu", "verifier_textes"]

#: Durée d'une réservation d'envoi : au-delà, elle est considérée comme abandonnée (processus tué).
RESERVATION_ENVOI_S = 900
_RESERVATION = "envoi_en_cours:"

#: Clés non textuelles (identifiants, adresses, références de pièces) exclues du contrôle de formulation.
#: ``donnees_entrantes`` : texte reçu d'un tiers et cité tel quel (question d'un client, extrait de source
#: officielle) — ce n'est pas une formulation du produit ; il n'est jamais envoyé comme notre texte.
_CLES_NON_TEXTE = frozenset({"destinataires", "cc", "pieces", "attachments", "ref", "refs", "id", "url",
                             "donnees_entrantes"})


def textes_du_contenu(contenu: Any) -> list[str]:
    """Toutes les chaînes rédigées d'un contenu (récursif), hors identifiants et références."""
    sortie: list[str] = []
    if isinstance(contenu, str):
        sortie.append(contenu)
    elif isinstance(contenu, dict):
        for k, v in contenu.items():
            if k not in _CLES_NON_TEXTE:
                sortie += textes_du_contenu(v)
    elif isinstance(contenu, list | tuple):
        for v in contenu:
            sortie += textes_du_contenu(v)
    return sortie


def verifier_textes(contenu: dict[str, Any]) -> list[str]:
    """Liste des motifs de blocage (vide si le contenu passe les garde-fous)."""
    motifs = []
    for texte in textes_du_contenu(contenu):
        for v in check_text(texte):
            motifs.append(f"formulation interdite « {v.expression} » ({v.categorie})")
    return sorted(set(motifs))


def _instantane(o: Outbox) -> ActionSortante:
    return ActionSortante(
        id=o.id, tenant_id=o.tenant_id, kind=TypeAction(o.kind), statut=StatutAction(o.statut),
        payload=dict(o.payload or {}), payload_corrige=o.payload_corrige, motif_blocage=o.motif_blocage,
        motif_refus=o.motif_refus, idempotency_key=o.idempotency_key, auto=o.auto, cree_par=o.cree_par,
        cree_le=o.cree_le, decide_par=o.decide_par, decide_le=o.decide_le, envoye_le=o.envoye_le,
        reference_envoi=o.reference_envoi,
    )


class FileSortante:
    def __init__(self, db: Database) -> None:
        self.db = db

    # --- droits ---
    @staticmethod
    def _exiger(acteur: Acteur, action: Action, tenant_id: str | None) -> None:
        if not peut(acteur, action, Ressource("outbox", tenant_id)):
            raise AccesRefuse(f"action « {action.value} » refusée pour le rôle {Role(acteur.role).value}")

    @staticmethod
    def _audit(s: Any, acteur: Acteur, o: Outbox, action: str, details: dict[str, Any] | None = None) -> None:
        journaliser(s, actor=acteur.id, role=Role(acteur.role).value, action=f"outbox_{action}",
                    tenant_id=o.tenant_id, target=f"outbox:{o.id}", ip=acteur.ip,
                    details={"kind": o.kind, "statut": o.statut, **(details or {})})

    @staticmethod
    def _transition(o: Outbox, vers: StatutAction) -> None:
        de = StatutAction(o.statut)
        if vers not in TRANSITIONS[de]:
            raise TransitionInterdite(f"transition interdite : {de.value} -> {vers.value}")
        o.statut = vers.value

    # --- autonomie ---
    def autonomie(self, kind: TypeAction | str) -> ModeAutonomie:
        with self.db.transaction_systeme() as s:
            return ModeAutonomie(sorties.autonomie(s, TypeAction(kind).value))

    def definir_autonomie(self, kind: TypeAction | str, mode: ModeAutonomie | str, acteur: Acteur) -> None:
        if Role(acteur.role) is not Role.fondateur:
            raise AccesRefuse("autonomie modifiable par le fondateur seulement")
        kind, mode = TypeAction(kind), ModeAutonomie(mode)
        with self.db.transaction_systeme() as s:
            avant = sorties.autonomie(s, kind.value)
            sorties.definir_autonomie(s, kind.value, mode.value, acteur.id)
            journaliser(s, actor=acteur.id, role=Role.fondateur.value, action="outbox_autonomie",
                        target=f"outbox_autonomie:{kind.value}", ip=acteur.ip,
                        details={"de": avant, "vers": mode.value})

    # --- cycle ---
    def proposer(self, kind: TypeAction | str, payload: dict[str, Any], acteur: Acteur, *,
                 tenant_id: str | None = None, idempotency_key: str | None = None) -> ActionSortante:
        """Crée un brouillon (idempotent par ``idempotency_key``). En mode ``auto``, il est approuvé
        aussitôt si les garde-fous passent ; sinon il reste brouillon avec le motif de blocage."""
        kind = TypeAction(kind)
        self._exiger(acteur, Action.proposer_sortie, tenant_id)
        with self.db.transaction_systeme() as s:
            if idempotency_key:
                existant = sorties.lire_par_cle(s, idempotency_key)
                if existant is not None:
                    return _instantane(existant)
            if tenant_id is not None and not sorties.client_existe(s, tenant_id):
                raise AccesRefuse("client introuvable")
            o, cree = sorties.inserer_ou_lire(s, id=nouvel_id("out"), tenant_id=tenant_id, kind=kind.value, statut="brouillon",
                                payload=payload, idempotency_key=idempotency_key, cree_par=acteur.id,
                                cree_le=maintenant())
            if not cree:  # course rattrapée : action créée entre-temps par une transaction concurrente
                return _instantane(o)
            self._audit(s, acteur, o, "proposer")
            motifs = verifier_textes(payload)
            o.motif_blocage = "; ".join(motifs) or None
            if not motifs and sorties.autonomie(s, kind.value) == ModeAutonomie.auto.value:
                self._transition(o, StatutAction.approuve)
                o.auto, o.decide_par, o.decide_le = True, "systeme:autonomie", maintenant()
                journaliser(s, actor="systeme:autonomie", role=Role.systeme.value, action="outbox_approuver_auto",
                            tenant_id=o.tenant_id, target=f"outbox:{o.id}", details={"kind": o.kind})
            s.flush()
            return _instantane(o)

    def _decider(self, action_id: str, acteur: Acteur, faire: Any) -> ActionSortante:
        """Exécute une décision du fondateur dans une transaction ; un blocage par les garde-fous est
        enregistré (motif + audit) puis signalé par ``ActionBloquee``."""
        bloque: ActionBloquee | None = None
        with self.db.transaction_systeme() as s:
            o = sorties.lire(s, action_id, verrou=True)
            if o is None:
                raise AccesRefuse("action introuvable")
            self._exiger(acteur, Action.approuver_sortie, o.tenant_id)
            try:
                return faire(s, o)
            except ActionBloquee as exc:
                bloque = exc
        raise bloque

    def _bloquer_si_besoin(self, s: Any, acteur: Acteur, o: Outbox, contenu: dict[str, Any], **details: Any) -> None:
        motifs = verifier_textes(contenu)
        if motifs:
            o.motif_blocage = "; ".join(motifs)
            self._audit(s, acteur, o, "bloque", {"motifs": len(motifs), **details})
            raise ActionBloquee(motifs)

    def approuver(self, action_id: str, acteur: Acteur) -> ActionSortante:
        def faire(s: Any, o: Outbox) -> ActionSortante:
            if StatutAction(o.statut) is not StatutAction.brouillon:
                raise TransitionInterdite(f"transition interdite : {o.statut} -> approuve")
            self._bloquer_si_besoin(s, acteur, o, o.payload)
            self._transition(o, StatutAction.approuve)
            o.decide_par, o.decide_le, o.motif_blocage = acteur.id, maintenant(), None
            self._audit(s, acteur, o, "approuver")
            return _instantane(o)

        return self._decider(action_id, acteur, faire)

    def corriger(self, action_id: str, acteur: Acteur, payload_corrige: dict[str, Any]) -> ActionSortante:
        """Approuve avec un contenu corrigé (le brouillon d'origine est conservé)."""

        def faire(s: Any, o: Outbox) -> ActionSortante:
            if StatutAction(o.statut) is not StatutAction.brouillon:
                raise TransitionInterdite(f"transition interdite : {o.statut} -> corrige")
            self._bloquer_si_besoin(s, acteur, o, payload_corrige, correction=True)
            self._transition(o, StatutAction.corrige)
            o.payload_corrige = payload_corrige
            o.decide_par, o.decide_le, o.motif_blocage = acteur.id, maintenant(), None
            self._audit(s, acteur, o, "corriger")
            return _instantane(o)

        return self._decider(action_id, acteur, faire)

    def refuser(self, action_id: str, acteur: Acteur, motif: str) -> ActionSortante:
        if not (motif and motif.strip()):
            raise ValueError("le refus exige un motif")

        def faire(s: Any, o: Outbox) -> ActionSortante:
            self._transition(o, StatutAction.refuse)
            o.motif_refus, o.decide_par, o.decide_le = motif.strip()[:1000], acteur.id, maintenant()
            self._audit(s, acteur, o, "refuser")
            return _instantane(o)

        return self._decider(action_id, acteur, faire)

    def envoyer(self, action_id: str, expediteur: Expediteur, acteur: Acteur) -> ActionSortante:
        """Envoie une action approuvée ou corrigée (garde-fous revérifiés juste avant l'envoi)."""
        # 1. réservation (transaction courte) : contrôles, garde-fous, marque « envoi en cours »
        with self.db.transaction_systeme() as s:
            o = sorties.lire(s, action_id, verrou=True)
            if o is None:
                raise AccesRefuse("action introuvable")
            self._exiger(acteur, Action.envoyer_sortie, o.tenant_id)
            if StatutAction(o.statut) not in (StatutAction.approuve, StatutAction.corrige):
                raise TransitionInterdite(f"envoi interdit depuis le statut {o.statut}")
            if _reservation_active(o.reference_envoi):
                raise TransitionInterdite("envoi déjà en cours pour cette action")
            instant = _instantane(o)
            motifs = verifier_textes(instant.payload_effectif)
            if motifs:
                raise ActionBloquee(motifs)
            marque = f"{_RESERVATION}{secrets.token_hex(8)}:{maintenant().isoformat()}"
            o.reference_envoi = marque
        # 2. appel de l'expéditeur **hors transaction** : aucun verrou d'écriture tenu pendant un appel réseau
        try:
            reference = expediteur.envoyer(instant)
        except BaseException:
            with self.db.transaction_systeme() as s:
                o = sorties.lire(s, action_id, verrou=True)
                if o is not None and o.reference_envoi == marque:
                    o.reference_envoi = None  # réservation levée : l'envoi pourra être retenté
            raise
        # 3. enregistrement (transaction courte)
        with self.db.transaction_systeme() as s:
            o = sorties.lire(s, action_id, verrou=True)
            if o is None:
                raise AccesRefuse("action introuvable")
            if StatutAction(o.statut) is StatutAction.envoye:  # réservation expirée et reprise ailleurs
                self._audit(s, acteur, o, "envoyer_doublon", {"reference": reference[:200]})
                return _instantane(o)
            self._transition(o, StatutAction.envoye)
            o.envoye_le, o.reference_envoi = maintenant(), reference[:500]
            self._audit(s, acteur, o, "envoyer", {"expediteur": getattr(expediteur, "nom", "?")})
            return _instantane(o)

    def envoyer_approuves(self, expediteur: Expediteur, acteur: Acteur) -> list[ActionSortante]:
        return [self.envoyer(a.id, expediteur, acteur) for a in self.lister(acteur, statuts=["approuve", "corrige"])]

    def par_cle(self, idempotency_key: str, acteur: Acteur) -> ActionSortante | None:
        """Action d'une clé d'idempotence (fondateur et système)."""
        if Role(acteur.role) not in (Role.fondateur, Role.systeme):
            raise AccesRefuse("réservé au fondateur et au système")
        with self.db.transaction_systeme() as s:
            o = sorties.lire_par_cle(s, idempotency_key)
            return _instantane(o) if o is not None else None

    def remplacer_brouillon(self, action_id: str, payload: dict[str, Any], acteur: Acteur, *, motif: str) -> ActionSortante:
        """Remplace le contenu d'un **brouillon** par une source qui fait foi (ex. paiement Stripe reçu pour
        une échéance déjà proposée par un agent, F-08). Refusé hors ``brouillon`` ; garde-fous revérifiés ;
        journalisé (``outbox_remplacer``)."""
        self._exiger(acteur, Action.proposer_sortie, None)
        with self.db.transaction_systeme() as s:
            o = sorties.lire(s, action_id, verrou=True)
            if o is None:
                raise AccesRefuse("action introuvable")
            if o.statut != StatutAction.brouillon.value:
                raise TransitionInterdite("seul un brouillon peut être remplacé")
            o.payload = payload
            motifs = verifier_textes(payload)
            o.motif_blocage = "; ".join(motifs) or None
            self._audit(s, acteur, o, "remplacer", {"motif": motif[:200]})
            s.flush()
            return _instantane(o)

    # --- lecture ---
    def obtenir(self, action_id: str, acteur: Acteur) -> ActionSortante:
        with self.db.transaction_systeme() as s:
            o = sorties.lire(s, action_id)
            client = Role(acteur.role) not in (Role.fondateur, Role.systeme)
            if (o is None or not peut(acteur, Action.lire, Ressource("outbox", o.tenant_id))
                    or (client and o.statut != StatutAction.envoye.value)):
                raise AccesRefuse("introuvable ou hors périmètre")
            return _instantane(o)

    def lister(self, acteur: Acteur, *, statuts: list[str] | None = None, kind: str | None = None,
               tenant_id: str | None = None) -> list[ActionSortante]:
        """Fondateur et système : toute la file ; rôle client : les actions de son client seulement."""
        if Role(acteur.role) in (Role.fondateur, Role.systeme):
            filtre_tenant = tenant_id
        else:
            if acteur.tenant_id is None or (tenant_id and tenant_id != acteur.tenant_id):
                raise AccesRefuse("hors périmètre")
            filtre_tenant = acteur.tenant_id
        with self.db.transaction_systeme() as s:
            lignes = sorties.lister(s, statuts=statuts, kind=kind, tenant_id=filtre_tenant)
            client = Role(acteur.role) not in (Role.fondateur, Role.systeme)
            return [_instantane(o) for o in lignes
                    if peut(acteur, Action.lire, Ressource("outbox", o.tenant_id))
                    and not (client and o.statut != StatutAction.envoye.value)]


def _reservation_active(reference: str | None) -> bool:
    """Vrai si ``reference`` est une réservation d'envoi de moins de ``RESERVATION_ENVOI_S`` secondes."""
    if not reference or not reference.startswith(_RESERVATION):
        return False
    from datetime import datetime

    try:  # « envoi_en_cours:<jeton>:<horodatage ISO> »
        depuis = datetime.fromisoformat(reference[len(_RESERVATION):].split(":", 1)[1])
    except (IndexError, ValueError):
        return False
    return maintenant() - depuis < timedelta(seconds=RESERVATION_ENVOI_S)
