"""Seuils de couverture (D-4903) : taux global et taux minimal par paquet (``scripts/couverture_paquets.py``
``--min-paquet``), et cohérence des seuils déclarés dans le Makefile, la CI et ``docs/QUALITE.md``."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "couverture_paquets_seuils", RACINE / "scripts/couverture_paquets.py"
)
couverture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(couverture)


def _f(cl, n, cb=0, nb=0):
    return {
        "summary": {
            "covered_lines": cl,
            "num_statements": n,
            "covered_branches": cb,
            "num_branches": nb,
            "percent_covered": 100 * (cl + cb) / (n + nb),
            "missing_lines": n - cl,
            "num_partial_branches": 0,
        }
    }


DONNEES = {
    "files": {
        "src/controldone/controls/famille_a.py": _f(80, 100, 10, 20),  # 75 %
        "src/controldone/auth/jetons.py": _f(95, 100),  # 95 %
        "src/controldone/cli.py": _f(10, 100),
    },
    "totals": {
        "covered_lines": 185,
        "num_statements": 300,
        "covered_branches": 10,
        "num_branches": 20,
        "percent_covered": 60.9,
    },
}


def test_taux_par_paquet_lignes_et_branches():
    assert couverture.taux_par_paquet(DONNEES) == {"controls": 75.0, "auth": 95.0, "(racine)": 10.0}


@pytest.mark.parametrize("valeur", ["controls", "=80", "controls=abc"])
def test_seuil_mal_forme(valeur):
    with pytest.raises(ValueError):
        couverture.seuils_paquets([valeur])


def test_seuils_virgule_decimale():
    assert couverture.seuils_paquets(["controls=85,5", " auth =92"]) == {"controls": 85.5, "auth": 92.0}


def test_paquet_sous_le_seuil_ou_absent():
    assert couverture.paquets_sous_le_seuil(DONNEES, {"controls": 75, "auth": 95}) == []
    erreurs = couverture.paquets_sous_le_seuil(DONNEES, {"controls": 80, "controle": 1})
    assert erreurs == [
        "paquet 'controle' absent du rapport de couverture",
        "Couverture de controls 75.0 % < minimum 80.0 %",
    ]


def test_ligne_de_commande(tmp_path, capsys):
    j = tmp_path / "c.json"
    j.write_text(json.dumps(DONNEES), encoding="utf-8")
    out = str(tmp_path / "p.md")
    assert couverture.main([str(j), "--out", out, "--min", "60", "--min-paquet", "controls=75 auth=95"]) == 0
    assert couverture.main([str(j), "--out", out, "--min-paquet", "controls=76"]) == 1
    assert "controls 75.0 % < minimum 76.0 %" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        couverture.main([str(j), "--out", out, "--min-paquet", "controls"])


def _variables_makefile() -> dict[str, str]:
    texte = (RACINE / "Makefile").read_text(encoding="utf-8")
    return dict(re.findall(r"^(COUV_MIN\w*)\s*\?=\s*(.*)$", texte, re.M))


def test_seuils_identiques_makefile_ci_documentation():
    """Un seuil changé à un endroit doit l'être partout (Makefile, job ``complet`` de la CI, ``docs/QUALITE.md``)."""
    mk = _variables_makefile()
    assert float(mk["COUV_MIN"]) > 0
    paquets = couverture.seuils_paquets(mk["COUV_MIN_PAQUETS"].split())
    assert set(paquets) >= {"controls", "auth"}
    ci = (RACINE / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert f'COUV_MIN: "{mk["COUV_MIN"]}"' in ci
    assert f'COUV_MIN_PAQUETS: "{mk["COUV_MIN_PAQUETS"]}"' in ci
    qualite = (RACINE / "docs/QUALITE.md").read_text(encoding="utf-8")
    assert f"COUV_MIN={mk['COUV_MIN']}" in qualite
    for nom, mini in paquets.items():
        assert f"`{nom}` ≥ {mini:g} %".replace(".", ",") in qualite
