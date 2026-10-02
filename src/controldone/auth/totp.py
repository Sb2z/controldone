"""Second facteur TOTP (RFC 6238 sur HOTP RFC 4226), bibliothèque standard seulement (hmac, hashlib).

``verifier_totp`` renvoie le **pas** accepté (pour l'anti-rejeu : un pas déjà utilisé est refusé par
``storage.comptes.utiliser_pas_totp``) ou ``None``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

__all__ = ["code_hotp", "code_totp", "generer_secret", "pas_courant", "uri_provisioning", "verifier_totp"]

_ALGOS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}


def generer_secret(octets: int = 20) -> str:
    """Secret base32 (sans « = »), 160 bits par défaut."""
    return base64.b32encode(secrets.token_bytes(octets)).decode().rstrip("=")


def _cle(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_hotp(cle: bytes, compteur: int, *, chiffres: int = 6, algo: str = "SHA1") -> str:
    mac = hmac.new(cle, struct.pack(">Q", compteur), _ALGOS[algo]).digest()
    decalage = mac[-1] & 0x0F
    binaire = struct.unpack(">I", mac[decalage:decalage + 4])[0] & 0x7FFFFFFF
    return str(binaire % 10**chiffres).zfill(chiffres)


def pas_courant(t: float | None = None, *, periode: int = 30) -> int:
    return int((time.time() if t is None else t) // periode)


def code_totp(secret: str, t: float | None = None, *, periode: int = 30, chiffres: int = 6, algo: str = "SHA1") -> str:
    return code_hotp(_cle(secret), pas_courant(t, periode=periode), chiffres=chiffres, algo=algo)


def verifier_totp(secret: str, code: str, t: float | None = None, *, fenetre: int = 1, periode: int = 30,
                  chiffres: int = 6, algo: str = "SHA1") -> int | None:
    """Pas accepté (tolérance de ± ``fenetre`` pas pour la dérive d'horloge), sinon ``None``."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != chiffres or not code.isdigit():
        return None
    cle = _cle(secret)
    pas = pas_courant(t, periode=periode)
    trouve = None
    for d in range(-fenetre, fenetre + 1):
        # comparaison à temps constant, sans sortie anticipée
        if hmac.compare_digest(code_hotp(cle, pas + d, chiffres=chiffres, algo=algo), code):
            trouve = pas + d
    return trouve


def uri_provisioning(secret: str, compte: str, emetteur: str = "ControlDOne") -> str:
    params = urlencode({"secret": secret, "issuer": emetteur, "algorithm": "SHA1", "digits": 6, "period": 30})
    return f"otpauth://totp/{quote(emetteur)}:{quote(compte)}?{params}"
