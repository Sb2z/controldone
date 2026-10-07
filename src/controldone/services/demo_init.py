"""Base de démonstration (``controldone init-demo``) : **données fictives** uniquement.

- compte fondateur : mot de passe et secret TOTP générés, affichés **une fois** (stockés haché / chiffré) ;
- deux clients fictifs (``DONNÉES FICTIVES``), leurs utilisateurs, entités, transitaires et grilles validées ;
- les dossiers de démonstration (``controldone.demo``) déposés par le chemin réel (service de dépôt, coffre
  chiffré, job ``traiter_lot``, worker) : le tableau de bord est peuplé par le vrai pipeline ;
- quelques décisions du fondateur pour illustrer la publication (constats validés, rapport publié, dossier de
  réclamation en attente d'approbation, réclamation déclarée envoyée par le client).
"""

from __future__ import annotations

import contextlib
import json
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from controldone.auth.motdepasse import hacher_mot_de_passe
from controldone.auth.roles import Acteur, Role
from controldone.auth.totp import generer_secret, uri_provisioning
from controldone.services import admin, depot, publication, reclamations, validation
from controldone.services.lecture import constats_courants
from controldone.services.plateforme import Plateforme, RequeteInvalide
from controldone.storage.cles import chiffrer_secret
from controldone.storage.comptes import creer_utilisateur, enregistrer_totp, utilisateur_par_email
from controldone.storage.models import Constat, Ecart

__all__ = ["CompteDemo", "ResultatDemo", "initialiser_demo"]

EMAIL_FONDATEUR = "fondateur@controldone-demo.test"


@dataclass
class CompteDemo:
    email: str
    mot_de_passe: str
    role: str
    client: str | None = None


@dataclass
class ResultatDemo:
    fondateur: CompteDemo
    totp_secret: str
    totp_uri: str
    comptes: list[CompteDemo] = field(default_factory=list)
    clients: list[str] = field(default_factory=list)
    jobs: int = 0
    deja_initialisee: bool = False


CLIENTS = [
    {
        "id": "demo_ateliers",
        "raison_sociale": "ATELIERS DÉMO FICTIF SAS",
        "offre": "diagnostic",
        "transitaire_id": "TR-DEMO",
        "grille": "GRL-DEMO-2026",
        "dossiers": ["DEMO-1", "DEMO-2", "DEMO-3"],
        "comptes": [
            ("admin@ateliers-demo.test", "client_admin"),
            ("lecture@ateliers-demo.test", "client_lecteur"),
        ],
    },
    {
        "id": "demo_nord",
        "raison_sociale": "ATELIERS DÉMO FICTIF — SITE NORD",
        "offre": "continu",
        "transitaire_id": "TR-DEMO-NORD",
        "grille": "GRL-DEMO-2026-NORD",
        "dossiers": ["DEMO-2", "DEMO-3"],
        "comptes": [("admin@site-nord-demo.test", "client_admin")],
    },
]


def _executer_jobs(plateforme: Plateforme, maximum: int = 50) -> int:
    import controldone.jobs.handlers  # noqa: F401  (handlers intégrés + recontrôle)
    from controldone.jobs.worker import Worker

    w = Worker(plateforme.db, worker_id="init-demo", lease_s=300, services={"vault": plateforme.vault})
    n = 0
    while n < maximum and w.executer_un() is not None:
        n += 1
    return n


def initialiser_demo(
    plateforme: Plateforme, *, mot_de_passe_fondateur: str | None = None, decisions: bool = True
) -> ResultatDemo:
    from controldone.demo.donnees import grille_demo, profil_demo
    from controldone.demo.generateur import generer_demo

    db = plateforme.db
    db.creer_schema()
    if utilisateur_par_email(db, EMAIL_FONDATEUR) is not None:
        return ResultatDemo(
            fondateur=CompteDemo(EMAIL_FONDATEUR, "", "fondateur"),
            totp_secret="",
            totp_uri="",
            deja_initialisee=True,
        )
    # --- fondateur ---
    mdp_f = mot_de_passe_fondateur or secrets.token_urlsafe(15)
    uid = "usr_fondateur_demo"
    fondateur = Acteur(uid, Role.fondateur)
    creer_utilisateur(
        db,
        user_id=uid,
        email=EMAIL_FONDATEUR,
        mot_de_passe_hash=hacher_mot_de_passe(mdp_f),
        role=Role.fondateur,
        acteur=fondateur,
        nom="Fondateur (démonstration)",
    )
    secret = generer_secret()
    enregistrer_totp(db, uid, chiffrer_secret(plateforme.cles_maitresses, secret), acteur=fondateur)
    res = ResultatDemo(
        fondateur=CompteDemo(EMAIL_FONDATEUR, mdp_f, "fondateur"),
        totp_secret=secret,
        totp_uri=uri_provisioning(secret, EMAIL_FONDATEUR, "ControlDOne démo"),
    )

    profil = profil_demo()
    with tempfile.TemporaryDirectory(prefix="cd-demo-") as tmp:
        racine = generer_demo(Path(tmp) / "demo")
        for c in CLIENTS:
            tid = admin.creer_client(
                plateforme, fondateur, c["raison_sociale"], offre=c["offre"], demo=True, tenant_id=c["id"]
            )
            res.clients.append(tid)
            admin_client = None
            for email, role in c["comptes"]:
                mdp = secrets.token_urlsafe(12)
                admin.creer_utilisateur_client(plateforme, fondateur, tid, email, role, mot_de_passe=mdp)
                res.comptes.append(CompteDemo(email, mdp, role, c["raison_sociale"]))
                if role == "client_admin" and admin_client is None:
                    admin_client = email
            with db.operateur(fondateur) as op:
                scope = op.client(tid, "initialisation de la démonstration")
                for e in profil["entites"]:
                    admin.ajouter_entite(
                        scope,
                        e["raison_sociale"],
                        tva=e.get("tva"),
                        siren=e.get("siren"),
                        eori=e.get("eori"),
                        alias=";".join(e.get("alias") or []),
                    )
                for t in profil["transitaires"]:
                    admin.ajouter_transitaire(
                        scope,
                        t["nom"],
                        tva=t.get("tva"),
                        alias=";".join(t.get("alias") or []),
                        contact="service.litiges@transit-demo.test (FICTIF)",
                        transitaire_id=c["transitaire_id"],
                    )
                g = {**grille_demo(), "grille_id": c["grille"]}
                ligne = admin.importer_grille(
                    scope,
                    json.dumps(g).encode(),
                    "grille.json",
                    transitaire_id=c["transitaire_id"],
                    reference=g["reference"],
                )
                scope.valider_grille(ligne.grille_id, ligne.version)
            # dépôt par le compte administrateur du client (chemin réel : coffre + lot + job)
            compte = utilisateur_par_email(db, admin_client)
            acteur = Acteur(compte.id, Role.client_admin, tid)
            fichiers = []
            for nom in c["dossiers"]:
                for f in sorted((racine / "dossiers" / nom / "docs").iterdir()):
                    contenu = f.read_bytes()
                    fichiers.append(
                        depot.FichierTransmis(nom=f"{nom}/{f.name}", contenu=contenu, taille=len(contenu))
                    )
            depot.deposer(plateforme, acteur, fichiers)
    res.jobs = _executer_jobs(plateforme)
    if decisions:
        _decisions(plateforme, fondateur, res)
    from controldone.prospection.demo import semer_demo

    semer_demo(db, fondateur)  # module « Marketing » : sociétés FICTIVES, aucun courriel préparé (D-5001)
    return res


def _decisions(plateforme: Plateforme, fondateur: Acteur, res: ResultatDemo) -> None:
    """Illustration : client 1 — écarts certains validés, rapport publié, relevé d'écarts à approuver,
    une réclamation déclarée envoyée ; client 2 — tout reste à valider (file de validation)."""
    tid = "demo_ateliers"
    with plateforme.db.operateur(fondateur) as op:
        scope = op.client(tid, "démonstration : validation des constats")
        for c in constats_courants(scope):
            if c.statut_validation == "propose" and c.niveau == "ecart_certain":
                validation.valider(scope, c.id, "Valeurs vérifiées sur les pièces (démonstration).")
    try:
        r = publication.publier_rapport(plateforme, fondateur, tid)
        from controldone.outbox import FileSortante

        FileSortante(plateforme.db).approuver(r.action_id, fondateur)
        publication.mettre_a_disposition(plateforme, r.action_id, fondateur)
    except RequeteInvalide:  # aucun dossier à publier : la démonstration reste utilisable
        pass
    with contextlib.suppress(RequeteInvalide):  # aucun écart certain validé ouvert
        reclamations.preparer_dossier(plateforme, fondateur, tid, "TR-DEMO")
    compte = next(
        (x for x in res.comptes if x.client == "ATELIERS DÉMO FICTIF SAS" and x.role == "client_admin"), None
    )
    if compte is None:
        return
    u = utilisateur_par_email(plateforme.db, compte.email)
    acteur = Acteur(u.id, Role.client_admin, tid)
    with plateforme.db.tenant(tid, acteur) as scope:
        ecarts = [e for e in scope.lister(Ecart) if e.statut == "ouvert"]
        visibles = {c.id for c in scope.lister(Constat)}
        for e in ecarts[:1]:
            if e.constat_id in visibles:
                reclamations.declarer_envoi(
                    scope, e.id, "Envoyée par courriel au service litiges (démonstration)."
                )


def resume(res: ResultatDemo) -> list[str]:
    lignes = ["Base de démonstration ControlDOne — DONNÉES FICTIVES", ""]
    if res.deja_initialisee:
        return [*lignes, "Déjà initialisée : rien à faire (utiliser --force pour la recréer)."]
    lignes += [
        "Compte fondateur (affiché une seule fois ; seule une empreinte est conservée) :",
        f"  adresse      : {res.fondateur.email}",
        f"  mot de passe : {res.fondateur.mot_de_passe}",
        f"  secret TOTP  : {res.totp_secret}",
        f"  URI TOTP     : {res.totp_uri}",
        "  (code courant : python -c \"from controldone.auth import code_totp; print(code_totp('<secret>'))\")",
        "",
        "Comptes client (fictifs) :",
    ]
    for c in res.comptes:
        lignes.append(f"  {c.email:32s} {c.mot_de_passe:20s} {c.role:15s} {c.client}")
    lignes += ["", f"Clients : {', '.join(res.clients)} — {res.jobs} tâche(s) exécutée(s)."]
    return lignes
