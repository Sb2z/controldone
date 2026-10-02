"""Collecte des données validées pour le référentiel (lecture seule, client par client).

- Clients : actifs, **hors** ceux qui ont exercé l'opt-out contractuel (``reglages["referentiel_opt_out"]``).
- Dossiers retenus : ceux dont aucun constat n'attend encore la décision du fondateur (statut ``propose``)
  — c'est-à-dire des données **validées**.
- Lus : pays d'origine (lignes de facture commerciale, à défaut articles de déclaration), Incoterm, régime
  de déclaration (H1/H7), mois (date d'acceptation de la déclaration), transitaire (nom et TVA, anonymisés
  ensuite), montants HT des prestations de la facture du transitaire par nature, et présence d'un écart
  certain validé.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from controldone.auth.roles import Acteur
from controldone.storage.clients import clients_actifs
from controldone.storage.db import Database
from controldone.storage.models import Constat, Document, Transitaire
from controldone.storage.models import Dossier as DossierRow

from .calcul import EnregistrementFlux

__all__ = ["NATURES_PRIX", "collecter", "opt_out"]

#: Prestations du transitaire dont le prix est agrégé (les débours ne sont pas des prix).
NATURES_PRIX = ("frais_dedouanement", "frais_avance_fonds", "frais_ligne_supplementaire", "magasinage", "transport",
                "manutention", "surcharge")
ACTEUR = Acteur.systeme("referentiel")


def opt_out(reglages: dict[str, Any] | None) -> bool:
    return bool((reglages or {}).get("referentiel_opt_out"))


def _val(champ: Any) -> str | None:
    return champ.get("valeur") if isinstance(champ, dict) else None


def _dec(champ: Any) -> Decimal | None:
    v = _val(champ)
    try:
        return Decimal(v) if v not in (None, "") else None
    except InvalidOperation:
        return None


def _enregistrement(tenant: str, dossier: DossierRow, docs: list[Document], tra: Transitaire | None,
                    constats: list[Constat]) -> EnregistrementFlux | None:
    par_type: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        par_type.setdefault(d.type, []).append(d.contenu or {})
    fc = (par_type.get("facture_commerciale") or [{}])[0]
    dec = (par_type.get("declaration") or [{}])[0]
    champs_fc, champs_dec = fc.get("champs") or {}, dec.get("champs") or {}
    pays = Counter(_val(x.get("pays_origine")) for x in champs_fc.get("lignes") or [] if _val(x.get("pays_origine")))
    if not pays:
        pays = Counter(_val(x.get("pays_origine")) for x in champs_dec.get("articles") or []
                       if _val(x.get("pays_origine")))
    mois = (_val(champs_dec.get("date_acceptation")) or "")[:7] or dossier.cree_le.strftime("%Y-%m")
    prix: dict[str, Decimal] = {}
    for ft in par_type.get("facture_transitaire") or []:
        for ligne in (ft.get("champs") or {}).get("lignes") or []:
            nature = ligne.get("nature")
            montant = _dec(ligne.get("montant_ht"))
            if nature in NATURES_PRIX and montant is not None:
                prix[nature] = prix.get(nature, Decimal("0.00")) + montant
    if tra is None:
        return None
    return EnregistrementFlux(
        client_id=tenant, transitaire_nom=tra.nom, transitaire_tva=tra.tva,
        pays_origine=pays.most_common(1)[0][0] if pays else None,
        incoterm=_val(champs_fc.get("incoterm")) or _val(champs_dec.get("incoterm")),
        sous_type_declaration=dec.get("sous_type"), mois=mois,
        avec_ecart=any(c.niveau == "ecart_certain" and c.statut_validation in ("valide", "modifie") for c in constats),
        prix=prix,
    )


def collecter(db: Database) -> tuple[list[EnregistrementFlux], dict[str, int]]:
    """Enregistrements de tous les clients participants, et compteurs (clients exclus, dossiers retenus)."""
    sortie: list[EnregistrementFlux] = []
    stats = {"clients": 0, "clients_opt_out": 0, "dossiers": 0, "dossiers_non_valides": 0}
    for tenant in clients_actifs(db):
        with db.tenant(tenant, ACTEUR, lecture=True) as sc:
            if opt_out(sc.client().reglages):
                stats["clients_opt_out"] += 1
                continue
            stats["clients"] += 1
            transitaires = {t.id: t for t in sc.lister(Transitaire)}
            constats: dict[str, list[Constat]] = {}
            for c in sc.lister(Constat):
                constats.setdefault(c.dossier_id, []).append(c)
            docs: dict[str, list[Document]] = {}
            for d in sc.lister(Document, ordre=Document.id):
                if d.dossier_id:
                    docs.setdefault(d.dossier_id, []).append(d)
            for dossier in sc.lister(DossierRow, ordre=DossierRow.id):
                cs = constats.get(dossier.id, [])
                if any(c.statut_validation == "propose" for c in cs):
                    stats["dossiers_non_valides"] += 1
                    continue
                tra_id = (dossier.contenu or {}).get("transitaire_id")
                e = _enregistrement(tenant, dossier, docs.get(dossier.id, []), transitaires.get(tra_id), cs)
                if e is not None:
                    sortie.append(e)
                    stats["dossiers"] += 1
    return sortie, stats
