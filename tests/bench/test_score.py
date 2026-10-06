"""Tests du correcteur du banc sur des cas jouets construits à la main (SPEC §19.4, §19.7)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from bench.score.__main__ import main
from bench.score.core import scorer, wilson_borne_basse
from bench.score.formulations import charger_formulations

AVERTISSEMENT = (
    "Ce document est un contrôle technique de cohérence entre documents et de calcul. Il ne "
    "constitue ni un conseil juridique, fiscal ou douanier, ni un avis sur la conformité des "
    "opérations. Les montants indiqués sont des écarts constatés entre documents ; ils ne "
    "préjugent pas des sommes légalement dues."
)

FORMULATIONS = charger_formulations(Path("/nonexistent/formulations.yaml"))


# ---------------------------------------------------------------------------
# Fabriques
# ---------------------------------------------------------------------------


def doc_v(doc_id, type_, file, pages):
    return {
        "doc_id": doc_id,
        "type": type_,
        "sous_type": None,
        "format": "pdf_natif",
        "degradation": "d0",
        "file": file,
        "pages": pages,
    }


DOCS_STD = [
    doc_v("fc1", "facture_commerciale", "docs/envoi.pdf", [1, 2]),
    doc_v("dec1", "declaration", "docs/envoi.pdf", [3, 4]),
    doc_v("ft1", "facture_transitaire", "docs/ft.pdf", [1]),
]


def erreur(eid, ctrl, accepted, level, montant, nature, documents, **kw):
    e = {
        "error_id": eid,
        "control_id": ctrl,
        "accepted_control_ids": accepted,
        "expected_level": level,
        "expected_amount_eur": montant,
        "amount_nature": nature,
        "composante": None,
        "documents": documents,
        "fields": [],
        "injection": "x",
    }
    e.update(kw)
    return e


def truth(did, errors=(), traps=(), documents=None, truth_values=None, links=None):
    return {
        "schema": "controldone.bench.truth/1.0.0",
        "dossier_id": did,
        "split": "holdout",
        "client_id": "CL01",
        "generator_version": "t",
        "seed": 1,
        "degradation": "d0",
        "files": [],
        "documents": documents if documents is not None else DOCS_STD,
        "truth_values": truth_values or {},
        "expected_links": links or [],
        "injected_errors": list(errors),
        "traps": list(traps),
        "expected_outcome": "conforme",
        "expected_totals": {"recouvrable_certain_eur": "0.00", "recouvrable_a_verifier_eur": "0.00"},
    }


DOCS_PROD = [
    {
        "document_id": "p_fc",
        "type": "facture_commerciale",
        "sous_type": None,
        "file": "docs/envoi.pdf",
        "pages": [1, 2],
        "confiance_classement": 0.9,
    },
    {
        "document_id": "p_dec",
        "type": "declaration",
        "sous_type": None,
        "file": "docs/envoi.pdf",
        "pages": [3, 4],
        "confiance_classement": 0.9,
    },
    {
        "document_id": "p_ft",
        "type": "facture_transitaire",
        "sous_type": None,
        "file": "docs/ft.pdf",
        "pages": [1],
        "confiance_classement": 0.9,
    },
]


def constat(fid, ctrl, niveau, montant, docs, **kw):
    c = {
        "finding_id": fid,
        "controle_id": ctrl,
        "niveau": niveau,
        "raisons": [],
        "montant_en_jeu": montant,
        "nature_montant": "recouvrable",
        "composante": None,
        "renvoi": False,
        "documents_concernes": docs,
        "preuves": [],
        "libelle": "La facture du transitaire indique 10,00 EUR ; la déclaration indique 8,00 EUR.",
        "prochaine_action": "Demander une explication au transitaire.",
        "statut_validation": "propose",
    }
    c.update(kw)
    return c


def findings(did, constats=(), documents=None, cout="0.10", duree=10.0, **kw):
    f = {
        "schema": "controldone.findings/1.0.0",
        "dossier_id": did,
        "dossier_version": 1,
        "execution": {
            "execution_id": "e",
            "version_moteur": "0.1",
            "version_regles": "0.1",
            "empreinte_tolerances": "x",
            "modele_llm": None,
            "cout_ia_eur": cout,
            "duree_s": duree,
        },
        "statut_global": "conforme",
        "documents": documents if documents is not None else DOCS_PROD,
        "liens": [],
        "resultats": [],
        "constats": list(constats),
        "avertissement": AVERTISSEMENT,
    }
    f.update(kw)
    return f


class Banc:
    def __init__(self, tmp: Path):
        self.corpus = tmp / "corpus"
        self.run = tmp / "out" / "run1"
        self.run.mkdir(parents=True)

    def ajouter(self, t: dict, f: dict | None):
        d = self.corpus / "holdout" / t["dossier_id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "truth.json").write_text(json.dumps(t), encoding="utf-8")
        if f is not None:
            o = self.run / t["dossier_id"]
            o.mkdir(parents=True, exist_ok=True)
            (o / "findings.json").write_text(json.dumps(f), encoding="utf-8")

    def scorer(self):
        return scorer(self.corpus, "holdout", self.run, FORMULATIONS)


@pytest.fixture
def banc(tmp_path):
    return Banc(tmp_path)


def classes(m):
    return {(d["finding_id"] or d["error_id"]): d["classe"] for d in m["details"]}


E_C3 = erreur("BX0001-E1", "C3", ["C3", "C5"], "ecart_certain", "2508.00", "recouvrable", ["ft1", "dec1"])


# ---------------------------------------------------------------------------
# Appariement et classes
# ---------------------------------------------------------------------------


def test_appariement_parfait(banc):
    banc.ajouter(
        truth("BX0001", [E_C3]),
        findings("BX0001", [constat("f1", "C3", "ecart_certain", "2508.00", ["p_ft", "p_dec"])]),
    )
    m = banc.scorer()
    g = m["global"]
    assert classes(m) == {"f1": "vp_certain"}
    assert (g["vp_certain"], g["fp_certain"], g["fn"]) == (1, 0, 0)
    assert g["precision_certain"] == 1.0 and g["rappel"] == 1.0 and g["rappel_certain"] == 1.0
    assert g["exactitude_montant"] == 1.0 and g["precision_detection"] == 1.0
    assert m["par_controle"]["C3"]["vp_certain"] == 1
    assert m["gate"] == {"passe": True, "motifs": []}
    assert m["schema"] == "controldone.bench.metrics/1.0.0" and m["run_id"] == "run1"


def test_montant_faux_donne_fp_certain_mais_detection(banc):
    banc.ajouter(
        truth("BX0001", [E_C3]),
        findings("BX0001", [constat("f1", "C3", "ecart_certain", "2400.00", ["p_ft"])]),
    )
    m = banc.scorer()
    d = m["details"][0]
    assert d["classe"] == "fp_certain" and d["motif"] == "montant_incorrect"
    assert d["error_id"] == "BX0001-E1"
    g = m["global"]
    assert g["fn"] == 0 and g["vp_detection"] == 1 and g["fp_certain_montant"] == 1
    assert g["exactitude_montant"] == 0.0 and g["precision_certain"] == 0.0


def test_tolerance_montant_max_5_centimes_ou_1_pct(banc):
    e_petit = erreur("BX0001-E1", "D3", ["D3"], "ecart_certain", "3.00", "recouvrable", ["ft1"])
    e_grand = erreur("BX0001-E2", "D1", ["D1"], "ecart_certain", "1000.00", "recouvrable", ["ft1"])
    banc.ajouter(
        truth("BX0001", [e_petit, e_grand]),
        findings(
            "BX0001",
            [
                constat("f1", "D3", "ecart_certain", "3.05", ["p_ft"]),  # 0,05 ≤ max(0,05 ; 0,03)
                constat("f2", "D1", "ecart_certain", "1010.01", ["p_ft"]),  # 10,01 > 10,00
            ],
        ),
    )
    assert classes(banc.scorer()) == {"f1": "vp_certain", "f2": "fp_certain"}


def test_constat_certain_non_apparie_est_fp(banc):
    banc.ajouter(
        truth("BX0001", [E_C3]),
        findings(
            "BX0001",
            [
                constat("f1", "C3", "ecart_certain", "2508.00", ["p_ft"]),
                constat("f2", "D3", "ecart_certain", "50.00", ["p_ft"]),  # contrôle non accepté
                constat("f3", "C4", "ecart_certain", "2508.00", ["p_ft"]),  # C4 ∉ accepted
                constat("f4", "C3", "a_verifier", "12.00", ["p_ft"]),  # erreur déjà prise
            ],
        ),
    )
    m = banc.scorer()
    assert classes(m) == {"f1": "vp_certain", "f2": "fp_certain", "f3": "fp_certain", "f4": "fp_a_verifier"}
    g = m["global"]
    assert g["fp_certain_non_apparie"] == 2 and g["fp_a_verifier"] == 1
    assert g["bruit_a_verifier_par_dossier"] == 1.0
    assert m["par_controle"]["D3"]["fp_certain"] == 1  # FP compté sur le contrôle du constat
    assert m["par_controle"]["C3"]["vp_certain"] == 1
    assert math.isclose(g["precision_certain"], round(1 / 3, 4))


def test_glouton_trie_par_ecart_de_montant_puis_ids(banc):
    banc.ajouter(
        truth("BX0001", [E_C3]),
        findings(
            "BX0001",
            [
                constat("f_a", "C5", "ecart_certain", "2000.00", ["p_ft"]),
                constat("f_b", "C3", "ecart_certain", None, ["p_ft"]),
                constat("f_c", "C3", "ecart_certain", "2508.01", ["p_ft"]),
            ],
        ),
    )
    m = banc.scorer()
    assert classes(m)["f_c"] == "vp_certain"
    assert classes(m)["f_a"] == "fp_certain" and classes(m)["f_b"] == "fp_certain"


def test_departage_controle_principal_puis_niveau_certain(banc):
    # Holdout 1 : à écart de montant égal (deux montants null), le constat du contrôle
    # principal de l'erreur l'emporte sur un constat d'un contrôle accepté qui trie avant.
    e = erreur("BX0001-E1", "B4", ["B4", "A10"], "ecart_certain", None, None, ["dec1"])
    banc.ajouter(
        truth("BX0001", [e]),
        findings(
            "BX0001",
            [
                constat("f_a", "A10", "a_verifier", None, ["p_dec"]),
                constat("f_b", "B4", "ecart_certain", None, ["p_dec"]),
            ],
        ),
    )
    m = banc.scorer()
    assert classes(m)["f_b"] == "vp_certain"
    assert classes(m)["f_a"] == "fp_a_verifier"
    assert m["global"]["fp_certain"] == 0


def test_departage_niveau_certain_a_controle_egal(banc):
    e = erreur("BX0001-E1", "B4", ["B4", "A10"], "ecart_certain", None, None, ["dec1"])
    banc.ajouter(
        truth("BX0001", [e]),
        findings(
            "BX0001",
            [
                constat("f_a", "B4", "a_verifier", None, ["p_dec"]),
                constat("f_b", "B4", "ecart_certain", None, ["p_dec"]),
            ],
        ),
    )
    m = banc.scorer()
    assert classes(m)["f_b"] == "vp_certain"


def test_a_verifier_apparie_a_erreur_certaine_est_sous_classement(banc):
    banc.ajouter(
        truth("BX0001", [E_C3]), findings("BX0001", [constat("f1", "C3", "a_verifier", "2508.00", ["p_dec"])])
    )
    m = banc.scorer()
    g = m["global"]
    assert classes(m) == {"f1": "vp_a_verifier"}
    assert g["sous_classement"] == 1 and g["taux_sous_classement"] == 1.0
    assert g["rappel"] == 1.0 and g["rappel_certain"] == 0.0
    assert g["vp_certain"] == 0 and g["fp_certain"] == 0 and g["precision_certain"] is None
    assert m["details"][0]["sous_classement"] is True


def test_surclassement(banc):
    e = erreur("BX0001-E1", "A4", ["A4", "A5"], "a_verifier", "90.00", "ecart_documentaire", ["fc1", "dec1"])
    banc.ajouter(
        truth("BX0001", [e]), findings("BX0001", [constat("f1", "A5", "ecart_certain", "90.00", ["p_fc"])])
    )
    g = banc.scorer()["global"]
    assert g["vp_certain"] == 1 and g["surclassement"] == 1 and g["taux_surclassement"] == 1.0
    assert g["precision_certain"] == 1.0


def test_montant_null_attendu(banc):
    e1 = erreur("BX0001-E1", "A1", ["A1"], "ecart_certain", None, "aucun", ["dec1"])
    e2 = erreur("BX0001-E2", "A3", ["A3", "A6"], "ecart_certain", None, "aucun", ["dec1"])
    banc.ajouter(
        truth("BX0001", [e1, e2]),
        findings(
            "BX0001",
            [
                constat("f1", "A1", "ecart_certain", None, ["p_dec"]),
                constat("f2", "A3", "ecart_certain", "12.00", ["p_dec"]),
            ],
        ),
    )
    m = banc.scorer()
    assert classes(m) == {"f1": "vp_certain", "f2": "fp_certain"}
    assert m["global"]["exactitude_montant"] is None  # aucun montant attendu


def test_doublon_composantes(banc):
    e1 = erreur("BX0001-E1", "C1", ["C1", "C5"], "ecart_certain", "500.00", "recouvrable", ["ft1", "dec1"])
    e2 = erreur(
        "BX0001-E2",
        "C5",
        ["C5", "C1", "C2", "C3", "C4"],
        "ecart_certain",
        "500.00",
        "recouvrable",
        ["ft1", "dec1"],
    )
    banc.ajouter(
        truth("BX0001", [e1, e2]),
        findings(
            "BX0001",
            [
                constat("f1", "C1", "ecart_certain", "500.00", ["p_ft"]),
                constat("f2", "C5", "ecart_certain", None, ["p_ft"], raisons=["doublon_composantes"]),
            ],
        ),
    )
    m = banc.scorer()
    assert classes(m) == {"f1": "vp_certain", "f2": "vp_certain"}
    # Sans autre constat apparié portant un montant, le null est incorrect.
    banc2 = Banc(banc.corpus.parent / "b2")
    banc2.ajouter(
        truth("BX0001", [e2]),
        findings(
            "BX0001", [constat("f2", "C5", "ecart_certain", None, ["p_ft"], raisons=["doublon_composantes"])]
        ),
    )
    assert classes(banc2.scorer()) == {"f2": "fp_certain"}


def test_doublon_composantes_redondant_neutre(banc):
    e1 = erreur("BX0001-E1", "C1", ["C1", "C5"], "ecart_certain", "500.00", "recouvrable", ["ft1"])
    banc.ajouter(
        truth("BX0001", [e1]),
        findings(
            "BX0001",
            [
                constat("f1", "C1", "ecart_certain", "500.00", ["p_ft"]),
                constat("f2", "C5", "ecart_certain", None, ["p_ft"], raisons=["doublon_composantes"]),
            ],
        ),
    )
    m = banc.scorer()
    assert classes(m) == {"f1": "vp_certain", "f2": "redondant_doublon_composantes"}
    assert m["global"]["fp_certain"] == 0 and m["global"]["neutres"] == 1


# ---------------------------------------------------------------------------
# Pièges
# ---------------------------------------------------------------------------


def test_violation_de_piege(banc):
    traps = [
        {"trap_id": "BX0001-T1", "control_id": "C1", "max_level": "conforme", "documents": ["ft1", "dec1"]},
        {"trap_id": "BX0001-T2", "control_id": "A4", "max_level": "a_verifier", "documents": ["fc1", "dec1"]},
    ]
    banc.ajouter(
        truth("BX0001", [], traps),
        findings(
            "BX0001",
            [
                constat("f1", "C5", "ecart_certain", "0.03", ["p_ft"]),  # C5 ∈ équivalents(C1)
                constat("f2", "C1", "a_verifier", "0.03", ["p_dec"]),  # au-delà de conforme
                constat("f3", "A5", "a_verifier", "4.00", ["p_fc"]),  # toléré (max a_verifier)
                constat("f4", "A4", "ecart_certain", "4.00", ["p_fc"]),  # au-delà de a_verifier
            ],
        ),
    )
    m = banc.scorer()
    assert classes(m) == {"f1": "fp_certain", "f2": "fp_a_verifier", "f3": "piege_tolere", "f4": "fp_certain"}
    det = {d["finding_id"]: d for d in m["details"]}
    assert det["f1"]["trap_id"] == "BX0001-T1" and det["f1"]["motif"] == "piege"
    assert det["f4"]["trap_id"] == "BX0001-T2"
    g = m["global"]
    assert g["fp_certain_piege"] == 2 and g["violations_pieges"] == 3
    assert g["fp_a_verifier"] == 1  # le constat toléré n'est pas du bruit


def test_piege_sans_chevauchement_de_document_ne_s_applique_pas(banc):
    traps = [{"trap_id": "T1", "control_id": "C1", "max_level": "conforme", "documents": ["ft1"]}]
    banc.ajouter(
        truth("BX0001", [], traps), findings("BX0001", [constat("f1", "C1", "a_verifier", "1.00", ["p_fc"])])
    )
    m = banc.scorer()
    assert m["details"][0]["motif"] == "non_apparie" and m["details"][0]["trap_id"] is None


def test_constat_apparie_a_une_erreur_ignore_le_piege(banc):
    traps = [{"trap_id": "T1", "control_id": "C3", "max_level": "conforme", "documents": ["ft1"]}]
    banc.ajouter(
        truth("BX0001", [E_C3], traps),
        findings("BX0001", [constat("f1", "C3", "ecart_certain", "2508.00", ["p_ft"])]),
    )
    assert classes(banc.scorer()) == {"f1": "vp_certain"}


# ---------------------------------------------------------------------------
# Contrôles F entre dossiers
# ---------------------------------------------------------------------------


def _f3():
    return erreur(
        "BX0001-E1",
        "F3",
        ["F3", "C5"],
        "ecart_certain",
        "300.00",
        "recouvrable",
        ["ft1"],
        other_dossiers=["BX0002"],
    )


def test_controle_f_apparie_depuis_autre_dossier(banc):
    banc.ajouter(truth("BX0001", [_f3()]), findings("BX0001", []))
    banc.ajouter(
        truth("BX0002"), findings("BX0002", [constat("g1", "F3", "ecart_certain", "300.00", ["p_ft"])])
    )
    m = banc.scorer()
    assert classes(m) == {"g1": "vp_certain"}
    assert m["details"][0]["error_id"] == "BX0001-E1"
    assert m["global"]["rappel"] == 1.0


def test_controle_f_occurrence_miroir_neutre(banc):
    banc.ajouter(
        truth("BX0001", [_f3()]),
        findings("BX0001", [constat("f1", "F3", "ecart_certain", "300.00", ["p_ft"])]),
    )
    banc.ajouter(
        truth("BX0002"), findings("BX0002", [constat("g1", "F3", "ecart_certain", "300.00", ["p_ft"])])
    )
    m = banc.scorer()
    assert classes(m) == {"f1": "vp_certain", "g1": "miroir_inter_dossiers"}
    assert m["global"]["fp_certain"] == 0


def test_controle_non_f_ne_traverse_pas_les_dossiers(banc):
    e = erreur(
        "BX0001-E1", "D5", ["D5"], "ecart_certain", "80.00", "recouvrable", ["ft1"], other_dossiers=["BX0002"]
    )
    banc.ajouter(truth("BX0001", [e]), findings("BX0001", []))
    banc.ajouter(
        truth("BX0002"), findings("BX0002", [constat("g1", "D5", "ecart_certain", "80.00", ["p_ft"])])
    )
    m = banc.scorer()
    assert classes(m) == {"g1": "fp_certain", "BX0001-E1": "fn"}


def test_controle_f_doc_qualifie_et_doc_d_un_autre_dossier(banc):
    e = erreur(
        "BX0001-E1",
        "F5",
        ["F5", "A4"],
        "a_verifier",
        None,
        "ecart_documentaire",
        ["fc1", "BX0002/fc1"],
        other_dossiers=["BX0002"],
    )
    banc.ajouter(
        truth("BX0001", [e]),
        findings(
            "BX0001",
            [
                # le constat cite un document produit du dossier BX0002 (identifiant global)
                constat("f1", "F5", "a_verifier", None, ["q_fc"])
            ],
        ),
    )
    docs2 = [dict(DOCS_PROD[0], document_id="q_fc")]
    banc.ajouter(truth("BX0002"), findings("BX0002", [], documents=docs2))
    assert classes(banc.scorer()) == {"f1": "vp_a_verifier"}


# ---------------------------------------------------------------------------
# Correspondance des documents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fichier,pages,attendu",
    [
        ("docs/envoi.pdf", [3, 4], "vp_certain"),
        ("docs/envoi.pdf", [4, 5, 6], "vp_certain"),  # 1 page sur 2 = 50 %
        ("envoi.pdf", [3], "vp_certain"),  # chemin relatif à docs/
        ("docs/envoi.pdf", [5, 6], "fp_certain"),  # aucune page commune
        ("docs/autre.pdf", [3, 4], "fp_certain"),  # autre fichier
    ],
)
def test_regle_de_chevauchement_des_pages(banc, fichier, pages, attendu):
    e = erreur(
        "BX0001-E1", "B1", ["B1", "B2"], "ecart_certain", "52.28", "arithmetique_declaration", ["dec1"]
    )
    docs = [{"document_id": "p_x", "type": "declaration", "file": fichier, "pages": pages}]
    banc.ajouter(
        truth("BX0001", [e]),
        findings("BX0001", [constat("f1", "B1", "ecart_certain", "52.28", ["p_x"])], documents=docs),
    )
    assert classes(banc.scorer())["f1"] == attendu


def test_moins_de_50_pourcent_des_pages(banc):
    docs_v = [doc_v("dec1", "declaration", "docs/d.pdf", [1, 2, 3, 4, 5])]
    e = erreur(
        "BX0001-E1", "B2", ["B2", "B1"], "ecart_certain", "10.00", "arithmetique_declaration", ["dec1"]
    )
    banc.ajouter(
        truth("BX0001", [e], documents=docs_v),
        findings(
            "BX0001",
            [
                constat("f1", "B2", "ecart_certain", "10.00", ["p1"]),
                constat("f2", "B2", "ecart_certain", "10.00", ["p2"]),
            ],
            documents=[
                {"document_id": "p1", "file": "docs/d.pdf", "pages": [1, 2]},
                {"document_id": "p2", "file": "docs/d.pdf", "pages": [3, 4, 5]},
            ],
        ),
    )
    assert classes(banc.scorer()) == {"f1": "fp_certain", "f2": "vp_certain"}


# ---------------------------------------------------------------------------
# Fichiers manquants, extraction, regroupement, coûts
# ---------------------------------------------------------------------------


def test_findings_absent_compte_fn_et_est_signale(banc):
    banc.ajouter(truth("BX0001", [E_C3]), None)
    banc.ajouter(truth("BX0002"), findings("BX0002", []))
    d = banc.corpus / "holdout" / "BX0003"
    banc.ajouter(
        truth("BX0003", [erreur("BX0003-E1", "D1", ["D1"], "ecart_certain", "1.00", "recouvrable", ["ft1"])]),
        None,
    )
    (banc.run / "BX0003").mkdir()
    (banc.run / "BX0003" / "findings.json").write_text("{pas du json", encoding="utf-8")
    m = banc.scorer()
    assert m["dossiers"]["findings_absents"] == ["BX0001"]
    assert m["dossiers"]["findings_illisibles"] == ["BX0003"]
    assert m["global"]["fn"] == 2 and m["global"]["rappel"] == 0.0
    assert classes(m) == {"BX0001-E1": "fn", "BX0003-E1": "fn"}
    assert d.exists()


def test_extraction_par_champ(banc):
    tv = {
        "fc1": {
            "numero": "INV-2026-0815",
            "date": "2026-08-14",
            "devise": "USD",
            "total_facture": "12540.00",
            "total_imprime": True,
            "acheteur.tva": "FR32000123459",
            "incoterm": "FOB",
            "lignes": [
                {"code_marchandise_imprime": "8471.30", "quantite": "10", "montant_ligne": "12540.00"}
            ],
        }
    }
    valeurs = {
        "p_fc": {
            "numero": {"valeur": "INV 2026-0815"},
            "date": {"valeur": "2026-08-14"},
            "devise": {"valeur": "EUR"},  # faux
            "total_facture": {"valeur": "12540.004"},  # à 0,005 près
            "total_imprime": {"valeur": True},
            "acheteur": {"tva": {"valeur": "FR 32 000123459"}},  # imbriqué
            # incoterm absent -> faux
            "lignes": [
                {
                    "code_marchandise_imprime": {"valeur": "847130"},
                    "quantite": {"valeur": "10.000"},
                    "montant_ligne": {"valeur": "12540.01"},
                }
            ],  # faux (> 0,005)
        }
    }
    banc.ajouter(truth("BX0001", truth_values=tv), findings("BX0001", [], valeurs=valeurs))
    ex = banc.scorer()["extraction_par_champ"]
    c = {k: v["corrects"] for k, v in ex["champs"].items()}
    assert c == {
        "facture_commerciale.acheteur.tva": 1,
        "facture_commerciale.date": 1,
        "facture_commerciale.devise": 0,
        "facture_commerciale.incoterm": 0,
        "facture_commerciale.numero": 1,
        "facture_commerciale.total_facture": 1,
        "facture_commerciale.total_imprime": 1,
        "facture_commerciale.lignes[].code_marchandise_imprime": 1,
        "facture_commerciale.lignes[].quantite": 1,
        "facture_commerciale.lignes[].montant_ligne": 0,
    }
    assert ex["n_dossiers_evalues"] == 1 and ex["global"]["n"] == 10


def test_extraction_non_mesuree_sans_valeurs(banc):
    banc.ajouter(truth("BX0001", truth_values={"fc1": {"numero": "X"}}), findings("BX0001", []))
    assert banc.scorer()["extraction_par_champ"]["n_dossiers_evalues"] == 0


def test_regroupement_f1(banc):
    links = [
        {"from": "fc1", "to": "dec1", "role": "declaration"},
        {"from": "ft1", "to": "dec1", "role": "facture_transitaire"},
    ]
    liens = [
        {"from": "p_fc", "to": "p_dec", "role": "declaration"},
        {"from": "p_fc", "to": "p_ft", "role": "facture_transitaire"},
    ]
    banc.ajouter(truth("BX0001", links=links), findings("BX0001", [], liens=liens))
    r = banc.scorer()["regroupement"]
    assert (r["vp"], r["fp"], r["fn"]) == (1, 1, 1) and r["f1"] == 0.5


def test_regroupement_forme_annexe_c(banc):
    links = [{"from": "fc1", "to": "dec1", "role": "declaration"}]
    liens = [
        {"document_id": "p_dec", "role": "declaration", "force": "forte", "signaux": []},
        {"document_id": "p_fc", "role": "facture_commerciale", "force": "forte"},
    ]
    banc.ajouter(truth("BX0001", links=links), findings("BX0001", [], liens=liens))
    r = banc.scorer()["regroupement"]
    assert r["modes"] == {"documents": 1} and r["f1"] == 1.0


def test_cout_et_duree(banc):
    for i, (c, d) in enumerate([("0.10", 10), ("0.20", 20), ("0.30", 30), ("0.40", 400)], 1):
        banc.ajouter(truth(f"BX000{i}"), findings(f"BX000{i}", [], cout=c, duree=d))
    m = banc.scorer()
    assert m["cout"]["moyenne_eur"] == "0.2500" and m["cout"]["mediane_eur"] == "0.2500"
    assert m["cout"]["p95_eur"] == "0.4000" and m["cout"]["max_eur"] == "0.4000"
    assert m["duree"]["p95_s"] == "400.0000" and m["duree"]["moyenne_s"] == "115.0000"
    assert any("durée p95" in a for a in m["alertes"])


# ---------------------------------------------------------------------------
# Seuil bloquant (§19.7)
# ---------------------------------------------------------------------------


def _dossiers_vp(banc, n, ctrl="D3", n_fp=0, ctrl_fp=None, debut=1):
    """n dossiers avec un VP certain chacun, puis n_fp dossiers avec un FP certain."""
    for i in range(debut, debut + n):
        did = f"BX{i:04d}"
        e = erreur(f"{did}-E1", ctrl, [ctrl], "ecart_certain", "10.00", "recouvrable", ["ft1"])
        banc.ajouter(
            truth(did, [e]), findings(did, [constat("f1", ctrl, "ecart_certain", "10.00", ["p_ft"])])
        )
    for i in range(debut + n, debut + n + n_fp):
        did = f"BX{i:04d}"
        banc.ajouter(
            truth(did), findings(did, [constat("f1", ctrl_fp or ctrl, "ecart_certain", "10.00", ["p_ft"])])
        )


def test_gate_petit_echantillon_tolerance_zero(banc):
    _dossiers_vp(banc, 5, n_fp=1)
    gate = banc.scorer()["gate"]
    assert not gate["passe"]
    assert any(mo.startswith("3.") for mo in gate["motifs"])
    assert any(mo.startswith("1.") for mo in gate["motifs"])  # 5/6 < 0,97


def test_gate_precision_globale(banc):
    _dossiers_vp(banc, 40, n_fp=2, ctrl_fp="D9")  # 40/42 = 0,952
    m = banc.scorer()
    assert m["global"]["n_constats_certain"] == 42
    motifs = m["gate"]["motifs"]
    assert any(mo.startswith("1.") for mo in motifs)
    assert not any(mo.startswith("3.") for mo in motifs)
    assert m["global"]["precision_certain_wilson_bas"] < m["global"]["precision_certain"]


def test_gate_precision_par_controle(banc):
    _dossiers_vp(banc, 100, ctrl="D3")
    _dossiers_vp(banc, 10, ctrl="D1", n_fp=1, debut=101)  # D1 : 10/11 = 0,909 ; global 110/111
    m = banc.scorer()
    motifs = m["gate"]["motifs"]
    assert m["global"]["precision_certain"] >= 0.97
    assert [mo[:5] for mo in motifs] == ["2. D1"]
    assert m["par_controle"]["D1"]["n_constats_certain"] == 11


def test_gate_passe_avec_grand_echantillon_et_un_fp(banc):
    _dossiers_vp(banc, 40, n_fp=1, ctrl_fp="D9")  # 40/41 = 0,9756 ; D9 : 1 constat
    assert banc.scorer()["gate"]["passe"]


def test_gate_rappel_p1(banc):
    e1 = erreur("BX0001-E1", "P1", ["P1"], "a_verifier", None, "aucun", ["fc1"])
    e2 = erreur("BX0002-E1", "P1", ["P1"], "a_verifier", None, "aucun", ["fc1"])
    banc.ajouter(
        truth("BX0001", [e1]),
        findings("BX0001", [constat("f1", "P1", "a_verifier", None, ["p_fc"], nature_montant="aucun")]),
    )
    banc.ajouter(truth("BX0002", [e2]), findings("BX0002", []))
    m = banc.scorer()
    assert m["par_controle"]["P1"]["rappel"] == 0.5
    assert [mo[:2] for mo in m["gate"]["motifs"]] == ["4."]


def test_gate_formulation_interdite_et_renvoi_avec_montant(banc):
    banc.ajouter(
        truth("BX0001"),
        findings(
            "BX0001",
            [
                constat(
                    "f1",
                    "A13",
                    "a_verifier",
                    None,
                    ["p_fc"],
                    libelle="Le code imprimé sur la facture diffère : le bon code est 8471.30.",
                ),
                constat(
                    "f2",
                    "A12",
                    "a_verifier",
                    "120.00",
                    ["p_fc"],
                    renvoi=True,
                    nature_montant="renvoi",
                    prochaine_action="Ce point relève d'une appréciation réglementaire.",
                ),
                constat(
                    "f3",
                    "C1",
                    "a_verifier",
                    "5.00",
                    ["p_ft"],
                    prochaine_action="Les droits dus sont inférieurs.",
                ),
            ],
            avertissement=AVERTISSEMENT + " Facturation FRAUDULEUSE.",
        ),
    )
    m = banc.scorer()
    motifs = m["gate"]["motifs"]
    assert not m["gate"]["passe"]
    gf = m["garde_fous"]
    assert {(h["finding_id"], h["champ"]) for h in gf["formulations_interdites"]} == {
        ("f1", "libelle"),
        ("f3", "prochaine_action"),
        (None, "avertissement"),
    }
    assert [h["finding_id"] for h in gf["renvois_avec_montant"]] == ["f2"]
    assert all(mo.startswith("5.") for mo in motifs) and len(motifs) == 4


def test_cli_gate_code_retour(banc, capsys):
    _dossiers_vp(banc, 3, n_fp=1)
    args = ["--corpus", str(banc.corpus), "--split", "holdout", "--run", str(banc.run)]
    assert main(args) == 0
    assert main([*args, "--gate"]) == 1
    out = capsys.readouterr().out
    assert "ÉCHOUE" in out and "3. petit échantillon" in out
    m = json.loads((banc.run / "metrics.json").read_text(encoding="utf-8"))
    assert m["gate"]["passe"] is False and m["split"] == "holdout"
    md = (banc.run / "metrics.md").read_text(encoding="utf-8")
    assert "Par contrôle" in md and "| D3 |" in md


def test_cli_gate_passe(banc):
    _dossiers_vp(banc, 3)
    args = ["--corpus", str(banc.corpus), "--run", str(banc.run), "--gate"]
    assert main(args) == 0


# ---------------------------------------------------------------------------
# Wilson et formulations
# ---------------------------------------------------------------------------


def test_wilson():
    assert wilson_borne_basse(0, 0) is None
    assert wilson_borne_basse(0, 10) == 0.0
    assert math.isclose(wilson_borne_basse(10, 10), 0.722467, abs_tol=1e-5)
    assert math.isclose(wilson_borne_basse(97, 100), 0.915476, abs_tol=1e-4)
    assert math.isclose(wilson_borne_basse(50, 100), 0.403832, abs_tol=1e-5)


@pytest.mark.parametrize(
    "texte",
    [
        "Les DROITS DUS sur cette ligne",
        "une taxe dûe",
        "Sous-évaluation manifeste",
        "sous evaluation",
        "opération illégale",
        "montants illégaux",
        "facturation frauduleuse",
        "ControlDOne réclame la somme",
        "Nous garantissons le résultat",
        "documents certifiés conformes",
        "Il faut rectifier la déclaration",
        "le taux applicable est de 5 %",
    ],
)
def test_formulations_interdites_detectees(texte):
    assert FORMULATIONS.chercher(texte)


@pytest.mark.parametrize(
    "texte",
    [
        AVERTISSEMENT,
        "Le montant liquidé indiqué sur la déclaration diffère du montant refacturé.",
        "Le code imprimé sur la facture diffère du code imprimé sur la déclaration.",
        "Point à faire vérifier par un RDE ou un avocat.",
        "La valeur en douane n'est pas appréciée.",
    ],
)
def test_formulations_autorisees(texte):
    assert FORMULATIONS.chercher(texte) == []


def test_formulations_depuis_yaml(tmp_path):
    y = tmp_path / "f.yaml"
    y.write_text(
        'version: 1\nformulations:\n  - expression: "perte sèche"\n'
        '    remplacer_par: "écart"\n  - "abus manifeste"\n',
        encoding="utf-8",
    )
    f = charger_formulations(y)
    assert f.source == str(y)
    assert f.chercher("Une PERTE SECHE.") and f.chercher("abus manifestes")
    assert not f.chercher("écart")
