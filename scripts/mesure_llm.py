#!/usr/bin/env python
"""Mesure de la lecture par modèle de langage sur un petit échantillon du banc (D-4008).

À lancer **par le fondateur, une fois la clé configurée** (chaque exécution dépense de l'argent, plafonné par
``--budget-eur``) ::

    python scripts/mesure_llm.py --corpus bench/corpus_g4 --limit 20 --confirmer-depense
    python scripts/mesure_llm.py --corpus bench/corpus_g4 --limit 20 --effort medium --confirmer-depense

Deux exécutions du système sur les **mêmes** dossiers du split ``dev`` (jamais ``holdout``) :

1. ``deterministe`` : extracteurs structure + déterministe seuls (référence) ;
2. ``llm`` : mêmes extracteurs + extracteur ``llm`` (appelé seulement là où le déterministe est faible, D-4001),
   un seul processus, budget total plafonné **avant** chaque appel (``CostGuard``).

Puis le correcteur du banc (``bench.score``) sur chaque sortie et un rapport ``<out>/rapport.md`` (+ ``.json``) :

- coût total, coût par dossier (moyen, maximal), nombre d'appels, motifs d'appel, cache de prompt ;
- latence par appel (médiane, 95e centile) ;
- valeurs proposées / ancrées exactement / ancrées « proches » / rejetées / ajoutées à l'extraction ;
- exactitude d'extraction par champ (correcteur) : déterministe contre déterministe + modèle ;
- effet sur le banc : précision « certain », rappel, faux « certain » ; **verdict** : précision ≥ 0,97 et
  **aucun nouveau faux certain** (sinon code retour 1).

Le correcteur compte comme manqués les dossiers hors échantillon : le rappel absolu n'a pas de sens sur un
échantillon, seule la comparaison des deux exécutions en a. Le système ne lit jamais ``truth.json`` ; seul le
correcteur le lit (comme ``bench_run``).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
for chemin in (RACINE / "src", RACINE):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

SEUIL_PRECISION = 0.97
SPLIT = "dev"  # jamais holdout


class _RegistreGlobal:
    """Registre de coûts de la mesure : un seul budget pour tous les clients du banc."""

    def __init__(self) -> None:
        from controldone.extract.llm import RegistreCoutsMemoire

        self.r = RegistreCoutsMemoire()

    def total_dossier(self, dossier_id: str) -> Decimal:
        return self.r.total_dossier(dossier_id)

    def total_client_mois(self, client_id: str, mois: str) -> Decimal:
        return self.r.total

    def enregistrer(self, entree: Any) -> None:
        self.r.enregistrer(entree)


def composants(
    avec_llm: bool,
    *,
    client: Any = None,
    budget_eur: Decimal = Decimal("5"),
    journal: list | None = None,
    settings: Any = None,
) -> Any:
    """Composants du pipeline : toujours sans ``llm`` pour la référence, même si une clé est configurée."""
    from controldone.extract.llm import CostGuard, LLMExtracteur
    from controldone.pipeline import Composants, _decoupeur_ingestion, _extracteurs_disponibles

    extracteurs = [e for e in _extracteurs_disponibles() if e.type != "llm"]
    if avec_llm:
        s = settings
        guard = CostGuard(
            _RegistreGlobal(),
            plafond_dossier=(s.llm_plafond_dossier_eur if s else Decimal("0.50")),
            plafond_client_mensuel=budget_eur,
        )
        extracteurs.append(LLMExtracteur(client=client, settings=s, cost_guard=guard, journal=journal))
    return Composants(decoupeur=_decoupeur_ingestion(), extracteurs=extracteurs)


def executer(
    corpus: Path, dossiers: Sequence[str], out: Path, comp: Any, *, workers: int, journal: list | None = None
) -> dict:
    """``bench_run.executer_banc`` sur l'échantillon ; avec ``journal``, chaque entrée est étiquetée du dossier."""
    from controldone import bench_run

    if journal is None:
        return bench_run.executer_banc(
            corpus, SPLIT, out, workers=workers, composants=comp, only=list(dossiers)
        )
    origine = bench_run._passe_preparation

    def preparation(d: Any) -> Any:
        n = len(journal)
        res = origine(d)
        for e in journal[n:]:
            e.setdefault("dossier", d.dossier_id)
        return res

    bench_run._passe_preparation = preparation  # un seul processus : la liste est partagée
    try:
        return bench_run.executer_banc(corpus, SPLIT, out, workers=1, composants=comp, only=list(dossiers))
    finally:
        bench_run._passe_preparation = origine


def scorer_run(corpus: Path, run: Path) -> dict:
    from bench.score.core import scorer

    m = scorer(corpus, SPLIT, run)
    (run / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return m


def _faux_certains(m: dict) -> Counter:
    return Counter(
        (d["dossier_id"], d["controle_id"]) for d in m.get("details", []) if d.get("classe") == "fp_certain"
    )


def _centile(valeurs: list[float], q: float) -> float | None:
    if not valeurs:
        return None
    v = sorted(valeurs)
    return round(v[min(len(v) - 1, round(q * (len(v) - 1)))], 3)


def comparer(base: dict, llm: dict, journal: list[dict], dossiers: Sequence[str]) -> dict:
    gb, gl = base["global"], llm["global"]
    nouveaux = _faux_certains(llm) - _faux_certains(base)
    appels = [e for e in journal if "duree_s" in e and not e.get("depuis_cache")]
    couts = Counter()
    for e in journal:
        couts[e.get("dossier", "?")] += Decimal(e.get("cout_eur") or "0")
    total = sum(couts.values(), Decimal(0))
    par_dossier = [couts.get(d, Decimal(0)) for d in dossiers]
    stats = Counter()
    for e in journal:
        for k in ("proposees", "exactes", "proches", "rejetees", "completees"):
            stats[k] += int(e.get(k) or 0)
        for k in ("jetons_entree", "jetons_sortie", "jetons_lecture_cache", "jetons_ecriture_cache"):
            stats[k] += int(e.get(k) or 0)
    eb = (base.get("extraction_par_champ") or {}).get("global") or {}
    el = (llm.get("extraction_par_champ") or {}).get("global") or {}
    champs_b = (base.get("extraction_par_champ") or {}).get("champs") or {}
    champs_l = (llm.get("extraction_par_champ") or {}).get("champs") or {}
    deltas = []
    for k in sorted(set(champs_b) | set(champs_l)):
        a, b = (champs_b.get(k) or {}).get("exactitude"), (champs_l.get(k) or {}).get("exactitude")
        if a is not None and b is not None and a != b:
            deltas.append({"champ": k, "deterministe": a, "llm": b, "delta": round(b - a, 4)})
    deltas.sort(key=lambda x: x["delta"])
    precision = gl.get("precision_certain")
    verdict = (precision is None or precision >= SEUIL_PRECISION) and not nouveaux
    return {
        "n_dossiers": len(dossiers),
        "cout": {
            "total_eur": str(total),
            "par_dossier_moyen_eur": str((total / len(dossiers)).quantize(Decimal("0.000001")))
            if dossiers
            else "0",
            "par_dossier_max_eur": str(max(par_dossier, default=Decimal(0))),
            "appels": len(appels),
            "refus_plafond": sum(1 for e in journal if e.get("refus")),
            "motifs": dict(Counter(e.get("motif") for e in journal)),
            "jetons": {k: v for k, v in stats.items() if k.startswith("jetons")},
        },
        "latence_s": {
            "mediane": _centile([e["duree_s"] for e in appels], 0.5),
            "p95": _centile([e["duree_s"] for e in appels], 0.95),
        },
        "valeurs": {k: stats[k] for k in ("proposees", "exactes", "proches", "rejetees", "completees")},
        "extraction": {
            "deterministe": eb.get("exactitude"),
            "llm": el.get("exactitude"),
            "n": [eb.get("n"), el.get("n")],
            "champs_changes": deltas,
        },
        "banc": {
            "precision_certain": [gb.get("precision_certain"), precision],
            "rappel": [gb.get("rappel"), gl.get("rappel")],
            "fp_certain": [gb.get("fp_certain"), gl.get("fp_certain")],
            "vp_certain": [gb.get("vp_certain"), gl.get("vp_certain")],
            "nouveaux_faux_certains": [
                {"dossier": d, "controle": c, "n": n} for (d, c), n in sorted(nouveaux.items())
            ],
        },
        "verdict": {"passe": verdict, "seuil_precision": SEUIL_PRECISION},
    }


def rendre(r: dict, meta: dict) -> str:
    b, c, x = r["banc"], r["cout"], r["extraction"]
    lignes = [
        "# Mesure de la lecture par modèle de langage (D-4008)",
        "",
        f"Corpus `{meta['corpus']}` / {SPLIT}, {r['n_dossiers']} dossiers ; modèle `{meta['modele']}`, effort "
        f"`{meta['effort']}`, tarifs du {meta['date_tarifs']} ; budget {meta['budget_eur']} EUR.",
        "",
        "## Coût et latence",
        "",
        f"- Total : {c['total_eur']} EUR ; par dossier : moyen {c['par_dossier_moyen_eur']}, max {c['par_dossier_max_eur']} EUR",
        f"- Appels : {c['appels']} ; refus par plafond : {c['refus_plafond']} ; motifs : {c['motifs']}",
        f"- Jetons : {c['jetons']}",
        f"- Latence par appel : médiane {r['latence_s']['mediane']} s, p95 {r['latence_s']['p95']} s",
        "",
        "## Valeurs lues par le modèle",
        "",
        f"- {r['valeurs']}",
        "",
        "## Exactitude d'extraction (correcteur)",
        "",
        f"- Déterministe : {x['deterministe']} ; déterministe + modèle : {x['llm']} (n = {x['n']})",
    ]
    lignes += [f"  - `{d['champ']}` : {d['deterministe']} -> {d['llm']}" for d in x["champs_changes"][:20]]
    lignes += [
        "",
        "## Effet sur le banc (même échantillon)",
        "",
        "| | déterministe | + modèle |",
        "|---|---|---|",
        f"| précision certain | {b['precision_certain'][0]} | {b['precision_certain'][1]} |",
        f"| vrais certains | {b['vp_certain'][0]} | {b['vp_certain'][1]} |",
        f"| faux certains | {b['fp_certain'][0]} | {b['fp_certain'][1]} |",
        f"| rappel (échantillon, relatif) | {b['rappel'][0]} | {b['rappel'][1]} |",
        "",
        f"Nouveaux faux certains : {b['nouveaux_faux_certains'] or 'aucun'}",
        "",
        f"**Verdict : {'PASSE' if r['verdict']['passe'] else 'ÉCHOUE'}** (précision ≥ {SEUIL_PRECISION} et aucun "
        "nouveau faux certain).",
        "",
    ]
    return "\n".join(lignes)


def mesurer(
    corpus: Path,
    out: Path,
    *,
    limit: int,
    budget_eur: Decimal,
    workers: int = 4,
    client: Any = None,
    settings: Any = None,
    scorer: Callable[[Path, Path], dict] = scorer_run,
    executeur: Callable[..., dict] = executer,
) -> dict:
    from controldone.bench_run import lister_dossiers
    from controldone.extract.llm import charger_tarifs

    dossiers = [p.name for p in lister_dossiers(corpus, SPLIT, limit)]
    out.mkdir(parents=True, exist_ok=True)
    debut = time.perf_counter()
    executeur(corpus, dossiers, out / "deterministe", composants(False), workers=workers)
    journal: list[dict] = []
    executeur(
        corpus,
        dossiers,
        out / "llm",
        composants(True, client=client, budget_eur=budget_eur, journal=journal, settings=settings),
        workers=1,
        journal=journal,
    )
    r = comparer(scorer(corpus, out / "deterministe"), scorer(corpus, out / "llm"), journal, dossiers)
    s = settings
    if s is None:
        from controldone.config import get_settings

        s = get_settings()
    meta = {
        "corpus": str(corpus),
        "modele": s.llm_model,
        "effort": s.llm_effort or "défaut",
        "date_tarifs": charger_tarifs(s)[1],
        "budget_eur": str(budget_eur),
        "duree_s": round(time.perf_counter() - debut, 1),
        "dossiers": dossiers,
    }
    r["meta"] = meta
    (out / "journal_llm.json").write_text(
        json.dumps(journal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out / "rapport.json").write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "rapport.md").write_text(rendre(r, meta), encoding="utf-8")
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--corpus", type=Path, default=Path("bench/corpus_g4"))
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--workers", type=int, default=4, help="processus pour l'exécution de référence")
    ap.add_argument(
        "--budget-eur",
        type=Decimal,
        default=Decimal("5.00"),
        help="dépense maximale de la mesure, vérifiée avant chaque appel (défaut 5 EUR)",
    )
    ap.add_argument("--modele", default=None, help="remplace CONTROLDONE_LLM_MODEL pour cette mesure")
    ap.add_argument(
        "--effort", default=None, help="remplace CONTROLDONE_LLM_EFFORT (low, medium, high ; vide)"
    )
    ap.add_argument(
        "--confirmer-depense", action="store_true", help="obligatoire : la mesure appelle l'API payante"
    )
    args = ap.parse_args(argv)
    if "holdout" in str(args.corpus).lower():
        print("refusé : la mesure ne lit que le split dev", file=sys.stderr)
        return 2
    from controldone.config import get_settings

    s = get_settings()
    maj = {k: v for k, v in (("llm_model", args.modele), ("llm_effort", args.effort)) if v is not None}
    if maj:
        s = s.model_copy(update=maj)
    if not s.llm_disponible:
        print(
            "clé Anthropic absente (ANTHROPIC_API_KEY ou CONTROLDONE_ANTHROPIC_API_KEY) : rien à mesurer. "
            "Vérifier avec : controldone llm verifier",
            file=sys.stderr,
        )
        return 2
    if not args.confirmer_depense:
        print(
            f"cette mesure appelle l'API payante (budget maximal {args.budget_eur} EUR) : relancer avec "
            "--confirmer-depense",
            file=sys.stderr,
        )
        return 2
    out = args.out or Path("bench/out") / time.strftime("llm_%Y%m%d_%H%M%S")
    r = mesurer(
        args.corpus, out, limit=args.limit, budget_eur=args.budget_eur, workers=args.workers, settings=s
    )
    print((out / "rapport.md").read_text(encoding="utf-8"))
    return 0 if r["verdict"]["passe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
