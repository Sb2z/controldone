"""Bloc I (interface) : langue de l'interface (D-3803), retour après action dans une liste filtrée (D-3802),
colonne « Créée » des tâches, libellés des alertes (D-3806), sessions actives (D-3804). Données fictives."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from aides_web import ADMIN_A, ADMIN_B, LECTEUR_A, connecter_client, connecter_fondateur, jeton, poster
from i18n_cles import GABARITS, cles_js, toutes

from controldone.guardrails import AVERTISSEMENT, check_text
from controldone.web.i18n import AVERTISSEMENT_EN, COOKIE_LANGUE, PHRASE_RENVOI_EN, negocier, traduire
from controldone.web.i18n_en import CATALOGUE_EN, TEXTES_JS
from controldone.web.listes_vues import LIBELLES_ALERTES, libelle_alerte
from controldone.web.rendu import environnement, retour_sur, texte_visible

A, B = "demo_ateliers", "demo_nord"
SRC = Path(__file__).resolve().parents[2] / "src" / "controldone"


# --- catalogue -------------------------------------------------------------------------------------------------------


def test_aucun_texte_marque_sans_traduction():
    manquants = sorted(toutes() - set(CATALOGUE_EN))
    assert manquants == [], manquants[:20]


def test_textes_js_couverts_et_transmis():
    assert cles_js() <= set(TEXTES_JS) <= set(CATALOGUE_EN)


def test_parametres_identiques_dans_les_deux_langues():
    for fr, en in CATALOGUE_EN.items():
        assert sorted(re.findall(r"\{(\w+)\}", fr)) == sorted(re.findall(r"\{(\w+)\}", en)), fr
        assert en.strip(), fr


#: Équivalents anglais des formulations interdites (SPEC §3.2) : jamais dans l'interface anglaise.
INTERDITS_EN = ("illegal", "unlawful", "fraud", "non-compliant", "wrong code", "correct code", "wrong rate",
                "incorrect rate", "duty owed", "duties owed", "tax owed", "overpaid", "we claim", "on behalf of our client",
                "we guarantee", "certified compliant", "undervaluation", "overvaluation", "refund of duties")


def test_traductions_sans_formulation_interdite():
    for fr, en in CATALOGUE_EN.items():
        assert check_text(en) == [], fr
        assert not any(x in en.lower() for x in INTERDITS_EN), en
    for texte in (AVERTISSEMENT_EN, PHRASE_RENVOI_EN):
        assert check_text(texte) == []
        assert not any(x in texte.lower() for x in INTERDITS_EN if x != "duty owed")


def test_negociation_accept_language():
    assert negocier(None) == "fr"
    assert negocier("en-GB,en;q=0.9") == "en"
    assert negocier("de-DE,en;q=0.5,fr;q=0.8") == "fr"
    assert negocier("de, it") == "fr"
    assert negocier("en;q=0, fr;q=0.1") == "fr"
    assert negocier("x" * 10_000) == "fr"
    assert traduire("Dossiers", "en") == "Files" and traduire("Dossiers", "fr") == "Dossiers"
    assert traduire("Texte absent du catalogue", "en") == "Texte absent du catalogue"


# --- pages dans les deux langues ------------------------------------------------------------------------------------


def _pages_client(monde):
    return ["/espace", "/espace/depot", "/espace/dossiers", f"/espace/dossiers/{monde.ids[A]['dossier'][0]}",
            f"/espace/lots/{monde.ids[A]['lot'][0]}", "/espace/rapports", "/espace/recouvrement",
            "/compte/mot-de-passe", "/compte/sessions", "/compte", "/espace/dossiers/inexistant"]


def _pages_fondateur(monde):
    return ["/admin", "/admin/clients", f"/admin/clients/{A}", f"/admin/clients/{A}/dossiers/{monde.ids[A]['dossier'][0]}",
            "/admin/validation", "/admin/jobs", "/admin/journal", "/admin/alertes", "/admin/autonomie",
            "/admin/finances", "/admin/notifications", "/compte/sessions", "/compte"]


def _rendus(monkeypatch) -> set[str]:
    vus: set[str] = set()
    env = environnement()
    origine = env.get_template

    def suivre(nom, *a, **k):
        vus.add(nom)
        return origine(nom, *a, **k)

    monkeypatch.setattr(env, "get_template", suivre)
    return vus


@pytest.mark.parametrize("langue", ["fr", "en"])
def test_toutes_les_pages_dans_les_deux_langues(monde, monkeypatch, langue):
    vus = _rendus(monkeypatch)
    francais_seul = re.compile(r"\b(Tableau de bord|Déposer des documents|Se déconnecter|Rechercher|Aucun dossier)\b")
    for qui, pages in (("client", _pages_client(monde)), ("fondateur", _pages_fondateur(monde))):
        c = monde.client()
        c.cookies.set(COOKIE_LANGUE, langue)
        connecter_client(c, monde, ADMIN_A) if qui == "client" else connecter_fondateur(c, monde)
        for url in pages:
            r = c.get(url)
            assert r.status_code in (200, 404), (url, r.status_code)
            assert f'<html lang="{langue}">' in r.text, url
            texte = texte_visible(r.text)
            assert check_text(texte) == [], (url, check_text(texte)[:2])
            assert AVERTISSEMENT in texte, url  # texte juridique exact, en français, dans les deux langues
            if langue == "en":
                assert AVERTISSEMENT_EN in texte and "Courtesy translation" in texte, url
                assert not francais_seul.search(re.sub(r'<[^>]*lang="fr"[^>]*>.*?</[^>]+>', " ", r.text)), url
            else:
                assert AVERTISSEMENT_EN not in texte
    connexion = monde.client()
    connexion.cookies.set(COOKIE_LANGUE, langue)
    assert f'<html lang="{langue}">' in connexion.get("/connexion").text
    pages_gabarits = {p.relative_to(GABARITS).as_posix() for p in GABARITS.rglob("*.j2")}
    hors_pages = {"base.html.j2", "macros.html.j2", "listes.html.j2", "graphes.html.j2", "api_docs.html.j2",
                  "totp.html.j2", "admin/paiement_bouchon.html.j2"}
    assert pages_gabarits - hors_pages <= vus | {"connexion.html.j2"}, sorted(pages_gabarits - hors_pages - vus)


@pytest.mark.parametrize("langue", ["fr", "en"])
def test_gabarits_hors_parcours_dans_les_deux_langues(langue):
    """Gabarits sans page simple à atteindre dans le parcours (second facteur, paiement simulé) : rendus
    directement avec un contexte fictif."""
    from controldone.web.i18n import activer

    activer(langue)
    try:
        commun = {"titre": "x", "acteur": None, "csrf": "jeton", "demo": False, "flash": None, "nav": None,
                  "chemin": "/", "langue": langue, "textes_js": {}, "retour_langue": "/", "request": None}
        html = environnement().get_template("totp.html.j2").render(**commun)
        assert ("Verification code" in html) == (langue == "en")
        session = SimpleNamespace(id="cs_FICTIF", mode="payment", metadata=SimpleNamespace(numero="F-FICTIF-1"))
        html = environnement().get_template("admin/paiement_bouchon.html.j2").render(**commun, session=session,
                                                                                     montant="12.00")
        assert ("Simulate a successful payment" in html) == (langue == "en")
        assert check_text(texte_visible(html)) == []
    finally:
        activer("fr")


def test_choix_de_la_langue(monde):
    c = monde.client()
    # page de connexion : Accept-Language sans préférence enregistrée
    assert '<html lang="en">' in c.get("/connexion", headers={"Accept-Language": "en-US,en;q=0.9"}).text
    assert '<html lang="fr">' in c.get("/connexion", headers={"Accept-Language": "de"}).text
    # sans jeton CSRF : refusé
    assert c.post("/preferences/langue", data={"langue": "en"}).status_code == 403
    t = jeton(c.get("/connexion").text)
    r = c.post("/preferences/langue", data={"csrf": t, "langue": "en", "retour": "//evil.example/x"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "httponly" in r.headers["set-cookie"].lower() and f"{COOKIE_LANGUE}=en" in r.headers["set-cookie"]
    page = c.get("/connexion", headers={"Accept-Language": "fr"}).text  # la préférence l'emporte
    assert '<html lang="en">' in page and "Sign in" in page
    # valeur inconnue : sans effet ; retour vers une liste filtrée conservé
    t = jeton(page)
    r = c.post("/preferences/langue", data={"csrf": t, "langue": "xx", "retour": "/connexion?a=1"},
               follow_redirects=False)
    assert r.headers["location"] == "/connexion?a=1" and "set-cookie" not in r.headers
    # connecté : interface et messages en anglais
    connecter_client(c, monde, ADMIN_A)
    d = c.get("/espace/dossiers?statut=conforme").text
    assert "Files" in d and 'name="retour" value="/espace/dossiers?statut=conforme"' in d
    assert "Status: unknown value" in c.get("/espace/dossiers?statut=zzz").text


def test_suivi_json_dans_la_langue_de_l_utilisateur(monde):
    c = monde.client()
    c.cookies.set(COOKIE_LANGUE, "en")
    connecter_client(c, monde, ADMIN_A)
    d = c.get(f"/espace/lots/{monde.ids[A]['lot'][0]}/etat").json()
    assert d["libelle"] == "Done" and d["texte"] == "Processing complete."


# --- retour après action dans une liste filtrée -----------------------------------------------------------------------


@pytest.mark.parametrize("valeur", [
    "//evil.example", "/\\evil.example", "https://evil.example/", "javascript:alert(1)", "/%2F%2Fevil.example",
    "/x/../admin", "/x?a=%0d%0aSet-Cookie:x", "/x?a=%ZZ", "/x?a=<b>", "/x#a b", "/x?a=b c", "/espace@evil.example",
    "\t/espace", "/" + "a" * 2001, "http:/evil", "/x?next=//evil", None, 3,
])
def test_retour_refuse_les_redirections_ouvertes(valeur):
    assert retour_sur(valeur, "/defaut") == "/defaut"


@pytest.mark.parametrize("valeur", [
    "/admin/validation?client=demo_a&min=10%2C5&q=caf%C3%A9+cr%C3%A8me#constats",
    "/espace/recouvrement?statut=ouvert&tri=-reste&page=2", "/admin/jobs?statut=dead&kind=traiter_lot",
    "/x?a=%2F%2Fevil.example",  # « // » encodé dans une valeur : reste une valeur, pas une adresse
])
def test_retour_accepte_les_requetes_encodees(valeur):
    assert retour_sur(valeur, "/defaut") == valeur


def test_retour_apres_validation_dans_une_file_filtree(monde):
    c = monde.client()
    connecter_fondateur(c, monde)
    filtre = f"/admin/validation?client={B}&min=0%2C5"
    page = c.get(filtre).text
    attendu = f"/admin/validation?client={B}&amp;min=0%2C5#constats"
    assert f'name="retour" value="{attendu}"' in page
    cid = monde.ids[B]["constat_propose"][0]
    r = poster(c, filtre, f"/admin/clients/{B}/constats/{cid}/valider",
               {"retour": attendu.replace("&amp;", "&")})
    assert r.status_code == 303 and r.headers["location"] == f"/admin/validation?client={B}&min=0%2C5#constats"
    r = poster(c, filtre, f"/admin/clients/{B}/constats/{monde.ids[B]['constat_propose'][1]}/rejeter",
               {"retour": "https://evil.example/", "motif": "FICTIF"})
    assert r.headers["location"] == "/admin/validation"


def test_retour_apres_action_dans_le_suivi_des_avoirs(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    filtre = "/espace/recouvrement?statut=ouvert&tri=-montant"
    page = c.get(filtre).text
    m = re.search(r'action="/espace/recouvrement/([^/"]+)/reclame"', page)
    assert m and 'name="retour" value="/espace/recouvrement?statut=ouvert&amp;tri=-montant"' in page
    r = poster(c, filtre, f"/espace/recouvrement/{m.group(1)}/reclame",
               {"retour": "/espace/recouvrement?statut=ouvert&tri=-montant"})
    assert r.status_code == 303 and r.headers["location"] == "/espace/recouvrement?statut=ouvert&tri=-montant"


# --- tâches : colonne « Créée » ----------------------------------------------------------------------------------------


def test_taches_creee_et_prochain_essai(monde):
    from datetime import UTC, datetime, timedelta

    from controldone.storage.file_jobs import JobStore

    store = JobStore(monde.pf.db)
    jid = store.enqueue("essai_fictif", {}, "essai-fictif-cree")[0].id
    with monde.pf.db.transaction_systeme() as s:
        from controldone.storage.models import Job

        j = s.get(Job, jid)
        j.cree_le = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)
        j.run_after = datetime(2031, 5, 6, 9, 0, tzinfo=UTC) + timedelta(minutes=1)
    info = next(x for x in store.rechercher(kind="essai_fictif")[0])
    assert info.cree_le.year == 2026 and info.run_after.year == 2031
    c = monde.client()
    connecter_fondateur(c, monde)
    page = c.get("/admin/jobs?kind=essai_fictif").text
    ligne = page.split("<code>essai_fictif</code>")[0].rsplit("<tr>", 1)[1]
    assert "4 mars 2026" in ligne and "6 mai 2031" in ligne  # création, puis prochain essai (colonne séparée)
    assert "Prochain essai" in page


# --- alertes -------------------------------------------------------------------------------------------------------------


def _kinds_emis() -> set[str]:
    kinds: set[str] = set()
    for p in SRC.rglob("*.py"):
        texte = p.read_text(encoding="utf-8")
        for m in re.finditer(r"(?:signaler_alerte|emettre_alerte|alerte_fondateur|alerter)\((.{0,300})", texte, re.S):
            kinds |= set(re.findall(r'kind="([a-z_]+)"', m.group(1)))
            kinds |= set(re.findall(r'^\s*"([a-z_]+)",', m.group(1)))
        kinds |= set(re.findall(r'alerter\("([a-z_]+)"', texte))
    from typing import get_args

    from controldone.agents.outils import KINDS_ALERTE
    from controldone.services.notifications import LIBELLES

    return kinds | set(get_args(KINDS_ALERTE)) | set(LIBELLES)


def test_chaque_type_d_alerte_a_son_libelle():
    emis = _kinds_emis()
    assert {"sauvegarde_echec", "sauvegarde_verification_echec", "sauvegarde_absente",
            "sauvegarde_hors_site_echec", "job_mort"} <= emis
    assert sorted(emis - set(LIBELLES_ALERTES)) == []
    for k in emis:
        assert traduire(libelle_alerte(k), "en") != k


def test_page_alertes_libelles_sauvegarde(monde):
    from controldone.storage.alertes import emettre_alerte

    with monde.pf.db.transaction_systeme() as s:
        for k in ("sauvegarde_echec", "sauvegarde_verification_echec", "sauvegarde_absente",
                  "sauvegarde_hors_site_echec", "type_futur_inconnu"):
            emettre_alerte(s, cle=f"{k}:essai", kind=k, message=f"Message FICTIF {k}")
    c = monde.client()
    connecter_fondateur(c, monde)
    page = c.get("/admin/alertes").text
    for lib in ("Sauvegarde en échec", "Sauvegarde non conforme", "Aucune sauvegarde récente",
                "Copie hors site en échec"):
        assert lib in page
    assert "type_futur_inconnu" in page  # type inconnu : nom technique, jamais d'erreur
    c.cookies.set(COOKIE_LANGUE, "en")
    assert "Backup failed verification" in c.get("/admin/alertes").text


# --- sessions actives ------------------------------------------------------------------------------------------------


def test_sessions_actives_et_fermer_les_autres(monde):
    c1, c2, c3 = monde.client(), monde.client(), monde.client()
    for c in (c1, c2, c3):
        connecter_client(c, monde, ADMIN_A)
    autre = monde.client()
    connecter_client(autre, monde, ADMIN_B)
    page = c1.get("/compte/sessions").text
    assert "Cette session" in page and "Fermer mes autres sessions" in page
    refs = re.findall(r'action="/compte/sessions/([0-9a-f]+)/fermer"', page)
    assert len(refs) >= 2
    assert all(s not in page for s in (c1.cookies.get("cd_session") or "x",))  # jeton jamais affiché
    # une référence ne vaut que pour le compte connecté
    r = poster(autre, "/compte/sessions", f"/compte/sessions/{refs[0]}/fermer")
    assert r.status_code == 303
    assert "introuvable" in autre.get("/compte/sessions").text
    # fermer une session précise
    r = poster(c1, "/compte/sessions", f"/compte/sessions/{refs[0]}/fermer")
    assert r.status_code == 303 and "Session fermée" in c1.get("/compte/sessions").text
    # fermer toutes les autres : c1 reste connecté, c2 et c3 sont déconnectés
    r = poster(c1, "/compte/sessions", "/compte/sessions/fermer-autres")
    assert r.status_code == 303
    assert c1.get("/espace").status_code == 200
    for c in (c2, c3):
        assert c.get("/espace", follow_redirects=False).status_code in (302, 303, 307)
    assert autre.get("/espace").status_code == 200  # un autre compte n'est pas touché
    assert "Aucune autre session ouverte" in c1.get("/compte/sessions").text
    # sans jeton CSRF : refusé
    assert c1.post("/compte/sessions/fermer-autres").status_code == 403


def test_sessions_lecteur_et_fondateur(monde):
    lecteur = monde.client()
    connecter_client(lecteur, monde, LECTEUR_A)
    assert lecteur.get("/compte/sessions").status_code == 200
    f = monde.client()
    connecter_fondateur(f, monde)
    assert "Mes sessions actives" in f.get("/compte/sessions").text
    anonyme = monde.client()
    assert anonyme.get("/compte/sessions", follow_redirects=False).status_code in (302, 303, 307)
