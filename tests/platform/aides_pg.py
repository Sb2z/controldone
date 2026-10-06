"""PostgreSQL pour les tests : un serveur JETABLE désigné par ``CONTROLDONE_TEST_PG_URL`` (URL d'administration,
droit CREATEDB ; ex. ``scripts/pg_jetable.sh demarrer`` puis ``postgresql+pg8000://cd@127.0.0.1:55432/postgres``).
Sans cette variable (ou sans le pilote pg8000), les tests PostgreSQL sont ignorés : ils ne tournent jamais contre
un serveur non prévu pour cela."""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator

import pytest


def serveur_pg() -> str:
    url = os.environ.get("CONTROLDONE_TEST_PG_URL", "").strip()
    if not url:
        pytest.skip("PostgreSQL : CONTROLDONE_TEST_PG_URL non défini (scripts/pg_jetable.sh demarrer)")
    pytest.importorskip("pg8000")
    return url


@pytest.fixture
def base_pg() -> Iterator[str]:
    """URL d'une base PostgreSQL vide, supprimée après le test."""
    from controldone.storage.sauvegarde import creer_base_pg, supprimer_base_pg

    serveur = serveur_pg()
    nom = f"cd_test_{secrets.token_hex(5)}"
    url = creer_base_pg(serveur, nom)
    try:
        yield url
    finally:
        supprimer_base_pg(serveur, nom)
