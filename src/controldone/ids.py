"""Identifiants triables de type UUID v7, préfixés (SPEC §6.2).

Format : ``<prefixe>_<32 hexadécimaux minuscules>`` (ex. ``doc_0192f3a1...``). L'ordre lexicographique
suit l'ordre de création (horodatage en millisecondes sur 48 bits, puis compteur monotone).

Deux modes :

- normal : horloge système + ``secrets`` (aléa cryptographique) ;
- déterministe (banc, tests) : ``IdGenerator.deterministe(seed)`` — horloge virtuelle partant d'une
  époque fixe et aléa tiré d'un ``random.Random(seed)`` : la même suite d'appels donne les mêmes
  identifiants, octet pour octet.

Pour les objets dont l'identité découle de leur contenu (résultats de contrôle, constats), utiliser
``id_stable(prefixe, *parties)`` : identifiant dérivé d'un SHA-256, identique d'une exécution à l'autre
(indispensable à la reproductibilité de SPEC §6.2.12).
"""

from __future__ import annotations

import hashlib
import random
import re
import secrets
import threading
import time
from enum import StrEnum

__all__ = [
    "PREFIXE_RE",
    "IdGenerator",
    "Prefixe",
    "id_stable",
    "nouvel_id",
    "set_generateur_global",
    "uuid7_hex",
]


class Prefixe(StrEnum):
    """Préfixes d'identifiants par entité."""

    client = "cli"
    entite = "ent"
    transitaire = "tra"
    grille = "grl"
    profil = "tol"
    lot = "lot"
    fichier = "fic"
    page = "pag"
    document = "doc"
    valeur = "vs"
    dossier = "dos"
    lien = "lnk"
    allocation = "alc"
    resultat = "res"
    constat = "f"
    execution = "exe"
    correction = "cor"
    reclamation = "rec"
    ecart = "eca"
    evenement = "evt"
    job = "job"


PREFIXE_RE = re.compile(r"^[a-z]{1,8}_[0-9a-f]{32}$")

# Époque de l'horloge virtuelle du mode déterministe : 2026-01-01T00:00:00Z en millisecondes.
_EPOQUE_DETERMINISTE_MS = 1_767_225_600_000


def uuid7_hex(ms: int, rand_a: int, rand_b: int) -> str:
    """Assemble un UUID v7 (RFC 9562) en 32 hexadécimaux.

    ``ms`` : horodatage Unix en millisecondes (48 bits) ; ``rand_a`` : 12 bits ; ``rand_b`` : 62 bits.
    """
    if not 0 <= ms < (1 << 48):
        raise ValueError("horodatage hors plage (48 bits)")
    valeur = (ms & ((1 << 48) - 1)) << 80
    valeur |= 0x7 << 76  # version 7
    valeur |= (rand_a & 0xFFF) << 64
    valeur |= 0b10 << 62  # variante RFC 4122/9562
    valeur |= rand_b & ((1 << 62) - 1)
    return f"{valeur:032x}"


class IdGenerator:
    """Générateur d'identifiants UUID v7 préfixés, monotone, sûr entre fils d'exécution."""

    def __init__(self, seed: int | None = None, *, horloge_ms: int | None = None) -> None:
        self._verrou = threading.Lock()
        self._deterministe = seed is not None
        self._rng = random.Random(seed) if seed is not None else None
        self._horloge_virtuelle = horloge_ms if horloge_ms is not None else _EPOQUE_DETERMINISTE_MS
        self._dernier_ms = -1
        self._compteur = 0

    @classmethod
    def deterministe(cls, seed: int, *, horloge_ms: int | None = None) -> IdGenerator:
        return cls(seed, horloge_ms=horloge_ms)

    @property
    def est_deterministe(self) -> bool:
        return self._deterministe

    def _bits(self, n: int) -> int:
        if self._rng is not None:
            return self._rng.getrandbits(n)
        return secrets.randbits(n)

    def _maintenant_ms(self) -> int:
        if self._deterministe:
            # L'horloge virtuelle avance d'une milliseconde par identifiant : ordre strict garanti.
            self._horloge_virtuelle += 1
            return self._horloge_virtuelle
        return time.time_ns() // 1_000_000

    def hex(self) -> str:
        with self._verrou:
            ms = self._maintenant_ms()
            if ms <= self._dernier_ms:
                # Même milliseconde (ou horloge reculée) : on garde le dernier horodatage et on
                # incrémente le compteur porté par rand_a (méthode 1 de la RFC 9562).
                ms = self._dernier_ms
                self._compteur += 1
                if self._compteur > 0xFFF:
                    ms += 1
                    self._compteur = 0
            else:
                self._compteur = self._bits(11)  # laisse de la marge pour incrémenter
            self._dernier_ms = ms
            return uuid7_hex(ms, self._compteur, self._bits(62))

    def nouveau(self, prefixe: Prefixe | str) -> str:
        """Nouvel identifiant ``<prefixe>_<hex>``."""
        return f"{Prefixe(prefixe).value if isinstance(prefixe, Prefixe) else prefixe}_{self.hex()}"

    __call__ = nouveau


_generateur_global = IdGenerator()


def set_generateur_global(generateur: IdGenerator) -> None:
    """Remplace le générateur utilisé par ``nouvel_id`` (ex. mode déterministe du banc)."""
    global _generateur_global
    _generateur_global = generateur


def nouvel_id(prefixe: Prefixe | str) -> str:
    """Nouvel identifiant depuis le générateur global."""
    return _generateur_global.nouveau(prefixe)


def id_stable(prefixe: Prefixe | str, *parties: object) -> str:
    """Identifiant déterministe dérivé du contenu (SHA-256 des parties, format UUID v8).

    Les parties sont converties en texte et jointes par un séparateur non imprimable : même entrée,
    même identifiant, d'une exécution à l'autre et d'une machine à l'autre.
    """
    p = prefixe.value if isinstance(prefixe, Prefixe) else prefixe
    brut = "\x1f".join("" if x is None else str(x) for x in parties)
    h = int.from_bytes(hashlib.sha256(brut.encode("utf-8")).digest()[:16], "big")
    h &= ~(0xF << 76)
    h |= 0x8 << 76  # version 8 (« personnalisée »)
    h &= ~(0b11 << 62)
    h |= 0b10 << 62
    return f"{p}_{h:032x}"
