"""Pages des utilisateurs client (``/espace``). Le client est **toujours** celui de la session : aucune
route ne reçoit d'identifiant de client. Un rôle client ne voit que les constats publiés (validés)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from controldone.auth.roles import Acteur, Action, Role, peut
from controldone.outbox import TypeAction
from controldone.services import depot, publication, reclamations
from controldone.services.lecture import (
    client_info,
    detail_dossier,
    job_du_lot,
    lire_lot,
    lister_lots,
)
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide
from controldone.services.saisie import montant_saisi
from controldone.storage.erreurs import AccesRefuse
from controldone.web.graphes import donnees_client
from controldone.web.i18n import traduire as _
from controldone.web.listes import Requete, lire_requete
from controldone.web.listes_sql import (
    indicateurs,
    page_dossiers,
    page_registre,
    totaux_registre,
    transitaires_registre,
)
from controldone.web.listes_vues import (
    PARAMS_DOSSIERS,
    STATUTS_DOSSIER,
    STATUTS_ECART,
    TRIS_DOSSIERS,
    TRIS_REGISTRE,
    params_registre,
)
from controldone.web.rendu import page, redirection, retour_sur
from controldone.web.reponses import fichier_attache, png
from controldone.web.securite import acteur_de, depuis_boucle
from controldone.web.suivi import ETAPES, etat_traitement
from controldone.web.vues import image_page, images_dossier

routeur = APIRouter(prefix="/espace")


def _client(request: Request) -> Acteur:
    acteur = acteur_de(request)
    if acteur.role not in (Role.client_admin, Role.client_lecteur) or acteur.tenant_id is None:
        raise AccesRefuse("introuvable ou hors périmètre")
    return acteur


def _pf(request: Request) -> Plateforme:
    return request.app.state.plateforme


def _contexte(acteur: Acteur) -> dict[str, Any]:
    return {
        "peut_deposer": peut(acteur, Action.deposer, acteur),
        "peut_declarer": peut(acteur, Action.declarer_recouvrement, acteur),
    }


@routeur.get("")
def tableau(request: Request) -> Response:
    a = _client(request)
    pf = _pf(request)
    # indicateurs agrégés en lecture de colonnes, 8 derniers dossiers par la liste paginée en SQL (bloc I3) :
    # aucune relecture de tous les dossiers et constats du client
    derniers = Requete(filtres={}, brut={}, tri="-date", tri_defaut="-date", page=1, taille=8)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        info = client_info(scope)
        ind = indicateurs(scope)
        dossiers = page_dossiers(scope, derniers)[0].elements
        lots = lister_lots(scope, limite=5)
        totaux, _n = totaux_registre(scope)
        graphes = donnees_client(scope, ind.lignes)
    for lot_ in lots:
        lot_["suivi"] = etat_traitement(lot_["statut"], job_du_lot(pf.db, a.tenant_id, lot_["id"]))
    rapports = publication.actions_client(pf, a, TypeAction.rapport_publication)
    kpi = {
        "dossiers": ind.dossiers,
        "constats": ind.constats,
        "certain": ind.certain,
        "a_verifier": ind.a_verifier,
        "reste": totaux["reste"],
        "credite": totaux["credite"],
    }
    return page(
        request,
        "client/tableau.html.j2",
        titre="Tableau de bord",
        nav="tableau",
        info=info,
        dossiers=dossiers,
        lots=lots,
        kpi=kpi,
        rapports=rapports[-3:],
        graphes=graphes,
        demo=info["demo"],
        **_contexte(a),
    )


@routeur.get("/depot")
def depot_form(request: Request) -> Response:
    a = _client(request)
    pf = _pf(request)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        info = client_info(scope)
        lots = lister_lots(scope, limite=10)
    for lot_ in lots:
        lot_["suivi"] = etat_traitement(lot_["statut"], job_du_lot(pf.db, a.tenant_id, lot_["id"]))
    return page(
        request,
        "client/depot.html.j2",
        titre="Déposer des documents",
        nav="depot",
        info=info,
        lots=lots,
        limites=pf.limites,
        demo=info["demo"],
        **_contexte(a),
    )


@routeur.post("/depot")
def deposer(request: Request) -> Response:
    a = _client(request)
    pf = _pf(request)
    if not peut(a, Action.deposer, a):
        raise Interdit("dépôt non autorisé")
    form = depuis_boucle(request.form, max_files=2000, max_fields=10, max_part_size=64 * 1024)
    request.app.state.securite.verifier(
        request, form.get("csrf") if isinstance(form.get("csrf"), str) else None
    )
    transmis = []
    for item in form.getlist("fichiers"):
        if not isinstance(item, UploadFile) or not (item.filename or "").strip():
            continue
        # le téléversement est déjà sur disque (fichier temporaire du serveur) : lu fichier par fichier
        # au moment de la réception, jamais tout le lot en mémoire (F-14)
        transmis.append(depot.FichierTransmis.depuis_flux(item.filename or "fichier", item.file, item.size))
    try:
        r = depot.deposer(pf, a, transmis)
    except RequeteInvalide as exc:
        return redirection(request, "/espace/depot", erreur=str(exc))
    msg = _("{n} fichier(s) reçu(s)", n=r.acceptes)
    if r.doublons:
        msg += ", " + _("{n} déjà reçu(s)", n=r.doublons)
    if r.refuses:
        msg += ", " + _("{n} refusé(s)", n=len(r.refuses))
    return redirection(request, f"/espace/lots/{r.lot_id}", message=msg + ".")


@routeur.get("/lots/{lot_id}")
def lot(request: Request, lot_id: str) -> Response:
    a = _client(request)
    pf = _pf(request)
    job = job_du_lot(pf.db, a.tenant_id, lot_id)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        info = client_info(scope)
        donnees = lire_lot(scope, lot_id, job=job)
    suivi = etat_traitement(donnees["statut"], job)
    return page(
        request,
        "client/lot.html.j2",
        titre="Dépôt",
        nav="depot",
        lot=donnees,
        info=info,
        demo=info["demo"],
        suivi=suivi,
        etapes=ETAPES,
        rafraichir=not suivi["fini"],
        **_contexte(a),
    )


def _limiter_suivi(request: Request, a: Acteur) -> Response | None:
    """Limite de débit des points de suivi interrogés par le navigateur (par compte) : 429 au-delà."""
    if request.app.state.limiteur_suivi.autoriser(f"suivi:{a.id}"):
        return None
    return JSONResponse({"erreur": "trop de requêtes"}, status_code=429, headers={"Retry-After": "5"})


def _json_suivi(donnees: dict[str, Any]) -> JSONResponse:
    return JSONResponse(donnees, headers={"Cache-Control": "no-store"})


@routeur.get("/suivi")
def etat_lots(request: Request) -> Response:
    """État des dépôts récents du client de la session (tableaux de bord) : JSON, aucune donnée de document."""
    a = _client(request)
    if (refus := _limiter_suivi(request, a)) is not None:
        return refus
    pf = _pf(request)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        lots = lister_lots(scope, limite=10)
    sortie = []
    for x in lots:
        e = etat_traitement(x["statut"], job_du_lot(pf.db, a.tenant_id, x["id"]))
        sortie.append({"lot_id": x["id"], **e})
    return _json_suivi({"lots": sortie})


@routeur.get("/lots/{lot_id}/etat")
def etat_lot(request: Request, lot_id: str) -> Response:
    """État du traitement d'un dépôt (page du dépôt) : JSON ; 404 identique pour un lot d'un autre client."""
    a = _client(request)
    if (refus := _limiter_suivi(request, a)) is not None:
        return refus
    pf = _pf(request)
    job = job_du_lot(pf.db, a.tenant_id, lot_id)
    try:
        with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
            donnees = lire_lot(scope, lot_id, job=job)
    except AccesRefuse:
        return JSONResponse({"erreur": "introuvable"}, status_code=404, headers={"Cache-Control": "no-store"})
    e = etat_traitement(donnees["statut"], job)
    return _json_suivi(
        {
            "lot_id": donnees["id"],
            **e,
            "dossiers": len(donnees["dossiers"]),
            "fichiers": len(donnees["fichiers"]),
        }
    )


@routeur.get("/dossiers")
def dossiers(request: Request) -> Response:
    a = _client(request)
    req = lire_requete(request, PARAMS_DOSSIERS, TRIS_DOSSIERS, "reference")
    with _pf(request).db.tenant(a.tenant_id, a, lecture=True) as scope:
        info = client_info(scope)
        p, total_dossiers = page_dossiers(scope, req)  # filtres, tri et pagination en SQL (D-3801)
    return page(
        request,
        "client/dossiers.html.j2",
        titre="Dossiers",
        nav="dossiers",
        p=p,
        req=req,
        statuts=STATUTS_DOSSIER,
        total_dossiers=total_dossiers,
        info=info,
        demo=info["demo"],
        **_contexte(a),
    )


@routeur.get("/dossiers/{dossier_id}")
def dossier(request: Request, dossier_id: str) -> Response:
    a = _client(request)
    pf = _pf(request)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        info = client_info(scope)
        lu = detail_dossier(scope, dossier_id)
        images = images_dossier(pf.vault, scope, lu)
    return page(
        request,
        "dossier.html.j2",
        titre=_("Dossier {ref}", ref=lu.ligne.reference),
        nav="dossiers",
        lu=lu,
        img=images,
        base="/espace",
        client=info,
        fondateur=False,
        demo=info["demo"],
        retour=request.url.path,
        **_contexte(a),
    )


@routeur.get("/documents/{document_id}/pages/{numero}.png")
def page_document(request: Request, document_id: str, numero: int) -> Response:
    a = _client(request)
    pf = _pf(request)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        img = image_page(pf.vault, scope, document_id, numero)
    if img is None:
        raise AccesRefuse("introuvable ou hors périmètre")
    return png(img)


@routeur.get("/fichiers/{fichier_id}")
def fichier(request: Request, fichier_id: str) -> Response:
    from controldone.storage.models import Fichier

    a = _client(request)
    pf = _pf(request)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        f = scope.obtenir(Fichier, fichier_id)
        if not f.coffre_ref:
            raise AccesRefuse("introuvable ou hors périmètre")
        contenu, nom = pf.vault.lire(a.tenant_id, f.coffre_ref), f.nom_original
    return fichier_attache(contenu, nom)


@routeur.get("/rapports")
def rapports(request: Request) -> Response:
    a = _client(request)
    pf = _pf(request)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        info = client_info(scope)
    liste = list(reversed(publication.actions_client(pf, a, TypeAction.rapport_publication)))
    dossiers_rec = list(reversed(publication.actions_client(pf, a, TypeAction.reclamation_dossier)))
    return page(
        request,
        "client/rapports.html.j2",
        titre="Rapports et relevés d'écarts",
        nav="rapports",
        rapports=liste,
        reclamations=dossiers_rec,
        info=info,
        demo=info["demo"],
        **_contexte(a),
    )


@routeur.get("/rapports/{action_id}/{fmt}")
def piece(request: Request, action_id: str, fmt: str) -> Response:
    a = _client(request)
    contenu, mime, nom = publication.piece(_pf(request), a, action_id, fmt)
    en_ligne = request.query_params.get("afficher") == "1" and fmt in ("html", "pdf")
    return fichier_attache(contenu, nom, mime, en_ligne=en_ligne)


@routeur.get("/recouvrement")
def recouvrement(request: Request) -> Response:
    a = _client(request)
    with _pf(request).db.tenant(a.tenant_id, a, lecture=True) as scope:
        info = client_info(scope)
        transitaires = transitaires_registre(scope)
        req = lire_requete(request, params_registre(transitaires), TRIS_REGISTRE, "-reste")
        totaux, total_lignes = totaux_registre(scope)
        p = page_registre(scope, req, transitaires)  # filtres, tri et pagination en SQL (D-3801)
    return page(
        request,
        "client/recouvrement.html.j2",
        titre="Suivi des avoirs reçus",
        nav="recouvrement",
        p=p,
        req=req,
        statuts=STATUTS_ECART,
        transitaires=sorted(transitaires.items(), key=lambda t: t[1]),
        total_lignes=total_lignes,
        totaux=totaux,
        info=info,
        demo=info["demo"],
        retour=retour_sur("/espace/recouvrement" + req.url(), "/espace/recouvrement"),
        **_contexte(a),
    )


def _formulaire_client(request: Request) -> Any:
    from controldone.web.securite import formulaire_sync

    return formulaire_sync(request)


@routeur.post("/recouvrement/{ecart_id}/reclame")
def declarer_envoi(request: Request, ecart_id: str) -> Response:
    a = _client(request)
    form = _formulaire_client(request)
    retour = retour_sur(form.get("retour"), "/espace/recouvrement")
    try:
        reclamations.declarer_envoi_releve(
            _pf(request), a, ecart_id, str(form.get("commentaire") or "")[:500]
        )
    except RequeteInvalide as exc:
        return redirection(request, retour, erreur=str(exc))
    return redirection(request, retour, message="Envoi de votre courrier enregistré.")


@routeur.post("/recouvrement/{ecart_id}/avoir")
def avoir(request: Request, ecart_id: str) -> Response:
    a = _client(request)
    form = _formulaire_client(request)
    retour = retour_sur(form.get("retour"), "/espace/recouvrement")
    try:
        montant = montant_saisi(form.get("montant"), nom="montant HT de l'avoir")
        tva = form.get("montant_tva")
        montant_tva = (
            montant_saisi(tva, nom="TVA de l'avoir", zero=True)
            if isinstance(tva, str) and tva.strip()
            else None
        )
        origine = "administration" if form.get("origine") == "administration" else "transitaire"
        reclamations.enregistrer_avoir_recu(
            _pf(request),
            a,
            ecart_id,
            montant,
            str(form.get("reference") or "")[:200],
            str(form.get("commentaire") or "")[:500],
            origine=origine,
            montant_tva=montant_tva,
        )
    except RequeteInvalide as exc:
        return redirection(request, retour, erreur=str(exc))
    return redirection(request, retour, message="Avoir enregistré.")
