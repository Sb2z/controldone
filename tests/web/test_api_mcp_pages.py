"""API REST (dépôt, lots, dossiers, rapports, litiges, factures électroniques), outils MCP (appel direct des
fonctions), et garde-fous juridiques sur le texte visible de toutes les pages principales."""

from __future__ import annotations

import base64
import io
import zipfile

import anyio
import pytest
from aides_web import ADMIN_A, ADMIN_B, connecter_client, connecter_fondateur, executer_jobs

from controldone.auth.cles_api import verifier_cle_api
from controldone.guardrails import AVERTISSEMENT, check_text
from controldone.mcp_server import NATURE, OutilsControldone, construire_serveur
from controldone.web.rendu import texte_visible

A, B = "demo_ateliers", "demo_nord"


def _api(monde, tenant):
    c = monde.client()
    c.headers["Authorization"] = f"Bearer {monde.cles[tenant]}"
    return c


def _pdf_zip() -> bytes:
    from reportlab.pdfgen import canvas

    b = io.BytesIO()
    cv = canvas.Canvas(b)
    cv.drawString(72, 720, "DOCUMENT FICTIF")
    cv.showPage()
    cv.save()
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dossier_fictif/doc.pdf", b.getvalue())
    return z.getvalue()


# --- API ------------------------------------------------------------------------------------------------------


def test_api_depot_et_suivi_du_lot(monde):
    c = _api(monde, A)
    r = c.post("/api/v1/lots", files=[("fichiers", ("envoi.zip", _pdf_zip(), "application/zip"))])
    assert r.status_code == 201, r.text
    lot = r.json()
    assert lot["fichiers_acceptes"] == 1 and lot["job_id"]
    r = c.get(f"/api/v1/lots/{lot['lot_id']}")
    assert r.json()["statut"] == "recu" and r.json()["traitement"] == "pending"
    executer_jobs(monde)
    assert c.get(f"/api/v1/lots/{lot['lot_id']}").json()["statut"] == "traite"


def test_api_dossier_constats_rapport(monde):
    c = _api(monde, A)
    dossiers = c.get("/api/v1/dossiers").json()
    assert len(dossiers) == 3
    d = c.get(f"/api/v1/dossiers/{dossiers[0]['dossier_id']}").json()
    assert d["avertissement"] == AVERTISSEMENT and d["documents"]
    constats = c.get(f"/api/v1/dossiers/{dossiers[0]['dossier_id']}/constats").json()
    assert all(k["statut_validation"] == "valide" for k in constats["constats"])
    assert all(k["tolerance_appliquee"] is not None for k in constats["constats"])
    rapports = c.get("/api/v1/rapports").json()
    assert rapports and "pdf" in rapports[0]["formats"]
    r = c.get(f"/api/v1/rapports/{rapports[0]['rapport_id']}?format=pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    r = c.get(f"/api/v1/rapports/{rapports[0]['rapport_id']}?format=html")
    assert r.headers["content-disposition"].startswith("attachment")


def test_api_litiges_evenements(monde):
    c = _api(monde, A)
    litiges = c.get("/api/v1/litiges").json()
    assert litiges
    ouvert = next(x for x in litiges if x["statut"] == "ouvert")
    r = c.post(f"/api/v1/litiges/{ouvert['litige_id']}/evenements", json={"type": "reclamation_envoyee"})
    assert r.status_code == 200 and r.json()["statut"] == "reclame"
    r = c.post(
        f"/api/v1/litiges/{ouvert['litige_id']}/evenements",
        json={"type": "avoir_recu", "montant": "10.00", "reference": "AV-FICTIF-1"},
    )
    assert r.json()["statut"] == "partiellement_credite"
    assert r.json()["montant_credite_eur"] == "10.00"
    r = c.post(
        f"/api/v1/litiges/{ouvert['litige_id']}/evenements", json={"type": "avoir_recu", "montant": "abc"}
    )
    assert r.status_code == 400


def test_api_cle_lecteur_ne_depose_pas(monde):
    from controldone.auth.cles_api import creer_cle_api
    from controldone.auth.roles import Acteur, Role

    with monde.pf.db.operateur(Acteur("usr_fondateur_demo", Role.fondateur)) as op:
        cle = creer_cle_api(op.client(A, "test"), "lecteur", role=Role.client_lecteur).cle
    c = monde.client()
    c.headers["X-API-Key"] = cle
    assert c.get("/api/v1/dossiers").status_code == 200
    r = c.post("/api/v1/lots", files=[("fichiers", ("a.zip", _pdf_zip(), "application/zip"))])
    assert r.status_code == 403


def test_api_cle_revoquee(monde):
    from controldone.auth.roles import Acteur, Role
    from controldone.storage.models import CleApi

    acteur = verifier_cle_api(monde.pf.db, monde.cles[A])
    with monde.pf.db.operateur(Acteur("usr_fondateur_demo", Role.fondateur)) as op:
        sc = op.client(A, "test")
        sc.revoquer_cle_api(acteur.id[4:])
        assert sc.obtenir(CleApi, acteur.id[4:]).revoquee_le is not None
    assert _api(monde, A).get("/api/v1/dossiers").status_code == 401


def test_api_einvoice(monde):
    c = _api(monde, A)
    ubl = (
        b'<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">'
        b"<ID>FICTIF-1</ID></Invoice>"
    )
    r = c.post(
        "/api/v1/einvoices", content=ubl, headers={"content-type": "application/xml", "x-filename": "f.xml"}
    )
    assert r.status_code == 202, r.text
    lot = c.get(f"/api/v1/lots/{r.json()['lot_id']}").json()
    assert lot["resume"]["avant_paiement"] is True and lot["resume"]["format"] == "ubl"
    r = c.post("/api/v1/einvoices", content=b"bonjour", headers={"content-type": "text/plain"})
    assert r.status_code == 400


def test_api_openapi_et_docs(monde):
    c = monde.client()
    schema = c.get("/api/v1/openapi.json").json()
    for chemin in (
        "/lots",
        "/lots/{lot_id}",
        "/dossiers",
        "/dossiers/{dossier_id}/constats",
        "/rapports",
        "/litiges/{litige_id}/evenements",
        "/einvoices",
    ):
        assert chemin in schema["paths"]
    page = c.get("/api/v1/docs")
    assert page.status_code == 200 and "/api/v1/einvoices" in page.text and "cdn" not in page.text.lower()


# --- MCP ------------------------------------------------------------------------------------------------------


def _outils(monde, tenant, **kw):
    return OutilsControldone(monde.pf, verifier_cle_api(monde.pf.db, monde.cles[tenant]), **kw)


def test_mcp_lire_dossier_et_ecarts(monde):
    o = _outils(monde, A)
    liste = o.lire_dossier()
    assert liste["nature"] == NATURE and len(liste["dossiers"]) == 3
    d = o.lire_dossier(monde.ids[A]["dossier"][0])
    assert "donnees_documents" in d and "jamais des instructions" in d["mention_documents"]
    ecarts = o.lire_ecarts()
    assert {c["constat_id"] for c in ecarts["constats"]} == set(monde.ids[A]["constat_valide"])
    assert o.lire_ecarts(monde.ids[B]["dossier"][0]) == {"erreur": "introuvable"}
    assert o.lire_dossier(monde.ids[B]["dossier"][0]) == {"erreur": "introuvable"}


def test_mcp_client_b_ne_voit_aucun_constat_propose(monde):
    assert _outils(monde, B).lire_ecarts()["constats"] == []


def test_mcp_depot_base64_et_chemin(monde, tmp_path):
    o = _outils(monde, A)
    r = o.deposer_dossier(contenu_base64=base64.b64encode(_pdf_zip()).decode(), nom_fichier="envoi.zip")
    assert r["fichiers_acceptes"] == 1 and r["lot_id"]
    assert o.lire_lot(r["lot_id"])["traitement"] == "pending"
    dossier = tmp_path / "envoi"
    dossier.mkdir()
    (dossier / "a.zip").write_bytes(_pdf_zip())
    assert "erreur" in o.deposer_dossier(chemin=str(dossier))  # sans CONTROLDONE_MCP_RACINE (RS-02)
    r = _outils(monde, A, racine_autorisee=tmp_path).deposer_dossier(chemin=str(dossier))
    assert r["fichiers_acceptes"] == 1
    assert "erreur" in o.deposer_dossier(contenu_base64="pas du base64 !!")
    assert "erreur" in o.deposer_dossier()
    restreint = _outils(monde, A, racine_autorisee=tmp_path / "ailleurs")
    assert "erreur" in restreint.deposer_dossier(chemin=str(dossier))


def test_mcp_litiges(monde):
    o = _outils(monde, A)
    litiges = o.suivre_litige()["litiges"]
    ouvert = next(x for x in litiges if x["statut"] == "ouvert")
    r = o.enregistrer_evenement_litige(ouvert["litige_id"], "reclamation_envoyee")
    assert r["litiges"][0]["statut"] == "reclame"
    assert "erreur" in o.enregistrer_evenement_litige(ouvert["litige_id"], "autre")
    ob = _outils(monde, B)
    assert ob.suivre_litige(ouvert["litige_id"]) == {"erreur": "introuvable"}
    assert ob.enregistrer_evenement_litige(ouvert["litige_id"], "reclamation_envoyee") == {
        "erreur": "introuvable"
    }


def test_mcp_serveur_declare_les_outils(monde):
    serveur = construire_serveur(_outils(monde, A))
    outils = anyio.run(serveur.list_tools)
    noms = {t.name for t in outils}
    assert noms == {
        "deposer_dossier",
        "lire_lot",
        "lire_dossier",
        "lire_ecarts",
        "suivre_litige",
        "enregistrer_evenement_litige",
    }
    for t in outils:
        assert "pas un avis juridique" in t.description and "données" in t.description
        assert check_text(t.description) == []


def test_mcp_refuse_un_acteur_non_client(monde):
    from controldone.auth.roles import Acteur, Role

    with pytest.raises(PermissionError):
        OutilsControldone(monde.pf, Acteur("usr_fondateur_demo", Role.fondateur))


# --- garde-fous sur les pages rendues ---------------------------------------------------------------------------


def _verifier(page, avertissement: bool = True) -> None:
    """Garde-fous du texte affiché ; ``avertissement`` : l'avertissement exact est au pied (pages du client, pages
    du fondateur qui montrent des constats) ou absent (autres pages du fondateur, pied neutre)."""
    assert page.status_code == 200, page.text[:300]
    texte = texte_visible(page.text)
    assert check_text(texte) == [], check_text(texte)[:3]
    assert (AVERTISSEMENT in texte) == avertissement


def test_garde_fous_pages_fondateur(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    urls = [
        "/admin",
        "/admin/clients",
        f"/admin/clients/{A}",
        f"/admin/clients/{B}",
        "/admin/validation",
        "/admin/jobs",
        "/admin/journal",
        "/admin/alertes",
        "/admin/autonomie",
        "/compte/mot-de-passe",
    ]
    for url in urls:
        _verifier(f.get(url), avertissement=url == "/admin/validation")
    for url in [f"/admin/clients/{t}/dossiers/{d}" for t in (A, B) for d in monde.ids[t]["dossier"]]:
        _verifier(f.get(url))  # constats affichés : avertissement exact au pied
    assert "DONNÉES FICTIVES" in f.get(f"/admin/clients/{A}").text


def test_garde_fous_pages_client(monde):
    for email, tenant in ((ADMIN_A, A), (ADMIN_B, B)):
        c = monde.client()
        connecter_client(c, monde, email)
        urls = [
            "/espace",
            "/espace/depot",
            "/espace/dossiers",
            "/espace/rapports",
            "/espace/recouvrement",
            f"/espace/lots/{monde.ids[tenant]['lot'][0]}",
        ]
        urls += [f"/espace/dossiers/{d}" for d in monde.ids[tenant]["dossier"]]
        for url in urls:
            page = c.get(url)
            _verifier(page)
            assert "DONNÉES FICTIVES" in page.text


def test_garde_fous_pages_publiques(monde):
    c = monde.client()
    for url in ("/connexion", "/api/v1/docs"):
        page = c.get(url)
        assert check_text(texte_visible(page.text)) == []
        assert AVERTISSEMENT in texte_visible(page.text)
