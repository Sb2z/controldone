"""CLI : python -m bench.generator --out bench/corpus --split dev|holdout|all --count 250 --seed 20261002"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import shutil
import sys
import time

from . import GENERATOR_VERSION
from .common import dumps, sha256_bytes

_STATE = {}


def _init(seed, count):
    from .clients import build_registry
    from .plan import build_plan
    plans = build_plan(seed, count)
    _STATE["seed"] = seed
    _STATE["reg"] = build_registry(seed)
    _STATE["plans"] = {p["id"]: p for p in plans}


def _work(args):
    did, out = args
    from .assemble import generate_dossier
    t0 = time.time()
    try:
        truth, tsha, warnings = generate_dossier(_STATE["seed"], _STATE["plans"][did], _STATE["reg"], _STATE["plans"],
                                                 out)
    except Exception:  # noqa: BLE001
        import traceback
        return did, None, None, [traceback.format_exc()], time.time() - t0
    return did, truth, tsha, warnings, time.time() - t0


def write_clients(out, seed):
    from .clients import build_registry, profile_json
    from .validate import validate_grid
    reg = build_registry(seed)
    for cid in sorted(reg.clients):
        d = os.path.join(out, "clients", cid)
        os.makedirs(os.path.join(d, "grilles"), exist_ok=True)
        with open(os.path.join(d, "profil.json"), "w", encoding="utf-8") as fh:
            fh.write(dumps(profile_json(reg, cid)))
        for (c, tid), g in sorted(reg.grids.items()):
            if c != cid:
                continue
            validate_grid(g)
            with open(os.path.join(d, "grilles", g["grille_id"] + ".json"), "w", encoding="utf-8") as fh:
                fh.write(dumps(g))
    return reg


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m bench.generator")
    ap.add_argument("--out", default="bench/corpus")
    ap.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    ap.add_argument("--count", type=int, default=250)
    ap.add_argument("--seed", type=int, default=20261002)
    ap.add_argument("--only", default="", help="liste d'identifiants BX séparés par des virgules")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 0))
    ap.add_argument("--plan-only", action="store_true", help="écrit seulement le plan (stdout), sans fichiers")
    args = ap.parse_args(argv)

    from .plan import build_plan
    from .validate import validate_truth
    plans = build_plan(args.seed, args.count)
    if args.plan_only:
        json.dump(plans, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)
        return 0
    os.makedirs(args.out, exist_ok=True)
    write_clients(args.out, args.seed)
    sel = [p for p in plans if args.split == "all" or p["split"] == args.split]
    if args.only:
        keep = set(args.only.split(","))
        sel = [p for p in sel if p["id"] in keep]
    for p in sel:
        d = os.path.join(args.out, p["split"], p["id"])
        if os.path.isdir(d):
            shutil.rmtree(d)
    t0 = time.time()
    results = []
    jobs = [(p["id"], args.out) for p in sel]
    if args.jobs > 1 and len(jobs) > 1:
        ctx = mp.get_context("fork")
        with ctx.Pool(args.jobs, initializer=_init, initargs=(args.seed, args.count)) as pool:
            for res in pool.imap_unordered(_work, jobs, chunksize=1):
                results.append(res)
    else:
        _init(args.seed, args.count)
        for j in jobs:
            results.append(_work(j))
    results.sort(key=lambda x: x[0])
    errors = 0
    warn_count = 0
    failed = [r for r in results if r[1] is None]
    for did, _, _, warnings, _ in failed:
        errors += 1
        print(f"[ÉCHEC] {did}:\n{warnings[0]}", file=sys.stderr)
    results = [r for r in results if r[1] is not None]
    for did, truth, tsha, warnings, dt_ in results:
        try:
            validate_truth(truth)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"[ERREUR schéma] {did}: {exc}", file=sys.stderr)
        for w in warnings:
            warn_count += 1
            print(f"[avertissement] {did}: {w}", file=sys.stderr)
    _write_manifest(args, plans, results)
    elapsed = time.time() - t0
    print(f"{len(results)} dossiers générés ({args.split}) en {elapsed:.1f} s ; erreurs de schéma : {errors} ; "
          f"avertissements : {warn_count}")
    return 1 if errors else 0


def _write_manifest(args, plans, results):
    path = os.path.join(args.out, "manifest.json")
    man = {"schema": "controldone.bench.manifest/1.0.0", "generator_version": GENERATOR_VERSION, "seed": args.seed,
           "count": args.count, "dossiers": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
        if old.get("seed") == args.seed and old.get("generator_version") == GENERATOR_VERSION \
                and old.get("count") == args.count:
            man["dossiers"] = {d["dossier_id"]: d for d in old.get("dossiers", [])}
    by_id = {p["id"]: p for p in plans}
    for did, truth, tsha, warnings, dt_ in results:
        p = by_id[did]
        man["dossiers"][did] = {
            "dossier_id": did, "split": p["split"], "client_id": p["client"],
            "truth": f"{p['split']}/{did}/truth.json", "truth_sha256": tsha,
            "files": [{"path": f"{p['split']}/{did}/{f['path']}", "sha256": f["sha256"], "pages": f["pages"]}
                      for f in truth["files"]],
        }
    man["clients"] = sorted({d["client_id"] for d in man["dossiers"].values()})
    man["splits"] = {s: sorted(k for k, v in man["dossiers"].items() if v["split"] == s) for s in ("dev", "holdout")}
    man["dossiers"] = [man["dossiers"][k] for k in sorted(man["dossiers"])]
    man["split_rule"] = "holdout si int(sha256(dossier_id)[0:8], 16) % 5 == 0, sinon dev"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(man))


if __name__ == "__main__":
    sys.exit(main())
