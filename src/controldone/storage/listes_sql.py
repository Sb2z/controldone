"""Requêtes des listes filtrées, triées et paginées **en SQL** de l'interface (D-3801) : dossiers et écarts d'un
client. La mise en forme des lignes et la pagination affichée restent dans ``web/listes_sql.py``.

Toutes les requêtes partent de ``TenantScope.requete`` (cloisonnement du client ; constats publiés seuls pour un
rôle client). Les filtres, déjà validés par l'interface, sont passés comme **paramètres liés** (sous-chaînes
échappées : ``%`` et ``_`` n'ont pas de sens particulier). Montants stockés en texte exact : tri et comparaison par
``CAST … AS NUMERIC`` en base (clé de tri seulement) ; les montants affichés et les totaux sont recalculés en
``Decimal`` par l'appelant ou ici, jamais en flottant côté Python.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Numeric, case, cast, func, or_, select

from controldone.storage.models import Constat, Dossier, Ecart, NotificationAlerte, Transitaire
from controldone.storage.scope import OperatorScope, TenantScope

__all__ = ["CLES_DOSSIER", "compter_dossiers", "constats_indicateurs", "dossiers_page", "ecarts_page",
           "lignes_dossiers", "notifications_page", "totaux_ecarts", "transitaires_ecarts"]

_EN_CONSTATS = ("ecart_certain", "a_verifier")
CLES_DOSSIER = ("num_facture_transitaire", "ref_transport", "mrn", "num_facture_commerciale")


def _contient(expr: Any, mot: str) -> Any:
    return func.lower(func.coalesce(expr, "")).contains(mot, autoescape=True)


def _compter(scope: TenantScope, q: Any) -> int:
    lignes = scope.executer_lecture(select(func.count()).select_from(q.order_by(None).subquery()))
    return int(lignes[0][0] or 0) if lignes else 0


def _page(scope: TenantScope, q: Any, ordre: list[Any], page: int, taille: int) -> tuple[list[Any], int]:
    """Lignes de la page ``page`` (ramenée à la dernière page existante) et total filtré."""
    total = _compter(scope, q)
    pages = max(1, -(-total // taille))
    decalage = (min(page, pages) - 1) * taille
    return scope.executer_lecture(q.order_by(*ordre).offset(decalage).limit(taille)), total


# --- dossiers ------------------------------------------------------------------------------------------------


def dossiers_page(scope: TenantScope, *, statut: str | None, mots: Sequence[str], tri: str, page: int,
                  taille: int) -> tuple[list[str], int, int]:
    """``(identifiants de la page, total filtré, total des dossiers du client)``.

    Mêmes statuts, montants et nombres que ``services.lecture.lister_dossiers`` : agrégats des constats visibles
    de la version courante (sous-requête groupée), statut « client » calculé par ``CASE``. ``mots`` : mots de
    recherche normalisés (minuscules ASCII), chacun présent dans la référence ou l'une des clés."""
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
    if statut:
        q = q.where(code == statut)
    for mot in mots:
        q = q.where(or_(_contient(reference, mot),
                        *(_contient(Dossier.contenu[("cles", k)].as_string(), mot) for k in CLES_DOSSIER)))
    cles = {"reference": reference, "date": Dossier.cree_le, "montant": montant, "constats": nb}
    cle = cles[tri.lstrip("-")]
    ordre = [cle.desc() if tri.startswith("-") else cle.asc(), reference, Dossier.id]
    lignes, total = _page(scope, q, ordre, page, taille)
    return [r[0] for r in lignes], total, total_client


def compter_dossiers(scope: TenantScope) -> int:
    """Nombre de dossiers du client (``COUNT`` en base)."""
    return _compter(scope, scope.requete(Dossier))


def constats_indicateurs(scope: TenantScope) -> list[Any]:
    """Constats visibles de la **version courante** de leur dossier, lus **colonne par colonne** (jamais le JSON
    ``contenu`` entier) pour les indicateurs et graphiques des tableaux de bord (bloc I3) : ``(controle_id,
    niveau, statut_validation, nature_montant, montant_en_jeu, hors_totaux, dossier.cree_le,
    dossier.transitaire_id)``. Rôle client : constats publiés seuls (``TenantScope.requete``). Montants en
    ``Decimal`` (colonne), additionnés par l'appelant."""
    d = scope.requete(Dossier).subquery("d")
    q = (scope.requete(Constat)
         .with_only_columns(Constat.controle_id, Constat.niveau, Constat.statut_validation, Constat.nature_montant,
                            Constat.montant_en_jeu, Constat.contenu["hors_totaux"].as_string(), d.c.cree_le,
                            d.c.contenu["transitaire_id"].as_string())
         .join(d, (d.c.id == Constat.dossier_id) & (d.c.version == Constat.dossier_version)))
    return scope.executer_lecture(q)


def lignes_dossiers(scope: TenantScope, ids: Sequence[str]) -> list[tuple[Any, list[Constat]]]:
    """Pour chaque identifiant (dans l'ordre) : vue du dossier (colonnes et clés seulement) et ses constats
    visibles de la version courante."""
    if not ids:
        return []
    q = scope.requete(Dossier).with_only_columns(
        Dossier.id, Dossier.reference, Dossier.statut_global, Dossier.version, Dossier.lot_id, Dossier.cree_le,
        Dossier.contenu["cles"].label("cles")).where(Dossier.id.in_(list(ids)))
    dossiers = {r.id: r for r in scope.executer_lecture(q)}
    par_dossier: dict[str, list[Constat]] = {}
    for c in scope.lister_parmi(Constat, "dossier_id", ids):
        d = dossiers.get(c.dossier_id)
        if d is not None and d.version == c.dossier_version:
            par_dossier.setdefault(c.dossier_id, []).append(c)
    out = []
    for i in ids:
        d = dossiers.get(i)
        if d is None:
            continue
        vue = SimpleNamespace(id=d.id, reference=d.reference, statut_global=d.statut_global, version=d.version,
                              lot_id=d.lot_id, cree_le=d.cree_le, contenu={"cles": d.cles or {}})
        out.append((vue, par_dossier.get(i, [])))
    return out


# --- écarts (suivi des avoirs) ---------------------------------------------------------------------------------


def _visibles(scope: TenantScope) -> Any:
    return scope.requete(Ecart).where(Ecart.constat_id.in_(scope.requete(Constat).with_only_columns(Constat.id)))


def transitaires_ecarts(scope: TenantScope) -> dict[str, str]:
    """Transitaires des écarts visibles : ``{id: nom}`` (nom inconnu : l'identifiant)."""
    noms = {t.id: t.nom for t in scope.lister(Transitaire)}
    ids = [r[0] for r in scope.executer_lecture(_visibles(scope).with_only_columns(Ecart.transitaire_id).distinct())]
    return {i: noms.get(i, i) for i in ids if i}


def totaux_ecarts(scope: TenantScope) -> tuple[dict[str, Decimal], int]:
    """Totaux de tous les écarts visibles, en ``Decimal`` sur une lecture en colonnes : ``(totaux, nombre)``."""
    t = {"initial": Decimal(0), "credite": Decimal(0), "reste": Decimal(0)}
    n = 0
    q = _visibles(scope).with_only_columns(Ecart.montant_initial, Ecart.reste, Ecart.statut,
                                           Ecart.contenu["montant_credite"].as_string())
    for initial, reste, statut, credite in scope.executer_lecture(q):
        n += 1
        t["initial"] += initial or Decimal(0)
        t["credite"] += Decimal(str(credite or "0"))
        if statut not in ("credite", "abandonne"):
            t["reste"] += reste or Decimal(0)
    return t, n


def ecarts_page(scope: TenantScope, *, statut: str | None, transitaire: str | None,
                mots: Sequence[tuple[str, Sequence[str], Sequence[str], bool]], tri: str, page: int,
                taille: int) -> tuple[list[str], int]:
    """``(identifiants des écarts de la page, total filtré)``. ``mots`` : pour chaque mot normalisé, les codes de
    composante et les identifiants de transitaire dont le libellé le contient (rapprochés par l'appelant sur ses
    listes fermées), et s'il désigne le transitaire non identifié."""
    dossier_id = Ecart.contenu["dossier_id"].as_string()
    q = _visibles(scope).with_only_columns(Ecart.id)
    if statut:
        q = q.where(Ecart.statut == statut)
    if transitaire:
        q = q.where(Ecart.transitaire_id == transitaire)
    for mot, composantes, ids_transitaires, non_identifie in mots:
        refs = scope.requete(Dossier).with_only_columns(Dossier.id).where(
            _contient(func.coalesce(Dossier.reference, Dossier.id), mot))
        conds = [dossier_id.in_(refs), _contient(Ecart.contenu["mrn"].as_string(), mot),
                 Ecart.contenu["composante"].as_string().in_(list(composantes)),
                 Ecart.transitaire_id.in_(list(ids_transitaires))]
        if non_identifie:
            conds.append(Ecart.transitaire_id.is_(None))
        q = q.where(or_(*conds))
    reference = (scope.requete(Dossier).with_only_columns(func.coalesce(Dossier.reference, Dossier.id))
                 .where(Dossier.id == dossier_id).scalar_subquery())
    cles = {"reste": cast(Ecart.reste, Numeric), "montant": cast(Ecart.montant_initial, Numeric),
            "dossier": reference, "age": Ecart.contenu["reclame_le"].as_string()}
    nom = tri.lstrip("-")
    desc = tri.startswith("-")
    if nom == "age":  # âge décroissant = envoi le plus ancien d'abord
        desc = not desc
    cle = cles[nom]
    ordre = [cle.is_(None), cle.desc() if desc else cle.asc(), Ecart.modifie_le, Ecart.id]
    lignes, total = _page(scope, q, ordre, page, taille)
    return [r[0] for r in lignes], total


# --- historique des notifications poussées (fondateur) -----------------------------------------------------------


def notifications_page(op: OperatorScope, *, decalage: int, limite: int) -> tuple[list[dict[str, Any]], int]:
    """Notifications poussées (``notifications_alertes``, D-3502), plus récentes d'abord : ``(lignes, total)``.
    Aucune donnée client dans cette table (type, nombre, canaux, état, essais, horodatages).

    Interface mince de l'interface (bloc I3) en attendant l'API de lecture du bloc production : seule
    ``web/notifications_vues.py`` l'appelle."""
    total = int(op.session.execute(select(func.count()).select_from(NotificationAlerte)).scalar() or 0)
    q = (select(NotificationAlerte).order_by(NotificationAlerte.cree_le.desc(), NotificationAlerte.id.desc())
         .offset(max(0, decalage)).limit(limite))
    lignes = [{"id": n.id, "kind": n.kind, "nombre": n.nombre, "canaux": [c for c in (n.canaux or "").split(",") if c],
               "statut": n.statut, "essais": n.essais, "cree_le": n.cree_le, "envoyee_le": n.envoyee_le}
              for n in op.session.execute(q).scalars()]
    return lignes, total
