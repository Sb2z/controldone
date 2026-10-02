"""Référentiel anonymisé : aucun identifiant ne sort, seuils de k-anonymat, arrondis, alias publics,
opt-out, recalcul par job."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from aides_ops import FONDATEUR, SYSTEME, doc_row

from controldone.jobs.registre import JobContext
from controldone.model.dossier import Dossier as DossierModele
from controldone.referentiel import (
    EnregistrementFlux,
    Seuils,
    agreger,
    arrondir_montant,
    cle_transitaire,
    en_csv,
    en_json,
    famille_incoterm,
    groupe_pays,
    recalculer,
)
from controldone.referentiel.jobs import referentiel_recalculer
from controldone.storage.file_jobs import JobInfo
from controldone.storage.models import Constat, Transitaire

SEL = b"sel-de-test-FICTIF"
NOM_TRA, TVA_TRA = "TRANSIT EXPRESS FICTIF SAS", "FR40123456789"


def _enr(i, *, client=None, tra=NOM_TRA, tva=TVA_TRA, ecart=False, prix=None, pays="CN", mois="2026-08"):
    return EnregistrementFlux(client_id=client or f"cli_{i % 5}", transitaire_nom=tra, transitaire_tva=tva,
                              pays_origine=pays, incoterm="FOB", sous_type_declaration="h1", mois=mois,
                              avec_ecart=ecart, prix=prix if prix is not None else
                              {"frais_dedouanement": Decimal("60.00") + i})


def test_regroupements():
    assert groupe_pays("cn") == "chine" and groupe_pays("DE") == "ue" and groupe_pays("BR") == "autre"
    assert groupe_pays(None) == "inconnu"
    assert famille_incoterm("FOB Shanghai") == "F" and famille_incoterm("DDP") == "D" and famille_incoterm("?") == "inconnue"
    assert arrondir_montant(Decimal("62.40")) == Decimal("60.00") and arrondir_montant(Decimal("62.50")) == Decimal("65.00")


def test_cle_transitaire_salee_et_alias_public():
    h = cle_transitaire(NOM_TRA, TVA_TRA, sel=SEL)
    assert h.startswith("T-") and len(h) == 14
    assert h == cle_transitaire("autre graphie", "FR 40 123 456 789", sel=SEL)  # TVA normalisée
    assert h != cle_transitaire(NOM_TRA, TVA_TRA, sel=b"autre-sel")
    assert TVA_TRA not in h and "TRANSIT" not in h
    alias = {"Transitaire public FICTIF": {"tva": [TVA_TRA], "noms": []}}
    assert cle_transitaire(NOM_TRA, TVA_TRA, sel=SEL, alias_publics=alias) == "Transitaire public FICTIF"
    with pytest.raises(ValueError):
        cle_transitaire(NOM_TRA, None, sel=b"")


def test_seuils_de_publication():
    # 5 clients, 10 dossiers : publié
    res = agreger([_enr(i) for i in range(10)], sel=SEL)
    assert len(res.agregats) == 1 and res.supprimes == 0
    # 4 clients, 12 dossiers : supprimé
    res = agreger([_enr(i, client=f"cli_{i % 4}") for i in range(12)], sel=SEL)
    assert res.agregats == [] and res.supprimes == 1
    # 5 clients, 9 dossiers : supprimé
    res = agreger([_enr(i) for i in range(9)], sel=SEL)
    assert res.agregats == [] and res.supprimes == 1
    # seuils réglables (jamais en dessous en production : voir docs/REFERENTIEL.md)
    assert len(agreger([_enr(i) for i in range(9)], sel=SEL, seuils=Seuils(5, 9)).agregats) == 1


def test_statistique_de_prix_soumise_aux_memes_seuils():
    enr = [_enr(i, prix={"frais_dedouanement": Decimal("60")} | ({"magasinage": Decimal("100")} if i < 4 else {}))
           for i in range(10)]
    a = agreger(enr, sel=SEL).agregats[0]
    assert "frais_dedouanement" in a.prix and "magasinage" not in a.prix  # 4 dossiers seulement


def test_taux_et_montants_arrondis():
    enr = [_enr(i, ecart=i < 3, prix={"frais_dedouanement": Decimal("61.37") + i}) for i in range(10)]
    a = agreger(enr, sel=SEL).agregats[0]
    assert a.taux_dossiers_avec_ecart == Decimal("0.30")
    assert all(v % 5 == 0 for v in a.prix["frais_dedouanement"].values())
    assert a.dossiers == "10-19"


def test_aucun_identifiant_dans_les_exports():
    identifiants = [NOM_TRA, TVA_TRA, "40123456789", "CLIENT", "cli_", "dos_", "FT-", "26FR", "rue", "Paris"]
    enr = [_enr(i) for i in range(12)]
    res = agreger(enr, sel=SEL)
    texte = json.dumps(en_json(res)) + en_csv(res)
    for ident in identifiants:
        assert ident not in texte, ident


# --- intégration base : collecte, opt-out, job ------------------------------------------------------------


def _peupler_flux(db, tenant, n_dossiers, *, opt_out=False, propose=False):
    from controldone.storage.db import Database  # noqa: F401

    with db.operateur(FONDATEUR) as op:
        op.creer_client(tenant, f"CLIENT {tenant.upper()} FICTIF",
                        reglages={"referentiel_opt_out": True} if opt_out else {})
    with db.tenant(tenant, SYSTEME) as sc:
        sc._ajouter_interne(Transitaire(id=f"tra_{tenant}", nom=NOM_TRA, tva=TVA_TRA))
        for i in range(n_dossiers):
            did = f"dos_{tenant}_{i}"
            sc.enregistrer_dossier(DossierModele(id=did, client_id=tenant, transitaire_id=f"tra_{tenant}",
                                                 reference=f"D-2026-{i:05d}"))
            fc = doc_row(f"fc_{tenant}_{i}", "facture_commerciale", {"numero": f"FC-{tenant}-{i}", "incoterm": "FOB"},
                         dossier_id=did)
            fc.contenu["champs"]["lignes"] = [{"pays_origine": {"valeur": "CN"}}]
            sc._ajouter_interne(fc)
            dec = doc_row(f"dec_{tenant}_{i}", "declaration", {"mrn": f"26FR0000000000{i:04d}",
                                                              "date_acceptation": "2026-08-14"}, dossier_id=did,
                          extra={"sous_type": "h1"})
            sc._ajouter_interne(dec)
            ft = doc_row(f"ft_{tenant}_{i}", "facture_transitaire", {"numero": f"FT-{tenant}-{i}"}, dossier_id=did)
            ft.contenu["champs"]["lignes"] = [{"nature": "frais_dedouanement", "montant_ht": {"valeur": "65.00"}},
                                              {"nature": "debours_droits", "montant_ht": {"valeur": "999.00"}}]
            sc._ajouter_interne(ft)
            if i == 0:
                sc._ajouter_interne(Constat(id=f"f_{tenant}_{i}", dossier_id=did, dossier_version=1, controle_id="C1",
                                            niveau="ecart_certain", montant_en_jeu=Decimal("10.00"),
                                            nature_montant="recouvrable",
                                            statut_validation="propose" if propose else "valide", contenu={}))


def test_recalcul_par_job_et_opt_out(db, tmp_path):
    for t in ("cli_p1", "cli_p2", "cli_p3", "cli_p4", "cli_p5"):
        _peupler_flux(db, t, 2)
    _peupler_flux(db, "cli_opt", 2, opt_out=True)
    sortie = tmp_path / "ref"
    job = JobInfo("job_x", "referentiel_recalculer", {"dossier_sortie": str(sortie)}, "referentiel:1", None,
                  "running", 1, 5, None, None, None, None, None)  # type: ignore[arg-type]
    import os

    os.environ["CONTROLDONE_REFERENTIEL_SEL"] = "sel-FICTIF"
    try:
        resume = referentiel_recalculer(JobContext(job=job, db=db))
    finally:
        del os.environ["CONTROLDONE_REFERENTIEL_SEL"]
    assert resume["clients"] == 5 and resume["clients_opt_out"] == 1 and resume["publies"] == 1
    data = json.loads((sortie / "referentiel.json").read_text(encoding="utf-8"))
    a = data["agregats"][0]
    assert a["groupe_origine"] == "chine" and a["famille_incoterm"] == "F" and a["regime"] == "standard"
    assert a["mois"] == "2026-08" and a["prix"]["frais_dedouanement"]["mediane"] == "65.00"
    assert a["taux_dossiers_avec_ecart"] == "0.50"
    brut = (sortie / "referentiel.json").read_text() + (sortie / "referentiel.csv").read_text()
    for ident in (NOM_TRA, TVA_TRA, "cli_p", "FT-", "FC-", "26FR", "D-2026", "999"):
        assert ident not in brut, ident
    # un client de moins (opt-out) : sous le seuil, plus rien n'est publié
    with db.operateur(FONDATEUR) as op:
        op.modifier_client("cli_p5", reglages={"referentiel_opt_out": True})
    res = recalculer(db, dossier_sortie=sortie, sel=b"sel-FICTIF", alias_publics={})
    assert res["publies"] == 0 and res["supprimes"] == 1


def test_dossiers_non_valides_exclus(db, tmp_path):
    for t in ("cli_q1", "cli_q2", "cli_q3", "cli_q4", "cli_q5"):
        _peupler_flux(db, t, 2, propose=True)
    res = recalculer(db, dossier_sortie=tmp_path, sel=b"s", alias_publics={})
    assert res["dossiers_non_valides"] == 5 and res["publies"] == 0
