"""Paramètres et filtres de chaque liste de l'interface (D-3401) : dossiers, file de validation, suivi des avoirs,
journal d'audit, tâches. Les listes fermées (statuts, contrôles, clients, transitaires) sont construites à partir
des données **déjà lues dans le périmètre** de l'acteur : un identifiant d'un autre client n'y figure jamais et
est donc refusé comme une valeur inconnue."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from controldone.controls.specs import ORDRE_CONTROLES, get_spec
from controldone.web.listes import Param, Requete, contient, montant_dans, trier

__all__ = [
    "FAMILLES",
    "NIVEAUX_VALIDATION",
    "PARAMS_DOSSIERS",
    "STATUTS_DOSSIER",
    "STATUTS_ECART",
    "STATUTS_JOB",
    "TRIS_DOSSIERS",
    "TRIS_JOBS",
    "TRIS_JOURNAL",
    "TRIS_REGISTRE",
    "TRIS_VALIDATION",
    "filtrer_dossiers",
    "filtrer_registre",
    "filtrer_validation",
    "params_jobs",
    "params_journal",
    "params_registre",
    "params_validation",
]

#: Familles de contrôles (SPEC §9 à §16).
FAMILLES = {
    "P": "Préalables", "A": "Facture commerciale / déclaration", "B": "Cohérence de la déclaration",
    "C": "Facture du transitaire / déclaration", "D": "Facture du transitaire / grille", "E": "Avoirs",
    "F": "Doublons entre dossiers", "G": "Petits envois",
}

# --- dossiers ------------------------------------------------------------------------------------------------

STATUTS_DOSSIER = {
    "ecart_certain": "Écart certain", "a_verifier": "À vérifier", "en_validation": "En cours de validation",
    "document_manquant": "Document manquant", "conforme": "Conforme", "non_concerne": "Non concerné",
    "en_cours": "En cours",
}
PARAMS_DOSSIERS = {"q": Param("Recherche"), "statut": Param("Statut", "choix", tuple(STATUTS_DOSSIER))}
TRIS_DOSSIERS = ("reference", "-reference", "date", "-date", "montant", "-montant", "constats", "-constats")


def filtrer_dossiers(lignes: Iterable[Any], req: Requete) -> list[Any]:
    """Recherche sur la référence et les clés (facture du transitaire, transport, MRN, facture commerciale)."""
    f = req.filtres
    out = [d for d in lignes
           if contient(f.get("q"), d.reference, *(v for _l, v in d.cles))
           and (not f.get("statut") or d.statut_code == f["statut"])]
    return trier(out, req.tri, {"reference": lambda d: d.reference, "date": lambda d: d.cree_le,
                                "montant": lambda d: d.recouvrable_certain, "constats": lambda d: d.nb_constats})


# --- file de validation (fondateur) ----------------------------------------------------------------------------

NIVEAUX_VALIDATION = {"ecart_certain": "Écart certain", "a_verifier": "À vérifier", "renvoi": "Renvoi (professionnel)"}
TRIS_VALIDATION = ("priorite", "-montant", "montant", "client")


def params_validation(clients: dict[str, str]) -> dict[str, Param]:
    return {
        "client": Param("Client", "choix", tuple(clients)),
        "controle": Param("Contrôle", "choix", tuple(ORDRE_CONTROLES)),
        "niveau": Param("Niveau", "choix", tuple(NIVEAUX_VALIDATION)),
        "min": Param("Montant minimal", "montant"),
        "max": Param("Montant maximal", "montant"),
    }


def libelles_controles() -> list[tuple[str, str]]:
    return [(c, f"{c} — {get_spec(c).libelle}") for c in ORDRE_CONTROLES]


def filtrer_validation(items: list[dict[str, Any]], req: Requete) -> list[dict[str, Any]]:
    """``items`` : déjà triés par priorité (§7.7). Filtres : client, contrôle, niveau, fourchette de montant."""
    f = req.filtres

    def garde(it: dict[str, Any]) -> bool:
        c = it["c"]
        niveau = "renvoi" if c.renvoi else c.niveau_code
        return ((not f.get("client") or it["tenant_id"] == f["client"])
                and (not f.get("controle") or c.controle_id == f["controle"])
                and (not f.get("niveau") or niveau == f["niveau"])
                and montant_dans(c.montant_valeur, f.get("min"), f.get("max")))

    out = [it for it in items if garde(it)]
    if req.tri == "priorite":
        return out
    if req.tri == "client":
        return sorted(out, key=lambda it: (it["client"].casefold(), it["dossier"]))
    return trier(out, req.tri, {"montant": lambda it: it["c"].montant_valeur})


# --- suivi des avoirs (client) -----------------------------------------------------------------------------------

STATUTS_ECART = {
    "ouvert": "Ouvert", "reclame": "Courrier envoyé", "partiellement_credite": "Partiellement crédité",
    "credite": "Crédité", "conteste": "Contesté", "abandonne": "Abandonné",
}
TRIS_REGISTRE = ("-reste", "reste", "-montant", "montant", "dossier", "-dossier", "-age", "age")


def params_registre(transitaires: dict[str, str]) -> dict[str, Param]:
    return {"q": Param("Recherche"), "statut": Param("Statut", "choix", tuple(STATUTS_ECART)),
            "transitaire": Param("Transitaire", "choix", tuple(transitaires))}


def filtrer_registre(lignes: Iterable[Any], req: Requete) -> list[Any]:
    f = req.filtres
    out = [x for x in lignes
           if contient(f.get("q"), x.dossier_reference, x.mrn, x.composante, x.transitaire)
           and (not f.get("statut") or x.statut_code == f["statut"])
           and (not f.get("transitaire") or x.transitaire_id == f["transitaire"])]
    return trier(out, req.tri, {"reste": lambda x: x.reste, "montant": lambda x: x.montant_initial,
                                "dossier": lambda x: x.dossier_reference, "age": lambda x: x.age_jours})


# --- journal d'audit et tâches (fondateur) : filtres appliqués en SQL (ORM, paramètres liés) ---------------------

TRIS_JOURNAL = ("-id", "id")


def params_journal(actions: Iterable[str], clients: Iterable[str]) -> dict[str, Param]:
    return {"acteur": Param("Acteur"), "action": Param("Action", "choix", tuple(actions)),
            "client": Param("Client", "choix", tuple(clients)), "du": Param("Du", "date"), "au": Param("Au", "date")}


STATUTS_JOB = {"pending": "En attente", "running": "En cours", "done": "Terminée", "dead": "Morte"}
TRIS_JOBS = ("-cree", "cree")


def params_jobs(kinds: Iterable[str], clients: Iterable[str]) -> dict[str, Param]:
    return {"statut": Param("Statut", "choix", tuple(STATUTS_JOB)), "kind": Param("Type", "choix", tuple(kinds)),
            "client": Param("Client", "choix", tuple(clients))}


def somme(valeurs: Iterable[Decimal | None]) -> Decimal:
    return sum((v for v in valeurs if v is not None), Decimal(0))
