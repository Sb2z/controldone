"""Paiements : garde sur les clés Stripe, Stripe simulé (aucun appel réseau), signature des webhooks avec un
secret FICTIF, flux complet du bouchon (Checkout, abonnement, échec), idempotence des événements."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from aides_facturation import FONDATEUR, approuver

from controldone.facturation import PaiementBouchon, PaiementStripe, ServiceFacturation, SignatureInvalide
from controldone.facturation.paiements import (
    CleStripeRefusee,
    centimes,
    fournisseur_depuis_env,
    signer_charge,
)
from controldone.outbox import FileSortante
from controldone.storage import facturation as stock

SECRET = "whsec_test_FICTIF"
CLE_TEST = "sk_test_FICTIVE_0000000000000000"


def _evt(type_: str, objet: dict, evt_id: str = "evt_FICTIF_1") -> bytes:
    return json.dumps({"id": evt_id, "object": "event", "type": type_, "created": 1790000000, "livemode": False,
                       "data": {"object": objet}}).encode()


def test_garde_sur_les_cles():
    assert PaiementStripe(CLE_TEST, SECRET, client=MagicMock(), env={}).mode_test
    with pytest.raises(CleStripeRefusee, match="production"):
        PaiementStripe("sk_live_FICTIVE", SECRET, client=MagicMock(), env={"CONTROLDONE_ENV": "prod"})
    with pytest.raises(CleStripeRefusee, match="production"):
        PaiementStripe("sk_live_FICTIVE", SECRET, client=MagicMock(), env={"STRIPE_LIVE_OK": "1"})
    live = PaiementStripe("sk_live_FICTIVE", SECRET, client=MagicMock(),
                          env={"CONTROLDONE_ENV": "prod", "STRIPE_LIVE_OK": "1"})
    assert not live.mode_test
    with pytest.raises(CleStripeRefusee):
        PaiementStripe("pk_test_FICTIVE", SECRET, client=MagicMock(), env={})
    with pytest.raises(CleStripeRefusee) as exc:
        PaiementStripe("sk_live_SECRET_A_NE_PAS_AFFICHER", SECRET, client=MagicMock(), env={})
    assert "SECRET_A_NE_PAS_AFFICHER" not in str(exc.value)


def test_fournisseur_selon_environnement(tmp_path):
    assert isinstance(fournisseur_depuis_env({}, racine_bouchon=tmp_path), PaiementBouchon)
    p = fournisseur_depuis_env({"STRIPE_SECRET_KEY": CLE_TEST, "STRIPE_WEBHOOK_SECRET": SECRET})
    assert isinstance(p, PaiementStripe) and p.secret_webhook == SECRET  # aucun appel réseau à la construction
    with pytest.raises(CleStripeRefusee):
        fournisseur_depuis_env({"STRIPE_SECRET_KEY": "sk_live_FICTIVE"})


def test_stripe_simule_parametres_checkout_et_abonnement():
    client = MagicMock()
    client.v1.customers.create.return_value = MagicMock(id="cus_FICTIF")
    client.v1.checkout.sessions.create.return_value = MagicMock(id="cs_test_FICTIF", url="https://checkout.example.test/x")
    p = PaiementStripe(CLE_TEST, SECRET, client=client, env={})
    assert p.creer_client(client_id="cli_a", raison_sociale="CLIENT A FICTIF", email="a@fictif.test") == "cus_FICTIF"
    s = p.session_paiement(client_id="cli_a", customer_id="cus_FICTIF", facture_id="fac_1", numero="F-2026-0001",
                           montant_ttc=Decimal("468.00"), libelle="ControlDOne", url_succes="https://x/ok",
                           url_annulation="https://x/ko")
    assert s.id == "cs_test_FICTIF" and s.mode == "payment"
    params = client.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert params["mode"] == "payment" and params["line_items"][0]["price_data"]["unit_amount"] == 46800
    assert params["metadata"] == {"client_id": "cli_a", "facture_id": "fac_1", "numero": "F-2026-0001"}
    assert client.v1.checkout.sessions.create.call_args.kwargs["options"] == {"idempotency_key": "checkout:fac_1"}
    p.session_abonnement(client_id="cli_b", customer_id=None, palier="essentiel", libelle="Essentiel",
                         montant_ttc_mensuel=Decimal("118.80"), url_succes="https://x/ok", url_annulation="https://x/ko")
    params = client.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert params["mode"] == "subscription" and params["line_items"][0]["price_data"]["recurring"] == {"interval": "month"}
    assert params["line_items"][0]["price_data"]["unit_amount"] == 11880
    assert params["subscription_data"]["metadata"]["palier"] == "essentiel"
    with pytest.raises(ValueError):
        centimes(Decimal("1.005"))


def test_signature_webhook_secret_fictif():
    p = PaiementStripe(CLE_TEST, SECRET, client=MagicMock(), env={})
    charge = _evt("checkout.session.completed", {"id": "cs_1"})
    assert p.verifier_webhook(charge, signer_charge(charge, SECRET))["id"] == "evt_FICTIF_1"
    for sig in (None, "", signer_charge(charge, "whsec_autre"), "t=1,v1=00"):
        with pytest.raises(SignatureInvalide):
            p.verifier_webhook(charge, sig)
    with pytest.raises(SignatureInvalide):  # charge modifiée après signature
        p.verifier_webhook(charge.replace(b"cs_1", b"cs_2"), signer_charge(charge, SECRET))
    with pytest.raises(SignatureInvalide):  # signature trop ancienne (rejeu)
        p.verifier_webhook(charge, signer_charge(charge, SECRET, horodatage=1_000_000_000))
    sans_secret = PaiementStripe(CLE_TEST, None, client=MagicMock(), env={})
    with pytest.raises(SignatureInvalide):
        sans_secret.verifier_webhook(charge, signer_charge(charge, SECRET))


def _facture_emise(service, db):
    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    return service.emettre(a.id, FONDATEUR, le=date(2026, 10, 2))


def test_flux_bouchon_paiement_unique(service, db, bouchon):
    f = _facture_emise(service, db)
    s = service.lien_paiement(f.id, FONDATEUR, url_base="http://testserver")
    assert s.url == f"/admin/finances/bouchon/{s.id}" and bouchon.session(s.id)["amount_total"] == 46800
    assert stock.compte_paiement(db, "cli_a").customer_id.startswith("cus_bouchon_")
    evts = bouchon.simuler_paiement(s.id)
    res = [service.traiter_webhook(c, sig) for c, sig in evts]
    assert res[0]["statut"] == "traite" and "encaissement" in res[0]["effets"]
    assert service.traiter_webhook(*evts[0])["statut"] == "deja_traite"  # webhook rejoué
    e = stock.evenements_paiement(db)
    assert len(e) == 1 and e[0].montant == Decimal("468.00") and e[0].facture_id == f.id and e[0].client_id == "cli_a"
    with pytest.raises(SignatureInvalide):
        service.traiter_webhook(evts[0][0], signer_charge(evts[0][0], "whsec_mauvais"))


def test_flux_bouchon_abonnement(service, db, bouchon):
    s = service.lien_abonnement("cli_b", "essentiel", FONDATEUR, url_base="http://testserver")
    assert bouchon.session(s.id)["amount_total"] == 11880  # 99,00 HT + 19,80 TVA
    for charge, sig in bouchon.simuler_paiement(s.id, mois="2026-10"):
        service.traiter_webhook(charge, sig)
    compte = stock.compte_paiement(db, "cli_b")
    assert compte.statut_abonnement == "active" and compte.palier == "essentiel" and compte.abonnement_id
    brouillon = FileSortante(db).lister(FONDATEUR, kind="facture_emise", tenant_id="cli_b")
    assert len(brouillon) == 1 and brouillon[0].idempotency_key == "facture:abonnement:cli_b:2026-10"
    assert brouillon[0].statut.value == "brouillon"  # jamais émise sans le fondateur
    approuver(db, brouillon[0].id)
    f = service.emettre(brouillon[0].id, FONDATEUR, le=date(2026, 10, 2))
    assert f.contenu["net_a_payer"] == "0.00" and "<ram:TotalPrepaidAmount>118.80<" in f.xml
    # échéance suivante en échec : alerte au fondateur, aucun encaissement
    charge, sig = bouchon.simuler_facture_abonnement(compte.abonnement_id, compte.customer_id, 11880,
                                                     {"client_id": "cli_b", "palier": "essentiel"}, payee=False)
    assert service.traiter_webhook(charge, sig)["effets"] == ["alerte"]
    with db.operateur(FONDATEUR) as op:
        assert any(a.kind == "paiement_echoue" and a.tenant_id == "cli_b" for a in op.alertes())
    assert sum((e.montant or 0) for e in stock.evenements_paiement(db, client_id="cli_b")) == Decimal("118.80")


def test_metadonnee_client_inconnue_sans_effet(service, db):
    charge = _evt("checkout.session.completed", {"id": "cs_x", "mode": "payment", "payment_status": "paid",
                                                 "amount_total": 1000, "currency": "eur",
                                                 "metadata": {"client_id": "cli_inexistant", "facture_id": "fac_x"}})
    res = service.traiter_webhook(charge, signer_charge(charge, "whsec_test_FICTIF"))
    e = stock.evenements_paiement(db)[0]
    assert res["statut"] == "traite" and e.client_id is None and e.facture_id is None


def test_paiement_avec_stripe_simule(db, catalogue, pa):
    client = MagicMock()
    client.v1.customers.create.return_value = MagicMock(id="cus_FICTIF")
    client.v1.checkout.sessions.create.return_value = MagicMock(id="cs_test_1", url="https://checkout.example.test/1")
    svc = ServiceFacturation(db, catalogue=catalogue, pa=pa, prod=False,
                             paiement=PaiementStripe(CLE_TEST, SECRET, client=client, env={}))
    f = _facture_emise(svc, db)
    s = svc.lien_paiement(f.id, FONDATEUR, url_base="https://controldone.example.test")
    assert s.url == "https://checkout.example.test/1" and client.v1.customers.create.call_count == 1
    svc.lien_paiement(f.id, FONDATEUR, url_base="https://controldone.example.test")
    assert client.v1.customers.create.call_count == 1  # client Stripe réutilisé
    charge = _evt("checkout.session.completed", {"id": "cs_test_1", "mode": "payment", "payment_status": "paid",
                                                 "amount_total": 46800, "currency": "eur", "customer": "cus_FICTIF",
                                                 "metadata": {"client_id": "cli_a", "facture_id": f.id}})
    assert svc.traiter_webhook(charge, signer_charge(charge, SECRET))["statut"] == "traite"
    assert stock.evenements_paiement(db)[0].fournisseur == "stripe"
