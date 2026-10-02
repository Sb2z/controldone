"""Démonstration : ``python -m controldone.ingest.demo <chemin> [--truth] [--sans-ocr] [--cache DIR]``.

Affiche, pour un dossier ou un fichier : fichiers reçus (type, refus), pages (qualité, score), classement
de chaque page et documents logiques. Avec ``--truth`` et un dossier du banc (split ``dev`` seulement),
compare les documents produits à ``truth.json`` ``documents[]`` (type par page) et affiche l'exactitude.
Aucun texte de document n'est affiché (seulement types, références normalisées et indicateurs).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .decoupage import decouper_fichier
from .pages import OptionsPages
from .reception import recevoir_chemin


def _truth_par_page(truth: dict) -> dict[tuple[str, int], tuple[str, str | None]]:
    out = {}
    for d in truth.get("documents", []):
        for p in d.get("pages") or [1]:
            out[(d["file"], int(p))] = (d["type"], d.get("sous_type"))
    return out


def analyser(chemin: Path, *, options: OptionsPages, verbeux: bool = True, truth: bool = False) -> Counter:
    docs_dir = chemin / "docs" if (chemin / "docs").is_dir() else chemin
    racine = chemin if (chemin / "docs").is_dir() else None
    rec = recevoir_chemin(docs_dir, racine=racine)
    vrai = {}
    if truth and (chemin / "truth.json").exists():
        t = json.loads((chemin / "truth.json").read_text("utf-8"))
        if t.get("split") != "dev":
            raise SystemExit("truth.json : seul le split dev peut être lu")
        vrai = _truth_par_page(t)
    stats: Counter = Counter()
    for fr in rec.fichiers:
        f = fr.fichier
        if verbeux:
            print(f"- {f.chemin_relatif} [{f.type_mime}] {f.statut.value}"
                  f"{' (' + f.motif_refus + ')' if f.motif_refus else ''}{' doublon' if f.doublon_de else ''}")
        if not fr.a_traiter:
            continue
        r = decouper_fichier(f, fr.contenu, options=options, corps_courriel=fr.corps_courriel)
        if verbeux:
            for c in r.classements:
                t = r.textes.get(c.numero)
                print(f"    p{c.numero}: {t.qualite.value if t else '?'}"
                      f" natif={t.score_natif if t else None} ocr={t.score_ocr if t else None}"
                      f" rot={t.rotation if t else 0} -> {c.type if isinstance(c.type, str) else c.type.value}"
                      f"/{c.sous_type or c.motif_non_exploitable or ''} conf={c.confiance}"
                      f" refs={c.refs.numero_facture or ''} {','.join(c.refs.mrn_prefixes)} {c.indices}")
            if r.structure is not None:
                print(f"    structure: {r.structure.format}")
            for d in r.documents:
                print(f"    => {d.type.value}/{d.sous_type or (d.motif_non_exploitable or '')} pages="
                      f"{[p.numero for p in d.pages]} conf={d.confiance_classement} langue={d.langue}")
        if vrai:
            for d in r.documents:
                for p in d.pages:
                    cle = (f.chemin_relatif, p.numero)
                    if cle not in vrai:
                        continue
                    t_vrai, st_vrai = vrai[cle]
                    stats["pages"] += 1
                    ok = d.type.value == t_vrai
                    stats["type_ok"] += ok
                    stats[f"vrai:{t_vrai}"] += 1
                    stats[f"ok:{t_vrai}"] += ok
                    if ok and st_vrai is not None:
                        stats["sous_type_n"] += 1
                        stats["sous_type_ok"] += (d.sous_type == st_vrai or
                                                  (d.motif_non_exploitable or "") == st_vrai)
                    if not ok:
                        stats[f"confusion:{t_vrai}->{d.type.value}"] += 1
            n_vrai = len({(d["file"], d["doc_id"]) for d in json.loads(
                (chemin / "truth.json").read_text("utf-8")).get("documents", []) if d["file"] == f.chemin_relatif})
            stats["docs_vrais"] += n_vrai
            stats["docs_produits"] += len(r.documents)
            stats["fichiers_nb_docs_ok"] += n_vrai == len(r.documents)
            stats["fichiers"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m controldone.ingest.demo")
    ap.add_argument("chemins", nargs="+", type=Path)
    ap.add_argument("--truth", action="store_true", help="comparer à truth.json (split dev seulement)")
    ap.add_argument("--sans-ocr", action="store_true")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    opts = OptionsPages(ocr=not a.sans_ocr, cache_dir=a.cache)
    total: Counter = Counter()
    for ch in a.chemins:
        if not a.quiet:
            print(f"# {ch}")
        total += analyser(ch, options=opts, verbeux=not a.quiet, truth=a.truth)
    if a.truth and total["pages"]:
        print(f"\nPages comparées : {total['pages']} ; type exact : {total['type_ok']} "
              f"({100 * total['type_ok'] / total['pages']:.1f} %)")
        if total["sous_type_n"]:
            print(f"Sous-type exact (type juste) : {total['sous_type_ok']}/{total['sous_type_n']}")
        print(f"Fichiers avec le bon nombre de documents : {total['fichiers_nb_docs_ok']}/{total['fichiers']}")
        for k in sorted(k for k in total if k.startswith("vrai:")):
            t = k[5:]
            print(f"  {t}: {total['ok:' + t]}/{total[k]}")
        for k, v in sorted(((k, v) for k, v in total.items() if k.startswith("confusion:")), key=lambda kv: -kv[1]):
            print(f"  {k[10:]}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
