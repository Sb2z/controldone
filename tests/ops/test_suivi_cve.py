"""scripts/suivi_cve.py : nouvelles, disparues et devenues corrigeables entre deux audits Trivy, sans réseau
(D-4704). Audits synthétiques (paquets et identifiants FICTIFS)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "suivi_cve.py"


@pytest.fixture(scope="module")
def suivi():
    spec = importlib.util.spec_from_file_location("suivi_cve", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["suivi_cve"] = module  # (dataclasses relit le module de la classe)
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("suivi_cve", None)


def _trivy(chemin: Path, vulns: list[tuple[str, str, str, str | None]], cree: str = "2026-09-06") -> Path:
    chemin.write_text(
        json.dumps(
            {
                "CreatedAt": f"{cree}T10:00:00Z",
                "Metadata": {"OS": {"Family": "debian", "Name": "13.7"}},
                "Results": [
                    {
                        "Target": "image FICTIVE",
                        "Vulnerabilities": [
                            {
                                "PkgName": p,
                                "VulnerabilityID": i,
                                "Severity": g,
                                "InstalledVersion": "1.0",
                                **({"FixedVersion": f} if f else {}),
                            }
                            for p, i, g, f in vulns
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return chemin


def test_comparaison_et_archivage(suivi, tmp_path, capsys):
    hist, sortie = tmp_path / "historique", tmp_path / "suivi.md"
    avant = _trivy(
        tmp_path / "avant.json",
        [
            ("libfictive", "CVE-2026-0001", "HIGH", None),
            ("libfictive", "CVE-2026-0002", "CRITICAL", None),
            ("libdisparue", "CVE-2026-0003", "HIGH", None),
            ("libbasse", "CVE-2026-0009", "LOW", None),
        ],
    )
    args = ["--historique", str(hist), "--sortie", str(sortie)]
    assert suivi.main(["--courant", str(avant), *args]) == 0  # première exécution : référence
    assert "première exécution" in sortie.read_text(encoding="utf-8")
    assert len(list(hist.glob("image-trivy-20260906-*.json"))) == 1
    assert suivi.main(["--courant", str(avant), *args]) == 0  # identique : pas archivé deux fois
    assert len(list(hist.iterdir())) == 1

    apres = _trivy(
        tmp_path / "apres.json",
        [
            ("libfictive", "CVE-2026-0001", "HIGH", None),
            ("libfictive", "CVE-2026-0002", "CRITICAL", "1.1"),
            ("libnouvelle", "CVE-2026-0004", "HIGH", None),
            ("libbasse", "CVE-2026-0010", "MEDIUM", None),
        ],
        cree="2026-10-06",
    )
    capsys.readouterr()
    assert suivi.main(["--courant", str(apres), *args]) == 1
    texte = sortie.read_text(encoding="utf-8")
    assert texte == capsys.readouterr().out.split("audit archivé")[0]
    assert "## Nouvelles (1)\n\n- libnouvelle 1.0 : CVE-2026-0004 (HIGH), sans correctif publié" in texte
    assert "## Disparues (corrigées ou retirées) (1)\n\n- libdisparue 1.0 : CVE-2026-0003" in texte
    assert (
        "reconstruire l'image (make audit-image) (1)\n\n- libfictive 1.0 : CVE-2026-0002 (CRITICAL)" in texte
    )
    assert "inchangées depuis le précédent : 2" in texte and "MEDIUM" not in texte and "LOW" not in texte
    assert len(list(hist.iterdir())) == 2
    # le mois suivant sans changement : le précédent est le dernier audit différent, rien à traiter
    assert suivi.main(["--courant", str(apres), *args, "--precedent", str(apres)]) == 0


def test_lecture_de_image_md(suivi, tmp_path):
    md = tmp_path / "image.md"
    md.write_text(
        "# Audit\n\n## Graves et corrigeables (bloquant : reconstruire l'image)\n\n"
        "- libfictive 2.0 : CVE-2026-0005 (CRITICAL), corrigé en 2.1\n\n"
        "## Graves sans correctif publié (suivi)\n\n- libautre 1:3.0-1 : CVE-2026-0006 (HIGH)\n",
        encoding="utf-8",
    )
    vulns = suivi.lire_audit(md)
    assert vulns[("libfictive", "CVE-2026-0005")].corrige_en == "2.1"
    assert vulns[("libautre", "CVE-2026-0006")].corrige_en is None and len(vulns) == 2


def test_audit_absent(suivi, tmp_path):
    assert suivi.main(["--courant", str(tmp_path / "absent.json"), "--historique", str(tmp_path / "h")]) == 2
