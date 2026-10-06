"""Paramètres et filtres de chaque liste de l'interface (D-3401) : dossiers, file de validation, suivi des avoirs,
journal d'audit, tâches. Les listes fermées (statuts, contrôles, clients, transitaires) sont construites à partir
des données **déjà lues dans le périmètre** de l'acteur : un identifiant d'un autre client n'y figure jamais et
est donc refusé comme une valeur inconnue."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from controldone.controls.specs import ORDRE_CONTROLES, get_spec
from controldone.web.i18n import N_
from controldone.web.listes import Param, Requete, contient, montant_dans, trier

__all__ = [
    "ALERTES_GRAVES",
    "alerte_du_bandeau",
    "FAMILLES",
    "LIBELLES_ALERTES",
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
    "libelle_alerte",
    "params_jobs",
    "params_journal",
    "params_registre",
    "params_validation",
]

#: Familles de contrôles (SPEC §9 à §16).
FAMILLES = {
    "P": N_("Préalables"), "A": N_("Facture commerciale / déclaration"), "B": N_("Cohérence de la déclaration"),
    "C": N_("Facture du transitaire / déclaration"), "D": N_("Facture du transitaire / grille"), "E": N_("Avoirs"),
    "F": N_("Doublons entre dossiers"), "G": N_("Petits envois"),
}

# --- dossiers ------------------------------------------------------------------------------------------------

STATUTS_DOSSIER = {
    "ecart_certain": N_("Écart certain"), "a_verifier": N_("À vérifier"), "en_validation": N_("En cours de validation"),
    "document_manquant": N_("Document manquant"), "conforme": N_("Conforme"), "non_concerne": N_("Non concerné"),
    "en_cours": N_("En cours"),
}
PARAMS_DOSSIERS = {"q": Param(N_("Recherche")), "statut": Param(N_("Statut"), "choix", tuple(STATUTS_DOSSIER))}
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

NIVEAUX_VALIDATION = {"ecart_certain": N_("Écart certain"), "a_verifier": N_("À vérifier"), "renvoi": N_("Renvoi (professionnel)")}
TRIS_VALIDATION = ("priorite", "-montant", "montant", "client")


def params_validation(clients: dict[str, str]) -> dict[str, Param]:
    return {
        "client": Param(N_("Client"), "choix", tuple(clients)),
        "controle": Param(N_("Contrôle"), "choix", tuple(ORDRE_CONTROLES)),
        "niveau": Param(N_("Niveau"), "choix", tuple(NIVEAUX_VALIDATION)),
        "min": Param(N_("Montant minimal"), "montant"),
        "max": Param(N_("Montant maximal"), "montant"),
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


# --- alertes (fondateur) -----------------------------------------------------------------------------------------

#: Libellé de chaque type d'alerte (``storage.alertes.emettre_alerte``, ``TenantScope.signaler_alerte``, agents,
#: sauvegardes, facturation). Un type absent est affiché sous son nom technique ; un test vérifie que chaque type
#: émis dans le code a son libellé (D-3806).
LIBELLES_ALERTES = {
    "job_mort": N_("Tâche morte"), "cout_ia_alerte": N_("Coût IA 80 %"), "cout_ia_plafond": N_("Plafond IA atteint"),
    "sauvegarde_echec": N_("Sauvegarde en échec"), "sauvegarde_verification_echec": N_("Sauvegarde non conforme"),
    "sauvegarde_absente": N_("Aucune sauvegarde récente"),
    "sauvegarde_hors_site_echec": N_("Copie hors site en échec"),
    "volume_non_chiffre": N_("Volume de la base non chiffré"), "courriel_quarantaine": N_("Courriel en quarantaine"),
    "facture_conflit": N_("Conflit de facturation"), "paiement_echoue": N_("Paiement échoué"),
    "avoir_reliquat": N_("Reliquat d'avoir à affecter"), "revue_extraction": N_("Extraction à revoir"),
    "litige_inactif": N_("Écart sans suite"), "litige_a_preparer": N_("Relevé d'écarts à préparer"),
    "litige_a_valider": N_("Suivi d'écart à valider"), "litige_a_clore": N_("Suivi d'écart à clore"),
    "question_client_instruction": N_("Question client à instruire"), "essai": N_("Essai de notification"),
}
#: Gravité affichée (classe du badge) : sauvegarde, chiffrement, tâche morte, paiement = action requise.
ALERTES_GRAVES = frozenset({"job_mort", "cout_ia_plafond", "sauvegarde_echec", "sauvegarde_verification_echec",
                            "sauvegarde_absente", "sauvegarde_hors_site_echec", "volume_non_chiffre",
                            "paiement_echoue"})


#: Alertes affichées en bandeau sur le tableau de bord du fondateur tant qu'elles ne sont pas lues (bloc I3) :
#: sauvegardes (tout type ``sauvegarde_*``), volume non chiffré, plafond IA atteint, tâche morte.
ALERTES_BANDEAU = frozenset({"volume_non_chiffre", "cout_ia_plafond", "job_mort"})


def alerte_du_bandeau(kind: str) -> bool:
    return kind.startswith("sauvegarde_") or kind in ALERTES_BANDEAU


def libelle_alerte(kind: str) -> str:
    """Libellé français d'un type d'alerte (à traduire à l'affichage) ; repli : libellé des notifications, puis
    nom technique."""
    if kind in LIBELLES_ALERTES:
        return LIBELLES_ALERTES[kind]
    from controldone.services.notifications import LIBELLES

    return LIBELLES.get(kind, kind)


# --- suivi des avoirs (client) -----------------------------------------------------------------------------------

STATUTS_ECART = {
    "ouvert": N_("Ouvert"), "reclame": N_("Courrier envoyé"), "partiellement_credite": N_("Partiellement crédité"),
    "credite": N_("Crédité"), "conteste": N_("Contesté"), "abandonne": N_("Abandonné"),
}
TRIS_REGISTRE = ("-reste", "reste", "-montant", "montant", "dossier", "-dossier", "-age", "age")


def params_registre(transitaires: dict[str, str]) -> dict[str, Param]:
    return {"q": Param(N_("Recherche")), "statut": Param(N_("Statut"), "choix", tuple(STATUTS_ECART)),
            "transitaire": Param(N_("Transitaire"), "choix", tuple(transitaires))}


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
    return {"acteur": Param(N_("Acteur")), "action": Param(N_("Action"), "choix", tuple(actions)),
            "client": Param(N_("Client"), "choix", tuple(clients)), "du": Param(N_("Du"), "date"), "au": Param(N_("Au"), "date")}


STATUTS_JOB = {"pending": N_("En attente"), "running": N_("En cours"), "done": N_("Terminée"), "dead": N_("Morte")}
TRIS_JOBS = ("-cree", "cree")


def params_jobs(kinds: Iterable[str], clients: Iterable[str]) -> dict[str, Param]:
    return {"statut": Param(N_("Statut"), "choix", tuple(STATUTS_JOB)), "kind": Param(N_("Type"), "choix", tuple(kinds)),
            "client": Param(N_("Client"), "choix", tuple(clients))}


def somme(valeurs: Iterable[Decimal | None]) -> Decimal:
    return sum((v for v in valeurs if v is not None), Decimal(0))
