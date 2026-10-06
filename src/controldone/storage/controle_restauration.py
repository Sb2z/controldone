"""Contrôle approfondi d'un répertoire restauré (``sauvegarde.restaurer``) — D-3304.

Ce qui est vérifié, sans rien modifier d'autre que les fichiers WAL de la base restaurée :

- ``PRAGMA integrity_check`` de ``base/controldone.db`` ; PostgreSQL (D-3501) : la base où ``base/controldone.dump``
  a été chargé (``base_url``), comparée de la même façon (lignes, audit, références) ;
- nombre de lignes de chaque table égal à celui de l'instantané inscrit au manifeste ;
- chaîne d'audit (``verifier_chaine``) intacte, même nombre d'entrées et même tête qu'au manifeste ;
- chaque objet du coffre **se déchiffre** avec les clés fournies et son SHA-256 en clair est sa référence ;
- chaque fichier et chaque texte de page non purgé que la base référence est présent dans le coffre.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from controldone.storage.erreurs import ErreurIntegrite

__all__ = ["RapportControle", "controler"]


@dataclass
class RapportControle:
    cible: Path
    integrite: str = "non vérifiée"
    tables: dict[str, int] = field(default_factory=dict)
    audit_entrees: int = 0
    objets_coffre: int = 0
    octets_coffre: int = 0
    references: int = 0
    problemes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problemes

    def lignes(self) -> list[str]:
        sortie = [
            f"répertoire restauré : {self.cible}",
            f"intégrité de la base: {self.integrite}",
            f"tables              : {len(self.tables)} ({sum(self.tables.values())} lignes)",
            f"journal d'audit     : {self.audit_entrees} entrées",
            f"coffre              : {self.objets_coffre} objets déchiffrés ({self.octets_coffre} octets en clair)",
            f"références          : {self.references} fichiers et textes référencés par la base",
            "résultat            : " + ("CONFORME" if self.ok else "EN ÉCHEC"),
        ]
        return sortie + [f"  - {p}" for p in self.problemes]


def _references(base: Path) -> list[tuple[str, str, str]]:
    """``(client, espace, sha)`` des contenus non purgés référencés par la base."""
    con = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        refs: list[tuple[str, str, str]] = []
        if "fichiers" in tables:
            refs += [(t, "fichiers", r) for t, r in con.execute(
                "SELECT tenant_id, coffre_ref FROM fichiers WHERE coffre_ref IS NOT NULL AND purge_le IS NULL")]
        if "pages" in tables:
            refs += [(t, "textes", r) for t, r in con.execute(
                "SELECT tenant_id, texte_ref FROM pages WHERE texte_ref IS NOT NULL AND purge_le IS NULL")]
    finally:
        con.close()
    return refs


def _references_sql(url: str) -> list[tuple[str, str, str]]:
    """Comme ``_references``, par SQLAlchemy (base PostgreSQL chargée)."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.pool import NullPool

    moteur = create_engine(url, poolclass=NullPool, future=True)
    try:
        tables = set(inspect(moteur).get_table_names())
        refs: list[tuple[str, str, str]] = []
        with moteur.connect() as con:
            if "fichiers" in tables:
                refs += [(t, "fichiers", r) for t, r in con.execute(text(
                    "SELECT tenant_id, coffre_ref FROM fichiers WHERE coffre_ref IS NOT NULL AND purge_le IS NULL"))]
            if "pages" in tables:
                refs += [(t, "textes", r) for t, r in con.execute(text(
                    "SELECT tenant_id, texte_ref FROM pages WHERE texte_ref IS NOT NULL AND purge_le IS NULL"))]
    finally:
        moteur.dispose()
    return refs


def controler(cible: Path | str, cles: Any, *, base_url: str | None = None) -> RapportControle:
    """Contrôle ``cible`` (sortie de ``restaurer``) ; ne lève pas : voir ``rapport.problemes``. Archive
    PostgreSQL : ``base_url`` désigne la base où le dump a été chargé (``restaurer_postgresql``)."""
    from controldone.storage.audit import verifier_chaine
    from controldone.storage.db import Database
    from controldone.storage.sauvegarde import MANIFESTE, instantane_base, instantane_postgresql
    from controldone.storage.vault import ESPACES, FileVault

    cible = Path(cible)
    rapport = RapportControle(cible=cible)
    base = cible / "base" / "controldone.db"
    dump = cible / "base" / "controldone.dump"
    if not base.is_file() and dump.is_file():
        if not base_url:
            rapport.problemes.append("base PostgreSQL non chargée : indiquer l'URL de la base où le dump a été "
                                     "restauré (--base-cible / --base-url)")
            return rapport
    elif not base.is_file():
        rapport.problemes.append("base absente")
        return rapport
    postgresql = not base.is_file()
    manifeste: dict[str, Any] = {}
    if (cible / MANIFESTE).is_file():
        manifeste = json.loads((cible / MANIFESTE).read_text(encoding="utf-8"))
    else:
        rapport.problemes.append("manifeste absent : comptes de lignes non comparables (archive antérieure à D-3301)")

    try:
        etat = instantane_postgresql(base_url) if postgresql else instantane_base(base)  # type: ignore[arg-type]
    except Exception as exc:  # base injoignable
        rapport.problemes.append(f"base illisible : {type(exc).__name__}")
        return rapport
    rapport.integrite, rapport.tables = etat["integrite"], etat["tables"]
    if etat["integrite"] != "ok":
        rapport.problemes.append(f"intégrité de la base : {etat['integrite']}")
    attendu = manifeste.get("base", {})
    for t, n in sorted((attendu.get("tables") or {}).items()):
        if rapport.tables.get(t) != n:
            rapport.problemes.append(f"table {t} : {rapport.tables.get(t)} lignes au lieu de {n}")
    for t in sorted(set(rapport.tables) - set(attendu.get("tables") or rapport.tables)):
        rapport.problemes.append(f"table {t} absente de l'instantané")

    # chaîne d'audit
    db = Database(base_url if postgresql else f"sqlite:///{base}")
    try:
        s = db.session_systeme()
        try:
            anomalies = verifier_chaine(s)
        finally:
            s.close()
    finally:
        db.fermer()
    rapport.audit_entrees = etat["audit"]["entrees"]
    rapport.problemes += [f"audit, entrée {a.id} : {a.motif}" for a in anomalies[:20]]
    audit_attendu = attendu.get("audit") or {}
    if audit_attendu and (audit_attendu.get("entrees"), audit_attendu.get("tete")) != (
            etat["audit"]["entrees"], etat["audit"]["tete"]):
        rapport.problemes.append("journal d'audit différent de l'instantané (nombre d'entrées ou tête)")

    # coffre : chaque objet se déchiffre et correspond à sa référence
    vault = FileVault(cible / "coffre", cles)
    presents: set[tuple[str, str, str]] = set()
    for client in vault.clients():
        for espace in ESPACES:
            for sha in vault.lister(client, espace=espace):
                presents.add((client, espace, sha))
                try:
                    rapport.octets_coffre += len(vault.lire(client, sha, espace=espace))
                    rapport.objets_coffre += 1
                except (ErreurIntegrite, OSError) as exc:
                    rapport.problemes.append(f"coffre {client}/{espace}/{sha[:12]}… : {exc}")
    refs = _references_sql(base_url) if postgresql else _references(base)  # type: ignore[arg-type]
    rapport.references = len(refs)
    manquants = sorted(set(refs) - presents)
    rapport.problemes += [f"contenu référencé absent du coffre : {c}/{e}/{s[:12]}…" for c, e, s in manquants[:20]]
    if len(manquants) > 20:
        rapport.problemes.append(f"… et {len(manquants) - 20} autres contenus absents")
    return rapport
