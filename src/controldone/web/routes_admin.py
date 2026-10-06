"""Pages du fondateur (``/admin``). Second facteur obligatoire (jeton de session « deux facteurs ») ;
chaque ouverture d'un client passe par ``OperatorScope.client`` (journal d'audit avec motif)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from controldone.auth.roles import Acteur, Role
from controldone.outbox import ActionBloquee, FileSortante, ModeAutonomie, TransitionInterdite, TypeAction
from controldone.services import admin as svc_admin
from controldone.services import publication, reclamations, validation
from controldone.services.lecture import (
    LIBELLES_LOT,
    client_info,
    detail_dossier,
    libelle_document,
    vue_constat,
)
from controldone.services.plateforme import Plateforme, RequeteInvalide
from controldone.services.saisie import montant_saisi
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import Document, Dossier, Fichier
from controldone.web.graphes import donnees_fondateur
from controldone.web.i18n import N_
from controldone.web.i18n import traduire as _
from controldone.web.listes import decalage, lire_requete, paginer
from controldone.web.listes_vues import (
    NIVEAUX_VALIDATION,
    PARAMS_DOSSIERS,
    STATUTS_DOSSIER,
    STATUTS_JOB,
    TRIS_DOSSIERS,
    TRIS_JOBS,
    TRIS_JOURNAL,
    TRIS_VALIDATION,
    filtrer_dossiers,
    libelles_controles,
    params_jobs,
    params_journal,
    params_validation,
)
from controldone.web.rendu import page, redirection, retour_sur
from controldone.web.reponses import fichier_attache, png
from controldone.web.securite import acteur_de, depuis_boucle, formulaire_sync
from controldone.web.suivi import etat_traitement
from controldone.web.vues import image_page, images_dossier, images_preuves

routeur = APIRouter(prefix="/admin")

LIBELLES_SORTIE = {
    "email_client": N_("Courriel au client"), "rapport_publication": N_("Publication d'un rapport"),
    "reclamation_dossier": N_("Relevé d'écarts (mise à disposition du client)"), "relance": N_("Rappel au client"),
    "facture_emise": N_("Facture émise"), "post_linkedin": N_("Publication LinkedIn"),
    "email_prospection": N_("Courriel de prospection"), "statut_litige_pa": N_("Statut de litige"),
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
    pf = _pf(request)
    donnees = svc_admin.tableau_de_bord(pf, f)
    graphes = donnees_fondateur({c.id: c.stats for c in donnees["clients"]})
    return page(request, "admin/tableau.html.j2", titre="Tableau de bord", nav="tableau", d=donnees,
                graphes=graphes, traitements=_traitements(pf), demo=any(c.demo for c in donnees["clients"]))


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
    req = lire_requete(request, PARAMS_DOSSIERS, TRIS_DOSSIERS, "reference", ancre="#dossiers")
    d = svc_admin.fiche_client(pf, f, tenant_id)
    p = paginer(filtrer_dossiers(d["dossiers"], req), req)
    sorties = FileSortante(pf.db).lister(f, tenant_id=tenant_id)
    return page(request, "admin/client.html.j2", titre=d["info"]["raison_sociale"], nav="clients", c=d, p=p, req=req,
                statuts=STATUTS_DOSSIER,
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
    return _fiche(request, f, tenant_id, secret={"titre": N_("Mot de passe provisoire"), "valeur": mdp,
                                                 "note": N_("À transmettre à l'utilisateur par un canal sûr ; "
                                                            "il ne sera plus affiché.")})


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
                       message="Grille importée en brouillon (version {n}) : à valider.", n=g.version)


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
    return _fiche(request, f, tenant_id, secret={"titre": N_("Clé d'API"), "valeur": cle.cle,
                                                 "note": N_("Copiez-la maintenant : seule son empreinte est conservée.")})


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
                       message="Rapport préparé ({d} dossier(s), {c} constat(s) validé(s)) : à approuver dans la file "
                               "de validation.", d=r.nb_dossiers, c=r.nb_constats)


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
    return page(request, "dossier.html.j2", titre=_("Dossier {ref}", ref=lu.ligne.reference), nav="clients", lu=lu, img=images,
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
                msg = N_("Constat validé : il est publié au client.")
            elif quoi == "rejeter":
                validation.rejeter(scope, constat_id, motif)
                msg = N_("Constat rejeté.")
            else:
                validation.retrograder(scope, constat_id, motif)
                msg = N_("Constat rétrogradé en « à vérifier ».")
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
    return redirection(request, retour, message="Valeur corrigée (version {n} du dossier) : les contrôles sont "
                                                "relancés.", n=version)


# --- file de validation -----------------------------------------------------------------------------------------


@routeur.get("/validation")
def file_validation(request: Request) -> Response:
    """File de validation : filtres, tri et pagination en SQL (D-3801) ; seuls les constats de la page affichée
    sont mis en forme (libellés des documents, extraits de preuve), dans le périmètre de leur client."""
    f = _fondateur(request)
    pf = _pf(request)
    with pf.db.operateur(f) as op:
        clients = {t.id: {"raison_sociale": t.raison_sociale, "actif": t.actif,
                          "demo": bool((t.reglages or {}).get("demo"))} for t in op.lister_clients()}
        noms_actifs = {k: v["raison_sociale"] for k, v in clients.items() if v["actif"]}
        req = lire_requete(request, params_validation(noms_actifs), TRIS_VALIDATION, "priorite", ancre="#constats")
        fl = req.filtres
        criteres = {"clients": sorted(noms_actifs), "client": fl.get("client"), "controle": fl.get("controle"),
                    "niveau": fl.get("niveau"), "mini": fl.get("min"), "maxi": fl.get("max"), "tri": req.tri}
        total_file = 0

        def lire(dec: int) -> tuple[list[Any], int]:
            nonlocal total_file
            constats, total, total_file = op.rechercher_file_validation(**criteres, decalage=dec, limite=req.taille)
            return constats, total

        constats, total = _page_sql(req, lire)
        bruts, nb_attention = op.points_attention(sorted(noms_actifs))
        demo = any(clients[t]["demo"] for t in noms_actifs)
        par_client: dict[str, list[Any]] = defaultdict(list)
        for c in constats:
            par_client[c.tenant_id].append(c)
        for b in bruts:
            par_client.setdefault(b["tenant_id"], [])
        items_par_id: dict[str, dict[str, Any]] = {}
        attention: list[dict[str, Any]] = []
        for tenant_id, liste in par_client.items():
            nom = clients[tenant_id]["raison_sociale"]
            scope = op.client(tenant_id, "file de validation", lecture=True)
            libelles = _libelles_documents(scope, {c.dossier_id for c in liste},
                                           {b["document_id"] for b in bruts if b["tenant_id"] == tenant_id})
            refs = {d.id: d.reference or d.id for d in scope.lister_parmi(Dossier, "id", {c.dossier_id for c in liste})}
            vues = [vue_constat(c, libelles) for c in liste]
            extraits = images_preuves(pf.vault, scope, vues)
            for v in vues:
                items_par_id[v.id] = {"c": v, "tenant_id": tenant_id, "client": nom,
                                      "dossier": refs.get(v.dossier_id, v.dossier_id), "extraits": extraits}
            for b in bruts:
                if b["tenant_id"] == tenant_id:
                    attention.append({"type": N_("Rattachement faible") if b["type"] == "faible"
                                      else N_("Document non reconnu"),
                                      "client": nom, "tenant_id": tenant_id, "dossier_id": b["dossier_id"],
                                      "dossier": b["dossier"],
                                      "detail": libelles.get(b["document_id"], b["document_id"])
                                      if b["type"] == "faible" else b["document_id"]})
        p = paginer([items_par_id[c.id] for c in constats], req, total=total)
    sorties = FileSortante(pf.db).lister(f, statuts=["brouillon"])
    noms = {k: v["raison_sociale"] for k, v in clients.items()}
    return page(request, "admin/validation.html.j2", titre="File de validation", nav="validation", p=p, req=req,
                total_file=total_file, clients_filtre=sorted(noms_actifs.items(), key=lambda x: x[1].casefold()),
                controles=libelles_controles(), niveaux=NIVEAUX_VALIDATION, attention=attention,
                nb_attention=nb_attention, sorties=sorties, noms=noms, libelles_sortie=LIBELLES_SORTIE, demo=demo,
                retour=retour_sur("/admin/validation" + req.url(), "/admin/validation"))


def _libelles_documents(scope: Any, dossier_ids: set[str], document_ids: set[str]) -> dict[str, str]:
    """Libellés des documents des dossiers ``dossier_ids`` et des documents ``document_ids`` (page affichée)."""
    from controldone.model.documents import Document as DocumentModele

    libelles: dict[str, str] = {}
    for d in scope.lister_parmi(Document, "dossier_id", dossier_ids) + scope.lister_parmi(Document, "id", document_ids):
        try:
            libelles[d.id] = libelle_document(DocumentModele.model_validate(d.contenu))
        except ValueError:
            libelles[d.id] = d.id
    return libelles


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
            msg = N_("Action approuvée.")
        elif quoi == "corriger":
            a = fs.obtenir(action_id, f)
            contenu = {**a.payload, "objet": _s(form, "objet", 300), "corps": _s(form, "corps", 20000)}
            fs.corriger(action_id, f, contenu)
            publication.mettre_a_disposition(pf, action_id, f)
            msg = N_("Action corrigée et approuvée.")
        else:
            motif = _s(form, "motif", 1000)
            if not motif:
                return redirection(request, retour, erreur="Le refus exige un motif.")
            fs.refuser(action_id, f, motif)
            msg = N_("Action refusée.")
    except ActionBloquee as exc:
        return redirection(request, retour, erreur="Bloqué par les garde-fous : {motifs}",
                           motifs="; ".join(exc.motifs)[:300])
    except TransitionInterdite:
        return redirection(request, retour, erreur="Cette action a déjà fait l'objet d'une décision.")
    except ValueError as exc:  # facture approuvée mais non émise (vendeur incomplet, coupon épuisé…)
        return redirection(request, retour, erreur="Action approuvée, suite impossible : {motif}", motif=str(exc)[:250])
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
    kinds, clients = store.valeurs()
    req = lire_requete(request, params_jobs(kinds, clients), TRIS_JOBS, "-cree")
    f = req.filtres
    criteres = {"statut": f.get("statut"), "kind": f.get("kind"), "tenant_id": f.get("client")}
    liste, total = _page_sql(req, lambda dec: store.rechercher(**criteres, croissant=req.tri == "cree", decalage=dec,
                                                              limite=req.taille))
    p = paginer(liste, req, total=total)
    return page(request, "admin/jobs.html.j2", titre="Tâches", nav="jobs", p=p, req=req, statuts=STATUTS_JOB,
                kinds=kinds, clients=clients, compte=store.compter_par_statut(),
                retour=retour_sur("/admin/jobs" + req.url(), "/admin/jobs"))


@routeur.get("/jobs/etat")
def etat_jobs(request: Request) -> Response:
    """Suivi en direct des traitements de dépôts (tableau de bord du fondateur) : JSON, sans donnée de document."""
    f = _fondateur(request)
    if not request.app.state.limiteur_suivi.autoriser(f"suivi:{f.id}"):
        return JSONResponse({"erreur": "trop de requêtes"}, status_code=429, headers={"Retry-After": "5"})
    return JSONResponse(_traitements(_pf(request)), headers={"Cache-Control": "no-store"})


def _traitements(pf: Plateforme, limite: int = 6) -> dict[str, Any]:
    store = JobStore(pf.db)
    liste, _total = store.rechercher(kind="traiter_lot", limite=limite)
    lots = []
    for j in liste:
        statut_lot = "traite" if j.statut == "done" else "recu"
        lots.append({"lot_id": str(j.payload.get("lot_id") or ""), "client": j.tenant_id or "",
                     "cree_le": j.run_after.isoformat() if j.run_after else None,
                     **etat_traitement(statut_lot, j)})
    return {"compte": store.compter_par_statut(), "lots": lots}


@routeur.post("/jobs/{job_id}/relancer")
def relancer(request: Request, job_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    ok = JobStore(_pf(request).db).relancer(job_id, acteur_id=f.id)
    return redirection(request, retour_sur(form.get("retour"), "/admin/jobs"), message="Tâche remise en file." if ok else None,
                       erreur=None if ok else "Seule une tâche morte peut être relancée.")


@routeur.get("/journal")
def journal(request: Request) -> Response:
    f = _fondateur(request)
    with _pf(request).db.operateur(f) as op:
        anomalies = op.verifier_journal()
        actions, clients = op.valeurs_journal()
        req = lire_requete(request, params_journal(actions, clients), TRIS_JOURNAL, "-id")
        fl = req.filtres
        criteres = {"acteur": fl.get("acteur"), "action": fl.get("action"), "tenant_id": fl.get("client"),
                    "du": _debut_jour(fl.get("du")), "au": _debut_jour(fl.get("au"), 1)}
        entrees, total = _page_sql(req, lambda dec: op.rechercher_journal(**criteres, croissant=req.tri == "id",
                                                                          decalage=dec, limite=req.taille))
        lignes = [{"id": e.id, "ts": e.ts, "actor": e.actor, "role": e.role, "tenant_id": e.tenant_id,
                   "action": e.action, "target": e.target, "ip": e.ip, "details": e.details,
                   "hash": e.hash[:12]} for e in entrees]
        anom = [{"id": a.id, "motif": a.motif} for a in anomalies]
    p = paginer(lignes, req, total=total)
    return page(request, "admin/journal.html.j2", titre="Journal d'audit", nav="journal", p=p, req=req,
                actions=actions, clients=clients, anomalies=anom)


def _page_sql(req: Any, lire: Any) -> tuple[list[Any], int]:
    """Page lue en SQL ; une page au-delà de la dernière est relue à la dernière page existante."""
    liste, total = lire((req.page - 1) * req.taille)
    if not liste and total and req.page > 1:
        liste, total = lire(decalage(req, total))
    return liste, total


def _debut_jour(d: Any, plus: int = 0) -> Any:
    """Minuit (heure de Paris) du jour ``d`` (+ ``plus`` jours), en UTC ; ``None`` sans date."""
    if d is None:
        return None
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    return datetime.combine(d + timedelta(days=plus), time(0), tzinfo=ZoneInfo("Europe/Paris"))


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
