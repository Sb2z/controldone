"""Exercice mensuel sur une **vraie** archive de production (``controldone sauvegarde exercice-mensuel``) — D-4702.

``make restauration-test`` prouve la chaîne sur une base fictive ; cet exercice prouve que **la dernière archive
réelle** (copie locale ``/backups`` ou copie hors site téléchargée) se restaure avec la clé de production et que
l'application démarre dessus. Étapes, chacune chronométrée :

1. sélection : la plus récente ``controldone-*.tar.gz.enc`` de ``--source`` (ou ``--archive``), âge, empreinte
   SHA-256 de l'archive chiffrée comparée à son ``.sha256`` ;
2. relecture complète (déchiffrement de chaque segment, manifeste) et **clé qui l'ouvre** (rang et empreinte
   publique, ``storage.cles.empreinte_cle`` : sert au contrôle de la copie papier séquestrée, D-4703) ;
3. restauration dans un emplacement **jetable** : répertoire temporaire à côté de l'archive (même volume) ;
   PostgreSQL : base jetable créée sur ``BACKUP_PG_VERIFICATION_URL`` (droit ``CREATEDB``) ;
4. contrôle approfondi (``storage.controle_restauration``) : intégrité, lignes et audit contre le manifeste,
   chaque objet du coffre déchiffré, références présentes, traces d'envoi déchiffrées ;
5. migrations de la **copie** si l'archive est antérieure au code (comme le ferait une mise à jour) ;
6. application démarrée en **lecture seule** sur la copie : ``serve --sans-worker`` sur 127.0.0.1 (mode ``dev``,
   environnement nettoyé : aucune variable de production, aucune notification, aucun connecteur), ``/sante`` et
   ``/connexion`` ; PostgreSQL : base copiée mise en ``default_transaction_read_only`` ;
7. rendu d'un rapport publié (le plus récent) : HTML et PDF relus et déchiffrés depuis le coffre restauré ;
8. preuve de la lecture seule : lignes par table et tête de l'audit identiques avant et après ;
9. **destruction** de la copie (répertoire et base jetable), puis compte rendu daté.

Compte rendu : ``<rapports>/exercice-mensuel-AAAAMMJJTHHMMSSZ.md`` et ``.json`` (droits 0600 ; défaut
``<data_dir>/exercices``). Il ne contient **aucune donnée client** : nom et taille de l'archive, empreintes,
nombres (tables, lignes, entrées d'audit, objets), durées, empreinte publique de la clé, résultat. Codes de
sortie : 0 conforme ; 1 exercice en échec (alerte ``sauvegarde_verification_echec``) ; 2 configuration (aucune
archive, clé absente, serveur PostgreSQL de vérification non défini pour une archive PostgreSQL).

Planification : ``deploy/scheduler.sh``, premier dimanche du mois, **désactivée par défaut**
(``SCHED_EXERCICE_MENSUEL=1``). Procédure et lecture du compte rendu : ``docs/EXPLOITATION.md`` § 3.4.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["CompteRendu", "executer_exercice_mensuel", "main"]

OK, ECHEC, ECHEC_CONFIGURATION = 0, 1, 2


class EchecExercice(AssertionError):
    pass


class ConfigurationAbsente(EchecExercice):
    pass


@dataclass
class CompteRendu:
    """Compte rendu de l'exercice : nombres, empreintes et durées seulement (aucune donnée client)."""

    debut: str
    archive: str | None = None
    taille_octets: int = 0
    sha256: str | None = None
    empreinte_externe: str = "absente"
    age_h: float | None = None
    moteur: str | None = None
    cle_rang: int | None = None
    cle_empreinte: str | None = None
    manifeste: dict[str, Any] = field(default_factory=dict)
    controle: dict[str, int] = field(default_factory=dict)
    etapes: list[dict[str, Any]] = field(default_factory=list)
    remarques: list[str] = field(default_factory=list)
    echec: str | None = None
    copie_detruite: bool = False

    @property
    def ok(self) -> bool:
        return self.echec is None

    def duree(self, *prefixes: str) -> float:
        return sum(e["duree_s"] for e in self.etapes if not prefixes or e["nom"].startswith(prefixes))

    def en_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["resultat"] = "CONFORME" if self.ok else "EN ÉCHEC"
        d["duree_totale_s"] = round(self.duree(), 2)
        d["duree_remise_en_service_s"] = round(
            self.duree("restauration", "contrôle approfondi", "démarrage"), 2
        )
        return d

    def markdown(self) -> str:
        m = self.manifeste
        lignes = [
            f"# Exercice mensuel de restauration — {self.debut}",
            "",
            f"**Résultat : {'CONFORME' if self.ok else 'EN ÉCHEC — ' + str(self.echec)}**",
            "",
            "Compte rendu sans donnée client : nombres, empreintes et durées (D-4702).",
            "",
            "## Archive",
            "",
            f"- archive : `{self.archive or '—'}` ({self.taille_octets} octets), âge "
            + (f"{self.age_h:.1f} h" if self.age_h is not None else "inconnu"),
            f"- SHA-256 de l'archive chiffrée : `{self.sha256 or '—'}` (fichier .sha256 : {self.empreinte_externe})",
            f"- moteur : {self.moteur or '—'}",
            f"- clé qui l'ouvre : rang {self.cle_rang if self.cle_rang is not None else '—'} de "
            f"CONTROLDONE_MASTER_KEY, empreinte publique `{self.cle_empreinte or '—'}`",
        ]
        if m:
            lignes.append(
                f"- manifeste : instantané du {m.get('cree_le')}, {m.get('tables')} tables, {m.get('lignes')} "
                f"lignes, audit {m.get('audit')} entrées, {m.get('fichiers')} fichiers"
            )
        if self.controle:
            c = self.controle
            lignes.append(
                f"- contrôle approfondi : {c.get('objets_coffre')} objets du coffre déchiffrés, "
                f"{c.get('references')} références présentes, traces d'envoi déchiffrées : {c.get('traces')}"
            )
        lignes += ["", "## Étapes", "", "| Étape | Durée (s) | Détail |", "|---|---:|---|"]
        lignes += [f"| {e['nom']} | {e['duree_s']:.2f} | {e['detail']} |" for e in self.etapes]
        j = self.en_json()
        lignes += [
            "",
            f"Durée totale {j['duree_totale_s']:.1f} s ; restauration + contrôle + démarrage "
            f"{j['duree_remise_en_service_s']:.1f} s (ordre de grandeur du temps de remise en service, hors "
            "téléchargement).",
            "",
            "Copie jetable détruite : " + ("oui" if self.copie_detruite else "NON — à effacer à la main"),
        ]
        if self.remarques:
            lignes += ["", "## Remarques", ""] + [f"- {r}" for r in self.remarques]
        return "\n".join(lignes) + "\n"


def _cle_ouvrante(archive: Path, cles: Sequence[bytes]) -> int | None:
    """Rang de la clé maîtresse qui déchiffre le premier segment (format ``CDSAV2``), ou ``None``."""
    from cryptography.fernet import InvalidToken

    from controldone.storage.cles import deriver_multifernet
    from controldone.storage.sauvegarde import MAGIE

    with archive.open("rb") as f:
        if f.read(len(MAGIE)) != MAGIE:
            return None
        tete = f.read(4)
        if len(tete) != 4:
            return None
        jeton = f.read(min(struct.unpack(">I", tete)[0], 16 * 1024 * 1024))
    for rang, cle in enumerate(cles):
        try:
            deriver_multifernet([cle], "sauvegarde").decrypt(jeton)
            return rang
        except InvalidToken:
            continue
    return None


def _rendre_un_rapport(base_url: str, coffre: Path, cles: Sequence[bytes]) -> str:
    """Relit le rapport publié le plus récent (HTML et PDF) depuis la copie : en mémoire, rien n'est écrit."""
    from controldone.auth.roles import Acteur, Role
    from controldone.outbox.modele import StatutAction, TypeAction
    from controldone.outbox.service import FileSortante
    from controldone.services import publication
    from controldone.services.plateforme import Plateforme
    from controldone.storage import Database, FileVault

    db = Database(base_url)
    try:
        plateforme = Plateforme(db=db, vault=FileVault(coffre, cles), cles_maitresses=list(cles))
        acteur = Acteur("systeme:exercice_mensuel", Role.systeme)
        publies = FileSortante(db).lister(
            acteur, statuts=[StatutAction.envoye.value], kind=TypeAction.rapport_publication.value
        )
        if not publies:
            return ""
        action = publies[-1]  # le plus récent (ordre chronologique)
        formats = publication.formats_disponibles(action)
        tailles = []
        for fmt in ("html", "pdf"):
            if fmt not in formats:
                continue
            contenu, _, _ = publication.piece(plateforme, acteur, action.id, fmt)
            if fmt == "pdf" and not contenu.startswith(b"%PDF"):
                raise EchecExercice("rapport publié : PDF illisible")
            if fmt == "html" and b"<html" not in contenu[:4096].lower():
                raise EchecExercice("rapport publié : HTML illisible")
            tailles.append(f"{fmt.upper()} {len(contenu)} o")
        if not tailles:
            raise EchecExercice("rapport publié sans pièce HTML ni PDF")
        return "rapport publié le plus récent : " + ", ".join(tailles)
    finally:
        db.fermer()


def _get(url: str, chemin: str) -> int:
    import httpx

    return httpx.get(url + chemin, timeout=30, follow_redirects=False).status_code


def executer_exercice_mensuel(
    archive: Path,
    *,
    cles: Sequence[bytes],
    travail_parent: Path | None = None,
    pg_serveur: str | None = None,
    age_max_h: float | None = None,
    journal: Callable[[str], None] | None = None,
) -> CompteRendu:
    """Déroule l'exercice sur ``archive`` ; la copie (répertoire et base jetable) est toujours détruite."""
    from controldone.services.exercice_restauration import _demarrer_web, _environnement
    from controldone.storage.cles import empreinte_cle
    from controldone.storage.controle_restauration import controler
    from controldone.storage.sauvegarde import (
        _date,
        creer_base_pg,
        empreinte_fichier,
        instantane_base,
        instantane_postgresql,
        restaurer,
        restaurer_postgresql,
        supprimer_base_pg,
        verifier,
    )

    cr = CompteRendu(debut=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), archive=archive.name)
    parent = Path(travail_parent or archive.parent)
    travail = Path(tempfile.mkdtemp(prefix=".cd-exercice-mensuel-", dir=parent))
    os.chmod(travail, 0o700)
    (travail / "tmp").mkdir(mode=0o700)
    cible = travail / "copie"
    nom_pg = f"cd_mensuel_{secrets.token_hex(5)}"
    etat: dict[str, Any] = {}

    def etape(nom: str, fn: Callable[[], str]) -> None:
        debut = time.monotonic()
        detail = fn()
        cr.etapes.append({"nom": nom, "duree_s": round(time.monotonic() - debut, 3), "detail": detail})
        if journal:
            journal(f"  [ok] {nom} — {detail}")

    try:

        def selection() -> str:
            if not archive.is_file():
                raise ConfigurationAbsente(f"archive introuvable : {archive.name}")
            cr.taille_octets = archive.stat().st_size
            cr.sha256 = empreinte_fichier(archive)
            externe = archive.with_name(archive.name + ".sha256")
            if externe.is_file():
                attendu = externe.read_text(encoding="utf-8").split()[0] if externe.stat().st_size else ""
                cr.empreinte_externe = "conforme" if attendu == cr.sha256 else "différente"
                if cr.empreinte_externe == "différente":
                    raise EchecExercice("empreinte de l'archive différente de son fichier .sha256")
            d = _date(archive)
            if d is not None:
                cr.age_h = round((datetime.now(UTC) - d).total_seconds() / 3600, 1)
                if age_max_h is not None and cr.age_h > age_max_h:
                    raise EchecExercice(
                        f"archive la plus récente vieille de {cr.age_h:.0f} h (> {age_max_h} h)"
                    )
            return f"{archive.name}, {cr.taille_octets} octets, empreinte .sha256 {cr.empreinte_externe}"

        etape("sélection de l'archive", selection)

        def relecture() -> str:
            r = verifier(archive, cles)
            if not r.ok:
                raise EchecExercice("relecture : " + "; ".join(r.problemes[:3]))
            man = r.manifeste or {}
            base = man.get("base", {})
            cr.moteur = base.get("moteur", "sqlite") if man else "inconnu (archive sans manifeste)"
            cr.manifeste = {
                "cree_le": man.get("cree_le"),
                "tables": len(base.get("tables", {})),
                "lignes": sum(base.get("tables", {}).values()),
                "audit": base.get("audit", {}).get("entrees"),
                "fichiers": r.fichiers,
            }
            cr.cle_rang = _cle_ouvrante(archive, cles)
            if cr.cle_rang is not None:
                cr.cle_empreinte = empreinte_cle(cles[cr.cle_rang])
                if cr.cle_rang > 0:
                    cr.remarques.append(
                        f"archive ouverte par la clé de rang {cr.cle_rang} (ancienne clé après rotation) : "
                        "la garder tant que cette archive est conservée"
                    )
            return f"{r.fichiers} fichiers conformes au manifeste ({r.octets_clairs} octets en clair)"

        etape("relecture complète (déchiffrement, manifeste)", relecture)

        def restauration() -> str:
            restaurer(archive, cible, cles)
            dump = cible / "base" / "controldone.dump"
            if not dump.is_file():
                etat["url"] = f"sqlite:///{cible / 'base' / 'controldone.db'}"
                return "copie jetable SQLite (répertoire temporaire à côté de l'archive)"
            cr.moteur = "postgresql"
            if not pg_serveur:
                raise ConfigurationAbsente(
                    "archive PostgreSQL : BACKUP_PG_VERIFICATION_URL (serveur de vérification, droit "
                    "CREATEDB) est nécessaire pour la charger dans une base jetable"
                )
            etat["url"] = creer_base_pg(pg_serveur, nom_pg)
            etat["base_pg"] = True
            restaurer_postgresql(dump, etat["url"])
            return "pg_restore dans une base jetable du serveur de vérification"

        etape("restauration dans un emplacement jetable", restauration)

        def controle() -> str:
            base_url = etat["url"] if cr.moteur == "postgresql" else None
            rapport = controler(cible, cles, base_url=base_url)
            if not rapport.ok:
                raise EchecExercice("contrôle approfondi : " + "; ".join(rapport.problemes[:3]))
            cr.controle = {
                "objets_coffre": rapport.objets_coffre,
                "references": rapport.references,
                "traces": rapport.traces_dechiffrees,
                "audit": rapport.audit_entrees,
            }
            return (
                f"intégrité, {len(rapport.tables)} tables, audit {rapport.audit_entrees} entrées, "
                f"{rapport.objets_coffre} objets déchiffrés, {rapport.references} références"
            )

        etape("contrôle approfondi", controle)

        def migrations() -> str:
            from controldone.storage import Database

            db = Database(etat["url"])
            try:
                attente = db.migrations_en_attente()
                if not attente:
                    return "aucune étape en attente : archive au niveau du code"
                db.creer_schema(migrer=False)
                db.migrer()
                cr.remarques.append(
                    f"archive antérieure au code : {len(attente)} étape(s) de migration appliquée(s) à la copie"
                )
                return f"{len(attente)} étape(s) appliquée(s) à la copie : " + ", ".join(
                    f"{m.version:04d}" for m in attente
                )
            finally:
                db.fermer()

        etape("migrations de la copie", migrations)

        def figer() -> dict[str, Any]:
            if cr.moteur == "postgresql":
                return instantane_postgresql(etat["url"])
            return instantane_base(cible / "base" / "controldone.db")

        if cr.moteur == "postgresql":  # lecture seule imposée par le serveur pour toute nouvelle session
            from controldone.storage.sauvegarde import base_pg_lecture_seule

            base_pg_lecture_seule(pg_serveur, nom_pg)  # type: ignore[arg-type]
        etat["avant"] = figer()

        def demarrage() -> str:
            cle = ",".join(c.decode() for c in cles)
            env = _environnement(travail, cible, etat["url"], cle, secrets.token_hex(32))
            proc, url = _demarrer_web(env, travail, travail / "web.log")
            etat["web"], etat["url_web"] = proc, url
            codes = {c: _get(url, c) for c in ("/sante", "/connexion")}
            if any(v != 200 for v in codes.values()):
                raise EchecExercice(f"application démarrée mais pages en erreur : {codes}")
            return "serve --sans-worker sur 127.0.0.1 : /sante 200, /connexion 200"

        etape("démarrage de l'application (lecture seule)", demarrage)

        def rendu() -> str:
            detail = _rendre_un_rapport(etat["url"], cible / "coffre", cles)
            if not detail:
                cr.remarques.append("aucun rapport publié dans l'archive : rendu non éprouvé")
                return "aucun rapport publié dans l'archive"
            return detail

        etape("rendu d'un rapport publié", rendu)

        def lecture_seule() -> str:
            proc = etat.pop("web", None)
            if proc is not None:
                proc.terminate()
                proc.wait(15)
            apres = figer()
            avant = etat["avant"]
            if apres["tables"] != avant["tables"] or apres["audit"] != avant["audit"]:
                ecarts = sorted(
                    t
                    for t in set(avant["tables"]) | set(apres["tables"])
                    if avant["tables"].get(t) != apres["tables"].get(t)
                )
                raise EchecExercice(
                    f"la copie a été modifiée pendant l'exercice (tables : {', '.join(ecarts)})"
                )
            return f"{len(apres['tables'])} tables et tête de l'audit identiques avant et après"

        etape("lecture seule vérifiée", lecture_seule)
    except ConfigurationAbsente as exc:
        cr.echec = f"configuration : {exc}"
    except EchecExercice as exc:
        cr.echec = str(exc)[:600]
    except Exception as exc:
        cr.echec = f"{type(exc).__name__}: {str(exc)[:500]}"
    finally:
        debut = time.monotonic()
        proc = etat.pop("web", None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
        detruite = True
        if etat.get("base_pg") and pg_serveur:
            try:
                supprimer_base_pg(pg_serveur, nom_pg)
            except Exception:
                detruite = False
                cr.remarques.append(f"base jetable {nom_pg} NON supprimée : la supprimer à la main")
        shutil.rmtree(travail, ignore_errors=True)
        detruite = detruite and not travail.exists()
        cr.copie_detruite = detruite
        cr.etapes.append(
            {
                "nom": "destruction de la copie",
                "duree_s": round(time.monotonic() - debut, 3),
                "detail": (
                    "répertoire et base jetable supprimés" if etat.get("base_pg") else "répertoire supprimé"
                )
                if detruite
                else "INCOMPLÈTE",
            }
        )
        if not detruite and cr.echec is None:
            cr.echec = "copie jetable non détruite"
    return cr


def ecrire_compte_rendu(cr: CompteRendu, dossier: Path) -> tuple[Path, Path]:
    dossier.mkdir(parents=True, exist_ok=True, mode=0o700)
    horodatage = cr.debut.replace("-", "").replace(":", "")
    md = dossier / f"exercice-mensuel-{horodatage}.md"
    js = dossier / f"exercice-mensuel-{horodatage}.json"
    for chemin, contenu in (
        (md, cr.markdown()),
        (js, json.dumps(cr.en_json(), ensure_ascii=False, indent=2)),
    ):
        fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenu)
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    from controldone.config import env, get_settings
    from controldone.storage.cles import charger_cles_maitresses
    from controldone.storage.erreurs import CleManquante
    from controldone.storage.sauvegarde import alerter, derniere_sauvegarde

    ap = argparse.ArgumentParser(
        prog="controldone sauvegarde exercice-mensuel",
        description="Exercice mensuel sur la dernière vraie archive : restauration jetable, contrôle approfondi, "
        "application en lecture seule, rendu d'un rapport, destruction, compte rendu daté sans donnée client.",
    )
    ap.add_argument("--archive", default=None, help="archive précise (défaut : la plus récente de --source)")
    ap.add_argument(
        "--source",
        default=None,
        help="répertoire des archives : copie locale ou copie hors site téléchargée "
        "(défaut : BACKUP_DIR, sinon <data_dir>/sauvegardes)",
    )
    ap.add_argument(
        "--rapports", default=None, help="où écrire le compte rendu (défaut : <data_dir>/exercices)"
    )
    ap.add_argument(
        "--repertoire", default=None, help="où créer la copie jetable (défaut : à côté de l'archive)"
    )
    ap.add_argument("--age-max-h", type=float, default=None, help="échec si l'archive est plus ancienne")
    args = ap.parse_args(argv)

    data_dir = Path(get_settings().data_dir)
    rapports = Path(args.rapports or data_dir / "exercices")
    if not env("CONTROLDONE_MASTER_KEY", "").strip():
        print(
            "CONTROLDONE_MASTER_KEY absente : l'exercice se fait avec la clé de production", file=sys.stderr
        )
        return ECHEC_CONFIGURATION
    try:
        cles = charger_cles_maitresses(data_dir=data_dir)
    except CleManquante as exc:
        print(f"clé maîtresse : {exc}", file=sys.stderr)
        return ECHEC_CONFIGURATION
    if args.archive:
        archive: Path | None = Path(args.archive)
    else:
        source = Path(args.source or env("BACKUP_DIR", "").strip() or data_dir / "sauvegardes")
        archive = derniere_sauvegarde(source) if source.is_dir() else None
        if archive is None:
            print(f"aucune archive controldone-*.tar.gz.enc dans {source}", file=sys.stderr)
            return ECHEC_CONFIGURATION
    print(f"Exercice mensuel sur {archive.name}", flush=True)
    cr = executer_exercice_mensuel(
        archive,
        cles=cles,
        travail_parent=Path(args.repertoire) if args.repertoire else None,
        pg_serveur=env("BACKUP_PG_VERIFICATION_URL", "").strip() or None,
        age_max_h=args.age_max_h,
        journal=lambda m: print(m, flush=True),
    )
    md, _ = ecrire_compte_rendu(cr, rapports)
    print(cr.markdown())
    print(f"Compte rendu : {md}")
    if cr.ok:
        return OK
    if cr.echec and cr.echec.startswith("configuration"):
        return ECHEC_CONFIGURATION
    with contextlib.suppress(Exception):
        alerter(
            "sauvegarde_verification_echec",
            f"Exercice mensuel en échec sur {archive.name} : {cr.echec}"[:500],
            {"archive": archive.name, "exercice": "mensuel"},
        )
    return ECHEC


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
