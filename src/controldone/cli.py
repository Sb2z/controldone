"""Command-line interface for ControlDOne.

Exit codes are meant for orchestrators (scheduled tasks, n8n, Power Automate):
  0  analysis ran, no blocking anomaly (statuses OK / OK_A_CONTROLER only);
  1  analysis ran and at least one dossier is KO / KO_BLOQUANT / MANQUE_DOC
     (disable with --exit-zero if only the report matters);
  2  usage error: input path missing, unknown client profile.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import Counter

from controldone.pipeline import analyze
from controldone.profile import ProfileError, load_profile
from controldone.reporting import write_report_v4
from controldone import reporting_json


STATUS_ORDER = ["KO_BLOQUANT", "MANQUE_DOC", "KO", "OK_A_CONTROLER", "A_VERIFIER", "OK"]


def main() -> int:
    parser = argparse.ArgumentParser(description="ControlDOne - controle documentaire douane")
    parser.add_argument(
        "--input",
        "-i",
        default=os.path.join("data", "input"),
        help="Fichier ou dossier a analyser",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=os.path.join("data", "output"),
        help="Dossier de sortie du rapport Excel",
    )
    parser.add_argument(
        "--report-name",
        default=None,
        help="Nom du fichier Excel de sortie",
    )
    parser.add_argument(
        "--client",
        default=None,
        help="Profil client a utiliser (dossier sous config/clients/). "
             "Par defaut: CONTROLDONE_CLIENT, ou l'unique client configure.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Ecrit le resultat complet en JSON sur stdout (machine-readable)",
    )
    parser.add_argument(
        "--webhook",
        default=None,
        metavar="URL",
        help="POST le resultat JSON vers cette URL en fin d'analyse "
             "(webhook n8n / Power Automate / relais Teams...)",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="Toujours sortir avec le code 0, meme en presence d'anomalies",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Chemin d'entree introuvable : {args.input}", file=sys.stderr)
        return 2

    def progress(current: int, total: int, path: str) -> None:
        rel = os.path.relpath(path, args.input) if os.path.isdir(args.input) else os.path.basename(path)
        print(f"[{current}/{total}] Analyse: {rel}", file=sys.stderr, flush=True)

    try:
        profile = load_profile(args.client) if args.client else None
        result = analyze(args.input, progress=progress, profile=profile)
    except ProfileError as exc:
        print(f"Erreur de profil client : {exc}", file=sys.stderr)
        return 2
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_name = args.report_name or f"controle_douane_{stamp}.xlsx"
    out_path = os.path.join(args.output, report_name)
    write_report_v4(result.bundles, out_path, result.errors)

    payload = reporting_json.run_to_dict(
        result.bundles, result.errors, len(result.documents), report_path=out_path,
    )

    if args.json:
        print(reporting_json.to_json(payload))
    else:
        counts = Counter(bundle.status for bundle in result.bundles)
        print(f"Documents parses : {len(result.documents)}")
        print(f"Dossiers generes : {len(result.bundles)}")
        print(f"Erreurs lecture  : {len(result.errors)}")
        print(f"Rapport          : {out_path}")
        for status in STATUS_ORDER:
            if counts[status]:
                print(f"  {status}: {counts[status]}")

    if args.webhook:
        try:
            code = reporting_json.post_webhook(args.webhook, payload)
            print(f"Webhook {args.webhook} -> HTTP {code}", file=sys.stderr)
        except Exception as exc:
            print(f"Webhook en echec ({exc}), rapport genere malgre tout.", file=sys.stderr)

    if args.exit_zero:
        return 0
    return 1 if payload["summary"]["anomalies"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
