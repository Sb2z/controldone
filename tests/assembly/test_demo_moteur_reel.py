"""Jeu de démonstration traité par les **extracteurs réels** (mise en page inconnue des extracteurs, D-950 à
D-953) : constats attendus et famille A évaluée."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(scope="module")
def demo_reel(tmp_path_factory):
    from controldone.demo import executer_demo

    base = tmp_path_factory.mktemp("demo_reel")
    return executer_demo(base / "out", racine=base / "jeu", moteur="reel")


def test_constats_du_moteur_reel(demo_reel):
    findings = {d["dossier_id"]: d for d in json.loads(demo_reel.findings.read_text(encoding="utf-8"))}
    constats = {k: {(c["controle_id"], c["niveau"]) for c in d["constats"]} for k, d in findings.items()}
    assert constats["D-2026-00001"] == {("C3", "ecart_certain"), ("D3", "ecart_certain")}
    assert constats["D-2026-00002"] == {("B1", "ecart_certain"), ("A12", "a_verifier")}
    assert constats["D-2026-00003"] == set()
    assert [findings[k]["statut_global"] for k in sorted(findings)] == ["ecart_certain", "ecart_certain", "conforme"]
    a12 = next(c for c in findings["D-2026-00002"]["constats"] if c["controle_id"] == "A12")
    assert a12["montant_en_jeu"] is None


def test_famille_a_evaluee(demo_reel):
    """Seul A9 (quantités, non imprimées sur les déclarations du jeu) reste non vérifiable."""
    for d in json.loads(demo_reel.findings.read_text(encoding="utf-8")):
        non_verifiables = {r["controle_id"] for r in d["resultats"]
                           if r["controle_id"].startswith("A") and r["outcome"] == "non_verifiable"}
        assert non_verifiables <= {"A9"}, (d["dossier_id"], non_verifiables)
