"""Pages des utilisateurs client (``/espace``). Le client est **toujours** celui de la session : aucune
route ne reçoit d'identifiant de client. Un rôle client ne voit que les constats publiés (validés)."""

from __future__ import annotations

from decimal import Decimal
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
from controldone.web.i18n import N_, pluriel
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


def _certains_hors_recouvrement(scope: Any, dossiers: list[Any]) -> dict[str, Decimal]:
    """Affichage seulement : pour un dossier « Écart certain » sans montant recouvrable (par exemple un écart de
    calcul sur la déclaration), montant de ses écarts certains publiés qui ne se demandent pas au transitaire. Rien
    n'est ajouté aux totaux recouvrables (indicateurs, suivi des avoirs, rapport) : mêmes règles d'exclusion que
    ``services.lecture.ligne_dossier``."""
    from controldone.services.lecture import hors_totaux
    from controldone.storage import listes_sql as requetes

    ids = [d.id for d in dossiers if d.statut_code == "ecart_certain" and not d.recouvrable_certain]
    out: dict[str, Decimal] = {}
    for d, cs in requetes.lignes_dossiers(scope, ids):
        out[d.id] = sum(
            (
                c.montant_en_jeu
                for c in cs
                if c.niveau == "ecart_certain"
                and c.statut_validation == "valide"
                and c.nature_montant not in ("recouvrable", "renvoi", "aucun")
                and not hors_totaux(c)
                and c.montant_en_jeu
                and c.montant_en_jeu > 0
            ),
            Decimal(0),
        )
    return out


def _a_confirmer(scope: Any) -> Decimal:
    """Affichage seulement : part du suivi des avoirs dont le constat publié est « à vérifier » (badge « À
    confirmer »). Quand elle est nulle, le total du suivi est le montant recouvrable certain et porte le même nom
    qu'au tableau de bord ; sinon il est présenté comme « Montant recouvrable », dont cette part. Aucun total
    n'est modifié."""
    from controldone.storage.models import Constat, Ecart

    ids = [c.id for c in scope.lister(Constat, niveau="a_verifier")]
    if not ids:
        return Decimal(0)
    return sum(
        (e.montant_initial or Decimal(0) for e in scope.lister_parmi(Ecart, "constat_id", ids)), Decimal(0)
    )


def types_preuves(scope: Any, lu: Any) -> dict[tuple[str, int], str]:
    """Affichage seulement : type de la valeur lue de chaque preuve (``{(constat_id, index): TypeValeur}``), pour
    que la carte du constat dise « Code lu : 1008 » et non « Valeur lue », qui se lirait comme un montant. Lu dans
    le constat (valeur sourcée citée) et dans le document, au sein du périmètre déjà ouvert ; une preuve sans
    valeur sourcée (calcul) n'y figure pas et garde un libellé neutre."""
    from controldone.model.documents import Document as DocumentModele
    from controldone.storage.models import Constat, Document

    valeurs: dict[str, dict[str, str]] = {}
    out: dict[tuple[str, int], str] = {}
    for c in lu.constats:
        try:
            brutes = (scope.obtenir(Constat, c.id).contenu or {}).get("preuves") or []
        except AccesRefuse:
            continue
        for p in c.preuves:
            if p.document_id is None or p.index >= len(brutes):
                continue
            vs_id = brutes[p.index].get("valeur_sourcee_id")
            if not vs_id:
                continue
            if p.document_id not in valeurs:
                try:
                    doc = DocumentModele.model_validate(scope.obtenir(Document, p.document_id).contenu)
                    valeurs[p.document_id] = {v.id: v.type.value for v in doc.valeurs()}
                except AccesRefuse:
                    valeurs[p.document_id] = {}
            if t := valeurs[p.document_id].get(vs_id):
                out[(c.id, p.index)] = t
    return out


#: Titres générés avec un tiret cadratin pour séparateur (« Rapport de diagnostic — Société »), déjà enregistrés
#: dans les actions publiées : affichés avec « · ». Seuls ces débuts connus sont repris ; le reste du titre
#: (raison sociale, numéros de facture) s'affiche tel quel.
DEBUTS_TITRES = ("Rapport de diagnostic", "Votre relevé d'écarts est prêt", "Relevé d'écarts entre documents")


def titre_affiche(objet: Any) -> str:
    """Titre d'un rapport ou d'un relevé tel qu'affiché dans l'espace du client (séparateur « · »)."""
    reste = str(objet or "")
    debuts: list[str] = []
    while True:
        for debut in DEBUTS_TITRES:
            if reste.startswith(debut + " — "):
                debuts.append(debut)
                reste = reste[len(debut) + 3 :]
                break
        else:
            break
    return " · ".join([*debuts, reste]) if debuts else reste


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
        hors_recouvrement = _certains_hors_recouvrement(scope, dossiers)
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
        hors_recouvrement=hors_recouvrement,
        lots=lots,
        kpi=kpi,
        rapports=rapports[-3:],
        graphes=graphes,
        titre_affiche=titre_affiche,
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
    msg = pluriel(
        N_("{n} fichier reçu"), N_("{n} fichiers reçus"), r.acceptes, aucun=N_("Aucun fichier reçu")
    )
    if r.doublons:
        msg += ", " + pluriel(N_("{n} déjà reçu"), N_("{n} déjà reçus"), r.doublons)
    if r.refuses:
        msg += ", " + pluriel(N_("{n} refusé"), N_("{n} refusés"), len(r.refuses))
    return redirection(
        request,
        f"/espace/lots/{r.lot_id}",
        message=msg + ". " + _("Le traitement a commencé : suivez-le sur cette page."),
    )


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
        hors_recouvrement = _certains_hors_recouvrement(scope, p.elements)
    return page(
        request,
        "client/dossiers.html.j2",
        titre="Dossiers",
        nav="dossiers",
        p=p,
        req=req,
        statuts=STATUTS_DOSSIER,
        total_dossiers=total_dossiers,
        hors_recouvrement=hors_recouvrement,
        info=info,
        demo=info["demo"],
        **_contexte(a),
    )


def _bilan_dossier(scope: Any, lu: Any) -> dict[str, Any]:
    """Ce que le dossier a permis d'obtenir (D-5205) : montant recouvrable (dont la part à confirmer), avoirs
    enregistrés par le client et reste, lus dans le suivi des avoirs pour les seuls constats publiés de ce dossier.
    Rien n'est estimé."""
    from controldone.services.reclamations import registre
    from controldone.storage.models import Ecart

    ids_constats = [c.id for c in lu.constats]
    ids = [e.id for e in scope.lister_parmi(Ecart, "constat_id", ids_constats)] if ids_constats else []
    lignes = registre(scope, ecart_ids=ids) if ids else []
    return {
        "n": len(lignes),
        "initial": sum((x.montant_initial for x in lignes), Decimal(0)),
        # part « à confirmer » (constat publié « à vérifier ») : nomme le total comme au suivi des avoirs
        "a_confirmer": sum((x.montant_initial for x in lignes if x.niveau == "a_verifier"), Decimal(0)),
        "credite": sum((x.montant_credite for x in lignes), Decimal(0)),
        "reste": sum((x.reste for x in lignes if x.statut_code not in ("credite", "abandonne")), Decimal(0)),
    }


@routeur.get("/dossiers/{dossier_id}")
def dossier(request: Request, dossier_id: str) -> Response:
    a = _client(request)
    pf = _pf(request)
    with pf.db.tenant(a.tenant_id, a, lecture=True) as scope:
        info = client_info(scope)
        lu = detail_dossier(scope, dossier_id)
        images = images_dossier(pf.vault, scope, lu)
        bilan = _bilan_dossier(scope, lu)
        types_lus = types_preuves(scope, lu)
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
        bilan=bilan,
        types_lus=types_lus,
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
        titre_affiche=titre_affiche,
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
        a_confirmer = _a_confirmer(scope)
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
        a_confirmer=a_confirmer,
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
    return redirection(request, retour, message="C'est noté : votre courrier est enregistré dans le suivi.")


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
    return redirection(request, retour, message="Avoir enregistré. Il est déduit du reste à obtenir.")
