#!/usr/bin/env python
"""Mesure du classement par page et du regroupement sur le banc (outil de mesure, jamais appelé par ``src/``).

Pour chaque dossier du split : étapes 1 à 6 du pipeline (``controldone.pipeline.preparer_lot``, comme le banc :
profil client, graine), puis comparaison à la vérité (``truth.json``), lue **ici seulement** :

- **classement par page** : chaque page de ``documents[]`` (fichier, n° de page) reçoit le type du document
  produit qui la contient ; exactitude du type, du couple (type, sous-type), matrice de confusion ;
- **regroupement** : les documents de vérité sont reliés par ``expected_links`` : un document est dans le groupe des documents qu'il cite ; un
  document produit est apparié au document de vérité dont il couvre le plus de pages ; une paire de documents de
  vérité est « regroupée » si leurs documents appariés sont dans un même dossier produit. Précision, rappel et
  F1 sur les paires ; nombre de liens ``faible`` (P4) et de dossiers incomplets (P1) produits.

Exemples ::

    CONTROLDONE_PAGES_CACHE_DIR=var/cache/g2_pages python scripts/mesure_classement.py --corpus bench/corpus_g2
    python scripts/mesure_classement.py --corpus bench/corpus --erreurs 40 --json /tmp/cls.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

_CLIENTS: dict[str, Any] = {}


def _init(corpus: str) -> None:
    from controldone import bench_run

    logging.disable(logging.WARNING)
    _CLIENTS.update(bench_run._clients(Path(corpus)))


def _rel(chemin: str) -> str:
    c = chemin.replace("\\", "/")
    return c[5:] if c.startswith("docs/") else c


def _mesurer(args: tuple[str, str, str | None]) -> dict[str, Any]:
    from controldone import bench_run
    from controldone.pipeline import preparer_lot

    chemin, dossier_id, client_id = args
    dossier = Path(chemin)
    profil, grilles = _CLIENTS.get(client_id or "", (None, []))
    try:
        prep = preparer_lot(dossier / "docs", profil, grilles, options=bench_run._options(dossier_id))
    except Exception as e:
        return {"dossier": dossier_id, "erreur": f"{type(e).__name__}: {e}"[:200]}
    vrai = json.loads((dossier / "truth.json").read_text(encoding="utf-8"))
    fic_chemin = {fid: _rel(f.chemin_relatif) for fid, f in prep.fichiers.items()}
    # page (fichier, n°) -> document produit
    page_doc: dict[tuple[str, int], str] = {}
    for d in sorted(prep.documents.values(), key=lambda x: bool(x.doublon_de)):
        for p in d.pages:
            page_doc.setdefault((fic_chemin.get(p.fichier_id, "?"), p.numero), d.id)
    textes = {(fic_chemin.get(fid, "?"), p.numero): p.texte for fid, ps in prep.pages.items() for p in ps}
    dossier_de: dict[str, list[int]] = defaultdict(list)
    force_de: dict[str, str] = {}
    for i, dos in enumerate(prep.dossiers):
        for li in dos.liens:
            dossier_de[li.document_id].append(i)
            if li.force.value == "faible":
                force_de[li.document_id] = "faible"
    pages_out = []
    appariement: dict[str, str | None] = {}
    for td in vrai["documents"]:
        f = _rel(td["file"])
        couverts: Counter[str] = Counter()
        for n in td["pages"]:
            did = page_doc.get((f, n))
            d = prep.documents.get(did) if did else None
            if did:
                couverts[did] += 1
            pages_out.append({
                "doc": td["doc_id"], "fichier": f, "page": n, "type": td["type"], "sous_type": td.get("sous_type"),
                "format": td.get("format"), "langue": td.get("language"),
                "gabarit": td.get("transitaire_template") or td.get("declaration_layout") or td.get("ci_layout"),
                "pred": d.type.value if d else None, "pred_st": d.sous_type if d else None,
                "conf": d.confiance_classement if d else None,
                "texte": (textes.get((f, n)) or "")[:400],
            })
        appariement[td["doc_id"]] = couverts.most_common(1)[0][0] if couverts else None
    # groupes de vérité : un document appartient au(x) groupe(s) des documents qu'il cite (expected_links), un
    # document qui ne cite rien forme son groupe ; une facture de transitaire mensuelle est dans plusieurs groupes.
    sortants: dict[str, list[str]] = defaultdict(list)
    for lk in vrai["expected_links"]:
        sortants[lk["from"]].append(lk["to"])

    def ancres(x: str, vus: frozenset[str] = frozenset()) -> set[str]:
        cibles = [y for y in sortants.get(x, []) if y not in vus]
        if not cibles:
            return {x}
        return set().union(*(ancres(y, vus | {x}) for y in cibles))

    lies = {lk["from"] for lk in vrai["expected_links"]} | {lk["to"] for lk in vrai["expected_links"]}
    # un document qu'aucun lien ne cite (vérité muette) est hors de la mesure
    ids = [td["doc_id"] for td in vrai["documents"] if td["doc_id"] in lies or len(vrai["documents"]) == 1]
    anc = {x: ancres(x) for x in ids}
    tp = fp = fn = 0
    paires_ko = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            attendu = bool(anc[a] & anc[b])
            da, db = appariement[a], appariement[b]
            ensemble = bool(da and db and (da == db or set(dossier_de.get(da, [])) & set(dossier_de.get(db, []))))
            if attendu and ensemble:
                tp += 1
            elif attendu:
                fn += 1
                paires_ko.append(("manque", a, b))
            elif ensemble:
                fp += 1
                paires_ko.append(("en_trop", a, b))
    faibles = [doc for doc, did in appariement.items() if did and force_de.get(did) == "faible"]
    return {
        "dossier": dossier_id, "pages": pages_out, "tp": tp, "fp": fp, "fn": fn, "paires_ko": paires_ko,
        "faibles": len([li for dos in prep.dossiers for li in dos.liens if li.force.value == "faible"]),
        "faibles_docs": faibles,
        "incomplets": sum(1 for dos in prep.dossiers if dos.incomplet),
        "dossiers": len(prep.dossiers),
        "attendus": len(set().union(*anc.values())) if anc else 0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="bench/corpus")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--dossiers", default=None, help="liste séparée par des virgules")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--erreurs", type=int, default=0, help="nombre de pages mal classées affichées")
    ap.add_argument("--json", default=None, help="sortie détaillée")
    a = ap.parse_args(argv)
    from controldone import bench_run

    corpus = Path(a.corpus)
    only = a.dossiers.split(",") if a.dossiers else None
    dossiers = bench_run.lister_dossiers(corpus, a.split, only=only)
    _init(str(corpus))
    banc = bench_run.assigner_clients(dossiers, corpus, _CLIENTS)
    taches = [(str(d.chemin), d.dossier_id, d.client_id) for d in banc]
    os.environ.setdefault("CONTROLDONE_PAGES_PARALLELE", "1")
    if a.workers > 1:
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(str(corpus),)) as ex:
            res = list(ex.map(_mesurer, taches, chunksize=1))
    else:
        res = [_mesurer(t) for t in taches]
    pages = [p for r in res for p in r.get("pages", [])]
    ok_t = sum(1 for p in pages if p["pred"] == p["type"])
    ok_st = sum(1 for p in pages if p["pred"] == p["type"] and (p["pred_st"] or None) == (p["sous_type"] or None))
    tp, fp, fn = (sum(r.get(k, 0) for r in res) for k in ("tp", "fp", "fn"))
    prec = tp / (tp + fp) if tp + fp else 1.0
    rap = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * prec * rap / (prec + rap) if prec + rap else 0.0
    print(f"corpus {a.corpus}/{a.split} : {len(res)} dossiers, {len(pages)} pages")
    print(f"classement type : {ok_t}/{len(pages)} = {ok_t / max(1, len(pages)):.4f}")
    print(f"type+sous-type  : {ok_st}/{len(pages)} = {ok_st / max(1, len(pages)):.4f}")
    print(f"regroupement paires : TP {tp} FP {fp} FN {fn} précision {prec:.4f} rappel {rap:.4f} F1 {f1:.4f}")
    print(f"liens faibles (P4) : {sum(r.get('faibles', 0) for r in res)} ; dossiers incomplets : "
          f"{sum(r.get('incomplets', 0) for r in res)} ; dossiers produits/attendus : "
          f"{sum(r.get('dossiers', 0) for r in res)}/{sum(r.get('attendus', 0) for r in res)}")
    erreurs = [r for r in res if "erreur" in r]
    if erreurs:
        print("erreurs :", [(r["dossier"], r["erreur"]) for r in erreurs])
    conf = Counter((p["type"], p["pred"]) for p in pages if p["pred"] != p["type"])
    print("confusions (vérité -> prédit) :")
    for (t, pr), n in conf.most_common(25):
        print(f"  {n:4d}  {t} -> {pr}")
    par_fmt: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for p in pages:
        k = f"{p['type']}/{p['format']}"
        par_fmt[k][1] += 1
        par_fmt[k][0] += p["pred"] == p["type"]
    print("par type/format :")
    for k, (o, n) in sorted(par_fmt.items()):
        print(f"  {k:45s} {o:4d}/{n:4d} {o / n:.3f}")
    if a.erreurs:
        print("pages mal classées :")
        for r in res:
            for p in r.get("pages", []):
                if p["pred"] != p["type"] and a.erreurs > 0:
                    a.erreurs -= 1
                    print(f"--- {r['dossier']} {p['doc']} {p['fichier']} p{p['page']} {p['type']}/{p['sous_type']} "
                          f"-> {p['pred']}/{p['pred_st']} ({p['conf']}) {p['format']} {p['langue']} {p['gabarit']}")
                    print("    " + p["texte"][:300].replace("\n", " | "))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
