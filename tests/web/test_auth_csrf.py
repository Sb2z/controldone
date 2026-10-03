"""Connexion (TOTP du fondateur, anti-rejeu), session, CSRF, limitation de débit, mot de passe."""

from __future__ import annotations

import time

from aides_web import (
    ADMIN_A,
    FONDATEUR_EMAIL,
    MDP_FONDATEUR,
    connecter,
    connecter_client,
    connecter_fondateur,
    jeton,
    poster,
)

from controldone.auth.roles import Acteur, Role
from controldone.auth.totp import code_totp


def test_page_racine_redirige_vers_connexion(monde):
    r = monde.client().get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/connexion"
    assert monde.client().get("/espace", follow_redirects=False).headers["location"] == "/connexion"
    assert monde.client().get("/admin", follow_redirects=False).headers["location"] == "/connexion"


def test_connexion_client(monde):
    c = monde.client()
    connecter_client(c, monde)
    r = c.get("/espace")
    assert r.status_code == 200 and "ATELIERS DÉMO FICTIF SAS" in r.text
    cookie = c.cookies.get("cd_session")
    assert cookie


def test_cookie_de_session_httponly(monde):
    c = monde.client()
    r = connecter(c, ADMIN_A, monde.comptes[ADMIN_A])
    entete = next(v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("cd_session=")).lower()
    assert "httponly" in entete and "samesite=lax" in entete and "path=/" in entete


def test_mauvais_mot_de_passe_message_unique(monde):
    c = monde.client()
    r1 = connecter(c, ADMIN_A, "mauvais-mot-de-passe-123")
    r2 = connecter(c, "inconnu@exemple-fictif.test", "mauvais-mot-de-passe-123")
    assert r1.status_code == r2.status_code == 401
    assert "Identifiants invalides" in r1.text and "Identifiants invalides" in r2.text


def test_fondateur_exige_totp(monde):
    c = monde.client()
    r = connecter(c, FONDATEUR_EMAIL, MDP_FONDATEUR)
    assert r.headers["location"] == "/connexion/totp"
    # sans second facteur : aucune session
    assert c.get("/admin", follow_redirects=False).headers["location"] == "/connexion"
    t = jeton(c.get("/connexion/totp").text)
    r = c.post("/connexion/totp", data={"csrf": t, "code": "000000"}, follow_redirects=False)
    assert r.status_code == 401
    connecter_fondateur(c, monde, t=time.time() + 30)  # pas suivant (le précédent est consommé ou non)
    assert c.get("/admin").status_code == 200


def test_totp_anti_rejeu(monde):
    import time

    instant = time.time()  # même pas TOTP pour les deux connexions (sinon le test échoue à un changement de pas)
    c1, c2 = monde.client(), monde.client()
    connecter_fondateur(c1, monde, t=instant)
    r = connecter(c2, FONDATEUR_EMAIL, MDP_FONDATEUR)
    assert r.headers["location"] == "/connexion/totp"
    t = jeton(c2.get("/connexion/totp").text)
    r = c2.post("/connexion/totp", data={"csrf": t, "code": code_totp(monde.totp, instant)}, follow_redirects=False)
    assert r.status_code == 401  # même code, même pas : refusé


def test_etape_totp_sans_mot_de_passe_refusee(monde):
    c = monde.client()
    assert c.get("/connexion/totp", follow_redirects=False).headers["location"] == "/connexion"
    t = jeton(c.get("/connexion").text)
    r = c.post("/connexion/totp", data={"csrf": t, "code": code_totp(monde.totp)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/connexion"


def test_jeton_fondateur_sans_second_facteur_refuse(monde):
    c = monde.client()
    etat = monde.app.state.securite
    faux = etat.sessions.emettre(Acteur("usr_fondateur_demo", Role.fondateur), deux_facteurs=False)
    c.cookies.set("cd_session", faux)
    assert c.get("/admin", follow_redirects=False).headers["location"] == "/connexion"


def test_jeton_falsifie_refuse(monde):
    c = monde.client()
    c.cookies.set("cd_session", "eyJ1IjoidXNyX2ZvbmRhdGV1cl9kZW1vIn0.signature-fausse")
    assert c.get("/espace", follow_redirects=False).headers["location"] == "/connexion"


def test_deconnexion_revoque_la_session(monde):
    c = monde.client()
    connecter_client(c, monde)
    jeton_session = c.cookies.get("cd_session")
    r = poster(c, "/espace", "/deconnexion")
    assert r.status_code == 303
    c2 = monde.client()
    c2.cookies.set("cd_session", jeton_session)
    assert c2.get("/espace", follow_redirects=False).headers["location"] == "/connexion"


def test_post_sans_csrf_refuse(monde):
    c = monde.client()
    connecter_client(c, monde)
    lien = monde.ids["demo_ateliers"]["ecart"][0]
    r = c.post(f"/espace/recouvrement/{lien}/reclame", data={}, follow_redirects=False)
    assert r.status_code == 403
    r = c.post(f"/espace/recouvrement/{lien}/reclame", data={"csrf": "abc.def"}, follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/deconnexion", data={}, follow_redirects=False)
    assert r.status_code == 403


def test_csrf_d_une_autre_session_refuse(monde):
    a, b = monde.client(), monde.client()
    connecter_client(a, monde)
    connecter_client(b, monde)
    t_b = jeton(b.get("/espace").text)
    lien = monde.ids["demo_ateliers"]["ecart"][0]
    r = a.post(f"/espace/recouvrement/{lien}/reclame", data={"csrf": t_b}, follow_redirects=False)
    assert r.status_code == 403


def test_connexion_sans_csrf_refusee(monde):
    r = monde.client().post("/connexion", data={"email": ADMIN_A, "mot_de_passe": monde.comptes[ADMIN_A]},
                            follow_redirects=False)
    assert r.status_code == 403


def test_csrf_fondateur(monde):
    c = monde.client()
    connecter_fondateur(c, monde)
    cid = monde.ids["demo_nord"]["constat_propose"][0]
    r = c.post(f"/admin/clients/demo_nord/constats/{cid}/valider", data={}, follow_redirects=False)
    assert r.status_code == 403


def test_limitation_des_tentatives(monde):
    c = monde.client()
    statuts = [connecter(c, ADMIN_A, "mauvais-mot-de-passe-123").status_code for _ in range(7)]
    assert statuts[0] == 401 and statuts[-1] == 429


def test_changer_mot_de_passe(monde):
    c = monde.client()
    connecter_client(c, monde)
    r = poster(c, "/compte/mot-de-passe", "/compte/mot-de-passe",
               {"actuel": monde.comptes[ADMIN_A], "nouveau": "court", "confirmation": "court"})
    assert r.status_code == 400
    r = poster(c, "/compte/mot-de-passe", "/compte/mot-de-passe",
               {"actuel": monde.comptes[ADMIN_A], "nouveau": "nouvelle-phrase-FICTIVE-42",
                "confirmation": "nouvelle-phrase-FICTIVE-42"})
    assert r.status_code == 303
    c2 = monde.client()
    assert connecter(c2, ADMIN_A, "nouvelle-phrase-FICTIVE-42").status_code == 303
