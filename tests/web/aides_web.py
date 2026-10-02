"""Aides des tests web (données fictives)."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from controldone.auth.totp import code_totp
from controldone.ingest.reception import Limites
from controldone.services.plateforme import Plateforme
from controldone.storage import Database, FileVault
from controldone.web import ParametresWeb, create_app

CLE_MAITRESSE = Fernet.generate_key()
SECRET_SESSION = "secret-de-session-des-tests-FICTIF-0123456789"
MDP_FONDATEUR = "phrase-de-passe-fondateur-FICTIVE"


def plateforme(racine: Path, limites: Limites | None = None) -> Plateforme:
    db = Database(f"sqlite:///{racine}/plateforme.db")
    return Plateforme(db=db, vault=FileVault(racine / "coffre", [CLE_MAITRESSE]), cles_maitresses=[CLE_MAITRESSE],
                      limites=limites or Limites(), dossier_sorties=racine / "sorties")


@dataclass
class Modele:
    racine: Path
    totp: str
    comptes: dict[str, str]
    cles: dict[str, str]
    ids: dict[str, dict[str, list[str]]] = field(default_factory=dict)


@dataclass
class Monde:
    pf: Plateforme
    app: object
    totp: str
    comptes: dict[str, str]
    cles: dict[str, str]
    ids: dict[str, dict[str, list[str]]]

    def client(self) -> TestClient:
        return TestClient(self.app, base_url="http://testserver")


def construire_monde(modele: Modele, tmp_path: Path, *, limites: Limites | None = None, https: bool = False) -> Monde:
    racine = tmp_path / "monde"
    shutil.copytree(modele.racine, racine)
    pf = plateforme(racine, limites)
    app = create_app(ParametresWeb(plateforme=pf, secrets_session=[SECRET_SESSION], prod=False, https=https,
                                   limites=limites or Limites()))
    return Monde(pf=pf, app=app, totp=modele.totp, comptes=dict(modele.comptes), cles=dict(modele.cles), ids=modele.ids)


# --- aides ----------------------------------------------------------------------------------------------------

ADMIN_A = "admin@ateliers-demo.test"
LECTEUR_A = "lecture@ateliers-demo.test"
ADMIN_B = "admin@site-nord-demo.test"
FONDATEUR_EMAIL = "fondateur@controldone-demo.test"


def jeton(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "jeton CSRF absent de la page"
    return m.group(1)


def connecter(c: TestClient, email: str, mdp: str):
    t = jeton(c.get("/connexion").text)
    return c.post("/connexion", data={"csrf": t, "email": email, "mot_de_passe": mdp}, follow_redirects=False)


def connecter_fondateur(c: TestClient, monde: Monde, *, t: float | None = None) -> None:
    r = connecter(c, FONDATEUR_EMAIL, MDP_FONDATEUR)
    assert r.status_code == 303 and r.headers["location"] == "/connexion/totp"
    tj = jeton(c.get("/connexion/totp").text)
    r = c.post("/connexion/totp", data={"csrf": tj, "code": code_totp(monde.totp, t)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin", r.text[:500]


def connecter_client(c: TestClient, monde: Monde, email: str = ADMIN_A) -> None:
    r = connecter(c, email, monde.comptes[email])
    assert r.status_code == 303 and r.headers["location"] == "/espace"


def poster(c: TestClient, page: str, url: str, donnees: dict | None = None, **kw):
    """POST d'un formulaire avec le jeton CSRF lu sur ``page``."""
    t = jeton(c.get(page).text)
    return c.post(url, data={"csrf": t, **(donnees or {})}, follow_redirects=False, **kw)


def executer_jobs(monde: Monde) -> int:
    import controldone.jobs.handlers  # noqa: F401
    from controldone.jobs.worker import Worker

    w = Worker(monde.pf.db, worker_id="tests", lease_s=300, services={"vault": monde.pf.vault})
    n = 0
    while w.executer_un() is not None:
        n += 1
    return n
