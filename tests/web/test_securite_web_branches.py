"""Couverture de la sécurité web (``web.securite``, bloc O4, D-4901) : URL publique et hôtes admis (RS-18), mode
d'exécution (RS-16), limite de taille des corps en flux (413), réduction des rapports CSP (aucune URL complète ni
donnée personnelle au journal). Fonctions et middleware testés directement, sans application. Données fictives."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from starlette.requests import Request

from controldone.web import securite as ws


def _requete(url_hote: str = "hote-fictif.test:8080", scheme: str = "http") -> Request:
    hote, _, port = url_hote.partition(":")
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": scheme,
            "server": (hote, int(port or 80)),
            "path": "/",
            "query_string": b"",
            "headers": [(b"host", url_hote.encode())],
        }
    )


# --- URL publique, hôtes admis -------------------------------------------------------------------------------------


@pytest.fixture
def env_vide(monkeypatch):
    for v in ("CONTROLDONE_URL_PUBLIQUE", "CONTROLDONE_DOMAIN", "CONTROLDONE_HOTES_AUTORISES"):
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


@pytest.mark.parametrize(
    "valeur",
    [
        "ftp://controle-fictif.test",
        "https://",
        "https://hote_invalide.test",
        "https://controle-fictif.test/chemin",
        "https://controle-fictif.test?x=1",
        "https://controle-fictif.test#ancre",
        "https://moi:secret@controle-fictif.test",  # pragma: allowlist secret
    ],
)
def test_url_publique_invalide(env_vide, valeur):
    env_vide.setenv("CONTROLDONE_URL_PUBLIQUE", valeur)
    with pytest.raises(ValueError, match="invalide"):
        ws.url_publique()


def test_url_publique_http_refusee_en_production(env_vide):
    env_vide.setenv("CONTROLDONE_URL_PUBLIQUE", "http://controle-fictif.test")
    assert ws.url_publique() == "http://controle-fictif.test"  # hors production : admis
    env_vide.setenv("CONTROLDONE_ENV", "prod")
    with pytest.raises(ValueError, match="https"):
        ws.url_publique()


def test_url_publique_configuree_ignore_l_hote_de_la_requete(env_vide):
    env_vide.setenv("CONTROLDONE_URL_PUBLIQUE", "https://controle-fictif.test:8443/")
    assert ws.url_publique(_requete("attaquant-fictif.test")) == "https://controle-fictif.test:8443"


def test_url_publique_depuis_le_domaine(env_vide):
    env_vide.setenv("CONTROLDONE_DOMAIN", " Controle-Fictif.TEST. ")
    assert ws.url_publique(_requete("attaquant-fictif.test")) == "https://controle-fictif.test"


def test_domaine_invalide_ignore(env_vide):
    env_vide.setenv("CONTROLDONE_DOMAIN", "pas un domaine")
    assert ws.url_publique(_requete()) == "http://hote-fictif.test:8080"  # développement : URL de la requête
    assert ws.hotes_autorises() is None


def test_url_publique_non_configuree(env_vide):
    with pytest.raises(ValueError, match="non configurée"):
        ws.url_publique()  # pas de requête
    env_vide.setenv("CONTROLDONE_ENV", "prod")
    with pytest.raises(ValueError, match="non configurée"):
        ws.url_publique(_requete())  # jamais l'hôte de la requête en production


def test_hotes_autorises(env_vide):
    assert ws.hotes_autorises() is None
    env_vide.setenv("CONTROLDONE_DOMAIN", "controle-fictif.test")
    env_vide.setenv("CONTROLDONE_URL_PUBLIQUE", "https://Portail-Fictif.test")
    env_vide.setenv("CONTROLDONE_HOTES_AUTORISES", " Interne-Fictif.test , ,controle-fictif.test")
    assert ws.hotes_autorises() == [
        "controle-fictif.test",
        "portail-fictif.test",
        "interne-fictif.test",
        "127.0.0.1",
        "localhost",
        "::1",
    ]


def test_hotes_autorises_url_publique_seule(env_vide):
    env_vide.setenv("CONTROLDONE_URL_PUBLIQUE", "https://portail-fictif.test")
    assert ws.hotes_autorises()[0] == "portail-fictif.test"


# --- mode d'exécution du service -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hote, attendu",
    [("localhost", True), ("[::1]", True), ("127.8.9.1", True), ("0.0.0.0", False), ("machine", False)],
)
def test_boucle_locale(hote, attendu):
    assert ws._boucle_locale(hote) is attendu


def test_mode_dev_https_ou_proxy_refuse(monkeypatch):
    monkeypatch.delenv("CONTROLDONE_DEV_RESEAU", raising=False)
    monkeypatch.delenv("CONTROLDONE_ENV", raising=False)
    with pytest.raises(ws.ModeIncoherent, match="--https") as exc:
        ws.verifier_mode_service(hote="127.0.0.1", https=True, mode="dev")
    assert "CONTROLDONE_ENV absent" in str(exc.value)
    monkeypatch.setenv("CONTROLDONE_ENV", "test")
    with pytest.raises(ws.ModeIncoherent, match="--proxy") as exc:
        ws.verifier_mode_service(hote="127.0.0.1", proxy=True)
    assert "CONTROLDONE_ENV=test" in str(exc.value)
    ws.verifier_mode_service(hote="0.0.0.0", https=True, proxy=True, mode="prod")  # production : rien à dire


def test_mode_dev_reseau_volontaire_journalise(monkeypatch, caplog):
    monkeypatch.setenv("CONTROLDONE_DEV_RESEAU", "1")
    with caplog.at_level(logging.WARNING):
        ws.verifier_mode_service(hote="0.0.0.0", mode="dev")
    assert "mode_dev_expose" in caplog.text


# --- limite de taille des corps (413) ---------------------------------------------------------------------------------


def _appeler(app, *, chemin="/x", entetes=(), morceaux=(b"",), type_="http"):
    envoyes: list[dict] = []
    file = [{"type": "http.request", "body": m, "more_body": i < len(morceaux) - 1} for i, m in enumerate(morceaux)]

    async def recevoir():
        return file.pop(0) if file else {"type": "http.disconnect"}

    async def envoyer(message):
        envoyes.append(message)

    scope = {"type": type_, "path": chemin, "headers": list(entetes)}
    asyncio.run(ws.LimiteCorps(app, limite=10, limite_depot=100, chemins_depot=("/depot",))(scope, recevoir, envoyer))
    return envoyes


def _application_qui_lit(reponse_avant_lecture: bool = False):
    async def app(scope, receive, send):
        if reponse_avant_lecture:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        while True:
            m = await receive()
            if not m.get("more_body"):
                break
        if not reponse_avant_lecture:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return app


def _statut(envoyes):
    return next(m["status"] for m in envoyes if m["type"] == "http.response.start")


def test_corps_annonce_trop_gros_refuse_sans_lecture():
    lu = []

    async def app(scope, receive, send):  # pragma: no cover - ne doit pas être appelée
        lu.append(True)

    envoyes = _appeler(app, entetes=[(b"content-length", b"11")])
    assert _statut(envoyes) == 413 and not lu
    corps = envoyes[1]["body"].decode()
    assert envoyes[0]["headers"][1] == (b"content-length", str(len(corps.encode())).encode())


def test_content_length_mensonger_ou_illisible_compte_en_flux():
    for entete in (b"3", b"pas-un-nombre"):
        envoyes = _appeler(_application_qui_lit(), entetes=[(b"content-length", entete)], morceaux=(b"123456", b"78901"))
        assert _statut(envoyes) == 413


def test_depot_a_sa_propre_limite():
    assert _statut(_appeler(_application_qui_lit(), chemin="/depot", morceaux=(b"x" * 60, b"y" * 30))) == 200
    assert _statut(_appeler(_application_qui_lit(), chemin="/depot", morceaux=(b"x" * 60, b"y" * 41))) == 413


def test_reponse_deja_commencee_pas_de_second_entete():
    envoyes = _appeler(_application_qui_lit(reponse_avant_lecture=True), morceaux=(b"x" * 20,))
    assert [m["type"] for m in envoyes] == ["http.response.start"]  # coupure, sans seconde réponse


def test_autres_protocoles_transmis():
    vus = []

    async def app(scope, receive, send):
        vus.append(scope["type"])

    _appeler(app, type_="lifespan")
    assert vus == ["lifespan"]


@pytest.mark.parametrize(
    "cookie, accept, attendu",
    [
        (b"cd_langue=en", b"fr", "en"),
        (b"__Host-cd_langue=en", b"", "en"),
        (b"cd_langue=xx", b"en-GB,en;q=0.9", "en"),
        (b'cd_langue="\\\x00;;', b"fr-FR", "fr"),
    ],
)
def test_langue_de_la_reponse_413(cookie, accept, attendu):
    scope = {"headers": [(b"cookie", cookie), (b"accept-language", accept)]}
    assert ws._langue_brute(scope) == attendu


# --- rapports CSP : réduction avant journal ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valeur, attendu",
    [("script-src-elem", "script-src-elem"), ("Script-Src", "script-src"), ("script src", "?"), (None, "?"), ("é", "?")],
)
def test_jeton_sur(valeur, attendu):
    assert ws._jeton_sur(valeur) == attendu


@pytest.mark.parametrize(
    "valeur, attendu",
    [
        ("inline", "inline"),
        ("EVAL", "eval"),
        ("https://cdn-fictif.test/a.js?token=secret#x", "https://cdn-fictif.test"),  # pragma: allowlist secret
        ("https://moi:mdp@cdn-fictif.test:8443/x", "https://cdn-fictif.test:8443"),
        ("https://controle-fictif.test/page", "self"),
        ("data:image/png;base64,AAAA", "data"),
        ("chrome-extension://abcdef/x.js", "chrome-extension"),
        ("pas une url", "?"),
        ("https:///sans-hote", "?"),
        ("https://[::1/", "?"),
        ("https://cdn-fictif.test:99999/", "?"),
    ],
)
def test_origine_sans_chemin_ni_identifiants(valeur, attendu):
    assert ws._origine(valeur, "controle-fictif.test") == attendu


@pytest.mark.parametrize(
    "valeur, attendu",
    [
        ("https://controle-fictif.test/dossiers/D-1?client=dupont#x", "/dossiers/D-1"),
        ("", "/"),
        ("https://x.test/é<script>", "/__script_"),
        ("https://[::1/", "?"),
    ],
)
def test_chemin_reduit(valeur, attendu):
    assert ws._chemin(valeur) == attendu


def test_rapports_formats():
    ancien = {"csp-report": {"violated-directive": "img-src", "blocked-uri": "x", "document-uri": "y"}}
    assert ws._rapports(ancien)[0]["directive"] == "img-src"
    nouveau = [
        {"type": "csp-violation", "body": {"effectiveDirective": "script-src", "blockedURL": "inline"}},
        {"type": "deprecation", "body": {}},
        {"type": "csp-violation", "body": "pas un objet"},
        "pas un objet",
    ] + [{"type": "csp-violation", "body": {}}] * 10
    assert len(ws._rapports(nouveau)) == ws.RAPPORTS_MAX_PAR_ENVOI - 3
    assert ws._rapports({"autre": 1}) == [] and ws._rapports("texte") == []


def test_rapport_csp_de_bout_en_bout(monde, caplog):
    c = monde.client()
    url = "/csp-rapport"
    assert c.post(url, content=b"{}", headers={"content-type": "text/plain"}).status_code == 415
    assert c.post(url, content=b"{pas du json", headers={"content-type": "application/json"}).status_code == 400
    trop = b"[" + b" " * ws.TAILLE_MAX_RAPPORT_CSP + b"]"
    assert c.post(url, content=trop, headers={"content-type": "application/reports+json"}).status_code == 413
    rapport = {
        "csp-report": {
            "effective-directive": "script-src-elem",
            "blocked-uri": "https://cdn-fictif.test/x.js?jeton=SECRET-FICTIF",
            "document-uri": "https://testserver/dossiers?client=DUPONT-FICTIF",
            "disposition": "enforce",
            "script-sample": "alert('DONNEE-FICTIVE')",
        }
    }
    with caplog.at_level(logging.WARNING, "controldone.web.securite"):
        r = c.post(url, content=json.dumps(rapport), headers={"content-type": "application/csp-report"})
    assert r.status_code == 204
    assert "directive=script-src-elem bloque=https://cdn-fictif.test document=/dossiers" in caplog.text
    for secret in ("SECRET-FICTIF", "DUPONT-FICTIF", "DONNEE-FICTIVE", "testclient"):
        assert secret not in caplog.text
