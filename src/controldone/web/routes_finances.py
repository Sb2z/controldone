"""Pages « Finances » du fondateur (``/admin/finances``) et point d'entrée des webhooks Stripe
(``/webhooks/stripe``, public, signature vérifiée par ``STRIPE_WEBHOOK_SECRET``).

Toute facture part en **brouillon** dans la file de validation ; l'émission (numéro, Factur-X) suit
l'approbation du fondateur ; rien n'est envoyé automatiquement au client.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from controldone.calendrier import aujourdhui_paris, mois_paris
from controldone.facturation import Consentement, CouponRefuse, SignatureInvalide, service_pour
from controldone.facturation.finances import export_csv, synthese
from controldone.facturation.paiements import PaiementBouchon
from controldone.outbox import FileSortante, TypeAction
from controldone.services.saisie import montant_saisi
from controldone.storage import facturation as stock
from controldone.storage.erreurs import AccesRefuse
from controldone.web.rendu import page, redirection
from controldone.web.reponses import fichier_attache
from controldone.web.routes_admin import _fondateur, _pf, _s
from controldone.web.securite import depuis_boucle, formulaire_sync

__all__ = ["routeur", "routeur_webhooks"]

log = logging.getLogger("controldone.web.finances")
routeur = APIRouter(prefix="/admin/finances")
routeur_webhooks = APIRouter()
_RETOUR = "/admin/finances"


def _url_base(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


@routeur.get("")
def finances(request: Request) -> Response:
    f = _fondateur(request)
    pf = _pf(request)
    svc = service_pour(pf)
    s = synthese(pf.db, acteur_id=f.id, acteur_role=f.role.value)
    mois = mois_paris()
    du_mois = next((x for x in s.par_mois if x.mois == mois), None)
    clients = stock.clients_facturation(pf.db)
    fs = FileSortante(pf.db)
    emises = {x["id"] for x in s.factures}
    a_emettre = [a for a in fs.lister(f, kind=TypeAction.facture_emise.value, statuts=["approuve", "corrige"])
                 if stock.facture_par_outbox(pf.db, a.id) is None]
    brouillons = fs.lister(f, kind=TypeAction.facture_emise.value, statuts=["brouillon"])
    cat = svc.catalogue
    coupons = {code: len(stock.coupon_utilisations(pf.db, code)) for code in cat.coupons}
    return page(request, "admin/finances.html.j2", titre="Finances", nav="finances", s=s, du_mois=du_mois, mois=mois,
                clients=clients, a_emettre=a_emettre, brouillons=brouillons, cat=cat, coupons=coupons,
                paiement=svc.paiement, pa=svc.pa, nb_emises=len(emises), vendeur_incomplet=cat.vendeur.champs_a_completer())


@routeur.get("/export.csv")
def export(request: Request) -> Response:
    f = _fondateur(request)
    pf = _pf(request)
    s = synthese(pf.db, acteur_id=f.id, acteur_role=f.role.value)
    return fichier_attache(export_csv(s.lignes), f"finances-{aujourdhui_paris():%Y-%m-%d}.csv", "text/plain; charset=utf-8")


@routeur.get("/factures/{facture_id}.{fmt}")
def piece_facture(request: Request, facture_id: str, fmt: str) -> Response:
    _fondateur(request)
    fac = stock.facture(_pf(request).db, facture_id)
    if fac is None or fmt not in ("pdf", "xml"):
        raise AccesRefuse("introuvable ou hors périmètre")
    nom = re.sub(r"[^A-Za-z0-9_.-]", "_", fac.numero)
    if fmt == "pdf":
        return fichier_attache(fac.pdf, f"{nom}.pdf", "application/pdf", en_ligne=True)
    return fichier_attache(fac.xml.encode("utf-8"), f"{nom}-factur-x.xml")


def _erreur(request: Request, exc: Exception) -> Response:
    return redirection(request, _RETOUR, erreur=str(exc)[:300])


@routeur.post("/diagnostic")
def proposer_diagnostic(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    svc = service_pour(_pf(request))
    coupon = _s(form, "coupon", 64) or None
    consentement = None
    if coupon:
        consentement = Consentement(signe=form.get("consentement_signe") == "1", signe_par=_s(form, "signe_par", 200),
                                    signe_le=_s(form, "signe_le", 10), reference_document=_s(form, "reference", 200))
    try:
        svc.proposer_diagnostic(_s(form, "client_id", 64), f, coupon=coupon, consentement=consentement)
    except (CouponRefuse, ValueError) as exc:
        return _erreur(request, exc)
    return redirection(request, "/admin/validation#sorties", message="Brouillon de facture de diagnostic créé : "
                                                                     "à approuver dans la file de validation.")


@routeur.post("/abonnement")
def proposer_abonnement(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        service_pour(_pf(request)).proposer_abonnement(_s(form, "client_id", 64), f, palier=_s(form, "palier", 32),
                                                       mois=_s(form, "mois", 7))
    except (KeyError, ValueError) as exc:
        return _erreur(request, exc)
    return redirection(request, "/admin/validation#sorties", message="Brouillon de facture d'abonnement créé.")


@routeur.post("/commission")
def proposer_commission(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        base = montant_saisi(_s(form, "base", 40), nom="base HT")
        service_pour(_pf(request)).proposer_commission(
            _s(form, "client_id", 64), f, base=base, avoir_id=_s(form, "avoir_id", 100),
            origine="administration" if _s(form, "origine", 20) == "administration" else "transitaire")
    except (InvalidOperation, ValueError) as exc:
        return _erreur(request, exc)
    return redirection(request, "/admin/validation#sorties", message="Brouillon de facture de commission créé.")


@routeur.post("/emettre/{action_id}")
def emettre(request: Request, action_id: str) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    try:
        fac = service_pour(_pf(request)).emettre_et_deposer(action_id, f)
    except ValueError as exc:
        return _erreur(request, exc)
    return redirection(request, _RETOUR, message=f"Facture {fac.numero} émise et déposée sur la plateforme agréée.")


@routeur.post("/factures/{facture_id}/avoir")
def avoir(request: Request, facture_id: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        brut = _s(form, "montant_ht", 40)
        service_pour(_pf(request)).proposer_avoir(facture_id, f, motif=_s(form, "motif", 500),
                                                  montant_ht=montant_saisi(brut, nom="montant HT") if brut else None)
    except (InvalidOperation, ValueError) as exc:
        return _erreur(request, exc)
    return redirection(request, "/admin/validation#sorties", message="Brouillon d'avoir créé : à approuver.")


@routeur.post("/factures/{facture_id}/paiement")
def lien_paiement(request: Request, facture_id: str) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    try:
        session = service_pour(_pf(request)).lien_paiement(facture_id, f, url_base=_url_base(request))
    except ValueError as exc:
        return _erreur(request, exc)
    return redirection(request, _RETOUR, message=f"Lien de paiement à transmettre au client : {session.url}")


@routeur.post("/abonnement/lien")
def lien_abonnement(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        session = service_pour(_pf(request)).lien_abonnement(_s(form, "client_id", 64), _s(form, "palier", 32), f,
                                                             url_base=_url_base(request))
    except (KeyError, ValueError) as exc:
        return _erreur(request, exc)
    return redirection(request, _RETOUR, message=f"Lien d'abonnement à transmettre au client : {session.url}")


@routeur.post("/pa/synchroniser")
def synchroniser_pa(request: Request) -> Response:
    _fondateur(request)
    formulaire_sync(request)
    n = service_pour(_pf(request)).synchroniser_statuts_pa()
    return redirection(request, _RETOUR, message=f"{n} statut(s) de cycle de vie reçu(s) de la plateforme agréée.")


# --- bouchon de paiement (aucun Stripe configuré) ---------------------------------------------------------------


def _bouchon(request: Request) -> PaiementBouchon:
    p = service_pour(_pf(request)).paiement
    if not isinstance(p, PaiementBouchon):
        raise AccesRefuse("introuvable ou hors périmètre")
    return p


@routeur.get("/bouchon/{session_id}")
def page_bouchon(request: Request, session_id: str) -> Response:
    _fondateur(request)
    try:
        session = _bouchon(request).session(session_id)
    except KeyError as exc:
        raise AccesRefuse("introuvable ou hors périmètre") from exc
    return page(request, "admin/paiement_bouchon.html.j2", titre="Paiement simulé", nav="finances", session=session,
                montant=Decimal(session["amount_total"]) / 100)


@routeur.post("/bouchon/{session_id}/payer")
def payer_bouchon(request: Request, session_id: str) -> Response:
    _fondateur(request)
    formulaire_sync(request)
    bouchon = _bouchon(request)
    svc = service_pour(_pf(request))
    try:
        evenements = bouchon.simuler_paiement(session_id)
    except KeyError as exc:
        raise AccesRefuse("introuvable ou hors périmètre") from exc
    for charge, signature in evenements:  # même chemin que les webhooks réels (signature vérifiée)
        svc.traiter_webhook(charge, signature)
    return redirection(request, _RETOUR, message=f"Paiement simulé : {len(evenements)} événement(s) traité(s).")


# --- webhooks -----------------------------------------------------------------------------------------------------


@routeur_webhooks.post("/webhooks/stripe", include_in_schema=False)
def webhook_stripe(request: Request) -> Response:
    charge = depuis_boucle(request.body)
    try:
        res: dict[str, Any] = service_pour(request.app.state.plateforme).traiter_webhook(
            charge, request.headers.get("stripe-signature"))
    except SignatureInvalide:
        log.warning("webhook_stripe_refuse")
        return JSONResponse({"erreur": "signature invalide"}, status_code=400)
    return JSONResponse({"recu": True, "statut": res["statut"]})


