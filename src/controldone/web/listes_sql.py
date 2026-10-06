"""Listes filtrées, triées et paginées **en SQL** (D-3801) : dossiers et suivi des avoirs d'un client.

Les requêtes sont dans ``storage/listes_sql.py`` (cloisonnement ``TenantScope``, paramètres liés) ; ce module
prépare les filtres validés par ``web.listes.lire_requete`` et met en forme la seule page affichée, avec les mêmes
règles que les listes complètes (``services.lecture.ligne_dossier``, ``services.reclamations.registre``).

Recherche : chaque mot (minuscules, sans accents) doit figurer dans l'un des champs ; références et clés comparées
en minuscules en base, libellés (composante, transitaire) rapprochés ici sur leurs listes fermées.
"""

from __future__ import annotations

from decimal import Decimal

from controldone.model.enums import Composante
from controldone.rapport.vue import LIBELLES_COMPOSANTE
from controldone.services.lecture import ligne_dossier
from controldone.services.reclamations import registre
from controldone.storage import listes_sql as requetes
from controldone.storage.scope import TenantScope
from controldone.web.listes import Page, Requete, normaliser, paginer

__all__ = ["page_dossiers", "page_registre", "totaux_registre", "transitaires_registre"]


def _mots(q: str | None) -> list[str]:
    return normaliser(q).split() if q else []


def page_dossiers(scope: TenantScope, req: Requete) -> tuple[Page, int]:
    """Page de la liste des dossiers : ``(page de DossierLigne, nombre total de dossiers du client)``."""
    f = req.filtres
    ids, total, total_client = requetes.dossiers_page(scope, statut=f.get("statut"), mots=_mots(f.get("q")),
                                                      tri=req.tri, page=req.page, taille=req.taille)
    client = scope.actor.est_client
    lignes = [ligne_dossier(d, cs, client=client) for d, cs in requetes.lignes_dossiers(scope, ids)]
    return paginer(lignes, req, total=total), total_client


def transitaires_registre(scope: TenantScope) -> dict[str, str]:
    """Transitaires des écarts visibles (liste fermée du filtre) : ``{id: nom}``."""
    return requetes.transitaires_ecarts(scope)


def totaux_registre(scope: TenantScope) -> tuple[dict[str, Decimal], int]:
    """Totaux du suivi (tous les écarts visibles), en ``Decimal``, et nombre d'écarts."""
    return requetes.totaux_ecarts(scope)


def page_registre(scope: TenantScope, req: Requete, transitaires: dict[str, str]) -> Page:
    """Page du suivi des avoirs (mêmes lignes que ``services.reclamations.registre``)."""
    f = req.filtres
    mots = []
    for mot in _mots(f.get("q")):
        composantes = [c.value for c in Composante if mot in normaliser(LIBELLES_COMPOSANTE.get(c, c.value))]
        ids_transitaires = [i for i, nom in transitaires.items() if mot in normaliser(nom)]
        mots.append((mot, composantes, ids_transitaires, mot in normaliser("transitaire non identifié")))
    ids, total = requetes.ecarts_page(scope, statut=f.get("statut"), transitaire=f.get("transitaire"), mots=mots,
                                      tri=req.tri, page=req.page, taille=req.taille)
    return paginer(registre(scope, ecart_ids=ids), req, total=total)
