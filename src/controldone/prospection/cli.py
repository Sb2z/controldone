"""Ligne de commande ``controldone prospection`` (fondateur, sur le serveur) :

    controldone prospection importer fichier.csv [--essai]   # analyse (doublons, exclusion) puis import
    controldone prospection etapes                           # brouillons des étapes de séquence échues
    controldone prospection etat                             # pipeline, plafonds du jour, prospects à purger
    controldone prospection purger [--oui]                   # purge des prospects au-delà de 3 ans

Rien n'est envoyé : les courriels restent des brouillons de la file de validation (``/admin/validation``)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

__all__ = ["ajouter_commandes"]

ACTEUR_CLI = "cli:fondateur"


def _service() -> Any:
    from controldone.prospection.service import ServiceProspection
    from controldone.storage.db import Database

    db = Database()
    db.exiger_schema_a_jour()
    return ServiceProspection(db)


def _acteur() -> Any:
    from controldone.auth.roles import Acteur, Role

    return Acteur(ACTEUR_CLI, Role.fondateur)


def _executer(args: argparse.Namespace) -> int:
    from controldone.prospection.service import RefusProspection
    from controldone.prospection.statuts import LIBELLES_STATUT

    svc = _service()
    f = _acteur()
    try:
        if args.action == "importer":
            if not args.fichier:
                print("fichier CSV attendu", file=sys.stderr)
                return 2
            chemin = Path(args.fichier)
            if not chemin.is_file():
                print(f"introuvable : {chemin}", file=sys.stderr)
                return 2
            contenu = chemin.read_bytes()
            lignes = svc.analyser_import(f, contenu)
            for x in lignes:
                motif = f" ({x.motif})" if x.motif else ""
                print(f"  ligne {x.numero:4d} {x.statut:9s}{motif} {x.raison_sociale}")
            if args.essai:
                print(
                    f"{sum(x.statut == 'nouveau' for x in lignes)} ligne(s) importable(s) ; rien n'est écrit (--essai)."
                )
                return 0
            r = svc.importer(f, contenu, chemin.name)
            print(
                f"{r.crees} prospect(s) créé(s), {r.contacts} contact(s) ; doublons {r.doublons}, "
                f"exclus {r.exclus}, invalides {r.invalides}."
            )
        elif args.action == "etapes":
            ids = svc.preparer_etapes_dues(f)
            print(f"{len(ids)} brouillon(s) préparé(s) : à approuver dans /admin/validation.")
        elif args.action == "etat":
            t = svc.tableau(f)
            for st, n in t["par_statut"]:
                print(f"  {LIBELLES_STATUT[st]:22s} {n}")
            c = t["compteurs"]
            print(
                f"aujourd'hui : {c['preparations']}/{c['plafond_preparations']} préparation(s), "
                f"{c['envois']}/{c['plafond_envois']} envoi(s) ; à purger : {t['a_purger']}"
            )
        elif args.action == "purger":
            n = len(svc.a_purger(f))
            if not args.oui:
                print(
                    f"{n} prospect(s) à purger (sans contact émanant d'eux depuis 3 ans). Relancer avec --oui."
                )
                return 0
            print(f"{svc.purger(f)} prospect(s) purgé(s) ; la liste d'opposition est conservée.")
    except RefusProspection as exc:
        print(f"refusé : {exc}", file=sys.stderr)
        return 1
    finally:
        svc.db.fermer()
    return 0


def ajouter_commandes(sous: Any) -> None:
    p = sous.add_parser("prospection", help="prospection du fondateur : importer | etapes | etat | purger")
    p.add_argument("action", choices=["importer", "etapes", "etat", "purger"])
    p.add_argument("fichier", nargs="?", default=None, help="importer : fichier CSV (format prospects.csv)")
    p.add_argument("--essai", action="store_true", help="importer : analyser sans rien écrire")
    p.add_argument("--oui", action="store_true", help="purger : confirmer la purge")
    p.set_defaults(fn=_executer)
