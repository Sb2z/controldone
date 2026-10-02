"""Ligne de commande ``controldone``.

    controldone diagnostic <dossier_ou_fichier> [--client-profile p.json] [--grilles dir] --out <dir>
    controldone demo [--out var/demo] [--demo-dir demo] [--moteur auto|reel|demo]
    controldone serve [--host 127.0.0.1] [--port 8000] [--sans-worker] [--init-schema]
    controldone init-demo [--force] [--si-absente]

``diagnostic`` : exécute le pipeline sur un lot (chaque sous-dossier de premier niveau qui contient des
documents est une frontière de regroupement naturelle) et écrit ``report.html``, ``report.pdf``,
``report.json``, ``findings.json`` et ``findings.xlsx``.

``demo`` : génère le jeu **fictif** (3 dossiers) sous ``demo/``, exécute le diagnostic et écrit le rapport
dans ``var/demo/``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

__all__ = ["main"]


def _diagnostic(args: argparse.Namespace) -> int:
    from controldone.pipeline import OptionsPipeline, traiter_lot
    from controldone.rapport import generer_rapport
    from controldone.referentiel_io import charger_grilles, charger_profil_client

    source = Path(args.source)
    if not source.exists():
        print(f"Introuvable : {source}", file=sys.stderr)
        return 2
    profil = charger_profil_client(args.client_profile)
    grilles = charger_grilles(args.grilles, client_id=profil.client_id) if args.grilles else []
    options = OptionsPipeline(seed=args.seed, llm=not args.sans_llm)
    resultats = traiter_lot(source, profil, grilles, options=options)
    sorties = generer_rapport(resultats, profil, args.out)
    v = sorties.vue
    print(f"{len(resultats)} dossier(s) — recouvrable certain {v.recouvrable_certain} ; "
          f"à vérifier {v.recouvrable_a_verifier} ; points professionnels {v.nb_renvois} ; "
          f"non lus {len(v.non_lus)}")
    for nom in ("html", "pdf", "json", "findings", "xlsx"):
        print(f"  {nom:9s} {sorties[nom]}")
    return 0


def _demo(args: argparse.Namespace) -> int:
    from controldone.demo import executer_demo

    sorties = executer_demo(args.out, racine=args.demo_dir, moteur=args.moteur)
    v = sorties.vue
    print("Démonstration ControlDOne — DONNÉES FICTIVES")
    for d in v.dossiers:
        constats = ", ".join(f"{c.controle_id} ({c.niveau.lower()})" for c in d.constats) or "aucun constat"
        print(f"  {d.reference} : {d.statut} — {constats}")
    print(f"Rapport : {sorties.pdf.resolve()}")
    print(f"          {sorties.html.resolve()}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from controldone.services.plateforme import Plateforme
    from controldone.web import ParametresWeb, create_app

    plateforme = Plateforme.depuis_env()
    if args.init_schema:
        plateforme.db.creer_schema()
    app = create_app(ParametresWeb(plateforme=plateforme, worker_integre=not args.sans_worker,
                                   https=True if args.https else None))
    print(f"ControlDOne — http://{args.host}:{args.port}/ (worker intégré : {'non' if args.sans_worker else 'oui'})")
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=args.proxy, forwarded_allow_ips="127.0.0.1",
                log_level="warning", server_header=False)
    return 0


def _init_demo(args: argparse.Namespace) -> int:
    import shutil

    from controldone.services.demo_init import initialiser_demo, resume
    from controldone.services.plateforme import Plateforme

    plateforme = Plateforme.depuis_env()
    if args.force:
        chemin = plateforme.db.chemin_sqlite()
        if chemin is None:
            print("--force n'est possible qu'avec une base SQLite.", file=sys.stderr)
            return 2
        plateforme.db.fermer()
        for suffixe in ("", "-wal", "-shm"):
            Path(str(chemin) + suffixe).unlink(missing_ok=True)
        shutil.rmtree(plateforme.vault.racine, ignore_errors=True)
        plateforme = Plateforme.depuis_env()
    res = initialiser_demo(plateforme)
    if res.deja_initialisee and args.si_absente:
        print("Base de démonstration déjà initialisée.")
        return 0
    print("\n".join(resume(res)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="controldone", description="ControlDOne — contrôle technique de cohérence "
                                 "des documents d'import.")
    ap.add_argument("-v", "--verbeux", action="store_true")
    sous = ap.add_subparsers(dest="commande", required=True)

    d = sous.add_parser("diagnostic", help="diagnostic d'un dossier ou d'un lot de fichiers")
    d.add_argument("source", help="dossier (arborescence conservée) ou fichier")
    d.add_argument("--client-profile", dest="client_profile", default=None, help="profil client (JSON)")
    d.add_argument("--grilles", default=None, help="dossier des grilles tarifaires validées (JSON)")
    d.add_argument("--out", required=True, help="dossier de sortie")
    d.add_argument("--seed", type=int, default=None, help="identifiants reproductibles")
    d.add_argument("--sans-llm", dest="sans_llm", action="store_true", help="ne jamais appeler le modèle")
    d.set_defaults(fn=_diagnostic)

    m = sous.add_parser("demo", help="démonstration sur un jeu fictif")
    m.add_argument("--out", default="var/demo")
    m.add_argument("--demo-dir", dest="demo_dir", default="demo", help="où écrire le jeu fictif")
    m.add_argument("--moteur", choices=["auto", "reel", "demo"], default="auto")
    m.set_defaults(fn=_demo)

    sv = sous.add_parser("serve", help="interface web et API (uvicorn)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--sans-worker", dest="sans_worker", action="store_true",
                    help="ne pas lancer le worker intégré (production : python -m controldone.jobs.worker)")
    sv.add_argument("--init-schema", dest="init_schema", action="store_true", help="créer les tables manquantes")
    sv.add_argument("--https", action="store_true", help="servi derrière TLS : en-tête HSTS")
    sv.add_argument("--proxy", action="store_true", help="faire confiance aux en-têtes X-Forwarded-* du mandataire local")
    sv.set_defaults(fn=_serve)

    di = sous.add_parser("init-demo", help="base de démonstration (données fictives, deux clients)")
    di.add_argument("--force", action="store_true", help="supprimer la base SQLite et le coffre existants")
    di.add_argument("--si-absente", dest="si_absente", action="store_true", help="ne rien faire si déjà initialisée")
    di.set_defaults(fn=_init_demo)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbeux else logging.ERROR, format="%(levelname)s %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
