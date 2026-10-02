"""Audit final, exploitation : relevé d'écarts (brief juridique §1.3, §9), référentiel (§5.4), dossier surveillé
(F-16), assiette de la commission (D-1314)."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from test_referentiel import NOM_TRA, SEL, TVA_TRA, _enr

from controldone.guardrails import FormulationInterdite
from controldone.litiges.redaction import verifier_modele
from controldone.referentiel import agreger
from controldone.referentiel.anonymisation import charger_alias_publics
from controldone.referentiel.export import en_csv, en_json

# --- relevé d'écarts et modèle à adapter ---------------------------------------------------------------------------


@pytest.mark.parametrize("texte", [
    "Nous réclamons le remboursement.", "Valant mise en demeure.", "Sous huitaine, à défaut de régularisation.",
    "Conformément aux dispositions du code des douanes.", "En application de l'article L. 441-10.",
    "Des pénalités de retard s'appliqueront.", "Suivi du recouvrement",
])
def test_modele_sans_formulation_d_acte_juridique(texte):
    with pytest.raises(FormulationInterdite):
        verifier_modele(texte)


def test_modele_neutre_accepte():
    verifier_modele("Pourriez-vous vérifier ces montants et nous indiquer si vous émettrez un avoir ? "
                    "Article 12 de la déclaration.")


# --- référentiel : prix seulement pour un transitaire nommé, accord écrit obligatoire -----------------------------


def test_transitaire_nomme_sans_taux_d_ecart():
    alias = {"Transitaire public FICTIF": {"tva": [TVA_TRA], "noms": [NOM_TRA]}}
    enr = [_enr(i, ecart=i % 2 == 0, prix={"frais_dedouanement": Decimal("50")}) for i in range(12)]
    nomme = agreger(enr, sel=SEL, alias_publics=alias).agregats
    assert nomme and nomme[0].transitaire == "Transitaire public FICTIF"
    assert nomme[0].taux_dossiers_avec_ecart is None and nomme[0].prix  # avant : taux d'écart publié sous le nom
    assert en_json(agreger(enr, sel=SEL, alias_publics=alias))["agregats"][0]["taux_dossiers_avec_ecart"] is None
    assert en_csv(agreger(enr, sel=SEL, alias_publics=alias)).splitlines()[1].split(",")[6] == ""
    anonyme = agreger(enr, sel=SEL, alias_publics={}).agregats
    assert anonyme[0].transitaire.startswith("T-") and anonyme[0].taux_dossiers_avec_ecart is not None


def test_alias_sans_accord_ecrit_ignore(tmp_path):
    f = tmp_path / "alias.yaml"
    f.write_text('version: 1\nalias:\n  "Sans accord FICTIF":\n    tva: ["FR00000000001"]\n'
                 '  "Avec accord FICTIF":\n    accord_ecrit: "accord-FICTIF-1, 2026-10-01"\n    tva: ["FR00000000002"]\n',
                 encoding="utf-8")
    assert list(charger_alias_publics(f)) == ["Avec accord FICTIF"]


# --- F-16 : dossier surveillé à mémoire bornée -----------------------------------------------------------------------


def test_f16_dossier_surveille_ne_lit_pas_les_gros_fichiers(tmp_path, monkeypatch):
    from pathlib import Path

    from controldone.connecteurs.dossier_surveille import DossierSurveille, ElementsParesseux

    racine = tmp_path / "depot"
    racine.mkdir()
    (racine / "gros.pdf").write_bytes(b"%PDF" + b"0" * 5000)
    for i in range(3):
        (racine / f"petit{i}.xml").write_bytes(b"<x>FICTIF</x>" * 20)
    for p in racine.iterdir():
        os.utime(p, (1, 1))
    lus = []
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: lus.append(self.name) or original(self))
    c = DossierSurveille("cli_a", racine, taille_fichier=1000, taille_lot=600)
    depots = c.relever()
    assert lus == []  # avant : read_bytes de chaque fichier au relevé, même de plusieurs Go
    assert all(isinstance(d.elements, ElementsParesseux) for d in depots)
    assert len(depots) == 2 and depots[0].meta["ignores_trop_gros"] == ["gros.pdf"]  # 260 o par fichier, 600 o max
    assert [r for d in depots for r, _ in d.elements] == ["petit0.xml", "petit1.xml", "petit2.xml"]
    assert "gros.pdf" not in lus
