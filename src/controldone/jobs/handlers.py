"""Handlers intégrés.

- ``traiter_lot`` (payload ``{"lot_id": …}``) : déchiffre les fichiers du lot dans un répertoire temporaire
  (arborescence d'origine conservée, chemins assainis), appelle ``controldone.pipeline.traiter_lot``
  (import paresseux : son absence donne une erreur réessayable), puis enregistre via ``TenantScope``
  dossiers, documents, résultats et constats, textes de page (chiffrés), coût IA ; le tout en **une**
  transaction qui marque aussi le lot ``traite`` (rejouer un job déjà appliqué ne crée aucun doublon).
  Le modèle de langage est désactivé si le plafond mensuel du client est atteint.
- ``purger_retention`` : ``storage.retention.purger_expires``.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from controldone.auth.roles import Acteur
from controldone.jobs.couts import enregistrer_cout, etat_plafond
from controldone.jobs.registre import ErreurDefinitive, JobContext, handler
from controldone.jobs.worker import ErreurTemporaire
from controldone.storage.coltypes import maintenant
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import Fichier, Lot, PageTexte
from controldone.storage.vault import FileVault

__all__ = ["charger_pipeline", "chemin_sur", "purger_retention", "traiter_lot"]


def charger_pipeline() -> tuple[Callable[..., Any], type]:
    """Import paresseux du pipeline (écrit par une autre équipe ; peut être absent)."""
    try:
        from controldone.pipeline import OptionsPipeline, traiter_lot
    except ImportError as exc:
        raise ErreurTemporaire("pipeline indisponible") from exc
    return traiter_lot, OptionsPipeline


def chemin_sur(racine: Path, chemin_relatif: str, defaut: str) -> Path:
    """Chemin sous ``racine`` construit depuis un chemin relatif non fiable (``..``, absolu, NUL rejetés)."""
    parties = [p for p in PurePosixPath(chemin_relatif.replace("\\", "/")).parts
               if p not in ("", ".", "..", "/") and "\x00" not in p]
    parties = [p[:150] for p in parties][-6:] or [defaut]
    cible = (racine.joinpath(*parties)).resolve()
    if not cible.is_relative_to(racine.resolve()):
        raise AccesRefuse("chemin de fichier hors du répertoire de travail")
    return cible


def _vault(ctx: JobContext) -> FileVault:
    v = ctx.services.get("vault")
    if v is None:
        v = FileVault.depuis_env()
        ctx.services["vault"] = v
    return v


def _profil(scope: Any) -> Any:
    from controldone.model.referentiel import Client, Entite, Transitaire
    from controldone.referentiel_io import ProfilClient
    from controldone.storage.models import Entite as EntiteRow
    from controldone.storage.models import Transitaire as TransitaireRow

    t = scope.client()
    client = Client(id=t.id, raison_sociale=t.raison_sociale, offre=t.offre,
                    plafond_cout_ia_mensuel_eur=t.plafond_cout_ia_mensuel_eur, retention_jours=t.retention_jours)
    return ProfilClient(
        client=client,
        entites=[Entite.model_validate({"id": e.id, "raison_sociale": e.raison_sociale, "tva": e.tva,
                                        **(e.contenu or {}), "client_id": t.id})
                 for e in scope.lister(EntiteRow)],
        transitaires=[Transitaire.model_validate({"id": x.id, "nom": x.nom, "tva": x.tva, **(x.contenu or {}),
                                                  "client_id": t.id})
                      for x in scope.lister(TransitaireRow)],
    )


def _rattacher_fichiers(doc: Any, fichiers_pipeline: dict[str, Any], par_sha: dict[str, str]) -> Any:
    """Les pages d'un document citent les fichiers du lot **enregistrés** (et non les identifiants
    temporaires du pipeline) : vignettes de page et téléchargement retrouvent le fichier du coffre."""
    pages = []
    for pr in doc.pages:
        f = fichiers_pipeline.get(pr.fichier_id)
        notre = par_sha.get(f.sha256) if f is not None else None
        pages.append(pr.model_copy(update={"fichier_id": notre}) if notre else pr)
    return doc.model_copy(update={"pages": pages})


@handler("traiter_lot")
def traiter_lot(ctx: JobContext) -> dict[str, Any]:
    tenant_id = ctx.tenant_id
    lot_id = ctx.payload.get("lot_id")
    if not tenant_id or not lot_id:
        raise ErreurDefinitive("payload invalide (client et lot obligatoires)")
    pipeline, options_cls = charger_pipeline()
    vault = _vault(ctx)
    acteur = Acteur.systeme("worker")

    with ctx.db.tenant(tenant_id, acteur, lecture=True) as scope:
        lot = scope.obtenir(Lot, lot_id)
        if lot.statut == "traite":
            return {"deja_traite": True, **(lot.resume or {})}
        fichiers = [(f.id, f.chemin_relatif, f.nom_original, f.coffre_ref, f.sha256)
                    for f in scope.lister(Fichier, lot_id=lot_id, statut="ok", ordre=Fichier.id)]
        profil = _profil(scope)
        grilles = scope.grilles_validees()
        plafond = etat_plafond(scope)

    with tempfile.TemporaryDirectory(prefix="cd-lot-") as tmp:
        racine = Path(tmp) / "lot"
        racine.mkdir()
        for fid, chemin, nom, ref, _sha in fichiers:
            if not ref:
                continue  # purgé
            cible = chemin_sur(racine, chemin or nom, fid)
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(vault.lire(tenant_id, ref))
        ctx.heartbeat()
        options = options_cls(llm=plafond.llm_autorise)
        resultats = pipeline(racine, profil, grilles, options=options)
    ctx.heartbeat()

    par_sha = {sha: fid for fid, _c, _n, _r, sha in fichiers}
    n_constats = 0
    executions: set[str] = set()
    pages_vues: set[str] = set()
    with ctx.db.tenant(tenant_id, acteur) as scope:
        lot = scope.obtenir(Lot, lot_id)
        if lot.statut == "traite":  # appliqué entre-temps par un autre worker
            return {"deja_traite": True, **(lot.resume or {})}
        for rd in resultats:
            fichier_ids = sorted({par_sha[f.sha256] for f in rd.fichiers.values() if f.sha256 in par_sha})
            for fid_pipeline, pages in (rd.pages or {}).items():
                f = rd.fichiers.get(fid_pipeline)
                notre = par_sha.get(f.sha256) if f is not None else None
                if notre is None:
                    continue
                for p in pages:
                    cle = f"{notre}:{p.numero}"
                    if cle in pages_vues or scope.lister(PageTexte, fichier_id=notre, numero=p.numero):
                        continue
                    pages_vues.add(cle)
                    ref = vault.deposer_texte(tenant_id, p.texte) if p.texte else None
                    scope.enregistrer_page(
                        "pag_" + hashlib.sha256(f"{tenant_id}:{cle}".encode()).hexdigest()[:32], notre,
                        p.numero, qualite_texte=str(p.qualite_texte), sha256_texte=p.sha256_texte, texte_ref=ref,
                    )
            scope.enregistrer_dossier(rd.dossier, lot_id=lot_id,
                                      documents=[_rattacher_fichiers(d, rd.fichiers, par_sha)
                                                 for d in rd.documents.values()],
                                      fichier_ids=fichier_ids)
            scope.enregistrer_resultats(rd.resultats)
            n_constats += sum(1 for r in rd.resultats if r.constat is not None)
            ex = rd.execution
            if ex.id not in executions:
                executions.add(ex.id)
                if ex.cout_ia_eur or ex.jetons_entree or ex.jetons_sortie:
                    enregistrer_cout(scope, cout_eur=ex.cout_ia_eur, jetons_entree=ex.jetons_entree,
                                     jetons_sortie=ex.jetons_sortie, modele=ex.modele_llm, lot_id=lot_id,
                                     execution_id=ex.id)
        non_lus = len(resultats[0].non_lus) if resultats else 0
        resume = {"dossiers": len(resultats), "constats": n_constats, "non_lus": non_lus,
                  "llm": plafond.llm_autorise}
        lot.statut, lot.resume = "traite", resume
        scope.flush()
    return resume


@handler("purger_retention")
def purger_retention(ctx: JobContext) -> dict[str, Any]:
    from controldone.storage.retention import purger_expires

    rapport = purger_expires(ctx.db, _vault(ctx), maintenant())
    return {"fichiers": sum(rapport.fichiers.values()), "textes": sum(rapport.textes.values())}


# Handlers de la plateforme web (recontrôle après correction, §6.2.11) : enregistrés au chargement.
from controldone.services import recontrole as _recontrole  # noqa: E402, F401
