"""Sauvegardes chiffrées (SQLite en ligne + coffre) et restauration. Voir ``docs/EXPLOITATION.md``.

- ``sauvegarder`` : copie **en ligne** de la base SQLite (API ``sqlite3.backup``, cohérente même pendant
  l'écriture), archive tar.gz {base, coffre}, chiffrée (Fernet, clé dérivée ``sauvegarde`` de la clé
  maîtresse) : ``controldone-AAAAMMJJTHHMMSSZ.tar.gz.enc`` (droits 0600).
- ``rotation`` : conserve la plus récente de chacun des 7 derniers jours et de chacune des 4 dernières
  semaines ISO ; supprime les autres.
- ``restaurer`` : déchiffre, vérifie et extrait (filtre ``data`` : aucun chemin absolu, ``..`` ni lien).

Ligne de commande : ``python -m controldone.storage.sauvegarde sauvegarder|restaurer|rotation …``.
PostgreSQL : utiliser ``pg_dump`` (voir l'exploitation) ; ``sauvegarder`` le refuse.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sqlite3
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import InvalidToken, MultiFernet

from controldone.storage.cles import charger_cles_maitresses, deriver_multifernet
from controldone.storage.erreurs import ErreurIntegrite

__all__ = ["NOM_RE", "restaurer", "rotation", "sauvegarder"]

NOM_RE = re.compile(r"^controldone-(\d{8}T\d{6}Z)\.tar\.gz\.enc$")


def _fernet(cles: Sequence[bytes]) -> MultiFernet:
    return deriver_multifernet(cles, "sauvegarde")


def sauvegarder(base_sqlite: Path | str, coffre: Path | str | None, destination: Path | str,
                cles: Sequence[bytes], *, now: datetime | None = None) -> Path:
    base_sqlite, destination = Path(base_sqlite), Path(destination)
    if not base_sqlite.is_file():
        raise FileNotFoundError(f"base SQLite introuvable : {base_sqlite}")
    now = now or datetime.now(UTC)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory() as tmp:
        copie = Path(tmp) / "controldone.db"
        src = sqlite3.connect(str(base_sqlite))
        dst = sqlite3.connect(str(copie))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        tampon = io.BytesIO()
        with tarfile.open(fileobj=tampon, mode="w:gz") as tar:
            tar.add(copie, arcname="base/controldone.db")
            if coffre is not None and Path(coffre).is_dir():
                tar.add(Path(coffre), arcname="coffre")
        jeton = _fernet(cles).encrypt(tampon.getvalue())
    cible = destination / f"controldone-{now.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.gz.enc"
    fd = os.open(cible, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(jeton)
    return cible


def _date(p: Path) -> datetime | None:
    m = NOM_RE.match(p.name)
    return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) if m else None


def rotation(destination: Path | str, *, jours: int = 7, semaines: int = 4) -> list[Path]:
    """Applique la politique de conservation ; renvoie les fichiers supprimés."""
    sauvegardes = sorted(((d, p) for p in Path(destination).glob("controldone-*.tar.gz.enc")
                          if (d := _date(p)) is not None), reverse=True)
    garder: set[Path] = set()
    vus_jours: list[object] = []
    vus_semaines: list[object] = []
    for d, p in sauvegardes:  # du plus récent au plus ancien
        jour = d.date()
        semaine = d.isocalendar()[:2]
        if jour not in vus_jours and len(vus_jours) < jours:
            vus_jours.append(jour)
            garder.add(p)
        if semaine not in vus_semaines and len(vus_semaines) < semaines:
            vus_semaines.append(semaine)
            garder.add(p)
    supprimes = [p for _, p in sauvegardes if p not in garder]
    for p in supprimes:
        p.unlink()
    return supprimes


def restaurer(archive: Path | str, cible: Path | str, cles: Sequence[bytes]) -> Path:
    """Déchiffre et extrait dans ``cible`` (``cible/base/controldone.db``, ``cible/coffre/``)."""
    cible = Path(cible)
    try:
        clair = _fernet(cles).decrypt(Path(archive).read_bytes())
    except InvalidToken as exc:
        raise ErreurIntegrite("sauvegarde indéchiffrable (clé incorrecte ou fichier altéré)") from exc
    cible.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(clair), mode="r:gz") as tar:
        for membre in tar.getmembers():
            if not (membre.name == "base" or membre.name.startswith(("base/", "coffre"))):
                raise ErreurIntegrite(f"entrée inattendue dans l'archive : {membre.name!r}")
        tar.extractall(cible, filter="data")
    base = cible / "base" / "controldone.db"
    con = sqlite3.connect(str(base))
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if ok != "ok":
        raise ErreurIntegrite("base restaurée corrompue")
    return cible


def main(argv: Sequence[str] | None = None) -> int:
    from controldone.config import get_settings
    from controldone.storage.db import Database

    parser = argparse.ArgumentParser(prog="python -m controldone.storage.sauvegarde")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("sauvegarder")
    b.add_argument("--destination", default=None)
    b.add_argument("--sans-rotation", action="store_true")
    r = sub.add_parser("restaurer")
    r.add_argument("archive")
    r.add_argument("cible")
    rot = sub.add_parser("rotation")
    rot.add_argument("--destination", default=None)
    args = parser.parse_args(argv)
    data_dir = Path(get_settings().data_dir)
    cles = charger_cles_maitresses(data_dir=data_dir)
    destination = Path(getattr(args, "destination", None) or data_dir / "sauvegardes")
    if args.cmd == "sauvegarder":
        db = Database()
        chemin = db.chemin_sqlite()
        db.fermer()
        if chemin is None:
            print("base non SQLite : utiliser pg_dump (voir docs/EXPLOITATION.md)", file=sys.stderr)
            return 2
        sortie = sauvegarder(chemin, data_dir / "coffre", destination, cles)
        print(sortie)
        if not args.sans_rotation:
            for p in rotation(destination):
                print(f"supprimée : {p}")
    elif args.cmd == "restaurer":
        print(restaurer(args.archive, args.cible, cles))
    else:
        for p in rotation(destination):
            print(f"supprimée : {p}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
