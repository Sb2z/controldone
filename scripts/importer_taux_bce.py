"""Alimente ``ref/taux_bce.csv`` (SPEC §8.7) à partir du fichier historique des taux de référence de la BCE.

Usage (hors ligne, le fichier est téléchargé à part depuis le site de la BCE) ::

    python scripts/importer_taux_bce.py eurofxref-hist.zip --depuis 2024-01-01 [--sortie ref/taux_bce.csv]

Les taux de référence ne servent qu'à déterminer le sens d'un taux imprimé sans libellé et à A7 (ordre de
grandeur) ; jamais à calculer un montant en jeu (D-806).
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from controldone.taux_reference import convertir_historique_bce


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", type=Path, help="eurofxref-hist.csv ou eurofxref-hist.zip (BCE)")
    ap.add_argument("--depuis", type=date.fromisoformat, default=None, help="première date conservée (AAAA-MM-JJ)")
    ap.add_argument("--sortie", type=Path, default=Path(__file__).resolve().parents[1] / "ref" / "taux_bce.csv")
    args = ap.parse_args(argv)
    texte = convertir_historique_bce(args.source.read_bytes(), depuis=args.depuis)
    args.sortie.write_text(texte, encoding="utf-8")
    print(f"{args.sortie} : {texte.count(chr(10)) - 1} taux")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
