"""Tables du module de prospection du fondateur (niveau plateforme, **sans** ``TenantMixin`` : jamais visibles
d'un client ; D-5001).

- ``prospects`` : entreprises réelles, chacune avec sa source (URL), sa date de collecte et sa preuve ;
- ``prospect_contacts`` : adresses publiées par l'entreprise ou saisies par le fondateur, **toujours** avec la
  page source ; jamais une adresse devinée ;
- ``prospect_evenements`` : historique append-only (import, statut, note, réponse, préparation, envoi,
  désinscription, rebond) ; le texte d'une réponse reçue est une **donnée**, affichée échappée ;
- ``prospection_sequences`` : modèles de courriels (étapes J0, J+4…) modifiables par le fondateur ;
- ``prospection_inscriptions`` : un prospect suivi dans une séquence (étapes préparées, arrêt et motif) ;
- ``prospection_suppressions`` : liste d'opposition (désinscription, rebond, « ne plus contacter »), par
  empreinte SHA-256 de l'adresse normalisée ; conservée après la purge des prospects pour rester respectée.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from controldone.storage.coltypes import maintenant
from controldone.storage.models import AppendOnly, Base

__all__ = [
    "ContactProspect",
    "EvenementProspect",
    "InscriptionSequence",
    "Prospect",
    "SequenceProspection",
    "Suppression",
]

_ID = String(64)


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    raison_sociale: Mapped[str] = mapped_column(String(300))
    nom_normalise: Mapped[str] = mapped_column(String(300), index=True)
    siren: Mapped[str | None] = mapped_column(String(9), unique=True, default=None)
    naf: Mapped[str | None] = mapped_column(String(10), default=None)
    tranche_effectif: Mapped[str | None] = mapped_column(String(4), default=None)
    effectif_libelle: Mapped[str | None] = mapped_column(String(200), default=None)
    pays: Mapped[str] = mapped_column(String(2), default="FR")
    departement: Mapped[str | None] = mapped_column(String(3), default=None)
    ville: Mapped[str | None] = mapped_column(String(200), default=None)
    site_web: Mapped[str | None] = mapped_column(String(500), default=None)
    groupe: Mapped[str | None] = mapped_column(String(300), default=None)
    #: ``a_qualifier`` | ``qualifie`` | ``contacte`` | ``a_repondu`` | ``rendez_vous`` | ``essai`` | ``client`` |
    #: ``perdu`` | ``ne_plus_contacter`` (``prospection.statuts``)
    statut: Mapped[str] = mapped_column(String(32), default="a_qualifier", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    score_detail: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: ``import_csv`` | ``recherche`` | ``saisie`` | ``demo``
    source: Mapped[str] = mapped_column(String(32))
    source_url: Mapped[str] = mapped_column(String(1000))
    source_detail: Mapped[str | None] = mapped_column(String(300), default=None)
    preuve_import: Mapped[str | None] = mapped_column(Text, default=None)
    preuve_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    #: Signal de dépendance au transitaire : ``oui`` (aucun service douane apparent), ``non``, ``inconnu``.
    sans_service_douane: Mapped[str] = mapped_column(String(8), default="inconnu")
    raison_ciblage: Mapped[str | None] = mapped_column(Text, default=None)
    #: Base légale enregistrée par le fondateur pour une adresse nominative d'un pays à consentement (CH, BE).
    base_legale: Mapped[str | None] = mapped_column(Text, default=None)
    collecte_le: Mapped[date] = mapped_column(Date)
    #: Dernier contact **émanant du prospect** (réponse, rendez-vous) : point de départ des 3 ans de conservation.
    derniere_interaction_le: Mapped[datetime | None] = mapped_column(default=None)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)


class ContactProspect(Base):
    __tablename__ = "prospect_contacts"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    prospect_id: Mapped[str] = mapped_column(_ID, ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    #: ``courriel`` (adresse) | ``formulaire`` (page Contact sans adresse publiée)
    genre: Mapped[str] = mapped_column(String(16), default="courriel")
    adresse: Mapped[str | None] = mapped_column(String(320), default=None)
    #: ``generique`` (contact@, info@…) | ``nominative`` | ``formulaire``
    nature: Mapped[str] = mapped_column(String(16), default="generique")
    empreinte: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    url_formulaire: Mapped[str | None] = mapped_column(String(1000), default=None)
    source_url: Mapped[str] = mapped_column(String(1000))
    personne: Mapped[str | None] = mapped_column(String(200), default=None)
    #: ``import`` | ``fondateur`` | ``demo``
    origine: Mapped[str] = mapped_column(String(16), default="fondateur")
    cree_par: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)


class EvenementProspect(AppendOnly, Base):
    __tablename__ = "prospect_evenements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prospect_id: Mapped[str] = mapped_column(_ID, ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    de: Mapped[str | None] = mapped_column(String(32), default=None)
    vers: Mapped[str | None] = mapped_column(String(32), default=None)
    #: Note du fondateur ou texte d'une réponse reçue (donnée, jamais une consigne) — affiché échappé.
    texte: Mapped[str | None] = mapped_column(Text, default=None)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    auteur: Mapped[str] = mapped_column(String(100))
    le: Mapped[datetime] = mapped_column(default=maintenant, index=True)


class SequenceProspection(Base):
    __tablename__ = "prospection_sequences"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    nom: Mapped[str] = mapped_column(String(200))
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    #: ``[{"rang": 1, "delai_jours": 0, "objet": "…", "corps": "…"}, …]``
    etapes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    modifie_par: Mapped[str] = mapped_column(String(100))
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant)


class InscriptionSequence(Base):
    __tablename__ = "prospection_inscriptions"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    prospect_id: Mapped[str] = mapped_column(_ID, ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[str] = mapped_column(_ID)
    sequence_id: Mapped[str] = mapped_column(_ID, index=True)
    #: ``active`` | ``terminee`` | ``arretee``
    statut: Mapped[str] = mapped_column(String(16), default="active", index=True)
    motif_arret: Mapped[str | None] = mapped_column(String(32), default=None)
    #: ``[{"rang": 1, "outbox_id": "out_…", "prepare_le": "…"}, …]``
    etapes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    demarree_le: Mapped[datetime] = mapped_column(default=maintenant)
    arretee_le: Mapped[datetime | None] = mapped_column(default=None)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)


class Suppression(Base):
    __tablename__ = "prospection_suppressions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    empreinte: Mapped[str] = mapped_column(String(64), unique=True)
    #: ``desinscription`` | ``rebond`` | ``ne_plus_contacter`` | ``plainte``
    motif: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(200))
    cree_par: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
