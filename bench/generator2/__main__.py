"""CLI du générateur n° 2 (corpus de généralisation).

    python -m bench.generator2 --out bench/corpus_g2 --split dev|holdout|all --count 300 --seed 777 [--jobs 2]
                               [--ids GX0001,GX0002] [--stats-only]

- La planification couvre toujours les `count` dossiers (dev et holdout) : générer un split plus tard
  redonne exactement les mêmes dossiers, octet pour octet.
- Écrit `clients/<CL>/profil.json`, `clients/<CL>/grilles/<id>.json`, `<split>/<GXnnnn>/{truth.json,docs/}`,
  `manifest.json` et `stats_generation.json` (couverture par contrôle, y compris la couverture
  planifiée du holdout, sans générer ses fichiers).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from .build import ANNEXE_A, Dossier, expected_level
from .plan import CONTROLES, plan_corpus
from .util import GENERATOR_VERSION
from .world import CLIENT_FORWARDERS, build_world

_STATE: dict = {}


def build_all(seed: int, count: int, wanted: set | None = None) -> tuple[dict, dict, list]:
    """Construit (sans rendu) les dossiers voulus et leurs partenaires (F2, F3, F5)."""
    specs = plan_corpus(seed, count)
    world = build_world(seed)
    byid = {s["dossier_id"]: s for s in specs}
    reg: dict = {}

    def bld(did):
        if did in reg:
            return reg[did]
        s = byid[did]
        for _code, pid in s["partners"]:
            bld(pid)
        d = Dossier(world, s, seed, reg)
        d.build()
        reg[did] = d
        return d

    for s in specs:
        if wanted is None or s["dossier_id"] in wanted:
            bld(s["dossier_id"])
    return world, reg, specs


def _init_worker(seed, count, wanted):
    _STATE["seed"] = seed
    _STATE["world"], _STATE["reg"], _ = build_all(seed, count, wanted)


def _work(args):
    did, out = args
    from .emit import write_dossier
    t0 = time.perf_counter()
    res = write_dossier(_STATE["reg"][did], Path(out))
    res["seconds"] = round(time.perf_counter() - t0, 2)
    res["dossier_id"] = did
    return res


def write_clients(world: dict, out: Path):
    for cid, cl in sorted(world["clients"].items()):
        d = out / "clients" / cid
        (d / "grilles").mkdir(parents=True, exist_ok=True)
        prof = {
            "schema": "controldone.bench.profil/1.0.0", "client_id": cid,
            "mention": "DONNÉES FICTIVES — profil client de test (bench.generator2)",
            "entites": [{"raison_sociale": e["raison_sociale"], "tva": e["tva"], "siren": e["siren"], "eori": e["eori"],
                         "alias": list(e["alias"])} for e in cl["entites"]],
            "transitaires": [{"transitaire_id": world["forwarders"][f]["transitaire_id"], "nom": world["forwarders"][f]["nom"],
                              "tva": world["forwarders"][f]["tva"], "alias": list(world["forwarders"][f]["alias"])}
                             for f in CLIENT_FORWARDERS[cid]],
            "tolerances": {},
        }
        (d / "profil.json").write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for (gcid, fam), g in sorted(world["grids"].items()):
            if gcid == cid:
                (d / "grilles" / f"{g['grille_id']}.json").write_text(json.dumps(g, ensure_ascii=False, indent=2) + "\n",
                                                                     encoding="utf-8")


def coverage(reg: dict) -> dict:
    """Erreurs par contrôle principal et par split (niveaux attendus calculés comme dans truth.json)."""
    cov = {c: {"dev": 0, "holdout": 0, "certain": 0} for c in CONTROLES + ["P1", "P2"]}
    for did, dos in reg.items():
        for e in dos.errors:
            c = cov.setdefault(e["ctrl"], {"dev": 0, "holdout": 0, "certain": 0})
            c[dos.spec["split"]] += 1
            if expected_level(dos, e) == "ecart_certain":
                c["certain"] += 1
        if dos.has("fichier_double") and not any(e["ctrl"] == "F1" for e in dos.errors):
            cov["F1"][dos.spec["split"]] += 1     # injection F1 réalisée au plan de fichiers (emit.plan_files)
    return cov


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.generator2")
    ap.add_argument("--out", type=Path, default=Path("bench/corpus_g2"))
    ap.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--seed", type=int, default=777)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--ids", default=None, help="liste de dossiers à générer (tests), séparés par des virgules")
    ap.add_argument("--stats-only", action="store_true", help="planification et construction seulement, sans fichiers")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    jobs = max(1, min(2, a.jobs))
    # Construction de TOUS les dossiers (rapide, sans rendu) : statistiques et couverture planifiée
    world, reg_all, specs = build_all(a.seed, a.count)
    splits = ["dev", "holdout"] if a.split == "all" else [a.split]
    ids = [s["dossier_id"] for s in specs if s["split"] in splits]
    if a.ids:
        keep = set(a.ids.split(","))
        ids = [i for i in ids if i in keep] or [i for i in a.ids.split(",") if i in reg_all]
    cov = coverage(reg_all)
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    results = []
    if not a.stats_only:
        write_clients(world, out)
        tasks = [(d, str(out)) for d in ids]
        if jobs == 1:
            _init_worker(a.seed, a.count, set(ids))
            for t in tasks:
                r = _work(t)
                results.append(r)
                print(f"{r['dossier_id']} {r['seconds']:6.2f}s  {len(r['files'])} fichier(s)"
                      + (f"  !! {len(r['problems'])} problème(s)" if r["problems"] else ""), flush=True)
        else:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
            with ctx.Pool(jobs, initializer=_init_worker, initargs=(a.seed, a.count, set(ids)), maxtasksperchild=25) as pool:
                for r in pool.imap(_work, tasks, chunksize=1):
                    results.append(r)
                    print(f"{r['dossier_id']} {r['seconds']:6.2f}s  {len(r['files'])} fichier(s)"
                          + (f"  !! {len(r['problems'])} problème(s)" if r["problems"] else ""), flush=True)
    problems = [p for r in results for p in r["problems"]]
    # Manifest (fusionné avec un manifest existant : générer dev puis holdout)
    man_path = out / "manifest.json"
    prev = {}
    if man_path.is_file():
        try:
            prev = {d["dossier_id"]: d for d in json.loads(man_path.read_text(encoding="utf-8")).get("dossiers", [])}
        except Exception:
            prev = {}
    for r in results:
        t = r["truth"]
        prev[t["dossier_id"]] = {"dossier_id": t["dossier_id"], "split": t["split"], "client_id": t["client_id"],
                                 "files": [{"path": f["path"], "sha256": f["sha256"], "pages": f["pages"]} for f in r["files"]]}
    if not a.stats_only:
        manifest = {
            "schema": "controldone.bench.manifest/1.0.0", "generator": "bench.generator2",
            "generator_version": GENERATOR_VERSION, "seed": a.seed, "count": a.count,
            "split_rule": "holdout si int(sha256(dossier_id)[0:8], 16) % 5 == 0",
            "mention": "DONNÉES FICTIVES",
            "planned": {"dev": sum(1 for s in specs if s["split"] == "dev"),
                        "holdout": sum(1 for s in specs if s["split"] == "holdout")},
            "dossiers": [prev[k] for k in sorted(prev)],
        }
        man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Statistiques
    comp = defaultdict(Counter)
    for did, dos in reg_all.items():
        sp = dos.spec
        s = sp["split"]
        comp["client"][f"{s}:{sp['client_id']}"] += 1
        comp["famille"][f"{s}:{sp['family']}"] += 1
        comp["presentation"][f"{s}:{sp['layout']}"] += 1
        comp["degradation"][f"{s}:{dos.deg_dossier}"] += 1
        comp["nb_erreurs"][f"{s}:{min(len(dos.errors), 3)}{'+' if len(dos.errors) >= 3 else ''}"] += 1
        for d in dos.order:
            if d in dos.removed:
                continue
            doc = dos.docs[d]
            comp["mode"][f"{s}:{doc.get('mode')}"] += 1
            if doc["kind"] == "ci":
                comp["devise"][f"{s}:{doc['devise']}"] += 1
                comp["ci_layout"][f"{s}:{doc['layout']}"] += 1
                comp["ci_langue"][f"{s}:{doc['lang']}"] += 1
    stats = {
        "generator_version": GENERATOR_VERSION, "seed": a.seed, "count": a.count, "split_generated": a.split,
        "generated": len(results), "seconds": round(time.perf_counter() - t0, 1),
        "coverage": cov, "composition": {k: dict(sorted(v.items())) for k, v in comp.items()},
        "problems": problems,
    }
    (out / "stats_generation.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(results)} dossier(s) générés en {stats['seconds']} s ; {len(problems)} problème(s) d'auto-contrôle.")
    print("Contrôle  dev  holdout(planifié)  certain")
    for c, v in cov.items():
        flag = "" if (v["dev"] + v["holdout"] >= 6 and v["holdout"] >= 2) or c.startswith("P") else "  <-- couverture insuffisante"
        print(f"  {c:5s} {v['dev']:4d} {v['holdout']:6d} {v['certain']:10d}{flag}")
    for p in problems[:40]:
        print("  !", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
