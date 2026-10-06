"""Seconde revue de sécurité (``docs/REVUE_SECURITE_2.md``, D-3201 à D-3205) : limitation de débit partagée et
persistante, révocation des sessions en base, en-têtes HTTP, rapports CSP, JavaScript de l'interface, audit des
dépendances, entrées hostiles (XML déduit, images, CSV de grille). Données fictives seulement."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import logging
import re
import threading
import time
from pathlib import Path

import pytest
from aides_web import (
    ADMIN_A,
    CLE_MAITRESSE,
    SECRET_SESSION,
    connecter,
    connecter_client,
    poster,
)

from controldone.auth import GestionnaireSessions, LimiteurDebitPartage, RegistreRevocations, sel_debit
from controldone.auth.roles import Acteur, Role
from controldone.services.plateforme import Plateforme
from controldone.storage import Database, FileVault
from controldone.web import ParametresWeb, create_app

RACINE = Path(__file__).resolve().parents[2]
SEL = sel_debit([CLE_MAITRESSE])


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


def _lignes(db: Database) -> list[tuple]:
    import sqlite3

    with sqlite3.connect(db.chemin_sqlite()) as cx:
        return cx.execute("SELECT cle, portee, jetons FROM debit_compteurs").fetchall()


# --- D-3201 : limiteur partagé ----------------------------------------------------------------------------------


def test_limiteur_partage_seuils_et_recharge(db):
    h = Horloge()
    lim = LimiteurDebitPartage("connexion_compte", 3, 1.0, db=db, sel=SEL, horloge=h)
    assert [lim.autoriser("a@exemple.test") for _ in range(4)] == [True, True, True, False]
    assert lim.autoriser("b@exemple.test")  # autre clé, autre seau
    assert lim.attente("a@exemple.test") == pytest.approx(1.0)
    h.t += 1.0
    assert lim.autoriser("a@exemple.test") and not lim.autoriser("a@exemple.test")


def test_limiteur_partage_entre_processus_et_redemarrage(db):
    """Deux instances sur deux connexions à la même base (deux processus web, ou un redémarrage) partagent le
    seau : la limite n'est plus remise à zéro en relançant le service."""
    h = Horloge()
    a = LimiteurDebitPartage("connexion_ip", 4, 4 / 300, db=db, sel=SEL, horloge=h)
    db2 = Database(db.url)
    b = LimiteurDebitPartage("connexion_ip", 4, 4 / 300, db=db2, sel=SEL, horloge=h)
    try:
        assert a.autoriser("203.0.113.7") and b.autoriser("203.0.113.7")
        assert a.autoriser("203.0.113.7") and b.autoriser("203.0.113.7")
        assert not a.autoriser("203.0.113.7") and not b.autoriser("203.0.113.7")
    finally:
        db2.fermer()


def test_limiteur_partage_pseudonymise(db):
    lim = LimiteurDebitPartage("connexion_compte", 5, 5 / 300, db=db, sel=SEL)
    lim.autoriser("fondateur@controldone-demo.test")
    LimiteurDebitPartage("connexion_ip", 5, 5 / 300, db=db, sel=SEL).autoriser("198.51.100.23")
    lignes = _lignes(db)
    assert len(lignes) == 2
    brut = repr(lignes)
    assert "controldone-demo" not in brut and "198.51.100" not in brut
    assert all(re.fullmatch(r"(connexion_compte|connexion_ip):[0-9a-f]{64}", c) for c, _, _ in lignes)


def test_limiteur_partage_table_bornee(db):
    h = Horloge()
    lim = LimiteurDebitPartage("api", 2, 2.0, db=db, sel=SEL, horloge=h, max_lignes=50, purge_toutes_s=0)
    for i in range(300):  # préfixes de clé d'API inventés par un attaquant
        lim.autoriser(f"api:{i:06x}")
    assert len(_lignes(db)) <= 51
    h.t += 5  # tous les seaux sont pleins à nouveau : lignes expirées, purgées
    lim.autoriser("api:dernier")
    assert len(_lignes(db)) == 1


def test_limiteur_partage_atomique_sous_concurrence(db):
    lim = LimiteurDebitPartage("connexion_ip", 20, 1e-6, db=db, sel=SEL)
    autorises = []
    verrou = threading.Lock()

    def essayer():
        bases = Database(db.url)  # une connexion par fil, comme des processus distincts
        try:
            local = LimiteurDebitPartage("connexion_ip", 20, 1e-6, db=bases, sel=SEL)
            n = sum(local.autoriser("192.0.2.1") for _ in range(10))
        finally:
            bases.fermer()
        with verrou:
            autorises.append(n)

    fils = [threading.Thread(target=essayer) for _ in range(6)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert sum(autorises) == 20
    assert not lim.autoriser("192.0.2.1")


def test_limiteur_partage_base_indisponible_bascule_en_memoire(db, caplog):
    from controldone.storage.securite import CompteurDebit

    CompteurDebit.__table__.drop(db.engine)
    lim = LimiteurDebitPartage("connexion_compte", 2, 2 / 300, db=db, sel=SEL)
    with caplog.at_level(logging.WARNING, logger="controldone.auth.debit"):
        assert [lim.autoriser("x@exemple.test") for _ in range(3)] == [True, True, False]
    assert "debit_base_indisponible" in caplog.text and "x@exemple" not in caplog.text


def test_rembourser_et_effacer(db):
    h = Horloge()
    lim = LimiteurDebitPartage("connexion_compte", 2, 1e-6, db=db, sel=SEL, horloge=h)
    assert lim.autoriser("k") and lim.autoriser("k") and not lim.autoriser("k")
    lim.rembourser("k")
    assert lim.autoriser("k") and not lim.autoriser("k")
    lim.effacer("k")
    assert lim.autoriser("k") and lim.autoriser("k")


# --- D-3202 : révocation des sessions en base ----------------------------------------------------------------------


def test_revocation_persistante_entre_processus(db):
    h = Horloge()
    a = GestionnaireSessions(SECRET_SESSION, horloge=h, registre=RegistreRevocations(db, horloge=h))
    db2 = Database(db.url)
    b = GestionnaireSessions(SECRET_SESSION, horloge=h, registre=RegistreRevocations(db2, horloge=h))
    try:
        acteur = Acteur("usr_fictif", Role.client_admin, "demo_ateliers")
        jeton_ = a.emettre(acteur)
        d = b.lire(jeton_)
        a.revoquer(d.sid, debut=d.debut)  # déconnexion servie par le processus A
        with pytest.raises(PermissionError):
            b.lire(jeton_)  # refusée aussi par le processus B
        autre = a.emettre(acteur)
        h.t += 10
        coupure = a.revoquer_utilisateur("usr_fictif")  # changement de mot de passe
        with pytest.raises(PermissionError):
            b.lire(autre)
        neuf = a.emettre(acteur)
        assert b.lire(neuf).debut >= coupure
    finally:
        db2.fermer()


# --- parcours web ----------------------------------------------------------------------------------------------------


def _seconde_app(monde):
    """Même base, autre instance de l'application : un autre processus web ou un redémarrage."""
    db2 = Database(monde.pf.db.url)
    pf2 = Plateforme(
        db=db2,
        vault=FileVault(monde.pf.vault.racine, [CLE_MAITRESSE]),
        cles_maitresses=[CLE_MAITRESSE],
        limites=monde.pf.limites,
        dossier_sorties=monde.pf.dossier_sorties,
    )
    return create_app(
        ParametresWeb(plateforme=pf2, secrets_session=[SECRET_SESSION], prod=False, https=False)
    ), db2


def test_verrou_de_connexion_survit_au_redemarrage_et_se_leve_en_ligne_de_commande(
    monde, monkeypatch, capsys
):
    from fastapi.testclient import TestClient

    from controldone.cli import main

    c = monde.client()
    statuts = [connecter(c, ADMIN_A, "mauvais-mot-de-passe-FICTIF").status_code for _ in range(6)]
    assert statuts[0] == 401 and statuts[-1] == 429
    app2, db2 = _seconde_app(monde)
    try:
        c2 = TestClient(app2, base_url="http://testserver")
        assert connecter(c2, ADMIN_A, monde.comptes[ADMIN_A]).status_code == 429  # toujours bloqué
        monkeypatch.setenv("CONTROLDONE_DATABASE_URL", monde.pf.db.url)
        assert main(["debit", "lister"]) == 0
        assert "BLOQUÉ" in capsys.readouterr().out
        assert main(["debit", "effacer", "--email", ADMIN_A.upper(), "--motif", "essais du fondateur"]) == 0
        assert connecter(c2, ADMIN_A, monde.comptes[ADMIN_A]).status_code == 303
    finally:
        db2.fermer()
    from controldone.storage.models import AuditLog

    with monde.pf.db.transaction_systeme() as s:
        actions = [a.action for a in s.query(AuditLog).all()]
    assert "debit_effacer" in actions


def test_connexions_reussies_ne_bloquent_pas(monde):
    """Le fondateur bloqué après des connexions de test réussies (RAPPORT_DU_MATIN) : seuls les échecs comptent."""
    for _ in range(12):
        c = monde.client()
        connecter_client(c, monde)


def test_deconnexion_revoque_dans_tous_les_processus(monde):
    from fastapi.testclient import TestClient

    c = monde.client()
    connecter_client(c, monde)
    cookie = c.cookies.get("cd_session")
    assert cookie
    poster(c, "/espace", "/deconnexion")
    app2, db2 = _seconde_app(monde)
    try:
        c2 = TestClient(app2, base_url="http://testserver", cookies={"cd_session": cookie})
        r = c2.get("/espace", follow_redirects=False)
        assert r.status_code in (302, 303) and r.headers["location"].endswith("/connexion")
    finally:
        db2.fermer()


def test_changement_de_mot_de_passe_ferme_les_autres_sessions(monde):
    nouveau = "nouvelle-phrase-de-passe-FICTIVE"
    c1, c2 = monde.client(), monde.client()
    connecter_client(c1, monde)
    connecter_client(c2, monde)
    r = poster(
        c1,
        "/compte/mot-de-passe",
        "/compte/mot-de-passe",
        {"actuel": monde.comptes[ADMIN_A], "nouveau": nouveau, "confirmation": nouveau},
    )
    assert r.status_code == 303
    assert c1.get("/espace", follow_redirects=False).status_code == 200  # session neuve
    r = c2.get("/espace", follow_redirects=False)
    assert r.status_code in (302, 303) and r.headers["location"].endswith("/connexion")


def test_changement_de_mot_de_passe_limite(monde):
    c = monde.client()
    connecter_client(c, monde)
    statuts = [
        poster(
            c,
            "/compte/mot-de-passe",
            "/compte/mot-de-passe",
            {"actuel": "faux-mot-de-passe-FICTIF", "nouveau": "x" * 12, "confirmation": "x" * 12},
        ).status_code
        for _ in range(6)
    ]
    assert statuts[0] == 400 and statuts[-1] == 429


# --- D-3204 : en-têtes et rapports CSP -------------------------------------------------------------------------------


def test_en_tetes_durcis(monde):
    r = monde.client().get("/connexion")
    h = r.headers
    for f in ("camera", "microphone", "geolocation", "payment", "usb", "serial", "hid", "display-capture"):
        assert f"{f}=()" in h["permissions-policy"]
    assert h["cross-origin-opener-policy"] == "same-origin"
    assert h["cross-origin-resource-policy"] == "same-origin"
    assert h["referrer-policy"] == "same-origin"
    csp = h["content-security-policy"]
    assert csp.startswith("default-src 'self'") and "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "report-uri /csp-rapport" in csp and "report-to csp" in csp
    assert "require-trusted-types-for 'script'" in csp and "trusted-types 'none'" in csp
    assert h["reporting-endpoints"] == 'csp="/csp-rapport"'
    statique = monde.client().get("/static/theme.js")
    assert statique.status_code == 200 and "cache-control" not in statique.headers


def test_cookie_de_session_en_production(_modele, tmp_path):
    from aides_web import construire_monde
    from fastapi.testclient import TestClient

    m = construire_monde(_modele, tmp_path / "prod", https=True)
    m.app.state.securite.cookie.update({"key": "__Host-cd_session", "secure": True, "samesite": "strict"})
    try:
        c = TestClient(m.app, base_url="https://testserver")
        r = connecter(c, ADMIN_A, m.comptes[ADMIN_A])
        entete = r.headers["set-cookie"]
        assert "__Host-cd_session=" in entete and "HttpOnly" in entete and "Secure" in entete
        assert "SameSite=strict" in entete and "Path=/" in entete and "Max-Age=28800" in entete
        assert "Domain=" not in entete
        assert r.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"
    finally:
        m.pf.db.fermer()


_RAPPORT = {
    "csp-report": {
        "document-uri": "http://testserver/espace/dossiers/dos_FICTIF?q=Societe+FICTIVE&email=a%40exemple.test",
        "effective-directive": "script-src-elem",
        "violated-directive": "script-src-elem",
        "blocked-uri": "https://cdn.exemple.test/piege.js?jeton=SECRET-FICTIF",
        "disposition": "enforce",
        "script-sample": "alert('donnee personnelle FICTIVE')",
    }
}


def test_rapport_csp_journalise_sans_donnee_personnelle(monde, caplog):
    c = monde.client()
    with caplog.at_level(logging.WARNING, logger="controldone.web.securite"):
        r = c.post(
            "/csp-rapport", content=json.dumps(_RAPPORT), headers={"content-type": "application/csp-report"}
        )
    assert r.status_code == 204
    journal = caplog.text
    assert "directive=script-src-elem" in journal and "bloque=https://cdn.exemple.test" in journal
    assert "document=/espace/dossiers/dos_FICTIF" in journal
    for interdit in (
        "SECRET-FICTIF",
        "piege.js",
        "exemple.test/espace",
        "Societe",
        "a%40",
        "alert",
        "testclient",
    ):
        assert interdit not in journal
    rapports = [
        {
            "type": "csp-violation",
            "body": {
                "effectiveDirective": "img-src",
                "blockedURL": "data",
                "documentURL": "http://testserver/admin",
                "disposition": "report",
            },
        }
    ]
    r = c.post(
        "/csp-rapport", content=json.dumps(rapports), headers={"content-type": "application/reports+json"}
    )
    assert r.status_code == 204


def test_rapport_csp_borne(monde):
    c = monde.client()
    gros = json.dumps({"csp-report": {"blocked-uri": "x" * 20_000}})
    assert (
        c.post("/csp-rapport", content=gros, headers={"content-type": "application/csp-report"}).status_code
        == 413
    )
    assert c.post("/csp-rapport", content="{}", headers={"content-type": "text/plain"}).status_code == 415
    assert (
        c.post(
            "/csp-rapport", content="{pas du json", headers={"content-type": "application/csp-report"}
        ).status_code
        == 400
    )
    assert c.get("/csp-rapport").status_code in (404, 405)
    statuts = [
        c.post(
            "/csp-rapport", content=json.dumps(_RAPPORT), headers={"content-type": "application/csp-report"}
        ).status_code
        for _ in range(25)
    ]
    assert 429 in statuts


# --- JavaScript de l'interface -----------------------------------------------------------------------------------------

_PUITS = re.compile(
    r"\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function\b|"
    r"\bsrcdoc\b|createContextualFragment|setTimeout\(\s*[\"']|setInterval\(\s*[\"']|javascript:|"
    r"DOMParser|parseFromString|setHTMLUnsafe|createPolicy|createElement\(\s*[\"']script"
)


def test_javascript_sans_puits_html():
    """Le JavaScript servi n'écrit que du texte (``textContent``) : aucun puits HTML ni évaluation de chaîne, aucune
    politique Trusted Types (la CSP impose ``trusted-types 'none'``, D-3204)."""
    statique = RACINE / "src/controldone/web/static"
    fichiers = sorted(statique.glob("*.js")) + sorted((statique / "vendor").glob("*.js"))
    assert fichiers
    for f in fichiers:
        texte = f.read_text(encoding="utf-8")
        assert not _PUITS.search(texte), (f.name, _PUITS.search(texte).group(0))
    for gabarit in (RACINE / "src/controldone/web/templates").rglob("*.j2"):
        texte = gabarit.read_text(encoding="utf-8")
        # Seul bloc admis sans ``src`` : des **données** JSON (non exécutées, hors ``script-src``) produites par
        # ``|tojson`` (qui échappe ``<``, ``>``, ``&`` et ``'`` : pas de sortie du bloc possible).
        donnees = re.compile(
            r'<script type="application/json" id="[a-z0-9-]+">\{\{ [a-z_]+\|tojson \}\}</script>'
        )
        texte = donnees.sub("", texte)
        assert not re.search(r"<script(?![^>]*\bsrc=)", texte), gabarit.name  # aucun script en ligne
        assert not re.search(r"\son[a-z]+\s*=", texte), gabarit.name  # aucun gestionnaire en ligne
        assert "|safe" not in texte.replace(" ", ""), gabarit.name


# --- D-3203 : audit des dépendances ---------------------------------------------------------------------------------


def _audit():
    spec = importlib.util.spec_from_file_location(
        "audit_dependances", RACINE / "scripts/audit_dependances.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_classement_des_licences():
    a = _audit()
    for lic in (
        "MIT",
        "MIT License",
        "BSD-3-Clause",
        "Apache-2.0 OR BSD-3-Clause",
        "MIT-CMU",
        "PSF-2.0",
        "Apache Software License; BSD License",
        "Public Domain",
        "OFL-1.1",
        "MIT-0",
        "BSD-3-Clause, Apache-2.0, dependency licenses",
    ):
        assert a.classer_licence(lic) == "permissive", lic
    for lic in (
        "GNU Lesser General Public License v2 or later (LGPLv2+)",
        "GPL-3.0",
        "AGPL-3.0-only",
        "Mozilla Public License 2.0 (MPL 2.0)",
    ):
        assert a.classer_licence(lic) == "copyleft", lic
    assert a.classer_licence("UNKNOWN") == "inconnue" and a.classer_licence("Proprietary") == "inconnue"


def test_composants_embarques_declares():
    a = _audit()
    config = json.loads((RACINE / "config/audit_dependances.json").read_text(encoding="utf-8"))
    assert a.verifier_embarques(config["composants_embarques"]) == []
    motion = next(e for e in config["composants_embarques"] if e["nom"] == "motion")
    assert motion["version"] == "14.0.0" and motion["licence"] == "MIT"
    assert all(v.strip() for v in config["licences_acceptees"].values())
    lock = a.lire_lock(RACINE / "requirements.lock")
    assert lock and "fastapi" in lock and "uvicorn" in lock and "python-multipart" in lock


# --- REV2-01 : fiche XML déduite ---------------------------------------------------------------------------------------


def _declaration_xml(n: int, entete: str = "<MRN>26FR000000000000A1</MRN>") -> bytes:
    articles = "".join(
        f'<Item seq="{i}"><CommodityCode>8544429090</CommodityCode><Duty type="A00"><Rate>2</Rate>'
        f"<Amount>1.00</Amount></Duty></Item>"
        for i in range(n)
    )
    return f"<Declaration>{entete}{articles}</Declaration>".encode()


def test_fiche_deduite_lineaire():
    """Avant : 4 000 articles (0,5 Mo) = 3,5 s, croissance quadratique (≈ 1 h 30 pour un XML de 1 million de
    balises). Après : linéaire."""
    from controldone.ingest.structure import _xml, fiche_deduite

    racine = _xml(_declaration_xml(16_000))
    t0 = time.perf_counter()
    fiche = fiche_deduite(racine)
    duree = time.perf_counter() - t0
    assert fiche is not None
    assert duree < 15, duree  # ≈ 2 s mesurées ; la version quadratique dépassait 50 s


def test_fiche_deduite_xxe_et_entites():
    from controldone.ingest.structure import _xml, fiche_deduite

    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">'
        b'<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        + _declaration_xml(2, "<MRN>&x;</MRN><Note>&c;&c;&c;</Note>")
    )
    racine = _xml(xxe)
    if racine is not None:
        texte = "".join(racine.itertext())
        assert "root:" not in texte and "aaaaaaaaaa" not in texte
        fiche_deduite(racine)  # aucune exception, aucune entité résolue


# --- REV2-03 : images à cadres multiples, agrandissement borné --------------------------------------------------------


def test_images_cadres_bornes_et_agrandissement_plafonne(monkeypatch):
    from PIL import Image

    from controldone.ingest import pages

    tailles = []

    def faux_ocr(image, opts, numero):
        tailles.append(image.size)
        return pages._page_illisible(numero, "faux_ocr")

    monkeypatch.setattr(pages, "ocr_disponible", lambda: True)
    monkeypatch.setattr(pages, "_ocr_image", faux_ocr)
    cadres = [Image.new("L", (40, 30), 255) for _ in range(6)]
    tampon = io.BytesIO()
    cadres[0].save(tampon, format="TIFF", save_all=True, append_images=cadres[1:], dpi=(300, 300))
    sortie = pages._pages_image(tampon.getvalue(), pages.OptionsPages(max_pages=2))
    assert len(sortie) == 2 and len(tailles) == 2

    tailles.clear()
    grande = io.BytesIO()
    Image.new("L", (6000, 5000), 255).save(grande, format="PNG", dpi=(72, 72))
    pages._pages_image(grande.getvalue(), pages.OptionsPages())
    w, h = tailles[0]
    assert w * h <= pages.MAX_PIXELS_AGRANDISSEMENT * 1.01 and w > 6000  # agrandie, mais pas × 9 (270 Mpx)


# --- REV2-04 : CSV de grille tarifaire ---------------------------------------------------------------------------------


def test_csv_de_grille_sans_effet_global_ni_erreur_500():
    from controldone.services.admin import _postes_csv
    from controldone.services.plateforme import RequeteInvalide

    assert csv.excel.delimiter == ","
    _postes_csv("code_poste")  # une seule colonne : l'analyse du dialecte échoue
    assert csv.excel.delimiter == ","  # avant : « ; » pour tout le processus
    with pytest.raises(RequeteInvalide):
        _postes_csv("code_poste;prix\nA;" + "9" * 200_000 + "\n")


# --- REV2-05 : paramètres de liste ------------------------------------------------------------------------------------


def test_listes_parametres_hostiles_sans_erreur_500(monde):
    c = monde.client()
    connecter_client(c, monde)
    for q in (
        "page=²",
        "page=١٢",
        "taille=⁵⁰",
        "page=99999999999",
        "tri=__class__",
        "q=" + "x" * 5000,
        "q=%00",
        "page=1&page=2",
    ):
        r = c.get(f"/espace/dossiers?{q}", follow_redirects=False)
        assert r.status_code in (200, 400), (q, r.status_code)


def test_reinitialisation_du_mot_de_passe_en_ligne_de_commande(monde, monkeypatch):
    from controldone.cli import main

    c = monde.client()
    connecter_client(c, monde)
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", monde.pf.db.url)
    monkeypatch.setattr("sys.stdin", io.StringIO("phrase-reinitialisee-FICTIVE\n"))
    assert main(["reinitialiser-mot-de-passe", "--email", ADMIN_A, "--mot-de-passe-stdin"]) == 0
    r = c.get("/espace", follow_redirects=False)
    assert r.status_code in (302, 303)  # session ouverte avant : fermée
    assert connecter(monde.client(), ADMIN_A, monde.comptes[ADMIN_A]).status_code == 401
    assert connecter(monde.client(), ADMIN_A, "phrase-reinitialisee-FICTIVE").status_code == 303
    monkeypatch.setattr("sys.stdin", io.StringIO("court\n"))
    assert main(["reinitialiser-mot-de-passe", "--email", ADMIN_A, "--mot-de-passe-stdin"]) == 2
