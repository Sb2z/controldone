"""Registre de recouvrement (SPEC §17) et dossier de réclamation rédigé pour le client (§17.3).

- ``registre`` : écarts à recouvrer du client (constats validés ``recouvrable``), âge depuis la réclamation,
  relances suggérées à 30, 60 et 90 jours, événements append-only ;
- ``declarer_envoi`` : le **client** déclare avoir envoyé lui-même sa réclamation (``ouvert`` -> ``reclame``) ;
- ``enregistrer_avoir`` : avoir reçu (montant, référence) -> ``partiellement_credite`` ou ``credite`` ;
- ``preparer_dossier`` (fondateur) : dossier de réclamation **au nom du client** (première personne, entité
  du client en expéditeur, aucune mention du prestataire, aucune signature autre que celle à compléter par le
  client), en texte et en PDF ; garde-fous §3.2 ; proposé dans la file des sorties (``reclamation_dossier``)
  pour validation par le fondateur avant mise à disposition. Le système n'envoie **jamais** rien au
  transitaire.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from controldone.auth.roles import Acteur, Action, Role
from controldone.model.enums import Composante, StatutEcart
from controldone.model.recouvrement import ErreurTransition, PieceRecouvrement
from controldone.rapport.vue import LIBELLES_COMPOSANTE
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide, exiger
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import Constat, Dossier, Ecart, EvenementRecouvrement, Transitaire
from controldone.storage.scope import TenantScope

__all__ = ["LIBELLES_STATUT_ECART", "LigneRegistre", "declarer_envoi", "enregistrer_avoir", "preparer_dossier",
           "registre"]

LIBELLES_STATUT_ECART = {
    "ouvert": "Ouvert", "reclame": "Réclamé", "partiellement_credite": "Partiellement crédité",
    "credite": "Crédité", "conteste": "Contesté", "abandonne": "Abandonné",
}
RELANCES = (30, 60, 90)
MONTANT_AVOIR_MAX = Decimal("1000000000")


@dataclass
class LigneRegistre:
    id: str
    constat_id: str
    dossier_id: str | None
    dossier_reference: str | None
    transitaire: str
    transitaire_id: str | None
    composante: str
    niveau: str | None
    mrn: str | None
    montant_initial: Decimal
    montant_credite: Decimal
    reste: Decimal
    statut: str
    statut_code: str
    age_jours: int | None
    relance: str | None
    evenements: list[dict[str, Any]]

    def en_dict(self) -> dict[str, Any]:
        return {"litige_id": self.id, "constat_id": self.constat_id, "dossier_id": self.dossier_id,
                "dossier_reference": self.dossier_reference, "transitaire": self.transitaire,
                "composante": self.composante, "niveau": self.niveau, "mrn": self.mrn,
                "montant_initial_eur": str(self.montant_initial), "montant_credite_eur": str(self.montant_credite),
                "reste_eur": str(self.reste), "statut": self.statut_code, "age_jours": self.age_jours,
                "relance_suggeree": self.relance, "evenements": self.evenements,
                "nature": "écart constaté entre documents ; ne préjuge pas des sommes légalement dues"}


def _relance(age: int | None, statut: str) -> str | None:
    if age is None or statut not in ("reclame", "partiellement_credite", "conteste"):
        return None
    passees = [j for j in RELANCES if age >= j]
    return f"relance suggérée ({passees[-1]} jours)" if passees else None


def registre(scope: TenantScope, *, ecart_id: str | None = None) -> list[LigneRegistre]:
    """Écarts du client dont le constat est visible par l'acteur (rôle client : constats publiés)."""
    visibles = {c.id: c for c in scope.lister(Constat)}
    transitaires = {t.id: t.nom for t in scope.lister(Transitaire)}
    references = {d.id: d.reference or d.id for d in scope.lister(Dossier)}
    lignes = [scope.obtenir(Ecart, ecart_id)] if ecart_id else scope.lister(Ecart, ordre=Ecart.modifie_le)
    maintenant = datetime.now(UTC)
    out = []
    for e in lignes:
        if e.constat_id not in visibles:
            if ecart_id:
                raise AccesRefuse("introuvable ou hors périmètre")
            continue
        j = e.contenu or {}
        reclame_le = j.get("reclame_le")
        age = None
        if reclame_le:
            try:
                age = (maintenant - datetime.fromisoformat(reclame_le.replace("Z", "+00:00"))).days
            except ValueError:
                age = None
        evts = [{"de": v.de, "vers": v.vers, "le": v.le.isoformat() if v.le else None,
                 "montant": str(v.montant) if v.montant is not None else None,
                 "commentaire": (v.contenu or {}).get("commentaire"),
                 "piece": ((v.contenu or {}).get("piece") or {}).get("autre")}
                for v in scope.lister(EvenementRecouvrement, ecart_id=e.id, ordre=EvenementRecouvrement.le)]
        try:
            comp = LIBELLES_COMPOSANTE.get(Composante(j.get("composante")), j.get("composante") or "—")
        except ValueError:
            comp = j.get("composante") or "—"
        out.append(LigneRegistre(
            id=e.id, constat_id=e.constat_id, dossier_id=j.get("dossier_id"),
            dossier_reference=references.get(j.get("dossier_id") or ""),
            transitaire=transitaires.get(e.transitaire_id or "", e.transitaire_id or "transitaire non identifié"),
            transitaire_id=e.transitaire_id, composante=comp, niveau=visibles[e.constat_id].niveau, mrn=j.get("mrn"),
            montant_initial=e.montant_initial, montant_credite=Decimal(str(j.get("montant_credite") or "0")),
            reste=e.reste, statut=LIBELLES_STATUT_ECART.get(e.statut, e.statut), statut_code=e.statut,
            age_jours=age, relance=_relance(age, e.statut), evenements=evts))
    return out


def declarer_envoi(scope: TenantScope, ecart_id: str, commentaire: str | None = None) -> None:
    """Le client déclare avoir envoyé lui-même la réclamation (§17.1)."""
    exiger(scope.actor, Action.declarer_recouvrement, scope.tenant_id)
    registre(scope, ecart_id=ecart_id)  # visibilité du constat
    try:
        scope.transitionner_ecart(ecart_id, StatutEcart.reclame, commentaire=(commentaire or "").strip()[:500] or None)
    except ErreurTransition as exc:
        raise RequeteInvalide(str(exc)) from exc


def enregistrer_avoir(scope: TenantScope, ecart_id: str, montant: Decimal, reference: str | None = None,
                      commentaire: str | None = None) -> None:
    """Avoir reçu du transitaire : crédite l'écart (partiellement ou totalement)."""
    exiger(scope.actor, Action.declarer_recouvrement, scope.tenant_id)
    ligne = registre(scope, ecart_id=ecart_id)[0]
    # NaN, infini ou valeur démesurée : refus propre (et non une erreur 500 à la comparaison ou à l'arrondi, RS-08)
    if not isinstance(montant, Decimal) or not montant.is_finite() or montant > MONTANT_AVOIR_MAX:
        raise RequeteInvalide("montant de l'avoir invalide")
    if montant <= 0:
        raise RequeteInvalide("le montant de l'avoir doit être positif")
    vers = StatutEcart.credite if montant >= ligne.reste else StatutEcart.partiellement_credite
    piece = PieceRecouvrement(autre=(reference or "").strip()[:200] or None)
    try:
        scope.transitionner_ecart(ecart_id, vers, montant=montant.quantize(Decimal("0.01")), piece=piece,
                                  commentaire=(commentaire or "").strip()[:500] or None)
    except ErreurTransition as exc:
        raise RequeteInvalide(str(exc)) from exc


# --- dossier de réclamation (§17.3) ---------------------------------------------------------------------


def preparer_dossier(plateforme: Plateforme, fondateur: Acteur, tenant_id: str, transitaire_id: str) -> str:
    """Prépare **et valide** (décision du fondateur) le dossier de demande d'avoir d'un transitaire, rédigé au
    nom du client par ``controldone.litiges`` (D-600, D-601) ; le brouillon ``reclamation_dossier`` attend
    ensuite l'approbation dans la file de validation (mise à disposition du client). Renvoie l'action."""
    from controldone.litiges import ServiceLitiges

    if fondateur.role is not Role.fondateur:
        raise Interdit("préparation réservée au fondateur")
    service = ServiceLitiges(plateforme.db, vault=plateforme.vault)
    try:
        d = service.preparer(fondateur, tenant_id, transitaire_id)
    except ValueError as exc:
        raise RequeteInvalide("aucun écart validé à demander pour ce transitaire") from exc
    d = service.valider(fondateur, tenant_id, d.id)
    return d.outbox_mise_a_disposition or ""
