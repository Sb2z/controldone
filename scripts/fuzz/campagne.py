"""Campagne de robustesse : chaque échantillon passe par le pipeline complet, sous surveillance.

    python scripts/fuzz/campagne.py var/fuzz/samples var/fuzz/mutations --out var/fuzz/bilan_avant.json \
        [--paralleles 2] [--delai 900] [--rss-max-mo 3000] [--as-max-octets 1500000000]

Garde-fous de la machine qui exécute la campagne (une campagne à 3 cas parallèles sans plafond d'espace d'adressage
a déjà épuisé la mémoire du conteneur) : chaque cas tourne sous ``RLIMIT_AS`` (``--as-max-octets``, hérité par ses
processus de pages, qui ne peuvent pas le relever), avec un délai et un plafond de mémoire résidente de l'arbre ;
au plus 2 cas en parallèle.

Un processus par échantillon (``executer_un.py``) ; on relève toutes les 0,25 s la mémoire résidente du
processus principal et de toute sa descendance (processus de pages, forkserver) via ``/proc``. Issues :

- ``traite`` : au moins un fichier lu (pages produites), le reste éventuellement refusé ou listé non lu ;
- ``refuse`` : refusé à la réception avec un motif explicite ;
- ``non_lu`` : accepté puis listé dans ``non_lus`` avec un motif ;
- ``plantage`` (exception non rattrapée), ``delai`` (tué au-delà de ``--delai``), ``memoire`` (au-delà de
  ``--rss-max-mo``), ``silencieux`` (ni traité, ni refusé, ni listé) : défauts à corriger.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ICI = Path(__file__).resolve().parent
PAGE = os.sysconf("SC_PAGE_SIZE")


def _enfants(pid: int) -> list[int]:
    out = []
    try:
        for tid in os.listdir(f"/proc/{pid}/task"):
            try:
                with open(f"/proc/{pid}/task/{tid}/children") as f:
                    out += [int(x) for x in f.read().split()]
            except OSError:
                pass
    except OSError:
        pass
    return out


def _rss(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/statm") as f:
            return int(f.read().split()[1]) * PAGE
    except (OSError, IndexError, ValueError):
        return 0


def arbre(pid: int) -> list[int]:
    vus, pile = [], [pid]
    while pile:
        p = pile.pop()
        vus.append(p)
        pile += _enfants(p)
    return vus


def tuer_arbre(pid: int) -> None:
    for p in reversed(arbre(pid)):
        with contextlib.suppress(OSError):
            os.kill(p, 9)


PARALLELES_MAX = 2


def _plafond_as(octets: int):
    def _f():  # dans l'enfant, avant exec : plafond dur, hérité par toute la descendance
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (octets, octets))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return _f


def executer(fichier: Path, delai: float, rss_max: int, env: dict[str, str], as_max: int = 1_500_000_000) -> dict:
    with tempfile.TemporaryDirectory(prefix="cdo-camp-") as tmp:
        sortie = Path(tmp) / "bilan.json"
        debut = time.monotonic()
        proc = subprocess.Popen([sys.executable, str(ICI / "executer_un.py"), str(fichier), str(sortie)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env,
                                start_new_session=True, preexec_fn=_plafond_as(as_max))
        pic_principal = pic_arbre = 0
        cause = None
        err: list[bytes] = []
        lecteur = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
        lecteur.start()
        while proc.poll() is None:
            pids = arbre(proc.pid)
            principal = _rss(proc.pid)
            total = sum(_rss(p) for p in pids)
            pic_principal, pic_arbre = max(pic_principal, principal), max(pic_arbre, total)
            if time.monotonic() - debut > delai:
                cause = "delai"
            elif total > rss_max:
                cause = "memoire"
            if cause:
                tuer_arbre(proc.pid)
                break
            time.sleep(0.25)
        proc.wait()
        lecteur.join(5)
        duree = time.monotonic() - debut
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, 9)  # restes éventuels (forkserver orphelin)
        bilan = json.loads(sortie.read_text("utf-8")) if sortie.exists() else {}
    bilan.update({"echantillon": str(fichier), "duree_totale_s": round(duree, 2), "code": proc.returncode,
                  "rss_principal_mo": round(pic_principal / 2**20), "rss_arbre_mo": round(pic_arbre / 2**20),
                  "stderr": (b"".join(err)[-1500:]).decode("utf-8", "replace")})
    if cause is None and bilan.get("exception") == "MemoryError":
        cause = "memoire"  # plafond d'espace d'adressage atteint dans le processus principal
    bilan["issue"] = cause or classer(bilan)
    return bilan


def classer(b: dict) -> str:
    if not b.get("ok"):
        return "plantage"
    nl = b.get("non_lus", [])
    refus = [n for n in nl if n["motif"].startswith("refuse:")]
    autres = {n["fichier"] for n in nl if not n["motif"].startswith("refuse:")}
    lus = [f for f in b.get("fichiers", []) if f["chemin"] not in autres]
    if any(n["motif"].startswith(("reception_en_erreur", "lecture_en_erreur", "regroupement_en_erreur"))
           for n in nl):
        return "plantage"  # exception rattrapée par le pipeline mais qui a fait perdre la réception ou le fichier
    if lus and b.get("pages", 0) > 0:
        return "traite"
    if autres:
        return "non_lu"
    if refus:
        return "refuse"
    return "silencieux"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--paralleles", type=int, default=2)
    ap.add_argument("--delai", type=float, default=900)
    ap.add_argument("--rss-max-mo", type=int, default=3000)
    ap.add_argument("--as-max-octets", type=int, default=1_500_000_000)
    ap.add_argument("--filtre", default="")
    a = ap.parse_args(argv)
    fichiers = sorted(p for s in a.sources for p in Path(s).rglob("*") if p.is_file() and a.filtre in str(p))
    env = {k: v for k, v in os.environ.items() if k != "CONTROLDONE_PAGES_CACHE_DIR"}
    env.setdefault("CONTROLDONE_ENV", "dev")
    env["CONTROLDONE_PAGES_PARALLELE"] = "1"
    env.setdefault("MALLOC_ARENA_MAX", "2")  # espace d'adressage réservé par fil : sans effet sur le résultat
    resultats: list[dict] = []
    verrou = threading.Lock()

    def tache(f: Path) -> dict:
        r = executer(f, a.delai, a.rss_max_mo * 2**20, env, a.as_max_octets)
        with verrou:
            resultats.append(r)
            print(f"[{len(resultats):4d}/{len(fichiers)}] {r['issue']:10s} {r['duree_totale_s']:7.1f}s "
                  f"{r['rss_principal_mo']:5d}/{r['rss_arbre_mo']:5d} Mo  {f}", flush=True)
        return r

    with ThreadPoolExecutor(max(1, min(a.paralleles, PARALLELES_MAX))) as ex:
        list(ex.map(tache, fichiers))
    resultats.sort(key=lambda r: r["echantillon"])
    resume = Counter(r["issue"] for r in resultats)
    par_cat: dict[str, Counter] = {}
    for r in resultats:
        cat = Path(r["echantillon"]).parent.name
        par_cat.setdefault(cat, Counter())[r["issue"]] += 1
    synthese = {
        "total": len(resultats), "issues": dict(resume),
        "par_categorie": {k: dict(v) for k, v in sorted(par_cat.items())},
        "duree_max_s": max((r["duree_totale_s"] for r in resultats), default=0),
        "rss_principal_max_mo": max((r["rss_principal_mo"] for r in resultats), default=0),
        "rss_arbre_max_mo": max((r["rss_arbre_mo"] for r in resultats), default=0),
        "lents_120s": [(r["echantillon"], r["duree_totale_s"]) for r in resultats if r["duree_totale_s"] > 120],
        "defauts": [(r["echantillon"], r["issue"], r.get("exception")) for r in resultats
                    if r["issue"] in ("plantage", "delai", "memoire", "silencieux")],
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"synthese": synthese, "resultats": resultats}, ensure_ascii=False, indent=1),
                           "utf-8")
    print(json.dumps(synthese, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
