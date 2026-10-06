"""Outil d'analyse du bruit ``scripts/analyse_bruit.py`` (D-3701) — banc fictif minimal."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("analyse_bruit", RACINE / "scripts" / "analyse_bruit.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules["analyse_bruit"] = m  # dataclasses : module enregistré avant exécution
    spec.loader.exec_module(m)
    return m


def _ecrire(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture
def banc(tmp_path):
    corpus, run = tmp_path / "corpus", tmp_path / "out" / "x_dev"
    _ecrire(corpus / "dev" / "ZZ0001" / "truth.json", {
        "dossier_id": "ZZ0001", "declaration_layout": "M9", "transitaire_template": "G99", "degradation": "d1",
        "documents": [{"doc_id": "ft1", "type": "facture_transitaire", "format": "pdf_scan", "degradation": "d1",
                       "degradation_mode": "scan300", "file": "docs/ft.pdf", "transitaire_template": "G99"}],
        "traps": [{"trap_id": "ZZ0001-T1", "control_id": "D1", "description": "Piège fictif."}],
    })
    constat = {"finding_id": "f1", "controle_id": "D1", "niveau": "a_verifier", "sous_controle": "total_ht",
               "raisons": ["confiance_insuffisante"], "libelle": "Libellé fictif", "documents_concernes": ["d1"]}
    _ecrire(run / "ZZ0001" / "findings.json", {
        "documents": [{"document_id": "d1", "type": "facture_transitaire", "file": "docs/ft.pdf"}],
        "constats": [constat, {**constat, "finding_id": "f2"}],
    })
    _ecrire(run / "metrics.json", {
        "global": {"n_dossiers": 1, "fp_a_verifier": 2, "bruit_a_verifier_par_dossier": 2.0, "violations_pieges": 1},
        "details": [
            {"dossier_id": "ZZ0001", "finding_id": "f1", "controle_id": "D1", "classe": "fp_a_verifier",
             "motif": "non_apparie", "trap_id": None},
            {"dossier_id": "ZZ0001", "finding_id": "f2", "controle_id": "D1", "classe": "fp_a_verifier",
             "motif": "piege", "trap_id": "ZZ0001-T1"},
        ],
    })
    return corpus, run


def test_ventilation_par_controle_raison_document_et_piege(banc):
    m = _module()
    corpus, run = banc
    bruits, cpts = m.collecter(corpus, "dev", run)
    assert len(bruits) == 2 and cpts["doublons_lot"] == [("ZZ0001", "D1", "Libellé fictif", 2)]
    t = m.ventiler(bruits)
    assert t["controle_sous"]["D1:total_ht"] == 2
    assert t["controle_raison"]["D1:total_ht | confiance_insuffisante"] == 2
    assert t["type_doc"]["facture_transitaire/pdf_scan/d1/G99"] == 2
    assert t["degradation_doc"]["d1:scan300"] == 2 and t["mise_en_page"]["M9"] == 2
    assert t["pieges_description"]["D1 | Piège fictif."] == 1 and t["motif"] == {"non_apparie": 1, "piege": 1}


def test_holdout_refuse_et_sortie_json(banc, tmp_path, capsys):
    m = _module()
    corpus, run = banc
    with pytest.raises(ValueError):
        m.collecter(corpus, "holdout", run)
    sortie = tmp_path / "bruit.json"
    assert m.main(["--corpus", str(corpus), "--run", str(run), "--avant", str(run), "--json", str(sortie)]) == 0
    assert "D1:total_ht" in capsys.readouterr().out
    assert json.loads(sortie.read_text())["tables"]["controle"] == {"D1": 2}
