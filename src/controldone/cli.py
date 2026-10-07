"""Ligne de commande ``controldone``.

    controldone diagnostic <dossier_ou_fichier> [--client-profile p.json] [--grilles dir] --out <dir>
    controldone demo [--out var/demo] [--demo-dir demo] [--moteur auto|reel|demo]
    controldone serve [--host 127.0.0.1] [--port 8000] [--sans-worker] [--init-schema]
    controldone init-demo [--force] [--si-absente]
    controldone creer-fondateur --email <adresse> [--nom "…"] [--mot-de-passe-stdin]
    controldone debit lister | effacer (--email E | --ip A | --cle-api P | --tout) [--motif "…"]
    controldone reinitialiser-mot-de-passe --email <adresse> [--mot-de-passe-stdin]
    controldone sauvegarde sauvegarder|verifier|restaurer|controler|rotation|alerter|exercice|exercice-mensuel …
    controldone migrer [--etat] [--sans-sauvegarde]
    controldone alertes notifier | essai | etat | historique [--limite N]
    controldone prospection importer <fichier.csv> [--essai] | etapes | etat | purger [--oui]

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

from controldone.config import env

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
    print(
        f"{len(resultats)} dossier(s) — recouvrable certain {v.recouvrable_certain} ; "
        f"à vérifier {v.recouvrable_a_verifier} ; points professionnels {v.nb_renvois} ; "
        f"non lus {len(v.non_lus)}"
    )
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

    from controldone.config import get_settings
    from controldone.services.plateforme import Plateforme
    from controldone.web import ParametresWeb, create_app
    from controldone.web.securite import ModeIncoherent, verifier_mode_service

    try:  # mode dev oublié en production (RS-16, D-3601)
        verifier_mode_service(hote=args.host, https=args.https, proxy=args.proxy)
    except ModeIncoherent as exc:
        print(f"ControlDOne : démarrage refusé — {exc}", file=sys.stderr)
        return 2
    # Téléversements multipart (Starlette) et fichiers temporaires sur le volume de données, pas sur un
    # tmpfs /tmp en mémoire (D-1305) : ``CONTROLDONE_TMP_DIR``, défaut ``<data_dir>/tmp``.
    get_settings().appliquer_repertoire_temporaire()
    plateforme = Plateforme.depuis_env()
    if args.init_schema:  # tables d'une base neuve ; migrations d'une base existante : ci-dessous (D-3503)
        plateforme.db.creer_schema(migrer=False)
    from controldone.storage import SchemaPerime

    try:  # colonnes ajoutées par une version plus récente sans migration : arrêt explicite (D-1322) ; migration
        # en attente en production : attente du service « migrer », puis arrêt unique (D-4102)
        plateforme.db.attendre_schema_a_jour(
            journal=lambda m: print(f"ControlDOne : {m}", file=sys.stderr, flush=True)
        )
    except SchemaPerime as exc:
        print(f"ControlDOne : {exc}", file=sys.stderr)
        return 3
    from controldone.storage.securite import signaler_volume_non_chiffre

    signaler_volume_non_chiffre(plateforme.db)  # RS-21, D-3605 : alerte en production seulement
    app = create_app(
        ParametresWeb(
            plateforme=plateforme, worker_integre=not args.sans_worker, https=True if args.https else None
        )
    )
    print(
        f"ControlDOne — http://{args.host}:{args.port}/ (worker intégré : {'non' if args.sans_worker else 'oui'})"
    )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        proxy_headers=args.proxy,
        forwarded_allow_ips=args.forwarded_allow_ips,
        log_level="warning",
        server_header=False,
    )
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


def _creer_fondateur(args: argparse.Namespace) -> int:
    """Compte fondateur de production : mot de passe saisi (jamais en argument), secret TOTP affiché une fois."""
    import getpass
    import secrets as _secrets

    from controldone.auth.motdepasse import LONGUEUR_MIN, MotDePasseFaible, hacher_mot_de_passe
    from controldone.auth.roles import Acteur, Role
    from controldone.auth.totp import generer_secret, uri_provisioning
    from controldone.services.plateforme import Plateforme
    from controldone.storage.cles import chiffrer_secret
    from controldone.storage.comptes import creer_utilisateur, enregistrer_totp, utilisateur_par_email

    plateforme = Plateforme.depuis_env()
    db = plateforme.db
    db.creer_schema()
    if utilisateur_par_email(db, args.email) is not None:
        print(f"Un compte existe déjà pour {args.email} : rien n'est modifié.", file=sys.stderr)
        return 1
    if args.mot_de_passe_stdin:
        mdp = sys.stdin.readline().rstrip("\n")
    else:
        mdp = getpass.getpass(f"Mot de passe du fondateur ({LONGUEUR_MIN} caractères minimum) : ")
        if getpass.getpass("Confirmation : ") != mdp:
            print("Les deux saisies diffèrent.", file=sys.stderr)
            return 2
    try:
        empreinte = hacher_mot_de_passe(mdp)
    except MotDePasseFaible as exc:
        print(f"Mot de passe refusé : {exc}.", file=sys.stderr)
        return 2
    uid = f"usr_{_secrets.token_hex(8)}"
    fondateur = Acteur(uid, Role.fondateur)
    creer_utilisateur(
        db,
        user_id=uid,
        email=args.email,
        mot_de_passe_hash=empreinte,
        role=Role.fondateur,
        acteur=fondateur,
        nom=args.nom,
    )
    secret = generer_secret()
    enregistrer_totp(db, uid, chiffrer_secret(plateforme.cles_maitresses, secret), acteur=fondateur)
    print("Compte fondateur créé.")
    print(f"  adresse     : {args.email}")
    print(f"  secret TOTP : {secret}   (affiché une seule fois ; stocké chiffré)")
    print(f"  URI TOTP    : {uri_provisioning(secret, args.email)}")
    print("Ajouter le secret dans l'application d'authentification, puis se connecter sur /admin.")
    return 0


def _sauvegarde(args: argparse.Namespace) -> int:
    """Délègue à ``controldone.storage.sauvegarde`` (``exercice`` : ``services.exercice_restauration`` ;
    ``exercice-mensuel`` : ``services.exercice_mensuel``)."""
    reste = list(args.arguments)
    if reste[:1] == ["exercice-mensuel"]:  # dernière vraie archive (D-4702)
        from controldone.services.exercice_mensuel import main as exercice_mensuel

        return exercice_mensuel(reste[1:])
    if reste[:1] == ["exercice"]:
        from controldone.services.exercice_restauration import main as exercice

        return exercice(reste[1:])
    from controldone.storage.sauvegarde import main as sauvegarde

    return sauvegarde(reste)


def _migrer(args: argparse.Namespace) -> int:
    """Migrations de schéma (D-3503) : sauvegarde d'abord (par défaut), puis étapes en attente."""
    from controldone.storage.db import Database

    db = Database()
    try:
        attente = db.migrations_en_attente()
        neuve = _base_neuve(db)
        print(f"base : {db.engine.url.render_as_string(hide_password=True)}")
        print(
            "migrations en attente : " + (", ".join(f"{m.version:04d} {m.nom}" for m in attente) or "aucune")
        )
        traces = _traces_en_clair()
        if traces:
            print(f"traces d'envoi en clair à chiffrer : {traces}")
        if args.etat:
            return 0
        if not attente and not neuve:
            return _chiffrer_traces()
        if attente and not neuve and not args.sans_sauvegarde:
            from controldone.storage.sauvegarde import main as sauvegarde

            print("sauvegarde avant migration…", flush=True)
            destination = env("BACKUP_DIR")  # conteneur scheduler : /backups ; sinon <data_dir>/sauvegardes
            code = sauvegarde(
                ["sauvegarder", "--sans-rotation", *(["--destination", destination] if destination else [])]
            )
            if code != 0:
                print(
                    f"sauvegarde en échec (code {code}) : migration abandonnée (--sans-sauvegarde pour passer "
                    "outre, après une sauvegarde faite autrement)",
                    file=sys.stderr,
                )
                return 1
        db.creer_schema(migrer=False)  # tables manquantes ; base neuve : migrations inscrites
        db.migrer(journal=print)
        manquantes = db.colonnes_manquantes()
        if manquantes:
            print("colonnes encore manquantes : " + ", ".join(manquantes[:20]), file=sys.stderr)
            return 3
        print("schéma à jour.")
        return _chiffrer_traces()
    finally:
        db.fermer()


def _traces_en_clair() -> int:
    from controldone.storage.traces_envoi import racine_par_defaut

    racine = racine_par_defaut()
    if not racine.is_dir():
        return 0
    return sum(
        1 for p in racine.glob("*/*") if p.is_file() and not p.name.startswith(".") and p.suffix != ".enc"
    )


def _chiffrer_traces() -> int:
    """Étape de données de ``migrer`` (D-4106) : traces d'envoi écrites en clair avant cette version -> chiffrées.
    Idempotent ; rien à faire (et aucune clé lue) s'il n'en reste pas."""
    if not _traces_en_clair():
        return 0
    from controldone.storage.traces_envoi import chiffrer_en_clair

    try:
        n = chiffrer_en_clair()
    except Exception as exc:
        print(f"chiffrement des traces d'envoi en échec : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"traces d'envoi chiffrées : {n}")
    return 0


def _base_neuve(db: object) -> bool:
    from controldone.storage.migrations import base_neuve

    return base_neuve(db.engine)  # type: ignore[attr-defined]


def _alertes(args: argparse.Namespace) -> int:
    """Notifications poussées des alertes (D-3502) : rien ne part hors production ni sans configuration."""
    from controldone.services.notifications import ConfigNotifications, envoyer_essai, notifier_alertes

    config = ConfigNotifications.depuis_env()
    for e in config.erreurs:
        print(f"configuration ignorée — {e}", file=sys.stderr)
    if args.action == "etat":
        print("notifications : " + ("actives" if config.actif else f"inactives ({config.motif_inactif()})"))
        for c in config.canaux:
            print(f"  canal : {c.nom}")  # jamais l'URL ni le mot de passe
        return 0
    from controldone.storage.db import Database

    if args.action == "essai":  # lancé par le fondateur seulement (jamais par le planificateur)
        if not config.actif:
            print(f"notifications inactives : {config.motif_inactif()}", file=sys.stderr)
            return 2
        try:
            db_essai: Database | None = Database()
        except Exception:  # base injoignable : l'essai part quand même, sans inscription
            db_essai = None
        try:
            reussis, rates = envoyer_essai(config, db=db_essai)
        finally:
            if db_essai is not None:
                db_essai.fermer()
        print(f"essai envoyé : {', '.join(reussis) or 'aucun'} ; en échec : {', '.join(rates) or 'aucun'}")
        return 0 if not rates else 1
    db = Database()
    if args.action == "historique":
        from controldone.services.notifications import historique

        try:
            h = historique(db, limite=args.limite, config=config)
        finally:
            db.fermer()
        print("notifications : " + ("actives" if h.actif else f"inactives ({h.motif_inactif})"))

        def dernier(d: object) -> str:
            return d.strftime("%Y-%m-%d %H:%M") if d else "jamais"  # type: ignore[attr-defined]

        for etat in h.canaux.values():
            print(
                f"  canal {etat.canal:9s} : {'EN ÉCHEC' if etat.en_echec else 'ok'} — dernier succès "
                f"{dernier(etat.dernier_succes)}, dernier échec {dernier(etat.dernier_echec)}"
            )
        for n in h.notifications:
            canaux = ", ".join(f"{c} {r}" for c, r in n.canaux.items()) or "-"
            print(
                f"  {n.jour}  {h.libelle(n.kind):32s} ({n.nombre})  {n.statut:8s} essais {n.essais}  [{canaux}]"
            )
        if not h.notifications:
            print("  (aucune notification sur 30 jours)")
        return 0
    try:
        rapport = notifier_alertes(db, config)
    finally:
        db.fermer()
    print("\n".join(rapport.lignes()))
    return 1 if rapport.echecs else 0


def _llm(args: argparse.Namespace) -> int:
    """État de la lecture par modèle de langage (D-4006). ``verifier`` : clé présente ? puis **un** appel minimal
    (quelques jetons, < 0,01 EUR) seulement si la clé est présente et sans ``--sans-appel``. ``couts`` : coût du
    mois et plafond de chaque client (fondateur). La clé n'est jamais affichée."""
    from controldone.config import get_settings
    from controldone.extract.llm import verifier_cle

    s = get_settings()
    if args.action == "verifier":
        etat = verifier_cle(s, appel=not args.sans_appel)
        print(
            f"clé Anthropic : {'présente' if etat['cle_presente'] else 'absente'}"
            + (
                ""
                if etat["cle_presente"]
                else " (ANTHROPIC_API_KEY ou CONTROLDONE_ANTHROPIC_API_KEY dans .env) "
                "— extraction 100 % déterministe"
            )
        )
        print(
            f"modèle : {etat['modele']} ; effort : {etat['effort']} ; tarifs du {etat['date_tarifs']}"
            + (
                ""
                if etat["tarif_connu"]
                else " (modèle absent de config/llm_tarifs.yaml : tarif le plus élevé)"
            )
        )
        appel = etat["appel"]
        if appel is None:
            print("appel de test : non effectué")
            return 0 if etat["cle_presente"] or args.sans_appel else 1
        if not appel["ok"]:
            print(
                f"appel de test : ÉCHEC ({appel.get('erreur') or appel.get('stop_reason')}"
                + (f", HTTP {appel['statut']}" if appel.get("statut") else "")
                + ")"
            )
            return 1
        print(
            f"appel de test : OK — modèle servi {appel['modele_servi']}, {appel['jetons_entree']} + "
            f"{appel['jetons_sortie']} jetons, {appel['cout_eur']} EUR, {appel['duree_s']} s"
        )
        return 0
    from controldone.auth.roles import Acteur, Role
    from controldone.jobs.couts import etat_plafond, mois_courant
    from controldone.storage.db import Database

    db = Database()
    try:
        with db.operateur(Acteur("cli:llm_couts", Role.fondateur)) as op:  # lecture transversale journalisée
            clients = op.lister_clients()
        print(f"mois {mois_courant()} — clé {'présente' if s.llm_disponible else 'absente'}")
        for t in clients:
            e = etat_plafond(t.id, db=db)
            etat = (
                "désactivé (client)"
                if e.desactive
                else ("ARRÊT 100 %" if e.arret else ("alerte 80 %" if e.alerte else "actif"))
            )
            print(f"  {t.id} : {e.cout} / {e.plafond} EUR — {etat}")
    finally:
        db.fermer()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="controldone",
        description="ControlDOne — contrôle technique de cohérence des documents d'import.",
    )
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
    sv.add_argument(
        "--sans-worker",
        dest="sans_worker",
        action="store_true",
        help="ne pas lancer le worker intégré (production : python -m controldone.jobs.worker)",
    )
    sv.add_argument(
        "--init-schema", dest="init_schema", action="store_true", help="créer les tables manquantes"
    )
    sv.add_argument("--https", action="store_true", help="servi derrière TLS : en-tête HSTS")
    sv.add_argument(
        "--proxy", action="store_true", help="faire confiance aux en-têtes X-Forwarded-* du mandataire local"
    )
    sv.add_argument(
        "--forwarded-allow-ips",
        dest="forwarded_allow_ips",
        default=env("CONTROLDONE_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        help="adresses du mandataire dont les en-têtes X-Forwarded-* sont crus (avec --proxy)",
    )
    sv.set_defaults(fn=_serve)

    di = sous.add_parser("init-demo", help="base de démonstration (données fictives, deux clients)")
    di.add_argument("--force", action="store_true", help="supprimer la base SQLite et le coffre existants")
    di.add_argument(
        "--si-absente", dest="si_absente", action="store_true", help="ne rien faire si déjà initialisée"
    )
    di.set_defaults(fn=_init_demo)

    from controldone.auth.cli_securite import ajouter_commandes

    ajouter_commandes(sous)  # debit lister|effacer, reinitialiser-mot-de-passe (D-3201)

    from controldone.prospection.cli import ajouter_commandes as commandes_prospection

    commandes_prospection(sous)  # prospection importer|etapes|etat|purger (D-5009)

    cf = sous.add_parser("creer-fondateur", help="compte fondateur de production (mot de passe saisi + TOTP)")
    cf.add_argument("--email", required=True)
    cf.add_argument("--nom", default="Fondateur")
    cf.add_argument(
        "--mot-de-passe-stdin",
        dest="mot_de_passe_stdin",
        action="store_true",
        help="lire le mot de passe sur l'entrée standard (scripts) au lieu de le demander",
    )
    cf.set_defaults(fn=_creer_fondateur)

    sg = sous.add_parser(
        "sauvegarde",
        add_help=False,
        help="sauvegarder | verifier | restaurer | controler | rotation | alerter | exercice | exercice-mensuel",
    )
    sg.add_argument("arguments", nargs=argparse.REMAINDER)
    sg.set_defaults(fn=_sauvegarde)

    mg = sous.add_parser(
        "migrer",
        help="migrations de schéma (sauvegarde préalable par défaut) et chiffrement des "
        "traces d'envoi encore en clair",
    )
    mg.add_argument("--etat", action="store_true", help="afficher les migrations en attente sans rien faire")
    mg.add_argument(
        "--sans-sauvegarde",
        dest="sans_sauvegarde",
        action="store_true",
        help="ne pas sauvegarder avant (sauvegarde déjà faite autrement)",
    )
    mg.set_defaults(fn=_migrer)

    al = sous.add_parser(
        "alertes", help="notifications poussées des alertes : notifier | essai | etat | historique"
    )
    al.add_argument("action", choices=["notifier", "essai", "etat", "historique"])
    al.add_argument("--limite", type=int, default=30, help="historique : nombre de lignes (défaut 30)")
    al.set_defaults(fn=_alertes)

    ll = sous.add_parser(
        "llm", help="lecture par modèle de langage : verifier (clé + un appel minimal) | couts"
    )
    ll.add_argument("action", choices=["verifier", "couts"])
    ll.add_argument(
        "--sans-appel",
        dest="sans_appel",
        action="store_true",
        help="verifier : seulement la présence de la clé, aucun appel",
    )
    ll.set_defaults(fn=_llm)

    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbeux else logging.ERROR, format="%(levelname)s %(message)s"
    )
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
