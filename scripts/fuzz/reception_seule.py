"""Mesure de l'étape 1 seule (réception, exécutée dans le processus web lors d'un dépôt) sur chaque échantillon.

    python scripts/fuzz/reception_seule.py var/fuzz/samples var/fuzz/mutations --out var/fuzz/reception.json

Un sous-processus par échantillon (délai ``--delai``) : durée, pic de mémoire résidente, issue par fichier.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CODE = r"""
import json, resource, sys, time
from collections import Counter
from controldone.services.depot import FichierTransmis, lire_borne
from controldone.ingest.reception import recevoir_octets
p = sys.argv[1]
t = time.monotonic()
try:
    contenu = open(p, "rb").read()
    r = recevoir_octets([(p.rsplit("/", 1)[-1], contenu)])
    issues = Counter(f"{x.fichier.statut.value}:{x.fichier.motif_refus or ''}" for x in r.fichiers)
    out = {"ok": True, "issues": dict(issues)}
except BaseException as e:
    out = {"ok": False, "exception": type(e).__name__, "message": str(e)[:200]}
out["duree_s"] = round(time.monotonic() - t, 2)
out["rss_max_mo"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
print(json.dumps(out))
"""


def un(p: Path, delai: float) -> dict:
    try:
        r = subprocess.run([sys.executable, "-c", CODE, str(p)], capture_output=True, timeout=delai, check=False)
        d = json.loads(r.stdout.decode().strip().splitlines()[-1]) if r.stdout.strip() else {
            "ok": False, "exception": f"code_{r.returncode}", "stderr": r.stderr.decode()[-500:]}
    except subprocess.TimeoutExpired:
        d = {"ok": False, "exception": "delai"}
    d["echantillon"] = str(p)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--delai", type=float, default=120)
    ap.add_argument("--paralleles", type=int, default=2)
    a = ap.parse_args()
    fichiers = sorted(p for s in a.sources for p in Path(s).rglob("*") if p.is_file())
    with ThreadPoolExecutor(a.paralleles) as ex:
        res = list(ex.map(lambda p: un(p, a.delai), fichiers))
    res.sort(key=lambda d: -d.get("duree_s", 1e9) if d.get("ok") else -1e9)
    Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False), "utf-8")
    print("échecs :", [(d["echantillon"], d.get("exception")) for d in res if not d.get("ok")])
    print("plus lents :", [(d["echantillon"], d["duree_s"], d["rss_max_mo"]) for d in res if d.get("ok")][:15])
    print("plus gourmands :", sorted(((d["rss_max_mo"], d["echantillon"]) for d in res if d.get("ok")), reverse=True)[:10])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
