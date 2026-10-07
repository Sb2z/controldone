"""Persistance du module de prospection (tables de ``models_prospection``). La logique (droits, exclusion,
opposition, séquences) est dans ``controldone.prospection`` ; ce module ne fait que lire et écrire, dans la
transaction fournie (session système ouverte par ``Database.transaction_systeme``)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controldone.storage.models_prospection import (
    ContactProspect,
    EvenementProspect,
    InscriptionSequence,
    Prospect,
    SequenceProspection,
    Suppression,
)

__all__ = [
    "ajouter_contact",
    "ajouter_evenement",
    "ajouter_suppression",
    "compter_evenements",
    "contact",
    "contacts",
    "contacts_par_empreinte",
    "evenements",
    "inscription",
    "inscriptions",
    "inserer_inscription",
    "inserer_prospect",
    "lire_prospect",
    "lister_prospects",
    "prospect_par_nom",
    "prospect_par_siren",
    "sequence",
    "sequences",
    "suppression",
    "suppressions",
    "supprimer_prospects",
    "tous_contacts",
    "tous_evenements",
]


# --- prospects -------------------------------------------------------------------------------------------------


def inserer_prospect(s: Session, **champs: Any) -> Prospect:
    p = Prospect(**champs)
    s.add(p)
    s.flush()
    return p


def lire_prospect(s: Session, prospect_id: str, *, verrou: bool = False) -> Prospect | None:
    q = select(Prospect).where(Prospect.id == prospect_id)
    if verrou:
        q = q.with_for_update()
    return s.execute(q).scalar_one_or_none()


def lister_prospects(s: Session) -> list[Prospect]:
    return list(s.execute(select(Prospect).order_by(Prospect.cree_le, Prospect.id)).scalars())


def prospect_par_siren(s: Session, siren: str) -> Prospect | None:
    return s.execute(select(Prospect).where(Prospect.siren == siren)).scalar_one_or_none()


def prospect_par_nom(s: Session, nom_normalise: str) -> Prospect | None:
    return s.execute(
        select(Prospect).where(Prospect.nom_normalise == nom_normalise).limit(1)
    ).scalar_one_or_none()


def supprimer_prospects(s: Session, ids: Iterable[str]) -> int:
    """Purge : contacts, événements, inscriptions puis prospects (la liste d'opposition est conservée)."""
    ids = list(ids)
    if not ids:
        return 0
    for table in (ContactProspect, EvenementProspect, InscriptionSequence):
        s.execute(delete(table).where(table.prospect_id.in_(ids)))
    n = s.execute(delete(Prospect).where(Prospect.id.in_(ids))).rowcount or 0
    s.flush()
    return int(n)


# --- contacts --------------------------------------------------------------------------------------------------


def ajouter_contact(s: Session, **champs: Any) -> ContactProspect:
    c = ContactProspect(**champs)
    s.add(c)
    s.flush()
    return c


def contacts(s: Session, prospect_id: str) -> list[ContactProspect]:
    return list(
        s.execute(
            select(ContactProspect)
            .where(ContactProspect.prospect_id == prospect_id)
            .order_by(ContactProspect.cree_le, ContactProspect.id)
        ).scalars()
    )


def tous_contacts(s: Session) -> list[ContactProspect]:
    return list(s.execute(select(ContactProspect).order_by(ContactProspect.cree_le)).scalars())


def contact(s: Session, contact_id: str) -> ContactProspect | None:
    return s.get(ContactProspect, contact_id)


def contacts_par_empreinte(s: Session, empreinte: str) -> list[ContactProspect]:
    return list(s.execute(select(ContactProspect).where(ContactProspect.empreinte == empreinte)).scalars())


# --- événements ------------------------------------------------------------------------------------------------


def ajouter_evenement(s: Session, **champs: Any) -> EvenementProspect:
    e = EvenementProspect(**champs)
    s.add(e)
    s.flush()
    return e


def evenements(s: Session, prospect_id: str) -> list[EvenementProspect]:
    return list(
        s.execute(
            select(EvenementProspect)
            .where(EvenementProspect.prospect_id == prospect_id)
            .order_by(EvenementProspect.le, EvenementProspect.id)
        ).scalars()
    )


def tous_evenements(s: Session, kinds: Iterable[str] | None = None) -> list[EvenementProspect]:
    q = select(EvenementProspect).order_by(EvenementProspect.le, EvenementProspect.id)
    if kinds is not None:
        q = q.where(EvenementProspect.kind.in_(list(kinds)))
    return list(s.execute(q).scalars())


def compter_evenements(s: Session, kinds: Iterable[str], depuis: datetime, jusqu_a: datetime) -> int:
    q = (
        select(func.count())
        .select_from(EvenementProspect)
        .where(EvenementProspect.kind.in_(list(kinds)))
        .where(EvenementProspect.le >= depuis)
        .where(EvenementProspect.le < jusqu_a)
    )
    return int(s.execute(q).scalar_one())


# --- séquences et inscriptions ---------------------------------------------------------------------------------


def sequences(s: Session) -> list[SequenceProspection]:
    return list(s.execute(select(SequenceProspection).order_by(SequenceProspection.id)).scalars())


def sequence(s: Session, sequence_id: str, *, verrou: bool = False) -> SequenceProspection | None:
    q = select(SequenceProspection).where(SequenceProspection.id == sequence_id)
    if verrou:
        q = q.with_for_update()
    return s.execute(q).scalar_one_or_none()


def inserer_sequence(s: Session, **champs: Any) -> SequenceProspection | None:
    """Insertion idempotente (séquence par défaut créée une fois, même par deux requêtes concurrentes)."""
    try:
        with s.begin_nested():
            seq = SequenceProspection(**champs)
            s.add(seq)
            s.flush()
    except IntegrityError:
        return sequence(s, champs["id"])
    return seq


def inserer_inscription(s: Session, **champs: Any) -> InscriptionSequence:
    i = InscriptionSequence(**champs)
    s.add(i)
    s.flush()
    return i


def inscription(s: Session, inscription_id: str, *, verrou: bool = False) -> InscriptionSequence | None:
    q = select(InscriptionSequence).where(InscriptionSequence.id == inscription_id)
    if verrou:
        q = q.with_for_update()
    return s.execute(q).scalar_one_or_none()


def inscriptions(
    s: Session, *, prospect_id: str | None = None, statut: str | None = None
) -> list[InscriptionSequence]:
    q = select(InscriptionSequence).order_by(InscriptionSequence.demarree_le, InscriptionSequence.id)
    if prospect_id is not None:
        q = q.where(InscriptionSequence.prospect_id == prospect_id)
    if statut is not None:
        q = q.where(InscriptionSequence.statut == statut)
    return list(s.execute(q).scalars())


# --- liste d'opposition ----------------------------------------------------------------------------------------


def suppression(s: Session, empreinte: str) -> Suppression | None:
    return s.execute(select(Suppression).where(Suppression.empreinte == empreinte)).scalar_one_or_none()


def ajouter_suppression(s: Session, **champs: Any) -> tuple[Suppression, bool]:
    """Ajout idempotent (une adresse déjà opposée reste avec son premier motif) ; ``(ligne, créée)``."""
    existant = suppression(s, champs["empreinte"])
    if existant is not None:
        return existant, False
    try:
        with s.begin_nested():
            ligne = Suppression(**champs)
            s.add(ligne)
            s.flush()
    except IntegrityError:
        existant = suppression(s, champs["empreinte"])
        if existant is None:  # pragma: no cover - contrainte violée sans ligne visible
            raise
        return existant, False
    return ligne, True


def suppressions(s: Session) -> list[Suppression]:
    return list(
        s.execute(select(Suppression).order_by(Suppression.cree_le.desc(), Suppression.id.desc())).scalars()
    )
