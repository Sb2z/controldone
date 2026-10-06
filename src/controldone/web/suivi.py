"""Suivi en direct du traitement d'un dépôt (D-3402) : état affiché à partir du lot et de sa tâche
``traiter_lot``. Les états sont : reçu, lecture, contrôles, terminé ou erreur. Aucune donnée de document :
seulement des statuts, des compteurs et les références des dossiers produits."""

from __future__ import annotations

from typing import Any

__all__ = ["ETAPES", "etat_traitement"]

ETAPES = (("recu", "Reçu"), ("lecture", "Lecture des documents"), ("controles", "Contrôles"),
          ("termine", "Terminé"))
_RANG = {code: i for i, (code, _l) in enumerate(ETAPES)}


def etat_traitement(lot_statut: str, job: Any) -> dict[str, Any]:
    """``{"etape", "libelle", "rang", "fini", "erreur", "pourcentage", "detail"}``. ``job`` : ``JobInfo`` ou
    ``dict`` ``{"statut", "etape", "essais"}`` (``lire_lot``) ou ``None``."""
    if isinstance(job, dict):
        statut, etape, essais = job.get("statut"), job.get("etape"), job.get("essais") or 0
    elif job is not None:
        statut, essais = job.statut, job.attempts
        etape = (job.resultat or {}).get("etape") if job.statut == "running" else None
    else:
        statut, etape, essais = None, None, 0
    detail = ""
    if lot_statut == "traite":
        code = "termine"
    elif lot_statut == "en_erreur":
        code, detail = "erreur", "Aucun fichier exploitable dans ce dépôt."
    elif statut == "dead":
        code, detail = "erreur", "Le traitement a échoué ; le fondateur est alerté."
    elif statut == "done":
        code = "termine"
    elif statut == "running":
        code = etape if etape in ("lecture", "controles") else "lecture"
    else:
        code = "recu"
        if essais:
            detail = "Nouvel essai programmé."
        elif statut == "pending":
            detail = "En attente de traitement."
    if code == "erreur":
        rang, libelle = len(ETAPES) - 1, "Erreur"
    else:
        rang, libelle = _RANG[code], dict(ETAPES)[code]
    return {"etape": code, "libelle": libelle, "rang": rang, "fini": code in ("termine", "erreur"),
            "erreur": code == "erreur", "pourcentage": (5, 35, 65, 100)[rang] if code != "erreur" else 100,
            "detail": detail}
