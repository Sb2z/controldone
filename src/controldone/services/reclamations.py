"""Suivi des avoirs reçus (SPEC §17) et relevé d'écarts remis au client (§17.3, brief juridique §1.3).

Vocabulaire (D-1315) : « relevé d'écarts » (et non « dossier de réclamation »), « suivi des avoirs reçus »
(et non « recouvrement »). Les noms techniques (``litiges``, ``reclame``, ``reclamation_dossier``,
``litige_id``…) restent inchangés pour la compatibilité de l'API.

- ``registre`` : écarts du client (constats validés ``recouvrable``), âge depuis l'envoi déclaré, rappels
  internes suggérés aux échéances ``reglages["relances_jours"]`` (défaut ``litiges.RELANCES_DEFAUT`` :
  J+15, J+30, J+45 — la même source que la planification du service des litiges, D-1317), événements
  append-only ;
- ``declarer_envoi_releve`` / ``enregistrer_avoir_recu`` : **façades** sur ``ServiceLitiges`` (D-1317) —
  quand l'écart appartient à un relevé, le cycle complet s'applique (relances planifiées, imputation
  déterministe, commission sur la base HT des avoirs de transitaire, brouillon de facture) ; sinon,
  transition directe de l'écart. Elles ouvrent leurs propres transactions (à appeler **hors** périmètre) ;
- ``declarer_envoi`` / ``enregistrer_avoir`` (dans un périmètre ouvert) : transition directe (compatibilité) ;
- ``preparer_dossier`` (fondateur) : relevé d'écarts + modèle de courrier neutre « à adapter par le client »
  (``litiges.redaction``), proposé dans la file des sorties (``reclamation_dossier``) pour validation avant
  mise à disposition. Le système n'envoie **jamais** rien au transitaire.
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

__all__ = ["LIBELLES_STATUT_ECART", "LigneRegistre", "declarer_envoi", "declarer_envoi_releve", "enregistrer_avoir",
           "enregistrer_avoir_recu", "jours_relance", "preparer_dossier", "registre"]

LIBELLES_STATUT_ECART = {
    "ouvert": "Ouvert", "reclame": "Relevé envoyé par le client", "partiellement_credite": "Avoir partiel reçu",
    "credite": "Avoir reçu", "conteste": "Contesté par le transitaire", "abandonne": "Abandonné",
}
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
                "relance_suggeree": self.relance, "rappel_suggere": self.relance, "evenements": self.evenements,
                "ecart_id": self.id, "statut_libelle": self.statut,
                "nature": "écart constaté entre documents ; ne préjuge pas des sommes légalement dues"}


def jours_relance(reglages: dict[str, Any] | None) -> tuple[int, ...]:
    """Échéances des rappels internes (jours après l'envoi déclaré) : ``reglages["relances_jours"]``, sinon
    ``litiges.RELANCES_DEFAUT``. Source unique de l'affichage et de la planification (D-1317)."""
    from controldone.litiges import RELANCES_DEFAUT

    brut = (reglages or {}).get("relances_jours") or RELANCES_DEFAUT
    try:
        jours = sorted({int(x) for x in brut if int(x) > 0})
    except (TypeError, ValueError):
        jours = list(RELANCES_DEFAUT)
    return tuple(jours) or tuple(RELANCES_DEFAUT)


def _relance(age: int | None, statut: str, jours: tuple[int, ...] | None = None) -> str | None:
    if age is None or statut not in ("reclame", "partiellement_credite", "conteste"):
        return None
    passees = [j for j in (jours or jours_relance(None)) if age >= j]
    return f"rappel suggéré ({passees[-1]} jours)" if passees else None


def registre(scope: TenantScope, *, ecart_id: str | None = None,
             ecart_ids: list[str] | None = None) -> list[LigneRegistre]:
    """Écarts du client dont le constat est visible par l'acteur (rôle client : constats publiés).

    ``ecart_ids`` : seulement ces écarts, dans cet ordre (page d'une liste filtrée en SQL, D-3801) ; les
    constats, dossiers et événements lus sont alors limités à ceux de la page."""
    jours = jours_relance(scope.client().reglages)
    transitaires = {t.id: t.nom for t in scope.lister(Transitaire)}
    if ecart_ids is not None:
        par_id = {e.id: e for e in scope.session.execute(
            scope.requete(Ecart).where(Ecart.id.in_(ecart_ids))).scalars()}
        lignes = [par_id[i] for i in ecart_ids if i in par_id]
        visibles = {c.id: c for c in scope.session.execute(
            scope.requete(Constat).where(Constat.id.in_([e.constat_id for e in lignes]))).scalars()}
        ids_dossiers = [str((e.contenu or {}).get("dossier_id") or "") for e in lignes]
        references = {d.id: d.reference or d.id for d in scope.session.execute(
            scope.requete(Dossier).where(Dossier.id.in_(ids_dossiers))).scalars()}
    else:
        visibles = {c.id: c for c in scope.lister(Constat)}
        references = {d.id: d.reference or d.id for d in scope.lister(Dossier)}
        lignes = [scope.obtenir(Ecart, ecart_id)] if ecart_id else scope.lister(Ecart, ordre=Ecart.modifie_le)
    # événements de toutes les lignes en une requête (et non une par écart)
    evenements: dict[str, list[Any]] = {}
    ids_lignes = [e.id for e in lignes if e.constat_id in visibles]
    for i in range(0, len(ids_lignes), 500):
        q = (scope.requete(EvenementRecouvrement)
             .where(EvenementRecouvrement.ecart_id.in_(ids_lignes[i:i + 500]))
             .order_by(EvenementRecouvrement.le))
        for v in scope.session.execute(q).scalars():
            evenements.setdefault(v.ecart_id, []).append(v)
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
                for v in evenements.get(e.id, [])]
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
            age_jours=age, relance=_relance(age, e.statut, jours), evenements=evts))
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


# --- façades sur le service des litiges (P0-1, D-1317) ---------------------------------------------------

def _nature(composante: str | None) -> Any:
    from controldone.model.enums import NatureLigne

    return {
        "droit": NatureLigne.debours_droits, "autre_taxe": NatureLigne.debours_autres_taxes,
        "tva": NatureLigne.debours_tva, "forfait_petits_envois": NatureLigne.debours_forfait_petits_envois,
    }.get(composante or "", NatureLigne.autre_prestation)


def _contexte_ecart(plateforme: Plateforme, acteur: Acteur, ecart_id: str) -> tuple[LigneRegistre, dict[str, Any],
                                                                                    str | None, str | None]:
    """(ligne visible, contenu de l'écart, relevé contenant l'écart, statut du relevé) — lecture seule."""
    from controldone.storage.models import Reclamation

    with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:  # type: ignore[arg-type]
        ligne = registre(scope, ecart_id=ecart_id)[0]
        contenu = dict(scope.obtenir(Ecart, ecart_id).contenu or {})
        rec_id = contenu.get("reclamation_id")
        statut = None
        if rec_id:
            try:
                statut = (scope.obtenir(Reclamation, rec_id).contenu or {}).get("statut")
            except AccesRefuse:
                rec_id = None
        return ligne, contenu, rec_id, statut


def declarer_envoi_releve(plateforme: Plateforme, acteur: Acteur, ecart_id: str,
                          commentaire: str | None = None) -> None:
    """Le client déclare avoir envoyé lui-même son courrier (web, API, MCP). Écart rattaché à un relevé validé
    -> ``ServiceLitiges.declarer_envoi`` (tout le relevé passe ``reclame`` ; rappels planifiés) ; sinon
    transition directe de l'écart."""
    from controldone.litiges import ServiceLitiges
    from controldone.litiges.etats import StatutReclamation

    exiger(acteur, Action.declarer_recouvrement, acteur.tenant_id)
    _ligne, _contenu, rec_id, statut = _contexte_ecart(plateforme, acteur, ecart_id)
    if rec_id and statut in (StatutReclamation.valide.value, StatutReclamation.conteste.value):
        service = ServiceLitiges(plateforme.db, vault=plateforme.vault)
        try:
            if statut == StatutReclamation.conteste.value:
                service.reprendre(acteur, acteur.tenant_id, rec_id)  # type: ignore[arg-type]
            else:
                service.declarer_envoi(acteur, acteur.tenant_id, rec_id)  # type: ignore[arg-type]
            return
        except ValueError:
            pass  # transition du relevé impossible : repli sur l'écart seul
    with plateforme.db.tenant(acteur.tenant_id, acteur) as scope:  # type: ignore[arg-type]
        declarer_envoi(scope, ecart_id, commentaire)


def enregistrer_avoir_recu(plateforme: Plateforme, acteur: Acteur, ecart_id: str, montant: Decimal,
                           reference: str | None = None, commentaire: str | None = None, *,
                           origine: str = "transitaire", montant_tva: Decimal | None = None) -> dict[str, Any]:
    """Avoir reçu, déclaré sur un écart (montant **hors taxes**). Écart rattaché à un relevé ->
    ``ServiceLitiges.enregistrer_avoir`` : imputation déterministe, transitions, commission (base HT, avoirs de
    transitaire seulement) et brouillon ``facture_emise`` ; sinon transition directe. Renvoie un résumé."""
    import hashlib

    from controldone.litiges import AvoirRecu, ServiceLitiges
    from controldone.litiges.commission import ORIGINES_CREDIT

    exiger(acteur, Action.declarer_recouvrement, acteur.tenant_id)
    if not isinstance(montant, Decimal) or not montant.is_finite() or montant > MONTANT_AVOIR_MAX:
        raise RequeteInvalide("montant de l'avoir invalide")
    if montant <= 0:
        raise RequeteInvalide("le montant de l'avoir doit être positif")
    if origine not in ORIGINES_CREDIT:
        raise RequeteInvalide("origine : transitaire ou administration")
    ligne, contenu, rec_id, _statut = _contexte_ecart(plateforme, acteur, ecart_id)
    montant = montant.quantize(Decimal("0.01"))
    if rec_id and ligne.transitaire_id:
        ref = (reference or "").strip()[:200] or None
        graine = f"{acteur.tenant_id}\x1f{ecart_id}\x1f{ref or ''}\x1f{montant}"
        if ref is None:  # sans numéro, deux saisies identiques restent deux avoirs distincts
            from controldone.ids import nouvel_id

            graine += "\x1f" + nouvel_id("avr")
        avoir_id = "avr_" + hashlib.sha256(graine.encode()).hexdigest()[:24]
        avoir = AvoirRecu.declare(
            avoir_id, ligne.transitaire_id, {_nature(contenu.get("composante")): montant}, numero=ref,
            factures_origine=[f for f in [_facture_ecart(plateforme, acteur, rec_id, ecart_id)] if f],
            mrns=[ligne.mrn] if ligne.mrn else [], origine=origine, montant_tva=montant_tva)
        res = ServiceLitiges(plateforme.db, vault=plateforme.vault).enregistrer_avoir(
            acteur, acteur.tenant_id, avoir)  # type: ignore[arg-type]
        if res.deja_traite or res.imputations:
            return {"voie": "litiges", "avoir_id": avoir_id, "deja_traite": res.deja_traite,
                    "impute": str(sum(res.imputations.values(), Decimal("0.00"))),
                    "commission": str(res.commission), "facture_commission": res.outbox_facture}
    with plateforme.db.tenant(acteur.tenant_id, acteur) as scope:  # type: ignore[arg-type]
        enregistrer_avoir(scope, ecart_id, montant, reference,
                          ((commentaire or "") + (" (remboursement d'une administration)"
                                                  if origine != "transitaire" else "")).strip() or None)
    return {"voie": "directe", "impute": str(min(montant, ligne.reste))}


def _facture_ecart(plateforme: Plateforme, acteur: Acteur, rec_id: str, ecart_id: str) -> str | None:
    from controldone.litiges import DossierReclamation
    from controldone.storage.models import Reclamation

    with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:  # type: ignore[arg-type]
        try:
            d = DossierReclamation.model_validate(scope.obtenir(Reclamation, rec_id).contenu)
        except AccesRefuse:
            return None
    return next((x.facture for x in d.lignes if x.ecart_id == ecart_id), None)


# --- relevé d'écarts (§17.3) ------------------------------------------------------------------------------


def preparer_dossier(plateforme: Plateforme, fondateur: Acteur, tenant_id: str, transitaire_id: str) -> str:
    """Prépare **et valide** (décision du fondateur) le relevé d'écarts d'un transitaire et son modèle de
    courrier à adapter par le client (``controldone.litiges``, D-1315) ; le brouillon ``reclamation_dossier``
    attend ensuite l'approbation dans la file de validation (mise à disposition du client). Renvoie l'action."""
    from controldone.litiges import ServiceLitiges

    if fondateur.role is not Role.fondateur:
        raise Interdit("préparation réservée au fondateur")
    service = ServiceLitiges(plateforme.db, vault=plateforme.vault)
    try:
        d = service.preparer(fondateur, tenant_id, transitaire_id)
    except ValueError as exc:
        raise RequeteInvalide("aucun écart validé à présenter pour ce transitaire") from exc
    d = service.valider(fondateur, tenant_id, d.id)
    return d.outbox_mise_a_disposition or ""
