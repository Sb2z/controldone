"""Sauvegardes chiffrées (SQLite en ligne + coffre + traces d'envoi), vérification et restauration.
Voir ``docs/EXPLOITATION.md`` §3 et ``deploy/README.md``.

- ``sauvegarder`` : copie **en ligne** de la base SQLite (API ``sqlite3.backup``, cohérente même pendant
  l'écriture) dans un répertoire temporaire **sur le volume de destination** (jamais un tmpfs ``/tmp``),
  puis archive tar.gz écrite **en flux** et chiffrée **par segments** :
  ``controldone-AAAAMMJJTHHMMSSZ.tar.gz.enc`` (droits 0600) + ``….tar.gz.enc.sha256`` (empreinte de l'archive
  chiffrée, format ``sha256sum`` : contrôle d'une copie hors site **sans** la clé). La mémoire utilisée ne
  dépend pas de la taille du coffre (un segment de 1 Mio à la fois) — F-02, D-1320.
- Contenu de l'archive (D-3301) : ``base/controldone.db``, ``coffre/`` (déjà chiffré par client),
  ``outbox_envoyee/`` (traces des envois mis à disposition) et, en dernier, ``MANIFESTE.json`` : taille et
  SHA-256 de **chaque** fichier, nombre de lignes par table et tête de la chaîne d'audit de l'instantané.
  **Jamais** de clé : ni ``dev_master.key``, ni ``.env`` ; la clé maîtresse se conserve à part (D-3302).
- ``verifier`` : relit l'archive en flux sans rien écrire (empreinte externe, déchiffrement de chaque segment,
  SHA-256 de chaque fichier comparé au manifeste, aucun fichier en trop ni en moins).
- ``restaurer`` : déchiffre et extrait en flux dans un répertoire **vide** (filtre ``data`` : aucun chemin
  absolu, ``..`` ni lien ; seules les entrées attendues sont admises), puis revérifie chaque fichier écrit
  contre le manifeste et ``PRAGMA integrity_check``. Les archives sans manifeste (avant D-3301) et de l'ancien
  format (un seul jeton Fernet) restent restaurables.
- ``rotation`` : conserve la plus récente de chacun des 7 derniers jours et de chacune des 4 dernières
  semaines ISO ; supprime les autres (et leurs empreintes), ainsi que les restes d'une sauvegarde interrompue.
- Contrôle approfondi d'un répertoire restauré : ``controldone.storage.controle_restauration``.

Format ``CDSAV2`` (documenté dans ``docs/EXPLOITATION.md`` §3) :

```
en-tête   : b"CDSAV2\\n"
segment*  : longueur (4 octets, gros-boutiste) || jeton Fernet(segment clair)
clair     : numéro de segment (8 octets, gros-boutiste) || drapeau final (1 octet : 0 ou 1) || données
```

Chaque segment est authentifié (Fernet : AES-128-CBC + HMAC-SHA256, clé dérivée ``sauvegarde`` de la clé
maîtresse, rotation par ``MultiFernet``) ; le numéro empêche de réordonner ou de dupliquer des segments, le
drapeau final de tronquer l'archive sans le détecter.

Ligne de commande : ``python -m controldone.storage.sauvegarde sauvegarder|verifier|restaurer|controler|
rotation|alerter …`` (aussi ``controldone sauvegarde …``). Codes de retour (D-3303) : 0 succès ; 1 échec de
la création ; 2 configuration (base non SQLite, clé absente ou invalide, archive introuvable) ; 3 vérification
ou contrôle en échec ; 4 aucune sauvegarde assez récente. Chaque échec émet une alerte au fondateur (une par
jour et par type). PostgreSQL : ``pg_dump`` (voir l'exploitation) ; ``sauvegarder`` le refuse.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import struct
import sys
import tarfile
import tempfile
import time
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from cryptography.fernet import InvalidToken, MultiFernet

from controldone.storage.cles import charger_cles_maitresses, deriver_multifernet
from controldone.storage.erreurs import CleManquante, ErreurIntegrite

__all__ = [
    "MAGIE",
    "MANIFESTE",
    "NOM_RE",
    "TAILLE_SEGMENT",
    "RapportVerification",
    "derniere_sauvegarde",
    "empreinte_fichier",
    "instantane_base",
    "restaurer",
    "rotation",
    "sauvegarder",
    "verifier",
]

NOM_RE = re.compile(r"^controldone-(\d{8}T\d{6}Z)\.tar\.gz\.enc$")
MAGIE = b"CDSAV2\n"
MANIFESTE = "MANIFESTE.json"
TAILLE_SEGMENT = 1024 * 1024
_LONGUEUR_MAX = 8 * TAILLE_SEGMENT  # jeton Fernet d'un segment : < 2 × clair (base64 + en-tête)
_ARC_BASE = "base/controldone.db"
_RACINES = ("base", "coffre", "outbox_envoyee")
EXT_EMPREINTE = ".sha256"
EXT_INVALIDE = ".invalide"

# Codes de retour de la ligne de commande (D-3303)
OK, ECHEC_CREATION, ECHEC_CONFIGURATION, ECHEC_VERIFICATION, ECHEC_FRAICHEUR = 0, 1, 2, 3, 4


def _fernet(cles: Sequence[bytes]) -> MultiFernet:
    return deriver_multifernet(cles, "sauvegarde")


def empreinte_fichier(chemin: Path | str) -> str:
    h = hashlib.sha256()
    with Path(chemin).open("rb") as f:
        while bloc := f.read(TAILLE_SEGMENT):
            h.update(bloc)
    return h.hexdigest()


# --- flux chiffrés ----------------------------------------------------------------------------------------


class _EcrivainChiffre(io.RawIOBase):
    """Flux en écriture : regroupe en segments de ``TAILLE_SEGMENT`` et écrit chaque segment chiffré."""

    def __init__(self, sortie: BinaryIO, fernet: MultiFernet, taille: int = TAILLE_SEGMENT) -> None:
        self.sortie, self.fernet, self.taille = sortie, fernet, taille
        self.tampon = bytearray()
        self.numero = 0
        self.empreinte = hashlib.sha256()
        self._ecrire(MAGIE)

    def _ecrire(self, donnees: bytes) -> None:
        self.sortie.write(donnees)
        self.empreinte.update(donnees)

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
        self._ecrire(struct.pack(">I", len(jeton)) + jeton)
        self.numero += 1

    def terminer(self) -> None:
        self._segment(bytes(self.tampon), final=True)
        self.tampon.clear()


class _Empreinte(io.RawIOBase):
    """Lecture qui calcule au passage le SHA-256 et la taille de ce qui est lu."""

    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.h = hashlib.sha256()
        self.n = 0

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray) -> int:  # type: ignore[override]
        donnees = self.source.read(len(b))
        n = len(donnees)
        b[:n] = donnees
        if n:
            self.h.update(donnees)
            self.n += n
        return n


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

    def vider(self) -> None:
        """Lit jusqu'au segment final : une archive dont la fin manque est refusée même si le tar est lisible."""
        while not self.fini:
            self._suivant()
        self.tampon = b""


# --- instantané de la base --------------------------------------------------------------------------------


def instantane_base(chemin: Path | str) -> dict[str, Any]:
    """Intégrité, nombre de lignes par table et tête de la chaîne d'audit d'une base SQLite (lecture seule)."""
    con = sqlite3.connect(f"file:{Path(chemin)}?mode=ro", uri=True)
    try:
        integrite = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        lignes = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        audit: dict[str, Any] = {"entrees": 0, "tete": None}
        if "audit_log" in tables:
            tete = con.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            audit = {"entrees": lignes["audit_log"], "tete": tete[0] if tete else None}
    finally:
        con.close()
    return {"integrite": integrite, "tables": lignes, "audit": audit}


# --- création ---------------------------------------------------------------------------------------------


def _entree_tar(nom: str, *, taille: int = 0, repertoire: bool = False, mtime: float | None = None) -> tarfile.TarInfo:
    info = tarfile.TarInfo(nom)
    info.type = tarfile.DIRTYPE if repertoire else tarfile.REGTYPE
    info.mode = 0o700 if repertoire else 0o600
    info.size = 0 if repertoire else taille
    info.mtime = int(mtime if mtime is not None else time.time())
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _ajouter_fichier(tar: tarfile.TarFile, chemin: Path, nom: str, fichiers: dict[str, dict[str, Any]]) -> None:
    with chemin.open("rb") as f:
        st = os.fstat(f.fileno())  # le descripteur garde l'inode ouvert : remplacement atomique sans effet
        lecteur = _Empreinte(f)  # type: ignore[arg-type]
        tar.addfile(_entree_tar(nom, taille=st.st_size, mtime=st.st_mtime), lecteur)
    fichiers[nom] = {"taille": lecteur.n, "sha256": lecteur.h.hexdigest()}


def _ajouter_arbre(tar: tarfile.TarFile, racine: Path, prefixe: str, fichiers: dict[str, dict[str, Any]]) -> None:
    """Ajoute ``racine`` (sans lien symbolique ni fichier temporaire ``.tmp-*`` en cours d'écriture)."""
    tar.addfile(_entree_tar(prefixe, repertoire=True))
    for dossier, sous, noms in os.walk(racine):
        sous[:] = sorted(d for d in sous if not Path(dossier, d).is_symlink())
        rel = Path(dossier).relative_to(racine)
        for d in sous:
            tar.addfile(_entree_tar((Path(prefixe) / rel / d).as_posix(), repertoire=True))
        for n in sorted(noms):
            p = Path(dossier) / n
            if n.startswith(".tmp-") or p.is_symlink() or not p.is_file():
                continue
            try:
                _ajouter_fichier(tar, p, (Path(prefixe) / rel / n).as_posix(), fichiers)
            except FileNotFoundError:  # purgé entre le parcours et la lecture : il n'est simplement pas copié
                continue


def sauvegarder(base_sqlite: Path | str, coffre: Path | str | None, destination: Path | str,
                cles: Sequence[bytes], *, now: datetime | None = None, tmp_dir: Path | str | None = None,
                sorties: Path | str | None = None) -> Path:
    """Sauvegarde en flux ; ``tmp_dir`` (copie de la base) : défaut ``destination`` (même volume).
    ``sorties`` : répertoire des traces d'envoi (``<data_dir>/outbox_envoyee``), facultatif."""
    from controldone import __version__

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
        etat_base = instantane_base(copie)
        fichiers: dict[str, dict[str, Any]] = {}
        fd = os.open(partiel, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as sortie:
                ecrivain = _EcrivainChiffre(sortie, _fernet(cles))
                with tarfile.open(fileobj=ecrivain, mode="w|gz") as tar:  # type: ignore[call-overload]
                    tar.addfile(_entree_tar("base", repertoire=True))
                    _ajouter_fichier(tar, copie, _ARC_BASE, fichiers)
                    for racine, prefixe in ((coffre, "coffre"), (sorties, "outbox_envoyee")):
                        if racine is not None and Path(racine).is_dir():
                            _ajouter_arbre(tar, Path(racine), prefixe, fichiers)
                    manifeste = {
                        "format": "controldone-sauvegarde", "version": 1, "application": __version__,
                        "cree_le": now.astimezone(UTC).isoformat(), "base": {"chemin": _ARC_BASE, **etat_base},
                        "fichiers": fichiers,
                    }
                    brut = json.dumps(manifeste, ensure_ascii=False, indent=1, sort_keys=True).encode()
                    tar.addfile(_entree_tar(MANIFESTE, taille=len(brut)), io.BytesIO(brut))
                ecrivain.terminer()
                sortie.flush()
                os.fsync(sortie.fileno())
            empreinte = ecrivain.empreinte.hexdigest()
            os.replace(partiel, cible)
        except BaseException:
            partiel.unlink(missing_ok=True)
            raise
    _ecrire_empreinte(cible, empreinte)
    return cible


def _ecrire_empreinte(archive: Path, empreinte: str) -> None:
    chemin = archive.with_name(archive.name + EXT_EMPREINTE)
    fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(f"{empreinte}  {archive.name}\n")


def _empreinte_attendue(archive: Path) -> str | None:
    chemin = archive.with_name(archive.name + EXT_EMPREINTE)
    if not chemin.is_file():
        return None
    return chemin.read_text(encoding="ascii", errors="replace").split()[0] if chemin.stat().st_size else ""


# --- lecture : vérification et restauration ---------------------------------------------------------------


def _verifier_membre(membre: tarfile.TarInfo) -> None:
    nom = membre.name
    if nom == MANIFESTE and membre.isfile():
        return
    if not any(nom == r or nom.startswith(r + "/") for r in _RACINES) or not (membre.isfile() or membre.isdir()):
        raise ErreurIntegrite(f"entrée inattendue dans l'archive : {nom!r}")


@contextlib.contextmanager
def _ouvrir(archive: Path, cles: Sequence[bytes], empreinte: _Empreinte | None = None
            ) -> Iterator[tuple[tarfile.TarFile, _LecteurChiffre | None]]:
    """Tar en flux sur l'archive déchiffrée (ancien format : déchiffré en mémoire). ``empreinte`` : calcule au
    passage le SHA-256 de l'archive chiffrée."""
    with archive.open("rb") as brut:
        entree: Any = brut
        if empreinte is not None:
            empreinte.source = brut
            entree = io.BufferedReader(empreinte, buffer_size=TAILLE_SEGMENT)
        tete = entree.read(len(MAGIE))
        try:
            if tete == MAGIE:
                lecteur = _LecteurChiffre(entree, _fernet(cles))
                tampon = io.BufferedReader(lecteur, buffer_size=TAILLE_SEGMENT)
                with tarfile.open(fileobj=tampon, mode="r|gz") as tar:  # type: ignore[call-overload]
                    yield tar, lecteur
            else:  # ancien format : un seul jeton Fernet (archives antérieures à D-1320)
                try:
                    clair = _fernet(cles).decrypt(tete + entree.read())
                except InvalidToken as exc:
                    raise ErreurIntegrite("sauvegarde indéchiffrable (clé incorrecte ou fichier altéré)") from exc
                with tarfile.open(fileobj=io.BytesIO(clair), mode="r:gz") as tar:
                    yield tar, None
        except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile, struct.error) as exc:
            raise ErreurIntegrite(f"archive de sauvegarde illisible ({type(exc).__name__})") from exc


@dataclass
class RapportVerification:
    archive: Path
    taille: int = 0
    fichiers: int = 0
    octets_clairs: int = 0
    manifeste: dict[str, Any] | None = None
    empreinte_externe: str = "absente"  # « conforme », « absente » ou « différente »
    problemes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problemes

    def lignes(self) -> list[str]:
        base = (self.manifeste or {}).get("base", {})
        tables = base.get("tables", {})
        sortie = [
            f"archive          : {self.archive}",
            f"taille           : {self.taille} octets ; empreinte externe : {self.empreinte_externe}",
            f"fichiers         : {self.fichiers} ({self.octets_clairs} octets en clair)",
            f"manifeste        : {'présent' if self.manifeste else 'absent (archive antérieure à D-3301)'}",
        ]
        if self.manifeste:
            sortie.append(f"instantané       : {self.manifeste.get('cree_le')} — {len(tables)} tables, "
                          f"{sum(tables.values())} lignes, audit {base.get('audit', {}).get('entrees')} entrées")
        sortie.append("résultat         : " + ("CONFORME" if self.ok else "EN ÉCHEC"))
        sortie += [f"  - {p}" for p in self.problemes]
        return sortie


def _comparer_au_manifeste(vus: dict[str, dict[str, Any]], manifeste: dict[str, Any] | None) -> list[str]:
    if manifeste is None:
        return []
    attendus: dict[str, dict[str, Any]] = manifeste.get("fichiers") or {}
    problemes = [f"fichier absent : {n}" for n in sorted(set(attendus) - set(vus))]
    problemes += [f"fichier non déclaré : {n}" for n in sorted(set(vus) - set(attendus))]
    for n in sorted(set(attendus) & set(vus)):
        if (vus[n]["taille"], vus[n]["sha256"]) != (attendus[n].get("taille"), attendus[n].get("sha256")):
            problemes.append(f"empreinte différente : {n}")
    return problemes


def verifier(archive: Path | str, cles: Sequence[bytes]) -> RapportVerification:
    """Relit toute l'archive en flux, sans rien écrire sur disque. Ne lève pas : ``rapport.problemes``."""
    archive = Path(archive)
    rapport = RapportVerification(archive=archive)
    if not archive.is_file():
        rapport.problemes.append("archive introuvable")
        return rapport
    rapport.taille = archive.stat().st_size
    attendue = _empreinte_attendue(archive)
    empreinte = _Empreinte(None)  # type: ignore[arg-type]
    vus: dict[str, dict[str, Any]] = {}
    try:
        with _ouvrir(archive, cles, empreinte) as (tar, lecteur):
            for membre in tar:
                _verifier_membre(membre)
                if not membre.isfile():
                    continue
                if membre.name == MANIFESTE:
                    if rapport.manifeste is not None:
                        raise ErreurIntegrite("manifeste en double")
                    f = tar.extractfile(membre)
                    assert f is not None
                    try:
                        rapport.manifeste = json.loads(f.read(16 * 1024 * 1024))
                    except ValueError as exc:
                        raise ErreurIntegrite("manifeste illisible") from exc
                    continue
                f = tar.extractfile(membre)
                h, n = hashlib.sha256(), 0
                assert f is not None
                while bloc := f.read(TAILLE_SEGMENT):
                    h.update(bloc)
                    n += len(bloc)
                vus[membre.name] = {"taille": n, "sha256": h.hexdigest()}
                rapport.fichiers += 1
                rapport.octets_clairs += n
            if lecteur is not None:
                lecteur.vider()
    except ErreurIntegrite as exc:
        rapport.problemes.append(str(exc))
        return rapport
    if attendue is not None:
        rapport.empreinte_externe = "conforme" if attendue == empreinte.h.hexdigest() else "différente"
        if rapport.empreinte_externe == "différente":
            rapport.problemes.append("empreinte de l'archive différente de son fichier .sha256")
    if _ARC_BASE not in vus:
        rapport.problemes.append("base absente de la sauvegarde")
    rapport.problemes += _comparer_au_manifeste(vus, rapport.manifeste)
    if rapport.manifeste and rapport.manifeste.get("base", {}).get("integrite") != "ok":
        rapport.problemes.append("la base était déjà corrompue au moment de la sauvegarde")
    return rapport


def restaurer(archive: Path | str, cible: Path | str, cles: Sequence[bytes]) -> Path:
    """Déchiffre et extrait en flux dans ``cible`` (absent ou vide) : ``base/controldone.db``, ``coffre/``,
    ``outbox_envoyee/``, ``MANIFESTE.json`` ; puis revérifie chaque fichier écrit contre le manifeste."""
    cible = Path(cible)
    archive = Path(archive)
    if cible.exists() and (not cible.is_dir() or any(cible.iterdir())):
        raise FileExistsError(f"la cible de restauration doit être absente ou vide : {cible}")
    cible.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _ouvrir(archive, cles) as (tar, lecteur):
        for membre in tar:
            _verifier_membre(membre)
            tar.extract(membre, cible, filter="data")
        if lecteur is not None:
            lecteur.vider()
    base = cible / _ARC_BASE
    if not base.is_file():
        raise ErreurIntegrite("base absente de la sauvegarde")
    manifeste_chemin = cible / MANIFESTE
    if manifeste_chemin.is_file():
        try:
            manifeste = json.loads(manifeste_chemin.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ErreurIntegrite("manifeste illisible") from exc
        vus = {p.relative_to(cible).as_posix(): {"taille": p.stat().st_size, "sha256": empreinte_fichier(p)}
               for p in sorted(cible.rglob("*")) if p.is_file() and p != manifeste_chemin}
        problemes = _comparer_au_manifeste(vus, manifeste)
        if problemes:
            raise ErreurIntegrite("restauration non conforme au manifeste : " + "; ".join(problemes[:5]))
    con = sqlite3.connect(str(base))
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if ok != "ok":
        raise ErreurIntegrite("base restaurée corrompue")
    return cible


# --- conservation -----------------------------------------------------------------------------------------


def _date(p: Path) -> datetime | None:
    m = NOM_RE.match(p.name)
    return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) if m else None


def derniere_sauvegarde(destination: Path | str) -> Path | None:
    archives = sorted((d, p) for p in Path(destination).glob("controldone-*.tar.gz.enc") if (d := _date(p)))
    return archives[-1][1] if archives else None


def rotation(destination: Path | str, *, jours: int = 7, semaines: int = 4, maintenant: float | None = None
             ) -> list[Path]:
    """Applique la politique de conservation ; renvoie les archives supprimées. Supprime aussi leurs
    empreintes ``.sha256`` et les restes de plus d'un jour d'une sauvegarde ou d'une vérification
    interrompue (``.partiel``, répertoires ``.cd-sauvegarde-*`` / ``.cd-verification-*``, ``.invalide``)."""
    destination = Path(destination)
    sauvegardes = sorted(((d, p) for p in destination.glob("controldone-*.tar.gz.enc")
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
        p.with_name(p.name + EXT_EMPREINTE).unlink(missing_ok=True)
    limite = (maintenant if maintenant is not None else time.time()) - 86400
    for reste in [*destination.glob("controldone-*.partiel"), *destination.glob(f"controldone-*{EXT_INVALIDE}"),
                  *destination.glob(".cd-sauvegarde-*"), *destination.glob(".cd-verification-*")]:
        with contextlib.suppress(OSError):
            if reste.lstat().st_mtime < limite:
                shutil.rmtree(reste) if reste.is_dir() and not reste.is_symlink() else reste.unlink()
    for empreinte in destination.glob(f"controldone-*.tar.gz.enc{EXT_EMPREINTE}"):  # empreinte orpheline
        if not empreinte.with_name(empreinte.name[: -len(EXT_EMPREINTE)]).exists():
            empreinte.unlink(missing_ok=True)
    return supprimes


# --- alertes et ligne de commande -------------------------------------------------------------------------


def alerter(kind: str, message: str, details: dict[str, Any] | None = None) -> bool:
    """Alerte au fondateur (tableau de bord ``/admin/alertes``), une par jour et par type. Ne lève jamais."""
    try:
        from controldone.storage.alertes import emettre_alerte
        from controldone.storage.db import Database

        db = Database()
        try:
            with db.transaction_systeme() as s:
                return emettre_alerte(s, cle=f"{kind}:{datetime.now(UTC):%Y-%m-%d}", kind=kind, message=message,
                                      details=details or {})
        finally:
            db.fermer()
    except Exception:  # la base elle-même est indisponible : le code retour et le journal suffisent
        print(f"alerte {kind} non enregistrée (base indisponible)", file=sys.stderr)
        return False


def _alerter_echec(exc: BaseException) -> None:
    alerter("sauvegarde_echec", f"Échec de la sauvegarde chiffrée ({type(exc).__name__}) : vérifier l'espace "
                                "disque, la clé maîtresse et le journal de sauvegarde.", {"erreur": type(exc).__name__})


def _verification_profonde(archive: Path, cles: Sequence[bytes]) -> list[str]:
    """Restaure dans un répertoire temporaire **à côté de l'archive** (même volume), contrôle, efface."""
    from controldone.storage.controle_restauration import controler

    with tempfile.TemporaryDirectory(prefix=".cd-verification-", dir=archive.parent) as tmp:
        try:
            cible = restaurer(archive, Path(tmp) / "r", cles)
        except (ErreurIntegrite, OSError) as exc:
            return [f"restauration d'essai impossible : {exc}"]
        return controler(cible, cles).problemes


def _verifier_et_signaler(archive: Path, cles: Sequence[bytes], *, profond: bool) -> int:
    rapport = verifier(archive, cles)
    if rapport.ok and profond:
        rapport.problemes += _verification_profonde(archive, cles)
    print("\n".join(rapport.lignes()) if not profond or not rapport.ok else
          "\n".join([*rapport.lignes(), "contrôle approfondi : restauration d'essai conforme"]))
    if rapport.ok:
        return OK
    alerter("sauvegarde_verification_echec", f"Sauvegarde {archive.name} non conforme : {rapport.problemes[0]}"[:500],
            {"archive": archive.name, "problemes": rapport.problemes[:10]})
    return ECHEC_VERIFICATION


def main(argv: Sequence[str] | None = None) -> int:
    from controldone.config import get_settings
    from controldone.storage.db import Database

    parser = argparse.ArgumentParser(prog="python -m controldone.storage.sauvegarde")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("sauvegarder", help="crée une archive chiffrée, la vérifie, applique la rotation")
    b.add_argument("--destination", default=None)
    b.add_argument("--sans-rotation", action="store_true")
    b.add_argument("--sans-verification", action="store_true", help="ne pas relire l'archive créée")
    b.add_argument("--verification-profonde", action="store_true",
                   help="restauration d'essai complète de l'archive créée (espace disque : une fois les données)")
    v = sub.add_parser("verifier", help="relit une archive (déchiffrement, manifeste, empreintes)")
    v.add_argument("archive", nargs="?", default=None)
    v.add_argument("--dernier", action="store_true", help="la plus récente de --destination")
    v.add_argument("--destination", default=None)
    v.add_argument("--profond", action="store_true", help="restauration d'essai complète puis contrôle")
    v.add_argument("--age-max-h", type=float, default=None, help="avec --dernier : code 4 si plus ancienne")
    r = sub.add_parser("restaurer", help="restaure dans un répertoire absent ou vide")
    r.add_argument("archive")
    r.add_argument("cible")
    r.add_argument("--controler", action="store_true", help="puis contrôle approfondi (coffre, audit, tables)")
    c = sub.add_parser("controler", help="contrôle approfondi d'un répertoire restauré")
    c.add_argument("cible")
    for p in (b, sub.add_parser("rotation", help="applique la politique de conservation")):
        if p is not b:
            p.add_argument("--destination", default=None)
        p.add_argument("--jours", type=int, default=int(os.environ.get("BACKUP_JOURS", "7")))
        p.add_argument("--semaines", type=int, default=int(os.environ.get("BACKUP_SEMAINES", "4")))
    a = sub.add_parser("alerter", help="enregistre une alerte fondateur (échec signalé par un script hôte)")
    a.add_argument("--kind", required=True, choices=["sauvegarde_echec", "sauvegarde_hors_site_echec",
                                                     "sauvegarde_absente", "sauvegarde_verification_echec"])
    a.add_argument("--message", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "alerter":
        alerter(args.kind, args.message)
        return OK
    data_dir = Path(get_settings().data_dir)
    try:
        cles = charger_cles_maitresses(data_dir=data_dir)
    except CleManquante as exc:
        print(f"clé maîtresse : {exc}", file=sys.stderr)
        if args.cmd == "sauvegarder":
            _alerter_echec(exc)
        return ECHEC_CONFIGURATION
    destination = Path(getattr(args, "destination", None) or data_dir / "sauvegardes")

    if args.cmd == "sauvegarder":
        db = Database()
        chemin = db.chemin_sqlite()
        db.fermer()
        if chemin is None:
            print("base non SQLite : utiliser pg_dump (voir docs/EXPLOITATION.md)", file=sys.stderr)
            return ECHEC_CONFIGURATION
        try:
            sortie = sauvegarder(chemin, data_dir / "coffre", destination, cles, sorties=data_dir / "outbox_envoyee")
        except Exception as exc:
            _alerter_echec(exc)
            print(f"sauvegarde en échec : {type(exc).__name__}: {exc}", file=sys.stderr)
            return ECHEC_CREATION
        print(sortie)
        code = OK
        if not args.sans_verification:
            code = _verifier_et_signaler(sortie, cles, profond=args.verification_profonde)
            if code != OK:  # mise à l'écart : ne compte ni comme « sauvegarde du jour », ni dans la rotation
                for p in (sortie, sortie.with_name(sortie.name + EXT_EMPREINTE)):
                    with contextlib.suppress(OSError):
                        p.rename(p.with_name(p.name + EXT_INVALIDE))
                return code
        if not args.sans_rotation:
            for p in rotation(destination, jours=args.jours, semaines=args.semaines):
                print(f"supprimée : {p}")
        return code
    if args.cmd == "verifier":
        archive = Path(args.archive) if args.archive else (derniere_sauvegarde(destination) if args.dernier else None)
        if archive is None:
            if args.dernier:
                print(f"aucune sauvegarde dans {destination}", file=sys.stderr)
                alerter("sauvegarde_absente", f"Aucune sauvegarde trouvée dans {destination}.")
                return ECHEC_FRAICHEUR
            parser.error("indiquer une archive ou --dernier")
        if not archive.is_file():
            print(f"archive introuvable : {archive}", file=sys.stderr)
            return ECHEC_CONFIGURATION
        code = _verifier_et_signaler(archive, cles, profond=args.profond)
        d = _date(archive)
        if code == OK and args.age_max_h is not None and d is not None:
            age_h = (datetime.now(UTC) - d).total_seconds() / 3600
            if age_h > args.age_max_h:
                print(f"sauvegarde la plus récente vieille de {age_h:.1f} h (> {args.age_max_h} h)", file=sys.stderr)
                alerter("sauvegarde_absente", f"Dernière sauvegarde vieille de {age_h:.0f} h ({archive.name}).")
                return ECHEC_FRAICHEUR
        return code
    if args.cmd == "restaurer":
        try:
            cible = restaurer(args.archive, args.cible, cles)
        except (ErreurIntegrite, FileExistsError, FileNotFoundError) as exc:
            print(f"restauration refusée : {exc}", file=sys.stderr)
            return ECHEC_VERIFICATION if isinstance(exc, ErreurIntegrite) else ECHEC_CONFIGURATION
        print(cible)
        if not args.controler:
            return OK
        args.cible = str(cible)
    if args.cmd in ("restaurer", "controler"):
        from controldone.storage.controle_restauration import controler

        rapport = controler(Path(args.cible), cles)
        print("\n".join(rapport.lignes()))
        return OK if rapport.ok else ECHEC_VERIFICATION
    for p in rotation(destination, jours=args.jours, semaines=args.semaines):
        print(f"supprimée : {p}")
    return OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
