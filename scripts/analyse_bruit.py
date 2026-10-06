#!/usr/bin/env python
"""Ventilation du bruit « à vérifier » d'un banc (outil d'analyse, dev seulement).

Joint ``<run>/metrics.json`` (classes du correcteur ``bench.score``, à lancer avant), ``<run>/<dossier>/findings.json``
(raisons, sous-contrôle, documents) et ``<corpus>/<split>/<dossier>/truth.json`` (type, format, mise en page,
gabarit, dégradation des documents ; pièges). Le bruit est la classe ``fp_a_verifier`` du correcteur (constat « à
vérifier » apparié à aucune erreur), dont ``bruit_a_verifier_par_dossier`` est le ratio ; il se divise en
**non apparié** (motif ``non_apparie``) et **piège déclenché** (motif ``piege`` : niveau au-dessus du maximum
toléré par le piège).

Sorties (texte, ou JSON avec ``--json``) :

- totaux (bruit, par dossier, non appariés, pièges déclenchés, pièges tolérés) ;
- par contrôle × sous-contrôle, et par contrôle × raison (``raisons`` du constat) ;
- par type de document concerné × format × dégradation, par mise en page de déclaration, par gabarit de
  transitaire ;
- pièges déclenchés par contrôle et par description (texte de vérité) ;
- constats en double dans un même lot (même contrôle, même libellé) ;
- avec ``--avant RUN`` (un par ``--run``) : différence par contrôle × sous-contrôle.

Exemples ::

    python scripts/analyse_bruit.py --corpus bench/corpus_g4 --run bench/out/g4_dev_blocA
    python scripts/analyse_bruit.py --corpus bench/corpus_g4 bench/corpus_g2 --run bench/out/g4_dev_lot2 \\
        bench/out/g2_dev_lot2 --avant bench/out/g4_dev_blocA bench/out/g2_dev_blocA --controle P4 --exemples 10

L'outil refuse le split ``holdout`` (jeux tenus à l'écart : seuls leurs totaux sont lus, par ``bench.score``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SPLITS_AUTORISES = ("dev",)


@dataclass
class Bruit:
    """Un constat « à vérifier » non apparié (ou piège déclenché), enrichi."""

    jeu: str
    dossier_id: str
    finding_id: str
    controle_id: str
    sous_controle: str | None
    motif: str  # non_apparie | piege
    raisons: list[str] = field(default_factory=list)
    libelle: str = ""
    types_docs: list[str] = field(default_factory=list)  # type/format/dégradation par document concerné
    degradations: list[str] = field(default_factory=list)
    mise_en_page: str | None = None  # declaration_layout du dossier
    gabarit: str | None = None  # transitaire_template du dossier
    degradation_dossier: str | None = None
    piege: str | None = None
    piege_description: str | None = None


def _lire_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _docs_verite_par_fichier(truth: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {d.get("file"): d for d in truth.get("documents", []) if isinstance(d, dict) and d.get("file")}


def _decrire_doc(dv: dict[str, Any] | None, doc_run: dict[str, Any] | None) -> tuple[str, str]:
    if dv is None:
        typ = (doc_run or {}).get("type") or "?"
        return f"{typ}/?/?", "?"
    typ = dv.get("type") or "?"
    fmt = dv.get("format") or "?"
    deg = dv.get("degradation") or "?"
    mode = dv.get("degradation_mode")
    lay = dv.get("declaration_layout") or dv.get("transitaire_template") or dv.get("ci_layout")
    desc = f"{typ}/{fmt}/{deg}"
    if lay:
        desc += f"/{lay}"
    return desc, f"{deg}:{mode}" if mode else deg


def collecter(corpus: Path, split: str, run: Path) -> tuple[list[Bruit], dict[str, Any]]:
    """Constats de bruit d'un banc et compteurs (le correcteur doit avoir écrit ``metrics.json``)."""
    if split not in SPLITS_AUTORISES:
        raise ValueError(f"split refusé : {split} (dev seulement)")
    metrics = _lire_json(run / "metrics.json")
    jeu = run.name
    details = metrics.get("details") or []
    par_dossier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in details:
        if d.get("classe") == "fp_a_verifier":
            par_dossier[d["dossier_id"]].append(d)
    tol = Counter()
    for d in details:
        if d.get("classe") == "piege_tolere":
            tol[d.get("controle_id")] += 1
    out: list[Bruit] = []
    doublons: list[tuple[str, str, str, int]] = []
    for dossier_id in sorted({d.get("dossier_id") for d in details if d.get("dossier_id")}):
        fp = run / dossier_id / "findings.json"
        tp = corpus / split / dossier_id / "truth.json"
        if not fp.exists() or not tp.exists():
            continue
        findings = _lire_json(fp)
        truth = _lire_json(tp)
        cles = Counter((c.get("controle_id"), c.get("libelle")) for c in findings.get("constats", [])
                       if c.get("niveau") in ("a_verifier", "ecart_certain"))
        for (cid, lib), n in cles.items():
            if n > 1:
                doublons.append((dossier_id, cid or "?", lib or "", n))
        constats = {c.get("finding_id"): c for c in findings.get("constats", [])}
        docs_run = {d.get("document_id"): d for d in findings.get("documents", [])}
        docs_v = _docs_verite_par_fichier(truth)
        pieges = {t.get("trap_id"): t for t in truth.get("traps", [])}
        for d in par_dossier.get(dossier_id, []):
            c = constats.get(d.get("finding_id"), {})
            types, degs = [], []
            for did in c.get("documents_concernes") or []:
                dr = docs_run.get(did)
                dv = docs_v.get((dr or {}).get("file"))
                t, g = _decrire_doc(dv, dr)
                types.append(t)
                degs.append(g)
            piege = d.get("trap_id")
            out.append(Bruit(
                jeu=jeu, dossier_id=dossier_id, finding_id=d.get("finding_id") or "",
                controle_id=d.get("controle_id") or c.get("controle_id") or "?",
                sous_controle=c.get("sous_controle"), motif=d.get("motif") or "non_apparie",
                raisons=list(c.get("raisons") or []), libelle=c.get("libelle") or "",
                types_docs=sorted(set(types)), degradations=sorted(set(degs)),
                mise_en_page=truth.get("declaration_layout"), gabarit=truth.get("transitaire_template"),
                degradation_dossier=truth.get("degradation"), piege=piege,
                piege_description=(pieges.get(piege) or {}).get("description") if piege else None,
            ))
    g = metrics.get("global", {})
    compteurs = {
        "jeu": jeu, "n_dossiers": g.get("n_dossiers"), "fp_a_verifier": g.get("fp_a_verifier"),
        "bruit_par_dossier": g.get("bruit_a_verifier_par_dossier"), "violations_pieges": g.get("violations_pieges"),
        "pieges_toleres": dict(tol), "doublons_lot": doublons,
        "vp_certain": g.get("vp_certain"), "fp_certain": g.get("fp_certain"), "rappel": g.get("rappel"),
        "rappel_certain": g.get("rappel_certain"),
    }
    return out, compteurs


def _cle_sc(b: Bruit) -> str:
    return f"{b.controle_id}:{b.sous_controle}" if b.sous_controle else b.controle_id


def ventiler(bruits: Iterable[Bruit]) -> dict[str, Counter]:
    """Tables de ventilation (compteurs) d'une liste de constats de bruit."""
    t: dict[str, Counter] = defaultdict(Counter)
    for b in bruits:
        sc = _cle_sc(b)
        t["controle"][b.controle_id] += 1
        t["controle_sous"][sc] += 1
        t["motif"][b.motif] += 1
        for r in b.raisons or ["(aucune)"]:
            t["controle_raison"][f"{sc} | {r}"] += 1
        for ty in b.types_docs or ["(aucun document)"]:
            t["type_doc"][ty] += 1
            t["controle_type_doc"][f"{sc} | {ty}"] += 1
        for dg in b.degradations or ["?"]:
            t["degradation_doc"][dg] += 1
        t["mise_en_page"][b.mise_en_page or "?"] += 1
        t["gabarit"][b.gabarit or "?"] += 1
        t["degradation_dossier"][b.degradation_dossier or "?"] += 1
        if b.motif == "piege":
            t["pieges_controle"][sc] += 1
            t["pieges_description"][f"{b.controle_id} | {b.piege_description}"] += 1
    return t


def _imprimer_table(titre: str, c: Counter, n: int, top: int) -> None:
    if not c:
        return
    print(f"\n## {titre}")
    for k, v in c.most_common(top):
        print(f"  {v:5d}  {k}")
    if len(c) > top:
        print(f"  ...   ({len(c) - top} autres, {sum(v for _k, v in c.most_common()[top:])} constats)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="analyse_bruit", description=__doc__.split("\n\n")[0])
    ap.add_argument("--corpus", nargs="+", required=True, type=Path)
    ap.add_argument("--split", default="dev", choices=list(SPLITS_AUTORISES))
    ap.add_argument("--run", nargs="+", required=True, type=Path)
    ap.add_argument("--avant", nargs="+", type=Path, default=None, help="bancs de référence (un par --run)")
    ap.add_argument("--controle", default=None, help="restreindre à un contrôle (ex. P4, D1)")
    ap.add_argument("--exemples", type=int, default=0, help="nombre de libellés d'exemple à afficher")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", type=Path, default=None, help="écrire la ventilation en JSON")
    args = ap.parse_args(argv)
    if len(args.corpus) not in (1, len(args.run)):
        ap.error("--corpus : un seul, ou un par --run")
    if args.avant and len(args.avant) != len(args.run):
        ap.error("--avant : un par --run")
    corpora = args.corpus * len(args.run) if len(args.corpus) == 1 else args.corpus

    def charger(runs: list[Path]) -> tuple[list[Bruit], list[dict[str, Any]]]:
        tous, cpts = [], []
        for corpus, run in zip(corpora, runs, strict=True):
            b, c = collecter(corpus, args.split, run)
            tous.extend(b)
            cpts.append(c)
        if args.controle:
            tous = [b for b in tous if b.controle_id == args.controle]
        return tous, cpts

    bruits, cpts = charger(args.run)
    tables = ventiler(bruits)
    n_dossiers = sum(c["n_dossiers"] or 0 for c in cpts)
    print("# Bruit « à vérifier » (fp_a_verifier)" + (f" — contrôle {args.controle}" if args.controle else ""))
    for c in cpts:
        print(f"  {c['jeu']}: {c['n_dossiers']} dossiers, bruit {c['fp_a_verifier']} "
              f"({c['bruit_par_dossier']} / dossier), pièges déclenchés {c['violations_pieges']}, "
              f"VP/FP certains {c['vp_certain']}/{c['fp_certain']}, rappel {c['rappel']}, "
              f"rappel certain {c['rappel_certain']}, doublons de lot {len(c['doublons_lot'])}")
    print(f"  total : {len(bruits)} constats sur {n_dossiers} dossiers "
          f"({len(bruits) / n_dossiers:.3f} / dossier)" if n_dossiers else "")
    for cle, titre in (("motif", "Motif"), ("controle_sous", "Contrôle × sous-contrôle"),
                       ("controle_raison", "Contrôle × raison"), ("type_doc", "Type / format / dégradation"),
                       ("controle_type_doc", "Contrôle × document"), ("degradation_doc", "Dégradation des documents"),
                       ("mise_en_page", "Mise en page de la déclaration (dossier)"),
                       ("gabarit", "Gabarit de transitaire (dossier)"),
                       ("pieges_controle", "Pièges déclenchés par contrôle"),
                       ("pieges_description", "Pièges déclenchés par description")):
        _imprimer_table(titre, tables.get(cle, Counter()), n_dossiers, args.top)
    doublons = [d for c in cpts for d in c["doublons_lot"] if not args.controle or d[1] == args.controle]
    if doublons:
        par_ctl = Counter(d[1] for d in doublons)
        print("\n## Constats en double dans un lot (contrôle : nombre de libellés répétés)")
        print("  " + ", ".join(f"{k} {v}" for k, v in par_ctl.most_common()))
    if args.avant:
        avant, cpts_av = charger(args.avant)
        ta = ventiler(avant)["controle_sous"]
        tb = tables["controle_sous"]
        print(f"\n## Différence avec --avant ({len(avant)} -> {len(bruits)})")
        for k in sorted(set(ta) | set(tb), key=lambda k: (tb.get(k, 0) - ta.get(k, 0), k)):
            if ta.get(k, 0) != tb.get(k, 0):
                print(f"  {ta.get(k, 0):5d} -> {tb.get(k, 0):5d}  {k}")
        ids_av = {(b.jeu.split('_')[0], b.dossier_id, b.controle_id, b.libelle) for b in avant}
        nouveaux = [b for b in bruits if (b.jeu.split('_')[0], b.dossier_id, b.controle_id, b.libelle) not in ids_av]
        if nouveaux and args.exemples:
            print("\n## Nouveaux constats de bruit (absents de --avant)")
            for b in nouveaux[: args.exemples]:
                print(f"  {b.dossier_id} {_cle_sc(b)} {b.raisons}: {b.libelle[:220]}")
    if args.exemples:
        print("\n## Exemples")
        for b in bruits[: args.exemples]:
            print(f"  {b.dossier_id} {_cle_sc(b)} {b.motif} {b.raisons} {b.types_docs}: {b.libelle[:220]}")
    if args.json:
        args.json.write_text(json.dumps({
            "compteurs": cpts, "tables": {k: dict(v) for k, v in tables.items()},
            "constats": [asdict(b) for b in bruits]}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
