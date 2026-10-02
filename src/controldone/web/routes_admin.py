"""Pages du fondateur (``/admin``). Second facteur obligatoire (jeton de session « deux facteurs ») ;
chaque ouverture d'un client passe par ``OperatorScope.client`` (journal d'audit avec motif)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import Response

from controldone.auth.roles import Acteur, Role
from controldone.outbox import ActionBloquee, FileSortante, ModeAutonomie, TransitionInterdite, TypeAction
from controldone.services import admin as svc_admin
from controldone.services import publication, reclamations, validation
from controldone.services.lecture import (
    LIBELLES_LOT,
    client_info,
    constats_courants,
    detail_dossier,
    documents_du_dossier,
    libelle_document,
    trier_constats,
    vue_constat,
)
from controldone.services.plateforme import Plateforme, RequeteInvalide
from controldone.services.saisie import montant_saisi
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import Document, Dossier, Fichier
from controldone.web.rendu import page, redirection, retour_sur
from controldone.web.reponses import fichier_attache, png
from controldone.web.securite import acteur_de, depuis_boucle, formulaire_sync
from controldone.web.vues import image_page, images_dossier, images_preuves

routeur = APIRouter(prefix="/admin")

LIBELLES_SORTIE = {
    "email_client": "Courriel au client", "rapport_publication": "Publication d'un rapport",
    "reclamation_dossier": "Relevé d'écarts (mise à disposition du client)", "relance": "Rappel au client",
    "facture_emise": "Facture émise", "post_linkedin": "Publication LinkedIn",
    "email_prospection": "Courriel de prospection", "statut_litige_pa": "Statut de litige",
}


def _fondateur(request: Request) -> Acteur:
    acteur = acteur_de(request)
    if acteur.role is not Role.fondateur:
        raise AccesRefuse("introuvable ou hors périmètre")
    return acteur


def _pf(request: Request) -> Plateforme:
    return request.app.state.plateforme


def _s(form: Any, cle: str, n: int = 500) -> str:
    v = form.get(cle)
    return v.strip()[:n] if isinstance(v, str) else ""


# --- tableau de bord --------------------------------------------------------------------------------------


@routeur.get("")
def tableau(request: Request) -> Response:
    f = _fondateur(request)
    donnees = svc_admin.tableau_de_bord(_pf(request), f)
    return page(request, "admin/tableau.html.j2", titre="Tableau de bord", nav="tableau", d=donnees,
                demo=any(c.demo for c in donnees["clients"]))


# --- clients ------------------------------------------------------------------------------------------------


@routeur.get("/clients")
def clients(request: Request) -> Response:
    f = _fondateur(request)
    donnees = svc_admin.tableau_de_bord(_pf(request), f)
    return page(request, "admin/clients.html.j2", titre="Clients", nav="clients", d=donnees)


@routeur.post("/clients")
def creer_client(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        tid = svc_admin.creer_client(_pf(request), f, _s(form, "raison_sociale", 300), offre=_s(form, "offre", 20),
                                     plafond=_s(form, "plafond", 20) or None, demo=form.get("demo") == "1")
    except RequeteInvalide as exc:
        return redirection(request, "/admin/clients", erreur=str(exc))
    return redirection(request, f"/admin/clients/{tid}", message="Client créé.")


def _fiche(request: Request, f: Acteur, tenant_id: str, **extra: Any) -> Response:
    pf = _pf(request)
    d = svc_admin.fiche_client(pf, f, tenant_id)
    sorties = FileSortante(pf.db).lister(f, tenant_id=tenant_id)
    return page(request, "admin/client.html.j2", titre=d["info"]["raison_sociale"], nav="clients", c=d,
                sorties=list(reversed(sorties))[:30], libelles_sortie=LIBELLES_SORTIE, libelles_lot=LIBELLES_LOT,
                demo=d["info"]["demo"], **extra)


@routeur.get("/clients/{tenant_id}")
def fiche_client(request: Request, tenant_id: str) -> Response:
    return _fiche(request, _fondateur(request), tenant_id)


@routeur.post("/clients/{tenant_id}/utilisateurs")
def ajouter_utilisateur(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        mdp = svc_admin.creer_utilisateur_client(_pf(request), f, tenant_id, _s(form, "email", 320),
                                                 _s(form, "role", 30), nom=_s(form, "nom", 200))
    except RequeteInvalide as exc:
        return redirection(request, f"/admin/clients/{tenant_id}", erreur=str(exc))
    if not mdp:
        return redirection(request, f"/admin/clients/{tenant_id}", message="Compte existant rattaché au client.")
    return _fiche(request, f, tenant_id, secret={"titre": "Mot de passe provisoire", "valeur": mdp,
                                                 "note": "À transmettre à l'utilisateur par un canal sûr ; "
                                                         "il ne sera plus affiché."})


@routeur.post("/clients/{tenant_id}/entites")
def ajouter_entite(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        with _pf(request).db.operateur(f) as op:
            svc_admin.ajouter_entite(op.client(tenant_id, "ajout d'une entité"), _s(form, "raison_sociale", 300),
                                     tva=_s(form, "tva", 32) or None, siren=_s(form, "siren", 9) or None,
                                     eori=_s(form, "eori", 32) or None, alias=_s(form, "alias", 1000))
    except RequeteInvalide as exc:
        return redirection(request, f"/admin/clients/{tenant_id}#entites", erreur=str(exc))
    return redirection(request, f"/admin/clients/{tenant_id}#entites", message="Entité enregistrée.")


@routeur.post("/clients/{tenant_id}/transitaires")
def ajouter_transitaire(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        with _pf(request).db.operateur(f) as op:
            svc_admin.ajouter_transitaire(op.client(tenant_id, "ajout d'un transitaire"), _s(form, "nom", 300),
                                          tva=_s(form, "tva", 32) or None, alias=_s(form, "alias", 1000),
                                          adresse=_s(form, "adresse", 500), contact=_s(form, "contact", 500))
    except RequeteInvalide as exc:
        return redirection(request, f"/admin/clients/{tenant_id}#transitaires", erreur=str(exc))
    return redirection(request, f"/admin/clients/{tenant_id}#transitaires", message="Transitaire enregistré.")


@routeur.post("/clients/{tenant_id}/grilles")
def importer_grille(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    form = depuis_boucle(request.form, max_files=1, max_fields=20, max_part_size=64 * 1024)
    request.app.state.securite.verifier(request, form.get("csrf") if isinstance(form.get("csrf"), str) else None)
    fichier = form.get("fichier")
    if not isinstance(fichier, UploadFile):
        return redirection(request, f"/admin/clients/{tenant_id}#grilles", erreur="Fichier de grille manquant.")
    contenu = fichier.file.read(2 * 1024 * 1024 + 1)
    try:
        with _pf(request).db.operateur(f) as op:
            g = svc_admin.importer_grille(
                op.client(tenant_id, "import d'une grille tarifaire"), contenu, fichier.filename or "grille",
                transitaire_id=_s(form, "transitaire_id", 64), reference=_s(form, "reference", 200) or None,
                valide_du=_s(form, "valide_du", 10) or None, valide_au=_s(form, "valide_au", 10) or None,
                hors_grille=_s(form, "hors_grille", 20) or "tolerees")
    except RequeteInvalide as exc:
        return redirection(request, f"/admin/clients/{tenant_id}#grilles", erreur=str(exc))
    return redirection(request, f"/admin/clients/{tenant_id}#grilles",
                       message=f"Grille importée en brouillon (version {g.version}) : à valider.")


@routeur.post("/clients/{tenant_id}/grilles/valider")
def valider_grille(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        version = int(_s(form, "version", 6))
    except ValueError:
        return redirection(request, f"/admin/clients/{tenant_id}#grilles", erreur="Version invalide.")
    with _pf(request).db.operateur(f) as op:
        op.client(tenant_id, "validation d'une grille tarifaire").valider_grille(_s(form, "grille_id", 64), version)
    return redirection(request, f"/admin/clients/{tenant_id}#grilles",
                       message="Grille validée : elle sert désormais aux contrôles D.")


@routeur.post("/clients/{tenant_id}/cles-api")
def creer_cle(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        with _pf(request).db.operateur(f) as op:
            cle = svc_admin.creer_cle(op.client(tenant_id, "création d'une clé d'API"), _s(form, "nom", 200),
                                      _s(form, "role", 30) or "client_admin")
    except RequeteInvalide as exc:
        return redirection(request, f"/admin/clients/{tenant_id}#cles", erreur=str(exc))
    return _fiche(request, f, tenant_id, secret={"titre": "Clé d'API", "valeur": cle.cle,
                                                 "note": "Copiez-la maintenant : seule son empreinte est conservée."})


@routeur.post("/clients/{tenant_id}/cles-api/{cle_id}/revoquer")
def revoquer_cle(request: Request, tenant_id: str, cle_id: str) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    with _pf(request).db.operateur(f) as op:
        op.client(tenant_id, "révocation d'une clé d'API").revoquer_cle_api(cle_id)
    return redirection(request, f"/admin/clients/{tenant_id}#cles", message="Clé révoquée.")


@routeur.post("/clients/{tenant_id}/plafond")
def plafond(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        montant = montant_saisi(_s(form, "plafond", 40), nom="plafond", maximum=Decimal("10000"), zero=True)
    except RequeteInvalide:
        return redirection(request, f"/admin/clients/{tenant_id}", erreur="Plafond invalide.")
    with _pf(request).db.operateur(f) as op:
        reglages = next((dict(t.reglages or {}) for t in op.lister_clients() if t.id == tenant_id), None)
        if reglages is None:
            raise AccesRefuse("introuvable ou hors périmètre")
        reglages.pop("plafond_cout_ia_mensuel_eur", None)
        op.modifier_client(tenant_id, plafond_cout_ia_mensuel_eur=montant, reglages=reglages)
    return redirection(request, f"/admin/clients/{tenant_id}", message="Plafond IA mensuel modifié.")


@routeur.post("/clients/{tenant_id}/publier")
def publier(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    try:
        r = publication.publier_rapport(_pf(request), f, tenant_id)
    except RequeteInvalide as exc:
        return redirection(request, f"/admin/clients/{tenant_id}", erreur=str(exc))
    except Exception as exc:  # garde-fous du rapport (formulation interdite) : message neutre
        from controldone.guardrails import FormulationInterdite

        if isinstance(exc, FormulationInterdite):
            return redirection(request, f"/admin/clients/{tenant_id}",
                               erreur="Rapport bloqué : une formulation interdite figure dans le texte.")
        raise
    return redirection(request, "/admin/validation#sorties",
                       message=f"Rapport préparé ({r.nb_dossiers} dossier(s), {r.nb_constats} constat(s) "
                               "validé(s)) : à approuver dans la file de validation.")


@routeur.post("/clients/{tenant_id}/reclamations")
def preparer_reclamation(request: Request, tenant_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        reclamations.preparer_dossier(_pf(request), f, tenant_id, _s(form, "transitaire_id", 64))
    except RequeteInvalide as exc:
        return redirection(request, f"/admin/clients/{tenant_id}", erreur=str(exc))
    return redirection(request, "/admin/validation#sorties",
                       message="Relevé d'écarts préparé : à approuver dans la file de validation.")


# --- dossier --------------------------------------------------------------------------------------------------


@routeur.get("/clients/{tenant_id}/dossiers/{dossier_id}")
def dossier(request: Request, tenant_id: str, dossier_id: str) -> Response:
    f = _fondateur(request)
    pf = _pf(request)
    with pf.db.operateur(f) as op:
        scope = op.client(tenant_id, "consultation d'un dossier", lecture=True)
        info = client_info(scope)
        lu = detail_dossier(scope, dossier_id)
        images = images_dossier(pf.vault, scope, lu)
    return page(request, "dossier.html.j2", titre=f"Dossier {lu.ligne.reference}", nav="clients", lu=lu, img=images,
                base=f"/admin/clients/{tenant_id}", client=info, fondateur=True, demo=info["demo"],
                retour=request.url.path)


@routeur.get("/clients/{tenant_id}/documents/{document_id}/pages/{numero}.png")
def page_document(request: Request, tenant_id: str, document_id: str, numero: int) -> Response:
    f = _fondateur(request)
    pf = _pf(request)
    with pf.db.operateur(f) as op:
        img = image_page(pf.vault, op.client(tenant_id, "affichage d'une page de document", lecture=True), document_id, numero)
    if img is None:
        raise AccesRefuse("introuvable ou hors périmètre")
    return png(img)


@routeur.get("/clients/{tenant_id}/fichiers/{fichier_id}")
def telecharger_fichier(request: Request, tenant_id: str, fichier_id: str) -> Response:
    f = _fondateur(request)
    pf = _pf(request)
    with pf.db.operateur(f) as op:
        fic = op.client(tenant_id, "téléchargement d'un fichier déposé", lecture=True).obtenir(Fichier, fichier_id)
        if not fic.coffre_ref:
            raise AccesRefuse("introuvable ou hors périmètre")
        contenu = pf.vault.lire(tenant_id, fic.coffre_ref)
        nom = fic.nom_original
    return fichier_attache(contenu, nom)


def _decision(request: Request, tenant_id: str, constat_id: str, quoi: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    retour = retour_sur(form.get("retour"), "/admin/validation")
    motif = _s(form, "motif", 1000)
    try:
        with _pf(request).db.operateur(f) as op:
            scope = op.client(tenant_id, f"décision sur un constat ({quoi})")
            if quoi == "valider":
                validation.valider(scope, constat_id, motif or None)
                msg = "Constat validé : il est publié au client."
            elif quoi == "rejeter":
                validation.rejeter(scope, constat_id, motif)
                msg = "Constat rejeté."
            else:
                validation.retrograder(scope, constat_id, motif)
                msg = "Constat rétrogradé en « à vérifier »."
    except RequeteInvalide as exc:
        return redirection(request, retour, erreur=str(exc))
    return redirection(request, retour, message=msg)


@routeur.post("/clients/{tenant_id}/constats/{constat_id}/valider")
def valider(request: Request, tenant_id: str, constat_id: str) -> Response:
    return _decision(request, tenant_id, constat_id, "valider")


@routeur.post("/clients/{tenant_id}/constats/{constat_id}/rejeter")
def rejeter(request: Request, tenant_id: str, constat_id: str) -> Response:
    return _decision(request, tenant_id, constat_id, "rejeter")


@routeur.post("/clients/{tenant_id}/constats/{constat_id}/retrograder")
def retrograder(request: Request, tenant_id: str, constat_id: str) -> Response:
    return _decision(request, tenant_id, constat_id, "retrograder")


@routeur.post("/clients/{tenant_id}/dossiers/{dossier_id}/corriger")
def corriger(request: Request, tenant_id: str, dossier_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    pf = _pf(request)
    retour = retour_sur(form.get("retour"), f"/admin/clients/{tenant_id}/dossiers/{dossier_id}")
    try:
        with pf.db.operateur(f) as op:
            version = validation.corriger_valeur(
                op.client(tenant_id, "correction d'une valeur extraite"), dossier_id, _s(form, "document_id", 64),
                _s(form, "valeur_id", 64), _s(form, "valeur", 300), _s(form, "motif", 1000))
    except RequeteInvalide as exc:
        return redirection(request, retour, erreur=str(exc))
    # le recontrôle a été mis en file dans la transaction de la correction (D-1306)
    return redirection(request, retour, message=f"Valeur corrigée (version {version} du dossier) : les contrôles "
                                                "sont relancés.")


# --- file de validation -----------------------------------------------------------------------------------------


@routeur.get("/validation")
def file_validation(request: Request) -> Response:
    f = _fondateur(request)
    pf = _pf(request)
    items: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []
    with pf.db.operateur(f) as op:
        clients = {t.id: {"raison_sociale": t.raison_sociale, "actif": t.actif,
                          "demo": bool((t.reglages or {}).get("demo"))} for t in op.lister_clients()}
        par_client: dict[str, list[Any]] = defaultdict(list)
        for c in op.file_validation():
            par_client[c.tenant_id].append(c)
        demo = False
        for tenant_id in sorted(set(par_client) | {t for t in clients if clients[t]["actif"]}):
            t = clients.get(tenant_id)
            if t is None:
                continue
            scope = op.client(tenant_id, "file de validation", lecture=True)
            demo = demo or t["demo"]
            courants = {c.id for c in constats_courants(scope)} if par_client.get(tenant_id) else set()
            libelles: dict[str, str] = {}
            refs: dict[str, str] = {}
            for d in scope.lister(Dossier):
                refs[d.id] = d.reference or d.id
                from controldone.model.dossier import Dossier as DossierModele

                m = DossierModele.model_validate(d.contenu)
                for doc_id, doc in documents_du_dossier(scope, m).items():
                    libelles[doc_id] = libelle_document(doc)
                for lien in m.liens:
                    if lien.force.value == "faible":
                        attention.append({"type": "Rattachement faible", "client": t["raison_sociale"],
                                          "tenant_id": tenant_id, "dossier_id": d.id, "dossier": refs[d.id],
                                          "detail": libelles.get(lien.document_id, lien.document_id)})
            for doc in scope.lister(Document, type="inconnu"):
                if doc.dossier_id:
                    attention.append({"type": "Document non reconnu", "client": t["raison_sociale"],
                                      "tenant_id": tenant_id, "dossier_id": doc.dossier_id,
                                      "dossier": refs.get(doc.dossier_id, doc.dossier_id), "detail": doc.id})
            vues = [vue_constat(c, libelles) for c in par_client.get(tenant_id, []) if c.id in courants]
            extraits = images_preuves(pf.vault, scope, vues[:40])
            for v in vues:
                items.append({"c": v, "tenant_id": tenant_id, "client": t["raison_sociale"],
                              "dossier": refs.get(v.dossier_id, v.dossier_id), "extraits": extraits})
    ordre = {id(x["c"]): i for i, x in enumerate(items)}
    tries = trier_constats([x["c"] for x in items])
    par_c = {id(x["c"]): x for x in items}
    items = [par_c[id(c)] for c in tries if id(c) in ordre]
    sorties = FileSortante(pf.db).lister(f, statuts=["brouillon"])
    noms = {k: v["raison_sociale"] for k, v in clients.items()}
    return page(request, "admin/validation.html.j2", titre="File de validation", nav="validation", items=items,
                attention=attention, sorties=sorties, noms=noms, libelles_sortie=LIBELLES_SORTIE, demo=demo,
                retour="/admin/validation")


def _sortie(request: Request, action_id: str, quoi: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    pf = _pf(request)
    fs = FileSortante(pf.db)
    retour = retour_sur(form.get("retour"), "/admin/validation#sorties")
    try:
        if quoi == "approuver":
            fs.approuver(action_id, f)
            publication.mettre_a_disposition(pf, action_id, f)
            msg = "Action approuvée."
        elif quoi == "corriger":
            a = fs.obtenir(action_id, f)
            contenu = {**a.payload, "objet": _s(form, "objet", 300), "corps": _s(form, "corps", 20000)}
            fs.corriger(action_id, f, contenu)
            publication.mettre_a_disposition(pf, action_id, f)
            msg = "Action corrigée et approuvée."
        else:
            motif = _s(form, "motif", 1000)
            if not motif:
                return redirection(request, retour, erreur="Le refus exige un motif.")
            fs.refuser(action_id, f, motif)
            msg = "Action refusée."
    except ActionBloquee as exc:
        return redirection(request, retour, erreur="Bloqué par les garde-fous : " + "; ".join(exc.motifs)[:300])
    except TransitionInterdite:
        return redirection(request, retour, erreur="Cette action a déjà fait l'objet d'une décision.")
    except ValueError as exc:  # facture approuvée mais non émise (vendeur incomplet, coupon épuisé…)
        return redirection(request, retour, erreur=f"Action approuvée, suite impossible : {exc}"[:300])
    return redirection(request, retour, message=msg)


@routeur.post("/sorties/{action_id}/approuver")
def approuver_sortie(request: Request, action_id: str) -> Response:
    return _sortie(request, action_id, "approuver")


@routeur.post("/sorties/{action_id}/corriger")
def corriger_sortie(request: Request, action_id: str) -> Response:
    return _sortie(request, action_id, "corriger")


@routeur.post("/sorties/{action_id}/refuser")
def refuser_sortie(request: Request, action_id: str) -> Response:
    return _sortie(request, action_id, "refuser")


@routeur.get("/sorties/{action_id}/{fmt}")
def piece_sortie(request: Request, action_id: str, fmt: str) -> Response:
    f = _fondateur(request)
    contenu, mime, nom = publication.piece(_pf(request), f, action_id, fmt)
    return fichier_attache(contenu, nom, mime, en_ligne=fmt in ("pdf", "html"))


# --- autonomie, jobs, journal, alertes ------------------------------------------------------------------------


@routeur.get("/autonomie")
def autonomie(request: Request) -> Response:
    f = _fondateur(request)
    fs = FileSortante(_pf(request).db)
    modes = [(k.value, LIBELLES_SORTIE.get(k.value, k.value), fs.autonomie(k).value) for k in TypeAction]
    return page(request, "admin/autonomie.html.j2", titre="Autonomie des actions sortantes", nav="autonomie",
                modes=modes, acteur_id=f.id)


@routeur.post("/autonomie")
def definir_autonomie(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        kind, mode = TypeAction(_s(form, "kind", 64)), ModeAutonomie(_s(form, "mode", 16))
    except ValueError:
        return redirection(request, "/admin/autonomie", erreur="Valeur inconnue.")
    FileSortante(_pf(request).db).definir_autonomie(kind, mode, f)
    return redirection(request, "/admin/autonomie", message="Réglage enregistré.")


@routeur.get("/jobs")
def jobs(request: Request) -> Response:
    _fondateur(request)
    store = JobStore(_pf(request).db)
    recents = store.lister(limite=200, recents=True)  # tri SQL décroissant avant la limite
    return page(request, "admin/jobs.html.j2", titre="Tâches", nav="jobs", jobs=list(reversed(recents)),
                compte=store.compter_par_statut())


@routeur.post("/jobs/{job_id}/relancer")
def relancer(request: Request, job_id: str) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    ok = JobStore(_pf(request).db).relancer(job_id, acteur_id=f.id)
    return redirection(request, "/admin/jobs", message="Tâche remise en file." if ok else None,
                       erreur=None if ok else "Seule une tâche morte peut être relancée.")


@routeur.get("/journal")
def journal(request: Request) -> Response:
    f = _fondateur(request)
    with _pf(request).db.operateur(f) as op:
        anomalies = op.verifier_journal()
        entrees = op.journal(300)
        lignes = [{"id": e.id, "ts": e.ts, "actor": e.actor, "role": e.role, "tenant_id": e.tenant_id,
                   "action": e.action, "target": e.target, "ip": e.ip, "details": e.details,
                   "hash": e.hash[:12]} for e in entrees]
        anom = [{"id": a.id, "motif": a.motif} for a in anomalies]
    return page(request, "admin/journal.html.j2", titre="Journal d'audit", nav="journal", lignes=lignes,
                anomalies=anom)


@routeur.get("/alertes")
def alertes(request: Request) -> Response:
    f = _fondateur(request)
    with _pf(request).db.operateur(f) as op:
        liste = [{"id": a.id, "kind": a.kind, "tenant_id": a.tenant_id, "message": a.message, "cree_le": a.cree_le,
                  "lue_le": a.lue_le} for a in op.alertes(non_lues=False)]
    return page(request, "admin/alertes.html.j2", titre="Alertes", nav="alertes", alertes=list(reversed(liste)))


@routeur.post("/alertes/{alerte_id}/lue")
def alerte_lue(request: Request, alerte_id: int) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    with _pf(request).db.operateur(f) as op:
        op.marquer_alerte_lue(alerte_id)
    return redirection(request, "/admin/alertes", message="Alerte marquée comme lue.")
