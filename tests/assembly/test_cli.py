"""Ligne de commande : ``controldone demo`` de bout en bout et ``controldone diagnostic``."""

from __future__ import annotations

import json

from controldone.cli import main


def test_demo_bout_en_bout(tmp_path, capsys):
    out, jeu = tmp_path / "var_demo", tmp_path / "demo"
    assert main(["demo", "--out", str(out), "--demo-dir", str(jeu)]) == 0
    sortie = capsys.readouterr().out
    assert "DONNÉES FICTIVES" in sortie and str((out / "report.pdf").resolve()) in sortie
    for nom in ("report.html", "report.pdf", "report.json", "findings.json", "findings.xlsx"):
        assert (out / nom).stat().st_size > 0
    assert len(list((jeu / "dossiers").glob("*/docs/*.pdf"))) == 9
    assert json.loads((jeu / "clients" / "DEMO" / "profil.json").read_text(encoding="utf-8"))["demo"] is True


def test_jeu_fictif_reproductible(tmp_path):
    from controldone.demo.generateur import generer_demo

    a, b = generer_demo(tmp_path / "a"), generer_demo(tmp_path / "b")
    fa = sorted(p.relative_to(a) for p in a.rglob("*.pdf"))
    assert fa == sorted(p.relative_to(b) for p in b.rglob("*.pdf"))
    for rel in fa:
        assert (a / rel).read_bytes() == (b / rel).read_bytes()


def test_diagnostic_sur_un_dossier(tmp_path, capsys):
    from controldone.demo.generateur import generer_demo

    jeu = generer_demo(tmp_path / "jeu")
    out = tmp_path / "rapport"
    code = main(["diagnostic", str(jeu / "dossiers" / "DEMO-2" / "docs"),
                 "--client-profile", str(jeu / "clients" / "DEMO" / "profil.json"),
                 "--grilles", str(jeu / "clients" / "DEMO" / "grilles"), "--out", str(out), "--seed", "3",
                 "--sans-llm"])
    assert code == 0
    assert (out / "report.pdf").exists() and (out / "findings.xlsx").exists()
    f = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert {d["file"] for d in f["documents"]} == {
        "docs/declaration_26FRD2FIC000005822.pdf", "docs/facture_commerciale_INV-FIC-0202.pdf",
        "docs/facture_transitaire_FT-FIC-0502.pdf"}


def test_diagnostic_source_introuvable(tmp_path, capsys):
    assert main(["diagnostic", str(tmp_path / "absent"), "--out", str(tmp_path / "o")]) == 2
