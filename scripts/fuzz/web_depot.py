"""Échantillons hostiles envoyés au point de dépôt de l'API web (``POST /api/v1/lots``) d'un serveur neuf.

    python scripts/fuzz/web_depot.py var/fuzz/samples --nombre 80 --out var/fuzz/web.json

Répertoire de données temporaire, client et clé d'API créés à la volée, ``controldone serve`` (worker intégré)
lancé sur un port libre puis arrêté. Pour chaque échantillon : code HTTP, réponse, temps ; le serveur doit rester
vivant (``/sante``) ; à la fin on attend que la file se vide et l'on relève l'état des lots et des jobs, la
mémoire du serveur et les traces d'exception de son journal.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rss_mo(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    except OSError:
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--nombre", type=int, default=80)
    ap.add_argument("--out", required=True)
    ap.add_argument("--attente-max", type=float, default=1800)
    a = ap.parse_args()
    import httpx
    from cryptography.fernet import Fernet

    data = Path(tempfile.mkdtemp(prefix="cdo-web-fuzz-"))
    env = {**os.environ, "CONTROLDONE_ENV": "dev", "CONTROLDONE_DATA_DIR": str(data),
           "CONTROLDONE_DATABASE_URL": f"sqlite:///{data}/controldone.db",
           "CONTROLDONE_MASTER_KEY": Fernet.generate_key().decode(), "CONTROLDONE_LOG_LEVEL": "WARNING"}
    env.pop("CONTROLDONE_PAGES_CACHE_DIR", None)
    env.pop("ANTHROPIC_API_KEY", None)
    # Client et clé d'API (processus séparé : réglages lus depuis cet environnement)
    prep = subprocess.run([sys.executable, "-c", r"""
from controldone.auth.roles import Acteur, Role
from controldone.services.admin import creer_client, creer_cle
from controldone.services.plateforme import Plateforme
pf = Plateforme.depuis_env(); pf.db.creer_schema()
f = Acteur("usr_fondateur_fuzz", Role.fondateur)
tid = creer_client(pf, f, "Client fuzz FICTIF")
from controldone.services.admin import creer_utilisateur_client
from controldone.storage.comptes import utilisateur_par_email
creer_utilisateur_client(pf, f, tid, "fuzz@exemple.invalid", "client_admin")
a = Acteur(utilisateur_par_email(pf.db, "fuzz@exemple.invalid").id, Role.client_admin, tid)
with pf.db.tenant(tid, a) as s:
    print(creer_cle(s, "fuzz").cle)
"""], env=env, capture_output=True, text=True, check=True)
    cle = prep.stdout.strip().splitlines()[-1]
    port = _port_libre()
    journal = open(data / "serve.log", "wb")  # noqa: SIM115 - fermé après l'arrêt du serveur
    serveur = subprocess.Popen([sys.executable, "-m", "controldone.cli", "serve", "--port", str(port)], env=env,
                               stdout=journal, stderr=subprocess.STDOUT, start_new_session=True)
    base = f"http://127.0.0.1:{port}"
    resultats = []
    try:
        for _ in range(120):
            try:
                if httpx.get(base + "/sante", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        fichiers = sorted(p for s in a.sources for p in Path(s).rglob("*") if p.is_file())
        rnd = random.Random(1606)
        choix = sorted(rnd.sample(fichiers, min(a.nombre, len(fichiers))))
        client = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {cle}"}, timeout=300)
        pic = 0.0
        for p in choix:
            t = time.monotonic()
            try:
                r = client.post("/api/v1/lots", files=[("fichiers", (p.name, p.read_bytes(),
                                                                       "application/octet-stream"))])
                code, corps = r.status_code, r.text[:400]
            except httpx.HTTPError as e:
                code, corps = -1, type(e).__name__
            vivant = serveur.poll() is None and httpx.get(base + "/sante", timeout=10).status_code == 200
            pic = max(pic, _rss_mo(serveur.pid))
            resultats.append({"echantillon": str(p), "http": code, "reponse": corps,
                              "duree_s": round(time.monotonic() - t, 2), "serveur_vivant": vivant})
            print(code, round(time.monotonic() - t, 2), "vivant" if vivant else "MORT", p, flush=True)
            if not vivant:
                break
            time.sleep(0.6)  # sous le débit de l'API (2 requêtes/s)
        # attente de la file
        debut = time.monotonic()
        etat = {}
        while time.monotonic() - debut < a.attente_max:
            q = subprocess.run([sys.executable, "-c", r"""
import json, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
jobs = dict(c.execute("select statut, count(*) from jobs group by statut").fetchall())
lots = dict(c.execute("select statut, count(*) from lots group by statut").fetchall())
err = [r[0] for r in c.execute("select last_error from jobs where last_error is not null").fetchall()]
print(json.dumps({"jobs": jobs, "lots": lots, "erreurs": err}))
""", str(data / "controldone.db")], capture_output=True, text=True, env=env)
            etat = json.loads(q.stdout or "{}")
            pic = max(pic, _rss_mo(serveur.pid))
            if not set(etat.get("jobs", {})) - {"done", "dead"}:
                break
            time.sleep(5)
        vivant_fin = serveur.poll() is None
        rss_fin = _rss_mo(serveur.pid)
    finally:
        serveur.send_signal(signal.SIGTERM)
        try:
            serveur.wait(30)
        except subprocess.TimeoutExpired:
            os.killpg(serveur.pid, 9)
        journal.close()
    log = (data / "serve.log").read_text("utf-8", "replace")
    codes: dict[str, int] = {}
    for r in resultats:
        codes[str(r["http"])] = codes.get(str(r["http"]), 0) + 1
    bilan = {"envoyes": len(resultats), "codes_http": codes, "file": etat, "serveur_vivant_fin": vivant_fin,
             "rss_serveur_pic_mo": round(pic), "rss_serveur_fin_mo": round(rss_fin),
             "tracebacks_journal": log.count("Traceback"), "extrait_journal": log[-3000:],
             "duree_max_depot_s": max((r["duree_s"] for r in resultats), default=0), "resultats": resultats,
             "data_dir": str(data)}
    Path(a.out).write_text(json.dumps(bilan, indent=1, ensure_ascii=False), "utf-8")
    print(json.dumps({k: v for k, v in bilan.items() if k not in ("resultats", "extrait_journal")}, indent=1,
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
