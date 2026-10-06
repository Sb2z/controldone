"""Exécution du système sur le banc (SPEC §19.2) puis appel du correcteur.

    python -m controldone.bench_run --corpus bench/corpus --split dev --out bench/out/<run_id> \
        [--limit N] [--workers K] [--no-score]

Pour chaque client : ``clients/<id>/profil.json`` et les grilles validées ``clients/<id>/grilles/*.json``.
Chaque dossier ``<split>/<dossier_id>/docs/`` est traité comme **un lot** (frontière de regroupement).
Deux passes : (1) préparation de tous les dossiers (réception à regroupement), en parallèle ; (2) contrôles
de chaque dossier avec, pour la famille F, tous les dossiers du même client dans le split. Sortie :
``<out>/<dossier_id>/findings.json`` (``documents[].file`` relatifs, commençant par ``docs/``).

Le système ne lit **jamais** ``truth.json`` : seuls ``profil.json``, les grilles, ``manifest.json``
(répartition des dossiers par client, si elle y figure) et les fichiers ``docs/`` sont lus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import multiprocessing as mp
import subprocess
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from controldone.findings_io import Findings, ecrire_findings
from controldone.model.enums import StatutGlobal
from controldone.pipeline import (
    Composants,
    LotPrepare,
    OptionsPipeline,
    autres_dossiers_de,
    controler_lot,
    preparer_lot,
)
from controldone.referentiel_io import ProfilClient, charger_grilles, charger_profil_client

__all__ = [
    "DossierBanc",
    "assigner_clients",
    "executer_banc",
    "fusionner_findings",
    "lister_dossiers",
    "main",
]

log = logging.getLogger("controldone.bench_run")

FICHIER_INTERDIT = "truth.json"


@dataclass(frozen=True)
class DossierBanc:
    dossier_id: str
    chemin: Path  # <corpus>/<split>/<dossier_id>
    client_id: str | None


def lister_dossiers(
    corpus: Path, split: str, limit: int | None = None, only: Sequence[str] | None = None
) -> list[Path]:
    base = corpus / split
    if not base.is_dir():
        raise FileNotFoundError(f"split introuvable : {base}")
    dossiers = sorted(p for p in base.iterdir() if p.is_dir() and (p / "docs").is_dir())
    if only:
        voulus = set(only)
        dossiers = [p for p in dossiers if p.name in voulus]
    return dossiers[:limit] if limit else dossiers


def _clients(corpus: Path) -> dict[str, tuple[ProfilClient, list]]:
    out = {}
    base = corpus / "clients"
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        prof = d / "profil.json"
        if not prof.exists():
            continue
        profil = charger_profil_client(prof)
        out[profil.client_id] = (profil, charger_grilles(d / "grilles", client_id=profil.client_id))
    return out


def _client_manifeste(manifest: Any, dossier_id: str) -> str | None:
    """Client d'un dossier d'après ``manifest.json`` (plusieurs formes acceptées)."""
    if not isinstance(manifest, dict):
        return None
    entrees = manifest.get("dossiers")
    if isinstance(entrees, dict):
        e = entrees.get(dossier_id)
        if isinstance(e, dict):
            return e.get("client_id")
        if isinstance(e, str):
            return e
    if isinstance(entrees, list):
        for e in entrees:
            if isinstance(e, dict) and (e.get("dossier_id") or e.get("id")) == dossier_id:
                return e.get("client_id")
    clients = manifest.get("clients")
    if isinstance(clients, dict):
        for cid, ds in clients.items():
            if isinstance(ds, list) and dossier_id in ds:
                return cid
    return None


def _texte_brut(docs: Path, limite: int = 2_000_000) -> str:
    """Texte des fichiers d'un dossier (couche texte des PDF, fichiers XML/CSV) pour identifier le client
    quand le manifeste ne le dit pas. Lecture seule, rien n'est interprété."""
    morceaux: list[str] = []
    for f in sorted(docs.rglob("*")):
        if not f.is_file() or f.name == FICHIER_INTERDIT:
            continue
        try:
            if f.suffix.lower() == ".pdf":
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(str(f))
                try:
                    for i in range(min(len(pdf), 20)):
                        morceaux.append(pdf[i].get_textpage().get_text_range())
                finally:
                    pdf.close()
            elif f.suffix.lower() in (".xml", ".csv", ".txt", ".eml"):
                morceaux.append(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if sum(len(m) for m in morceaux) > limite:
            break
    return "\n".join(morceaux)


def assigner_clients(dossiers: Sequence[Path], corpus: Path, clients: dict[str, Any]) -> list[DossierBanc]:
    """Client de chaque dossier : manifeste, sinon client unique, sinon identifiants d'entités trouvés dans
    le texte des documents (TVA, SIREN, EORI)."""
    manifest = None
    mf = corpus / "manifest.json"
    if mf.exists():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            manifest = None
    out = []
    for p in dossiers:
        cid = _client_manifeste(manifest, p.name)
        if cid is None and len(clients) == 1:
            cid = next(iter(clients))
        if cid is None and clients:
            from controldone.normalize.refs import norm_ref

            texte = norm_ref(_texte_brut(p / "docs"))
            scores = {}
            for k, (profil, _g) in clients.items():
                cles = [norm_ref(x) for e in profil.entites for x in (e.tva, e.siren, e.eori) if x]
                scores[k] = sum(texte.count(c) for c in cles if len(c) >= 9)
            meilleur = max(scores.items(), key=lambda kv: (kv[1], kv[0]))
            cid = meilleur[0] if meilleur[1] > 0 else None
        out.append(DossierBanc(p.name, p, cid))
    return out


def _graine(dossier_id: str) -> int:
    return int(hashlib.sha256(dossier_id.encode()).hexdigest()[:8], 16)


def _options(dossier_id: str) -> OptionsPipeline:
    return OptionsPipeline(seed=_graine(dossier_id), dossier_id_sortie=dossier_id, annee=2026)


# --- passes (exécutées dans les processus du pool) --------------------------------------------------

_CLIENTS: dict[str, tuple[ProfilClient, list]] = {}
_PREPARES: dict[str, LotPrepare] = {}
_CLIENT_DE: dict[str, str | None] = {}
_COMPOSANTS: Composants | None = None


def _profil(cid: str | None) -> tuple[ProfilClient | None, list]:
    if cid and cid in _CLIENTS:
        return _CLIENTS[cid]
    return None, []


def _passe_preparation(d: DossierBanc) -> tuple[str, LotPrepare | None, str | None]:
    logging.disable(logging.WARNING)
    try:
        profil, grilles = _profil(d.client_id)
        prep = preparer_lot(
            d.chemin / "docs", profil, grilles, options=_options(d.dossier_id), composants=_COMPOSANTS
        )
        return d.dossier_id, prep, None
    except Exception as e:  # un dossier en échec n'arrête pas le banc
        return d.dossier_id, None, f"{type(e).__name__}: {e}"[:300]


def _passe_controles(args: tuple[str, str]) -> tuple[str, dict[str, Any] | None, str | None]:
    dossier_id, out = args
    logging.disable(logging.WARNING)
    try:
        prep = _PREPARES[dossier_id]
        cid = _CLIENT_DE.get(dossier_id)
        autres = autres_dossiers_de(
            p for k, p in sorted(_PREPARES.items()) if k != dossier_id and _CLIENT_DE.get(k) == cid
        )
        res = controler_lot(prep, autres_dossiers=autres, options=_options(dossier_id))
        if not res:
            findings = _findings_vide(dossier_id, prep)
        else:
            findings = fusionner_findings([r.findings for r in res], dossier_id)
        ecrire_findings(findings, Path(out) / dossier_id / "findings.json")
        resume = {
            "dossiers_produits": len(res),
            "constats": len(findings.constats),
            "non_lus": [{"fichier": n.fichier, "motif": n.motif} for n in prep.non_lus],
            "statut_global": findings.statut_global,
            "duree_s": findings.execution.duree_s,
        }
        return dossier_id, resume, None
    except Exception as e:
        return dossier_id, None, f"{type(e).__name__}: {e}"[:300]


# --- fusion des sorties d'un lot ---------------------------------------------------------------------

_PRIORITE = [s.value for s in StatutGlobal]


def fusionner_findings(liste: Sequence[Findings], dossier_id: str) -> Findings:
    """Un ``findings.json`` par dossier du banc : réunit les dossiers produits pour le lot (orphelins
    compris). Statut global : le plus prioritaire (§18.2)."""
    if len(liste) == 1:
        return liste[0].model_copy(update={"dossier_id": dossier_id})
    base = liste[0]
    vus_docs, vus_liens, vus_constats = set(), set(), set()
    documents, liens, constats, resultats, valeurs = [], [], [], [], {}
    for f in liste:
        for d in f.documents:
            if d.document_id not in vus_docs:
                vus_docs.add(d.document_id)
                documents.append(d)
        for lien in f.liens:
            if lien.document_id not in vus_liens:
                vus_liens.add(lien.document_id)
                liens.append(lien)
        for c in f.constats:
            if c.finding_id not in vus_constats:
                vus_constats.add(c.finding_id)
                constats.append(c)
        resultats.extend(f.resultats)
        valeurs.update(f.valeurs)
    statut = min((f.statut_global for f in liste), key=_PRIORITE.index)
    return base.model_copy(
        update={
            "dossier_id": dossier_id,
            "dossier_version": max(f.dossier_version for f in liste),
            "documents": documents,
            "liens": liens,
            "valeurs": valeurs,
            "resultats": resultats,
            "constats": constats,
            "statut_global": statut,
        }
    )


def _findings_vide(dossier_id: str, prep: LotPrepare) -> Findings:
    from controldone.findings_io import FindingsExecution

    return Findings(
        dossier_id=dossier_id,
        dossier_version=1,
        execution=FindingsExecution(
            execution_id=f"exe_{prep.lot.id}",
            version_moteur="?",
            version_regles="?",
            cout_ia_eur=str(prep.cout.cout_eur.quantize(Decimal("0.01"))),
            duree_s=round(prep.duree_s, 3),
        ),
        statut_global=StatutGlobal.document_manquant.value,
    )


# --- orchestration -----------------------------------------------------------------------------------


def executer_banc(
    corpus: Path,
    split: str,
    out: Path,
    *,
    limit: int | None = None,
    workers: int = 4,
    composants: Composants | None = None,
    only: Sequence[str] | None = None,
) -> dict:
    """Passes 1 et 2 sur le split ; écrit les ``findings.json`` et ``run.json``. ``composants`` : doubles
    (tests) ; par défaut, composants publiés par les équipes ingestion et extraction."""
    global _CLIENTS, _PREPARES, _CLIENT_DE, _COMPOSANTS
    _COMPOSANTS = composants
    debut = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    _CLIENTS = _clients(corpus)
    dossiers = assigner_clients(lister_dossiers(corpus, split, limit, only), corpus, _CLIENTS)
    _CLIENT_DE = {d.dossier_id: d.client_id for d in dossiers}
    erreurs: dict[str, str] = {}
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()

    # passe 1 : préparation (réception -> regroupement)
    _PREPARES = {}
    if workers > 1 and len(dossiers) > 1:
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
            for did, prep, err in pool.map(_passe_preparation, dossiers, chunksize=1):
                if prep is not None:
                    _PREPARES[did] = prep
                else:
                    erreurs[did] = err or "?"
    else:
        for d in dossiers:
            did, prep, err = _passe_preparation(d)
            if prep is not None:
                _PREPARES[did] = prep
            else:
                erreurs[did] = err or "?"
    t1 = time.perf_counter() - debut

    # passe 2 : contrôles avec tous les dossiers du même client (famille F)
    resumes: dict[str, Any] = {}
    taches = [(did, str(out)) for did in sorted(_PREPARES)]
    if workers > 1 and len(taches) > 1:
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
            for did, resume, err in pool.map(_passe_controles, taches, chunksize=1):
                if resume is not None:
                    resumes[did] = resume
                else:
                    erreurs[did] = err or "?"
    else:
        for t in taches:
            did, resume, err = _passe_controles(t)
            if resume is not None:
                resumes[did] = resume
            else:
                erreurs[did] = err or "?"
    bilan = {
        "corpus": str(corpus),
        "split": split,
        "n_dossiers": len(dossiers),
        "workers": workers,
        "duree_preparation_s": round(t1, 2),
        "duree_totale_s": round(time.perf_counter() - debut, 2),
        "erreurs": erreurs,
        "dossiers": resumes,
        "clients": {d.dossier_id: d.client_id for d in dossiers},
    }
    (out / "run.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return bilan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m controldone.bench_run", description="Exécute le système sur le banc."
    )
    ap.add_argument("--corpus", type=Path, default=Path("bench/corpus"))
    ap.add_argument("--split", default="dev", choices=["dev", "holdout"])
    ap.add_argument("--out", type=Path, default=None, help="bench/out/<run_id> (défaut : horodaté)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--only",
        default=None,
        help="sous-ensemble de dossiers : BX0001,BX0002 (score sur ce seul "
        "sous-ensemble non significatif ; utiliser --no-score)",
    )
    ap.add_argument("--no-score", action="store_true", help="ne pas appeler le correcteur")
    args = ap.parse_args(argv)
    out = args.out or Path("bench/out") / time.strftime("run_%Y%m%d_%H%M%S")
    try:
        only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
        bilan = executer_banc(args.corpus, args.split, out, limit=args.limit, workers=args.workers, only=only)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    n_err = len(bilan["erreurs"])
    print(
        f"[bench_run] {bilan['n_dossiers']} dossiers traités en {bilan['duree_totale_s']} s "
        f"({args.workers} processus) ; erreurs : {n_err} ; sortie : {out}"
    )
    for did, err in sorted(bilan["erreurs"].items())[:10]:
        print(f"[bench_run] erreur {did} : {err}")
    if args.no_score:
        return 0
    cmd = [
        sys.executable,
        "-m",
        "bench.score",
        "--corpus",
        str(args.corpus),
        "--split",
        args.split,
        "--run",
        str(out),
    ]
    r = subprocess.run(cmd, check=False)
    resume = out / "metrics.md"
    if resume.exists():
        print(resume.read_text(encoding="utf-8")[:4000])
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
