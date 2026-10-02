"""Accès croisés : chaque route de l'espace client et chaque point de l'API, avec les identifiants d'un autre
client, répond exactement comme pour un identifiant inexistant (404) ; un rôle client n'atteint aucune route
du fondateur ; seuls les constats publiés sont visibles."""

from __future__ import annotations

import pytest
from aides_web import ADMIN_A, ADMIN_B, LECTEUR_A, connecter_client, jeton

A, B = "demo_ateliers", "demo_nord"
INEXISTANT = "x_00000000000000000000000000000000"


def _routes_get(ids: dict[str, list[str]]) -> list[str]:
    return [
        f"/espace/dossiers/{ids['dossier'][0]}",
        f"/espace/documents/{ids['document'][0]}/pages/1.png",
        f"/espace/fichiers/{ids['fichier'][0]}",
        f"/espace/lots/{ids['lot'][0]}",
        f"/espace/rapports/{ids['sortie_envoyee'][0]}/pdf",
    ]


def _remplacer(url: str) -> str:
    morceaux = url.split("/")
    for i, m in enumerate(morceaux):
        if "_" in m and not m.endswith(".png") and m not in ("espace",):
            morceaux[i] = INEXISTANT
    return "/".join(morceaux)


@pytest.mark.parametrize("i", range(5))
def test_routes_client_autre_client_404_comme_inexistant(monde, i):
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)  # client B tente les identifiants de A
    url = _routes_get(monde.ids[A])[i]
    r_etranger = c.get(url)
    r_inexistant = c.get(_remplacer(url))
    assert r_etranger.status_code == 404
    assert r_inexistant.status_code == 404
    assert "Page introuvable" in r_etranger.text and "Page introuvable" in r_inexistant.text
    assert monde.ids[A]["dossier"][0] not in r_etranger.text


def test_routes_client_propres_identifiants_accessibles(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    ids = monde.ids[A]
    assert c.get(f"/espace/dossiers/{ids['dossier'][0]}").status_code == 200
    assert c.get(f"/espace/documents/{ids['document'][0]}/pages/1.png").headers["content-type"] == "image/png"
    r = c.get(f"/espace/fichiers/{ids['fichier'][0]}")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")
    assert c.get(f"/espace/lots/{ids['lot'][0]}").status_code == 200


@pytest.mark.parametrize("action", ["reclame", "avoir"])
def test_post_recouvrement_croise_404(monde, action):
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)
    t = jeton(c.get("/espace/recouvrement").text)
    ecart_a = monde.ids[A]["ecart"][0]
    r1 = c.post(f"/espace/recouvrement/{ecart_a}/{action}", data={"csrf": t, "montant": "10"}, follow_redirects=False)
    r2 = c.post(f"/espace/recouvrement/{INEXISTANT}/{action}", data={"csrf": t, "montant": "10"},
                follow_redirects=False)
    assert r1.status_code == r2.status_code == 404


def test_parametre_client_ignore(monde):
    """Le client vient de la session : un paramètre ``tenant_id`` ne change rien."""
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)
    r = c.get(f"/espace/dossiers?tenant_id={A}&client={A}")
    assert r.status_code == 200
    for d in monde.ids[A]["dossier"]:
        assert d not in r.text


ROUTES_FONDATEUR_GET = ["/admin", "/admin/clients", f"/admin/clients/{A}", "/admin/validation", "/admin/jobs",
                        "/admin/journal", "/admin/alertes", "/admin/autonomie"]


@pytest.mark.parametrize("url", ROUTES_FONDATEUR_GET)
def test_client_n_atteint_pas_les_routes_du_fondateur(monde, url):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    assert c.get(url).status_code == 404


def test_client_ne_peut_pas_valider(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    t = jeton(c.get("/espace").text)
    cid = (monde.ids[A]["constat_propose"] or monde.ids[A]["constat"])[0]
    r = c.post(f"/admin/clients/{A}/constats/{cid}/valider", data={"csrf": t}, follow_redirects=False)
    assert r.status_code == 404
    r = c.post(f"/admin/clients/{A}/publier", data={"csrf": t}, follow_redirects=False)
    assert r.status_code == 404


def test_lecteur_ne_depose_pas(monde):
    c = monde.client()
    connecter_client(c, monde, LECTEUR_A)
    t = jeton(c.get("/espace/depot").text)
    r = c.post("/espace/depot", data={"csrf": t}, files={"fichiers": ("a.pdf", b"%PDF-1.4", "application/pdf")},
               follow_redirects=False)
    assert r.status_code == 403


# --- publication (§4) ------------------------------------------------------------------------------------------


def test_client_ne_voit_que_les_constats_publies(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    ids = monde.ids[A]
    textes = "".join(c.get(f"/espace/dossiers/{d}").text for d in ids["dossier"])
    for cid in ids["constat_valide"]:
        assert f"constat-{cid}" in textes
    for cid in ids["constat_propose"]:
        assert f"constat-{cid}" not in textes
    # client B : tous ses constats sont encore proposés -> aucun constat visible
    cb = monde.client()
    connecter_client(cb, monde, ADMIN_B)
    for d in monde.ids[B]["dossier"]:
        page = cb.get(f"/espace/dossiers/{d}").text
        assert 'class="constat ' not in page
        assert "Aucun constat publié" in page


# --- API ------------------------------------------------------------------------------------------------------


def _api(monde, tenant):
    c = monde.client()
    c.headers["Authorization"] = f"Bearer {monde.cles[tenant]}"
    return c


def _routes_api(ids):
    return [
        ("get", f"/api/v1/lots/{ids['lot'][0]}"),
        ("get", f"/api/v1/dossiers/{ids['dossier'][0]}"),
        ("get", f"/api/v1/dossiers/{ids['dossier'][0]}/constats"),
        ("get", f"/api/v1/rapports/{ids['sortie_envoyee'][0]}"),
        ("get", f"/api/v1/litiges/{ids['ecart'][0]}"),
        ("post", f"/api/v1/litiges/{ids['ecart'][0]}/evenements"),
    ]


@pytest.mark.parametrize("i", range(6))
def test_api_autre_client_404_identique(monde, i):
    c = _api(monde, B)
    methode, url = _routes_api(monde.ids[A])[i]
    corps = {"json": {"type": "reclamation_envoyee"}} if methode == "post" else {}
    r1 = getattr(c, methode)(url, **corps)
    r2 = getattr(c, methode)(_remplacer(url), **corps)
    assert r1.status_code == 404 and r2.status_code == 404, (r1.text, r2.text)
    assert r1.json() == r2.json() == {"detail": "introuvable"}


def test_api_sans_cle_401(monde):
    c = monde.client()
    for url in ("/api/v1/dossiers", "/api/v1/litiges", "/api/v1/rapports"):
        r = c.get(url)
        assert r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer"
    c.headers["Authorization"] = "Bearer cdk_abc_faux"
    assert c.get("/api/v1/dossiers").status_code == 401


def test_api_liste_ne_contient_que_le_client_de_la_cle(monde):
    r = _api(monde, B).get("/api/v1/dossiers")
    assert r.status_code == 200, r.text
    rb = r.json()
    assert {d["dossier_id"] for d in rb} == set(monde.ids[B]["dossier"])
    # constats : publiés seulement
    for d in monde.ids[B]["dossier"]:
        assert _api(monde, B).get(f"/api/v1/dossiers/{d}/constats").json()["constats"] == []
    ra = _api(monde, A)
    vus = {c["constat_id"] for d in monde.ids[A]["dossier"]
           for c in ra.get(f"/api/v1/dossiers/{d}/constats").json()["constats"]}
    assert vus == set(monde.ids[A]["constat_valide"])
