"""Préparation des vues communes au fondateur et au client : images des pages (vignettes) et extraits de
preuve, rendus depuis le coffre **dans le périmètre déjà ouvert** (un seul accès tracé par page vue)."""

from __future__ import annotations

from typing import Any

from controldone.model.documents import Document as DocumentModele
from controldone.services.lecture import DossierLu
from controldone.services.vignettes import extrait_png, page_png
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import Constat, Document, Fichier
from controldone.storage.scope import TenantScope

__all__ = ["image_page", "images_dossier", "images_preuves"]

MAX_VIGNETTES = 4


def _fichier(scope: TenantScope, fichier_id: str | None) -> Fichier | None:
    if not fichier_id:
        return None
    try:
        return scope.obtenir(Fichier, fichier_id)
    except AccesRefuse:
        return None


def _rendu_page(vault: Any, scope: TenantScope, f: Fichier, numero: int, taille: str) -> bytes | None:
    if not f.coffre_ref or f.type_mime not in ("application/pdf", "image/png", "image/jpeg", "image/tiff"):
        return None
    ref = f.coffre_ref
    return page_png(f"{scope.tenant_id}:{ref}", lambda: vault.lire(scope.tenant_id, ref), f.type_mime, numero,
                    taille)


def image_page(vault: Any, scope: TenantScope, document_id: str, numero: int, taille: str = "grand") -> bytes | None:
    doc = DocumentModele.model_validate(scope.obtenir(Document, document_id).contenu)
    pr = doc.page_ref(numero)
    if pr is None:
        raise AccesRefuse("introuvable ou hors périmètre")
    f = _fichier(scope, pr.fichier_id)
    if f is None:
        raise AccesRefuse("introuvable ou hors périmètre")
    return _rendu_page(vault, scope, f, numero, taille)


def images_preuves(vault: Any, scope: TenantScope, constats: list[Any],
                   docs: dict[str, DocumentModele] | None = None) -> dict[tuple[str, int], bytes]:
    """Extraits de page (rognages) des preuves : ``{(constat_id, index): PNG}``."""
    docs = dict(docs or {})
    sortie: dict[tuple[str, int], bytes] = {}
    for c in constats:
        brut = scope.obtenir(Constat, c.id).contenu or {}
        preuves = brut.get("preuves") or []
        for p in c.preuves:
            if p.document_id is None or p.page is None or p.index >= len(preuves):
                continue
            if p.document_id not in docs:
                try:
                    docs[p.document_id] = DocumentModele.model_validate(scope.obtenir(Document, p.document_id).contenu)
                except AccesRefuse:
                    continue
            doc = docs[p.document_id]
            pr = doc.page_ref(p.page)
            f = _fichier(scope, pr.fichier_id if pr else None)
            if f is None or not f.coffre_ref:
                continue
            zone = None
            vs_id = preuves[p.index].get("valeur_sourcee_id")
            for v in doc.valeurs():
                if v.id == vs_id and v.zone is not None:
                    zone = (v.zone.x0, v.zone.y0, v.zone.x1, v.zone.y1)
            ref = f.coffre_ref
            img = extrait_png(f"{scope.tenant_id}:{ref}", lambda ref=ref: vault.lire(scope.tenant_id, ref),
                              f.type_mime, p.page, zone=zone, valeur=p.valeur_lue)
            if img:
                sortie[(c.id, p.index)] = img
    return sortie


def images_dossier(vault: Any, scope: TenantScope, lu: DossierLu) -> dict[str, Any]:
    vignettes: dict[str, list[tuple[int, bytes]]] = {}
    for d in lu.documents:
        liste = []
        for fid, numero in d.pages[:MAX_VIGNETTES]:
            f = _fichier(scope, fid)
            img = _rendu_page(vault, scope, f, numero, "mini") if f else None
            if img:
                liste.append((numero, img))
        vignettes[d.id] = liste
    return {"vignettes": vignettes, "extraits": images_preuves(vault, scope, lu.constats)}
