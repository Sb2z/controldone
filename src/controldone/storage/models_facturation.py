"""Tables de la facturation du fondateur (niveau plateforme, **sans** ``TenantMixin``).

Les factures sont des pièces comptables du fondateur : conservation 10 ans (art. L123-22 du Code de
commerce), y compris après l'effacement des données d'un client ; ``client_id`` est donc une simple
colonne (pas de clé étrangère ni de cascade), comme dans le journal d'audit. Elles ne contiennent aucun
document du client : identité de facturation de l'acheteur, lignes et montants.

- ``factures`` : append-only (une facture émise est immuable ; une correction passe par un avoir) ;
  déclencheurs SQL qui refusent UPDATE/DELETE, en plus du garde ORM ``AppendOnly`` ;
- ``compteurs_factures`` : dernier numéro par (entité légale, préfixe, année) — numérotation continue ;
- ``evenements_paiement`` : append-only, un par événement Stripe ou bouchon (identifiant unique : un
  webhook rejoué n'est compté qu'une fois) ;
- ``comptes_paiement`` : correspondance client <-> client Stripe / abonnement (mutable) ;
- ``coupons_utilisations`` : append-only, une ligne par coupon consommé (consentement signé cité) ;
- ``statuts_factures_pa`` : append-only, statuts de cycle de vie reçus de la plateforme agréée.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DDL, Date, Integer, LargeBinary, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from controldone.storage.coltypes import DecimalTexte, maintenant
from controldone.storage.models import AppendOnly, Base

__all__ = [
    "ComptePaiement",
    "CompteurFacture",
    "CouponUtilisation",
    "EvenementPaiement",
    "FactureEmise",
    "StatutFacturePA",
]

_ID = String(64)


class FactureEmise(AppendOnly, Base):
    __tablename__ = "factures"
    __table_args__ = (UniqueConstraint("emetteur", "numero"), UniqueConstraint("emetteur", "serie", "annee", "sequence"))

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    emetteur: Mapped[str] = mapped_column(String(64))
    serie: Mapped[str] = mapped_column(String(8))
    annee: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    numero: Mapped[str] = mapped_column(String(35))
    type_code: Mapped[str] = mapped_column(String(3))  # 380 facture, 381 avoir
    type_facture: Mapped[str] = mapped_column(String(32))  # diagnostic, abonnement, commission, avoir…
    client_id: Mapped[str] = mapped_column(_ID, index=True)
    outbox_id: Mapped[str | None] = mapped_column(_ID, unique=True, default=None)
    facture_origine_id: Mapped[str | None] = mapped_column(_ID, default=None, index=True)
    date_emission: Mapped[date] = mapped_column(Date)
    date_echeance: Mapped[date] = mapped_column(Date)
    devise: Mapped[str] = mapped_column(String(3), default="EUR")
    total_ht: Mapped[Decimal] = mapped_column(DecimalTexte)
    total_tva: Mapped[Decimal] = mapped_column(DecimalTexte)
    total_ttc: Mapped[Decimal] = mapped_column(DecimalTexte)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)
    xml: Mapped[str] = mapped_column(Text)
    pdf: Mapped[bytes] = mapped_column(LargeBinary)
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    cree_par: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)


class CompteurFacture(Base):
    __tablename__ = "compteurs_factures"

    emetteur: Mapped[str] = mapped_column(String(64), primary_key=True)
    serie: Mapped[str] = mapped_column(String(8), primary_key=True)
    annee: Mapped[int] = mapped_column(Integer, primary_key=True)
    dernier: Mapped[int] = mapped_column(Integer, default=0)
    derniere_date: Mapped[date | None] = mapped_column(Date, default=None)


class EvenementPaiement(AppendOnly, Base):
    __tablename__ = "evenements_paiement"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # identifiant de l'événement (evt_…)
    fournisseur: Mapped[str] = mapped_column(String(16))  # stripe | bouchon
    type: Mapped[str] = mapped_column(String(100))
    client_id: Mapped[str | None] = mapped_column(_ID, index=True, default=None)
    facture_id: Mapped[str | None] = mapped_column(_ID, index=True, default=None)
    #: Montant encaissé TTC (``None`` si l'événement n'est pas un encaissement).
    montant: Mapped[Decimal | None] = mapped_column(DecimalTexte, default=None)
    devise: Mapped[str | None] = mapped_column(String(3), default=None)
    le: Mapped[datetime] = mapped_column(default=maintenant)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ComptePaiement(Base):
    __tablename__ = "comptes_paiement"

    client_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    fournisseur: Mapped[str] = mapped_column(String(16))
    customer_id: Mapped[str | None] = mapped_column(String(255), unique=True, default=None)
    abonnement_id: Mapped[str | None] = mapped_column(String(255), default=None)
    palier: Mapped[str | None] = mapped_column(String(32), default=None)
    statut_abonnement: Mapped[str | None] = mapped_column(String(32), default=None)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)


class CouponUtilisation(AppendOnly, Base):
    __tablename__ = "coupons_utilisations"
    __table_args__ = (UniqueConstraint("code", "client_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    client_id: Mapped[str] = mapped_column(_ID)
    facture_id: Mapped[str] = mapped_column(_ID)
    consentement: Mapped[dict[str, Any]] = mapped_column(default=dict)  # signé par, le, référence du document
    le: Mapped[datetime] = mapped_column(default=maintenant)


class StatutFacturePA(AppendOnly, Base):
    __tablename__ = "statuts_factures_pa"
    __table_args__ = (UniqueConstraint("identifiant_pa", "code", "horodatage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facture_id: Mapped[str | None] = mapped_column(_ID, index=True, default=None)
    numero: Mapped[str] = mapped_column(String(35))
    identifiant_pa: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(8))
    libelle: Mapped[str] = mapped_column(String(100))
    horodatage: Mapped[str] = mapped_column(String(40))
    motif: Mapped[str | None] = mapped_column(Text, default=None)
    le: Mapped[datetime] = mapped_column(default=maintenant)


# Immuabilité des factures émises, aussi au niveau SQL (comme ``audit_log``).
for _sql in ("CREATE TRIGGER IF NOT EXISTS factures_sans_update BEFORE UPDATE ON factures "
             "BEGIN SELECT RAISE(ABORT, 'facture émise immuable'); END;",
             "CREATE TRIGGER IF NOT EXISTS factures_sans_delete BEFORE DELETE ON factures "
             "BEGIN SELECT RAISE(ABORT, 'facture émise immuable'); END;"):
    event.listen(FactureEmise.__table__, "after_create", DDL(_sql).execute_if(dialect="sqlite"))
for _sql in ("CREATE OR REPLACE FUNCTION factures_immuables() RETURNS trigger AS $$ "
             "BEGIN RAISE EXCEPTION 'facture émise immuable'; END; $$ LANGUAGE plpgsql;",
             "CREATE TRIGGER factures_sans_modif BEFORE UPDATE OR DELETE ON factures "
             "FOR EACH ROW EXECUTE FUNCTION factures_immuables();"):
    event.listen(FactureEmise.__table__, "after_create", DDL(_sql).execute_if(dialect="postgresql"))
