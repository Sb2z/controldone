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
- Contenus d'au moins ``SEUIL_SEGMENTS`` octets (D-1305) : format ``CDV2`` chiffré **par segments**
  d'1 Mio (AES-256-GCM, clé dérivée HKDF ``vault-gcm:<client>``) écrit et lu segment par segment ; le
  chiffrement Fernet d'un bloc coûtait environ 6 fois la taille du fichier en mémoire (300 Mo pour 45 Mo).
  En-tête ``b"CDV2"`` + préfixe de nonce aléatoire (8 octets) ; chaque segment : longueur (4 octets) ||
  chiffré+étiquette ; nonce = préfixe || numéro (4 octets) ; données associées = en-tête || numéro ||
  drapeau final (réordonner, tronquer ou substituer un segment est détecté). Les objets Fernet existants
  restent lisibles.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import struct
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.fernet import InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from controldone.storage.cles import SEL_HKDF, charger_cles_maitresses, deriver_multifernet
from controldone.storage.erreurs import ErreurCoffre, ErreurIntegrite

__all__ = ["ESPACES", "FileVault"]

ESPACES = ("fichiers", "textes")
_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAGIE_V2 = b"CDV2"
SEUIL_SEGMENTS = 256 * 1024
TAILLE_SEGMENT = 1024 * 1024


class FileVault:
    def __init__(self, racine: Path | str, cles_maitresses: Sequence[bytes]) -> None:
        if not cles_maitresses:
            raise ErreurCoffre("aucune clé maîtresse")
        self.racine = Path(racine).resolve()
        self.racine.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._cles = list(cles_maitresses)
        self._cache: dict[str, MultiFernet] = {}

    @property
    def cles_maitresses(self) -> list[bytes]:
        """Clés maîtresses du coffre (la première chiffre) : mêmes clés pour les traces d'envoi (D-4106)."""
        return list(self._cles)

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

    def _aes(self, tenant_id: str) -> list[AESGCM]:
        """Clés AES-GCM du client (une par clé maîtresse, la première chiffre)."""
        t = self._tenant(tenant_id)
        cle = f"aes:{t}"
        if cle not in self._cache:
            aes = []
            for m in self._cles:
                hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=SEL_HKDF, info=f"vault-gcm:{t}".encode())
                aes.append(AESGCM(hkdf.derive(base64.urlsafe_b64decode(m))))
            self._cache[cle] = aes  # type: ignore[assignment]
        return self._cache[cle]  # type: ignore[return-value]

    def _ecrire_segments(self, chemin: Path, tenant_id: str, contenu: bytes) -> None:
        """Chiffrement par segments, écrit au fil de l'eau dans un fichier temporaire (mémoire : un segment)."""
        aes = self._aes(tenant_id)[0]
        prefixe = os.urandom(8)
        entete = MAGIE_V2 + prefixe
        vue = memoryview(contenu)
        n = max(1, -(-len(contenu) // TAILLE_SEGMENT))
        chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(entete)
                for i in range(n):
                    morceau = vue[i * TAILLE_SEGMENT:(i + 1) * TAILLE_SEGMENT]
                    final = i == n - 1
                    chiffre = aes.encrypt(prefixe + struct.pack(">I", i), bytes(morceau),
                                          entete + struct.pack(">IB", i, final))
                    f.write(struct.pack(">I", len(chiffre)) + chiffre)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, chemin)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _lire_segments(self, chemin: Path, tenant_id: str) -> bytes:
        erreur = ErreurIntegrite("contenu indéchiffrable (clé d'un autre client ou fichier altéré)")
        for aes in self._aes(tenant_id):
            sortie = bytearray()
            try:
                with chemin.open("rb") as f:
                    entete = f.read(12)
                    if len(entete) != 12 or entete[:4] != MAGIE_V2:
                        raise erreur
                    prefixe = entete[4:]
                    i = 0
                    while True:
                        tete = f.read(4)
                        if len(tete) != 4:
                            raise erreur  # tronqué : segment final absent
                        (n,) = struct.unpack(">I", tete)
                        if n > TAILLE_SEGMENT + 64:
                            raise erreur
                        chiffre = f.read(n)
                        nonce = prefixe + struct.pack(">I", i)
                        try:
                            clair = aes.decrypt(nonce, chiffre, entete + struct.pack(">IB", i, True))
                            sortie += clair
                            if f.read(1):
                                raise erreur  # données après le segment final
                            return bytes(sortie)
                        except InvalidTag:
                            sortie += aes.decrypt(nonce, chiffre, entete + struct.pack(">IB", i, False))
                        i += 1
            except InvalidTag:
                continue  # autre clé maîtresse (rotation) ou altération
        raise erreur

    def _chiffrer_vers(self, chemin: Path, tenant_id: str, contenu: bytes) -> None:
        if len(contenu) >= SEUIL_SEGMENTS:
            self._ecrire_segments(chemin, tenant_id, contenu)
        else:
            self._ecrire_atomique(chemin, self._fernet(tenant_id).encrypt(bytes(contenu)))

    def _dechiffrer(self, chemin: Path, tenant_id: str) -> bytes:
        with chemin.open("rb") as f:
            debut = f.read(4)
        if debut == MAGIE_V2:
            return self._lire_segments(chemin, tenant_id)
        try:
            return self._fernet(tenant_id).decrypt(chemin.read_bytes())
        except InvalidToken as exc:
            raise ErreurIntegrite("contenu indéchiffrable (clé d'un autre client ou fichier altéré)") from exc

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
            try:  # contenu déjà présent : sa date marque le dépôt récent (la purge l'épargne, D-1324)
                os.utime(chemin)
                return sha
            except FileNotFoundError:
                pass  # retiré entre-temps par une purge : réécrit ci-dessous
        self._chiffrer_vers(chemin, tenant_id, bytes(contenu) if isinstance(contenu, bytearray) else contenu)
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
        clair = self._dechiffrer(chemin, tenant_id)
        if hashlib.sha256(clair).hexdigest() != sha:
            raise ErreurIntegrite("empreinte du contenu différente de la référence")
        return clair

    def deposer_texte(self, tenant_id: str, texte: str) -> str:
        return self.deposer(tenant_id, texte.encode("utf-8"), espace="textes")

    def lire_texte(self, tenant_id: str, sha: str) -> str:
        return self.lire(tenant_id, sha, espace="textes").decode("utf-8")

    def existe(self, tenant_id: str, sha: str, *, espace: str = "fichiers") -> bool:
        return self._chemin(tenant_id, sha, espace).is_file()

    def depose_depuis(self, tenant_id: str, sha: str, *, espace: str = "fichiers") -> float | None:
        """Horodatage (epoch) du dernier dépôt de ce contenu (écriture ou redépôt à l'identique), ``None`` si
        absent."""
        try:
            return self._chemin(tenant_id, sha, espace).stat().st_mtime
        except FileNotFoundError:
            return None

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
            for e in ESPACES:
                for sha in list(self.lister(t, espace=e)):
                    chemin = self._chemin(t, sha, e)
                    try:
                        clair = self._dechiffrer(chemin, t)
                    except ErreurIntegrite as exc:  # les objets déjà tournés restent lisibles
                        raise ErreurIntegrite("objet indéchiffrable avec les clés fournies") from exc
                    self._chiffrer_vers(chemin, t, clair)
                    n += 1
        return n
