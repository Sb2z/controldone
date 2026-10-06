"""Hachage des mots de passe (Argon2id, paramètres par défaut d'argon2-cffi)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

__all__ = [
    "LONGUEUR_MIN",
    "MotDePasseFaible",
    "doit_rehacher",
    "hacher_mot_de_passe",
    "verifier_mot_de_passe",
]

LONGUEUR_MIN = 12
_PH = PasswordHasher()


class MotDePasseFaible(ValueError):
    pass


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    if len(mot_de_passe) < LONGUEUR_MIN:
        raise MotDePasseFaible(f"au moins {LONGUEUR_MIN} caractères")
    if len(mot_de_passe) > 1024:
        raise MotDePasseFaible("mot de passe trop long")
    return _PH.hash(mot_de_passe)


def verifier_mot_de_passe(hache: str, mot_de_passe: str) -> bool:
    try:
        return _PH.verify(hache, mot_de_passe)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def doit_rehacher(hache: str) -> bool:
    return _PH.check_needs_rehash(hache)
