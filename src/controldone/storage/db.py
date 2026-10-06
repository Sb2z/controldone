"""Moteur, sessions et schéma (D-003 : SQLite WAL par défaut, PostgreSQL possible).

``Database`` est le point d'entrée : ``db.tenant(tenant_id, acteur)`` (contexte ``TenantScope``),
``db.operateur(acteur)`` (contexte ``OperatorScope``). Aucune session brute ne doit être utilisée hors du
paquet ``controldone.storage`` (test ``test_pas_de_session_brute``).

SQLite : ``journal_mode=WAL``, ``foreign_keys=ON``, ``busy_timeout``. Les transactions commencent par
``BEGIN IMMEDIATE`` (un seul écrivain à la fois, pas d'échec « snapshot » au passage lecture -> écriture) ;
``db.session(lecture=True)`` ouvre une transaction différée pour les lectures longues.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from controldone.config import env
from controldone.storage import garde
from controldone.storage import migrations as _migrations
from controldone.storage.models import AuditLog, Base

if TYPE_CHECKING:
    from controldone.auth.roles import Acteur
    from controldone.storage.scope import OperatorScope, TenantScope

__all__ = ["Database", "MigrationEnAttente", "SchemaPerime", "creer_moteur", "url_par_defaut"]

_TRIGGERS_SQLITE = [
    "CREATE TRIGGER IF NOT EXISTS audit_log_sans_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log append-only'); END;",
    "CREATE TRIGGER IF NOT EXISTS audit_log_sans_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log append-only'); END;",
]
_TRIGGERS_PG = [
    "CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'audit_log append-only'; END; $$ LANGUAGE plpgsql;",
    "CREATE TRIGGER audit_log_sans_modif BEFORE UPDATE OR DELETE ON audit_log "
    "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();",
]
for _sql in _TRIGGERS_SQLITE:
    event.listen(AuditLog.__table__, "after_create", DDL(_sql).execute_if(dialect="sqlite"))
for _sql in _TRIGGERS_PG:
    event.listen(AuditLog.__table__, "after_create", DDL(_sql).execute_if(dialect="postgresql"))


def url_par_defaut() -> str:
    url = env("CONTROLDONE_DATABASE_URL")
    if url:
        return url
    from controldone.config import get_settings

    return get_settings().database_url


def creer_moteur(url: str, *, immediat: bool = True, echo: bool = False) -> Engine:
    u = make_url(url)
    if u.get_backend_name() != "sqlite":
        return create_engine(url, echo=echo, pool_pre_ping=True, future=True)
    if u.database and u.database != ":memory:":
        Path(u.database).parent.mkdir(parents=True, exist_ok=True)
    moteur = create_engine(url, echo=echo, future=True, connect_args={"timeout": 30})

    @event.listens_for(moteur, "connect")
    def _pragmas(dbapi_conn: Any, _record: Any) -> None:
        dbapi_conn.isolation_level = None  # transactions pilotées par l'écouteur « begin »
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    @event.listens_for(moteur, "begin")
    def _begin(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE" if immediat else "BEGIN")

    return moteur


class SchemaPerime(RuntimeError):
    """La base existante n'a pas toutes les colonnes du code (version plus récente sans migration) : arrêt
    au démarrage avec la liste des colonnes manquantes, plutôt qu'une erreur « no such column » en cours
    d'exécution (audit B, suspicion 8 ; D-1322)."""


class MigrationEnAttente(SchemaPerime):
    """Production : une étape de migration attend ``controldone migrer`` (D-3503, D-4102)."""


class Database:
    """Base de données de la plateforme."""

    def __init__(self, url: str | None = None, *, echo: bool = False) -> None:
        garde.installer()
        self.url = url or url_par_defaut()
        self.engine = creer_moteur(self.url, immediat=True, echo=echo)
        self.est_sqlite = self.engine.dialect.name == "sqlite"
        self.engine_lecture = (
            creer_moteur(self.url, immediat=False, echo=echo) if self.est_sqlite else self.engine
        )
        self._fabrique = sessionmaker(self.engine, expire_on_commit=False)
        self._fabrique_lecture = sessionmaker(self.engine_lecture, expire_on_commit=False)

    # --- schéma ---
    def creer_schema(self, *, migrer: bool = True) -> None:
        """Tables manquantes (``create_all``) ; base neuve : toutes les migrations inscrites ; base existante :
        migrations en attente appliquées si ``migrer`` (sinon laissées à ``exiger_schema_a_jour``)."""
        neuve = _migrations.base_neuve(self.engine)
        Base.metadata.create_all(self.engine)
        if neuve:
            _migrations.inscrire_toutes(self.engine)
        elif migrer:
            self.migrer()

    def migrations_en_attente(self) -> list[_migrations.Migration]:
        return _migrations.en_attente(self.engine)

    def migrer(self, *, journal: Any = None) -> list[_migrations.Migration]:
        """Applique les migrations en attente (D-3503). Sauvegarder avant en production : ``controldone
        migrer`` le fait par défaut."""
        return _migrations.appliquer(self.engine, journal=journal)

    def colonnes_manquantes(self) -> list[str]:
        """``table.colonne`` déclarées par le code mais absentes d'une table **existante** (``create_all``
        crée les tables manquantes, jamais les colonnes : il faut une migration)."""
        from sqlalchemy import inspect

        insp = inspect(self.engine)
        existantes = set(insp.get_table_names())
        manquantes = []
        for table in Base.metadata.sorted_tables:
            if table.name not in existantes:
                continue
            en_base = {c["name"] for c in insp.get_columns(table.name)}
            manquantes += [f"{table.name}.{c.name}" for c in table.columns if c.name not in en_base]
        return manquantes

    def exiger_schema_a_jour(self) -> None:
        """Démarrage du web et du worker. Migrations en attente : appliquées en ``dev`` / ``test`` ou avec
        ``CONTROLDONE_MIGRATION_AUTO=1``, sinon ``SchemaPerime`` (production : sauvegarder puis ``controldone
        migrer``). Puis lève ``SchemaPerime`` si une table existante n'a pas toutes les colonnes du code."""
        from controldone.storage.cles import mode_execution

        attente = self.migrations_en_attente()
        if attente:
            if mode_execution() in ("dev", "test") or env("CONTROLDONE_MIGRATION_AUTO") == "1":
                self.migrer()
            else:
                raise MigrationEnAttente(
                    "schéma de la base à migrer : "
                    + ", ".join(f"{m.version:04d} {m.nom}" for m in attente)
                    + " — sauvegarder puis exécuter « controldone "
                    "migrer » (docker compose : service « migrer », docs/EXPLOITATION.md § migrations)"
                )
        manquantes = self.colonnes_manquantes()
        if manquantes:
            raise SchemaPerime(
                "schéma de la base périmé : colonnes manquantes "
                + ", ".join(manquantes[:20])
                + (" …" if len(manquantes) > 20 else "")
                + " — appliquer la migration de la version (docs/EXPLOITATION.md, schéma)"
            )

    def attendre_schema_a_jour(
        self,
        *,
        attente_s: float | None = None,
        intervalle_s: float = 5.0,
        rappel_s: float = 60.0,
        journal: Callable[[str], None] | None = None,
    ) -> None:
        """Démarrage du web et du worker en production (D-4102) : comme ``exiger_schema_a_jour``, mais une
        **migration en attente** fait attendre le processus (au plus ``attente_s`` secondes, défaut
        ``CONTROLDONE_MIGRATION_ATTENTE_S``, 600 en production, 0 ailleurs) au lieu de l'arrêter aussitôt :
        pendant une mise à jour, le service ponctuel ``migrer`` (docker-compose) applique les étapes et le
        processus démarre alors de lui-même. Message clair au début puis toutes les ``rappel_s`` secondes ; le
        service web, qui n'écoute pas encore, est vu « unhealthy » par la sonde. Au-delà du délai :
        ``MigrationEnAttente`` (le processus sort une fois, code 3). Des colonnes manquantes **sans** migration
        en attente ne se réparent pas en attendant : ``SchemaPerime`` immédiat."""
        import time

        from controldone.storage.cles import mode_execution

        if attente_s is None:
            brut = env("CONTROLDONE_MIGRATION_ATTENTE_S").strip()
            try:
                attente_s = float(brut) if brut else (600.0 if mode_execution() == "prod" else 0.0)
            except ValueError:
                attente_s = 600.0
        debut = time.monotonic()
        dernier_rappel: float | None = None
        while True:
            try:
                self.exiger_schema_a_jour()
                if dernier_rappel is not None and journal:
                    journal(
                        f"migrations appliquées après {time.monotonic() - debut:.0f} s d'attente : démarrage"
                    )
                return
            except MigrationEnAttente as exc:
                ecoule = time.monotonic() - debut
                if ecoule >= attente_s:
                    raise MigrationEnAttente(f"{exc} — attente de {attente_s:.0f} s écoulée, arrêt") from None
                if journal and (dernier_rappel is None or time.monotonic() - dernier_rappel >= rappel_s):
                    journal(
                        f"{exc} — démarrage suspendu, en attente de la migration "
                        f"(encore {attente_s - ecoule:.0f} s au plus)"
                    )
                    dernier_rappel = time.monotonic()
                time.sleep(max(0.01, min(intervalle_s, attente_s - ecoule)))

    def chemin_sqlite(self) -> Path | None:
        u = make_url(self.url)
        if u.get_backend_name() != "sqlite" or not u.database or u.database == ":memory:":
            return None
        return Path(u.database)

    def fermer(self) -> None:
        self.engine.dispose()
        if self.engine_lecture is not self.engine:
            self.engine_lecture.dispose()

    # --- sessions (usage interne au paquet storage) ---
    def session(self, *, lecture: bool = False) -> Session:
        return (self._fabrique_lecture if lecture else self._fabrique)()

    def session_systeme(self, *, effacement: bool = False) -> Session:
        """Session plateforme non filtrée (worker, purge, file sortante). Usage interne au stockage."""
        s = self.session()
        s.info[garde.CLE_SYSTEME] = True
        if effacement:
            s.info[garde.CLE_EFFACEMENT] = True
        return s

    @contextmanager
    def transaction_systeme(self, *, effacement: bool = False) -> Iterator[Session]:
        s = self.session_systeme(effacement=effacement)
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()

    # --- périmètres ---
    @contextmanager
    def tenant(self, tenant_id: str, acteur: Acteur, *, lecture: bool = False) -> Iterator[TenantScope]:
        """``TenantScope`` dans une transaction : commit à la sortie, rollback sur exception."""
        from controldone.storage.scope import TenantScope

        s = self.session(lecture=lecture)
        try:
            scope = TenantScope(s, tenant_id, acteur)
            yield scope
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()

    @contextmanager
    def operateur(self, acteur: Acteur, *, ip: str | None = None) -> Iterator[OperatorScope]:
        from controldone.storage.scope import OperatorScope

        op = OperatorScope(self, acteur, ip=ip)
        try:
            yield op
            op.commit()
        except BaseException:
            op.rollback()
            raise
        finally:
            op.close()
