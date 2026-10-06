"""Tables (SQLAlchemy 2). Aucune ``relationship()`` : pas de chargement implicite qui échapperait au
cloisonnement ; toute lecture passe par ``TenantScope`` / ``OperatorScope``.

- ``TenantMixin`` : table de données client, ``tenant_id`` obligatoire, filtré automatiquement
  (voir ``storage.garde``). ``outbox`` est la seule table client où ``tenant_id`` peut être nul
  (actions de niveau plateforme du fondateur) ; une ligne sans client n'est visible d'aucun client.
- ``AppendOnly`` : ni modification ni suppression par l'ORM (le journal d'audit est en plus protégé par
  des déclencheurs SQL). Les événements de recouvrement et le registre des coûts IA ne sont supprimés que
  par l'effacement RGPD d'un client (session système).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from controldone.storage.coltypes import DecimalTexte, UTCDateTime, maintenant

__all__ = [
    "MODELES_CLIENT",
    "AiUsage",
    "Alerte",
    "AppendOnly",
    "AuditLog",
    "AutonomieSortie",
    "Base",
    "CleApi",
    "Constat",
    "CorrectionValeur",
    "Document",
    "Dossier",
    "DossierFichier",
    "Ecart",
    "Entite",
    "EvenementRecouvrement",
    "Fichier",
    "Grille",
    "Job",
    "Lot",
    "Membership",
    "NotificationAlerte",
    "Outbox",
    "PageTexte",
    "Reclamation",
    "Resultat",
    "Tenant",
    "TenantMixin",
    "Transitaire",
    "User",
]

_ID = String(64)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, datetime: UTCDateTime, Decimal: DecimalTexte}  # noqa: RUF012


class TenantMixin:
    """Données d'un client : ``tenant_id`` obligatoire et indexé."""

    @declared_attr
    def tenant_id(cls) -> Mapped[str]:
        return mapped_column(_ID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)


class AppendOnly:
    """Marqueur : ni UPDATE ni DELETE par l'ORM (contrôlé dans ``storage.garde``)."""


# --- plateforme ------------------------------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    raison_sociale: Mapped[str] = mapped_column(String(300))
    offre: Mapped[str] = mapped_column(String(32), default="diagnostic")
    plafond_cout_ia_mensuel_eur: Mapped[Decimal] = mapped_column(default=Decimal("8.00"))
    retention_jours: Mapped[int] = mapped_column(Integer, default=180)
    reglages: Mapped[dict[str, Any]] = mapped_column(default=dict)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    nom: Mapped[str | None] = mapped_column(String(200), default=None)
    #: ``fondateur`` | ``client_admin`` | ``client_lecteur`` (rôle par défaut ; le rôle dans un client
    #: est celui de ``memberships``).
    role: Mapped[str] = mapped_column(String(32))
    mot_de_passe_hash: Mapped[str] = mapped_column(String(300))
    totp_secret_chiffre: Mapped[str | None] = mapped_column(Text, default=None)
    totp_dernier_pas: Mapped[int | None] = mapped_column(Integer, default=None)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    derniere_connexion: Mapped[datetime | None] = mapped_column(default=None)


class AutonomieSortie(Base):
    """Réglage d'autonomie par type d'action sortante (absent = ``manuel``)."""

    __tablename__ = "outbox_autonomie"

    kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="manuel")
    modifie_par: Mapped[str] = mapped_column(String(100))
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant)


class AuditLog(AppendOnly, Base):
    """Journal append-only chaîné : ``hash = sha256(prev_hash + contenu canonique)``."""

    __tablename__ = "audit_log"
    # Filtres du journal (/admin/journal) : action, acteur, période ; tri par clé primaire (migration 2, D-3503)
    __table_args__ = (
        Index("ix_audit_log_action", "action", "id"),
        Index("ix_audit_log_actor", "actor", "id"),
        Index("ix_audit_log_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(default=maintenant)
    actor: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(32))
    # Pas de clé étrangère : le journal survit à l'effacement d'un client (identifiants seulement).
    tenant_id: Mapped[str | None] = mapped_column(_ID, index=True, default=None)
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str | None] = mapped_column(String(300), default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Alerte(Base):
    """Alerte pour le fondateur (tableau de bord) : job mort, plafond de coût IA… Jamais de contenu de
    document. ``cle`` déduplique (ex. ``cout80:<client>:<mois>``)."""

    __tablename__ = "alertes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cle: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str | None] = mapped_column(_ID, index=True, default=None)
    message: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    lue_le: Mapped[datetime | None] = mapped_column(default=None)
    #: traitée par l'envoi des notifications (envoyée, regroupée ou écartée) — migration 3, D-3502
    notifiee_le: Mapped[datetime | None] = mapped_column(default=None, index=True)


class NotificationAlerte(Base):
    """Notification poussée au fondateur (webhook, courriel) : **une par type d'alerte et par jour** (``cle`` =
    ``<kind>:<AAAA-MM-JJ>``). Aucune donnée client : type, nombre, horodatage, canaux (D-3502)."""

    __tablename__ = "notifications_alertes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cle: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(64))
    nombre: Mapped[int] = mapped_column(Integer, default=0)
    canaux: Mapped[str] = mapped_column(String(100), default="")
    #: ``envoyee`` | ``echec`` (nouvel essai au passage suivant)
    statut: Mapped[str] = mapped_column(String(16), default="echec")
    essais: Mapped[int] = mapped_column(Integer, default=0)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    envoyee_le: Mapped[datetime | None] = mapped_column(default=None)


class Job(Base):
    """File de tâches en base (D-004)."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_prets", "statut", "run_after"),
        # liste des tâches (/admin/taches) : filtres statut / type, tri par création (migration 2, D-3503)
        Index("ix_jobs_statut_cree", "statut", "cree_le"),
        Index("ix_jobs_kind_statut", "kind", "statut", "run_after"),
        Index("ix_jobs_cree", "cree_le"),
    )

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True)
    tenant_id: Mapped[str | None] = mapped_column(_ID, index=True, default=None)
    #: ``pending`` | ``running`` | ``done`` | ``dead``
    statut: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(default=maintenant)
    locked_until: Mapped[datetime | None] = mapped_column(default=None)
    locked_by: Mapped[str | None] = mapped_column(String(100), default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(default=None)
    last_error: Mapped[str | None] = mapped_column(String(300), default=None)
    resultat: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    termine_le: Mapped[datetime | None] = mapped_column(default=None)


# --- données client --------------------------------------------------------------------------------


class Membership(TenantMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(_ID, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)


class CleApi(TenantMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    nom: Mapped[str] = mapped_column(String(200))
    prefixe: Mapped[str] = mapped_column(String(32), unique=True)
    hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32), default="client_admin")
    cree_par: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    revoquee_le: Mapped[datetime | None] = mapped_column(default=None)
    dernier_usage: Mapped[datetime | None] = mapped_column(default=None)


class Entite(TenantMixin, Base):
    __tablename__ = "entites"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    raison_sociale: Mapped[str] = mapped_column(String(300))
    tva: Mapped[str | None] = mapped_column(String(32), default=None)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)


class Transitaire(TenantMixin, Base):
    __tablename__ = "transitaires"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    nom: Mapped[str] = mapped_column(String(300))
    tva: Mapped[str | None] = mapped_column(String(32), default=None)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)


class Grille(TenantMixin, Base):
    """Grille tarifaire versionnée : une ligne par version ; seule une version ``validee`` (par le
    fondateur) sert aux contrôles D."""

    __tablename__ = "grilles"
    __table_args__ = (UniqueConstraint("tenant_id", "grille_id", "version"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    grille_id: Mapped[str] = mapped_column(_ID, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    transitaire_id: Mapped[str | None] = mapped_column(_ID, default=None)
    reference: Mapped[str | None] = mapped_column(String(200), default=None)
    statut: Mapped[str] = mapped_column(String(16), default="brouillon")
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cree_par: Mapped[str | None] = mapped_column(String(100), default=None)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    valide_par: Mapped[str | None] = mapped_column(String(100), default=None)
    valide_le: Mapped[datetime | None] = mapped_column(default=None)


class Lot(TenantMixin, Base):
    __tablename__ = "lots"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    canal: Mapped[str] = mapped_column(String(16), default="depot")
    statut: Mapped[str] = mapped_column(String(16), default="recu")
    expediteur: Mapped[str | None] = mapped_column(String(320), default=None)
    recu_le: Mapped[datetime] = mapped_column(default=maintenant)
    cloture_le: Mapped[datetime | None] = mapped_column(default=None)
    resume: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Fichier(TenantMixin, Base):
    """Métadonnées d'un fichier reçu ; le contenu est dans le coffre chiffré (``coffre_ref`` = sha256)."""

    __tablename__ = "fichiers"
    __table_args__ = (Index("ix_fichiers_tenant_sha", "tenant_id", "sha256"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    lot_id: Mapped[str | None] = mapped_column(_ID, ForeignKey("lots.id", ondelete="CASCADE"), index=True)
    nom_original: Mapped[str] = mapped_column(String(500))
    chemin_relatif: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64))
    taille: Mapped[int] = mapped_column(Integer, default=0)
    type_mime: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    statut: Mapped[str] = mapped_column(String(16), default="ok")
    motif_refus: Mapped[str | None] = mapped_column(String(200), default=None)
    nombre_pages: Mapped[int | None] = mapped_column(Integer, default=None)
    doublon_de: Mapped[str | None] = mapped_column(_ID, default=None)
    coffre_ref: Mapped[str | None] = mapped_column(String(64), default=None)
    recu_le: Mapped[datetime] = mapped_column(default=maintenant)
    purge_le: Mapped[datetime | None] = mapped_column(default=None)


class PageTexte(TenantMixin, Base):
    """Page d'un fichier ; le texte est chiffré dans le coffre (``texte_ref``)."""

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("tenant_id", "fichier_id", "numero"),)

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    fichier_id: Mapped[str] = mapped_column(_ID, ForeignKey("fichiers.id", ondelete="CASCADE"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    qualite_texte: Mapped[str] = mapped_column(String(16), default="natif")
    sha256_texte: Mapped[str | None] = mapped_column(String(64), default=None)
    texte_ref: Mapped[str | None] = mapped_column(String(64), default=None)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    purge_le: Mapped[datetime | None] = mapped_column(default=None)


class Dossier(TenantMixin, Base):
    """Instantané JSON du ``Dossier`` pydantic (+ version, §6.2.7)."""

    __tablename__ = "dossiers"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    lot_id: Mapped[str | None] = mapped_column(_ID, default=None, index=True)
    reference: Mapped[str | None] = mapped_column(String(32), default=None)
    version: Mapped[int] = mapped_column(Integer, default=1)
    statut_global: Mapped[str | None] = mapped_column(String(32), default=None)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)
    cloture_le: Mapped[datetime | None] = mapped_column(default=None)


class DossierFichier(TenantMixin, Base):
    """Fichiers bruts utilisés par un dossier (purge §20.4 : quand tous leurs dossiers sont expirés)."""

    __tablename__ = "dossier_fichiers"
    __table_args__ = (UniqueConstraint("tenant_id", "dossier_id", "fichier_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dossier_id: Mapped[str] = mapped_column(_ID, ForeignKey("dossiers.id", ondelete="CASCADE"), index=True)
    fichier_id: Mapped[str] = mapped_column(_ID, ForeignKey("fichiers.id", ondelete="CASCADE"), index=True)


class Document(TenantMixin, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    lot_id: Mapped[str | None] = mapped_column(_ID, default=None, index=True)
    dossier_id: Mapped[str | None] = mapped_column(_ID, default=None, index=True)
    type: Mapped[str] = mapped_column(String(32))
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)


class Resultat(TenantMixin, Base):
    __tablename__ = "resultats"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    dossier_id: Mapped[str] = mapped_column(_ID, index=True)
    dossier_version: Mapped[int] = mapped_column(Integer)
    execution_id: Mapped[str | None] = mapped_column(_ID, default=None)
    controle_id: Mapped[str] = mapped_column(String(8))
    outcome: Mapped[str] = mapped_column(String(32))
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Constat(TenantMixin, Base):
    __tablename__ = "constats"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    resultat_id: Mapped[str | None] = mapped_column(_ID, default=None)
    dossier_id: Mapped[str] = mapped_column(_ID, index=True)
    dossier_version: Mapped[int] = mapped_column(Integer)
    controle_id: Mapped[str] = mapped_column(String(8))
    niveau: Mapped[str] = mapped_column(String(32))
    montant_en_jeu: Mapped[Decimal | None] = mapped_column(DecimalTexte, default=None)
    nature_montant: Mapped[str | None] = mapped_column(String(32), default=None)
    statut_validation: Mapped[str] = mapped_column(String(16), default="propose")
    valide_par: Mapped[str | None] = mapped_column(String(100), default=None)
    valide_le: Mapped[datetime | None] = mapped_column(default=None)
    commentaire_validation: Mapped[str | None] = mapped_column(Text, default=None)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Ecart(TenantMixin, Base):
    """Écart à recouvrer (§17.1)."""

    __tablename__ = "ecarts"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    constat_id: Mapped[str] = mapped_column(_ID, index=True)
    transitaire_id: Mapped[str | None] = mapped_column(_ID, default=None)
    statut: Mapped[str] = mapped_column(String(32), default="ouvert")
    montant_initial: Mapped[Decimal] = mapped_column(DecimalTexte)
    reste: Mapped[Decimal] = mapped_column(DecimalTexte)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)


class Reclamation(TenantMixin, Base):
    __tablename__ = "reclamations"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    transitaire_id: Mapped[str] = mapped_column(_ID)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    modifie_le: Mapped[datetime] = mapped_column(default=maintenant, onupdate=maintenant)


class EvenementRecouvrement(AppendOnly, TenantMixin, Base):
    __tablename__ = "evenements_recouvrement"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    ecart_id: Mapped[str] = mapped_column(_ID, index=True)
    de: Mapped[str] = mapped_column(String(32))
    vers: Mapped[str] = mapped_column(String(32))
    le: Mapped[datetime] = mapped_column(default=maintenant)
    auteur: Mapped[str] = mapped_column(String(100))
    montant: Mapped[Decimal | None] = mapped_column(DecimalTexte, default=None)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)


class CorrectionValeur(AppendOnly, TenantMixin, Base):
    """Correction d'une valeur extraite (§6.2.11), append-only : la valeur remplacée reste dans
    ``ancienne`` (instantané JSON complet) ; la nouvelle valeur ``saisie_humaine`` remplace l'ancienne
    dans ``documents.contenu`` pour les contrôles."""

    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    dossier_id: Mapped[str] = mapped_column(_ID, index=True)
    document_id: Mapped[str] = mapped_column(_ID, index=True)
    cible: Mapped[str] = mapped_column(_ID)
    chemin: Mapped[str] = mapped_column(String(300))
    ancienne_valeur: Mapped[str | None] = mapped_column(Text, default=None)
    nouvelle_valeur: Mapped[str | None] = mapped_column(Text, default=None)
    auteur: Mapped[str] = mapped_column(String(100))
    role_auteur: Mapped[str] = mapped_column(String(32))
    motif: Mapped[str] = mapped_column(Text)
    le: Mapped[datetime] = mapped_column(default=maintenant)
    contenu: Mapped[dict[str, Any]] = mapped_column(default=dict)


class AiUsage(AppendOnly, TenantMixin, Base):
    """Registre des coûts IA (§20.5)."""

    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_mois", "tenant_id", "mois"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dossier_id: Mapped[str | None] = mapped_column(_ID, default=None, index=True)
    lot_id: Mapped[str | None] = mapped_column(_ID, default=None)
    execution_id: Mapped[str | None] = mapped_column(_ID, default=None)
    mois: Mapped[str] = mapped_column(String(7))
    modele: Mapped[str | None] = mapped_column(String(100), default=None)
    jetons_entree: Mapped[int] = mapped_column(Integer, default=0)
    jetons_sortie: Mapped[int] = mapped_column(Integer, default=0)
    cout_eur: Mapped[Decimal] = mapped_column(DecimalTexte)
    le: Mapped[datetime] = mapped_column(default=maintenant)


class Outbox(TenantMixin, Base):
    """File de validation des actions sortantes (``ActionSortante``). ``tenant_id`` nul = action de
    niveau plateforme (prospection du fondateur…)."""

    __tablename__ = "outbox"

    tenant_id: Mapped[str | None] = mapped_column(  # type: ignore[assignment]
        _ID, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=True, default=None
    )
    id: Mapped[str] = mapped_column(_ID, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    statut: Mapped[str] = mapped_column(String(16), default="brouillon", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    payload_corrige: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    motif_blocage: Mapped[str | None] = mapped_column(Text, default=None)
    motif_refus: Mapped[str | None] = mapped_column(Text, default=None)
    idempotency_key: Mapped[str | None] = mapped_column(String(300), unique=True, default=None)
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    cree_par: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(default=maintenant)
    decide_par: Mapped[str | None] = mapped_column(String(100), default=None)
    decide_le: Mapped[datetime | None] = mapped_column(default=None)
    envoye_le: Mapped[datetime | None] = mapped_column(default=None)
    reference_envoi: Mapped[str | None] = mapped_column(String(500), default=None)


#: Tables de données client, dans un ordre de suppression compatible avec les clés étrangères.
MODELES_CLIENT: tuple[type[Base], ...] = (
    Outbox,
    AiUsage,
    EvenementRecouvrement,
    Reclamation,
    Ecart,
    Constat,
    Resultat,
    CorrectionValeur,
    Document,
    DossierFichier,
    Dossier,
    PageTexte,
    Fichier,
    Lot,
    Grille,
    Transitaire,
    Entite,
    CleApi,
    Membership,
)
