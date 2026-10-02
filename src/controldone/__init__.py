"""ControlDOne v2 — contrôle de cohérence des documents d'import.

Versions exposées (toutes citées par chaque ``Execution``, SPEC §6.2.12) :

- ``__version__`` / ``VERSION_MOTEUR`` : version du moteur (paquet) ;
- ``SCHEMA_VERSION`` : version du modèle de données (``controldone.dossier/<x.y.z>``, SPEC §6.4) ;
- ``VERSION_REGLES`` : version de l'ensemble des règles de contrôle (incrémentée à chaque changement
  de sémantique d'un contrôle ; un nouvel identifiant est créé si le sens change, SPEC §6.4) ;
- ``VERSION_NORMALISATION`` : version des fonctions de ``controldone.normalize`` (clé d'idempotence §7).
"""

__version__ = "2.0.0"
VERSION_MOTEUR = __version__
SCHEMA_VERSION = "2.0.0"
VERSION_REGLES = "2.0.0"
VERSION_NORMALISATION = "1.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "VERSION_MOTEUR",
    "VERSION_NORMALISATION",
    "VERSION_REGLES",
    "__version__",
]
