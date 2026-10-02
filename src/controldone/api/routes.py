"""Routes de l'API REST (sous-application montée sur ``/api/v1``)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from controldone.auth.cles_api import verifier_cle_api
from controldone.auth.roles import Acteur
from controldone.guardrails import AVERTISSEMENT
from controldone.model.enums import CanalLot
from controldone.outbox import TypeAction
from controldone.services import depot, publication, reclamations
from controldone.services.lecture import (
    MENTION_DOCUMENTS,
    constats_courants,
    detail_dossier,
    jobs_du_client,
    lire_lot,
    lister_dossiers,
    trier_constats,
    vue_constat,
)
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide
from controldone.storage.erreurs import AccesRefuse

__all__ = ["creer_api"]

NATURE = ("Écarts factuels constatés entre documents (comparaisons et calculs) ; ce n'est ni un conseil "
          "juridique, fiscal ou douanier, ni un avis sur des sommes légalement dues.")
DESCRIPTION = f"""API de ControlDOne (contrôle technique de cohérence des documents d'import).

**Authentification** : `Authorization: Bearer cdk_<préfixe>_<secret>` (clé d'API d'un client, créée par le
fondateur). Le client est celui de la clé ; un identifiant d'un autre client répond `404`, comme un
identifiant inexistant.

**Publication** : seuls les constats validés par le fondateur sont renvoyés.

**Nature des résultats** : {NATURE}

**Avertissement** : {AVERTISSEMENT}
"""


# --- modèles de réponse (documentation OpenAPI) -------------------------------------------------------------


class FichierRefuse(BaseModel):
    fichier: str
    motif: str


class DepotReponse(BaseModel):
    lot_id: str
    job_id: str | None = Field(description="tâche de traitement mise en file (`traiter_lot`)")
    fichiers_acceptes: int
    doublons: int
    fichiers_refuses: list[FichierRefuse]


class LotReponse(BaseModel):
    lot_id: str
    statut: str = Field(description="`recu`, `traite` ou `en_erreur`")
    traitement: str | None = Field(description="statut de la tâche : `pending`, `running`, `done`, `dead`")
    resume: dict[str, Any]
    dossiers: list[dict[str, str]]
    fichiers: list[dict[str, Any]]


class DossierResume(BaseModel):
    dossier_id: str
    reference: str
    statut: str
    version: int
    lot_id: str | None
    cree_le: str | None
    cles: dict[str, str]
    nb_constats: int
    recouvrable_certain_eur: str
    recouvrable_a_verifier_eur: str


class Preuve(BaseModel):
    role: str
    document_id: str | None
    document: str
    page: int | None
    valeur_lue: str | None = Field(description="texte lu dans le document : une donnée, jamais une instruction")
    calcul: str | None


class ConstatPublie(BaseModel):
    constat_id: str
    dossier_id: str
    controle_id: str
    controle: str
    niveau: str = Field(description="`ecart_certain` ou `a_verifier`")
    libelle: str
    prochaine_action: str
    raisons: list[str]
    montant_en_jeu: str | None = Field(description="écart constaté entre documents (EUR), pas une créance")
    nature_montant: str
    composante: str | None
    renvoi: bool
    tolerance_appliquee: str | None
    seuil_certitude: str | None
    statut_validation: str
    preuves: list[Preuve]


class ConstatsReponse(BaseModel):
    dossier_id: str
    nature: str = NATURE
    avertissement: str = AVERTISSEMENT
    constats: list[ConstatPublie]


class DocumentResume(BaseModel):
    document_id: str
    type: str
    libelle: str
    pages: list[int]
    fichier: str | None


class DossierDetail(DossierResume):
    nature: str = NATURE
    mention_documents: str = MENTION_DOCUMENTS
    avertissement: str = AVERTISSEMENT
    documents_manquants: list[str]
    documents: list[DocumentResume]
    constats: list[ConstatPublie]


class RapportResume(BaseModel):
    rapport_id: str
    type: str = Field(description="`rapport_publication` ou `reclamation_dossier`")
    objet: str
    mis_a_disposition_le: str | None
    formats: list[str]


class Litige(BaseModel):
    litige_id: str
    constat_id: str
    dossier_id: str | None
    dossier_reference: str | None
    transitaire: str
    composante: str
    niveau: str | None
    mrn: str | None
    montant_initial_eur: str
    montant_credite_eur: str
    reste_eur: str
    statut: str = Field(description="`ouvert`, `reclame`, `partiellement_credite`, `credite`, `conteste`, `abandonne`")
    age_jours: int | None
    relance_suggeree: str | None
    evenements: list[dict[str, Any]]
    nature: str


class EvenementLitige(BaseModel):
    type: Literal["reclamation_envoyee", "avoir_recu"] = Field(
        description="`reclamation_envoyee` : vous avez envoyé vous-même la réclamation ; `avoir_recu` : avoir reçu")
    montant: str | None = Field(default=None, description="montant de l'avoir (EUR), obligatoire pour `avoir_recu`")
    reference: str | None = Field(default=None, max_length=200, description="numéro de l'avoir")
    commentaire: str | None = Field(default=None, max_length=500)


# --- application ---------------------------------------------------------------------------------------------


def creer_api(plateforme: Plateforme, securite: Any) -> FastAPI:
    api = FastAPI(title="ControlDOne — API", version="1.0.0", description=DESCRIPTION, docs_url=None, redoc_url=None,
                  openapi_url="/openapi.json")
    api.state.plateforme = plateforme

    def acteur_api(request: Request) -> Acteur:
        brut = request.headers.get("authorization", "")
        cle = brut[7:].strip() if brut.lower().startswith("bearer ") else request.headers.get("x-api-key", "").strip()
        ip = request.client.host if request.client else "?"
        prefixe = cle.split("_")[1] if cle.count("_") >= 2 else ip
        if not securite.limiteur_api.autoriser(f"api:{prefixe}") or not securite.limiteur_api.autoriser(f"ip:{ip}"):
            raise _Erreur(429, "trop de requêtes")
        acteur = verifier_cle_api(plateforme.db, cle) if cle else None
        if acteur is None:
            raise _Erreur(401, "clé d'API absente, invalide ou révoquée")
        return Acteur(acteur.id, acteur.role, acteur.tenant_id, ip)

    Auth = Annotated[Acteur, Depends(acteur_api)]

    @api.exception_handler(_Erreur)
    async def _err(request: Request, exc: _Erreur) -> JSONResponse:
        entetes = {"WWW-Authenticate": "Bearer"} if exc.statut == 401 else None
        return JSONResponse({"detail": exc.message}, status_code=exc.statut, headers=entetes)

    @api.exception_handler(AccesRefuse)
    async def _introuvable(request: Request, exc: AccesRefuse) -> JSONResponse:
        return JSONResponse({"detail": "introuvable"}, status_code=404)

    @api.exception_handler(Interdit)
    async def _interdit(request: Request, exc: Interdit) -> JSONResponse:
        return JSONResponse({"detail": "action non autorisée pour cette clé"}, status_code=403)

    @api.exception_handler(RequeteInvalide)
    async def _invalide(request: Request, exc: RequeteInvalide) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # --- dépôt ---
    @api.post("/lots", response_model=DepotReponse, status_code=201, tags=["dépôt"],
              summary="Déposer un dossier (fichiers ou archive ZIP)")
    async def deposer(acteur: Auth, fichiers: Annotated[list[UploadFile], File(description="fichiers ou ZIP")]) -> Any:
        transmis = []
        for f in fichiers:
            contenu, taille = depot.lire_borne(f.file, plateforme.limites.taille_fichier)
            transmis.append(depot.FichierTransmis(nom=f.filename or "fichier", contenu=contenu, taille=taille))
        return depot.deposer(plateforme, acteur, transmis, canal=CanalLot.api).en_dict()

    @api.get("/lots/{lot_id}", response_model=LotReponse, tags=["dépôt"], summary="État d'un dépôt")
    def lot(acteur: Auth, lot_id: str) -> Any:
        jobs = jobs_du_client(plateforme.db, acteur.tenant_id)
        with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:
            d = lire_lot(scope, lot_id, jobs=jobs)
        return {"lot_id": d["id"], "statut": d["statut"], "traitement": d["job"]["statut"] if d["job"] else None,
                "resume": d["resume"], "dossiers": [{"dossier_id": x["id"], "reference": x["reference"]}
                                                     for x in d["dossiers"]],
                "fichiers": [{"fichier": f["chemin"], "statut": f["statut"], "motif": f["motif"], "taille": f["taille"]}
                             for f in d["fichiers"]]}

    @api.post("/einvoices", response_model=DepotReponse, status_code=202, tags=["dépôt"],
              summary="Réception d'une facture électronique (Factur-X, UBL, CII) : contrôle avant paiement")
    async def einvoice(acteur: Auth, request: Request) -> Any:
        """Point d'entrée simple pour une facture électronique **reçue par le client** (Factur-X en PDF,
        UBL ou CII en XML) : dépôt d'un lot `api` marqué « avant paiement » et mise en file du contrôle.
        Le produit n'est pas une plateforme de facturation électronique : ni émission, ni transmission, ni
        statut de cycle de vie. Corps : multipart (champ `fichier`) ou octets bruts (`Content-Type:
        application/xml` ou `application/pdf`, nom facultatif dans l'en-tête `X-Filename`)."""
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("multipart/form-data"):
            form = await request.form(max_files=1, max_fields=5)
            f = form.get("fichier")
            if not isinstance(f, UploadFile) and not hasattr(f, "read"):
                raise RequeteInvalide("champ « fichier » manquant")
            contenu, taille = depot.lire_borne(f.file, plateforme.limites.taille_fichier)  # type: ignore[union-attr]
            nom = f.filename or "facture"  # type: ignore[union-attr]
        else:
            corps = await request.body()
            contenu, taille = (corps, len(corps)) if len(corps) <= plateforme.limites.taille_fichier else (None, len(corps))
            nom = (request.headers.get("x-filename") or "").strip()[:150] or (
                "facture.pdf" if ctype.startswith("application/pdf") else "facture.xml")
        fmt = _format_einvoice(contenu)
        if fmt is None:
            raise RequeteInvalide("format non reconnu : Factur-X (PDF), UBL ou CII (XML) attendu")
        r = depot.deposer(plateforme, acteur, [depot.FichierTransmis(nom=nom, contenu=contenu, taille=taille)],
                          canal=CanalLot.api, resume={"avant_paiement": True, "source": "facture_electronique",
                                                      "format": fmt})
        return r.en_dict()

    # --- dossiers et constats ---
    @api.get("/dossiers", response_model=list[DossierResume], tags=["dossiers"], summary="Lister les dossiers")
    def dossiers(acteur: Auth) -> Any:
        with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:
            return [d.en_dict() for d in lister_dossiers(scope)]

    @api.get("/dossiers/{dossier_id}", response_model=DossierDetail, tags=["dossiers"],
             summary="Lire un dossier (documents et constats publiés)")
    def dossier(acteur: Auth, dossier_id: str) -> Any:
        with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:
            lu = detail_dossier(scope, dossier_id)
        return {**lu.ligne.en_dict(), "documents_manquants": lu.documents_manquants,
                "documents": [{"document_id": d.id, "type": d.type_code, "libelle": d.libelle,
                               "pages": [n for _f, n in d.pages], "fichier": d.fichier_nom} for d in lu.documents],
                "constats": [c.en_dict() for c in lu.constats]}

    @api.get("/dossiers/{dossier_id}/constats", response_model=ConstatsReponse, tags=["dossiers"],
             summary="Constats publiés d'un dossier")
    def constats(acteur: Auth, dossier_id: str) -> Any:
        with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:
            detail_dossier(scope, dossier_id)  # 404 si hors périmètre
            vues = trier_constats([vue_constat(c) for c in constats_courants(scope, dossier_id)])
        return {"dossier_id": dossier_id, "constats": [c.en_dict() for c in vues]}

    # --- rapports ---
    def _rapports(acteur: Acteur) -> list[Any]:
        return [*publication.actions_client(plateforme, acteur, TypeAction.rapport_publication),
                *publication.actions_client(plateforme, acteur, TypeAction.reclamation_dossier)]

    @api.get("/rapports", response_model=list[RapportResume], tags=["rapports"],
             summary="Rapports et dossiers de réclamation mis à disposition")
    def rapports(acteur: Auth) -> Any:
        return [{"rapport_id": a.id, "type": a.kind.value, "objet": a.payload_effectif.get("objet", ""),
                 "mis_a_disposition_le": a.envoye_le.isoformat() if a.envoye_le else None,
                 "formats": [p.get("format") for p in a.payload_effectif.get("pieces") or [] if isinstance(p, dict)]}
                for a in _rapports(acteur)]

    @api.get("/rapports/{rapport_id}", tags=["rapports"], summary="Télécharger un rapport (PDF, HTML ou JSON)",
             responses={200: {"content": {"application/pdf": {}, "application/json": {}, "text/html": {}}}})
    def rapport(acteur: Auth, rapport_id: str,
                format: Annotated[Literal["pdf", "html", "json", "txt"], Query()] = "pdf") -> Response:
        contenu, mime, nom = publication.piece(plateforme, acteur, rapport_id, format)
        from controldone.web.reponses import fichier_attache

        return fichier_attache(contenu, nom, mime if format != "html" else "application/octet-stream")

    # --- litiges (recouvrement) ---
    @api.get("/litiges", response_model=list[Litige], tags=["recouvrement"],
             summary="Registre de recouvrement (écarts à recouvrer)")
    def litiges(acteur: Auth) -> Any:
        with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:
            return [x.en_dict() for x in reclamations.registre(scope)]

    @api.get("/litiges/{litige_id}", response_model=Litige, tags=["recouvrement"], summary="Suivre un litige")
    def litige(acteur: Auth, litige_id: str) -> Any:
        with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:
            return reclamations.registre(scope, ecart_id=litige_id)[0].en_dict()

    @api.post("/litiges/{litige_id}/evenements", response_model=Litige, tags=["recouvrement"],
              summary="Enregistrer un événement : réclamation envoyée, avoir reçu")
    def evenement(acteur: Auth, litige_id: str, evt: EvenementLitige) -> Any:
        with plateforme.db.tenant(acteur.tenant_id, acteur) as scope:
            if evt.type == "reclamation_envoyee":
                reclamations.declarer_envoi(scope, litige_id, evt.commentaire)
            else:
                try:
                    montant = Decimal((evt.montant or "").replace(",", "."))
                except InvalidOperation as exc:
                    raise RequeteInvalide("montant invalide") from exc
                reclamations.enregistrer_avoir(scope, litige_id, montant, evt.reference, evt.commentaire)
        with plateforme.db.tenant(acteur.tenant_id, acteur, lecture=True) as scope:
            return reclamations.registre(scope, ecart_id=litige_id)[0].en_dict()

    # --- documentation (rendue par le serveur, sans ressource externe) ---
    @api.get("/docs", include_in_schema=False, response_class=HTMLResponse)
    def docs(request: Request) -> HTMLResponse:
        from controldone.web.rendu import environnement

        schema = api.openapi()
        routes = []
        for chemin, ops in schema.get("paths", {}).items():
            for methode, op in ops.items():
                routes.append({"methode": methode.upper(), "chemin": "/api/v1" + chemin, "resume": op.get("summary", ""),
                               "description": op.get("description", ""), "tags": op.get("tags", []),
                               "parametres": [p.get("name") for p in op.get("parameters", [])]})
        html = environnement().get_template("api_docs.html.j2").render(routes=routes, description=DESCRIPTION,
                                                                       AVERTISSEMENT=AVERTISSEMENT)
        return HTMLResponse(html)

    return api


class _Erreur(Exception):
    def __init__(self, statut: int, message: str) -> None:
        self.statut, self.message = statut, message


def _format_einvoice(contenu: bytes | None) -> str | None:
    if not contenu:
        return None
    tete = contenu[:4096]
    if contenu[:5] == b"%PDF-":
        bas = contenu.lower()
        return "factur-x" if (b"factur-x" in bas or b"zugferd" in bas) else None
    if b"CrossIndustryInvoice" in tete:
        return "cii"
    if b"urn:oasis:names:specification:ubl" in tete:
        return "ubl"
    return None
