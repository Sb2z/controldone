"""Interface : page « Finances » du fondateur (second facteur), refus pour un client, export CSV, pièces,
approbation d'une facture par la file de validation, paiement simulé et webhook Stripe signé."""

from __future__ import annotations

import re

import pytest
from aides_facturation import FONDATEUR
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from controldone.auth.motdepasse import hacher_mot_de_passe
from controldone.auth.roles import Role
from controldone.auth.totp import code_totp, generer_secret
from controldone.facturation.paiements import signer_charge
from controldone.outbox import FileSortante
from controldone.services.plateforme import Plateforme
from controldone.storage import FileVault
from controldone.storage import facturation as stock
from controldone.storage.cles import chiffrer_secret
from controldone.storage.comptes import creer_utilisateur, enregistrer_totp
from controldone.web import ParametresWeb, create_app

MDP = "phrase-de-passe-FICTIVE-123"
SECRET_SESSION = "secret-de-session-FICTIF-0123456789-abcdef"


def _jeton(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m
    return m.group(1)


@pytest.fixture
def web(db, service, tmp_path):
    cle = Fernet.generate_key()
    pf = Plateforme(db=db, vault=FileVault(tmp_path / "coffre", [cle]), cles_maitresses=[cle],
                    dossier_sorties=tmp_path / "sorties")
    pf.facturation = service  # type: ignore[attr-defined]
    creer_utilisateur(db, user_id=FONDATEUR.id, email="fondateur@controldone-fictif.test",
                      mot_de_passe_hash=hacher_mot_de_passe(MDP), role=Role.fondateur, acteur=FONDATEUR)
    secret = generer_secret()
    enregistrer_totp(db, FONDATEUR.id, chiffrer_secret([cle], secret), acteur=FONDATEUR)
    creer_utilisateur(db, user_id="usr_client_a", email="admin@client-a-fictif.test",
                      mot_de_passe_hash=hacher_mot_de_passe(MDP), role=Role.client_admin, acteur=FONDATEUR)
    with db.operateur(FONDATEUR) as op:
        op.client("cli_a", "compte de test").ajouter_membre("usr_client_a", Role.client_admin)
    app = create_app(ParametresWeb(plateforme=pf, secrets_session=[SECRET_SESSION], prod=False))
    return app, secret


def _connecter(c: TestClient, email: str, totp: str | None = None) -> None:
    t = _jeton(c.get("/connexion").text)
    r = c.post("/connexion", data={"csrf": t, "email": email, "mot_de_passe": MDP}, follow_redirects=False)
    assert r.status_code == 303
    if totp:
        t = _jeton(c.get("/connexion/totp").text)
        r = c.post("/connexion/totp", data={"csrf": t, "code": code_totp(totp)}, follow_redirects=False)
        assert r.headers["location"] == "/admin"


def _poster(c: TestClient, url: str, donnees: dict | None = None):
    t = _jeton(c.get("/admin/finances").text)
    return c.post(url, data={"csrf": t, **(donnees or {})}, follow_redirects=False)


def test_page_finances_et_cycle_complet(web, db, pa):
    app, totp = web
    c = TestClient(app, base_url="http://testserver")
    _connecter(c, "fondateur@controldone-fictif.test", totp)
    page = c.get("/admin/finances")
    assert page.status_code == 200 and "Finances" in page.text and "bouchon local" in page.text
    assert 'href="/admin/finances" aria-current="page"' in page.text
    # brouillon de diagnostic -> file de validation -> approbation (émission + dépôt PA)
    r = _poster(c, "/admin/finances/diagnostic", {"client_id": "cli_a"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/validation#sorties"
    assert stock.factures(db) == []  # rien n'est émis sans approbation
    (action,) = FileSortante(db).lister(FONDATEUR, kind="facture_emise")
    t = _jeton(c.get("/admin/validation").text)
    r = c.post(f"/admin/sorties/{action.id}/approuver", data={"csrf": t}, follow_redirects=False)
    assert r.status_code == 303
    (f,) = stock.factures(db)
    assert f.numero.startswith("F-") and f.numero.endswith("-0001")
    assert list((pa.racine / "deposees").glob("*.pdf"))
    page = c.get("/admin/finances").text
    assert f.numero in page and "Déposée (200)" in page
    pdf = c.get(f"/admin/finances/factures/{f.id}.pdf")
    assert pdf.status_code == 200 and pdf.content == f.pdf and pdf.headers["content-type"] == "application/pdf"
    xml = c.get(f"/admin/finances/factures/{f.id}.xml")
    assert xml.status_code == 200 and b"CrossIndustryInvoice" in xml.content
    # lien de paiement (bouchon) puis paiement simulé : passe par la vérification de signature du webhook
    r = _poster(c, f"/admin/finances/factures/{f.id}/paiement")
    lien = re.search(r"/admin/finances/bouchon/(cs_bouchon_[0-9a-f]+)", c.get("/admin/finances").text)
    assert r.status_code == 303 and lien
    assert "468,00" in c.get(lien.group(0)).text
    r = _poster(c, lien.group(0) + "/payer")
    assert r.status_code == 303
    assert stock.evenements_paiement(db)[0].facture_id == f.id
    csv = c.get("/admin/finances/export.csv")
    assert csv.status_code == 200 and "cli_a;CLIENT A FICTIF SAS;1;390,00;468,00" in csv.content.decode("utf-8")
    # coupon sans accord de publication : la remise s'applique quand même (accord distinct, D-1313)
    r = _poster(c, "/admin/finances/diagnostic", {"client_id": "cli_b", "coupon": "LANCEMENT-3-DIAGNOSTICS"})
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/validation")


def test_finances_refusees_a_un_client(web):
    app, _ = web
    c = TestClient(app, base_url="http://testserver")
    _connecter(c, "admin@client-a-fictif.test")
    for url in ("/admin/finances", "/admin/finances/export.csv"):
        assert c.get(url).status_code == 404
    assert "/admin/finances" not in c.get("/espace").text


def test_webhook_stripe_signature(web, db):
    app, _ = web
    c = TestClient(app, base_url="http://testserver")
    charge = (b'{"id": "evt_FICTIF_web", "type": "invoice.payment_failed", "livemode": false, '
              b'"data": {"object": {"id": "in_FICTIF", "metadata": {}}}}')
    assert c.post("/webhooks/stripe", content=charge, headers={"stripe-signature": "t=1,v1=faux"}).status_code == 400
    assert c.post("/webhooks/stripe", content=charge).status_code == 400
    r = c.post("/webhooks/stripe", content=charge,
               headers={"stripe-signature": signer_charge(charge, "whsec_test_FICTIF")})
    assert r.status_code == 200 and r.json() == {"recu": True, "statut": "traite"}
    r = c.post("/webhooks/stripe", content=charge,
               headers={"stripe-signature": signer_charge(charge, "whsec_test_FICTIF")})
    assert r.json()["statut"] == "deja_traite"
    assert len(stock.evenements_paiement(db)) == 1
