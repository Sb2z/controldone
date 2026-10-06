"""Suivi financier : CA HT net des avoirs, encaissements, coût IA par dossier et par client, marge brute,
export CSV."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from aides_facturation import FONDATEUR, SYSTEME, approuver

from controldone.facturation.finances import EncaissementLu, FactureLue, calculer_marges, export_csv, synthese
from controldone.facturation.paiements import signer_charge
from controldone.storage.facturation import UsageIA


def test_marges_fonction_pure():
    lignes = calculer_marges(
        [
            FactureLue("2026-10", "cli_a", Decimal("390.00")),
            FactureLue("2026-10", "cli_a", Decimal("-90.00")),
            FactureLue("2026-11", "cli_b", Decimal("99.00")),
        ],
        [EncaissementLu("2026-10", "cli_a", Decimal("360.00"))],
        [
            UsageIA("cli_a", "2026-10", "dos_1", Decimal("1.20")),
            UsageIA("cli_a", "2026-10", "dos_2", Decimal("0.80")),
            UsageIA("cli_a", "2026-10", None, Decimal("0.10")),
            UsageIA("cli_c", "2026-11", "dos_9", Decimal("0.50")),
        ],
        {"cli_a": "CLIENT A FICTIF"},
    )
    par = {(x.mois, x.client_id): x for x in lignes}
    a = par[("2026-10", "cli_a")]
    assert (a.ca_ht, a.encaisse_ttc, a.cout_ia, a.nb_factures, a.nb_dossiers_ia) == (
        Decimal("300.00"),
        Decimal("360.00"),
        Decimal("2.10"),
        2,
        2,
    )
    assert a.marge_brute == Decimal("297.90") and a.taux_marge == Decimal("99.3")
    c = par[("2026-11", "cli_c")]
    assert c.marge_brute == Decimal("-0.50") and c.taux_marge is None  # coût sans chiffre d'affaires
    assert [x.mois for x in lignes] == sorted(x.mois for x in lignes)


def test_synthese_depuis_la_base_et_csv(service, db, bouchon):
    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    f = service.emettre(a.id, FONDATEUR, le=date.today())
    av = service.proposer_avoir(f.id, FONDATEUR, motif="geste commercial FICTIF", montant_ht=Decimal("40.00"))
    approuver(db, av.id)
    service.emettre(av.id, FONDATEUR, le=date.today())
    s = service.lien_paiement(f.id, FONDATEUR, url_base="http://x")
    for charge, sig in bouchon.simuler_paiement(s.id):
        service.traiter_webhook(charge, sig)
    mois = date.today().strftime("%Y-%m")
    with db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_usage_ia(cout_eur=Decimal("0.42"), mois=mois, dossier_id="dos_FICTIF_1")
        sc.enregistrer_usage_ia(cout_eur=Decimal("0.08"), mois=mois, dossier_id="dos_FICTIF_1")
        sc.enregistrer_usage_ia(cout_eur=Decimal("0.30"), mois=mois, dossier_id="dos_FICTIF_2")
    with db.tenant("cli_b", SYSTEME) as sc:
        sc.enregistrer_usage_ia(cout_eur=Decimal("1.00"), mois=mois, dossier_id="dos_FICTIF_9")
    syn = synthese(db, acteur_id=FONDATEUR.id, acteur_role="fondateur")
    par = {(x.mois, x.client_id): x for x in syn.lignes}
    la = par[(mois, "cli_a")]
    assert (
        la.ca_ht == Decimal("350.00")
        and la.encaisse_ttc == Decimal("468.00")
        and la.cout_ia == Decimal("0.80")
    )
    assert (
        la.marge_brute == Decimal("349.20")
        and la.nb_dossiers_ia == 2
        and la.raison_sociale == "CLIENT A FICTIF SAS"
    )
    assert par[(mois, "cli_b")].marge_brute == Decimal("-1.00")
    assert syn.par_mois[-1].cout_ia == Decimal("1.80")
    assert syn.couts_dossiers[0].dossier_id == "dos_FICTIF_9"
    assert {x["numero"] for x in syn.factures} == {"F-" + mois[:4] + "-0001", "AV-" + mois[:4] + "-0001"}
    fac = next(x for x in syn.factures if x["type"] == "Facture")
    assert fac["encaisse"] == Decimal("468.00") and fac["statut_pa"] == "non déposée"
    # la lecture transversale du registre des coûts IA est journalisée
    with db.operateur(FONDATEUR) as op:
        assert any(e.action == "lire_couts_ia" for e in op.journal(50))
    csv = export_csv(syn.lignes).decode("utf-8")
    assert csv.startswith("﻿mois;client_id;client;factures;ca_ht_eur")
    assert f"{mois};cli_a;CLIENT A FICTIF SAS;2;350,00;468,00;0,80;2;349,20;99,8" in csv


def test_csv_neutralise_les_formules():
    from controldone.facturation.finances import LigneMarge

    csv = export_csv([LigneMarge("2026-10", "cli_x", '=HYPERLINK("http://x")')]).decode("utf-8")
    assert "\"'=HYPERLINK" in csv and ";=HYPERLINK" not in csv


def test_evenement_sans_montant_hors_encaissements(service, db):
    charge = json.dumps(
        {
            "id": "evt_FICTIF_sub",
            "type": "customer.subscription.deleted",
            "livemode": False,
            "data": {"object": {"id": "sub_x", "metadata": {"client_id": "cli_b"}}},
        }
    ).encode()
    service.traiter_webhook(charge, signer_charge(charge, "whsec_test_FICTIF"))
    syn = synthese(db, acteur_id=FONDATEUR.id, acteur_role="fondateur")
    assert syn.lignes == [] and syn.encaissements[0]["montant"] is None
