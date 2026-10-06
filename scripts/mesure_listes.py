"""Mesure des listes filtrées de l'interface sur un gros client **fictif** (dev seulement, D-3801).

Construit la base de démonstration dans un dossier temporaire, recopie les dossiers, constats et écarts du
client ``demo_ateliers`` jusqu'à ``--dossiers`` dossiers (références et clés renumérotées, montants variés,
tout marqué FICTIF), puis chronomètre les pages listées (médiane de ``--tours`` appels, client HTTP de test) :

    python scripts/mesure_listes.py --dossiers 5000

Aucune donnée réelle : la base est créée puis effacée à la fin.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from decimal import Decimal
from pathlib import Path

PAGES = [
    ("client", "/espace/dossiers"),
    ("client", "/espace/dossiers?q=FICTIF-0042"),
    ("client", "/espace/dossiers?statut=ecart_certain&tri=-montant"),
    ("client", "/espace/dossiers?tri=-constats&page=40"),
    ("client", "/espace/recouvrement"),
    ("client", "/espace/recouvrement?statut=ouvert&tri=-montant"),
    ("fondateur", "/admin/validation"),
    ("fondateur", "/admin/validation?niveau=ecart_certain&min=10"),
    ("fondateur", "/admin/validation?controle=C1&tri=-montant"),
]


def _jeton(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    if not m:
        raise SystemExit("jeton CSRF absent")
    return m.group(1)


def _grossir(pf, tenant: str, cible: int) -> int:
    from controldone.storage.models import Constat, Dossier, Ecart

    with pf.db.transaction_systeme() as s:
        dossiers = list(s.query(Dossier).filter(Dossier.tenant_id == tenant))
        constats = list(s.query(Constat).filter(Constat.tenant_id == tenant))
        ecarts = list(s.query(Ecart).filter(Ecart.tenant_id == tenant))
        par_dossier: dict[str, list[Constat]] = {}
        for c in constats:
            par_dossier.setdefault(c.dossier_id, []).append(c)
        ecart_de = {e.constat_id: e for e in ecarts}
        n = len(dossiers)
        i = 0
        while n < cible:
            modele = dossiers[i % len(dossiers)]
            i += 1
            n += 1
            did = "dos_" + uuid.uuid4().hex[:20]
            contenu = dict(modele.contenu or {})
            contenu["cles"] = {"num_facture_transitaire": [f"FICTIF-{n:04d}"], "mrn": [f"26FR{n:014d}"],
                               "ref_transport": [f"TR-FICTIF-{n}"], "num_facture_commerciale": [f"FC-{n:05d}"]}
            s.add(Dossier(id=did, tenant_id=tenant, lot_id=modele.lot_id, reference=f"GZ{n:05d}",
                          version=modele.version, statut_global=modele.statut_global, contenu=contenu))
            for c in par_dossier.get(modele.id, []):
                cid = "con_" + uuid.uuid4().hex[:20]
                m = c.montant_en_jeu
                if m is not None:
                    m = (m + Decimal(n % 97)).quantize(Decimal("0.01"))
                s.add(Constat(id=cid, tenant_id=tenant, resultat_id=None, dossier_id=did,
                              dossier_version=modele.version, controle_id=c.controle_id, niveau=c.niveau,
                              montant_en_jeu=m, nature_montant=c.nature_montant,
                              statut_validation=c.statut_validation, contenu=dict(c.contenu or {})))
                e = ecart_de.get(c.id)
                if e is not None:
                    j = dict(e.contenu or {})
                    j["dossier_id"] = did
                    s.add(Ecart(id="eca_" + uuid.uuid4().hex[:20], tenant_id=tenant, constat_id=cid,
                                transitaire_id=e.transitaire_id, statut=e.statut, montant_initial=m or e.montant_initial,
                                reste=m or e.reste, contenu=j))
            if n % 500 == 0:
                s.flush()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dossiers", type=int, default=5000)
    ap.add_argument("--tours", type=int, default=5)
    args = ap.parse_args()

    from cryptography.fernet import Fernet

    racine = Path(tempfile.mkdtemp(prefix="mesure_listes_"))
    cle = Fernet.generate_key()
    os.environ.update(CONTROLDONE_ENV="test", CONTROLDONE_MASTER_KEY=cle.decode(),
                      CONTROLDONE_SECRET_KEY="secret-de-mesure-FICTIF-0123456789abcdef",
                      CONTROLDONE_DATA_DIR=str(racine / "var"))
    try:
        from fastapi.testclient import TestClient

        from controldone.auth.totp import code_totp
        from controldone.ingest.reception import Limites
        from controldone.services.demo_init import initialiser_demo
        from controldone.services.plateforme import Plateforme
        from controldone.storage import Database, FileVault
        from controldone.web import ParametresWeb, create_app

        pf = Plateforme(db=Database(f"sqlite:///{racine}/plateforme.db"), vault=FileVault(racine / "coffre", [cle]),
                        cles_maitresses=[cle], limites=Limites(), dossier_sorties=racine / "sorties")
        res = initialiser_demo(pf, mot_de_passe_fondateur="phrase-de-passe-FICTIVE-mesure")
        t0 = time.perf_counter()
        n = _grossir(pf, "demo_ateliers", args.dossiers)
        print(f"client fictif demo_ateliers : {n} dossiers ({time.perf_counter() - t0:.1f} s de préparation)")
        app = create_app(ParametresWeb(plateforme=pf, secrets_session=["secret-de-mesure-FICTIF-0123456789abcdef"],
                                       prod=False, etat_partage=False))
        comptes = {c.email: c.mot_de_passe for c in res.comptes}
        clients = {}
        c = TestClient(app, base_url="http://testserver")
        email = "admin@ateliers-demo.test"
        c.post("/connexion", data={"csrf": _jeton(c.get("/connexion").text), "email": email,
                                   "mot_de_passe": comptes[email]})
        clients["client"] = c
        f = TestClient(app, base_url="http://testserver")
        f.post("/connexion", data={"csrf": _jeton(f.get("/connexion").text),
                                   "email": "fondateur@controldone-demo.test",
                                   "mot_de_passe": "phrase-de-passe-FICTIVE-mesure"})
        f.post("/connexion/totp", data={"csrf": _jeton(f.get("/connexion/totp").text),
                                        "code": code_totp(res.totp_secret)})
        clients["fondateur"] = f
        print(f"{'page':58} {'médiane':>9} {'statut':>6}")
        for qui, url in PAGES:
            durees = []
            statut = 0
            for _ in range(args.tours):
                t = time.perf_counter()
                r = clients[qui].get(url)
                durees.append(time.perf_counter() - t)
                statut = r.status_code
            print(f"{url:58} {statistics.median(durees) * 1000:7.0f} ms {statut:>6}")
        pf.db.fermer()
    finally:
        shutil.rmtree(racine, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
