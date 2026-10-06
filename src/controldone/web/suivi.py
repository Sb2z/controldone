"""Suivi en direct du traitement d'un dépôt (D-3402, étapes fines D-3805) : état affiché à partir du lot et de sa
tâche ``traiter_lot``. Étapes : reçu, lecture des pages, classement, extraction, regroupement, contrôles, terminé (ou
erreur). Le worker écrit l'étape courante dans ``jobs.resultat["etape"]`` : ``"<etape> <fait>/<total>"`` pour les
étapes fines du pipeline (``jobs.handlers.relais_progression``, D-3709), ``"lecture"`` (pipeline sans étapes fines)
ou ``"controles"`` (enregistrement des résultats). Aucune donnée de document : statuts, compteurs, références."""

from __future__ import annotations

import re
from typing import Any

from controldone.web.i18n import N_, traduire

__all__ = ["ETAPES", "etat_traitement"]

ETAPES = (("recu", N_("Reçu")), ("pages", N_("Lecture des pages")), ("classement", N_("Classement des documents")),
          ("extraction", N_("Extraction des valeurs")), ("regroupement", N_("Regroupement en dossiers")),
          ("controles", N_("Contrôles")), ("termine", N_("Terminé")))
_RANG = {code: i for i, (code, _l) in enumerate(ETAPES)}
#: Anciennes valeurs (worker sans étapes fines) : « lecture » couvre tout le pipeline.
_ALIAS = {"lecture": "pages"}
_ETAPE = re.compile(r"\A([a-z_]{1,20})(?: (\d{1,7})/(\d{1,7}))?\Z")


def _lire_etape(brut: Any) -> tuple[str, int | None, int | None]:
    m = _ETAPE.match(brut) if isinstance(brut, str) else None
    if m is None:
        return "pages", None, None
    code = _ALIAS.get(m.group(1), m.group(1))
    if code not in _RANG or code in ("recu", "termine"):
        code = "pages"  # valeur inconnue : « lecture » (affichage seulement)
    if m.group(2) is None:
        return code, None, None
    fait, total = int(m.group(2)), int(m.group(3))
    return code, min(fait, total), total


def _pourcentage(rang: int, fait: int | None, total: int | None) -> int:
    """Barre de progression par pas de 5 % (classes CSS ``w-0`` à ``w-100``) : 5 % reçu, 100 % terminé, les
    étapes intermédiaires se partagent l'intervalle, au prorata du compteur quand il est connu."""
    if rang <= 0:
        return 5
    if rang >= len(ETAPES) - 1:
        return 100
    largeur = 90 / (len(ETAPES) - 2)
    part = (fait / total) if fait is not None and total else 0.0
    valeur = 5 + largeur * (rang - 1 + part)
    return max(5, min(95, int(round(valeur / 5) * 5)))


def etat_traitement(lot_statut: str, job: Any, langue: str | None = None) -> dict[str, Any]:
    """``{"etape", "libelle", "rang", "fini", "erreur", "pourcentage", "detail", "fait", "total", "texte"}``.
    ``job`` : ``JobInfo`` ou ``dict`` ``{"statut", "etape", "essais"}`` (``lire_lot``) ou ``None``. Libellés dans
    ``langue`` (défaut : langue courante de la requête)."""
    if isinstance(job, dict):
        statut, etape, essais = job.get("statut"), job.get("etape"), job.get("essais") or 0
    elif job is not None:
        statut, essais = job.statut, job.attempts
        etape = (job.resultat or {}).get("etape") if job.statut == "running" else None
    else:
        statut, etape, essais = None, None, 0
    detail = ""
    fait = total = None
    if lot_statut == "traite":
        code = "termine"
    elif lot_statut == "en_erreur":
        code, detail = "erreur", N_("Aucun fichier exploitable dans ce dépôt.")
    elif statut == "dead":
        code, detail = "erreur", N_("Le traitement a échoué ; le fondateur est alerté.")
    elif statut == "done":
        code = "termine"
    elif statut == "running":
        code, fait, total = _lire_etape(etape)
    else:
        code = "recu"
        if essais:
            detail = N_("Nouvel essai programmé.")
        elif statut == "pending":
            detail = N_("En attente de traitement.")
    if code == "erreur":
        rang, libelle = len(ETAPES) - 1, N_("Erreur")
    else:
        rang, libelle = _RANG[code], dict(ETAPES)[code]
    libelle_t = traduire(libelle, langue)
    detail_t = traduire(detail, langue) if detail else ""
    compteur = traduire("{fait} sur {total}", langue, fait=fait, total=total) if fait is not None else ""
    if code == "erreur":
        texte = (traduire("Traitement en erreur.", langue) + " " + detail_t).strip()
    elif code == "termine":
        texte = traduire("Traitement terminé.", langue)
    else:
        texte = traduire("Étape en cours : {etape}.", langue, etape=libelle_t.lower())
        if compteur:
            texte = traduire("Étape en cours : {etape} ({compteur}).", langue, etape=libelle_t.lower(),
                             compteur=compteur)
        if detail_t:
            texte += " " + detail_t
    return {"etape": code, "libelle": libelle_t, "rang": rang, "fini": code in ("termine", "erreur"),
            "erreur": code == "erreur", "pourcentage": 100 if code == "erreur" else _pourcentage(rang, fait, total),
            "detail": detail_t, "fait": fait, "total": total, "texte": texte}
