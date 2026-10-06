"""Bloc E (interface) : recherche, filtres, tri, pagination (D-3401), suivi en direct des dépôts (D-3402),
graphiques des tableaux de bord (D-3403). Données fictives de la base de démonstration."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from aides_web import ADMIN_A, ADMIN_B, LECTEUR_A, connecter_client, connecter_fondateur, jeton
from starlette.datastructures import QueryParams

from controldone.services.plateforme import RequeteInvalide
from controldone.storage.file_jobs import JobStore
from controldone.web.listes import Param, lire_requete, paginer
from controldone.web.suivi import etat_traitement

A, B = "demo_ateliers", "demo_nord"
INEXISTANT = "lot_00000000000000000000000000000000"


def _refs(html: str) -> list[str]:
    return re.findall(r'<th scope="row"><a href="[^"]+">(D-\d{4}-\d{5})</a>', html)


# --- module listes ---------------------------------------------------------------------------------------------


class _Req:
    def __init__(self, qs: str) -> None:
        self.query_params = QueryParams(qs)


PARAMS = {"q": Param("Recherche"), "statut": Param("Statut", "choix", ("a", "b")), "min": Param("Min", "montant"),
          "du": Param("Du", "date")}


def test_lire_requete_valide_et_urls():
    r = lire_requete(_Req("q=%20MRN%20&statut=a&min=1%20234,50&tri=-x&page=2&taille=50&inconnu=1"), PARAMS,
                     ("x", "-x"), "x")
    assert r.filtres["q"] == "MRN" and r.filtres["statut"] == "a" and str(r.filtres["min"]) == "1234.50"
    assert r.page == 2 and r.taille == 50 and r.tri == "-x" and r.actif
    # un changement de filtre ou de tri ramène à la page 1 ; le paramètre inconnu n'est jamais réémis
    assert "page" not in r.url(statut="b") and "inconnu" not in r.url(page=3)
    assert "page=3" in r.url(page=3) and r.url_tri("x").count("tri=") == 0  # -x -> x (tri par défaut)
    assert r.sens("x") == "descending"


@pytest.mark.parametrize("qs", ["statut=zzz", "taille=7", "taille=1000", "page=0", "page=abc", "page=99999999",
                                "tri=nimporte", "q=" + "x" * 81, "q=a%00b", "min=1e9", "min=-5", "du=2026-13-01",
                                "statut=a&statut=b"])
def test_lire_requete_refuse(qs):
    with pytest.raises(RequeteInvalide):
        lire_requete(_Req(qs), PARAMS, ("x", "-x"), "x")


def test_paginer_borne_la_page():
    r = lire_requete(_Req("page=9"), PARAMS, ("x",), "x")
    p = paginer(list(range(60)), r)
    assert p.page == 3 and p.pages == 3 and p.elements == list(range(50, 60)) and p.debut == 51 and p.fin == 60
    assert p.numeros == [1, 2, 3]


# --- dossiers du client ---------------------------------------------------------------------------------------


def test_dossiers_client_recherche_filtre_tri(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    tous = _refs(c.get("/espace/dossiers").text)
    assert len(tous) == 3 and tous == sorted(tous)
    assert _refs(c.get("/espace/dossiers?tri=-reference").text) == sorted(tous, reverse=True)
    r = c.get("/espace/dossiers?q=00002")
    assert _refs(r.text) == [tous[1]] and "1 dossier (filtré)" in r.text
    assert _refs(c.get("/espace/dossiers?q=26frd3fic").text) == [tous[2]]  # MRN, insensible à la casse
    assert _refs(c.get("/espace/dossiers?statut=conforme").text) == [tous[2]]
    vide = c.get("/espace/dossiers?q=introuvable")
    assert _refs(vide.text) == [] and "Aucun dossier ne correspond" in vide.text
    # pagination bornée : page au-delà de la dernière -> dernière page
    assert _refs(c.get("/espace/dossiers?page=40").text) == tous


@pytest.mark.parametrize("qs", ["statut=inconnu", "taille=10", "tri=drop%20table", "page=-1"])
def test_dossiers_client_parametres_invalides_400(monde, qs):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    r = c.get("/espace/dossiers?" + qs)
    assert r.status_code == 400 and "Requête invalide" in r.text


def test_dossiers_client_cloisonnement(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)
    refs_b = _refs(c.get("/espace/dossiers").text)
    html = c.get("/espace/dossiers?q=").text
    for d in monde.ids[A]["dossier"]:
        assert d not in html
    assert len(refs_b) == 2
    # une recherche sur une clé du client A ne remonte rien chez B
    assert _refs(c.get("/espace/dossiers?q=26FRD1FIC000004711").text) == []


def test_recouvrement_filtres_et_transitaire_d_un_autre_client(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    page = c.get("/espace/recouvrement").text
    ids_tr = re.findall(r'<option value="([^"]+)"', page.split('name="transitaire"')[1].split("</select>")[0])
    ids_tr = [x for x in ids_tr if x]
    assert ids_tr
    assert c.get(f"/espace/recouvrement?transitaire={ids_tr[0]}").status_code == 200
    assert "Aucun écart ne correspond" in c.get("/espace/recouvrement?statut=credite").text
    assert c.get("/espace/recouvrement?tri=-montant&taille=50").status_code == 200
    # B ne peut pas filtrer sur un transitaire de A : valeur hors liste fermée -> 400, rien n'est lu
    cb = monde.client()
    connecter_client(cb, monde, ADMIN_B)
    assert cb.get(f"/espace/recouvrement?transitaire={ids_tr[0]}").status_code == 400


# --- fondateur ----------------------------------------------------------------------------------------------------


def test_file_validation_filtres(monde):
    c = monde.client()
    connecter_fondateur(c, monde)
    tout = c.get("/admin/validation").text
    n = len(re.findall(r'<article class="constat', tout))
    assert n == 3 and "3 constats proposés." in tout
    assert len(re.findall(r'<article class="constat', c.get(f"/admin/validation?client={B}").text)) == 2
    assert len(re.findall(r'<article class="constat', c.get("/admin/validation?niveau=ecart_certain").text)) == 1
    assert len(re.findall(r'<article class="constat', c.get("/admin/validation?controle=A12").text)) == 2
    assert len(re.findall(r'<article class="constat', c.get("/admin/validation?min=10&max=30").text)) == 1
    vide = c.get("/admin/validation?min=1000000")
    assert "Aucun constat ne correspond" in vide.text
    for qs in ("client=x_inconnu", "controle=Z9", "niveau=autre", "min=abc", "tri=reference"):
        assert c.get("/admin/validation?" + qs).status_code == 400, qs
    # pagination : 1 par page n'est pas permis (25, 50, 100)
    assert c.get("/admin/validation?taille=1").status_code == 400


def test_fiche_client_dossiers_filtres(monde):
    c = monde.client()
    connecter_fondateur(c, monde)
    r = c.get(f"/admin/clients/{A}?q=00003")
    assert r.status_code == 200 and _refs(r.text) == ["D-2026-00003"]
    assert c.get(f"/admin/clients/{A}?statut=autre").status_code == 400


def test_journal_filtres_pagination(monde):
    c = monde.client()
    connecter_fondateur(c, monde)
    r = c.get("/admin/journal")
    assert r.status_code == 200 and re.search(r"1–25 sur \d+ entrées", r.text)
    ids = [int(x) for x in re.findall(r'<tr><td class="num">(\d+)</td>', r.text)]
    assert len(ids) == 25 and ids == sorted(ids, reverse=True)
    p2 = [int(x) for x in re.findall(r'<tr><td class="num">(\d+)</td>', c.get("/admin/journal?page=2").text)]
    assert p2 and max(p2) < min(ids)
    asc = [int(x) for x in re.findall(r'<tr><td class="num">(\d+)</td>', c.get("/admin/journal?tri=id").text)]
    assert asc == sorted(asc) and asc[0] == 1
    connexions = c.get("/admin/journal?action=connexion&taille=100").text
    actions = re.findall(r"</span></td><td>([a-z_]+)</td>", connexions)
    assert actions and set(actions) == {"connexion"}
    # « % » et « _ » sont échappés : aucune entrée, pas d'erreur
    assert "Aucune entrée ne correspond" in c.get("/admin/journal?acteur=%25").text
    assert c.get("/admin/journal?action=pas_une_action").status_code == 400
    assert c.get("/admin/journal?du=2026-02-30").status_code == 400
    assert "Aucune entrée ne correspond" in c.get("/admin/journal?au=2001-01-01").text


def test_jobs_filtres(monde):
    c = monde.client()
    connecter_fondateur(c, monde)
    r = c.get("/admin/jobs?statut=done&kind=traiter_lot")
    assert r.status_code == 200 and r.text.count("<code>traiter_lot</code>") == 2
    assert "Aucune tâche ne correspond" in c.get("/admin/jobs?statut=dead").text
    assert c.get("/admin/jobs?statut=zombie").status_code == 400
    assert c.get(f"/admin/jobs?client={A}").text.count("<code>traiter_lot</code>") == 1


def test_listes_fondateur_inaccessibles_au_client(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    for url in ("/admin/journal?page=2", "/admin/jobs?statut=done", "/admin/validation?client=demo_nord",
                "/admin/jobs/etat"):
        assert c.get(url).status_code == 404, url


# --- suivi en direct -------------------------------------------------------------------------------------------------


def test_etat_traitement_etapes():
    assert etat_traitement("recu", None)["etape"] == "recu"
    assert etat_traitement("recu", {"statut": "pending", "essais": 0})["detail"] == "En attente de traitement."
    assert etat_traitement("recu", {"statut": "running", "etape": "controles"})["etape"] == "controles"
    assert etat_traitement("recu", {"statut": "running", "etape": "<script>"})["etape"] == "lecture"
    e = etat_traitement("recu", {"statut": "dead"})
    assert e["erreur"] and e["fini"] and e["etape"] == "erreur"
    assert etat_traitement("traite", {"statut": "running"})["etape"] == "termine"
    assert etat_traitement("en_erreur", None)["erreur"]


def test_point_de_suivi_lot(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    lot = monde.ids[A]["lot"][0]
    r = c.get(f"/espace/lots/{lot}/etat")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["lot_id"] == lot and d["etape"] == "termine" and d["fini"] and d["dossiers"] == 3
    assert set(d) == {"lot_id", "etape", "libelle", "rang", "fini", "erreur", "pourcentage", "detail", "dossiers",
                      "fichiers"}
    lecteur = monde.client()
    connecter_client(lecteur, monde, LECTEUR_A)
    assert lecteur.get(f"/espace/lots/{lot}/etat").status_code == 200
    s = c.get("/espace/suivi").json()
    assert [x["lot_id"] for x in s["lots"]] == monde.ids[A]["lot"]


def test_point_de_suivi_cloisonne(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)
    etranger = c.get(f"/espace/lots/{monde.ids[A]['lot'][0]}/etat")
    inexistant = c.get(f"/espace/lots/{INEXISTANT}/etat")
    assert etranger.status_code == inexistant.status_code == 404
    assert etranger.json() == inexistant.json() == {"erreur": "introuvable"}
    s = c.get("/espace/suivi").json()
    assert {x["lot_id"] for x in s["lots"]} == set(monde.ids[B]["lot"])
    anonyme = monde.client()
    assert anonyme.get(f"/espace/lots/{monde.ids[A]['lot'][0]}/etat", follow_redirects=False).status_code in (303, 401)


def test_point_de_suivi_limite_de_debit(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    lot = monde.ids[A]["lot"][0]
    codes = [c.get(f"/espace/lots/{lot}/etat").status_code for _ in range(40)]
    assert codes[0] == 200 and 429 in codes
    r = c.get(f"/espace/lots/{lot}/etat")
    assert r.status_code == 429 and r.headers["retry-after"] == "5"


def test_depot_suivi_etapes_et_page(monde):
    """Un dépôt neuf : « reçu » (la page s'actualise sans script) ; l'étape courante écrite par le worker qui
    détient le bail est relue par le point de suivi ; un échec réessayable revient à « reçu »."""
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    t = jeton(c.get("/espace/depot").text)
    source = Path(__file__).resolve().parents[2] / "demo/dossiers/DEMO-2/docs/facture_commerciale_INV-FIC-0202.pdf"
    contenu = source.read_bytes() + b"\n% copie FICTIVE pour le test de suivi\n"  # empreinte nouvelle : pas un doublon
    r = c.post("/espace/depot", data={"csrf": t}, files=[("fichiers", ("FICTIF.pdf", contenu, "application/pdf"))],
               follow_redirects=False)
    assert r.status_code == 303
    url = r.headers["location"]
    page = c.get(url).text
    assert 'aria-current="step"' in page and 'http-equiv="refresh"' in page and "data-suivi=" in page
    lot_id = url.rsplit("/", 1)[1]
    assert c.get(url + "/etat").json()["etape"] == "recu"
    # étape « lecture » écrite par un worker qui détient le bail
    store = JobStore(monde.pf.db)
    job = store.reserver("w-test", lease_s=60)
    assert job is not None and job.payload.get("lot_id") == lot_id
    assert store.marquer_etape(job.id, "w-test", "lecture", tentative=job.attempts)
    assert not store.marquer_etape(job.id, "autre-worker", "controles")
    assert c.get(url + "/etat").json()["etape"] == "lecture"
    store.echouer(job.id, "w-test", "essai", tentative=job.attempts)  # nouvel essai dans 30 s
    d = c.get(url + "/etat").json()
    assert d["etape"] == "recu" and d["detail"] == "Nouvel essai programmé." and not d["fini"]
    assert 'http-equiv="refresh"' in c.get(url).text


# --- graphiques ----------------------------------------------------------------------------------------------------


def test_graphes_tableaux_de_bord(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    html = c.get("/espace").text
    assert html.count('role="img"') == 3 and html.count("<desc id=") == 3
    assert "Montant recouvrable certain par transitaire" in html and "Données du graphique" in html
    assert ' style="' not in html  # CSP : aucun attribut style
    f = monde.client()
    connecter_fondateur(f, monde)
    h = f.get("/admin").text
    assert "Constats à valider par famille de contrôles" in h and "Traitements des dépôts" in h
    assert ' style="' not in h
    e = f.get("/admin/jobs/etat").json()
    assert e["compte"]["done"] == 2 and len(e["lots"]) == 2 and all(x["fini"] for x in e["lots"])
