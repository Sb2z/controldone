#!/usr/bin/env python
"""Mesure de la qualité de l'OCR sur les pages scannées du banc (outil de mesure, jamais appelé par ``src/``).

Pour chaque dossier du split **dev** (le split ``holdout`` est refusé), les documents de vérité scannés
(``format`` ``pdf_scan`` ou ``image``) sont passés par l'ingestion (``controldone.ingest.pages.textes_pages``,
comme le pipeline), puis le texte de leurs pages est comparé aux valeurs de ``truth_values`` du document :

- valeurs retenues : montants et nombres (au moins 3 chiffres significatifs), références et codes (lettres et
  chiffres, au moins 5 caractères : numéros de facture, MRN, TVA, EORI, titres de transport…), textes
  (noms, au moins 5 lettres). Les dates (formats imprimés variés) et les valeurs courtes sont ignorées ;
- normalisation : un montant ``157051.12`` est trouvé sous ``157 051,12``, ``157,051.12``, ``157.051,12``
  (séparateurs de milliers facultatifs, zéros décimaux finaux facultatifs) ; une référence ou un texte est
  comparé sans espaces, ponctuation, casse ni accents ;
- résultat : part des valeurs trouvées par mode de dégradation (``degradation_mode``) et par catégorie,
  confiance OCR moyenne, temps par page (p50/p95) quand le cache n'a pas servi.

La vérité (``truth.json``) n'est lue qu'ici. Le cache de pages est **désactivé par défaut** (``--cache`` pour
en donner un, propre à l'expérience : ne pas réutiliser les caches partagés ``var/cache/*_pages``).

Exemples ::

    python scripts/mesure_ocr.py --corpus bench/corpus_g4 --json /tmp/ocr_g4.json
    python scripts/mesure_ocr.py --corpus bench/corpus_g2 --modes fax,faxtiff --jobs 4
    python scripts/mesure_ocr.py --compare /tmp/avant.json /tmp/apres.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
#: ``MESURE_OCR_SRC`` : autre arbre de sources à mesurer (comparaison avant/après sur une copie de ``src``) ;
#: implique l'extraction sans processus isolé (le forkserver importerait les sources installées).
SOURCES = os.environ.get("MESURE_OCR_SRC") or str(RACINE / "src")
if SOURCES not in sys.path:
    sys.path.insert(0, SOURCES)

FORMATS_SCANNES = ("pdf_scan", "image")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NOMBRE = re.compile(r"^-?(\d+)(?:\.(\d+))?$")
_SEP_MILLIERS = r"[\s.,'’  ]?"


# --- valeurs de vérité ------------------------------------------------------------------------------------


def _feuilles(obj: Any, chemin: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _feuilles(v, f"{chemin}.{k}" if chemin else k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _feuilles(v, f"{chemin}[]")
    else:
        yield chemin, obj


def _compacter(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if c.isalnum()).upper()


def valeurs_verite(valeurs: dict) -> list[tuple[str, str, str]]:
    """(catégorie, chemin, valeur) des valeurs de vérité vérifiables dans le texte d'une page."""
    sortie: list[tuple[str, str, str]] = []
    vus: set[tuple[str, str]] = set()
    for chemin, v in _feuilles(valeurs):
        if v is None or isinstance(v, bool):
            continue
        s = str(v).strip()
        if not s or _DATE.match(s):
            continue
        m = _NOMBRE.match(s)
        if m:
            chiffres = m.group(1).lstrip("0") + (m.group(2) or "").rstrip("0")
            if len(chiffres) < 3:
                continue
            cat = "montant"
        else:
            c = _compacter(s)
            if any(ch.isdigit() for ch in c):
                if len(c) < 5:
                    continue
                cat = "reference"
            else:
                if len(c) < 5:
                    continue
                cat = "texte"
        if (cat, s) in vus:
            continue
        vus.add((cat, s))
        sortie.append((cat, chemin, s))
    return sortie


def motif_montant(s: str) -> re.Pattern[str]:
    m = _NOMBRE.match(s)
    assert m
    entier, dec = m.group(1).lstrip("0") or "0", (m.group(2) or "").rstrip("0")
    groupes = []
    while len(entier) > 3:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    groupes.insert(0, entier)
    corps = _SEP_MILLIERS.join(groupes)
    queue = rf"[.,]{dec}0*" if dec else r"(?:[.,]0+)?"
    return re.compile(rf"(?<!\d){corps}{queue}(?!\d)")


def trouvee(cat: str, valeur: str, texte: str, compact: str) -> bool:
    if cat == "montant":
        return bool(motif_montant(valeur).search(texte))
    return _compacter(valeur) in compact


# --- un fichier ---------------------------------------------------------------------------------------------


def _mesurer_fichier(t: dict) -> dict:
    from controldone.ingest.pages import OptionsPages, textes_pages
    from controldone.ingest.sniff import detecter_type

    if t.get("reglages"):  # variante de prétraitement (sans processus isolé : réglages du processus courant)
        import controldone.ingest.pages as module_pages

        module_pages.REGLAGES_OCR.update(t["reglages"])
    chemin = Path(t["chemin"])
    contenu = chemin.read_bytes()
    opts = OptionsPages(cache_dir=t.get("cache") or None, isoler=t.get("isoler", True))
    debut = time.perf_counter()
    try:
        pages = textes_pages(contenu, type_mime=detecter_type(contenu, chemin.name), options=opts)
    except Exception as e:  # mesure : on note l'échec
        return {"chemin": str(chemin), "erreur": f"{type(e).__name__}: {e}"[:200]}
    duree = time.perf_counter() - debut
    return {
        "chemin": str(chemin),
        "duree": duree,
        "pages": [
            {
                "numero": p.numero,
                "texte": p.texte,
                "score_ocr": p.score_ocr,
                "rotation": p.rotation,
                "qualite": p.qualite.value,
                "avert": p.avertissements,
            }
            for p in pages
        ],
    }


def taches_corpus(corpus: Path, modes: set[str] | None, dossiers: set[str] | None) -> list[dict]:
    """Une tâche par fichier contenant au moins un document scanné (split dev seulement)."""
    taches: dict[str, dict] = {}
    for dossier in sorted((corpus / "dev").iterdir()):
        if dossiers and dossier.name not in dossiers:
            continue
        vt = dossier / "truth.json"
        if not vt.exists():
            continue
        verite = json.loads(vt.read_text("utf-8"))
        if verite.get("split", "dev") != "dev":
            continue
        for d in verite["documents"]:
            if d.get("format") not in FORMATS_SCANNES:
                continue
            mode = d.get("degradation_mode") or d.get("degradation") or "?"
            if modes and mode not in modes:
                continue
            chemin = str(dossier / d["file"])
            tache = taches.setdefault(chemin, {"chemin": chemin, "docs": []})
            tache["docs"].append(
                {
                    "dossier": dossier.name,
                    "doc_id": d["doc_id"],
                    "type": d["type"],
                    "mode": mode,
                    "pages": d["pages"],
                    "valeurs": valeurs_verite(verite["truth_values"].get(d["doc_id"], {})),
                }
            )
    return list(taches.values())


def _centile(v: list[float], q: float) -> float:
    if not v:
        return 0.0
    v = sorted(v)
    return v[min(len(v) - 1, round(q * (len(v) - 1)))]


def mesurer(
    corpus: Path, *, modes=None, dossiers=None, cache=None, jobs=4, isoler=True, reglages: dict | None = None
) -> dict:
    taches = taches_corpus(corpus, modes, dossiers)
    # Réglages ou autre arbre de sources : le processus isolé (forkserver) importerait le module installé.
    isoler = isoler and not reglages and "MESURE_OCR_SRC" not in os.environ
    for t in taches:
        t["cache"], t["isoler"], t["reglages"] = cache, isoler, reglages
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        resultats = list(ex.map(_mesurer_fichier, taches, chunksize=1))
    docs = []
    temps_page: dict[str, list[float]] = defaultdict(list)
    for t, r in zip(taches, resultats, strict=True):
        if "erreur" in r:
            print(f"ERREUR {t['chemin']}: {r['erreur']}", file=sys.stderr)
            continue
        par_num = {p["numero"]: p for p in r["pages"]}
        for d in t["docs"]:
            ps = [par_num[n] for n in d["pages"] if n in par_num]
            texte = unicodedata.normalize("NFKC", "\n".join(p["texte"] for p in ps))
            compact = _compacter(texte)
            res = [(cat, ch, v, trouvee(cat, v, texte, compact)) for cat, ch, v in d["valeurs"]]
            scores = [p["score_ocr"] for p in ps if p["score_ocr"] is not None]
            docs.append(
                {
                    "dossier": d["dossier"],
                    "doc_id": d["doc_id"],
                    "type": d["type"],
                    "mode": d["mode"],
                    "fichier": t["chemin"],
                    "pages": len(ps),
                    "score_ocr": statistics.mean(scores) if scores else None,
                    "rotations": [p["rotation"] for p in ps],
                    "valeurs": [[cat, ch, v, ok] for cat, ch, v, ok in res],
                }
            )
            temps_page[d["mode"]].extend([r["duree"] / max(1, len(r["pages"]))] * len(ps))
    return {"corpus": str(corpus), "docs": docs, "temps_page": temps_page}


def resumer(res: dict) -> dict[str, dict]:
    groupes: dict[str, dict] = defaultdict(
        lambda: {"docs": 0, "pages": 0, "scores": [], "cat": defaultdict(lambda: [0, 0])}
    )
    for d in res["docs"]:
        for cle in (d["mode"], "TOUT"):
            g = groupes[cle]
            g["docs"] += 1
            g["pages"] += d["pages"]
            if d["score_ocr"] is not None:
                g["scores"].append(d["score_ocr"])
            for cat, _ch, _v, ok in d["valeurs"]:
                for c in (cat, "toutes"):
                    g["cat"][c][0] += int(ok)
                    g["cat"][c][1] += 1
    sortie = {}
    tous_temps = [x for v in res["temps_page"].values() for x in v]
    for cle, g in groupes.items():
        temps = tous_temps if cle == "TOUT" else res["temps_page"].get(cle, [])
        sortie[cle] = {
            "docs": g["docs"],
            "pages": g["pages"],
            "score_ocr": round(statistics.mean(g["scores"]), 3) if g["scores"] else None,
            "valeurs": {c: [ok, n, round(ok / n, 4) if n else None] for c, (ok, n) in g["cat"].items()},
            "p50_s": round(_centile(temps, 0.5), 2),
            "p95_s": round(_centile(temps, 0.95), 2),
        }
    return sortie


def afficher(resume: dict[str, dict], titre: str = "") -> None:
    if titre:
        print(titre)
    print(
        f"{'mode':<12}{'docs':>5}{'pages':>6}{'conf':>7}{'toutes':>16}{'montant':>16}{'reference':>16}"
        f"{'texte':>16}{'p50 s':>7}{'p95 s':>7}"
    )
    for cle in sorted(resume, key=lambda k: (k == "TOUT", k)):
        g = resume[cle]

        def f(c, g=g):
            v = g["valeurs"].get(c)
            return f"{v[0]}/{v[1]} {100 * v[2]:.1f}%" if v and v[1] else "-"

        conf = f"{g['score_ocr']:.3f}" if g["score_ocr"] is not None else "-"
        print(
            f"{cle:<12}{g['docs']:>5}{g['pages']:>6}{conf:>7}{f('toutes'):>16}{f('montant'):>16}"
            f"{f('reference'):>16}{f('texte'):>16}{g['p50_s']:>7}{g['p95_s']:>7}"
        )


def comparer(avant: dict, apres: dict) -> None:
    ra, rb = resumer(avant), resumer(apres)
    print(
        f"{'mode':<12}{'pages':>6}{'avant':>9}{'après':>9}{'delta':>8}{'conf av':>9}{'conf ap':>9}"
        f"{'p50 av':>8}{'p50 ap':>8}{'p95 av':>8}{'p95 ap':>8}"
    )
    for cle in sorted(set(ra) | set(rb), key=lambda k: (k == "TOUT", k)):
        a, b = ra.get(cle), rb.get(cle)
        if not a or not b:
            continue
        va, vb = a["valeurs"]["toutes"][2] or 0, b["valeurs"]["toutes"][2] or 0
        print(
            f"{cle:<12}{b['pages']:>6}{100 * va:>8.1f}%{100 * vb:>8.1f}%{100 * (vb - va):>+7.1f}"
            f"{a['score_ocr'] or 0:>9.3f}{b['score_ocr'] or 0:>9.3f}{a['p50_s']:>8}{b['p50_s']:>8}"
            f"{a['p95_s']:>8}{b['p95_s']:>8}"
        )
    # documents qui perdent ou gagnent des valeurs
    idx = {(d["dossier"], d["doc_id"]): d for d in avant["docs"]}
    pertes, gains = [], []
    for d in apres["docs"]:
        a = idx.get((d["dossier"], d["doc_id"]))
        if not a:
            continue
        ok_a = {(c, v) for c, _h, v, ok in a["valeurs"] if ok}
        ok_b = {(c, v) for c, _h, v, ok in d["valeurs"] if ok}
        if ok_a - ok_b:
            pertes.append((d["dossier"], d["doc_id"], d["mode"], len(ok_a - ok_b), len(ok_b - ok_a)))
        if ok_b - ok_a:
            gains.append((d["dossier"], d["doc_id"], d["mode"], len(ok_b - ok_a)))
    print(f"documents avec valeurs perdues : {len(pertes)} ; avec valeurs gagnées : {len(gains)}")
    for p in sorted(pertes, key=lambda x: -x[3])[:15]:
        print("  perte", *p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default=str(RACINE / "bench/corpus_g4"))
    ap.add_argument("--modes", default="", help="modes de dégradation retenus (séparés par des virgules)")
    ap.add_argument("--dossiers", default="")
    ap.add_argument("--cache", default=None, help="cache de pages propre à l'expérience (défaut : aucun)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--local", action="store_true", help="sans processus isolé (diagnostic)")
    ap.add_argument(
        "--reglages", default=None, help="JSON fusionné dans pages.REGLAGES_OCR (variante ; implique --local)"
    )
    ap.add_argument("--json", default=None, help="écrit le détail (textes non inclus) dans ce fichier")
    ap.add_argument("--compare", nargs=2, metavar=("AVANT", "APRES"), help="compare deux résultats JSON")
    a = ap.parse_args(argv)
    if a.compare:
        avant, apres = (json.loads(Path(p).read_text("utf-8")) for p in a.compare)
        comparer(avant, apres)
        return 0
    corpus = Path(a.corpus).resolve()
    if "holdout" in corpus.parts or corpus.name == "corpus_g3":
        ap.error("corpus ou split interdit")
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    res = mesurer(
        corpus,
        modes=set(filter(None, a.modes.split(","))) or None,
        dossiers=set(filter(None, a.dossiers.split(","))) or None,
        cache=a.cache,
        jobs=a.jobs,
        isoler=not a.local,
        reglages=json.loads(a.reglages) if a.reglages else None,
    )
    import controldone.ingest.pages as module_pages

    afficher(resumer(res), f"OCR {corpus.name} (dev) — sources {Path(module_pages.__file__).parents[2]}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
