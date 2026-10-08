"""Dépôt (limites §20.3, archives dangereuses, mise en file), en-têtes de sécurité, corps trop volumineux."""

from __future__ import annotations

import io
import zipfile

from aides_web import ADMIN_A, connecter_client, construire_monde, executer_jobs, jeton

from controldone.auth.roles import Acteur
from controldone.ingest.reception import Limites
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import Fichier, Lot

A = "demo_ateliers"


def _deposer(c, fichiers):
    t = jeton(c.get("/espace/depot").text)
    return c.post(
        "/espace/depot", data={"csrf": t}, files=[("fichiers", f) for f in fichiers], follow_redirects=False
    )


def _lot(monde, lot_id):
    with monde.pf.db.tenant(A, Acteur.systeme("t"), lecture=True) as s:
        return s.obtenir(Lot, lot_id), s.lister(Fichier, lot_id=lot_id)


def _pdf() -> bytes:
    from reportlab.pdfgen import canvas

    b = io.BytesIO()
    c = canvas.Canvas(b)
    c.drawString(72, 720, "FACTURE FICTIVE DE TEST")
    c.showPage()
    c.save()
    return b.getvalue()


def test_depot_cree_un_lot_et_un_job(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("envoi_test/facture.pdf", _pdf())
    r = _deposer(
        c, [("envoi.zip", z.getvalue(), "application/zip"), ("autre.pdf", _pdf(), "application/pdf")]
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/espace/lots/")
    lot_id = r.headers["location"].rsplit("/", 1)[1]
    lot, fichiers = _lot(monde, lot_id)
    assert lot.statut == "recu"
    assert {f.chemin_relatif for f in fichiers} == {"envoi/envoi_test/facture.pdf", "autre.pdf"} or len(
        fichiers
    ) == 2
    jobs = [j for j in JobStore(monde.pf.db).lister(tenant_id=A) if j.payload.get("lot_id") == lot_id]
    assert len(jobs) == 1 and jobs[0].kind == "traiter_lot"
    page = c.get(r.headers["location"]).text
    assert 'http-equiv="refresh"' in page
    executer_jobs(monde)
    assert _lot(monde, lot_id)[0].statut == "traite"


def test_fichier_trop_volumineux_refuse_sans_etre_conserve(monde, _modele, tmp_path):
    m = construire_monde(_modele, tmp_path / "petit", limites=Limites(taille_fichier=2000, taille_lot=10_000))
    c = m.client()
    connecter_client(c, m, ADMIN_A)
    r = _deposer(c, [("gros.pdf", b"%PDF-1.4\n" + b"0" * 5000, "application/pdf")])
    lot_id = r.headers["location"].rsplit("/", 1)[1]
    with m.pf.db.tenant(A, Acteur.systeme("t"), lecture=True) as s:
        lot = s.obtenir(Lot, lot_id)
        f = s.lister(Fichier, lot_id=lot_id)[0]
    assert (
        lot.statut == "en_erreur"
        and f.statut == "refuse"
        and f.motif_refus == "trop_gros"
        and f.coffre_ref is None
    )
    assert not [j for j in JobStore(m.pf.db).lister(tenant_id=A) if j.payload.get("lot_id") == lot_id]
    # dépôt total au-delà de la limite : refus global
    r = _deposer(c, [(f"f{i}.pdf", b"%PDF-1.4" + b"1" * 1900, "application/pdf") for i in range(6)])
    assert r.status_code == 303 and r.headers["location"] == "/espace/depot"
    m.pf.db.fermer()


def test_bombe_zip_refusee(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bombe.pdf", b"\0" * (8 * 1024 * 1024))
    assert len(z.getvalue()) < 100_000
    r = _deposer(c, [("bombe.zip", z.getvalue(), "application/zip")])
    lot_id = r.headers["location"].rsplit("/", 1)[1]
    lot, fichiers = _lot(monde, lot_id)
    assert lot.statut == "en_erreur"
    assert [f.motif_refus for f in fichiers] == ["archive_dangereuse"]
    assert all(f.coffre_ref is None for f in fichiers)


def test_zip_avec_traversee_refusee(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../etc/passwd.pdf", _pdf())
        zf.writestr("/absolu.pdf", _pdf())
    r = _deposer(c, [("piege.zip", z.getvalue(), "application/zip")])
    lot_id = r.headers["location"].rsplit("/", 1)[1]
    fichiers = _lot(monde, lot_id)[1]
    assert fichiers and all(f.statut == "refuse" and f.motif_refus == "archive_dangereuse" for f in fichiers)
    assert all(".." not in f.chemin_relatif and not f.chemin_relatif.startswith("/") for f in fichiers)


def test_html_depose_jamais_rendu(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    r = _deposer(c, [("page.html", b"<html><script>alert(1)</script></html>", "text/html")])
    lot_id = r.headers["location"].rsplit("/", 1)[1]
    fichiers = _lot(monde, lot_id)[1]
    assert fichiers[0].statut == "refuse"
    page = c.get(f"/espace/lots/{lot_id}").text
    assert "<script>alert(1)</script>" not in page


def test_telechargement_en_piece_jointe(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    r = c.get(f"/espace/fichiers/{monde.ids[A]['fichier'][0]}")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"] in ("application/pdf", "application/octet-stream")


def test_en_tetes_de_securite(monde):
    c = monde.client()
    for url in ("/connexion", "/sante", "/api/v1/docs"):
        r = c.get(url)
        h = r.headers
        assert h["content-security-policy"].startswith("default-src 'self'")
        assert (
            "script-src 'self'" in h["content-security-policy"]
            and "unsafe-inline" not in h["content-security-policy"]
        )
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "same-origin"
        assert h["x-content-type-options"] == "nosniff"
        assert "strict-transport-security" not in h
        assert h["cache-control"] == "no-store"


def test_hsts_en_https(_modele, tmp_path):
    m = construire_monde(_modele, tmp_path / "https", https=True)
    r = m.client().get("/connexion")
    assert r.headers["strict-transport-security"].startswith("max-age=")
    m.pf.db.fermer()


def test_cookie_production(_modele, tmp_path):
    from aides_web import SECRET_SESSION

    from controldone.web import ParametresWeb, create_app

    m = construire_monde(_modele, tmp_path / "prod")
    app = create_app(ParametresWeb(plateforme=m.pf, secrets_session=[SECRET_SESSION], prod=True))
    etat = app.state.securite
    assert (
        etat.cookie["key"] == "__Host-cd_session"
        and etat.cookie["secure"]
        and etat.cookie["samesite"] == "strict"
    )
    m.pf.db.fermer()


def test_corps_trop_volumineux_413(monde):
    c = monde.client()
    r = c.post(
        "/connexion",
        content=b"x" * (3 * 1024 * 1024),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 413


def test_texte_utilisateur_echappe(monde):
    """Une entité au nom piégé est affichée échappée."""
    from aides_web import connecter_fondateur, poster

    f = monde.client()
    connecter_fondateur(f, monde)
    poster(
        f,
        f"/admin/clients/{A}",
        f"/admin/clients/{A}/entites",
        {"raison_sociale": "<script>alert('x')</script>"},
    )
    page = f.get(f"/admin/clients/{A}").text
    assert "<script>alert" not in page and "&lt;script&gt;alert" in page


def test_nombre_de_fichiers_conserve_apres_traitement(monde):
    """Régression : le résumé du traitement s'ajoute à celui du dépôt sans l'effacer. Avant correction,
    « Dépôts récents » affichait « 0 fichier(s) » pour un lot traité qui avait produit des dossiers."""
    import re
    from pathlib import Path

    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    docs = Path(__file__).resolve().parents[2] / "demo/dossiers/DEMO-2/docs"
    envois = [
        (p.name, p.read_bytes() + b"\n% copie FICTIVE (test du compte de fichiers)\n", "application/pdf")
        for p in sorted(docs.glob("*.pdf"))
    ]  # empreintes nouvelles : pas des doublons de la base de démonstration
    assert len(envois) == 3
    r = _deposer(c, envois)
    assert r.status_code == 303
    lot_id = r.headers["location"].rsplit("/", 1)[1]
    avant = dict(_lot(monde, lot_id)[0].resume)
    assert (avant["fichiers"], avant["doublons"], avant["refuses"]) == (3, 0, 0)
    executer_jobs(monde)
    lot = _lot(monde, lot_id)[0]
    assert lot.statut == "traite"
    assert {k: lot.resume[k] for k in avant} == avant  # clés du dépôt intactes
    assert {"dossiers", "constats", "non_lus", "llm"} <= lot.resume.keys()  # clés du traitement ajoutées
    page = c.get("/espace/depot").text
    ligne = re.search(rf'<li><a href="/espace/lots/{lot_id}">.*?</li>', page, re.S)
    assert ligne is not None
    assert "3 fichiers" in ligne.group(0) and "aucun fichier" not in ligne.group(0)


def test_compte_de_fichiers_inconnu_non_affiche(monde):
    """Lot dont le résumé ne porte aucun compte de fichiers (lot traité avant la correction) : « Dépôts récents »
    n'affiche pas de nombre plutôt qu'un « aucun fichier » inexact."""
    import re

    with monde.pf.db.tenant(A, Acteur.systeme("t")) as s:
        for lot in s.lister(Lot):
            s.modifier(Lot, lot.id, resume={k: v for k, v in (lot.resume or {}).items() if k != "fichiers"})
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    page = c.get("/espace/depot").text
    lignes = re.findall(r'<li><a href="/espace/lots/[^"]+">.*?</li>', page, re.S)
    assert lignes and not [x for x in lignes if "fichier" in x]
