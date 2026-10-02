"""Coffre de fichiers chiffré (SPEC §20.1, §6.2.5).

- Chiffrement Fernet (AES-128-CBC + HMAC-SHA256) avec une clé **par client** dérivée de la clé maîtresse
  (HKDF, ``info = vault:<client>``) : un fichier d'un client ne se déchiffre pas avec la clé d'un autre.
- Adressage par contenu : ``<racine>/<client>/<espace>/<sha[:2]>/<sha>`` où ``sha`` = SHA-256 du clair ;
  dédoublonnage par client ; l'intégrité est revérifiée à la lecture.
- Traversée de chemin impossible : identifiant de client et ``sha`` validés par expression régulière,
  chemin résolu puis vérifié sous la racine ; écriture atomique (fichier temporaire + ``os.replace``),
  droits 0600.
- Espaces : ``fichiers`` (fichiers bruts) et ``textes`` (textes de page), purgés séparément (§20.4).
- Rotation : ``tourner_cles(nouvelles_cles)`` rechiffre tout avec la nouvelle clé courante.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

from cryptography.fernet import InvalidToken, MultiFernet

from controldone.storage.cles import charger_cles_maitresses, deriver_multifernet
from controldone.storage.erreurs import ErreurCoffre, ErreurIntegrite

__all__ = ["ESPACES", "FileVault"]

ESPACES = ("fichiers", "textes")
_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class FileVault:
    def __init__(self, racine: Path | str, cles_maitresses: Sequence[bytes]) -> None:
        if not cles_maitresses:
            raise ErreurCoffre("aucune clé maîtresse")
        self.racine = Path(racine).resolve()
        self.racine.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._cles = list(cles_maitresses)
        self._cache: dict[str, MultiFernet] = {}

    @classmethod
    def depuis_env(cls, racine: Path | str | None = None, *, mode: str | None = None) -> FileVault:
        from controldone.config import get_settings

        data_dir = get_settings().data_dir
        cles = charger_cles_maitresses(mode=mode, data_dir=data_dir)
        return cls(racine or Path(data_dir) / "coffre", cles)

    # --- chemins ---
    @staticmethod
    def _tenant(tenant_id: str) -> str:
        if not isinstance(tenant_id, str) or not _TENANT_RE.fullmatch(tenant_id):
            raise ErreurCoffre("identifiant de client invalide")
        return tenant_id

    @staticmethod
    def _sha(sha: str) -> str:
        if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
            raise ErreurCoffre("référence de contenu invalide")
        return sha

    @staticmethod
    def _espace(espace: str) -> str:
        if espace not in ESPACES:
            raise ErreurCoffre("espace inconnu")
        return espace

    def _chemin(self, tenant_id: str, sha: str, espace: str) -> Path:
        t, h, e = self._tenant(tenant_id), self._sha(sha), self._espace(espace)
        chemin = (self.racine / t / e / h[:2] / h).resolve()
        if not chemin.is_relative_to(self.racine / t):
            raise ErreurCoffre("chemin hors du coffre")
        return chemin

    def _fernet(self, tenant_id: str) -> MultiFernet:
        t = self._tenant(tenant_id)
        if t not in self._cache:
            self._cache[t] = deriver_multifernet(self._cles, f"vault:{t}")
        return self._cache[t]

    # --- opérations ---
    def deposer(self, tenant_id: str, contenu: bytes, *, espace: str = "fichiers") -> str:
        """Chiffre et range ``contenu`` ; renvoie son SHA-256 (référence). Idempotent."""
        if not isinstance(contenu, bytes | bytearray):
            raise TypeError("octets attendus")
        sha = hashlib.sha256(contenu).hexdigest()
        chemin = self._chemin(tenant_id, sha, espace)
        if chemin.exists():
            return sha
        jeton = self._fernet(tenant_id).encrypt(bytes(contenu))
        self._ecrire_atomique(chemin, jeton)
        return sha

    def _ecrire_atomique(self, chemin: Path, donnees: bytes) -> None:
        chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(donnees)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, chemin)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def lire(self, tenant_id: str, sha: str, *, espace: str = "fichiers") -> bytes:
        chemin = self._chemin(tenant_id, sha, espace)
        if not chemin.is_file():
            raise FileNotFoundError("contenu absent du coffre")
        try:
            clair = self._fernet(tenant_id).decrypt(chemin.read_bytes())
        except InvalidToken as exc:
            raise ErreurIntegrite("contenu indéchiffrable (clé d'un autre client ou fichier altéré)") from exc
        if hashlib.sha256(clair).hexdigest() != sha:
            raise ErreurIntegrite("empreinte du contenu différente de la référence")
        return clair

    def deposer_texte(self, tenant_id: str, texte: str) -> str:
        return self.deposer(tenant_id, texte.encode("utf-8"), espace="textes")

    def lire_texte(self, tenant_id: str, sha: str) -> str:
        return self.lire(tenant_id, sha, espace="textes").decode("utf-8")

    def existe(self, tenant_id: str, sha: str, *, espace: str = "fichiers") -> bool:
        return self._chemin(tenant_id, sha, espace).is_file()

    def supprimer(self, tenant_id: str, sha: str, *, espace: str = "fichiers") -> bool:
        chemin = self._chemin(tenant_id, sha, espace)
        if chemin.is_file():
            chemin.unlink()
            return True
        return False

    def lister(self, tenant_id: str, *, espace: str = "fichiers") -> Iterator[str]:
        base = self.racine / self._tenant(tenant_id) / self._espace(espace)
        if not base.is_dir():
            return
        for p in sorted(base.glob("??/*")):
            if _SHA_RE.fullmatch(p.name):
                yield p.name

    def supprimer_client(self, tenant_id: str) -> None:
        base = (self.racine / self._tenant(tenant_id)).resolve()
        if base.is_relative_to(self.racine) and base != self.racine and base.is_dir():
            shutil.rmtree(base)

    def clients(self) -> list[str]:
        return sorted(p.name for p in self.racine.iterdir() if p.is_dir() and _TENANT_RE.fullmatch(p.name))

    # --- rotation ---
    def tourner_cles(self, nouvelles_cles: Sequence[bytes]) -> int:
        """Rechiffre chaque objet avec la première de ``nouvelles_cles`` (qui doit contenir aussi les
        anciennes clés encore en usage). Renvoie le nombre d'objets rechiffrés."""
        if not nouvelles_cles:
            raise ErreurCoffre("aucune clé")
        self._cles = list(nouvelles_cles)
        self._cache.clear()
        n = 0
        for t in self.clients():
            mf = self._fernet(t)
            for e in ESPACES:
                for sha in list(self.lister(t, espace=e)):
                    chemin = self._chemin(t, sha, e)
                    try:
                        jeton = mf.rotate(chemin.read_bytes())
                    except InvalidToken as exc:  # les objets déjà tournés restent lisibles
                        raise ErreurIntegrite("objet indéchiffrable avec les clés fournies") from exc
                    self._ecrire_atomique(chemin, jeton)
                    n += 1
        return n
