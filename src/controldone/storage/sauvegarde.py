"""Sauvegardes chiffrées (SQLite en ligne + coffre) et restauration. Voir ``docs/EXPLOITATION.md``.

- ``sauvegarder`` : copie **en ligne** de la base SQLite (API ``sqlite3.backup``, cohérente même pendant
  l'écriture) dans un répertoire temporaire **sur le volume de destination** (jamais un tmpfs ``/tmp``),
  puis archive tar.gz {base, coffre} écrite **en flux** et chiffrée **par segments** :
  ``controldone-AAAAMMJJTHHMMSSZ.tar.gz.enc`` (droits 0600). La mémoire utilisée ne dépend pas de la taille
  du coffre (un segment de 1 Mio à la fois) — F-02, D-1320.
- ``rotation`` : conserve la plus récente de chacun des 7 derniers jours et de chacune des 4 dernières
  semaines ISO ; supprime les autres.
- ``restaurer`` : déchiffre et extrait **en flux** (filtre ``data`` : aucun chemin absolu, ``..`` ni lien ;
  seules les entrées ``base/`` et ``coffre/`` sont admises). Les archives de l'ancien format (un seul jeton
  Fernet) restent restaurables.

Format ``CDSAV2`` (documenté dans ``docs/EXPLOITATION.md`` §3) :

```
en-tête   : b"CDSAV2\n"
segment*  : longueur (4 octets, gros-boutiste) || jeton Fernet(segment clair)
clair     : numéro de segment (8 octets, gros-boutiste) || drapeau final (1 octet : 0 ou 1) || données
```

Chaque segment est authentifié (Fernet : AES-128-CBC + HMAC-SHA256, clé dérivée ``sauvegarde`` de la clé
maîtresse, rotation par ``MultiFernet``) ; le numéro empêche de réordonner ou de dupliquer des segments, le
drapeau final de tronquer l'archive sans le détecter.

Ligne de commande : ``python -m controldone.storage.sauvegarde sauvegarder|restaurer|rotation …``. Un échec
de la sauvegarde émet une alerte au fondateur (``sauvegarde_echec``) et renvoie le code 1.
PostgreSQL : utiliser ``pg_dump`` (voir l'exploitation) ; ``sauvegarder`` le refuse.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sqlite3
import struct
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from cryptography.fernet import InvalidToken, MultiFernet

from controldone.storage.cles import charger_cles_maitresses, deriver_multifernet
from controldone.storage.erreurs import ErreurIntegrite

__all__ = ["MAGIE", "NOM_RE", "TAILLE_SEGMENT", "restaurer", "rotation", "sauvegarder"]

NOM_RE = re.compile(r"^controldone-(\d{8}T\d{6}Z)\.tar\.gz\.enc$")
MAGIE = b"CDSAV2\n"
TAILLE_SEGMENT = 1024 * 1024
_LONGUEUR_MAX = 8 * TAILLE_SEGMENT  # jeton Fernet d'un segment : < 2 × clair (base64 + en-tête)


def _fernet(cles: Sequence[bytes]) -> MultiFernet:
    return deriver_multifernet(cles, "sauvegarde")


class _EcrivainChiffre(io.RawIOBase):
    """Flux en écriture : regroupe en segments de ``TAILLE_SEGMENT`` et écrit chaque segment chiffré."""

    def __init__(self, sortie: BinaryIO, fernet: MultiFernet, taille: int = TAILLE_SEGMENT) -> None:
        self.sortie, self.fernet, self.taille = sortie, fernet, taille
        self.tampon = bytearray()
        self.numero = 0
        self.sortie.write(MAGIE)

    def writable(self) -> bool:
        return True

    def write(self, b: bytes) -> int:  # type: ignore[override]
        self.tampon += b
        while len(self.tampon) > self.taille:
            self._segment(bytes(self.tampon[: self.taille]), final=False)
            del self.tampon[: self.taille]
        return len(b)

    def _segment(self, donnees: bytes, *, final: bool) -> None:
        jeton = self.fernet.encrypt(struct.pack(">QB", self.numero, 1 if final else 0) + donnees)
        self.sortie.write(struct.pack(">I", len(jeton)) + jeton)
        self.numero += 1

    def terminer(self) -> None:
        self._segment(bytes(self.tampon), final=True)
        self.tampon.clear()


class _LecteurChiffre(io.RawIOBase):
    """Flux en lecture : vérifie et déchiffre segment par segment (ordre, final, intégrité)."""

    def __init__(self, entree: BinaryIO, fernet: MultiFernet) -> None:
        self.entree, self.fernet = entree, fernet
        self.tampon = b""
        self.attendu = 0
        self.fini = False

    def readable(self) -> bool:
        return True

    def _suivant(self) -> None:
        tete = self.entree.read(4)
        if len(tete) < 4:
            raise ErreurIntegrite("sauvegarde tronquée (segment final absent)")
        (n,) = struct.unpack(">I", tete)
        if n > _LONGUEUR_MAX:
            raise ErreurIntegrite("sauvegarde altérée (segment hors limites)")
        jeton = self.entree.read(n)
        try:
            clair = self.fernet.decrypt(jeton)
        except InvalidToken as exc:
            raise ErreurIntegrite("sauvegarde indéchiffrable (clé incorrecte ou fichier altéré)") from exc
        numero, final = struct.unpack(">QB", clair[:9])
        if numero != self.attendu:
            raise ErreurIntegrite("sauvegarde altérée (segments réordonnés ou dupliqués)")
        self.attendu += 1
        self.tampon += clair[9:]
        if final:
            self.fini = True
            if self.entree.read(1):
                raise ErreurIntegrite("sauvegarde altérée (données après le segment final)")

    def readinto(self, b: bytearray) -> int:  # type: ignore[override]
        while not self.tampon and not self.fini:
            self._suivant()
        n = min(len(b), len(self.tampon))
        b[:n] = self.tampon[:n]
        self.tampon = self.tampon[n:]
        return n


def sauvegarder(base_sqlite: Path | str, coffre: Path | str | None, destination: Path | str,
                cles: Sequence[bytes], *, now: datetime | None = None, tmp_dir: Path | str | None = None) -> Path:
    """Sauvegarde en flux ; ``tmp_dir`` (copie de la base) : défaut ``destination`` (même volume)."""
    base_sqlite, destination = Path(base_sqlite), Path(destination)
    if not base_sqlite.is_file():
        raise FileNotFoundError(f"base SQLite introuvable : {base_sqlite}")
    now = now or datetime.now(UTC)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    cible = destination / f"controldone-{now.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.gz.enc"
    partiel = cible.with_name(cible.name + ".partiel")
    if tmp_dir is not None:
        Path(tmp_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".cd-sauvegarde-", dir=tmp_dir or destination) as tmp:
        copie = Path(tmp) / "controldone.db"
        src = sqlite3.connect(str(base_sqlite))
        dst = sqlite3.connect(str(copie))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        fd = os.open(partiel, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as sortie:
                ecrivain = _EcrivainChiffre(sortie, _fernet(cles))
                with tarfile.open(fileobj=ecrivain, mode="w|gz") as tar:  # type: ignore[call-overload]
                    tar.add(copie, arcname="base/controldone.db")
                    if coffre is not None and Path(coffre).is_dir():
                        tar.add(Path(coffre), arcname="coffre")
                ecrivain.terminer()
                sortie.flush()
                os.fsync(sortie.fileno())
            os.replace(partiel, cible)
        except BaseException:
            partiel.unlink(missing_ok=True)
            raise
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


def _verifier_membre(membre: tarfile.TarInfo) -> None:
    if not (membre.name == "base" or membre.name.startswith(("base/", "coffre"))):
        raise ErreurIntegrite(f"entrée inattendue dans l'archive : {membre.name!r}")


def restaurer(archive: Path | str, cible: Path | str, cles: Sequence[bytes]) -> Path:
    """Déchiffre et extrait en flux dans ``cible`` (``cible/base/controldone.db``, ``cible/coffre/``)."""
    cible = Path(cible)
    archive = Path(archive)
    with archive.open("rb") as f:
        nouveau = f.read(len(MAGIE)) == MAGIE
    cible.mkdir(parents=True, exist_ok=True, mode=0o700)
    if nouveau:
        with archive.open("rb") as entree:
            entree.read(len(MAGIE))
            lecteur = io.BufferedReader(_LecteurChiffre(entree, _fernet(cles)), buffer_size=TAILLE_SEGMENT)
            try:
                with tarfile.open(fileobj=lecteur, mode="r|gz") as tar:  # type: ignore[call-overload]
                    for membre in tar:
                        _verifier_membre(membre)
                        tar.extract(membre, cible, filter="data")
            except (tarfile.TarError, EOFError, OSError) as exc:
                if isinstance(exc, ErreurIntegrite):
                    raise
                raise ErreurIntegrite("archive de sauvegarde illisible") from exc
    else:  # ancien format : un seul jeton Fernet (archives antérieures à D-1320)
        try:
            clair = _fernet(cles).decrypt(archive.read_bytes())
        except InvalidToken as exc:
            raise ErreurIntegrite("sauvegarde indéchiffrable (clé incorrecte ou fichier altéré)") from exc
        with tarfile.open(fileobj=io.BytesIO(clair), mode="r:gz") as tar:
            for membre in tar.getmembers():
                _verifier_membre(membre)
            tar.extractall(cible, filter="data")
    base = cible / "base" / "controldone.db"
    if not base.is_file():
        raise ErreurIntegrite("base absente de la sauvegarde")
    con = sqlite3.connect(str(base))
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if ok != "ok":
        raise ErreurIntegrite("base restaurée corrompue")
    return cible


def _alerter_echec(exc: BaseException) -> None:
    """Alerte au fondateur (une par jour) : une sauvegarde qui échoue ne passe plus inaperçue."""
    try:
        from controldone.storage.alertes import emettre_alerte
        from controldone.storage.db import Database

        db = Database()
        try:
            with db.transaction_systeme() as s:
                emettre_alerte(s, cle=f"sauvegarde_echec:{datetime.now(UTC):%Y-%m-%d}", kind="sauvegarde_echec",
                               message=f"Échec de la sauvegarde chiffrée ({type(exc).__name__}) : vérifier l'espace "
                                       "disque, la clé maîtresse et le journal de sauvegarde.",
                               details={"erreur": type(exc).__name__})
        finally:
            db.fermer()
    except Exception:  # pragma: no cover - la base elle-même est indisponible : le code retour suffit
        print("alerte de sauvegarde non enregistrée", file=sys.stderr)


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
        try:
            sortie = sauvegarder(chemin, data_dir / "coffre", destination, cles)
        except Exception as exc:
            _alerter_echec(exc)
            print(f"sauvegarde en échec : {type(exc).__name__}", file=sys.stderr)
            return 1
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
