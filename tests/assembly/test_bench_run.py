"""Exécution du banc (§19.2) sur un mini-corpus fictif, avec des doubles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from doubles import DecoupeurDouble, ExtracteurDouble, ecrire_pdf
from test_pipeline import PROFIL, fabrique

from controldone.bench_run import assigner_clients, executer_banc, fusionner_findings, lister_dossiers
from controldone.findings_io import lire_findings
from controldone.pipeline import Composants


@pytest.fixture
def corpus(tmp_path):
    c = tmp_path / "corpus"
    (c / "clients" / "CL99" / "grilles").mkdir(parents=True)
    (c / "clients" / "CL99" / "profil.json").write_text(json.dumps(PROFIL), encoding="utf-8")
    (c / "clients" / "CL99" / "grilles" / "g1.json").write_text(
        json.dumps(
            {
                "grille_id": "G1",
                "transitaire_id": "T9",
                "reference": "DEVIS-FICTIF-1",
                "postes": [
                    {
                        "code_poste": "DEDOUANEMENT",
                        "nature": "frais_dedouanement",
                        "mode": "forfait",
                        "prix": "45.00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    for did in ("BX0001", "BX0002"):
        d = c / "dev" / did
        ecrire_pdf(d / "docs" / "fc_invoice.pdf", ["COMMERCIAL INVOICE INV-10001"])
        ecrire_pdf(d / "docs" / "sous" / "dec_h1.pdf", ["DECLARATION 26FR0000000000AAA1"])
        ecrire_pdf(d / "docs" / "sous" / "ft_facture.pdf", ["FACTURE FT-500"])
        (d / "truth.json").write_text("{ne pas lire}", encoding="utf-8")
    return c


def _composants():
    return Composants(decoupeur=DecoupeurDouble(), extracteurs=[ExtracteurDouble(fabrique)])


@pytest.fixture
def interdit_truth(monkeypatch):
    lus = []
    orig_read_text, orig_read_bytes, orig_open = Path.read_text, Path.read_bytes, Path.open

    def garde(p):
        if Path(p).name == "truth.json":
            lus.append(str(p))
            raise AssertionError("truth.json ne doit jamais être lu par le système")

    monkeypatch.setattr(
        Path, "read_text", lambda self, *a, **k: (garde(self), orig_read_text(self, *a, **k))[1]
    )
    monkeypatch.setattr(
        Path, "read_bytes", lambda self, *a, **k: (garde(self), orig_read_bytes(self, *a, **k))[1]
    )
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: (garde(self), orig_open(self, *a, **k))[1])
    return lus


@pytest.mark.parametrize("workers", [1, 2])
def test_banc_ecrit_un_findings_par_dossier(corpus, tmp_path, workers, interdit_truth):
    out = tmp_path / "out" / "run1"
    bilan = executer_banc(corpus, "dev", out, workers=workers, composants=_composants())
    assert bilan["erreurs"] == {}
    assert bilan["clients"] == {"BX0001": "CL99", "BX0002": "CL99"}
    for did in ("BX0001", "BX0002"):
        f = lire_findings(out / did / "findings.json")
        assert f.dossier_id == did
        assert sorted(d.file for d in f.documents) == [
            "docs/fc_invoice.pdf",
            "docs/sous/dec_h1.pdf",
            "docs/sous/ft_facture.pdf",
        ]
        assert any(c.controle_id == "B1" for c in f.constats)
    assert (out / "run.json").exists()
    assert interdit_truth == []


def test_limit(corpus):
    assert [p.name for p in lister_dossiers(corpus, "dev", limit=1)] == ["BX0001"]


def test_assignation_client_par_texte(corpus):
    autre = dict(
        PROFIL, client_id="CL98", entites=[{"raison_sociale": "AUTRE FICTIF", "tva": "FR00000000000"}]
    )
    (corpus / "clients" / "CL98").mkdir()
    (corpus / "clients" / "CL98" / "profil.json").write_text(json.dumps(autre), encoding="utf-8")
    from controldone.bench_run import _clients

    clients = _clients(corpus)
    # le texte des PDF ne cite aucune TVA : pas d'attribution (aucun indice), sans erreur
    res = assigner_clients(lister_dossiers(corpus, "dev"), corpus, clients)
    assert [r.client_id for r in res] == [None, None]
    (corpus / "manifest.json").write_text(
        json.dumps({"dossiers": [{"dossier_id": "BX0001", "client_id": "CL98"}]})
    )
    res = assigner_clients(lister_dossiers(corpus, "dev"), corpus, clients)
    assert res[0].client_id == "CL98"


def test_fusion_findings_statut_prioritaire(corpus, tmp_path):
    from controldone.pipeline import OptionsPipeline, traiter_lot

    r = traiter_lot(
        corpus / "dev" / "BX0001" / "docs",
        PROFIL,
        [],
        options=OptionsPipeline(seed=1),
        composants=_composants(),
    )[0].findings
    vide = r.model_copy(update={"constats": [], "statut_global": "conforme", "documents": r.documents[:1]})
    f = fusionner_findings([vide, r], "BX0001")
    assert f.statut_global == r.statut_global and len(f.documents) == len(r.documents)
    assert len(f.constats) == len(r.constats)
