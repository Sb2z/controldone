"""Exercice de restauration de bout en bout (``make restauration-test``, ``controldone sauvegarde exercice``) —
D-3305. Une sauvegarde jamais restaurée n'est pas une sauvegarde.

Hors ligne, dans un répertoire temporaire, avec une clé maîtresse **neuve** tenue seulement dans
l'environnement des sous-processus (jamais écrite dans les données ni dans l'archive) ; ``var/demo_web`` n'est
jamais touché. Étapes :

1. base de démonstration fictive neuve : ``controldone init-demo`` dans ``<travail>/source`` ;
2. empreintes de la source : lignes par table, tête de l'audit, SHA-256 de chaque fichier du coffre et des
   traces d'envoi ;
3. ``controldone sauvegarde sauvegarder --verification-profonde`` (création, relecture, restauration d'essai) ;
4. contrôles négatifs : mauvaise clé refusée, archive altérée d'un octet refusée, aucune clé dans l'archive ;
5. **effacement** de la source, puis ``controldone sauvegarde restaurer --controler`` dans un nouvel endroit ;
6. comparaison avec la source : lignes par table, tête de l'audit, octets de chaque fichier du coffre ;
7. ``controldone serve`` sur les données restaurées : ``/sante``, connexion du fondateur avec son second facteur
   (le secret TOTP chiffré se déchiffre), page ``/admin``, connexion d'un client, rapport publié rendu en HTML et
   PDF (lu et déchiffré depuis le coffre restauré).

Sortie : un compte rendu étape par étape avec les durées (mesure du temps de restauration) ; code 0 si tout est
conforme, 1 sinon.

PostgreSQL (D-3501, ``--postgres <url d'un serveur jetable>`` ou ``CONTROLDONE_EXERCICE_PG_URL``) : même parcours,
la base source et la base restaurée étant deux bases créées pour l'occasion sur ce serveur (droit ``CREATEDB``)
et supprimées à la fin ; la sauvegarde passe par ``pg_dump``, la restauration par ``pg_restore`` dans la base
vide, la vérification profonde charge le dump dans une troisième base jetable. Serveur jetable local :
``scripts/pg_jetable.sh`` (``make restauration-test-pg``). Ne jamais viser un serveur de production.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from controldone.config import RACINE_DEPOT

__all__ = ["ResultatExercice", "executer_exercice", "main"]

EMAIL_CLIENT = "admin@ateliers-demo.test"  # client de démonstration dont le rapport est publié (demo_init)


class EchecExercice(AssertionError):
    pass


@dataclass
class ResultatExercice:
    etapes: list[tuple[str, float, str]] = field(default_factory=list)  # (étape, durée s, détail)
    echec: str | None = None
    travail: Path | None = None

    @property
    def ok(self) -> bool:
        return self.echec is None

    def lignes(self) -> list[str]:
        sortie = ["Exercice de restauration ControlDOne — DONNÉES FICTIVES", ""]
        sortie += [f"  [ok] {nom:44s} {duree:7.2f} s  {detail}" for nom, duree, detail in self.etapes]
        total = sum(d for _, d, _ in self.etapes)
        restauration = sum(d for n, d, _ in self.etapes if n.startswith(("restauration", "démarrage du web")))
        sortie += [
            "",
            f"  durée totale {total:.1f} s ; restauration + contrôle + démarrage du web {restauration:.1f} s",
        ]
        sortie.append("  RÉSULTAT : " + ("CONFORME" if self.ok else f"EN ÉCHEC — {self.echec}"))
        return sortie


def _verifier(condition: bool, message: str) -> None:
    if not condition:
        raise EchecExercice(message)


def _environnement(
    travail: Path,
    donnees: Path,
    base: Path | str,
    cle: str,
    secret_session: str,
    pg_serveur: str | None = None,
) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CONTROLDONE_", "BACKUP_")) and k not in ("ANTHROPIC_API_KEY",)
    }
    env.update(
        {
            "CONTROLDONE_ENV": "dev",
            "CONTROLDONE_ENV_FILE": str(travail / "aucun.env"),  # aucun .env du poste n'est lu
            "CONTROLDONE_MASTER_KEY": cle,
            "CONTROLDONE_SECRET_KEY": secret_session,
            "CONTROLDONE_DATA_DIR": str(donnees),
            "CONTROLDONE_DATABASE_URL": base if isinstance(base, str) else f"sqlite:///{base}",
            "CONTROLDONE_TMP_DIR": str(travail / "tmp"),
            "PYTHONPATH": os.pathsep.join(
                filter(None, [str(RACINE_DEPOT / "src"), os.environ.get("PYTHONPATH")])
            ),
        }
    )
    if pg_serveur:  # vérification profonde : chargement d'essai du dump dans une base jetable
        env["BACKUP_PG_VERIFICATION_URL"] = pg_serveur
    return env


def _cli(env: dict[str, str], travail: Path, *args: str, timeout: float = 300) -> str:
    p = subprocess.run(
        [sys.executable, "-m", "controldone.cli", *args],
        env=env,
        cwd=travail,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        raise EchecExercice(
            f"controldone {' '.join(args[:2])} : code {p.returncode} — "
            f"{(p.stderr or p.stdout).strip()[-600:]}"
        )
    return p.stdout


def _identifiants(sortie: str) -> dict[str, str]:
    def champ(nom: str) -> str:
        m = re.search(rf"^\s+{nom}\s*:\s*(\S+)\s*$", sortie, re.M)
        _verifier(m is not None, f"init-demo : « {nom} » introuvable dans la sortie")
        return m.group(1)  # type: ignore[union-attr]

    m = re.search(rf"^\s+{re.escape(EMAIL_CLIENT)}\s+(\S+)\s", sortie, re.M)
    _verifier(m is not None, f"init-demo : compte {EMAIL_CLIENT} introuvable")
    return {
        "fondateur_email": champ("adresse"),
        "fondateur_mdp": champ("mot de passe"),
        "totp": champ("secret TOTP"),
        "client_mdp": m.group(1),
    }  # type: ignore[union-attr]


def _empreintes_arbre(racine: Path) -> dict[str, str]:
    return {
        p.relative_to(racine).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(racine.rglob("*"))
        if p.is_file() and not p.name.startswith(".tmp-")
    }


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _jeton(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    _verifier(m is not None, "jeton CSRF absent de la page")
    return m.group(1)  # type: ignore[union-attr]


def _parcours_web(url: str, ids: dict[str, str]) -> str:
    import httpx

    from controldone.auth import code_totp

    with httpx.Client(base_url=url, timeout=30, follow_redirects=False) as c:
        r = c.post(
            "/connexion",
            data={
                "csrf": _jeton(c.get("/connexion").text),
                "email": ids["fondateur_email"],
                "mot_de_passe": ids["fondateur_mdp"],
            },
        )
        _verifier(
            r.status_code == 303 and r.headers.get("location") == "/connexion/totp",
            f"connexion du fondateur : {r.status_code}",
        )
        r = c.post(
            "/connexion/totp",
            data={"csrf": _jeton(c.get("/connexion/totp").text), "code": code_totp(ids["totp"])},
        )
        _verifier(
            r.status_code == 303 and r.headers.get("location") == "/admin",
            f"second facteur du fondateur (secret TOTP chiffré) : {r.status_code}",
        )
        r = c.get("/admin")
        _verifier(r.status_code == 200, f"/admin : {r.status_code}")
    with httpx.Client(base_url=url, timeout=60, follow_redirects=False) as c:
        r = c.post(
            "/connexion",
            data={
                "csrf": _jeton(c.get("/connexion").text),
                "email": EMAIL_CLIENT,
                "mot_de_passe": ids["client_mdp"],
            },
        )
        _verifier(
            r.status_code == 303 and r.headers.get("location") == "/espace",
            f"connexion client : {r.status_code}",
        )
        r = c.get("/espace/dossiers")
        _verifier(r.status_code == 200, f"/espace/dossiers : {r.status_code}")
        page = c.get("/espace/rapports")
        _verifier(page.status_code == 200, f"/espace/rapports : {page.status_code}")
        m = re.search(r"/espace/rapports/([A-Za-z0-9_-]+)/html", page.text)
        _verifier(m is not None, "aucun rapport publié sur /espace/rapports")
        action = m.group(1)  # type: ignore[union-attr]
        html = c.get(f"/espace/rapports/{action}/html")
        _verifier(html.status_code == 200 and "FICTIF" in html.text, f"rapport HTML : {html.status_code}")
        pdf = c.get(f"/espace/rapports/{action}/pdf")
        _verifier(
            pdf.status_code == 200 and pdf.content.startswith(b"%PDF"), f"rapport PDF : {pdf.status_code}"
        )
    return f"fondateur + TOTP, /admin, client, rapport {action} (HTML {len(html.content)} o, PDF {len(pdf.content)} o)"


def _demarrer_web(env: dict[str, str], travail: Path, journal: Path) -> tuple[subprocess.Popen[bytes], str]:
    import httpx

    port = _port_libre()
    with journal.open("wb") as sortie:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "controldone.cli",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--sans-worker",
            ],
            env=env,
            cwd=travail,
            stdout=sortie,
            stderr=subprocess.STDOUT,
        )
    url = f"http://127.0.0.1:{port}"
    fin = time.monotonic() + 90
    while time.monotonic() < fin:
        if proc.poll() is not None:
            raise EchecExercice(
                f"le web s'est arrêté (code {proc.returncode}) : {journal.read_text(errors='replace')[-600:]}"
            )
        try:
            if httpx.get(url + "/sante", timeout=2).status_code == 200:
                return proc, url
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    proc.terminate()
    raise EchecExercice("le web ne répond pas sur /sante après 90 s")


def _interdit(chemin: Path) -> bool:
    demo_web = (RACINE_DEPOT / "var" / "demo_web").resolve()
    c = chemin.resolve()
    return c == demo_web or c.is_relative_to(demo_web) or demo_web.is_relative_to(c)


def executer_exercice(
    travail: Path, *, journal: Callable[[str], None] | None = None, pg_serveur: str | None = None
) -> ResultatExercice:
    """Déroule l'exercice dans ``travail`` (vide ou absent) ; ``pg_serveur`` : sur PostgreSQL (serveur jetable)."""
    import secrets

    from cryptography.fernet import Fernet

    from controldone.storage.controle_restauration import controler
    from controldone.storage.sauvegarde import (
        MANIFESTE,
        creer_base_pg,
        instantane_base,
        instantane_postgresql,
        supprimer_base_pg,
        verifier,
    )

    res = ResultatExercice(travail=travail)
    if _interdit(travail) or (travail.exists() and (not travail.is_dir() or any(travail.iterdir()))):
        res.echec = f"répertoire de travail interdit (var/demo_web) ou non vide : {travail}"
        return res
    travail.mkdir(parents=True, exist_ok=True, mode=0o700)
    (travail / "tmp").mkdir(mode=0o700)
    cle = Fernet.generate_key().decode()
    secret_session = hashlib.sha256(os.urandom(32)).hexdigest()
    source, sauvegardes, restauree = travail / "source", travail / "sauvegardes", travail / "restauree"
    suffixe = secrets.token_hex(4)
    bases_pg = {"source": f"cd_exercice_src_{suffixe}", "restauree": f"cd_exercice_rest_{suffixe}"}
    urls: dict[str, str] = {}
    base_source: Path | str = source / "controldone.db"
    if pg_serveur:
        try:
            urls["source"] = base_source = creer_base_pg(pg_serveur, bases_pg["source"])
        except Exception as exc:
            res.echec = (
                f"serveur PostgreSQL de l'exercice injoignable : {type(exc).__name__}: {str(exc)[:300]}"
            )
            return res
    env_source = _environnement(travail, source, base_source, cle, secret_session, pg_serveur)

    def etat_base(nom: str, fichier: Path) -> dict[str, Any]:
        return instantane_postgresql(urls[nom]) if pg_serveur else instantane_base(fichier)

    def etape(nom: str, fn: Callable[[], str]) -> None:
        debut = time.monotonic()
        detail = fn()
        res.etapes.append((nom, time.monotonic() - debut, detail))
        if journal:
            journal(f"  [ok] {nom} — {detail}")

    etat: dict[str, Any] = {}
    try:

        def init() -> str:
            etat["ids"] = _identifiants(_cli(env_source, travail, "init-demo"))
            _verifier(
                not (source / "dev_master.key").exists(), "clé de développement écrite dans les données"
            )
            return "2 clients fictifs, fondateur avec TOTP" + (" — PostgreSQL" if pg_serveur else "")

        etape("base de démonstration (init-demo)", init)

        def empreintes() -> str:
            etat["base"] = etat_base("source", source / "controldone.db")
            etat["coffre"] = _empreintes_arbre(source / "coffre")
            etat["sorties"] = _empreintes_arbre(source / "outbox_envoyee")
            _verifier(etat["base"]["integrite"] == "ok", "base source corrompue")
            _verifier(len(etat["coffre"]) > 0 and len(etat["sorties"]) > 0, "coffre ou traces d'envoi vides")
            return (
                f"{len(etat['base']['tables'])} tables, {sum(etat['base']['tables'].values())} lignes, "
                f"{len(etat['coffre'])} objets du coffre, {len(etat['sorties'])} traces d'envoi"
            )

        etape("empreintes de la source", empreintes)

        def sauvegarde() -> str:
            _cli(
                env_source,
                travail,
                "sauvegarde",
                "sauvegarder",
                "--destination",
                str(sauvegardes),
                "--verification-profonde",
            )
            archives = sorted(sauvegardes.glob("controldone-*.tar.gz.enc"))
            _verifier(len(archives) == 1, f"{len(archives)} archive(s) au lieu d'une")
            _verifier(Path(str(archives[0]) + ".sha256").is_file(), "empreinte .sha256 absente")
            etat["archive"] = archives[0]
            return f"{archives[0].name} ({archives[0].stat().st_size} octets), relue et restaurée à l'essai"

        etape("sauvegarde chiffrée + vérification profonde", sauvegarde)

        def negatifs() -> str:
            archive: Path = etat["archive"]
            brut = archive.read_bytes()
            _verifier(
                cle.encode() not in brut and b"SQLite format" not in brut and b"PGDMP" not in brut,
                "clé ou base en clair dans l'archive",
            )
            r = verifier(archive, [cle.encode()])
            _verifier(r.ok and r.manifeste is not None, f"vérification : {r.problemes}")
            noms = set(r.manifeste["fichiers"]) | {MANIFESTE}  # type: ignore[index]
            _verifier(
                not any(n.endswith((".key", ".env")) or "identifiants" in n for n in noms),
                "fichier de clé ou d'identifiants dans l'archive",
            )
            _verifier(not verifier(archive, [Fernet.generate_key()]).ok, "archive lisible avec une autre clé")
            alteree = travail / "alteree.tar.gz.enc"
            octets = bytearray(brut)
            octets[len(octets) // 2] ^= 0x01
            alteree.write_bytes(bytes(octets))
            _verifier(not verifier(alteree, [cle.encode()]).ok, "archive altérée acceptée")
            alteree.unlink()
            return f"{r.fichiers} fichiers conformes au manifeste ; autre clé et octet altéré refusés"

        etape("contrôles négatifs (clé, altération)", negatifs)

        def effacer() -> str:
            shutil.rmtree(source)
            _verifier(not source.exists(), "source non effacée")
            if pg_serveur:
                supprimer_base_pg(pg_serveur, bases_pg["source"])
                return "source supprimée (fichiers et base PostgreSQL)"
            return "source supprimée"

        etape("effacement de la source", effacer)

        base_restauree: Path | str = restauree / "base" / "controldone.db"
        if pg_serveur:
            urls["restauree"] = base_restauree = creer_base_pg(pg_serveur, bases_pg["restauree"])
        env_restauree = _environnement(travail, restauree, base_restauree, cle, secret_session)

        def restaurer() -> str:
            options = ["--base-cible", urls["restauree"]] if pg_serveur else []
            sortie = _cli(
                env_restauree,
                travail,
                "sauvegarde",
                "restaurer",
                str(etat["archive"]),
                str(restauree),
                *options,
                "--controler",
            )
            _verifier("CONFORME" in sortie, f"contrôle de la restauration : {sortie[-400:]}")
            return (
                "pg_restore dans une base vide, " if pg_serveur else ""
            ) + "déchiffrée, manifeste, intégrité, coffre déchiffré, audit"

        etape("restauration dans un nouvel endroit", restaurer)

        def comparer() -> str:
            apres = etat_base("restauree", restauree / "base" / "controldone.db")
            ecarts = {
                t: (n, apres["tables"].get(t))
                for t, n in etat["base"]["tables"].items()
                if apres["tables"].get(t) != n
            }
            _verifier(
                not ecarts and set(apres["tables"]) == set(etat["base"]["tables"]),
                f"lignes par table différentes : {ecarts}",
            )
            _verifier(apres["audit"] == etat["base"]["audit"], "tête de la chaîne d'audit différente")
            _verifier(_empreintes_arbre(restauree / "coffre") == etat["coffre"], "coffre restauré différent")
            _verifier(
                _empreintes_arbre(restauree / "outbox_envoyee") == etat["sorties"],
                "traces d'envoi différentes",
            )
            rapport = controler(restauree, [cle.encode()], base_url=urls.get("restauree"))
            _verifier(rapport.ok, f"contrôle : {rapport.problemes}")
            return (
                f"{len(apres['tables'])} tables identiques, audit {apres['audit']['entrees']} entrées, "
                f"{rapport.objets_coffre} objets déchiffrés, {rapport.references} références présentes"
            )

        etape("restauration : comparaison avec la source", comparer)

        def web() -> str:
            proc, url = _demarrer_web(env_restauree, travail, travail / "web.log")
            etat["web"] = proc
            etat["url"] = url
            return url

        etape("démarrage du web sur les données restaurées", web)
        etape("parcours web (connexion, rapport)", lambda: _parcours_web(etat["url"], etat["ids"]))
    except (EchecExercice, subprocess.TimeoutExpired, OSError) as exc:
        res.echec = str(exc)[:1000]
    except Exception as exc:  # base PostgreSQL de l'exercice (création, suppression)
        res.echec = f"{type(exc).__name__}: {str(exc)[:900]}"
    finally:
        proc = etat.get("web")
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if pg_serveur:
            for nom in bases_pg.values():
                try:
                    supprimer_base_pg(pg_serveur, nom)
                except Exception:  # serveur arrêté entre-temps : rien d'autre à nettoyer
                    break
    return res


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="controldone sauvegarde exercice",
        description="Exercice de restauration de bout en bout sur une base fictive.",
    )
    ap.add_argument("--repertoire", default=None, help="répertoire de travail (vide) ; défaut : temporaire")
    ap.add_argument("--garder", action="store_true", help="ne pas effacer le répertoire de travail")
    ap.add_argument(
        "--postgres",
        default=os.environ.get("CONTROLDONE_EXERCICE_PG_URL") or None,
        help="URL d'un serveur PostgreSQL JETABLE (droit CREATEDB) : exercice sur PostgreSQL",
    )
    args = ap.parse_args(argv)
    if args.repertoire:
        travail = Path(args.repertoire)
        if _interdit(travail) or (travail.exists() and (not travail.is_dir() or any(travail.iterdir()))):
            print(
                f"répertoire de travail refusé (doit être vide, hors var/demo_web) : {travail}",
                file=sys.stderr,
            )
            return 2
    else:
        travail = Path(tempfile.mkdtemp(prefix="cd-exercice-restauration-"))
    a_effacer = not args.garder
    print(f"Répertoire de travail : {travail}", flush=True)
    if args.postgres:
        print("Moteur : PostgreSQL (serveur jetable)", flush=True)
    res = executer_exercice(travail, journal=lambda m: print(m, flush=True), pg_serveur=args.postgres)
    print("\n".join(res.lignes()))
    if a_effacer and not _interdit(travail):
        shutil.rmtree(travail, ignore_errors=True)
    elif travail.exists():
        print(f"Conservé : {travail}")
    return 0 if res.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
