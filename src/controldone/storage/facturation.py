"""Persistance de la facturation du fondateur : numérotation continue, factures immuables, événements de
paiement, comptes de paiement, coupons, statuts de plateforme agréée, et lectures agrégées (coûts IA).

Numérotation (``emettre_numerotee``) : dans **une** transaction d'écriture (SQLite : ``BEGIN IMMEDIATE``,
un seul écrivain ; PostgreSQL : ``SELECT … FOR UPDATE`` sur le compteur), on lit le compteur de la série
(entité légale, préfixe, année), on construit la facture (XML, PDF) avec le numéro suivant, on l'insère
et on avance le compteur. Si la construction échoue, la transaction est annulée : le numéro n'est pas
consommé (pas de trou). Les dates d'émission d'une série sont croissantes (chronologie).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controldone.storage.audit import journaliser
from controldone.storage.db import Database
from controldone.storage.models import AiUsage, Tenant
from controldone.storage.models_facturation import (
    ComptePaiement,
    CompteurFacture,
    CouponUtilisation,
    EvenementPaiement,
    FactureEmise,
    StatutFacturePA,
)

__all__ = [
    "ChronologieRompue",
    "CouponIndisponible",
    "UsageIA",
    "alerte_fondateur",
    "client_par_customer",
    "clients_facturation",
    "compte_paiement",
    "coupon_utilisations",
    "couts_ia",
    "emettre_numerotee",
    "enregistrer_compte_paiement",
    "enregistrer_evenement",
    "enregistrer_statut_pa",
    "evenements_paiement",
    "facture",
    "facture_par_numero",
    "facture_par_outbox",
    "factures",
    "lire_client_facturation",
    "statuts_pa",
]


class ChronologieRompue(ValueError):
    """Date d'émission antérieure à celle de la dernière facture de la série."""


class CouponIndisponible(ValueError):
    """Coupon épuisé ou déjà utilisé par ce client (vérifié dans la transaction d'émission)."""


@dataclass(frozen=True)
class UsageIA:
    client_id: str
    mois: str
    dossier_id: str | None
    cout_eur: Decimal


def _compteur(s: Session, emetteur: str, serie: str, annee: int) -> CompteurFacture:
    q = select(CompteurFacture).where(CompteurFacture.emetteur == emetteur, CompteurFacture.serie == serie,
                                      CompteurFacture.annee == annee).with_for_update()
    c = s.execute(q).scalar_one_or_none()
    if c is None:
        c = CompteurFacture(emetteur=emetteur, serie=serie, annee=annee, dernier=0)
        with s.begin_nested():
            s.add(c)
        c = s.execute(q).scalar_one()
    return c


def emettre_numerotee(db: Database, *, emetteur: str, serie: str, date_emission: date, chiffres: int,
                      construire: Callable[[str], dict[str, Any]], acteur_id: str, acteur_role: str,
                      outbox_id: str | None = None, coupon: dict[str, Any] | None = None,
                      essais: int = 5, verifier: Callable[[Session], None] | None = None) -> FactureEmise:
    """Attribue le numéro suivant de la série et insère la facture construite par ``construire(numero)``
    (qui renvoie les colonnes de ``FactureEmise`` hors numérotation). Idempotent par ``outbox_id``.

    ``coupon`` = ``{"code", "client_id", "utilisations_max", "une_fois_par_client", "consentement"}`` :
    le coupon est consommé dans la même transaction (quota revérifié sous verrou)."""
    annee = date_emission.year
    for essai in range(essais):
        try:
            with db.transaction_systeme() as s:
                if outbox_id:
                    deja = s.execute(select(FactureEmise).where(FactureEmise.outbox_id == outbox_id)).scalar_one_or_none()
                    if deja is not None:
                        return deja
                c = _compteur(s, emetteur, serie, annee)  # verrou de la série
                if verifier is not None:
                    verifier(s)  # contrôles revérifiés sous le verrou (cumul des avoirs…)
                if c.derniere_date is not None and date_emission < c.derniere_date:
                    raise ChronologieRompue(f"date d'émission {date_emission} antérieure à la dernière facture "
                                            f"de la série ({c.derniere_date})")
                sequence = c.dernier + 1
                numero = f"{serie}-{annee}-{sequence:0{chiffres}d}"
                champs = construire(numero)
                f = FactureEmise(emetteur=emetteur, serie=serie, annee=annee, sequence=sequence, numero=numero,
                                 date_emission=date_emission, outbox_id=outbox_id, cree_par=acteur_id, **champs)
                s.add(f)
                c.dernier, c.derniere_date = sequence, date_emission
                if coupon:
                    n = s.execute(select(func.count()).select_from(CouponUtilisation)
                                  .where(CouponUtilisation.code == coupon["code"])).scalar_one()
                    if n >= int(coupon["utilisations_max"]):
                        raise CouponIndisponible("coupon épuisé")
                    if coupon.get("une_fois_par_client", True) and s.execute(
                            select(CouponUtilisation.id).where(CouponUtilisation.code == coupon["code"],
                                                               CouponUtilisation.client_id == coupon["client_id"])
                    ).first() is not None:
                        raise CouponIndisponible("coupon déjà utilisé par ce client")
                    s.add(CouponUtilisation(code=coupon["code"], client_id=coupon["client_id"], facture_id=f.id,
                                            consentement=dict(coupon.get("consentement") or {})))
                s.flush()
                journaliser(s, actor=acteur_id, role=acteur_role, action="facture_emise", tenant_id=f.client_id,
                            target=f"factures:{f.id}",
                            details={"numero": numero, "type": f.type_code, "total_ttc": str(f.total_ttc)})
                return f
        except IntegrityError:
            # course à la création du compteur (PostgreSQL) ou au numéro : on recommence proprement
            if essai == essais - 1:
                raise
    raise RuntimeError("numérotation impossible")  # pragma: no cover


def cumul_avoirs(s: Session, facture_id: str) -> Decimal:
    """Somme HT (positive) des avoirs émis sur une facture, lue dans la transaction ``s``."""
    montants = s.execute(select(FactureEmise.total_ht).where(FactureEmise.facture_origine_id == facture_id)).scalars()
    return sum((abs(Decimal(m)) for m in montants), Decimal("0.00"))


def facture(db: Database, facture_id: str) -> FactureEmise | None:
    with db.transaction_systeme() as s:
        return s.get(FactureEmise, facture_id)


def facture_par_outbox(db: Database, outbox_id: str) -> FactureEmise | None:
    with db.transaction_systeme() as s:
        return s.execute(select(FactureEmise).where(FactureEmise.outbox_id == outbox_id)).scalar_one_or_none()


def facture_par_numero(db: Database, numero: str, emetteur: str | None = None) -> FactureEmise | None:
    with db.transaction_systeme() as s:
        q = select(FactureEmise).where(FactureEmise.numero == numero)
        if emetteur:
            q = q.where(FactureEmise.emetteur == emetteur)
        return s.execute(q).scalars().first()


def factures(db: Database, *, client_id: str | None = None, emetteur: str | None = None) -> list[FactureEmise]:
    with db.transaction_systeme() as s:
        q = select(FactureEmise).order_by(FactureEmise.emetteur, FactureEmise.serie, FactureEmise.annee,
                                          FactureEmise.sequence)
        if client_id:
            q = q.where(FactureEmise.client_id == client_id)
        if emetteur:
            q = q.where(FactureEmise.emetteur == emetteur)
        return list(s.execute(q).scalars())


# --- coupons ---------------------------------------------------------------------------------------------


def coupon_utilisations(db: Database, code: str) -> list[CouponUtilisation]:
    with db.transaction_systeme() as s:
        return list(s.execute(select(CouponUtilisation).where(CouponUtilisation.code == code)).scalars())


# --- paiements --------------------------------------------------------------------------------------------


def enregistrer_evenement(db: Database, **champs: Any) -> bool:
    """Insère l'événement de paiement ; ``False`` s'il a déjà été traité (même identifiant)."""
    with db.transaction_systeme() as s:
        if s.get(EvenementPaiement, champs["id"]) is not None:
            return False
        try:
            with s.begin_nested():
                s.add(EvenementPaiement(**champs))
        except IntegrityError:
            return False
        journaliser(s, actor=f"systeme:paiement:{champs.get('fournisseur', '?')}", role="systeme",
                    action="paiement_evenement", tenant_id=champs.get("client_id"),
                    target=f"evenements_paiement:{champs['id'][:100]}",
                    details={"type": champs.get("type"), "montant": str(champs.get("montant"))})
        return True


def evenements_paiement(db: Database, *, client_id: str | None = None) -> list[EvenementPaiement]:
    with db.transaction_systeme() as s:
        q = select(EvenementPaiement).order_by(EvenementPaiement.le, EvenementPaiement.id)
        if client_id:
            q = q.where(EvenementPaiement.client_id == client_id)
        return list(s.execute(q).scalars())


def compte_paiement(db: Database, client_id: str) -> ComptePaiement | None:
    with db.transaction_systeme() as s:
        return s.get(ComptePaiement, client_id)


def client_par_customer(db: Database, customer_id: str) -> str | None:
    with db.transaction_systeme() as s:
        return s.execute(select(ComptePaiement.client_id)
                         .where(ComptePaiement.customer_id == customer_id)).scalar_one_or_none()


def enregistrer_compte_paiement(db: Database, client_id: str, *, fournisseur: str, **champs: Any) -> ComptePaiement:
    autorises = {"customer_id", "abonnement_id", "palier", "statut_abonnement"}
    if not champs.keys() <= autorises:
        raise ValueError(f"champs inconnus : {sorted(champs.keys() - autorises)}")
    with db.transaction_systeme() as s:
        c = s.get(ComptePaiement, client_id)
        if c is None:
            c = ComptePaiement(client_id=client_id, fournisseur=fournisseur)
            s.add(c)
        c.fournisseur = fournisseur
        for k, v in champs.items():
            if v is not None:
                setattr(c, k, v)
        s.flush()
        return c


# --- statuts de plateforme agréée --------------------------------------------------------------------------


def enregistrer_statut_pa(db: Database, **champs: Any) -> bool:
    with db.transaction_systeme() as s:
        existe = s.execute(select(StatutFacturePA.id).where(
            StatutFacturePA.identifiant_pa == champs["identifiant_pa"], StatutFacturePA.code == champs["code"],
            StatutFacturePA.horodatage == champs["horodatage"])).first()
        if existe is not None:
            return False
        s.add(StatutFacturePA(**champs))
        return True


def statuts_pa(db: Database, *, facture_id: str | None = None) -> list[StatutFacturePA]:
    with db.transaction_systeme() as s:
        q = select(StatutFacturePA).order_by(StatutFacturePA.id)
        if facture_id:
            q = q.where(StatutFacturePA.facture_id == facture_id)
        return list(s.execute(q).scalars())


# --- lectures transversales (fondateur, tracées) -------------------------------------------------------------


def lire_client_facturation(db: Database, client_id: str) -> tuple[str, str, dict[str, Any]] | None:
    """``(raison sociale, offre, réglages)`` d'un client (table plateforme ``tenants``)."""
    with db.transaction_systeme() as s:
        t = s.get(Tenant, client_id)
        return None if t is None else (t.raison_sociale, t.offre, dict(t.reglages or {}))


def clients_facturation(db: Database) -> dict[str, str]:
    """Identifiant -> raison sociale de tous les clients (actifs ou non)."""
    with db.transaction_systeme() as s:
        return dict(s.execute(select(Tenant.id, Tenant.raison_sociale).order_by(Tenant.id)).all())


def couts_ia(db: Database, *, acteur_id: str, acteur_role: str) -> list[UsageIA]:
    """Registre des coûts IA de tous les clients (agrégé par client, mois et dossier). Lecture
    transversale journalisée (``lire_couts_ia``) : montants et identifiants seulement."""
    with db.transaction_systeme() as s:
        journaliser(s, actor=acteur_id, role=acteur_role, action="lire_couts_ia", target="ai_usage",
                    details={"usage": "finances"})
        lignes = s.execute(select(AiUsage.tenant_id, AiUsage.mois, AiUsage.dossier_id, AiUsage.cout_eur)).all()
    agr: dict[tuple[str, str, str | None], Decimal] = {}
    for t, mois, dos, cout in lignes:
        agr[(t, mois, dos)] = agr.get((t, mois, dos), Decimal(0)) + Decimal(cout)
    return [UsageIA(t, m, d, c) for (t, m, d), c in sorted(agr.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or ""))]


def alerte_fondateur(db: Database, *, cle: str, kind: str, message: str, tenant_id: str | None = None,
                     details: dict[str, Any] | None = None) -> bool:
    """Alerte au tableau de bord du fondateur (paiement échoué…), dédoublonnée par ``cle``."""
    from controldone.storage.alertes import emettre_alerte

    with db.transaction_systeme() as s:
        return emettre_alerte(s, cle=cle, kind=kind, message=message, tenant_id=tenant_id, details=details)
