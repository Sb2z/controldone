"""Fixtures de la revue de sécurité (``docs/REVUE_SECURITE.md``) : reprend le « monde » de démonstration des tests
web (``tests/web/conftest.py`` : base fictive construite une fois par session, copiée pour chaque test)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"
if str(_WEB) not in sys.path:
    sys.path.insert(0, str(_WEB))

_spec = importlib.util.spec_from_file_location("controldone_tests_web_conftest", _WEB / "conftest.py")
assert _spec is not None and _spec.loader is not None
_web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_web)

_env = _web._env
_modele = _web._modele
monde = _web.monde
