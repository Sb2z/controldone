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

import gc
import hashlib
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from controldone.auth.roles import Acteur, Action
from controldone.ids import Prefixe, nouvel_id
from controldone.ingest.reception import recevoir_octets
from controldone.model.documents import Fichier as FichierModele
from controldone.model.enums import CanalLot, StatutFichier
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide, exiger
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import Lot
from controldone.storage.scope import TenantScope

__all__ = [
    "DepotPrepare",
    "FichierTransmis",
    "ResultatDepot",
    "deja_recus",
    "deposer",
    "enregistrer_prepare",
    "lire_borne",
    "mettre_en_file",
    "preparer_depot",
]

_ACTEUR_NETTOYAGE = Acteur.systeme("depot")

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
    """Fichier reçu d'un formulaire ou d'une API : nom d'origine et **soit** ses octets (``contenu`` ;
    ``None`` si au-delà de la limite par fichier : il sera refusé sans être conservé), **soit** un flux
    (``flux`` : fichier temporaire du téléversement, lu au moment du traitement, un fichier à la fois)."""

    nom: str
    contenu: bytes | None
    taille: int
    flux: BinaryIO | None = None

    @classmethod
    def depuis_flux(cls, nom: str, flux: BinaryIO, taille: int | None = None) -> FichierTransmis:
        """Téléversement déjà écrit sur disque par le serveur (multipart) : rien n'est lu ici."""
        if taille is None:
            try:
                pos = flux.tell()
                flux.seek(0, 2)
                taille = flux.tell() - pos
                flux.seek(pos)
            except (OSError, AttributeError):
                taille = 0
        return cls(nom=nom, contenu=None, taille=int(taille), flux=flux)

    def lire(self, limite: int) -> bytes | None:
        """Octets du fichier (``None`` s'il dépasse ``limite``)."""
        if self.flux is None:
            return self.contenu
        contenu, _ = lire_borne(self.flux, limite)
        return contenu


@dataclass
class ResultatDepot:
    lot_id: str
    job_id: str | None
    acceptes: int
    doublons: int
    refuses: list[tuple[str, str]] = field(default_factory=list)  # (chemin, motif lisible)

    def en_dict(self) -> dict[str, Any]:
        return {
            "lot_id": self.lot_id,
            "job_id": self.job_id,
            "fichiers_acceptes": self.acceptes,
            "doublons": self.doublons,
            "fichiers_refuses": [{"fichier": c, "motif": m} for c, m in self.refuses],
        }


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


@dataclass
class DepotPrepare:
    """Réception faite **hors transaction** (D-1304) : métadonnées des fichiers et références des contenus
    déjà chiffrés dans le coffre. ``nouveaux_blobs`` : contenus créés par ce dépôt (à retirer si
    l'enregistrement échoue)."""

    lot_id: str
    fichiers: list[tuple[Any, str | None]] = field(default_factory=list)  # (Fichier pydantic, coffre_ref)
    refuses: list[tuple[str, str]] = field(default_factory=list)
    acceptes: int = 0
    doublons: int = 0
    nouveaux_blobs: list[str] = field(default_factory=list)


def deja_recus(scope: TenantScope) -> dict[str, str]:
    """``{sha256: fichier_id}`` des fichiers déjà reçus et conservés (deux colonnes seulement, F-15)."""
    return scope.empreintes_fichiers()


def _limites_restantes(limites: Any, consomme: int) -> Any:
    from dataclasses import replace

    return replace(limites, taille_lot=max(0, limites.taille_lot - consomme))


def preparer_depot(
    plateforme: Plateforme,
    tenant_id: str,
    fichiers: Iterable[FichierTransmis | tuple[str, bytes]],
    deja: dict[str, str],
    *,
    canal: CanalLot = CanalLot.depot,
) -> DepotPrepare:
    """Réception **un fichier à la fois** (la mémoire ne contient jamais tout le lot) et dépôt chiffré dans
    le coffre, sans transaction ouverte. Les doublons (déjà reçus ou dans ce même dépôt) ne sont pas
    redéposés."""
    from controldone.model import Lot as LotModele

    prep = DepotPrepare(lot_id=nouvel_id(Prefixe.lot))
    lot = LotModele(id=prep.lot_id, client_id=tenant_id, canal=canal)
    vus = dict(deja)
    consomme = 0
    try:
        for f in fichiers:
            if isinstance(f, tuple):
                nom, contenu = f
            else:
                nom = f.nom
                contenu = f.lire(plateforme.limites.taille_fichier)
                if contenu is None:
                    prep.refuses.append((_nom_sur(f.nom), LIBELLES_REFUS["trop_gros"]))
                    continue
            reception = recevoir_octets(
                [(_nom_sur(nom), contenu)],
                client_id=tenant_id,
                canal=canal,
                deja_recus=vus,
                limites=_limites_restantes(plateforme.limites, consomme),
                lot=lot,
            )
            del contenu
            consomme_fichier = reception.taille_totale
            consomme += consomme_fichier
            for recu in reception.fichiers:
                fm = recu.fichier.model_copy(update={"lot_id": prep.lot_id})
                ref = None
                if fm.statut is StatutFichier.ok and recu.contenu is not None:
                    if fm.doublon_de is None:
                        existait = plateforme.vault.existe(tenant_id, fm.sha256)
                        ref = plateforme.vault.deposer(tenant_id, recu.contenu)
                        if not existait:
                            prep.nouveaux_blobs.append(ref)
                        vus.setdefault(fm.sha256, fm.id)
                        prep.acceptes += 1
                    else:
                        prep.doublons += 1
                elif fm.statut is StatutFichier.refuse:
                    prep.refuses.append(
                        (
                            fm.chemin_relatif,
                            LIBELLES_REFUS.get(fm.motif_refus or "", fm.motif_refus or "refusé"),
                        )
                    )
                recu.contenu = None
                prep.fichiers.append((fm, ref))
            del reception
            if consomme_fichier > 1024 * 1024:
                # l'analyse d'un PDF (pypdf) laisse des cycles de références qui retiennent les octets du
                # fichier : sans collecte, la mémoire cumulait tout le lot (F-14)
                gc.collect()
    except BaseException:
        annuler_blobs(plateforme, tenant_id, prep)
        raise
    return prep


def annuler_blobs(plateforme: Plateforme, tenant_id: str, prep: DepotPrepare) -> None:
    """Retire du coffre les contenus créés par un dépôt dont l'enregistrement a échoué, sauf ceux qu'une
    ligne ``Fichier`` référence entre-temps (adressage par contenu)."""
    if not prep.nouveaux_blobs:
        return
    try:  # vérification et suppression sous le verrou d'écriture (un dépôt concurrent du même contenu)
        with plateforme.db.tenant(tenant_id, _ACTEUR_NETTOYAGE) as scope:
            references = scope.contenus_references(prep.nouveaux_blobs)
            for sha in prep.nouveaux_blobs:
                if sha not in references:
                    plateforme.vault.supprimer(tenant_id, sha)
    except Exception:  # pragma: no cover - base indisponible : on ne supprime rien (prudence)
        return


def enregistrer_prepare(
    scope: TenantScope,
    prep: DepotPrepare,
    *,
    canal: CanalLot = CanalLot.depot,
    resume: dict[str, Any] | None = None,
    mettre_en_file_job: bool = False,
    vault: Any = None,
) -> ResultatDepot:
    """Courte transaction d'écriture : lot, métadonnées des fichiers et (``mettre_en_file_job``) job
    ``traiter_lot`` dans **la même** transaction (D-1306). Avec ``vault`` : chaque contenu référencé est
    revérifié dans la transaction (une purge concurrente l'a peut-être retiré, D-1324) ; sinon le dépôt est
    refusé proprement (à refaire), jamais enregistré avec un contenu absent."""
    tenant_id = scope.tenant_id
    lot_id = prep.lot_id
    if vault is not None:
        absents = sorted({ref for _fm, ref in prep.fichiers if ref and not vault.existe(tenant_id, ref)})
        if absents:
            raise RequeteInvalide("un contenu a été retiré du coffre pendant le dépôt : déposer à nouveau")
    scope.creer_lot(lot_id, canal=canal.value)
    for fm, ref in prep.fichiers:
        scope.enregistrer_fichier(fm, lot_id=lot_id, coffre_ref=ref)
    prealables = [
        (c, m)
        for c, m in prep.refuses
        if m == LIBELLES_REFUS["trop_gros"] and not any(fm.chemin_relatif == c for fm, _r in prep.fichiers)
    ]
    for chemin, _motif in prealables:
        # fichier au-delà de la limite : métadonnées seulement (aucun contenu conservé)
        sha = hashlib.sha256(f"refuse:{lot_id}:{chemin}".encode()).hexdigest()
        scope.enregistrer_fichier(
            FichierModele(
                client_id=tenant_id,
                lot_id=lot_id,
                nom_original=chemin.split("/")[-1],
                chemin_relatif=chemin,
                sha256=sha,
                taille=0,
                type_mime="application/octet-stream",
                statut=StatutFichier.refuse,
                motif_refus="trop_gros",
            ),
            lot_id=lot_id,
            coffre_ref=None,
        )
    statut = "recu" if prep.acceptes else "en_erreur"
    scope.modifier(
        Lot,
        lot_id,
        statut=statut,
        resume={
            **(resume or {}),
            "fichiers": prep.acceptes,
            "doublons": prep.doublons,
            "refuses": len(prep.refuses),
        },
    )
    resultat = ResultatDepot(
        lot_id=lot_id, job_id=None, acceptes=prep.acceptes, doublons=prep.doublons, refuses=list(prep.refuses)
    )
    if mettre_en_file_job and prep.acceptes:
        resultat.job_id = scope.mettre_en_file(
            "traiter_lot", {"lot_id": lot_id}, f"traiter_lot:{tenant_id}:{lot_id}"
        )
    return resultat


_SEMAPHORE: threading.BoundedSemaphore | None = None
_SEMAPHORE_VERROU = threading.Lock()


def _semaphore() -> threading.BoundedSemaphore:
    global _SEMAPHORE
    with _SEMAPHORE_VERROU:
        if _SEMAPHORE is None:
            from controldone.config import get_settings

            _SEMAPHORE = threading.BoundedSemaphore(max(1, get_settings().depots_simultanes))
        return _SEMAPHORE


def deposer(
    plateforme: Plateforme,
    acteur: Acteur,
    fichiers: list[FichierTransmis],
    *,
    canal: CanalLot = CanalLot.depot,
    resume: dict[str, Any] | None = None,
) -> ResultatDepot:
    """Dépose des fichiers pour le client **de l'acteur** (rôle client ``client_admin``) et met le lot en
    file. Le fondateur ne dépose pas pour un client par cette voie.

    Fonction **bloquante** (lecture, chiffrement, ``fsync``) : depuis une route ``async``, l'appeler par
    ``run_in_threadpool``. Déroulé (D-1304) : (1) lecture des empreintes déjà reçues (transaction de
    lecture) ; (2) réception et chiffrement dans le coffre, fichier par fichier, **sans** verrou d'écriture ;
    (3) courte transaction d'écriture : lot, fichiers, job. En cas d'échec de (3), les contenus créés par ce
    dépôt sont retirés du coffre. Au plus ``CONTROLDONE_DEPOTS_SIMULTANES`` dépôts à la fois."""
    tenant_id = acteur.tenant_id
    if not acteur.est_client or tenant_id is None:
        raise Interdit("dépôt réservé aux comptes client")
    exiger(acteur, Action.deposer, tenant_id)
    if not fichiers:
        raise RequeteInvalide("aucun fichier transmis")
    total = sum(f.taille for f in fichiers)
    if total > plateforme.limites.taille_lot:
        raise RequeteInvalide("dépôt trop volumineux : 500 Mo au plus par dépôt")
    with _semaphore():
        with plateforme.db.tenant(tenant_id, acteur, lecture=True) as scope:
            deja = deja_recus(scope)
        prep = preparer_depot(plateforme, tenant_id, fichiers, deja, canal=canal)
        try:
            with plateforme.db.tenant(tenant_id, acteur) as scope:
                return enregistrer_prepare(
                    scope, prep, canal=canal, resume=resume, mettre_en_file_job=True, vault=plateforme.vault
                )
        except BaseException:
            annuler_blobs(plateforme, tenant_id, prep)
            raise


def enregistrer_depot(
    plateforme: Plateforme,
    scope: TenantScope,
    elements: list[tuple[str, bytes]],
    *,
    canal: CanalLot = CanalLot.depot,
    resume: dict[str, Any] | None = None,
    refuses_prealables: list[tuple[str, str]] | None = None,
) -> ResultatDepot:
    """Réception + enregistrement dans ``scope`` (compatibilité : tout se fait dans la transaction de
    l'appelant). Ne met rien en file. Préférer ``deposer`` (transaction courte)."""
    prep = preparer_depot(plateforme, scope.tenant_id, elements, deja_recus(scope), canal=canal)
    prep.refuses = list(refuses_prealables or []) + prep.refuses
    return enregistrer_prepare(scope, prep, canal=canal, resume=resume)


def mettre_en_file(plateforme: Plateforme, tenant_id: str, lot_id: str) -> str:
    job, _cree = JobStore(plateforme.db).enqueue(
        "traiter_lot", {"lot_id": lot_id}, f"traiter_lot:{tenant_id}:{lot_id}", tenant_id
    )
    return job.id
