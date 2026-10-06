"""Suivi de sécurité (bloc S, D-3601 à D-3609) : points ouverts de la première revue (RS-16, RS-18 à RS-21),
plafond de pixels du rendu OCR, cookies secondaires ``__Host-``, copie locale bornée des révocations, sessions
actives. Données fictives seulement."""

from __future__ import annotations

import io
import os
from pathlib import Path

import httpx
import pytest
from aides_web import (
    ADMIN_A,
    FONDATEUR_EMAIL,
    MDP_FONDATEUR,
    SECRET_SESSION,
    connecter,
    connecter_client,
    jeton,
    poster,
)

from controldone.auth import GestionnaireSessions, RegistreRevocations
from controldone.auth.roles import Acteur, Role
from controldone.auth.totp import code_totp
from controldone.storage import Database

ACTEUR = Acteur("usr_fictif", Role.client_admin, "demo_ateliers")


class Horloge:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path}/securite.db")
    d.creer_schema()
    yield d
    d.fermer()


# --- RS-16 : mode dev oublié en production (D-3601) ----------------------------------------------------------------


def test_rs16_mode_dev_refuse_hors_boucle_locale(monkeypatch):
    from controldone.web.securite import ModeIncoherent, verifier_mode_service

    monkeypatch.delenv("CONTROLDONE_DEV_RESEAU", raising=False)
    for hote in ("127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.2"):
        verifier_mode_service(hote=hote, mode="dev")
    for kw in ({"hote": "0.0.0.0"}, {"hote": "192.0.2.10"}, {"hote": "::"},
               {"hote": "127.0.0.1", "https": True}, {"hote": "127.0.0.1", "proxy": True}):
        with pytest.raises(ModeIncoherent, match="CONTROLDONE_ENV=prod"):
            verifier_mode_service(mode="dev", **kw)
        with pytest.raises(ModeIncoherent):
            verifier_mode_service(mode="test", **kw)
        verifier_mode_service(mode="prod", **kw)
    monkeypatch.setenv("CONTROLDONE_DEV_RESEAU", "1")  # démonstration volontaire sur un réseau de confiance
    verifier_mode_service(hote="0.0.0.0", mode="dev")


def test_rs16_serve_refuse_de_demarrer(monkeypatch, tmp_path, capsys):
    from controldone.cli import main

    monkeypatch.setenv("CONTROLDONE_ENV", "dev")
    monkeypatch.delenv("CONTROLDONE_DEV_RESEAU", raising=False)
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", f"sqlite:///{tmp_path}/x.db")
    assert main(["serve", "--host", "0.0.0.0", "--port", "8999"]) == 2
    assert "démarrage refusé" in capsys.readouterr().err
    assert not (tmp_path / "x.db").exists() and not (tmp_path / "dev_master.key").exists()  # rien de créé


# --- RS-18 : URL publique et en-tête Host (D-3602) ------------------------------------------------------------------


def test_rs18_url_publique_jamais_depuis_host_en_production(monkeypatch):
    from starlette.requests import Request

    from controldone.web.securite import url_publique

    req = Request({"type": "http", "scheme": "https", "path": "/", "query_string": b"", "server": ("piege.test", 443),
                   "headers": [(b"host", b"piege.exemple.test")]})
    for k in ("CONTROLDONE_DOMAIN", "CONTROLDONE_URL_PUBLIQUE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    with pytest.raises(ValueError, match="CONTROLDONE_DOMAIN"):
        url_publique(req)
    monkeypatch.setenv("CONTROLDONE_DOMAIN", "app.controldone-demo.test")
    assert url_publique(req) == "https://app.controldone-demo.test"
    monkeypatch.setenv("CONTROLDONE_URL_PUBLIQUE", "https://portail.controldone-demo.test:8443/")
    assert url_publique(req) == "https://portail.controldone-demo.test:8443"
    for mauvaise in ("http://portail.controldone-demo.test", "https://a.test/chemin", "https://u:p@a.test",
                     "javascript:alert(1)"):
        monkeypatch.setenv("CONTROLDONE_URL_PUBLIQUE", mauvaise)
        with pytest.raises(ValueError):
            url_publique(req)
    monkeypatch.delenv("CONTROLDONE_URL_PUBLIQUE")
    monkeypatch.delenv("CONTROLDONE_DOMAIN")
    monkeypatch.setenv("CONTROLDONE_ENV", "dev")
    assert url_publique(req) == "https://piege.exemple.test"  # développement seulement


def test_rs18_hote_etranger_refuse(monkeypatch, _modele, tmp_path):
    from aides_web import construire_monde

    monkeypatch.setenv("CONTROLDONE_DOMAIN", "app.controldone-demo.test")
    monkeypatch.delenv("CONTROLDONE_URL_PUBLIQUE", raising=False)
    monkeypatch.setenv("CONTROLDONE_HOTES_AUTORISES", "testserver")
    m = construire_monde(_modele, tmp_path / "hotes")
    try:
        c = m.client()
        assert c.get("/sante").status_code == 200
        assert c.get("/sante", headers={"host": "app.controldone-demo.test"}).status_code == 200
        assert c.get("/sante", headers={"host": "127.0.0.1:8000"}).status_code == 200  # sonde de santé
        r = c.get("/connexion", headers={"host": "piege.exemple.test"})
        assert r.status_code == 400 and "content-security-policy" in r.headers
    finally:
        m.pf.db.fermer()


# --- RS-19 : veille, taille de réponse bornée en flux ---------------------------------------------------------------


def test_rs19_veille_reponse_bornee_en_flux():
    from controldone.agents.veille_sources import telecharger

    lus = []

    def morceaux(n: int):
        for _ in range(n):
            lus.append(1)
            yield b"<p>" + b"x" * (64 * 1024) + b"</p>"

    def repondre(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/annonce":  # taille annoncée au-delà du plafond
            return httpx.Response(200, headers={"content-length": str(50 * 1024 * 1024)}, content=b"")
        if request.url.path == "/flux":  # sans Content-Length, corps sans fin
            return httpx.Response(200, content=morceaux(10_000))
        return httpx.Response(200, text="<html><title>Page FICTIVE</title><body>texte</body></html>")

    http = httpx.Client(transport=httpx.MockTransport(repondre))
    r = telecharger("https://douane.gouv.fr/annonce", client=http, taille_max=1024 * 1024)
    assert r == {"url": "https://douane.gouv.fr/annonce", "statut": "non_verifie", "motif": "trop_volumineux"}
    r = telecharger("https://douane.gouv.fr/flux", client=http, taille_max=1024 * 1024)
    assert r["motif"] == "trop_volumineux" and len(lus) < 40  # abandon dès le plafond, pas 10 000 morceaux lus
    r = telecharger("https://douane.gouv.fr/ok", client=http)
    assert r["statut"] == "ok" and r["titre"] == "Page FICTIVE"


# --- RS-20 : vignettes rendues dans le processus isolé (D-3607) -----------------------------------------------------


def _pdf(largeur_pt: float = 595, hauteur_pt: float = 842, texte: str = "Total 123,45 FICTIF") -> bytes:
    from reportlab.pdfgen import canvas

    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=(largeur_pt, hauteur_pt))
    c.drawString(40, min(hauteur_pt - 40, 700), texte)
    c.showPage()
    c.save()
    return b.getvalue()


def test_rs20_vignettes_rendues_hors_du_processus_web(monkeypatch):
    from controldone.ingest import pages
    from controldone.services import vignettes

    appels = []
    original = pages.executer_isole

    def espion(cible, kwargs, **kw):
        appels.append(cible)
        return original(cible, kwargs, **kw)

    monkeypatch.setattr(pages, "executer_isole", espion)
    monkeypatch.setattr(vignettes, "ISOLER", True)
    png = vignettes.page_png("t:rs20a", _pdf, "application/pdf", 1, "mini")
    assert png and png.startswith(b"\x89PNG") and appels == ["rendu_page"]
    extrait = vignettes.extrait_png("t:rs20b", _pdf, "application/pdf", 1, valeur="123,45")
    assert extrait and extrait.startswith(b"\x89PNG") and appels == ["rendu_page"] * 2
    assert vignettes.page_png("t:rs20c", lambda: b"%PDF-1.7 illisible", "application/pdf", 1) is None


def test_rs20_processus_de_rendu_borne_et_liste_fermee():
    from controldone.ingest.pages import executer_isole

    with pytest.raises(ValueError):
        executer_isole("os:system", {})
    # mémoire insuffisante pour pdfium : échec contenu dans l'enfant, le processus appelant continue
    png, motif = executer_isole("rendu_page", {"contenu": _pdf(), "mime": "application/pdf", "numero": 1,
                                               "largeur": 1240}, memoire_mo=40)
    assert png is None and motif is not None and motif.startswith("processus_pages_code_")
    png, motif = executer_isole("rendu_page", {"contenu": _pdf(), "mime": "application/pdf", "numero": 1})
    assert motif is None and png.startswith(b"\x89PNG")


# --- RS-21 : volume de la base (D-3605) -------------------------------------------------------------------------------


def _faux_sys(racine: Path, dev: tuple[int, int], uuids: list[str]) -> Path:
    """``/sys`` minimal : ``dev/block/MAJ:MIN`` -> ``dm-0`` (uuid ``uuids[0]``), esclave ``dm-1`` (``uuids[1]``)…"""
    blocs = racine / "devices" / "virtual" / "block"
    for i, uuid in enumerate(uuids):
        d = blocs / f"dm-{i}"
        (d / "dm").mkdir(parents=True)
        (d / "dm" / "uuid").write_text(uuid + "\n")
        (d / "slaves").mkdir()
        if i:
            (blocs / f"dm-{i - 1}" / "slaves" / f"dm-{i}").symlink_to(d)
    (racine / "dev" / "block").mkdir(parents=True)
    (racine / "dev" / "block" / f"{dev[0]}:{dev[1]}").symlink_to(blocs / "dm-0")
    return racine


def test_rs21_chiffrement_du_volume_detecte(tmp_path):
    from controldone.storage.securite import chiffrement_volume

    st = os.stat(tmp_path)
    dev = (os.major(st.st_dev), os.minor(st.st_dev))
    assert chiffrement_volume(tmp_path, sys_dir=_faux_sys(tmp_path / "s1", dev, ["CRYPT-LUKS2-abc-racine"])) == "chiffre"
    lvm_sur_luks = _faux_sys(tmp_path / "s2", dev, ["LVM-xyz", "CRYPT-LUKS2-def-pv"])
    assert chiffrement_volume(tmp_path, sys_dir=lvm_sur_luks) == "chiffre"
    assert chiffrement_volume(tmp_path, sys_dir=_faux_sys(tmp_path / "s3", dev, ["LVM-sans-chiffrement"])) == "non_chiffre"
    assert chiffrement_volume(tmp_path, sys_dir=tmp_path / "absent") == "inconnu"
    assert chiffrement_volume(tmp_path / "inexistant", sys_dir=tmp_path / "s1") == "inconnu"


def test_rs21_alerte_au_demarrage_en_production(tmp_path, monkeypatch, db):
    from controldone.storage.models import Alerte
    from controldone.storage.securite import signaler_volume_non_chiffre

    monkeypatch.delenv("CONTROLDONE_VOLUME_CHIFFRE", raising=False)
    st = os.stat(db.chemin_sqlite())
    faux = _faux_sys(tmp_path / "sys", (os.major(st.st_dev), os.minor(st.st_dev)), ["LVM-sans-chiffrement"])
    assert signaler_volume_non_chiffre(db, mode="dev", sys_dir=faux) == "hors_prod"
    assert signaler_volume_non_chiffre(db, mode="prod", sys_dir=faux) == "non_chiffre"
    assert signaler_volume_non_chiffre(db, mode="prod", sys_dir=faux) == "non_chiffre"  # une alerte, pas deux
    with db.transaction_systeme() as s:
        alertes = [a.kind for a in s.query(Alerte).all()]
    assert alertes == ["volume_non_chiffre"]
    monkeypatch.setenv("CONTROLDONE_VOLUME_CHIFFRE", "1")  # chiffrement de l'hébergeur, invisible d'ici
    assert signaler_volume_non_chiffre(db, mode="prod", sys_dir=faux) == "declare"


# --- Rendu OCR des PDF : plafond de pixels (D-3606) -----------------------------------------------------------------


def test_echelle_rendu_ocr_sans_effet_sur_les_pages_ordinaires():
    from controldone.ingest.pages import MAX_PIXELS_RENDU_OCR, echelle_rendu_ocr

    for w, h in ((595, 842), (842, 1191), (612, 1008), (1191, 1684)):  # A4, A3, légal US, A2
        assert echelle_rendu_ocr(w, h, 300) == (300 / 72, False)
    for w, h in ((14173, 14173), (2384, 3370), (14400, 4000)):  # 5 m × 5 m, A0, bandeau de 5 m
        e, reduite = echelle_rendu_ocr(w, h, 300)
        assert reduite and w * h * e * e <= MAX_PIXELS_RENDU_OCR


def test_rendu_ocr_d_une_page_demesuree_plafonne(monkeypatch):
    import pypdfium2 as pdfium

    from controldone.ingest import pages

    demandes = []
    original = pdfium.PdfPage.render

    def espion(self, *a, scale=1, **kw):
        w, h = self.get_size()
        demandes.append(w * h * scale * scale)
        return original(self, *a, scale=scale, **kw)

    monkeypatch.setattr(pdfium.PdfPage, "render", espion)
    monkeypatch.setattr(pages, "ocr_disponible", lambda: True)
    monkeypatch.setattr(pages, "_ocr_image", lambda image, opts, numero: pages._page_illisible(numero, "essai"))
    opts = pages.OptionsPages(isoler=False)
    sortie = pages._pages_pdf(_pdf(14173, 14173, texte=""), opts)  # page de 5 m × 5 m, sans texte
    assert demandes and max(demandes) <= pages.MAX_PIXELS_RENDU_OCR
    assert "rendu_ocr_reduit" in sortie[0].avertissements
    demandes.clear()
    sortie = pages._pages_pdf(_pdf(texte=""), opts)  # A4 : 300 dpi, inchangé
    assert demandes and abs(demandes[0] - 595 * 842 * (300 / 72) ** 2) < 1
    assert "rendu_ocr_reduit" not in sortie[0].avertissements


# --- cookies secondaires __Host- (D-3604) ---------------------------------------------------------------------------


def test_cookies_secondaires_prefixes_en_production(_modele, tmp_path):
    from aides_web import construire_monde
    from fastapi.testclient import TestClient

    m = construire_monde(_modele, tmp_path / "prod", https=True)
    etat = m.app.state.securite
    etat.prod = True
    etat.cookie.update({"key": "__Host-cd_session", "secure": True, "samesite": "strict"})
    try:
        c = TestClient(m.app, base_url="https://testserver")
        r = connecter(c, FONDATEUR_EMAIL, MDP_FONDATEUR)
        assert r.status_code == 303
        entete = r.headers["set-cookie"]
        assert "__Host-cd_2fa=" in entete and "Secure" in entete and "Path=/" in entete and "Domain=" not in entete
        assert "cd_2fa" not in entete.replace("__Host-cd_2fa", "")
        tj = jeton(c.get("/connexion/totp").text)
        r = c.post("/connexion/totp", data={"csrf": tj, "code": code_totp(m.totp)}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/admin"
        poses = r.headers.get_list("set-cookie")
        assert any(x.startswith("__Host-cd_session=") for x in poses)
        assert any(x.startswith("__Host-cd_2fa=") and "Max-Age=0" in x and "Secure" in x for x in poses)  # effacé
        r = poster(c, "/admin", "/deconnexion")
        flash = [x for x in r.headers.get_list("set-cookie") if "flash" in x]
        assert flash and all(x.startswith("__Host-cd_flash=") and "Secure" in x and "Path=/" in x for x in flash)
        r = c.get("/connexion")
        assert "déconnecté" in r.text
        assert any(x.startswith("__Host-cd_flash=") and "Max-Age=0" in x and "Secure" in x
                   for x in r.headers.get_list("set-cookie"))
    finally:
        m.pf.db.fermer()


def test_cookies_secondaires_sans_prefixe_en_developpement(monde):
    c = monde.client()
    r = connecter(c, FONDATEUR_EMAIL, MDP_FONDATEUR)
    assert r.headers["set-cookie"].startswith("cd_2fa=")


# --- copie locale des révocations bornée (D-3604) -------------------------------------------------------------------


def test_revocations_locales_bornees_la_base_fait_foi(db):
    h = Horloge()
    g = GestionnaireSessions(SECRET_SESSION, horloge=h, registre=RegistreRevocations(db, horloge=h),
                             max_revocations_locales=5)
    jetons = [g.emettre(ACTEUR) for _ in range(20)]
    for j in jetons:
        d = g.lire(j)
        g.revoquer(d.sid, debut=d.debut)
    assert len(g._revoquees) <= 5
    for j in jetons:  # les révocations sorties de la copie locale restent refusées (registre en base)
        with pytest.raises(PermissionError):
            g.lire(j)
    for i in range(20):
        h.t += 1
        g.revoquer_utilisateur(f"usr_{i}")
    assert len(g._revoquees_avant) <= 5


def test_revocations_locales_expirees_partent_d_abord():
    h = Horloge()
    g = GestionnaireSessions(SECRET_SESSION, horloge=h, max_revocations_locales=3)
    anciens = [g.emettre(ACTEUR) for _ in range(2)]
    for j in anciens:
        g.revoquer(g.lire(j).sid)
    h.t += g.duree_absolue_s + 120  # ces deux révocations sont sans objet (jetons expirés de toute façon)
    recents = [g.emettre(ACTEUR) for _ in range(3)]
    for j in recents:
        g.revoquer(g.lire(j).sid)
    for j in recents:
        with pytest.raises(PermissionError, match="révoquée"):
            g.lire(j)


# --- sessions actives (D-3603) ---------------------------------------------------------------------------------------


def test_sessions_actives_lister_et_fermer_les_autres(db):
    h = Horloge()
    g = GestionnaireSessions(SECRET_SESSION, horloge=h, registre=RegistreRevocations(db, horloge=h))
    autre_compte = Acteur("usr_autre", Role.client_admin, "demo_ateliers")
    ua_firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
    from controldone.storage.securite import reduire_appareil, reduire_reseau

    j1 = g.emettre(ACTEUR, appareil=reduire_appareil(ua_firefox), reseau=reduire_reseau("203.0.113.57"))
    h.t += 60
    j2 = g.emettre(ACTEUR, appareil=reduire_appareil("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari/604.1"),
                   reseau=reduire_reseau("2001:db8:1:2::9"))
    h.t += 60
    j3 = g.emettre(ACTEUR)
    j_autre = g.emettre(autre_compte)
    s1, s2, s3 = (g.lire(j).sid for j in (j1, j2, j3))
    liste = g.sessions_actives(ACTEUR.id, sid_courant=s2)
    assert [x.sid for x in liste] == [s3, s2, s1]  # la plus récemment active d'abord
    assert [x.courante for x in liste] == [False, True, False]
    assert liste[2].appareil == "Firefox · Linux" and liste[2].reseau == "203.0.113.0/24"
    assert liste[1].appareil == "Safari · iOS" and liste[1].reseau == "2001:db8:1::/48"
    assert "203.0.113.57" not in repr(liste) and "Gecko" not in repr(liste)
    # rotation : dernière activité mise à jour
    h.t += g.rotation_s + 1
    _, nouveau = g.rafraichir(j1)
    assert nouveau and g.sessions_actives(ACTEUR.id)[0].sid == s1
    # on ne ferme pas la session d'un autre compte
    assert not g.fermer_session(ACTEUR.id, g.lire(j_autre).sid)
    g.lire(j_autre)
    assert g.fermer_autres_sessions(ACTEUR.id, s2) == 2
    for j in (nouveau, j3):
        with pytest.raises(PermissionError):
            g.lire(j)
    assert g.lire(j2).sid == s2 and [x.sid for x in g.sessions_actives(ACTEUR.id)] == [s2]
    assert g.fermer_session(ACTEUR.id, s2) and g.sessions_actives(ACTEUR.id) == []
    # expiration par inactivité : absente de la liste
    j4 = g.emettre(ACTEUR)
    h.t += g.inactivite_s + 1
    assert g.sessions_actives(ACTEUR.id) == []
    with pytest.raises(PermissionError):
        g.lire(j4)


def test_sessions_actives_partagees_entre_processus_et_purgees(db):
    from controldone.storage.securite import purger_revocations

    h = Horloge()
    a = GestionnaireSessions(SECRET_SESSION, horloge=h, registre=RegistreRevocations(db, horloge=h))
    db2 = Database(db.url)
    b = GestionnaireSessions(SECRET_SESSION, horloge=h, registre=RegistreRevocations(db2, horloge=h))
    try:
        ja, jb = a.emettre(ACTEUR), b.emettre(ACTEUR)
        assert {x.sid for x in a.sessions_actives(ACTEUR.id)} == {a.lire(ja).sid, b.lire(jb).sid}
        assert b.fermer_autres_sessions(ACTEUR.id, b.lire(jb).sid) == 1
        with pytest.raises(PermissionError):
            b.lire(ja)  # fermée par le processus B, refusée partout
        h.t += 1
        a.revoquer_utilisateur(ACTEUR.id)  # changement de mot de passe : plus aucune session listée
        assert a.sessions_actives(ACTEUR.id) == [] and b.sessions_actives(ACTEUR.id) == []
        a.emettre(ACTEUR)
        h.t += a.duree_absolue_s + 1
        assert purger_revocations(db, maintenant=h.t) >= 1
        from controldone.storage.securite import SessionOuverte

        with db.transaction_systeme() as s:
            assert s.query(SessionOuverte).count() == 0
    finally:
        db2.fermer()


def test_sessions_actives_sans_registre():
    g = GestionnaireSessions(SECRET_SESSION)
    j = g.emettre(ACTEUR)
    assert g.sessions_actives(ACTEUR.id) == [] and g.fermer_autres_sessions(ACTEUR.id, g.lire(j).sid) == 0


def test_connexion_web_enregistre_la_session(monde):
    c = monde.client()
    c.headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
    connecter_client(c, monde)
    c2 = monde.client()
    connecter_client(c2, monde)
    etat = monde.app.state.securite
    from controldone.storage.comptes import utilisateur_par_email

    compte = utilisateur_par_email(monde.pf.db, ADMIN_A)
    sessions = etat.sessions.sessions_actives(compte.id)
    assert len(sessions) == 2 and "Chrome · Windows" in {x.appareil for x in sessions}
    poster(c2, "/espace", "/deconnexion")
    assert len(etat.sessions.sessions_actives(compte.id)) == 1


# --- Caddy : tailles de corps alignées sur l'application (D-3608) ---------------------------------------------------


def test_caddy_corps_bornes_comme_l_application():
    import re

    from controldone.ingest.reception import Limites
    from controldone.web.app import CHEMINS_DEPOT
    from controldone.web.securite import TAILLE_MAX_RAPPORT_CSP

    texte = (Path(__file__).resolve().parents[2] / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    unites = {"KiB": 1024, "MiB": 1024**2}
    blocs = {m.group(1): int(m.group(2)) * unites[m.group(3)]
             for m in re.finditer(r"request_body @(\w+) \{\s*max_size (\d+)(KiB|MiB)\s*\}", texte)}
    matchers = {m.group(1): m.group(2).split() for m in re.finditer(r"@(\w+) (?:not )?path ([^\n]+)", texte)}
    assert set(blocs) == {"depot", "csp", "autres"}
    assert matchers["depot"] == list(CHEMINS_DEPOT)
    assert set(matchers["autres"]) == {*CHEMINS_DEPOT, "/csp-rapport"}  # aucun chemin couvert deux fois
    assert TAILLE_MAX_RAPPORT_CSP <= blocs["csp"] <= 64 * 1024
    assert blocs["depot"] >= Limites().taille_lot + 16 * 1024 * 1024  # l'application reste seule juge du dépôt
    assert 2 * 1024 * 1024 <= blocs["autres"] <= 8 * 1024 * 1024


# --- audit de l'image (D-3609) ---------------------------------------------------------------------------------------


def test_audit_image_bloque_seulement_les_graves_corrigeables():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "audit_dependances", Path(__file__).resolve().parents[2] / "scripts" / "audit_dependances.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    donnees = {"Metadata": {"OS": {"Family": "debian", "Name": "13.7"}}, "Results": [
        {"Target": "image (debian 13.7)", "Vulnerabilities": [
            {"PkgName": "libtiff6", "InstalledVersion": "4.7", "VulnerabilityID": "CVE-FICTIF-1", "Severity": "HIGH"},
            {"PkgName": "libxml2", "InstalledVersion": "2.14", "VulnerabilityID": "CVE-FICTIF-2", "Severity": "CRITICAL",
             "FixedVersion": "2.14.1"},
            {"PkgName": "bash", "InstalledVersion": "5.2", "VulnerabilityID": "CVE-FICTIF-3", "Severity": "LOW",
             "FixedVersion": "5.3"}]},
        {"Target": "Python", "Vulnerabilities": None}]}
    r = audit.resumer_trivy(donnees)
    assert r["systeme"] == "debian 13.7" and r["par_gravite"] == {"HIGH": 1, "CRITICAL": 1, "LOW": 1}
    assert [v["id"] for v in r["corrigeables"]] == ["CVE-FICTIF-2"]
    assert [v["id"] for v in r["non_corrigees"]] == ["CVE-FICTIF-1"]
    cmd = audit.commande_trivy("controldone:2.0.0", Path("/tmp/var/audit/image-trivy.json"))
    assert cmd[-1] == "controldone:2.0.0" and "--scanners" in cmd and "vuln" in cmd


def test_requirements_lock_avec_empreintes():
    racine = Path(__file__).resolve().parents[2]
    for nom in ("requirements.lock", "deploy/requirements-build.lock"):
        texte = (racine / nom).read_text(encoding="utf-8")
        blocs = [b for b in texte.replace("\\\n", " ").splitlines() if b.strip() and not b.startswith("#")]
        assert blocs, nom
        for b in blocs:
            assert "==" in b and "--hash=sha256:" in b, f"{nom} : {b[:60]} sans version figée ou sans empreinte"
    dockerfile = (racine / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("--require-hashes") >= 2 and "--no-build-isolation" in dockerfile
    ignore = (racine / "deploy" / "Dockerfile.dockerignore").read_text(encoding="utf-8")
    assert "!deploy/requirements-build.lock" in ignore
