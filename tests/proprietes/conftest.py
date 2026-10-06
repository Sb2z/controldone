"""Profils Hypothesis des tests de propriétés (D-3903).

``HYPOTHESIS_PROFILE`` choisit le profil : ``dev`` (défaut, 100 exemples), ``ci`` (borné, déterministe : 150
exemples, graine fixe, pas de base d'exemples), ``intensif`` (2 000 exemples, à lancer à la main :
``make proprietes PROFIL=intensif``).
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile("dev", max_examples=100, deadline=None)
settings.register_profile("ci", max_examples=150, deadline=None, derandomize=True, database=None,
                          print_blob=True, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("intensif", max_examples=2000, deadline=None,
                          suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
