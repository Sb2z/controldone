"""Clé maîtresse et clés dérivées (SPEC §20.1 : secrets hors dépôt, chiffrement au repos).

- ``CONTROLDONE_MASTER_KEY`` : une ou plusieurs clés Fernet (base64 urlsafe, 32 octets) séparées par des
  virgules ; la **première** chiffre, toutes déchiffrent (rotation sans interruption).
- Mode (``CONTROLDONE_ENV``) : ``dev`` (défaut), ``test`` ou ``prod``. Sans clé : en ``prod`` le service
  **refuse de démarrer** (``CleManquante``) ; en ``dev``/``test`` une clé est générée dans
  ``<data_dir>/dev_master.key`` (droits 0600) avec un avertissement bruyant.
- Clés dérivées par HKDF-SHA256 (``info`` = usage, ex. ``vault:<client>``, ``sauvegarde``, ``secrets``) :
  une clé par client pour le coffre, une pour les sauvegardes, une pour les secrets (TOTP).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import warnings
from collections.abc import Sequence
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from controldone.config import env
from controldone.storage.erreurs import CleManquante, ErreurIntegrite

__all__ = [
    "SEL_HKDF",
    "charger_cles_maitresses",
    "chiffrer_secret",
    "dechiffrer_secret",
    "deriver_fernet",
    "deriver_multifernet",
    "empreinte_cle",
    "mode_execution",
    "nouvelle_cle",
]

log = logging.getLogger("controldone.storage.cles")

SEL_HKDF = b"controldone/v2/hkdf"
_FICHIER_DEV = "dev_master.key"


def mode_execution() -> str:
    mode = env("CONTROLDONE_ENV", "dev").strip().lower()
    return mode if mode in ("dev", "test", "prod") else "prod"  # valeur inconnue : le plus strict


def nouvelle_cle() -> str:
    return Fernet.generate_key().decode()


def _valider(cle: str) -> bytes:
    brut = cle.strip().encode()
    try:
        if len(base64.urlsafe_b64decode(brut)) != 32:
            raise ValueError
        Fernet(brut)
    except Exception as exc:
        raise CleManquante("CONTROLDONE_MASTER_KEY invalide (clé Fernet attendue)") from exc
    return brut


#: Préfixe de l'empreinte publique d'une clé maîtresse (D-4703) : toute modification casse la procédure de
#: contrôle de la copie papier séquestrée (``docs/EXPLOITATION.md``), qui recalcule la même formule hors de
#: l'application.
PREFIXE_EMPREINTE = b"controldone:empreinte-cle:"


def empreinte_cle(cle: bytes | str) -> str:
    """Empreinte **publique** d'une clé maîtresse : 16 chiffres hexadécimaux (64 bits du SHA-256 de la clé
    préfixée), groupés par 4. Ne permet pas de retrouver la clé (256 bits aléatoires) ; sert à vérifier qu'une
    copie (papier séquestré, coffre de mots de passe) est bien la clé qui ouvre les archives, sans l'afficher."""
    brut = cle.encode() if isinstance(cle, str) else cle
    h = hashlib.sha256(PREFIXE_EMPREINTE + brut.strip()).hexdigest()[:16]
    return " ".join(h[i : i + 4] for i in range(0, 16, 4))


def charger_cles_maitresses(*, mode: str | None = None, data_dir: Path | str | None = None) -> list[bytes]:
    """Clés maîtresses (la première est la clé courante)."""
    mode = mode or mode_execution()
    brut = env("CONTROLDONE_MASTER_KEY", "").strip()
    if brut:
        return [_valider(c) for c in brut.split(",") if c.strip()]
    if mode == "prod":
        raise CleManquante("CONTROLDONE_MASTER_KEY absente : démarrage refusé en production")
    if data_dir is None:
        from controldone.config import get_settings

        data_dir = get_settings().data_dir
    chemin = Path(data_dir) / _FICHIER_DEV
    if not chemin.exists():
        chemin.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(nouvelle_cle())
    message = (
        f"!!! CLÉ MAÎTRESSE DE DÉVELOPPEMENT utilisée ({chemin}) — NE PAS UTILISER EN PRODUCTION : "
        "définir CONTROLDONE_MASTER_KEY et CONTROLDONE_ENV=prod !!!"
    )
    log.warning(message)
    warnings.warn(message, stacklevel=2)
    return [_valider(chemin.read_text())]


def deriver_fernet(cle_maitresse: bytes, usage: str) -> Fernet:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=SEL_HKDF, info=usage.encode())
    brut = base64.urlsafe_b64decode(cle_maitresse)
    return Fernet(base64.urlsafe_b64encode(hkdf.derive(brut)))


def deriver_multifernet(cles_maitresses: Sequence[bytes], usage: str) -> MultiFernet:
    if not cles_maitresses:
        raise CleManquante("aucune clé maîtresse")
    return MultiFernet([deriver_fernet(c, usage) for c in cles_maitresses])


def chiffrer_secret(cles_maitresses: Sequence[bytes], secret: str) -> str:
    return deriver_multifernet(cles_maitresses, "secrets").encrypt(secret.encode()).decode()


def dechiffrer_secret(cles_maitresses: Sequence[bytes], jeton: str) -> str:
    try:
        return deriver_multifernet(cles_maitresses, "secrets").decrypt(jeton.encode()).decode()
    except InvalidToken as exc:
        raise ErreurIntegrite("secret indéchiffrable (clé inconnue ou contenu altéré)") from exc
