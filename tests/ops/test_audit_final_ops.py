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


# --- planificateur : rattrapage sans doublon (audit B, suspicion 7) ------------------------------------------------

DEPLOY = __import__("pathlib").Path(__file__).resolve().parents[2] / "deploy"


def _copie_executable(source, cible):
    import shutil
    import stat

    cible.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, cible)
    cible.chmod(cible.stat().st_mode | stat.S_IXUSR)
    return cible


def test_sauvegarde_du_jour_pas_refaite_au_redemarrage(tmp_path):
    import subprocess
    from datetime import UTC, datetime

    script = _copie_executable(DEPLOY / "backup-cron.sh", tmp_path / "deploy" / "backup-cron.sh")
    appels = tmp_path / "appels.txt"
    faux = tmp_path / "scripts" / "backup.sh"
    faux.parent.mkdir()
    faux.write_text(f'#!/usr/bin/env bash\necho "$@" >> {appels}\n', encoding="utf-8")
    faux.chmod(0o700)
    dest = tmp_path / "sauvegardes"
    env = {**os.environ, "BACKUP_DIR": str(dest)}
    subprocess.run([str(script), "--si-absente"], check=True, env=env, capture_output=True)
    assert appels.read_text().split() == ["--destination", str(dest)]
    (dest / f"controldone-{datetime.now(UTC):%Y%m%d}T021500Z.tar.gz.enc").write_bytes(b"x")
    subprocess.run([str(script), "--si-absente"], check=True, env=env, capture_output=True)
    assert len(appels.read_text().splitlines()) == 1  # avant : sauvegarde refaite à chaque redémarrage


def test_planificateur_rattrape_le_referentiel_du_mois(tmp_path):
    import signal
    import subprocess
    import time
    from datetime import UTC, datetime

    script = _copie_executable(DEPLOY / "scheduler.sh", tmp_path / "deploy" / "scheduler.sh")
    journal = tmp_path / "appels.txt"
    for nom in ("faux_python", "backup-cron.sh"):
        f = tmp_path / "deploy" / nom
        f.write_text(f'#!/usr/bin/env bash\necho "{nom} $*" >> {journal}\n', encoding="utf-8")
        f.chmod(0o700)
    env = {**os.environ, "CONTROLDONE_PYTHON": str(tmp_path / "deploy" / "faux_python"), "SCHED_TICK_S": "3600",
           "SCHED_BACKUP_HHMM": "0000"}
    p = subprocess.Popen([str(script)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        fin = time.monotonic() + 20
        while time.monotonic() < fin and (not journal.exists() or "backup-cron.sh" not in journal.read_text()):
            time.sleep(0.1)
        time.sleep(0.5)
    finally:
        p.send_signal(signal.SIGTERM)
        p.wait(10)
    lignes = journal.read_text().splitlines()
    assert "backup-cron.sh --si-absente" in lignes
    now = datetime.now(UTC)
    ref = [x for x in lignes if "referentiel_recalculer" in x]
    if now.day > 2 or (now.day == 2 and now.strftime("%H%M") >= "0300"):
        # avant : seulement le 2 du mois (un arrêt ce jour-là sautait le mois), clé quotidienne
        assert len(ref) == 1 and f"referentiel:{now:%Y-%m}'" in ref[0]
    else:
        assert ref == []
