"""Listes filtrées, triées et paginées **en SQL** (D-3801) : dossiers et suivi des avoirs d'un client.

Toutes les requêtes partent de ``TenantScope.requete`` (cloisonnement du client ; constats publiés seuls pour un
rôle client). Les filtres validés par ``web.listes.lire_requete`` sont passés à l'ORM comme **paramètres liés**
(sous-chaînes échappées : ``%`` et ``_`` n'ont pas de sens particulier). Seule la page affichée (25, 50 ou 100
lignes) est ensuite lue en entier et mise en forme, avec les mêmes règles que les listes complètes
(``services.lecture.ligne_dossier``, ``services.reclamations.registre``).

Montants : stockés en texte exact ; le tri et la comparaison passent par ``CAST … AS NUMERIC`` en base (clé de
tri seulement), les montants affichés et les totaux sont recalculés en ``Decimal``.

Recherche : chaque mot (minuscules, sans accents) doit figurer dans l'un des champs ; les références et les clés
de dossier sont comparées en minuscules (ASCII), les libellés (composante, transitaire) sont rapprochés en Python
sur leurs listes fermées, puis passés en SQL comme ensembles de codes.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Numeric, case, cast, func, or_, select

from controldone.model.enums import Composante
from controldone.rapport.vue import LIBELLES_COMPOSANTE
from controldone.services.lecture import DossierLigne, ligne_dossier
from controldone.services.reclamations import LigneRegistre, registre
from controldone.storage.models import Constat, Dossier, Ecart, Transitaire
from controldone.storage.scope import TenantScope
from controldone.web.listes import Page, Requete, decalage, normaliser, paginer

__all__ = ["page_dossiers", "page_registre", "totaux_registre", "transitaires_registre"]

_EN_CONSTATS = ("ecart_certain", "a_verifier")
_CLES = ("num_facture_transitaire", "ref_transport", "mrn", "num_facture_commerciale")


def _mots(q: str | None) -> list[str]:
    return normaliser(q).split() if q else []


def _contient(expr: Any, mot: str) -> Any:
    return func.lower(func.coalesce(expr, "")).contains(mot, autoescape=True)


def _executer(scope: TenantScope, q: Any) -> list[Any]:
    return list(scope.session.execute(q))


def _compter(scope: TenantScope, q: Any) -> int:
    return int(scope.session.execute(select(func.count()).select_from(q.order_by(None).subquery())).scalar() or 0)


def _page(scope: TenantScope, req: Requete, q: Any, ordre: list[Any]) -> tuple[list[Any], int]:
    total = _compter(scope, q)
    lignes = _executer(scope, q.order_by(*ordre).offset(decalage(req, total)).limit(req.taille))
    return lignes, total


# --- dossiers ------------------------------------------------------------------------------------------------


def page_dossiers(scope: TenantScope, req: Requete) -> tuple[Page, int]:
    """Page de la liste des dossiers : ``(page de DossierLigne, nombre total de dossiers du client)``.

    Mêmes statuts, montants et nombres que ``services.lecture.lister_dossiers`` : agrégats des constats
    visibles de la version courante (sous-requête groupée), statut « client » calculé par ``CASE``."""
    client = scope.actor.est_client
    cs = scope.requete(Constat).subquery("cs")
    certain = ((cs.c.niveau == "ecart_certain") & (cs.c.statut_validation == "valide")
               & (cs.c.nature_montant == "recouvrable") & cs.c.montant_en_jeu.is_not(None)
               & (cast(cs.c.montant_en_jeu, Numeric) > 0)
               & (func.coalesce(cs.c.contenu["hors_totaux"].as_string(), "") == ""))
    agg = (select(cs.c.dossier_id.label("did"), cs.c.dossier_version.label("ver"),
                  func.sum(case((cs.c.statut_validation != "rejete", 1), else_=0)).label("nb"),
                  func.max(case(((cs.c.niveau == "ecart_certain") & (cs.c.statut_validation == "valide"), 1),
                                else_=0)).label("pub_ec"),
                  func.max(case(((cs.c.niveau == "a_verifier") & (cs.c.statut_validation == "valide"), 1),
                                else_=0)).label("pub_av"),
                  func.sum(case((certain, cast(cs.c.montant_en_jeu, Numeric)), else_=0)).label("montant"))
           .group_by(cs.c.dossier_id, cs.c.dossier_version).subquery("agg"))
    nb = func.coalesce(agg.c.nb, 0)
    montant = func.coalesce(agg.c.montant, 0)
    reference = func.coalesce(Dossier.reference, Dossier.id)
    if client:
        en_constats = Dossier.statut_global.in_(_EN_CONSTATS)
        code = case((Dossier.statut_global.is_(None), "en_cours"),
                    (en_constats & (func.coalesce(agg.c.pub_ec, 0) == 1), "ecart_certain"),
                    (en_constats & (func.coalesce(agg.c.pub_av, 0) == 1), "a_verifier"),
                    (en_constats, "en_validation"), else_=Dossier.statut_global)
    else:
        code = func.coalesce(Dossier.statut_global, "en_cours")
    base = scope.requete(Dossier)
    total_client = _compter(scope, base)
    q = (base.with_only_columns(Dossier.id).select_from(Dossier)
         .outerjoin(agg, (agg.c.did == Dossier.id) & (agg.c.ver == Dossier.version)))
    f = req.filtres
    if f.get("statut"):
        q = q.where(code == f["statut"])
    for mot in _mots(f.get("q")):
        q = q.where(or_(_contient(reference, mot),
                        *(_contient(Dossier.contenu[("cles", k)].as_string(), mot) for k in _CLES)))
    cles = {"reference": reference, "date": Dossier.cree_le, "montant": montant, "constats": nb}
    cle = cles[req.tri.lstrip("-")]
    ordre = [cle.desc() if req.tri.startswith("-") else cle.asc(), reference, Dossier.id]
    lignes, total = _page(scope, req, q, ordre)
    ids = [r[0] for r in lignes]
    return paginer(_lignes_dossiers(scope, ids, client=client), req, total=total), total_client


def _lignes_dossiers(scope: TenantScope, ids: list[str], *, client: bool) -> list[DossierLigne]:
    if not ids:
        return []
    dossiers = {r.id: r for r in _executer(scope, scope.requete(Dossier).with_only_columns(
        Dossier.id, Dossier.reference, Dossier.statut_global, Dossier.version, Dossier.lot_id, Dossier.cree_le,
        Dossier.contenu["cles"].label("cles")).where(Dossier.id.in_(ids)))}
    versions = {i: d.version for i, d in dossiers.items()}
    par_dossier: dict[str, list[Constat]] = {}
    for c in scope.session.execute(scope.requete(Constat).where(Constat.dossier_id.in_(ids))).scalars():
        if versions.get(c.dossier_id) == c.dossier_version:
            par_dossier.setdefault(c.dossier_id, []).append(c)
    out = []
    for i in ids:
        d = dossiers.get(i)
        if d is None:
            continue
        vue = SimpleNamespace(id=d.id, reference=d.reference, statut_global=d.statut_global, version=d.version,
                              lot_id=d.lot_id, cree_le=d.cree_le, contenu={"cles": d.cles or {}})
        out.append(ligne_dossier(vue, par_dossier.get(i, []), client=client))
    return out


# --- suivi des avoirs ----------------------------------------------------------------------------------------


def _visibles(scope: TenantScope) -> Any:
    return scope.requete(Ecart).where(Ecart.constat_id.in_(scope.requete(Constat).with_only_columns(Constat.id)))


def transitaires_registre(scope: TenantScope) -> dict[str, str]:
    """Transitaires des écarts visibles (liste fermée du filtre) : ``{id: nom}``."""
    noms = {t.id: t.nom for t in scope.lister(Transitaire)}
    ids = scope.session.execute(_visibles(scope).with_only_columns(Ecart.transitaire_id).distinct()).scalars()
    return {i: noms.get(i, i) for i in ids if i}


def totaux_registre(scope: TenantScope) -> tuple[dict[str, Decimal], int]:
    """Totaux du suivi (tous les écarts visibles), calculés en ``Decimal`` sur une lecture en colonnes."""
    t = {"initial": Decimal(0), "credite": Decimal(0), "reste": Decimal(0)}
    n = 0
    q = _visibles(scope).with_only_columns(Ecart.montant_initial, Ecart.reste, Ecart.statut,
                                           Ecart.contenu["montant_credite"].as_string())
    for initial, reste, statut, credite in scope.session.execute(q):
        n += 1
        t["initial"] += initial or Decimal(0)
        t["credite"] += Decimal(str(credite or "0"))
        if statut not in ("credite", "abandonne"):
            t["reste"] += reste or Decimal(0)
    return t, n


def page_registre(scope: TenantScope, req: Requete, transitaires: dict[str, str]) -> Page:
    """Page du suivi des avoirs (mêmes lignes que ``services.reclamations.registre``)."""
    f = req.filtres
    dossier_id = Ecart.contenu["dossier_id"].as_string()
    q = _visibles(scope).with_only_columns(Ecart.id)
    if f.get("statut"):
        q = q.where(Ecart.statut == f["statut"])
    if f.get("transitaire"):
        q = q.where(Ecart.transitaire_id == f["transitaire"])
    for mot in _mots(f.get("q")):
        composantes = [c.value for c in Composante
                       if mot in normaliser(LIBELLES_COMPOSANTE.get(c, c.value))]
        ids_transitaires = [i for i, nom in transitaires.items() if mot in normaliser(nom)]
        refs = scope.requete(Dossier).with_only_columns(Dossier.id).where(
            _contient(func.coalesce(Dossier.reference, Dossier.id), mot))
        conds = [dossier_id.in_(refs), _contient(Ecart.contenu["mrn"].as_string(), mot),
                 Ecart.contenu["composante"].as_string().in_(composantes),
                 Ecart.transitaire_id.in_(ids_transitaires)]
        if mot in normaliser("transitaire non identifié"):
            conds.append(Ecart.transitaire_id.is_(None))
        q = q.where(or_(*conds))
    reference = (scope.requete(Dossier).with_only_columns(func.coalesce(Dossier.reference, Dossier.id))
                 .where(Dossier.id == dossier_id).scalar_subquery())
    reclame = Ecart.contenu["reclame_le"].as_string()
    cles = {"reste": cast(Ecart.reste, Numeric), "montant": cast(Ecart.montant_initial, Numeric),
            "dossier": reference, "age": reclame}
    nom = req.tri.lstrip("-")
    desc = req.tri.startswith("-")
    cle = cles[nom]
    if nom == "age":  # âge décroissant = envoi le plus ancien d'abord
        desc = not desc
    ordre = [cle.is_(None), cle.desc() if desc else cle.asc(), Ecart.modifie_le, Ecart.id]
    lignes, total = _page(scope, req, q, ordre)
    elements: list[LigneRegistre] = registre(scope, ecart_ids=[r[0] for r in lignes])
    return paginer(elements, req, total=total)
