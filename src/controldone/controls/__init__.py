"""Contrôles (SPEC §8 à §16).

- ``framework`` : cadre commun (contexte, registre, classement, tolérances, moteur) ;
- ``famille_p``, ``famille_a`` … ``famille_g`` : un module par famille ; chaque contrôle est une
  fonction pure décorée par ``@control("X9")``, enregistrée à l'import du module.

Ne rien importer ici depuis les modules ``famille_*`` : le moteur les charge lui-même
(``charger_controles``).
"""
