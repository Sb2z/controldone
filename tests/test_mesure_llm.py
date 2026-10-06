"""Script de mesure de la lecture par modèle (D-4008) : faux client Anthropic, faux correcteur, aucun réseau ni
corpus réel (le script n'est pas lancé avec une vraie clé dans les tests)."""

import importlib.util
import json
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from controldone.config import Settings
from controldone.extract import ExtractionContext
from controldone.ids import IdGenerator
from controldone.model import Document, Page, PageRef, TypeDocument

RACINE = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("mesure_llm", RACINE / "scripts" / "mesure_llm.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Messages:
    def __init__(self):
        self.appels = []

    def parse(self, **kw):
        self.appels.append(kw)
        sortie = {"valeurs": [{"champ": "total_facture", "index": None, "valeur_brute": "EUR 1 250,00", "page": 1},
                              {"champ": "incoterm", "index": None, "valeur_brute": "CIF", "page": 1}]}
        return SimpleNamespace(parsed_output=kw["output_format"].model_validate(sortie), stop_reason="end_turn",
                               model=kw["model"], usage=SimpleNamespace(input_tokens=2000, output_tokens=300,
                                                                        cache_read_input_tokens=1000,
                                                                        cache_creation_input_tokens=0))


def _metrics(precision, fp, details, exactitude):
    return {"global": {"precision_certain": precision, "rappel": 0.5, "fp_certain": fp, "vp_certain": 10},
            "extraction_par_champ": {"global": {"exactitude": exactitude, "n": 100},
                                     "champs": {"facture_commerciale.total_facture": {"exactitude": exactitude}}},
            "details": details}


def _corpus(tmp_path):
    for d in ("BX0001", "BX0002", "BX0003"):
        (tmp_path / "corpus" / "dev" / d / "docs").mkdir(parents=True)
    (tmp_path / "corpus" / "holdout" / "BX9999" / "docs").mkdir(parents=True)
    return tmp_path / "corpus"


def _executeur(appels):
    def executeur(corpus, dossiers, out, comp, *, workers, journal=None):
        llm = [e for e in comp.extracteurs if e.type == "llm"]
        appels.append({"out": out.name, "dossiers": list(dossiers), "llm": bool(llm), "workers": workers})
        out.mkdir(parents=True, exist_ok=True)
        if llm:
            doc = Document(id="doc_1", type=TypeDocument.facture_commerciale,
                           pages=[PageRef(fichier_id="f", numero=1)])
            pages = [Page(fichier_id="f", numero=1, texte="FACTURE FICTIVE\nTOTAL EUR 1 250,00")]
            for d in dossiers:
                n = len(journal)
                llm[0].extract(doc, pages, ExtractionContext(ids=IdGenerator.deterministe(1), client_id="c",
                                                             dossier_id=d))
                for e in journal[n:]:
                    e.setdefault("dossier", d)
        return {}
    return executeur


def test_mesure_avec_faux_client(tmp_path):
    m = _module()
    corpus = _corpus(tmp_path)
    client = SimpleNamespace(messages=_Messages())
    appels = []
    base = _metrics(1.0, 0, [], 0.90)
    avec = _metrics(1.0, 0, [], 0.92)
    r = m.mesurer(corpus, tmp_path / "out", limit=2, budget_eur=D("1"), client=client,
                  settings=Settings(_env_file=None, anthropic_api_key="sk-test-fictif"),
                  scorer=lambda c, run: base if run.name == "deterministe" else avec,
                  executeur=_executeur(appels))
    assert [a["llm"] for a in appels] == [False, True] and appels[1]["workers"] == 1
    assert appels[0]["dossiers"] == ["BX0001", "BX0002"]  # dev seulement, échantillon limité
    assert len(client.messages.appels) == 2
    assert r["cout"]["appels"] == 2 and D(r["cout"]["total_eur"]) > 0
    assert r["valeurs"]["proposees"] == 4 and r["valeurs"]["rejetees"] == 2 and r["valeurs"]["completees"] == 2
    assert r["extraction"]["deterministe"] == 0.90 and r["extraction"]["llm"] == 0.92
    assert r["verdict"]["passe"] and r["banc"]["nouveaux_faux_certains"] == []
    rapport = (tmp_path / "out" / "rapport.md").read_text(encoding="utf-8")
    assert "Verdict : PASSE" in rapport and "claude-opus-5-5" in rapport
    assert json.loads((tmp_path / "out" / "journal_llm.json").read_text())[0]["dossier"] == "BX0001"


def test_verdict_echoue_sur_nouveau_faux_certain():
    m = _module()
    fp = [{"dossier_id": "BX0001", "controle_id": "B1", "classe": "fp_certain"}]
    r = m.comparer(_metrics(1.0, 0, [], 0.9), _metrics(0.99, 1, fp, 0.9), [], ["BX0001"])
    assert not r["verdict"]["passe"] and r["banc"]["nouveaux_faux_certains"][0]["controle"] == "B1"
    r = m.comparer(_metrics(1.0, 0, [], 0.9), _metrics(0.96, 0, [], 0.9), [], ["BX0001"])
    assert not r["verdict"]["passe"]  # précision < 0,97
    r = m.comparer(_metrics(0.98, 1, fp, 0.9), _metrics(0.98, 1, fp, 0.9), [], ["BX0001"])
    assert r["verdict"]["passe"]  # faux certain déjà présent sans le modèle : pas nouveau


@pytest.mark.parametrize("argv, attendu", [
    (["--corpus", "bench/corpus_g4/holdout"], "split dev"),
    (["--corpus", "bench/corpus_g4"], "clé Anthropic absente"),
])
def test_main_refuse_sans_cle_ou_holdout(monkeypatch, capsys, argv, attendu):
    from controldone.config import reset_settings

    m = _module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CONTROLDONE_ANTHROPIC_API_KEY", raising=False)
    reset_settings()
    try:
        assert m.main(argv) == 2
    finally:
        reset_settings()
    assert attendu in capsys.readouterr().err


def test_main_exige_la_confirmation_de_depense(monkeypatch, capsys):
    from controldone.config import reset_settings

    m = _module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fictif")
    reset_settings()
    try:
        assert m.main(["--corpus", "bench/corpus_g4"]) == 2
    finally:
        reset_settings()
    assert "--confirmer-depense" in capsys.readouterr().err
