import json

import pytest

from controldone.controls.framework import run_controls
from controldone.findings_io import (
    SCHEMA_FINDINGS,
    construire_findings,
    ecrire_findings,
    findings_json,
    lire_findings,
    statut_global_depuis_resultats,
)
from controldone.guardrails import AVERTISSEMENT
from controldone.model import (
    ErreurSchema,
    Execution,
    Fichier,
    Outcome,
    RaisonCode,
    StatutGlobal,
    StatutValidation,
)
from controldone.testing import contexte, declaration, taxation


def _run(montant="418.20"):
    d = declaration(id="doc_dec", taxations=[taxation("doc_dec", article="3", base="2091.00", taux="2.5",
                                                     montant=montant)])
    ctx = contexte([d])
    rs = run_controls(ctx, controles=["B1"])
    ex = Execution.nouvelle(id="exe_1", empreinte_tolerances=ctx.empreinte_tolerances, duree_s=1.5)
    fic = Fichier(id="fic_test", nom_original="envoi.pdf", chemin_relatif="docs/expedition_77/envoi.pdf",
                  sha256="0" * 64, taille=10, type_mime="application/pdf")
    return ctx, d, rs, ex, fic


def test_annexe_c(tmp_path):
    ctx, d, rs, ex, fic = _run()
    f = construire_findings(ctx.dossier, [d], rs, ex, fichiers={fic.id: fic}, dossier_id="BX0042")
    data = f.vers_dict()
    assert data["schema"] == SCHEMA_FINDINGS == "controldone.findings/1.0.0"
    assert data["dossier_id"] == "BX0042" and data["dossier_version"] == 1
    assert data["execution"]["execution_id"] == "exe_1" and data["execution"]["cout_ia_eur"] == "0.00"
    assert data["statut_global"] == "ecart_certain"
    assert data["documents"][0] == {
        "document_id": "doc_dec", "type": "declaration", "sous_type": None,
        "file": "docs/expedition_77/envoi.pdf", "pages": [1], "confiance_classement": 1.0,
    }
    assert data["liens"][0]["role"] == "declaration" and data["liens"][0]["force"] == "forte"
    assert data["valeurs"]["doc_dec"]["mrn"]["valeur"] == "26FR00000000000001"
    assert data["valeurs"]["doc_dec"]["mrn"]["methode"] == "texte_natif"
    r = data["resultats"][0]
    assert r["controle_id"] == "B1" and r["outcome"] == "ecart_certain" and r["tolerance"] == "0.01"
    c = data["constats"][0]
    assert c["finding_id"].startswith("f_") and c["niveau"] == "ecart_certain"
    assert c["montant_en_jeu"] == "365.93" and c["nature_montant"] == "arithmetique_declaration"
    assert c["preuves"][2] == {"document_id": "doc_dec", "page": 1, "valeur_brute": "418.20", "role": "valeur_b",
                               "calcul": None}
    assert c["statut_validation"] == "propose"
    assert data["avertissement"] == AVERTISSEMENT
    chemin = ecrire_findings(f, tmp_path / "BX0042" / "findings.json")
    relu = lire_findings(chemin)
    assert relu.vers_dict() == data
    assert findings_json(relu) == chemin.read_text(encoding="utf-8")


def test_montants_au_format_du_banc():
    ctx, d, rs, ex, _fic = _run()
    data = construire_findings(ctx.dossier, [d], rs, ex).vers_dict()
    import re

    assert re.fullmatch(r"^-?[0-9]+\.[0-9]{2}$", data["constats"][0]["montant_en_jeu"])


def test_lecture_versions():
    ctx, d, rs, ex, _fic = _run()
    data = construire_findings(ctx.dossier, [d], rs, ex).vers_dict()
    mineure = dict(data, schema="controldone.findings/1.3.0", champ_futur={"x": 1})
    assert lire_findings(mineure).dossier_id == data["dossier_id"]
    assert lire_findings(json.dumps(mineure)).dossier_id == data["dossier_id"]
    with pytest.raises(ErreurSchema):
        lire_findings(dict(data, schema="controldone.findings/2.0.0"))
    with pytest.raises(ErreurSchema):
        lire_findings(dict(data, schema="controldone.rapport/1.0.0"))


def test_statut_global_18_2():
    ctx, _d, rs, _ex, _fic = _run()
    assert statut_global_depuis_resultats(rs) is StatutGlobal.ecart_certain
    assert statut_global_depuis_resultats(rs, valides_seulement=True) is StatutGlobal.a_verifier
    rs_valide = [r.model_copy(update={"constat": r.constat.model_copy(
        update={"statut_validation": StatutValidation.valide})}) for r in rs]
    assert statut_global_depuis_resultats(rs_valide, valides_seulement=True) is StatutGlobal.ecart_certain
    _, _, conformes, _, _ = _run("52.28")
    assert statut_global_depuis_resultats(conformes) is StatutGlobal.conforme
    nv = ctx.non_verifiable("C1", RaisonCode.valeur_absente)
    assert statut_global_depuis_resultats([*conformes, nv]) is StatutGlobal.a_verifier
    p1 = ctx.constat("P1", ctx.classify("P1", ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=[]),
                     libelle="Aucune déclaration dans le dossier.")
    assert p1.outcome is Outcome.a_verifier
    assert statut_global_depuis_resultats([*rs, p1]) is StatutGlobal.document_manquant
    p5 = ctx.non_applicable("P5", RaisonCode.dossier_non_concerne, details={"non_concerne": True})
    assert statut_global_depuis_resultats([p5, p1]) is StatutGlobal.non_concerne


def test_sortie_reproductible_octet_pour_octet():
    sorties = []
    for _ in range(2):
        ctx, d, rs, ex, fic = _run()
        sorties.append(findings_json(construire_findings(ctx.dossier, [d], rs, ex, fichiers={fic.id: fic})))
    assert sorties[0] == sorties[1]
