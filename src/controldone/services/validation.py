"""Décisions du fondateur sur les constats (SPEC §7.7) et corrections de valeurs (§6.2.11).

- ``valider`` : publication du constat au client ; un constat ``recouvrable`` de montant positif ouvre un
  écart à recouvrer (§17.1) ;
- ``rejeter`` : motif obligatoire ;
- ``retrograder`` : ``ecart_certain`` -> ``a_verifier`` (motif obligatoire) ;
- **jamais de promotion directe** : un ``a_verifier`` ne devient ``ecart_certain`` que par un recontrôle
  après correction ou confirmation de la valeur douteuse par ``saisie_humaine`` (``corriger_valeur``) ;
- ``corriger_valeur`` : nouvelle ``ValeurSourcee`` ``saisie_humaine`` (confiance 1,0) qui remplace la
  précédente pour les contrôles, sans l'effacer (correction append-only) ; la version du dossier augmente
  et le job ``recontroler_dossier`` relance les contrôles.
"""

from __future__ import annotations

from decimal import Decimal

from controldone.auth.roles import Role
from controldone.extract.valeurs import valeur_sourcee
from controldone.ids import Prefixe, nouvel_id
from controldone.litiges.service import id_ecart
from controldone.model.champs import chemin_relatif
from controldone.model.documents import Document as DocumentModele
from controldone.model.dossier import Dossier as DossierModele
from controldone.model.enums import Composante, Methode, TypeExtracteur, TypeValeur
from controldone.model.recouvrement import EcartARecouvrer
from controldone.model.valeur import ExtracteurInfo
from controldone.services.plateforme import Plateforme, RequeteInvalide
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import Constat, Document, Dossier, Ecart
from controldone.storage.scope import TenantScope

__all__ = ["corriger_valeur", "mettre_en_file_recontrole", "rejeter", "retrograder", "valider"]

EXTRACTEUR_SAISIE = ExtracteurInfo(type=TypeExtracteur.saisie_humaine, id="saisie_humaine", version="1.0.0")


def valider(scope: TenantScope, constat_id: str, commentaire: str | None = None) -> Constat:
    c = scope.obtenir(Constat, constat_id)
    if c.statut_validation != "propose":
        raise RequeteInvalide("ce constat a déjà fait l'objet d'une décision")
    c = scope.valider_constat(constat_id, "valide", (commentaire or "").strip() or None)
    ouvrir_ecart(scope, c)
    return c


def rejeter(scope: TenantScope, constat_id: str, motif: str) -> Constat:
    if not (motif and motif.strip()):
        raise RequeteInvalide("le rejet exige un motif")
    c = scope.obtenir(Constat, constat_id)
    if c.statut_validation != "propose":
        raise RequeteInvalide("ce constat a déjà fait l'objet d'une décision")
    return scope.valider_constat(constat_id, "rejete", motif.strip()[:1000])


def retrograder(scope: TenantScope, constat_id: str, motif: str) -> Constat:
    if not (motif and motif.strip()):
        raise RequeteInvalide("la rétrogradation exige un motif")
    try:
        return scope.retrograder_constat(constat_id, motif)
    except ValueError as exc:
        raise RequeteInvalide(str(exc)) from exc


def ouvrir_ecart(scope: TenantScope, c: Constat) -> Ecart | None:
    """Écart à recouvrer né d'un constat validé ``recouvrable`` de montant positif (§17.1). Idempotent."""
    if c.nature_montant != "recouvrable" or not c.montant_en_jeu or c.montant_en_jeu <= 0:
        return None
    if scope.lister(Ecart, constat_id=c.id):
        return None  # déjà ouvert (ici ou par la préparation d'un dossier de demande d'avoir)
    dossier = DossierModele.model_validate(scope.obtenir(Dossier, c.dossier_id).contenu)
    j = c.contenu or {}
    ft = None
    for doc_id in j.get("documents_concernes") or []:
        try:
            if scope.obtenir(Document, doc_id).type == "facture_transitaire":
                ft = doc_id
                break
        except AccesRefuse:
            continue
    try:
        composante = Composante(j.get("composante") or "prestation")
    except ValueError:
        composante = Composante.prestation
    montant = Decimal(c.montant_en_jeu)
    ecart = EcartARecouvrer(
        id=id_ecart(scope.tenant_id, c.id), client_id=scope.tenant_id, constat_id=c.id,
        dossier_id=c.dossier_id, transitaire_id=dossier.transitaire_id, facture_transitaire_id=ft,
        mrn=(dossier.cles.mrn or [None])[0], composante=composante, montant_initial=montant, reste=montant,
    )
    e = scope.enregistrer_ecart(ecart)
    e.contenu = {**e.contenu, "niveau": c.niveau, "dossier_reference": dossier.reference}
    scope.flush()
    return e


def corriger_valeur(scope: TenantScope, dossier_id: str, document_id: str, valeur_id: str, nouvelle: str,
                    motif: str) -> int:
    """Corrige (ou confirme, même valeur) une valeur extraite ; renvoie la nouvelle version du dossier.
    L'appelant met ensuite le recontrôle en file (``mettre_en_file_recontrole``) après validation de la
    transaction."""
    if not (motif and motif.strip()):
        raise RequeteInvalide("la correction exige un motif")
    nouvelle = (nouvelle or "").strip()
    if not nouvelle or len(nouvelle) > 300:
        raise RequeteInvalide("valeur vide ou trop longue")
    dossier = DossierModele.model_validate(scope.obtenir(Dossier, dossier_id).contenu)
    if document_id not in dossier.document_ids():
        raise AccesRefuse("introuvable ou hors périmètre")
    doc = DocumentModele.model_validate(scope.obtenir(Document, document_id).contenu)
    ancienne = next((v for v in doc.valeurs() if v.id == valeur_id), None)
    if ancienne is None or doc.champs is None:
        raise AccesRefuse("introuvable ou hors périmètre")
    rel = chemin_relatif(ancienne.chemin)
    nv = valeur_sourcee(
        type_document=doc.type, chemin=rel, brut=nouvelle, document_id=doc.id, page=ancienne.page,
        extracteur=EXTRACTEUR_SAISIE, methode=Methode.saisie_humaine, confiance=1.0, type_valeur=ancienne.type,
        devise=ancienne.unite if ancienne.type is TypeValeur.montant else None,
    )
    if nv.valeur is None:
        raise RequeteInvalide("valeur illisible pour ce type de champ")
    nv = nv.model_copy(update={"remplace": ancienne.id, "zone": ancienne.zone, "valeur_brute": nouvelle,
                               "texte_contexte": ancienne.texte_contexte, "confiance": 1.0, "ancree": True})
    doc.champs.definir(rel, nv)
    role = "fondateur" if scope.actor.role is Role.fondateur else "utilisateur_client"
    ligne = scope.appliquer_correction(
        correction_id=nouvel_id(Prefixe.correction), dossier_id=dossier_id, document_id=document_id,
        cible=ancienne.id, chemin=ancienne.chemin, ancienne=ancienne.model_dump(mode="json"),
        nouvelle=nv.model_dump(mode="json"), contenu_document=doc.model_dump(mode="json"), motif=motif,
        role_auteur=role)
    return ligne.version


def mettre_en_file_recontrole(plateforme: Plateforme, tenant_id: str, dossier_id: str, version: int) -> str:
    job, _ = JobStore(plateforme.db).enqueue(
        "recontroler_dossier", {"dossier_id": dossier_id, "version": version},
        f"recontroler_dossier:{tenant_id}:{dossier_id}:v{version}", tenant_id)
    return job.id
