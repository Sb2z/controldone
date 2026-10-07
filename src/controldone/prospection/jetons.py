"""Jetons des liens de désinscription : ``<empreinte>.<signature>`` (base64url), HMAC-SHA256 (D-5007).

- L'adresse n'apparaît pas dans le lien : seule son empreinte SHA-256 (celle de la liste d'opposition).
- Secret : ``CONTROLDONE_PROSPECTION_SECRET`` (plusieurs valeurs séparées par des virgules, la première signe,
  toutes vérifient : rotation sans casser les liens déjà envoyés) ; à défaut, dérivé de chaque clé maîtresse
  (``controldone/desinscription|``). Jamais écrit dans le code ni dans la base.
- Aucune expiration : une demande d'opposition doit rester possible aussi longtemps que le message existe.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Sequence

__all__ = ["JetonInvalide", "emettre", "secrets_depuis_env", "verifier"]

_CONTEXTE = b"controldone/prospection/desinscription|"


class JetonInvalide(ValueError):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _deb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def secrets_depuis_env() -> list[bytes]:
    from controldone.config import env

    brut = env("CONTROLDONE_PROSPECTION_SECRET", "").strip()
    if brut:
        valeurs = [v.strip().encode("utf-8") for v in brut.split(",") if v.strip()]
        if any(len(v) < 32 for v in valeurs):
            raise ValueError("CONTROLDONE_PROSPECTION_SECRET : 32 caractères au moins")
        return valeurs
    from controldone.storage.cles import charger_cles_maitresses

    return [hashlib.sha256(b"controldone/desinscription|" + c).digest() for c in charger_cles_maitresses()]


def _signature(secret: bytes, empreinte_hex: str) -> bytes:
    return hmac.new(secret, _CONTEXTE + empreinte_hex.encode("ascii"), hashlib.sha256).digest()[:16]


def emettre(empreinte_hex: str, secrets_: Sequence[bytes]) -> str:
    if len(empreinte_hex) != 64 or any(c not in "0123456789abcdef" for c in empreinte_hex):
        raise ValueError("empreinte SHA-256 attendue")
    if not secrets_:
        raise ValueError("aucun secret de signature")
    return f"{_b64(bytes.fromhex(empreinte_hex))}.{_b64(_signature(secrets_[0], empreinte_hex))}"


def verifier(jeton: str, secrets_: Sequence[bytes]) -> str:
    """Empreinte (hexadécimal) d'un jeton valide ; ``JetonInvalide`` sinon (forme, longueur ou signature)."""
    if not isinstance(jeton, str) or len(jeton) > 100 or jeton.count(".") != 1:
        raise JetonInvalide("jeton mal formé")
    a, b = jeton.split(".")
    try:
        brut, sig = _deb64(a), _deb64(b)
    except (ValueError, TypeError):
        raise JetonInvalide("jeton mal formé") from None
    if len(brut) != 32 or len(sig) != 16:
        raise JetonInvalide("jeton mal formé")
    emp = brut.hex()
    if not any(hmac.compare_digest(sig, _signature(s, emp)) for s in secrets_):
        raise JetonInvalide("signature invalide")
    return emp
