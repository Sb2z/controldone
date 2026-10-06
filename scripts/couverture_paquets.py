"""Résumé de couverture par paquet (D-3902), à partir du JSON de coverage.py (``make couverture``).

Sortie Markdown (stdout et ``--out``) : un tableau par paquet de ``controldone`` (lignes, branches, total), puis les
modules **critiques** les moins couverts (contrôles, normalisation des montants, authentification, sécurité web,
stockage), pour orienter les tests à écrire. ``--min`` : taux global minimal (échec en dessous).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

#: Modules dont une branche non testée peut produire un faux constat ou une faille (ordre = priorité d'affichage).
CRITIQUES = (
    "controls/",
    "normalize/",
    "auth/",
    "web/securite.py",
    "web/listes.py",
    "web/rendu.py",
    "web/routes_auth.py",
    "storage/scope.py",
    "storage/securite.py",
    "storage/vault.py",
    "storage/cles.py",
    "services/saisie.py",
    "formatage.py",
    "guardrails.py",
)


def paquet(chemin: str) -> str:
    rel = chemin.split("controldone/", 1)[-1]
    return rel.split("/", 1)[0] if "/" in rel else "(racine)"


def taux(couverts: int, total: int) -> float:
    return 100.0 * couverts / total if total else 100.0


def resumer(donnees: dict, nb_critiques: int = 10) -> tuple[str, float]:
    par_paquet: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    modules = []
    for chemin, f in donnees["files"].items():
        s = f["summary"]
        acc = par_paquet[paquet(chemin)]
        acc[0] += s["covered_lines"]
        acc[1] += s["num_statements"]
        acc[2] += s.get("covered_branches", 0)
        acc[3] += s.get("num_branches", 0)
        rel = chemin.split("controldone/", 1)[-1]
        modules.append((rel, s))
    t = donnees["totals"]
    global_ = t["percent_covered"]
    lignes = ["| Paquet | Lignes | Branches | Total |", "|---|---:|---:|---:|"]
    for nom, (cl, nl, cb, nb) in sorted(
        par_paquet.items(), key=lambda kv: taux(kv[1][0] + kv[1][2], kv[1][1] + kv[1][3])
    ):
        lignes.append(
            f"| `{nom}` | {taux(cl, nl):.1f} % ({cl}/{nl}) | {taux(cb, nb):.1f} % ({cb}/{nb}) | "
            f"{taux(cl + cb, nl + nb):.1f} % |"
        )
    lignes.append(
        f"| **Total** | {taux(t['covered_lines'], t['num_statements']):.1f} % | "
        f"{taux(t.get('covered_branches', 0), t.get('num_branches', 0)):.1f} % | **{global_:.1f} %** |"
    )
    critiques = sorted(
        ((rel, s) for rel, s in modules if rel.startswith(CRITIQUES) and s["num_statements"] >= 10),
        key=lambda m: m[1]["percent_covered"],
    )[:nb_critiques]
    lignes += [
        "",
        f"Modules critiques les moins couverts ({nb_critiques}) :",
        "",
        "| Module | Total | Lignes manquantes | Branches partielles |",
        "|---|---:|---:|---:|",
    ]
    for rel, s in critiques:
        lignes.append(
            f"| `{rel}` | {s['percent_covered']:.1f} % | {s['missing_lines']} | "
            f"{s.get('num_partial_branches', 0)} |"
        )
    return "\n".join(lignes) + "\n", global_


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("json", type=Path, nargs="?", default=Path("var/couverture/couverture.json"))
    ap.add_argument("--out", type=Path, default=Path("var/couverture/paquets.md"))
    ap.add_argument("--critiques", type=int, default=10)
    ap.add_argument("--min", type=float, default=0.0, help="taux global minimal, en %%")
    a = ap.parse_args(argv)
    texte, global_ = resumer(json.loads(a.json.read_text(encoding="utf-8")), a.critiques)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(texte, encoding="utf-8")
    sys.stdout.write(texte)
    if global_ < a.min:
        sys.stderr.write(f"Couverture {global_:.1f} % < minimum {a.min:.1f} %\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
