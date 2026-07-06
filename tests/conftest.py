"""Test configuration: activate a synthetic client profile for every test.

The engine reads all client-specific data (VAT/SIREN, name & address aliases,
HS scope) from the active profile.  Tests must never use real client data, so
they run against the synthetic ``acme`` profile in ``tests/fixtures/acme``.
"""
from pathlib import Path

import pytest

from controldone.profile import load_profile, use_profile

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "acme"


@pytest.fixture(autouse=True)
def synthetic_profile():
    """Make the synthetic ACME profile the active profile for each test."""
    with use_profile(load_profile(client_dir=_FIXTURE_DIR)) as profile:
        yield profile
