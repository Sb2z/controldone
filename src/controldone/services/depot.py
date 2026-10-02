"""Dépôt de fichiers (interface web, API, MCP) : SPEC §7.1, §20.3.

1. Lecture **bornée** de chaque fichier transmis (``lire_borne`` : on n'accumule jamais plus que la limite
   par fichier ; au-delà, le fichier est refusé « trop volumineux » sans être conservé) ;
2. ``ingest.reception.recevoir_octets`` : type détecté par les octets, archives ZIP contrôlées (chemins
   absolus et ``..`` refusés, liens symboliques, profondeur, nombre d'entrées, taux de compression,
   taille décompressée), doublons de fichier ;
3. enregistrement dans le **périmètre du client de l'acteur** (``TenantScope``) : lot, métadonnées des
   fichiers, contenus chiffrés dans le coffre ;
4. mise en file du job ``traiter_lot`` (clé d'idempotence ``traiter_lot:<client>:<lot>``).

Aucun fichier déposé n'est jamais rendu comme une page HTML par l'application.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from controldone.auth.roles import Acteur, Action
from controldone.ids import Prefixe, nouvel_id
from controldone.ingest.reception import recevoir_octets
from controldone.model.documents import Fichier as FichierModele
from controldone.model.enums import CanalLot, StatutFichier
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide, exiger
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import Fichier, Lot
from controldone.storage.scope import TenantScope

__all__ = ["FichierTransmis", "ResultatDepot", "deposer", "lire_borne", "mettre_en_file"]

LIBELLES_REFUS = {
    "protege": "fichier protégé par mot de passe",
    "corrompu": "fichier corrompu ou illisible",
    "vide": "fichier vide",
    "non_supporte": "type de fichier non pris en charge",
    "trop_gros": "fichier trop volumineux (50 Mo par fichier, 500 Mo par dépôt, 300 pages)",
    "archive_dangereuse": "archive refusée (structure dangereuse : chemins, liens, profondeur, compression)",
}


@dataclass
class FichierTransmis:
    """Fichier reçu d'un formulaire ou d'une API : nom d'origine et octets (``None`` si au-delà de la
    limite par fichier : il sera refusé sans être conservé)."""

    nom: str
    contenu: bytes | None
    taille: int


@dataclass
class ResultatDepot:
    lot_id: str
    job_id: str | None
    acceptes: int
    doublons: int
    refuses: list[tuple[str, str]] = field(default_factory=list)  # (chemin, motif lisible)

    def en_dict(self) -> dict[str, Any]:
        return {"lot_id": self.lot_id, "job_id": self.job_id, "fichiers_acceptes": self.acceptes,
                "doublons": self.doublons,
                "fichiers_refuses": [{"fichier": c, "motif": m} for c, m in self.refuses]}


def lire_borne(flux: BinaryIO, limite: int, *, bloc: int = 1024 * 1024) -> tuple[bytes | None, int]:
    """Lit au plus ``limite`` octets ; renvoie ``(None, taille_lue)`` si le flux dépasse la limite (le
    surplus n'est pas conservé en mémoire)."""
    morceaux: list[bytes] = []
    lu = 0
    while True:
        b = flux.read(bloc)
        if not b:
            break
        lu += len(b)
        if lu > limite:
            # vider le reste sans le garder (taille seulement)
            while True:
                b = flux.read(bloc)
                if not b:
                    break
                lu += len(b)
            return None, lu
        morceaux.append(b)
    return b"".join(morceaux), lu


def _nom_sur(nom: str) -> str:
    nom = (nom or "fichier").replace("\x00", "").replace("\\", "/").strip()
    parties = [p for p in nom.split("/") if p not in ("", ".", "..")]
    return "/".join(p[:150] for p in parties[-6:]) or "fichier"


def _elements(fichiers: Iterable[FichierTransmis], plateforme: Plateforme,
              refuses: list[tuple[str, str]]) -> Iterator[tuple[str, bytes]]:
    for f in fichiers:
        if f.contenu is None:
            refuses.append((_nom_sur(f.nom), LIBELLES_REFUS["trop_gros"]))
            continue
        yield _nom_sur(f.nom), f.contenu


def deposer(plateforme: Plateforme, acteur: Acteur, fichiers: list[FichierTransmis], *,
            canal: CanalLot = CanalLot.depot, resume: dict[str, Any] | None = None) -> ResultatDepot:
    """Dépose des fichiers pour le client **de l'acteur** (rôle client ``client_admin``) et met le lot en
    file. Le fondateur ne dépose pas pour un client par cette voie."""
    tenant_id = acteur.tenant_id
    if not acteur.est_client or tenant_id is None:
        raise Interdit("dépôt réservé aux comptes client")
    exiger(acteur, Action.deposer, tenant_id)
    if not fichiers:
        raise RequeteInvalide("aucun fichier transmis")
    total = sum(f.taille for f in fichiers)
    if total > plateforme.limites.taille_lot:
        raise RequeteInvalide("dépôt trop volumineux : 500 Mo au plus par dépôt")
    refuses: list[tuple[str, str]] = []
    with plateforme.db.tenant(tenant_id, acteur) as scope:
        resultat = enregistrer_depot(plateforme, scope, list(_elements(fichiers, plateforme, refuses)),
                                     canal=canal, resume=resume, refuses_prealables=refuses)
    if resultat.acceptes:
        resultat.job_id = mettre_en_file(plateforme, tenant_id, resultat.lot_id)
    return resultat


def enregistrer_depot(plateforme: Plateforme, scope: TenantScope, elements: list[tuple[str, bytes]], *,
                      canal: CanalLot = CanalLot.depot, resume: dict[str, Any] | None = None,
                      refuses_prealables: list[tuple[str, str]] | None = None) -> ResultatDepot:
    """Réception + enregistrement dans ``scope`` (lot, fichiers, coffre). Ne met rien en file."""
    tenant_id = scope.tenant_id
    deja = {f.sha256: f.id for f in scope.lister(Fichier, statut="ok") if f.coffre_ref}
    lot_id = nouvel_id(Prefixe.lot)
    reception = recevoir_octets(elements, client_id=tenant_id, canal=canal, deja_recus=deja,
                                limites=plateforme.limites)
    scope.creer_lot(lot_id, canal=canal.value)
    refuses = list(refuses_prealables or [])
    acceptes = doublons = 0
    for recu in reception.fichiers:
        f = recu.fichier.model_copy(update={"lot_id": lot_id})
        ref = None
        if f.statut is StatutFichier.ok and recu.contenu is not None:
            if f.doublon_de is None:
                ref = plateforme.vault.deposer(tenant_id, recu.contenu)
                acceptes += 1
            else:
                doublons += 1
        elif f.statut is StatutFichier.refuse:
            refuses.append((f.chemin_relatif, LIBELLES_REFUS.get(f.motif_refus or "", f.motif_refus or "refusé")))
        scope.enregistrer_fichier(f, lot_id=lot_id, coffre_ref=ref)
    for chemin, motif in refuses_prealables or []:
        # fichier au-delà de la limite : métadonnées seulement (aucun contenu conservé)
        sha = hashlib.sha256(f"refuse:{lot_id}:{chemin}".encode()).hexdigest()
        scope.enregistrer_fichier(FichierModele(client_id=tenant_id, lot_id=lot_id, nom_original=chemin.split("/")[-1],
                                                chemin_relatif=chemin, sha256=sha, taille=0,
                                                type_mime="application/octet-stream", statut=StatutFichier.refuse,
                                                motif_refus="trop_gros"), lot_id=lot_id, coffre_ref=None)
    statut = "recu" if acceptes else "en_erreur"
    scope.modifier(Lot, lot_id, statut=statut,
                   resume={**(resume or {}), "fichiers": acceptes, "doublons": doublons, "refuses": len(refuses)})
    return ResultatDepot(lot_id=lot_id, job_id=None, acceptes=acceptes, doublons=doublons, refuses=refuses)


def mettre_en_file(plateforme: Plateforme, tenant_id: str, lot_id: str) -> str:
    job, _cree = JobStore(plateforme.db).enqueue("traiter_lot", {"lot_id": lot_id},
                                                 f"traiter_lot:{tenant_id}:{lot_id}", tenant_id)
    return job.id
