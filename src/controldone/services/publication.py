"""Rapport figé sur les constats **validés** et publication au client (SPEC §4, §18).

- ``reconstituer`` : relit en base (périmètre du client, accès du fondateur tracé) l'instantané de chaque
  dossier, ses documents, ses résultats de contrôle (version courante) et ses constats avec leur décision ;
  ``publies_seulement=True`` retire tout constat non validé (règle de publication), et le statut global est
  recalculé sur les seuls constats validés (``valides_seulement=True``).
- ``publier_rapport`` (fondateur) : génère HTML, PDF et JSON (``controldone.rapport.generer_rapport`` :
  garde-fous sur le texte visible), les range chiffrés dans le coffre du client et crée une action sortante
  ``rapport_publication`` (brouillon) dans la file de validation. Le client voit le rapport quand l'action
  est approuvée puis mise à disposition (``envoye``).
- ``piece`` : lecture d'une pièce (PDF, HTML, JSON…) d'une action sortante, avec contrôle de périmètre :
  un rôle client ne lit que les actions **mises à disposition** de **son** client.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from controldone.auth.roles import Acteur, Role
from controldone.calendrier import aujourdhui_paris
from controldone.findings_io import construire_findings, statut_global_depuis_resultats
from controldone.guardrails import AVERTISSEMENT
from controldone.model.documents import Fichier as FichierModele
from controldone.model.dossier import Dossier as DossierModele
from controldone.model.enums import StatutFichier
from controldone.model.resultats import Constat as ConstatModele
from controldone.model.resultats import Execution, ResultatControle
from controldone.outbox import ExpediteurFichier, FileSortante, StatutAction, TypeAction
from controldone.pipeline import NonLu, ResultatDossier
from controldone.referentiel_io import ProfilClient
from controldone.services.lecture import documents_du_dossier
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import Constat, Dossier, Fichier, Resultat
from controldone.storage.scope import TenantScope

__all__ = ["FORMATS", "ResultatPublication", "piece", "profil_client", "publier_rapport", "reconstituer"]

FORMATS = {
    "pdf": ("application/pdf", "rapport.pdf"),
    "html": ("text/html; charset=utf-8", "rapport.html"),
    "json": ("application/json", "rapport.json"),
    "txt": ("text/plain; charset=utf-8", "texte.txt"),
}


def profil_client(scope: TenantScope) -> ProfilClient:
    from controldone.jobs.handlers import _profil

    p = _profil(scope)
    p.demo = bool((scope.client().reglages or {}).get("demo"))
    return p


def _fichier_modele(f: Fichier) -> FichierModele | None:
    try:
        return FichierModele(
            id=f.id,
            client_id=f.tenant_id,
            lot_id=f.lot_id,
            nom_original=f.nom_original,
            chemin_relatif=f.chemin_relatif,
            sha256=f.sha256,
            taille=f.taille,
            type_mime=f.type_mime,
            statut=StatutFichier(f.statut),
            motif_refus=f.motif_refus,
            nombre_pages=f.nombre_pages,
            doublon_de=f.doublon_de,
        )
    except Exception:
        return None


def reconstituer(
    scope: TenantScope,
    vault: Any,
    dossier_racine: Path,
    *,
    publies_seulement: bool = True,
    dossier_ids: list[str] | None = None,
) -> list[ResultatDossier]:
    """``ResultatDossier`` de chaque dossier du client depuis la base (fondateur seulement : les résultats
    bruts ne sont pas lisibles par un rôle client). Les fichiers sont déchiffrés dans ``dossier_racine``
    (répertoire temporaire de l'appelant) pour les rognages de preuve du rapport."""
    if scope.actor.role is not Role.fondateur and scope.actor.role is not Role.systeme:
        raise Interdit("reconstitution réservée au fondateur")
    profil = profil_client(scope)
    lignes = scope.lister(Dossier, ordre=Dossier.reference)
    if dossier_ids is not None:
        lignes = [d for d in lignes if d.id in set(dossier_ids)]
    sortie: list[ResultatDossier] = []
    for ligne in lignes:
        dossier = DossierModele.model_validate(ligne.contenu)
        docs = documents_du_dossier(scope, dossier)
        fichiers: dict[str, FichierModele] = {}
        chemins: dict[str, str] = {}
        for d in docs.values():
            for pr in d.pages:
                if pr.fichier_id in fichiers:
                    continue
                try:
                    f = scope.obtenir(Fichier, pr.fichier_id)
                except AccesRefuse:
                    continue
                fm = _fichier_modele(f)
                if fm is None:
                    continue
                fichiers[f.id] = fm
                if f.coffre_ref:
                    try:
                        cible = dossier_racine / f.id
                        cible.write_bytes(vault.lire(scope.tenant_id, f.coffre_ref))
                        chemins[f.id] = str(cible)
                    except Exception:
                        pass
        constats = {c.id: c for c in scope.lister(Constat, dossier_id=ligne.id)}
        resultats: list[ResultatControle] = []
        execution_id = None
        for r in scope.lister(Resultat, dossier_id=ligne.id, ordre=Resultat.id):
            if r.dossier_version != ligne.version:
                continue
            rc = ResultatControle.model_validate(r.contenu)
            execution_id = execution_id or rc.execution_id
            if rc.constat is not None:
                c = constats.get(rc.constat.id)
                if c is None:
                    continue
                if publies_seulement and c.statut_validation != "valide":
                    continue  # règle de publication : ni proposé, ni rejeté
                if c.statut_validation == "rejete":
                    continue
                rc = rc.model_copy(update={"constat": ConstatModele.model_validate(c.contenu)})
            resultats.append(rc)
        statut = statut_global_depuis_resultats(resultats, valides_seulement=publies_seulement)
        dossier = dossier.model_copy(update={"statut_global": statut})
        execution = Execution.nouvelle(
            id=execution_id or f"exe_{ligne.id[4:]}",
            client_id=scope.tenant_id,
            empreinte_tolerances=profil.tolerances.empreinte(),
        )
        non_lus = (
            [
                NonLu(fichier=f.chemin_relatif, motif=f"refuse:{f.motif_refus}")
                for f in scope.lister(Fichier, lot_id=ligne.lot_id)
                if f.statut == StatutFichier.refuse.value
            ]
            if ligne.lot_id
            else []
        )
        findings = construire_findings(
            dossier,
            docs.values(),
            resultats,
            execution,
            fichiers=fichiers,
            dossier_id=dossier.reference or dossier.id,
            statut_global=statut,
        )
        sortie.append(
            ResultatDossier(
                dossier=dossier,
                documents=docs,
                fichiers=fichiers,
                chemins=chemins,
                pages={},
                resultats=resultats,
                findings=findings,
                execution=execution,
                statut_global=statut,
                non_lus=non_lus,
                profil=profil,
            )
        )
    return sortie


@dataclass
class ResultatPublication:
    action_id: str
    statut: str
    nb_dossiers: int
    nb_constats: int


def _generer(scope: TenantScope, vault: Any) -> tuple[dict[str, str], int, int, list[list[Any]], str]:
    from controldone.rapport import generer_rapport

    with tempfile.TemporaryDirectory(prefix="cd-rapport-") as tmp:
        racine = Path(tmp)
        (racine / "pieces").mkdir()
        resultats = reconstituer(scope, vault, racine / "pieces", publies_seulement=True)
        if not resultats:
            raise RequeteInvalide("aucun dossier à publier pour ce client")
        profil = resultats[0].profil
        sorties = generer_rapport(resultats, profil, racine / "rapport", date_rapport=aujourdhui_paris())
        refs = {}
        for fmt, chemin in (("pdf", sorties.pdf), ("html", sorties.html), ("json", sorties.json)):
            refs[fmt] = vault.deposer(scope.tenant_id, chemin.read_bytes())
        nb_constats = sum(1 for rd in resultats for r in rd.resultats if r.constat is not None)
        figes = [[rd.dossier.id, rd.dossier.version] for rd in resultats]
        return refs, len(resultats), nb_constats, figes, profil.client.raison_sociale


def publier_rapport(plateforme: Plateforme, fondateur: Acteur, tenant_id: str) -> ResultatPublication:
    """Fondateur seulement : rapport figé sur les constats validés, proposé dans la file des sorties."""
    if fondateur.role is not Role.fondateur:
        raise Interdit("publication réservée au fondateur")
    with plateforme.db.operateur(fondateur) as op:
        scope = op.client(tenant_id, "publication du rapport de diagnostic", lecture=True)
        refs, nb_dossiers, nb_constats, figes, client = _generer(scope, plateforme.vault)
    jour = aujourdhui_paris().isoformat()
    payload = {
        "objet": f"Rapport de diagnostic — {client}",
        "corps": (
            f"Votre rapport de diagnostic ({nb_dossiers} dossier{'s' if nb_dossiers > 1 else ''}, "
            f"{nb_constats} constat{'s' if nb_constats > 1 else ''} validé{'s' if nb_constats > 1 else ''}) "
            "est disponible dans votre espace, au format web et PDF."
        ),
        "destinataires": [],
        "pieces": [{"format": f, "ref": r, "nom": FORMATS[f][1]} for f, r in refs.items()],
        "dossiers_figes": figes,
        "genere_le": jour,
    }
    action = FileSortante(plateforme.db).proposer(
        TypeAction.rapport_publication,
        payload,
        fondateur,
        tenant_id=tenant_id,
        idempotency_key=f"rapport:{tenant_id}:{refs['json']}",
    )
    return ResultatPublication(action.id, action.statut.value, nb_dossiers, nb_constats)


def mettre_a_disposition(plateforme: Plateforme, action_id: str, acteur: Acteur) -> None:
    """Après approbation : « envoi » = mise à disposition du client dans son espace (l'expéditeur fichier
    écrit la trace ``var/outbox_envoyee/``). Seuls les rapports et relevés d'écarts sont concernés :
    rien n'est jamais envoyé à un transitaire."""
    fs = FileSortante(plateforme.db)
    a = fs.obtenir(action_id, acteur)
    if a.kind in (TypeAction.rapport_publication, TypeAction.reclamation_dossier) and a.statut in (
        StatutAction.approuve,
        StatutAction.corrige,
    ):
        fs.envoyer(
            action_id, ExpediteurFichier(plateforme.dossier_sorties, cles=plateforme.cles_maitresses), acteur
        )
    elif a.kind is TypeAction.facture_emise and a.statut in (StatutAction.approuve, StatutAction.corrige):
        # facture approuvée : émission (numéro, Factur-X) puis dépôt sur la plateforme agréée partenaire
        from controldone.facturation import service_pour

        service_pour(plateforme).emettre_et_deposer(action_id, acteur)


def piece(
    plateforme: Plateforme,
    acteur: Acteur,
    action_id: str,
    fmt: str,
    kinds: tuple[TypeAction, ...] = (TypeAction.rapport_publication, TypeAction.reclamation_dossier),
) -> tuple[bytes, str, str]:
    """``(octets, type MIME, nom)`` d'une pièce. Rôle client : action **mise à disposition** de son client
    (sinon ``AccesRefuse``, identique à une action inexistante)."""
    if fmt not in FORMATS:
        raise AccesRefuse("introuvable ou hors périmètre")
    a = FileSortante(plateforme.db).obtenir(action_id, acteur)  # AccesRefuse si hors périmètre
    if a.kind not in kinds or a.tenant_id is None:
        raise AccesRefuse("introuvable ou hors périmètre")
    if acteur.est_client and (a.tenant_id != acteur.tenant_id or a.statut is not StatutAction.envoye):
        raise AccesRefuse("introuvable ou hors périmètre")
    payload = a.payload_effectif
    for p in payload.get("pieces") or []:
        if isinstance(p, dict) and p.get("format") == fmt and p.get("ref"):
            contenu = plateforme.vault.lire(a.tenant_id, p["ref"])
            return contenu, FORMATS[fmt][0], p.get("nom") or FORMATS[fmt][1]
        # pièces du service des litiges : « coffre:<sha256> » (PDF du dossier de demande d'avoir)
        if isinstance(p, str) and p.startswith("coffre:") and fmt == "pdf":
            return (
                plateforme.vault.lire(a.tenant_id, p[len("coffre:") :]),
                FORMATS["pdf"][0],
                "releve_ecarts.pdf",
            )
    if fmt == "txt" and a.kind is TypeAction.reclamation_dossier and payload.get("corps"):
        texte = str(payload["corps"]) + "\n\n" + AVERTISSEMENT + "\n"
        return texte.encode("utf-8"), FORMATS["txt"][0], "releve_ecarts.txt"
    raise AccesRefuse("introuvable ou hors périmètre")


def formats_disponibles(action: Any) -> list[str]:
    """Formats téléchargeables d'une action (rapport : pdf/html/json ; relevé d'écarts : pdf/txt)."""
    out = []
    for p in action.payload_effectif.get("pieces") or []:
        if isinstance(p, dict) and p.get("format"):
            out.append(p["format"])
        elif isinstance(p, str) and p.startswith("coffre:"):
            out.append("pdf")
    if action.kind is TypeAction.reclamation_dossier and action.payload_effectif.get("corps"):
        out.append("txt")
    return list(dict.fromkeys(out))


def actions_client(plateforme: Plateforme, acteur: Acteur, kind: TypeAction) -> list[Any]:
    """Actions mises à disposition du client de l'acteur (rôle client) ou toutes (fondateur)."""
    return [
        a
        for a in FileSortante(plateforme.db).lister(acteur, kind=kind.value)
        if not acteur.est_client or a.statut is StatutAction.envoye
    ]
