"""Commandes d'exploitation de la sécurité (``controldone debit …``, ``controldone reinitialiser-mot-de-passe``).

- ``controldone debit lister`` : seaux de limitation de débit en cours (portée, jetons restants, déblocage) ; les
  identifiants sont pseudonymisés en base, seule l'empreinte s'affiche.
- ``controldone debit effacer --email E | --ip A | --cle-api PREFIXE | --tout [--motif …]`` : débloque une
  connexion (ex. le fondateur bloqué après des essais). Journalisé dans le journal d'audit.
- ``controldone reinitialiser-mot-de-passe --email E [--mot-de-passe-stdin]`` : seul chemin de réinitialisation
  (il n'y a pas de « mot de passe oublié » par courriel : aucun jeton de réinitialisation à voler ni à deviner).
  Il faut un accès à la machine du service (base et clé maîtresse). Toutes les sessions du compte sont
  révoquées, ses compteurs de débit remis à zéro ; journalisé.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

__all__ = ["ajouter_commandes"]


def _plateforme() -> Any:
    from controldone.services.plateforme import Plateforme
    from controldone.storage.securite import assurer_tables_securite

    pf = Plateforme.depuis_env()
    assurer_tables_securite(pf.db)
    return pf


def _cles_compte(pf: Any, email: str) -> list[tuple[str, str]]:
    """(portée, identifiant) des seaux d'un compte : connexion par courriel, second facteur, changement de mot
    de passe."""
    from controldone.storage.comptes import utilisateur_par_email

    email = email.strip().lower()
    cles = [("connexion_compte", email)]
    compte = utilisateur_par_email(pf.db, email)
    if compte is not None:
        cles += [("connexion_compte", "2fa:" + compte.id), ("connexion_compte", "mdp:" + compte.id)]
    return cles


def _debit_lister(args: argparse.Namespace) -> int:
    from controldone.storage.securite import lister_debit

    pf = _plateforme()
    maintenant = time.time()
    lignes = lister_debit(pf.db, maintenant=maintenant, limite=args.limite)
    if not lignes:
        print("Aucun compteur de débit en cours.")
        return 0
    print(f"{'portée':18s} {'empreinte':16s} {'jetons':>7s}  plein dans")
    for x in lignes:
        portee, _, empreinte = x.cle.partition(":")
        etat = "BLOQUÉ" if x.jetons < 1 else ""
        print(f"{portee:18s} {empreinte[:16]:16s} {x.jetons:7.2f}  {max(0, int(x.expire - maintenant))} s {etat}")
    return 0


def _debit_effacer(args: argparse.Namespace) -> int:
    from controldone.auth.debit import cle_debit, sel_debit
    from controldone.storage.securite import effacer_debit

    pf = _plateforme()
    sel = sel_debit(pf.cles_maitresses)
    cibles: list[tuple[str, str]] = []
    if args.email:
        cibles += _cles_compte(pf, args.email)
    if args.ip:
        cibles += [("connexion_ip", args.ip), ("api", "ip:" + args.ip)]
    if args.cle_api:
        cibles += [("api", "api:" + args.cle_api)]
    if not cibles and not args.tout:
        print("Préciser --email, --ip, --cle-api ou --tout.", file=sys.stderr)
        return 2
    acteur = "cli:debit"
    if args.tout:
        n = effacer_debit(pf.db, tout=True, cles=None, portee=None, acteur=acteur, motif=args.motif) if False else 0
        from controldone.storage.securite import effacer_tout_debit

        n = effacer_tout_debit(pf.db, acteur=acteur, motif=args.motif)
    else:
        n = effacer_debit(pf.db, cles=[cle_debit(p, i, sel) for p, i in cibles], acteur=acteur, motif=args.motif)
    print(f"{n} compteur(s) effacé(s). Les connexions concernées sont débloquées.")
    return 0


def _reinitialiser(args: argparse.Namespace) -> int:
    import getpass

    from controldone.auth.debit import cle_debit, sel_debit
    from controldone.auth.jetons import GestionnaireSessions
    from controldone.auth.motdepasse import LONGUEUR_MIN, MotDePasseFaible, hacher_mot_de_passe
    from controldone.auth.roles import Acteur, Role
    from controldone.storage.comptes import changer_mot_de_passe, utilisateur_par_email
    from controldone.storage.securite import effacer_debit, revoquer_sessions_utilisateur

    pf = _plateforme()
    compte = utilisateur_par_email(pf.db, args.email)
    if compte is None:
        print(f"Aucun compte pour {args.email}.", file=sys.stderr)
        return 1
    if args.mot_de_passe_stdin:
        mdp = sys.stdin.readline().rstrip("\n")
    else:
        mdp = getpass.getpass(f"Nouveau mot de passe ({LONGUEUR_MIN} caractères minimum) : ")
        if getpass.getpass("Confirmation : ") != mdp:
            print("Les deux saisies diffèrent.", file=sys.stderr)
            return 2
    try:
        empreinte = hacher_mot_de_passe(mdp)
    except MotDePasseFaible as exc:
        print(f"Mot de passe refusé : {exc}.", file=sys.stderr)
        return 2
    changer_mot_de_passe(pf.db, compte.id, empreinte, acteur=Acteur("cli:reinitialisation", Role.fondateur))
    maintenant = time.time()
    duree = GestionnaireSessions.DUREE_ABSOLUE_PAR_DEFAUT
    revoquer_sessions_utilisateur(pf.db, compte.id, apres=maintenant, expire=maintenant + duree + 60)
    sel = sel_debit(pf.cles_maitresses)
    effacer_debit(pf.db, cles=[cle_debit(p, i, sel) for p, i in _cles_compte(pf, args.email)],
                  acteur="cli:reinitialisation", motif="reinitialisation du mot de passe")
    print("Mot de passe remplacé ; toutes les sessions du compte sont fermées.")
    return 0


def ajouter_commandes(sous: Any) -> None:
    """Ajoute les sous-commandes au ``argparse`` de ``controldone.cli``."""
    d = sous.add_parser("debit", help="limitation de débit : lister ou débloquer (D-3201)")
    ds = d.add_subparsers(dest="action_debit", required=True)
    dl = ds.add_parser("lister", help="compteurs en cours (identifiants pseudonymisés)")
    dl.add_argument("--limite", type=int, default=200)
    dl.set_defaults(fn=_debit_lister)
    de = ds.add_parser("effacer", help="débloquer : remettre des compteurs à zéro")
    de.add_argument("--email", default=None, help="compte (connexion, second facteur, changement de mot de passe)")
    de.add_argument("--ip", default=None, help="adresse IP (connexion et API)")
    de.add_argument("--cle-api", dest="cle_api", default=None, help="préfixe public d'une clé d'API")
    de.add_argument("--tout", action="store_true", help="tous les compteurs")
    de.add_argument("--motif", default="", help="motif inscrit au journal d'audit")
    de.set_defaults(fn=_debit_effacer)

    r = sous.add_parser("reinitialiser-mot-de-passe",
                        help="nouveau mot de passe d'un compte (saisi), sessions révoquées")
    r.add_argument("--email", required=True)
    r.add_argument("--mot-de-passe-stdin", dest="mot_de_passe_stdin", action="store_true",
                   help="lire le mot de passe sur l'entrée standard (scripts)")
    r.set_defaults(fn=_reinitialiser)
