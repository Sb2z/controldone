"""Handler ``recontroler_dossier`` (payload ``{"dossier_id", "version"}``) : relance les contrôles d'un
dossier après une correction de valeur (SPEC §6.2.11, §7.7), sans repasser par la lecture des fichiers.

Contrôles purs (``run_controls``) sur l'instantané du dossier et de ses documents en base, avec les grilles
validées, les entités et transitaires du client et ses autres dossiers (famille F). Idempotent : une version
déjà recontrôlée (ou dépassée par une correction plus récente) n'est pas retraitée. Les constats gardent
leur validation si leur niveau et leur montant sont inchangés ; sinon ils sont de nouveau proposés au
fondateur (``TenantScope.enregistrer_resultats``).
"""

from __future__ import annotations

from typing import Any

from controldone.auth.roles import Acteur
from controldone.controls.context import AutreDossier, ControlContext
from controldone.controls.runner import run_controls
from controldone.findings_io import statut_global_depuis_resultats
from controldone.guardrails import MOTIF_FORMULATION_INTERDITE, check_text
from controldone.ids import Prefixe, nouvel_id
from controldone.jobs.registre import ErreurDefinitive, JobContext, handler
from controldone.model.documents import Document as DocumentModele
from controldone.model.dossier import Dossier as DossierModele
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import Document, Dossier

__all__ = ["recontroler_dossier"]


def _profil(scope: Any) -> Any:
    from controldone.jobs.handlers import _profil as profil_client

    return profil_client(scope)


def _rediger(resultats: list[Any]) -> list[Any]:
    sortie = []
    for r in resultats:
        c = r.constat
        if c is not None and c.motif_blocage is None and check_text(f"{c.libelle} {c.prochaine_action}"):
            r = r.model_copy(update={"constat": c.model_copy(update={"motif_blocage": MOTIF_FORMULATION_INTERDITE})})
        sortie.append(r)
    return sortie


@handler("recontroler_dossier")
def recontroler_dossier(ctx: JobContext) -> dict[str, Any]:
    tenant_id = ctx.tenant_id
    dossier_id = ctx.payload.get("dossier_id")
    if not tenant_id or not dossier_id:
        raise ErreurDefinitive("payload invalide (client et dossier obligatoires)")
    acteur = Acteur.systeme("recontrole")
    with ctx.db.tenant(tenant_id, acteur, lecture=True) as scope:
        try:
            ligne = scope.obtenir(Dossier, dossier_id)
        except AccesRefuse as exc:
            raise ErreurDefinitive("dossier introuvable") from exc
        dossier = DossierModele.model_validate(ligne.contenu)
        if ligne.version != ctx.payload.get("version", ligne.version):
            return {"ignore": "version depassee", "version": ligne.version}

        # une seule requête pour tous les documents du client (au lieu d'une par document, F-15) ;
        # validation pydantic paresseuse, une fois par document
        contenus = {d.id: d.contenu for d in scope.lister(Document)}
        valides: dict[str, DocumentModele] = {}

        def docs_de(d: DossierModele) -> dict[str, DocumentModele]:
            out = {}
            for i in d.document_ids():
                if i not in contenus:
                    continue
                if i not in valides:
                    valides[i] = DocumentModele.model_validate(contenus[i])
                out[i] = valides[i]
            return out

        documents = docs_de(dossier)
        autres = []
        for autre in scope.lister(Dossier):
            if autre.id == dossier_id:
                continue
            m = DossierModele.model_validate(autre.contenu)
            autres.append(AutreDossier(dossier=m, documents=docs_de(m)))
        profil = _profil(scope)
        grilles = scope.grilles_validees()
    contexte = ControlContext.construire(
        dossier, documents.values(), profil.tolerances, grilles=grilles, entites=profil.entites,
        transitaires=profil.transitaires, autres_dossiers=autres,
        parametres_petits_envois=profil.parametres_petits_envois, execution_id=nouvel_id(Prefixe.execution),
    )
    resultats = _rediger(run_controls(contexte))
    statut = statut_global_depuis_resultats(resultats)
    ctx.heartbeat()
    with ctx.db.tenant(tenant_id, acteur) as scope:
        ligne = scope.obtenir(Dossier, dossier_id)
        if ligne.version != dossier.version:
            return {"ignore": "version depassee", "version": ligne.version}
        scope.enregistrer_dossier(dossier.model_copy(update={"statut_global": statut}))
        n = scope.enregistrer_resultats(resultats)
    return {"dossier_id": dossier_id, "version": dossier.version, "resultats": n, "statut": statut.value}
