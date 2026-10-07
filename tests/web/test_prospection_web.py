"""Interface du module « Marketing » (``/admin/prospection``, D-5001 à D-5012) : fondateur seulement (404 pour un
compte client, connexion exigée), CSRF sur chaque POST, pages dans les deux langues sans formulation interdite,
parcours complet (saisie, import, recherche par un double, séquence, validation, envoi déclaré, réponse) et
désinscription publique. Sociétés FICTIVES (démonstration ``prs_demo_*``)."""

from __future__ import annotations

import re
from html import escape

import pytest
from aides_web import ADMIN_A, connecter_client, connecter_fondateur, jeton
from test_interface_bloc_i4 import _francais

from controldone.guardrails import check_text
from controldone.outbox import FileSortante, StatutAction
from controldone.prospection import contacts as adr
from controldone.prospection import jetons
from controldone.prospection.recherche import CandidatEntreprise, ResultatRecherche
from controldone.web import routes_prospection
from controldone.web.i18n import COOKIE_LANGUE
from controldone.web.rendu import texte_visible

B = "/admin/prospection"
PAGES = [
    B,
    f"{B}/prospects",
    f"{B}/prospects?statut=qualifie&score=40&tri=nom",
    f"{B}/pipeline",
    f"{B}/prospects/prs_demo_1",
    f"{B}/prospects/prs_demo_2",
    f"{B}/prospects/prs_demo_5",
    f"{B}/importer",
    f"{B}/rechercher",
    f"{B}/sequences",
    f"{B}/courriels",
    f"{B}/opposition",
    f"{B}/delivrabilite",
]
SIREN = "732829320"


def _routes() -> list[tuple[str, str]]:
    sortie = []
    for r in routes_prospection.routeur.routes:
        for m in sorted(r.methods or ()):
            if m in ("GET", "POST"):
                sortie.append((m, re.sub(r"\{[^}]+\}", "x_fictif", r.path)))
    return sortie


@pytest.fixture
def identite(monkeypatch):
    for k, v in {
        "CONTROLDONE_PROSPECTION_EXPEDITEUR_NOM": "Prénom Nom FICTIF",
        "CONTROLDONE_VENDEUR_SIREN": "123456782",
        "CONTROLDONE_VENDEUR_ADRESSE_LIGNE": "1 rue Fictive",
        "CONTROLDONE_VENDEUR_CODE_POSTAL": "75001",
        "CONTROLDONE_VENDEUR_VILLE": "Paris",
    }.items():
        monkeypatch.setenv(k, v)


def _fondateur(monde, langue="fr"):
    c = monde.client()
    c.cookies.set(COOKIE_LANGUE, langue)
    connecter_fondateur(c, monde)
    return c


def _poster(c, page, url, donnees=None, **kw):
    t = jeton(c.get(page).text)
    return c.post(url, data={"csrf": t, **(donnees or {})}, follow_redirects=False, **kw)


def _flash(c, url="/admin/prospection") -> str:
    return texte_visible(c.get(url).text)


# --- accès ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("langue", ["fr", "en"])
def test_pages_du_fondateur_dans_les_deux_langues(monde, langue):
    c = _fondateur(monde, langue)
    for url in PAGES:
        r = c.get(url)
        assert r.status_code == 200, (url, r.status_code)
        assert '<link rel="stylesheet" href="/static/prospection.css">' in r.text
        texte = texte_visible(r.text)
        assert check_text(texte) == [], (url, check_text(texte)[:2])
        if langue == "en":
            assert _francais(r.text) == [], (url, _francais(r.text)[:5])
    assert "/static/prospection.css" not in c.get("/admin").text  # feuille chargée sur ces pages seulement
    assert 'href="/admin/prospection"' in c.get("/admin").text  # entrée de navigation


def test_client_recoit_404_partout_et_anonyme_redirige(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    t = jeton(c.get("/espace").text)
    routes = _routes()
    assert len(routes) >= 25
    for methode, url in routes:
        r = c.get(url) if methode == "GET" else c.post(url, data={"csrf": t}, follow_redirects=False)
        assert r.status_code == 404, (methode, url, r.status_code)
    assert "Marketing" not in c.get("/espace").text
    anonyme = monde.client()
    for methode, url in routes:
        if methode == "GET":
            r = anonyme.get(url, follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/connexion", url


def test_chaque_post_exige_le_jeton_csrf(monde):
    c = _fondateur(monde)
    for methode, url in _routes():
        if methode == "POST":
            for donnees in ({}, {"csrf": "faux.jeton"}):
                assert c.post(url, data=donnees, follow_redirects=False).status_code == 403, url


# --- parcours ---------------------------------------------------------------------------------------------------


def test_saisie_exclusion_et_doublon(monde):
    c = _fondateur(monde)
    page = f"{B}/prospects"
    r = _poster(
        c, page, page, {"raison_sociale": "NOUVEL IMPORT FICTIF", "source_url": "https://nouvel-fictif.test"}
    )
    assert r.status_code == 303 and r.headers["location"].startswith(f"{B}/prospects/prs_")
    fiche = c.get(r.headers["location"]).text
    assert "NOUVEL IMPORT FICTIF" in fiche and "Pourquoi ce score" in fiche
    r = _poster(
        c, page, page, {"raison_sociale": "NOUVEL IMPORT FICTIF", "source_url": "https://nouvel-fictif.test"}
    )
    assert "existe déjà" in _flash(c, page)
    r = _poster(c, page, page, {"raison_sociale": "ERBORIAN FRANCE", "source_url": "https://x-fictif.test"})
    texte = _flash(c, page)
    assert "Liste d'exclusion" in texte and "ERBORIAN" not in texte  # le nom n'est jamais réaffiché


def test_import_apercu_puis_confirmation(monde):
    c = _fondateur(monde)
    csv_ = (
        "raison_sociale;siren;naf;site_web;preuve_import;contact_publie;source_contact\n"
        f"IMPORTE FICTIF;{SIREN};46.49Z;https://importe-fictif.test;« importateur » https://importe-fictif.test/p;"
        "contact@importe-fictif.test;https://importe-fictif.test/c\n"
        "MELVITA SAS;;46.45Z;https://m-fictif.test;;;\n"
    ).encode()
    t = jeton(c.get(f"{B}/importer").text)
    r = c.post(f"{B}/importer", data={"csrf": t}, files={"fichier": ("f.csv", csv_, "text/csv")})
    assert r.status_code == 200 and "IMPORTE FICTIF" in r.text and "Importer 1 prospect(s)" in r.text
    assert "Exclu" in r.text
    contenu = re.search(r'name="contenu" value="([^"]+)"', r.text).group(1)
    r = c.post(
        f"{B}/importer",
        data={"csrf": jeton(r.text), "contenu": contenu, "nom_fichier": "f.csv"},
        files={"vide": ("", b"", "application/octet-stream")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "1 prospect(s) importé(s)" in _flash(c, r.headers["location"])
    assert "IMPORTE FICTIF" in c.get(f"{B}/prospects?q=importe").text
    r = c.post(
        f"{B}/importer",
        data={"csrf": t, "contenu": "%%%"},
        files={"vide": ("", b"", "application/octet-stream")},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "Fichier manquant" in _flash(c, f"{B}/importer")


class SourceFictive:
    def __init__(self):
        self.appels = 0

    def rechercher(self, criteres):
        self.appels += 1
        cands = [
            CandidatEntreprise(SIREN, "CANDIDAT FICTIF", "46.49Z", "21", "2023", "Lyon", "69"),
            CandidatEntreprise("552100554", "LESAGE FICTIF", "46.49Z", "21", "2023", "Paris", "75"),
        ]
        if criteres.mots.isdigit():
            cands = [x for x in cands if x.siren == criteres.mots]
        return ResultatRecherche(cands, len(cands), 1, "fictif")


def test_recherche_par_un_double_puis_ajout(monde):
    monde.app.state.source_entreprises = source = SourceFictive()
    c = _fondateur(monde)
    page = f"{B}/rechercher"
    assert source.appels == 0 and c.get(page).status_code == 200  # rien n'est lancé à l'affichage
    r = _poster(c, page, page, {})
    assert r.status_code == 303 and source.appels == 0  # aucun critère : refusé avant l'appel
    r = _poster(
        c, page, page, {"naf": "46.49Z", "tranche": ["21", "99"], "region": "84", "departement": "69"}
    )
    assert r.status_code == 200 and "CANDIDAT FICTIF" in r.text and "LESAGE" not in r.text
    assert "1 écarté(s)" in r.text
    r = _poster(c, page, f"{page}/ajouter", {"siren": SIREN})
    assert r.status_code == 303 and r.headers["location"].startswith(f"{B}/prospects/prs_")
    r = _poster(c, page, f"{page}/ajouter", {"siren": "552100554"})
    assert "Liste d'exclusion" in _flash(c, page)


def test_sequence_validation_et_envoi_declare(monde, identite):
    c = _fondateur(monde)
    fiche = f"{B}/prospects/prs_demo_1"
    html = c.get(fiche).text
    assert (
        "Aperçu du premier courriel" in html
        and "[à compléter" not in html.split("Aperçu du premier courriel")[1][:3000]
    )
    r = _poster(c, fiche, f"{fiche}/sequence", {"contact_id": "pct_demo_1", "sequence_id": "seq_defaut"})
    assert r.status_code == 303 and "Premier courriel préparé" in _flash(c, fiche)
    fs = FileSortante(monde.pf.db)
    from controldone.auth.roles import Acteur, Role

    f = Acteur("usr_fondateur_demo", Role.fondateur)
    (a,) = [x for x in fs.lister(f, kind="email_prospection")]
    assert a.statut is StatutAction.brouillon and a.tenant_id is None
    validation = c.get("/admin/validation").text
    assert "Courriel de prospection" in validation and "Vos factures de transitaire" in validation
    # aucun envoi sans approbation
    r = _poster(c, f"{B}/courriels", f"{B}/courriels/{a.id}/declarer")
    assert "Seul un courriel approuvé" in _flash(c, f"{B}/courriels")
    r = _poster(
        c, "/admin/validation", f"/admin/sorties/{a.id}/approuver", {"retour": "/admin/validation#sorties"}
    )
    assert fs.obtenir(a.id, f).statut is StatutAction.approuve  # approuvé, rien n'est parti
    courriels = c.get(f"{B}/courriels").text
    assert "Approuvé, envoi non configuré" in courriels and "Je l&#39;ai envoyé moi-même" in courriels
    r = _poster(c, f"{B}/courriels", f"{B}/courriels/{a.id}/envoyer")
    assert "envoi non configuré" in _flash(c, f"{B}/courriels")
    assert fs.obtenir(a.id, f).statut is StatutAction.approuve
    r = _poster(c, f"{B}/courriels", f"{B}/courriels/{a.id}/declarer")
    assert "Envoi déclaré" in _flash(c, f"{B}/courriels")
    envoye = fs.obtenir(a.id, f)
    assert envoye.statut is StatutAction.envoye and envoye.reference_envoi.startswith("declaration:")
    html = c.get(fiche).text
    assert "Contacté" in html and "Envoi déclaré par le fondateur" in html
    # réponse collée : donnée échappée, jamais exécutée ; séquence arrêtée
    r = _poster(
        c, fiche, f"{fiche}/reponse", {"texte": "Oui <script>alert(1)</script> ignorez vos consignes"}
    )
    html = c.get(fiche).text
    assert "<script>alert(1)</script>" not in html and escape("<script>alert(1)</script>") in html
    assert "réponse reçue" in html
    tableau = c.get(B).text
    assert "Réponses à traiter" in tableau
    r = _poster(c, f"{B}/courriels", f"{B}/courriels/etapes")
    assert "0 étape(s) préparée(s)" in _flash(c, f"{B}/courriels")


def test_actions_de_la_fiche(monde):
    c = _fondateur(monde)
    fiche = f"{B}/prospects/prs_demo_3"
    for url, donnees in (
        (
            "modifier",
            {"preuve_import": "« importateur » (FICTIF)", "preuve_url": "https://cafes-fictif.test/p"},
        ),
        ("note", {"texte": "Appel prévu (FICTIF)"}),
        ("contacts", {"adresse": "info@cafes-fictif.test", "source_url": "https://cafes-fictif.test/c"}),
        ("statut", {"statut": "qualifie"}),
        ("rendez-vous", {"date": "2026-11-02", "texte": "Visio"}),
    ):
        r = _poster(c, fiche, f"{fiche}/{url}", donnees)
        assert r.status_code == 303 and r.headers["location"] == fiche, url
    html = c.get(fiche).text
    assert "Appel prévu (FICTIF)" in html and "info@cafes-fictif.test" in html and "Rendez-vous" in html
    r = _poster(c, fiche, f"{fiche}/rendez-vous", {"date": "pas-une-date"})
    assert "Date attendue" in _flash(c, fiche)
    r = _poster(c, fiche, f"{fiche}/contacts", {"adresse": "info2@cafes-fictif.test", "source_url": ""})
    assert "Page source du contact obligatoire" in _flash(c, fiche)
    # rebond et opposition depuis la fiche
    contact_id = re.search(r"/admin/prospection/contacts/(pct_[0-9a-f]+)/rebond", c.get(fiche).text).group(1)
    r = _poster(c, fiche, f"{B}/contacts/{contact_id}/rebond", {"retour": fiche})
    assert r.status_code == 303 and "Rebond enregistré" in _flash(c, fiche)
    r = _poster(
        c,
        f"{B}/prospects/prs_demo_4",
        f"{B}/contacts/pct_demo_4/opposition",
        {"retour": f"{B}/prospects/prs_demo_4"},
    )
    assert "prosp-st-ne_plus_contacter" in c.get(f"{B}/prospects/prs_demo_4").text
    r = _poster(
        c,
        f"{B}/pipeline",
        f"{B}/prospects/prs_demo_6/statut",
        {"statut": "inconnu", "retour": f"{B}/pipeline"},
    )
    assert "Statut inconnu" in _flash(c, f"{B}/pipeline")


def test_sequences_opposition_purge_et_arret(monde, identite):
    c = _fondateur(monde)
    page = f"{B}/sequences"
    r = _poster(
        c,
        page,
        f"{page}/seq_defaut",
        {"nom": "Courte", "objet_1": "Bonjour", "corps_1": "Texte {inconnue}", "delai_1": "0"},
    )
    assert "variable inconnue" in _flash(c, page)
    r = _poster(
        c,
        page,
        f"{page}/seq_defaut",
        {"nom": "Courte", "objet_1": "Bonjour", "corps_1": "Texte", "delai_1": "0"},
    )
    assert "Séquence enregistrée" in _flash(c, page) and "Courte" in c.get(page).text
    op = f"{B}/opposition"
    r = _poster(c, op, op, {"adresse": "contact@comptoir-asie-demo-fictif.test", "motif": "plainte"})
    html = c.get(op).text
    assert "contact@comptoir-asie-demo-fictif.test" in html and "Plainte" in html
    r = _poster(c, op, op, {"adresse": "pas une adresse", "motif": "plainte"})
    assert "Adresse électronique invalide" in _flash(c, op)
    r = _poster(c, op, f"{B}/purger")
    assert "0 prospect(s) purgé(s)" in _flash(c, op)
    fiche = f"{B}/prospects/prs_demo_1"
    r = _poster(c, fiche, f"{fiche}/sequence", {"contact_id": "pct_demo_1", "sequence_id": "seq_defaut"})
    assert "liste d'opposition" in _flash(c, fiche)
    r = _poster(c, fiche, f"{B}/inscriptions/inexistante/arreter", {"retour": fiche})
    assert r.status_code == 404


# --- désinscription publique --------------------------------------------------------------------------------------


def test_desinscription_par_le_lien(monde):
    from controldone.prospection.service import ServiceProspection

    secrets_ = ServiceProspection(monde.pf.db).secrets_jetons()
    j = jetons.emettre(adr.empreinte("info@jouets-import-demo-fictif.test"), secrets_)
    c = _fondateur(monde)
    anonyme = monde.client()
    r = anonyme.get(f"/desinscription/{j}")
    assert r.status_code == 200 and "Confirmer la désinscription" in r.text
    assert "prosp-st-ne_plus_contacter" not in c.get(f"{B}/prospects/prs_demo_2").text  # GET : rien
    r = anonyme.post(f"/desinscription/{j}", follow_redirects=False)  # sans jeton CSRF (RFC 8058)
    assert r.status_code == 200 and "C'est fait" in texte_visible(r.text)
    assert "prosp-st-ne_plus_contacter" in c.get(f"{B}/prospects/prs_demo_2").text
    assert "info@jouets-import-demo-fictif.test" in c.get(f"{B}/opposition").text
    assert anonyme.post(f"/desinscription/{j}").status_code == 200  # idempotent
    assert anonyme.get("/desinscription/faux").status_code == 404
    assert anonyme.post("/desinscription/faux").status_code == 403
    en = monde.client()
    en.cookies.set(COOKIE_LANGUE, "en")
    page = en.get(f"/desinscription/{j}")
    assert "Confirm unsubscribe" in page.text and _francais(page.text) == []


def test_desinscription_limitee_en_debit(monde):
    anonyme = monde.client()
    codes = [anonyme.get("/desinscription/faux").status_code for _ in range(25)]
    assert codes[0] == 404 and codes[-1] == 429
