"""CLI : ``python -m bench.score --corpus bench/corpus --split holdout --run bench/out/<run_id> [--gate]``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import scorer
from .formulations import charger_formulations
from .rapport import rendre_markdown


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.score",
                                 description="Correcteur du banc ControlDOne (SPEC §19).")
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--split", default="holdout", choices=["dev", "holdout"])
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--gate", action="store_true",
                    help="code retour 1 si le seuil bloquant (§19.7) échoue")
    ap.add_argument("--formulations", type=Path, default=None,
                    help="fichier YAML des formulations interdites (défaut : "
                         "config/formulations_interdites.yaml, sinon copie intégrée de §3.2)")
    args = ap.parse_args(argv)

    if not args.run.is_dir():
        print(f"Répertoire d'exécution introuvable : {args.run}", file=sys.stderr)
        return 2
    try:
        m = scorer(args.corpus, args.split, args.run, charger_formulations(args.formulations))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    (args.run / "metrics.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.run / "metrics.md").write_text(rendre_markdown(m), encoding="utf-8")

    g = m["global"]
    pc = g["precision_certain"]
    rp = g["rappel"]
    pc_s = "—" if pc is None else f"{pc:.4f}"
    rp_s = "—" if rp is None else f"{rp:.4f}"
    print(f"[bench.score] {m['run_id']} / {m['split']} : {g['n_dossiers']} dossiers, "
          f"{g['n_constats_certain']} constats certain, VP {g['vp_certain']}, "
          f"FP {g['fp_certain']}, FN {g['fn']}, precision_certain {pc_s}, rappel {rp_s}")
    if m["dossiers"]["findings_absents"]:
        print(f"[bench.score] findings.json absent : {', '.join(m['dossiers']['findings_absents'])}")
    if m["dossiers"]["findings_illisibles"]:
        print(f"[bench.score] findings.json illisible : "
              f"{', '.join(m['dossiers']['findings_illisibles'])}")
    for al in m["alertes"]:
        print(f"[bench.score] alerte : {al}")
    if m["gate"]["passe"]:
        print("[bench.score] seuil bloquant : PASSE")
    else:
        print("[bench.score] seuil bloquant : ÉCHOUE")
        for motif in m["gate"]["motifs"]:
            print(f"  - {motif}")
    if args.gate and not m["gate"]["passe"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
