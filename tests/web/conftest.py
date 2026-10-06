"""Fixtures de l'interface web, de l'API et du serveur MCP : base de démonstration (données fictives)
construite une fois par session par ``initialiser_demo`` (vrai pipeline, vrai worker), puis copiée pour
chaque test."""

from __future__ import annotations

import warnings

import pytest
from aides_web import (
    CLE_MAITRESSE,
    MDP_FONDATEUR,
    SECRET_SESSION,
    Modele,
    Monde,
    construire_monde,
    plateforme,
)

from controldone.auth.cles_api import creer_cle_api
from controldone.auth.roles import Acteur, Role
from controldone.jobs.metriques import METRIQUES
from controldone.services.demo_init import initialiser_demo
from controldone.storage.models import Constat, Document, Dossier, Ecart, Fichier, Lot


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLDONE_ENV", "test")
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", CLE_MAITRESSE.decode())
    monkeypatch.setenv("CONTROLDONE_SECRET_KEY", SECRET_SESSION)
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "var"))
    METRIQUES.reinitialiser()
    warnings.filterwarnings("ignore", category=UserWarning)
    yield


@pytest.fixture(scope="session")
def _modele(tmp_path_factory) -> Modele:
    mp = pytest.MonkeyPatch()
    mp.setenv("CONTROLDONE_ENV", "test")
    mp.setenv("CONTROLDONE_MASTER_KEY", CLE_MAITRESSE.decode())
    racine = tmp_path_factory.mktemp("web_modele")
    mp.setenv("CONTROLDONE_DATA_DIR", str(racine / "var"))
    pf = plateforme(racine)
    res = initialiser_demo(pf, mot_de_passe_fondateur=MDP_FONDATEUR)
    fondateur = Acteur("usr_fondateur_demo", Role.fondateur)
    cles = {}
    with pf.db.operateur(fondateur) as op:
        for t in ("demo_ateliers", "demo_nord"):
            cles[t] = creer_cle_api(op.client(t, "clé de test"), "tests").cle
    ids: dict[str, dict[str, list[str]]] = {}
    systeme = Acteur.systeme("tests")
    for t in ("demo_ateliers", "demo_nord"):
        with pf.db.tenant(t, systeme, lecture=True) as s:
            ids[t] = {
                "dossier": [d.id for d in s.lister(Dossier, ordre=Dossier.reference)],
                "document": [d.id for d in s.lister(Document)],
                "fichier": [f.id for f in s.lister(Fichier) if f.coffre_ref],
                "lot": [x.id for x in s.lister(Lot)],
                "constat": [c.id for c in s.lister(Constat)],
                "constat_propose": [c.id for c in s.lister(Constat) if c.statut_validation == "propose"],
                "constat_valide": [c.id for c in s.lister(Constat) if c.statut_validation == "valide"],
                "ecart": [e.id for e in s.lister(Ecart)],
            }
    from controldone.outbox import FileSortante

    for a in FileSortante(pf.db).lister(fondateur):
        if a.tenant_id in ids:
            ids[a.tenant_id].setdefault("sortie", []).append(a.id)
            if a.statut.value == "envoye":
                ids[a.tenant_id].setdefault("sortie_envoyee", []).append(a.id)
    pf.db.fermer()
    mp.undo()
    return Modele(
        racine=racine,
        totp=res.totp_secret,
        comptes={c.email: c.mot_de_passe for c in res.comptes},
        cles=cles,
        ids=ids,
    )


@pytest.fixture
def monde(_modele, tmp_path) -> Monde:
    m = construire_monde(_modele, tmp_path)
    yield m
    m.pf.db.fermer()
