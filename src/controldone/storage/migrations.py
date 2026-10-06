"""Migrations de schéma versionnées (D-3503) : faire évoluer une base **existante**.

``Base.metadata.create_all`` crée les tables manquantes, jamais une colonne ni un index d'une table existante.
Ce module tient, dans la table ``schema_version``, la liste des étapes appliquées ; chaque étape est une fonction
Python **idempotente** (elle constate l'état avant d'agir : ``CREATE INDEX IF NOT EXISTS``, colonne ajoutée
seulement si absente), écrite pour SQLite **et** PostgreSQL, et exécutée dans sa propre transaction avec
l'inscription de sa version (une étape interrompue est rejouée en entier au passage suivant).

- Base **neuve** (aucune table de l'application) : ``create_all`` produit directement le dernier schéma, toutes
  les étapes sont inscrites sans être exécutées.
- Base **existante** (y compris créée avant ce mécanisme, sans ``schema_version``) : les étapes non inscrites
  sont exécutées dans l'ordre. Une base antérieure aux tables ``debit_compteurs``, ``sessions_revoquees``,
  ``sessions_actives``… les reçoit par l'étape 1.
- Qui migre : ``controldone migrer`` (sauvegarde préalable par défaut) ; au démarrage du web et du worker
  seulement en ``dev`` / ``test`` ou avec ``CONTROLDONE_MIGRATION_AUTO=1``. En production, sinon, le démarrage
  s'arrête (code 3) en listant les étapes en attente (``Database.exiger_schema_a_jour``).
- PostgreSQL : verrou consultatif de transaction (``pg_advisory_xact_lock``) pour que deux processus qui
  démarrent ensemble ne migrent pas en même temps ; SQLite : ``BEGIN IMMEDIATE`` suffit.

Ajouter une étape : une fonction ``_mNNNN_nom(conn)`` idempotente, ajoutée **à la fin** de ``MIGRATIONS``
(jamais réordonnée ni modifiée une fois livrée), **et** la même évolution déclarée dans les modèles (une base
neuve ne passe pas par les étapes). Alembic a été écarté (dépendance non figée, autogénération inutile pour des
ajouts de colonnes et d'index, ``ALTER`` limités de SQLite) : voir D-3503.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, Engine, Integer, String, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from controldone.storage.coltypes import maintenant
from controldone.storage.models import Base

__all__ = [
    "MIGRATIONS",
    "Migration",
    "SchemaVersion",
    "appliquer",
    "base_neuve",
    "en_attente",
    "inscrire_toutes",
    "versions_appliquees",
]

_VERROU_PG = 0x434453  # « CDS » : verrou consultatif des migrations


class SchemaVersion(Base):
    """Étapes de migration appliquées à cette base."""

    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nom: Mapped[str] = mapped_column(String(100))
    applique_le: Mapped[datetime] = mapped_column(default=maintenant)


@dataclass(frozen=True)
class Migration:
    version: int
    nom: str
    description: str
    executer: Callable[[Connection], None]


# --- outils idempotents -----------------------------------------------------------------------------------


def _tables(conn: Connection) -> set[str]:
    return set(inspect(conn).get_table_names())


def _colonnes(conn: Connection, table: str) -> set[str]:
    return {c["name"] for c in inspect(conn).get_columns(table)}


def _creer_index(conn: Connection, nom: str, table: str, colonnes: tuple[str, ...]) -> None:
    if table not in _tables(conn):
        return
    cols = ", ".join(f'"{c}"' for c in colonnes)
    conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{nom}" ON "{table}" ({cols})'))


def _ajouter_colonne(conn: Connection, table: str, colonne: str) -> bool:
    """Ajoute ``table.colonne`` telle que déclarée dans les modèles (nullable, sans défaut serveur) si elle
    manque ; renvoie ``True`` si elle vient d'être ajoutée."""
    if table not in _tables(conn) or colonne in _colonnes(conn, table):
        return False
    col = Base.metadata.tables[table].c[colonne]
    if not col.nullable:  # une colonne NOT NULL sans défaut ne s'ajoute pas à une table remplie
        raise RuntimeError(f"migration : {table}.{colonne} doit être nullable ou avoir un défaut serveur")
    type_sql = col.type.compile(dialect=conn.dialect)
    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{colonne}" {type_sql}'))
    return True


# --- étapes -----------------------------------------------------------------------------------------------


def _m0001_socle(conn: Connection) -> None:
    """Tables manquantes d'une base créée avant ce mécanisme (débit, révocations et sessions actives, D-3201 ;
    facturation ; notifications) ; ``create_all`` ne touche pas aux tables existantes."""
    Base.metadata.create_all(conn, checkfirst=True)


def _m0002_index_journal_taches(conn: Connection) -> None:
    """Index du journal (action, acteur, date) et des tâches (statut, type, création) : backlog interface."""
    for nom, table, cols in (
        ("ix_audit_log_action", "audit_log", ("action", "id")),
        ("ix_audit_log_actor", "audit_log", ("actor", "id")),
        ("ix_audit_log_ts", "audit_log", ("ts",)),
        ("ix_jobs_statut_cree", "jobs", ("statut", "cree_le")),
        ("ix_jobs_kind_statut", "jobs", ("kind", "statut", "run_after")),
        ("ix_jobs_cree", "jobs", ("cree_le",)),
    ):
        _creer_index(conn, nom, table, cols)


def _m0003_alertes_notifiees(conn: Connection) -> None:
    """``alertes.notifiee_le`` (notifications poussées, D-3502). Les alertes déjà présentes sont marquées
    traitées : la mise à jour n'envoie pas d'un coup tout l'historique."""
    if _ajouter_colonne(conn, "alertes", "notifiee_le"):
        conn.execute(text("UPDATE alertes SET notifiee_le = cree_le WHERE notifiee_le IS NULL"))
    _creer_index(conn, "ix_alertes_notifiee_le", "alertes", ("notifiee_le",))
    Base.metadata.tables["notifications_alertes"].create(conn, checkfirst=True)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "socle", "tables manquantes (débit, sessions, facturation, notifications)", _m0001_socle),
    Migration(2, "index_journal_taches", "index du journal et des tâches", _m0002_index_journal_taches),
    Migration(3, "alertes_notifiees", "colonne alertes.notifiee_le et table notifications_alertes",
              _m0003_alertes_notifiees),
)


# --- application ------------------------------------------------------------------------------------------


def versions_appliquees(conn: Connection) -> set[int]:
    if SchemaVersion.__tablename__ not in _tables(conn):
        return set()
    return {int(v) for (v,) in conn.execute(text("SELECT version FROM schema_version"))}


def en_attente(engine: Engine) -> list[Migration]:
    with engine.connect() as conn:
        faites = versions_appliquees(conn)
    return [m for m in MIGRATIONS if m.version not in faites]


def base_neuve(engine: Engine) -> bool:
    """Aucune table de l'application (``schema_version`` mise à part)."""
    tables = set(inspect(engine).get_table_names()) - {SchemaVersion.__tablename__}
    return not (tables & set(Base.metadata.tables))


def _inscrire(conn: Connection, m: Migration) -> None:
    conn.execute(SchemaVersion.__table__.insert().values(version=m.version, nom=m.nom, applique_le=maintenant()))


def inscrire_toutes(engine: Engine) -> None:
    """Base neuve créée par ``create_all`` : toutes les étapes sont déjà dans le schéma."""
    SchemaVersion.__table__.create(engine, checkfirst=True)
    for m in en_attente(engine):
        try:
            with engine.begin() as conn:
                _inscrire(conn, m)
        except IntegrityError:  # inscrite entre-temps par un autre processus
            continue


def appliquer(engine: Engine, *, journal: Callable[[str], None] | None = None) -> list[Migration]:
    """Exécute les étapes en attente, dans l'ordre ; chacune dans sa transaction avec son inscription."""
    SchemaVersion.__table__.create(engine, checkfirst=True)
    faites: list[Migration] = []
    for m in en_attente(engine):
        try:
            with engine.begin() as conn:
                if conn.dialect.name == "postgresql":
                    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _VERROU_PG})
                if m.version in versions_appliquees(conn):  # appliquée par un autre processus pendant l'attente
                    continue
                m.executer(conn)
                _inscrire(conn, m)
        except IntegrityError:
            continue
        faites.append(m)
        if journal:
            journal(f"migration {m.version:04d} {m.nom} appliquée — {m.description}")
    return faites
