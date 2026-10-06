"""Traces d'envoi chiffrées au repos : ``<data_dir>/outbox_envoyee/`` (D-4106).

Les copies des envois mis à disposition (rapports publiés, relevés d'écarts : ``ExpediteurFichier`` ; factures
émises : ``ExpediteurFacture``) étaient écrites **en clair** sur le volume, hors du coffre chiffré. Elles sont
désormais chiffrées avec la gestion de clés existante :

- clé dérivée de ``CONTROLDONE_MASTER_KEY`` par HKDF (``info = outbox_envoyee``, ``storage.cles``), en
  ``MultiFernet`` : la première clé maîtresse chiffre, toutes déchiffrent (rotation sans interruption, comme le
  coffre et les sauvegardes) ;
- fichier ``<racine>/<type>/<nom>.enc`` = ``b"CDT1\\n"`` + jeton Fernet (AES-128-CBC + HMAC-SHA256 : une trace
  altérée ou chiffrée par une autre clé est refusée) ; écriture atomique (fichier temporaire + ``os.replace``),
  droits 0600, répertoires 0700 ;
- les traces sont petites (JSON de quelques Ko, PDF Factur-X de quelques centaines de Ko) : un seul jeton.

Migration des traces existantes : ``chiffrer_en_clair`` (appelé par ``controldone migrer``, donc par le service
ponctuel ``migrer`` de docker-compose à chaque mise à jour) chiffre chaque fichier en clair puis le supprime ;
idempotent, une trace déjà chiffrée n'est jamais retouchée. La sauvegarde copie les fichiers tels quels (chiffrés,
puis de nouveau chiffrés dans l'archive) ; la restauration les remet en place ; le contrôle approfondi
(``controle_restauration``) vérifie que chacun se déchiffre avec les clés fournies.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

from cryptography.fernet import InvalidToken, MultiFernet

from controldone.storage.cles import deriver_multifernet
from controldone.storage.erreurs import ErreurIntegrite

__all__ = ["EXTENSION", "MAGIE", "TracesEnvoi", "chiffrer_en_clair", "racine_par_defaut"]

MAGIE = b"CDT1\n"
EXTENSION = ".enc"
USAGE = "outbox_envoyee"
_NOM_RE = re.compile(r"[^A-Za-z0-9._-]")


def racine_par_defaut() -> Path:
    from controldone.config import get_settings

    return Path(get_settings().data_dir) / "outbox_envoyee"


class TracesEnvoi:
    """Répertoire des traces d'envoi, chiffrées par une clé dérivée de la clé maîtresse."""

    def __init__(self, racine: Path | str, cles_maitresses: Sequence[bytes]) -> None:
        self.racine = Path(racine)
        self._fernet: MultiFernet = deriver_multifernet(cles_maitresses, USAGE)

    @classmethod
    def depuis_env(cls, racine: Path | str | None = None) -> TracesEnvoi:
        from controldone.config import get_settings
        from controldone.storage.cles import charger_cles_maitresses

        cles = charger_cles_maitresses(data_dir=get_settings().data_dir)
        return cls(racine if racine is not None else racine_par_defaut(), cles)

    # --- écriture / lecture ---
    def chemin(self, kind: str, nom: str) -> Path:
        """``<racine>/<kind>/<nom>.enc`` (noms assainis : aucun séparateur ni ``..``)."""
        k = _NOM_RE.sub("_", kind).strip(".") or "inconnu"
        n = _NOM_RE.sub("_", nom).lstrip(".") or "trace"
        return self.racine / k / f"{n}{EXTENSION}"

    def ecrire(self, kind: str, nom: str, contenu: bytes) -> Path:
        """Chiffre et écrit (idempotent : réécrit la même trace au même endroit)."""
        cible = self.chemin(kind, nom)
        self._ecrire_atomique(cible, MAGIE + self._fernet.encrypt(bytes(contenu)))
        return cible

    def ecrire_json(self, kind: str, nom: str, donnees: dict[str, object]) -> Path:
        brut = json.dumps(donnees, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        return self.ecrire(kind, f"{nom}.json", brut)

    def lire(self, chemin: Path | str) -> bytes:
        """Contenu en clair d'une trace chiffrée ; ``ErreurIntegrite`` si altérée ou clé inconnue."""
        brut = Path(chemin).read_bytes()
        if not brut.startswith(MAGIE):
            raise ErreurIntegrite("trace d'envoi non chiffrée ou d'un format inconnu")
        try:
            return self._fernet.decrypt(brut[len(MAGIE) :])
        except InvalidToken as exc:
            raise ErreurIntegrite("trace d'envoi indéchiffrable (clé inconnue ou fichier altéré)") from exc

    def lire_json(self, chemin: Path | str) -> dict[str, object]:
        donnees = json.loads(self.lire(chemin).decode("utf-8"))
        if not isinstance(donnees, dict):
            raise ErreurIntegrite("trace d'envoi JSON inattendue")
        return donnees

    def lister(self) -> Iterator[Path]:
        """Traces chiffrées (``<kind>/<nom>.enc``), dans l'ordre des chemins."""
        if not self.racine.is_dir():
            return
        yield from sorted(
            p for p in self.racine.glob(f"*/*{EXTENSION}") if p.is_file() and not p.name.startswith(".")
        )

    def en_clair(self) -> list[Path]:
        """Fichiers encore en clair (traces écrites avant D-4106), hors fichiers temporaires."""
        if not self.racine.is_dir():
            return []
        return sorted(
            p
            for p in self.racine.glob("*/*")
            if p.is_file()
            and not p.is_symlink()
            and not p.name.startswith(".")
            and not p.name.endswith(EXTENSION)
        )

    def supprimer_client(self, tenant_id: str) -> int:
        """Effacement RGPD : supprime les traces JSON dont le champ ``tenant_id`` est ce client (traces chiffrées
        et, s'il en reste, traces en clair). Les factures émises (PDF, obligation de conservation) restent."""
        n = 0
        for p in [*self.lister(), *self.en_clair()]:
            try:
                if p.name.endswith(EXTENSION):
                    if not p.name.endswith(".json" + EXTENSION):
                        continue
                    donnees = self.lire_json(p)
                else:
                    if p.suffix != ".json":
                        continue
                    donnees = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(donnees, dict) or donnees.get("tenant_id") != tenant_id:
                    continue
                p.unlink()
                n += 1
            except (OSError, ValueError, ErreurIntegrite):
                continue
        return n

    # --- migration ---
    def chiffrer_en_clair(self) -> int:
        """Chiffre chaque trace encore en clair (``<nom>`` -> ``<nom>.enc``) puis supprime le clair. Idempotent ;
        le chiffré est écrit et relu avant la suppression du clair (une interruption ne perd rien)."""
        n = 0
        for p in self.en_clair():
            contenu = p.read_bytes()
            cible = p.with_name(p.name + EXTENSION)
            self._ecrire_atomique(cible, MAGIE + self._fernet.encrypt(contenu))
            if self.lire(cible) != contenu:  # pragma: no cover - défense
                raise ErreurIntegrite(f"relecture de la trace chiffrée {cible.name} différente")
            p.unlink()
            n += 1
        return n

    def tourner_cles(self, nouvelles_cles: Sequence[bytes]) -> int:
        """Rechiffre chaque trace avec la première de ``nouvelles_cles`` (qui contient aussi les anciennes)."""
        nouveau = deriver_multifernet(nouvelles_cles, USAGE)
        n = 0
        for p in list(self.lister()):
            clair = self.lire(p)
            self._ecrire_atomique(p, MAGIE + nouveau.encrypt(clair))
            n += 1
        self._fernet = nouveau
        return n

    @staticmethod
    def _ecrire_atomique(cible: Path, donnees: bytes) -> None:
        cible.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=cible.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(donnees)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, cible)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def chiffrer_en_clair(
    racine: Path | str | None = None, cles_maitresses: Sequence[bytes] | None = None
) -> int:
    """Étape de migration des données (``controldone migrer``) : chiffre les traces d'envoi encore en clair."""
    if cles_maitresses is None:
        return TracesEnvoi.depuis_env(racine).chiffrer_en_clair()
    return TracesEnvoi(
        racine if racine is not None else racine_par_defaut(), cles_maitresses
    ).chiffrer_en_clair()
