"""Intégration d'un dépôt relevé par un connecteur : réception (§7.1, §20.3), coffre chiffré, lot, job.

- Idempotence : un fichier déjà reçu par ce client (même sha256) n'est pas retraité (§7.1) ; un dépôt qui
  ne contient que des fichiers déjà reçus ne crée **aucun** lot ; un courriel déjà intégré (même
  ``Message-ID``) est ignoré.
- Boîte dédiée : expéditeur hors ``reglages["expediteurs_autorises"]`` -> quarantaine (aucun fichier
  traité) et alerte au fondateur (domaine de l'expéditeur seulement) ; le corps du message est stocké
  comme donnée (``document_support/courriel``), jamais interprété.
- Le traitement est mis en file (``traiter_lot``, clé ``traiter_lot:<client>:<lot>``) ; un dépôt d'une
  plateforme agréée y ajoute ``controle_avant_paiement``.
"""

from __future__ import annotations

import hashlib
from email.utils import parseaddr
from typing import Any

from controldone.auth.roles import Acteur
from controldone.ingest.reception import recevoir_courriel, recevoir_octets
from controldone.model.enums import CanalLot, StatutFichier
from controldone.storage.db import Database
from controldone.storage.models import Lot

from .base import Depot, ResultatDepot

__all__ = ["integrer_depot"]


def _deja_integre(lots: list[Lot], message_id: str | None, reference: str | None, source: str) -> bool:
    for lot in lots:
        r = lot.resume or {}
        if message_id and r.get("message_id") == message_id:
            return True
        if reference and r.get("source") == source and r.get("reference") == reference and source != "dossier_surveille":
            return True
    return False


def integrer_depot(db: Database, vault: Any, depot: Depot) -> ResultatDepot:
    tenant = depot.tenant_id
    acteur = Acteur.systeme(f"connecteur:{depot.source}")
    with db.tenant(tenant, acteur, lecture=True) as sc:
        deja = sc.empreintes_fichiers()  # deux colonnes, pas les lignes entières (F-15)
        reglages = sc.client().reglages or {}
        if _deja_integre(sc.lister(Lot), depot.message_id, depot.reference, depot.source):
            return ResultatDepot("deja_recu", motif="message_ou_reference_deja_integre")
    if depot.courriel is not None:
        reception = recevoir_courriel(depot.courriel, expediteurs_autorises=reglages.get("expediteurs_autorises", []),
                                      deja_recus=deja)
        if reception.quarantaine:
            expediteur = parseaddr(reception.lot.expediteur or "")[1]
            domaine = expediteur.rsplit("@", 1)[1] if "@" in expediteur else "inconnu"
            empreinte = hashlib.sha256((depot.message_id or "").encode() or depot.courriel).hexdigest()[:16]
            with db.tenant(tenant, acteur) as sc:
                sc.signaler_alerte(cle=f"quarantaine:{empreinte}", kind="courriel_quarantaine",
                                   message=f"Courriel d'un expéditeur non autorisé (domaine {domaine}) mis en "
                                           "quarantaine sur la boîte dédiée : rien n'a été traité.",
                                   details={"domaine": domaine, "message_sha": empreinte})
            return ResultatDepot("quarantaine", motif=reception.motif_quarantaine)
    else:
        reception = recevoir_octets(depot.elements, client_id=tenant, canal=CanalLot(depot.canal), deja_recus=deja)
    nouveaux = [f for f in reception.fichiers if f.fichier.doublon_de is None]
    doublons = len(reception.fichiers) - len(nouveaux)
    if not nouveaux:
        return ResultatDepot("deja_recu" if doublons else "vide", doublons=doublons)
    lot_id = reception.lot.id
    # Contenus chiffrés dans le coffre **avant** la transaction d'écriture (le verrou SQLite reste court,
    # F-04) ; retirés si l'enregistrement échoue.
    refs: list[str | None] = []
    nouveaux_blobs: list[str] = []
    for f in reception.fichiers:
        ref = None
        if f.a_traiter and f.contenu is not None:
            existait = vault.existe(tenant, f.fichier.sha256)
            ref = vault.deposer(tenant, f.contenu)
            if not existait:
                nouveaux_blobs.append(ref)
            f.contenu = None
        refs.append(ref)
    res = ResultatDepot("lot_cree", lot_id=lot_id, fichiers=sum(1 for r in refs if r is not None),
                        doublons=doublons, refuses=sum(1 for f in nouveaux if f.fichier.statut is StatutFichier.refuse))
    try:
        with db.tenant(tenant, acteur) as sc:
            lot = sc.creer_lot(lot_id, canal=CanalLot(depot.canal).value, expediteur=reception.lot.expediteur)
            lot.resume = {"source": depot.source, "reference": depot.reference, "message_id": depot.message_id,
                          **{k: v for k, v in depot.meta.items() if k in ("facture_pa_id", "controle_avant_paiement")}}
            for f, ref in zip(reception.fichiers, refs, strict=True):
                sc.enregistrer_fichier(f.fichier, lot_id=lot_id, coffre_ref=ref)
            sc.flush()
            # jobs mis en file dans la même transaction que le lot (D-1306)
            if res.fichiers:
                res.jobs.append(sc.mettre_en_file("traiter_lot", {"lot_id": lot_id}, f"traiter_lot:{tenant}:{lot_id}"))
            pa_id = depot.meta.get("facture_pa_id")
            if pa_id and depot.meta.get("controle_avant_paiement") and res.fichiers:
                payload = {"lot_id": lot_id, "facture_pa_id": pa_id,
                           **{k: str(depot.meta[k]) for k in ("numero", "date_echeance") if depot.meta.get(k)}}
                res.jobs.append(sc.mettre_en_file("controle_avant_paiement", payload,
                                                  f"controle_avant_paiement:{tenant}:{pa_id}"))
    except BaseException:
        try:
            with db.tenant(tenant, acteur, lecture=True) as sc:
                encore = sc.contenus_references(nouveaux_blobs)
            for sha in nouveaux_blobs:
                if sha not in encore:
                    vault.supprimer(tenant, sha)
        except Exception:  # pragma: no cover - nettoyage au mieux
            pass
        raise
    return res
