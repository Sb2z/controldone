"""Catalogue des outils des agents (fonctions typées ``fn(ctx, **params)``).

Règles communes, appliquées ici et testées :

- le client est **toujours** ``ctx.tenant_id`` (jamais un paramètre) : un outil ne peut lire ni écrire
  les données d'un autre client ;
- l'acteur est ``systeme:agent:<nom>`` : il peut lire et proposer, jamais approuver ni envoyer ;
- les seules écritures sont : brouillon sortant (``FileSortante.proposer``), alerte au fondateur
  (``signaler_alerte``), demande de job (``enqueue``), et l'état propre de la veille (instantanés) ;
- les destinataires d'un courriel ne sont jamais choisis par l'agent : ce sont les contacts du client ;
- les lectures de constats pour une réponse au client ne portent que sur les constats **publiés**.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from controldone.litiges import ServiceLitiges, destinataires_client, id_ecart, payload_facture
from controldone.litiges.etats import StatutReclamation
from controldone.litiges.facture import LigneFacture
from controldone.outbox import FileSortante
from controldone.perimetre import perimetre
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import Constat, Document, Lot, Reclamation, Resultat
from controldone.storage.models import Dossier as DossierRow

from .base import ContexteAgent, Outil

__all__ = ["CATALOGUE", "KINDS_ALERTE", "KINDS_JOB"]

KINDS_ALERTE = Literal["revue_extraction", "litige_inactif", "litige_a_preparer", "litige_a_valider",
                       "litige_a_clore", "question_client_instruction"]
KINDS_JOB = Literal["traiter_lot", "preparer_reclamation"]
TYPES_FACTURE = Literal["diagnostic", "abonnement", "commission"]


def _exiger_client(ctx: ContexteAgent) -> str:
    if not ctx.tenant_id:
        raise AccesRefuse("outil réservé à un agent rattaché à un client")
    return ctx.tenant_id


def _cle(ctx: ContexteAgent, cle: str) -> str:
    """Clé d'idempotence cloisonnée : préfixée par le client si elle ne le cite pas."""
    if ctx.tenant_id and ctx.tenant_id not in cle.split(":"):
        return f"{ctx.tenant_id}:{cle}"
    return cle


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


# --- lectures ---------------------------------------------------------------------------------------------


def _abonnement(ctx: ContexteAgent, tenant_id: str, reglages: dict[str, Any]) -> dict[str, Any]:
    """Palier souscrit et prix du catalogue (F-08) : ``reglages["abonnement_mensuel_eur"]`` s'il est fixé,
    sinon le prix du palier du compte de paiement (ou ``reglages["palier"]``) dans ``offres.yaml``.
    ``stripe_actif`` : un abonnement Stripe actif existe — c'est alors le webhook ``invoice.paid`` qui
    propose l'échéance (avec le montant déjà payé), pas l'agent."""
    from controldone.storage import facturation as stock

    compte = stock.compte_paiement(ctx.db, tenant_id)
    palier = (compte.palier if compte and compte.palier else None) or reglages.get("palier")
    stripe_actif = bool(compte and compte.abonnement_id and (compte.statut_abonnement or "") in ("active", "trialing"))
    prix = reglages.get("abonnement_mensuel_eur")
    if prix is None:
        try:
            from controldone.facturation.offres import charger_offres

            cat = charger_offres()
            p = cat.palier(palier) if palier else cat.paliers[0]
            prix, palier = p.prix_mensuel_ht, p.code
        except Exception:
            prix = "99.00"
    return {"prix": str(prix), "palier": palier, "stripe_actif": stripe_actif}


def lire_client(ctx: ContexteAgent) -> dict[str, Any]:
    """Raison sociale, offre et réglages utiles du client du contexte."""
    t = _exiger_client(ctx)
    with perimetre(ctx.db, t, ctx.acteur, lecture=True) as sc:
        c = sc.client()
        raison_sociale, offre, r = c.raison_sociale, c.offre, dict(c.reglages or {})
    abonnement = _abonnement(ctx, t, r)  # hors du périmètre : lit les tables de facturation (plateforme)
    return {"raison_sociale": raison_sociale, "offre": offre, "contacts": destinataires_client(r, t),
            "diagnostic_prix_eur": str(r.get("diagnostic_prix_eur", "390.00")),
            "abonnement_mensuel_eur": abonnement["prix"], "abonnement_palier": abonnement["palier"],
            "abonnement_stripe_actif": abonnement["stripe_actif"],
            "litiges_inactivite_jours": int(r.get("litiges_inactivite_jours", 60)),
            "seuil_confiance_revue": float(r.get("seuil_confiance_revue", 0.70))}


def lister_lots(ctx: ContexteAgent, statut: str | None = None) -> list[dict[str, Any]]:
    t = _exiger_client(ctx)
    with perimetre(ctx.db, t, ctx.acteur, lecture=True) as sc:
        filtres = {"statut": statut} if statut else {}
        return [{"id": x.id, "statut": x.statut, "canal": x.canal, "recu_le": _iso(x.recu_le),
                 "resume": dict(x.resume or {})} for x in sc.lister(Lot, ordre=Lot.recu_le, **filtres)]


def lire_dossiers_du_lot(ctx: ContexteAgent, lot_id: str) -> list[dict[str, Any]]:
    """Dossiers d'un lot avec leurs pièces manquantes (dossier incomplet et résultat P1, §9)."""
    t = _exiger_client(ctx)
    with perimetre(ctx.db, t, ctx.acteur, lecture=True) as sc:
        sc.obtenir(Lot, lot_id)
        sortie = []
        for d in sc.lister(DossierRow, lot_id=lot_id, ordre=DossierRow.id):
            contenu = d.contenu or {}
            manquants = set(contenu.get("documents_manquants") or [])
            for r in sc.lister(Resultat, dossier_id=d.id, controle_id="P1"):
                if r.outcome != "conforme":
                    manquants |= set(((r.contenu or {}).get("details") or {}).get("documents_manquants") or [])
            sortie.append({"dossier_id": d.id, "reference": d.reference, "version": d.version,
                           "incomplet": bool(contenu.get("incomplet")) or bool(manquants),
                           "documents_manquants": sorted(manquants), "cles": contenu.get("cles") or {}})
        return sortie


def _valeurs(noeud: Any, chemin: str = "") -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    if isinstance(noeud, dict):
        if isinstance(noeud.get("confiance"), int | float) and ("valeur" in noeud or "chemin" in noeud):
            out.append((str(noeud.get("chemin") or chemin), float(noeud["confiance"])))
            return out
        for k, v in noeud.items():
            out += _valeurs(v, f"{chemin}.{k}" if chemin else str(k))
    elif isinstance(noeud, list):
        for i, v in enumerate(noeud):
            out += _valeurs(v, f"{chemin}[{i}]")
    return out


def lister_extractions_peu_fiables(ctx: ContexteAgent, seuil: float = 0.70) -> list[dict[str, Any]]:
    """Dossiers dont des valeurs lues ont une confiance inférieure au seuil (chemins seulement)."""
    t = _exiger_client(ctx)
    with perimetre(ctx.db, t, ctx.acteur, lecture=True) as sc:
        dossiers = {d.id: d for d in sc.lister(DossierRow)}
        par_dossier: dict[str, list[str]] = {}
        for doc in sc.lister(Document, ordre=Document.id):
            if not doc.dossier_id:
                continue
            faibles = [c for c, conf in _valeurs((doc.contenu or {}).get("champs") or {}) if conf < seuil]
            if faibles:
                par_dossier.setdefault(doc.dossier_id, []).extend(faibles)
        return [{"dossier_id": did, "reference": dossiers[did].reference if did in dossiers else None,
                 "version": dossiers[did].version if did in dossiers else None, "nombre": len(ch),
                 "chemins": sorted(set(ch))[:10]} for did, ch in sorted(par_dossier.items())]


def lister_constats_publies(ctx: ContexteAgent) -> list[dict[str, Any]]:
    """Constats **publiés** (validés) du client, tels que le client les voit dans son rapport."""
    t = _exiger_client(ctx)
    with perimetre(ctx.db, t, ctx.acteur, lecture=True) as sc:
        dossiers = {d.id: d for d in sc.lister(DossierRow)}
        sortie = []
        for c in sc.lister(Constat, statut_validation="valide", ordre=Constat.id):
            cj = c.contenu or {}
            d = dossiers.get(c.dossier_id)
            sortie.append({
                "constat_id": c.id, "dossier_id": c.dossier_id, "dossier_reference": d.reference if d else None,
                "cles": (d.contenu or {}).get("cles") if d else {}, "controle_id": c.controle_id,
                "niveau": c.niveau, "libelle": cj.get("libelle") or "",
                "montant_en_jeu": str(c.montant_en_jeu) if c.montant_en_jeu is not None else None,
                "nature_montant": c.nature_montant, "composante": cj.get("composante"),
                "renvoi": bool(cj.get("renvoi")),
            })
        return sortie


def _resume_litige(d: Any, restes: dict[str, Decimal]) -> dict[str, Any]:
    return {"id": d.id, "statut": d.statut.value, "transitaire_id": d.transitaire_id, "factures": d.factures,
            "total_demande": str(d.total_demande), "reste": str(sum(restes.values(), Decimal("0.00"))),
            "envoyee_le": _iso(d.envoyee_le), "derniere_activite": _iso(d.derniere_activite),
            "cree_le": _iso(d.cree_le),
            "commissions": [{"avoir_id": c.avoir_id, "base": str(c.base), "taux": str(c.taux),
                             "montant": str(c.montant), "outbox_id": c.outbox_id,
                             "le": _iso(c.le)} for c in d.commissions]}


def lister_litiges(ctx: ContexteAgent) -> list[dict[str, Any]]:
    from controldone.litiges.modele import DossierReclamation

    t = _exiger_client(ctx)
    with perimetre(ctx.db, t, ctx.acteur, lecture=True) as sc:
        sortie = []
        for r in sc.lister(Reclamation, ordre=Reclamation.id):
            d = DossierReclamation.model_validate(r.contenu)
            restes = {e: sc.lire_ecart(e).reste for e in d.ecart_ids}
            sortie.append(_resume_litige(d, restes))
        return sortie


def lister_litiges_inactifs(ctx: ContexteAgent, jours: int = 60) -> list[str]:
    t = _exiger_client(ctx)
    return [d.id for d in ServiceLitiges(ctx.db, horloge=ctx.horloge).inactifs(ctx.acteur, t, jours=jours)]


def lister_ecarts_a_reclamer(ctx: ContexteAgent) -> list[dict[str, Any]]:
    """Par transitaire : constats validés recouvrables (``ecart_certain``) pas encore repris dans un
    dossier de demande d'avoir actif."""
    t = _exiger_client(ctx)
    service = ServiceLitiges(ctx.db, horloge=ctx.horloge)
    with perimetre(ctx.db, t, ctx.acteur, lecture=True) as sc:
        actives = {r.id for r in sc.lister(Reclamation)
                   if (r.contenu or {}).get("statut") != StatutReclamation.abandonnee.value}
        par_tra: dict[str, list[Decimal]] = {}
        for c in service.constats_eligibles(sc):
            if c.niveau != "ecart_certain":
                continue
            try:
                e = sc.lire_ecart(id_ecart(t, c.id))
                if e.reclamation_id in actives or e.statut.value in ("credite", "abandonne"):
                    continue
            except AccesRefuse:
                pass
            tra = sc.lire_dossier(c.dossier_id).transitaire_id
            if tra:
                par_tra.setdefault(tra, []).append(Decimal(c.montant_en_jeu))
        return [{"transitaire_id": k, "nombre": len(v), "total": str(sum(v, Decimal("0.00")))}
                for k, v in sorted(par_tra.items())]


# --- propositions (seules écritures) -----------------------------------------------------------------------


def proposer_courriel_client(ctx: ContexteAgent, objet: str, corps: str, cle: str,
                             donnees: dict[str, Any] | None = None) -> str:
    """Brouillon ``email_client`` adressé aux contacts **du client du contexte** (l'agent ne choisit pas
    les destinataires). ``donnees`` : identifiants et données entrantes citées (non rédigées par nous)."""
    t = _exiger_client(ctx)
    contacts = lire_client(ctx)["contacts"]
    payload: dict[str, Any] = {"objet": objet, "corps": corps, "destinataires": contacts,
                               "destinataire_role": "client", "agent": ctx.agent}
    if donnees:
        payload["donnees_entrantes"] = donnees
    return FileSortante(ctx.db).proposer("email_client", payload, ctx.acteur, tenant_id=t,
                                         idempotency_key=_cle(ctx, cle)).id


def proposer_facture(ctx: ContexteAgent, type_facture: TYPES_FACTURE, lignes: list[dict[str, str]], cle: str,
                     references: dict[str, str] | None = None) -> str:
    """Brouillon ``facture_emise`` (diagnostic, abonnement, commission) : ``lignes`` =
    ``[{"libelle": …, "prix_unitaire_ht": "390.00", "quantite": "1"}]``."""
    t = _exiger_client(ctx)
    client = lire_client(ctx)
    lf = [LigneFacture(libelle=x["libelle"], prix_unitaire_ht=Decimal(x["prix_unitaire_ht"]),
                       quantite=Decimal(x.get("quantite", "1"))) for x in lignes]
    payload = payload_facture(type_facture, lf, destinataires=client["contacts"],
                              raison_sociale=client["raison_sociale"], references=references)
    return FileSortante(ctx.db).proposer("facture_emise", payload, ctx.acteur, tenant_id=t,
                                         idempotency_key=_cle(ctx, cle)).id


def proposer_note_veille(ctx: ContexteAgent, objet: str, corps: str, cle: str,
                         sources: list[dict[str, str]] | None = None) -> str:
    """Note de veille pour le fondateur (brouillon de plateforme, jamais publié)."""
    if ctx.tenant_id is not None:
        raise AccesRefuse("note de veille : agent de plateforme seulement")
    payload = {"objet": objet, "corps": corps, "destinataires": ["fondateur"], "publication": "jamais",
               "donnees_entrantes": {"sources": sources or []}}
    return FileSortante(ctx.db).proposer("note_veille", payload, ctx.acteur, tenant_id=None,
                                         idempotency_key=cle).id


def signaler_alerte(ctx: ContexteAgent, cle: str, kind: KINDS_ALERTE, message: str,
                    details: dict[str, str | int] | None = None) -> bool:
    """Alerte au tableau de bord du fondateur (dédoublonnée par ``cle``), sans contenu de document."""
    t = _exiger_client(ctx)
    with perimetre(ctx.db, t, ctx.acteur) as sc:
        return sc.signaler_alerte(cle=cle, kind=kind, message=message[:500], details=dict(details or {}))


def demander_job(ctx: ContexteAgent, kind: KINDS_JOB, payload: dict[str, str], cle: str) -> str:
    """Demande de traitement (job idempotent) pour le client du contexte."""
    from controldone.jobs import JobStore

    t = _exiger_client(ctx)
    job, _ = JobStore(ctx.db).enqueue(kind, dict(payload), _cle(ctx, cle), t)
    return job.id


def planifier_relances(ctx: ContexteAgent) -> list[str]:
    """Brouillons ``relance`` échus, adressés au client (``ServiceLitiges.creer_relances_dues``)."""
    t = _exiger_client(ctx)
    return ServiceLitiges(ctx.db, horloge=ctx.horloge).creer_relances_dues(
        t, maintenant_=ctx.maintenant(), acteur=ctx.acteur)


# --- veille (plateforme) ------------------------------------------------------------------------------------


def lire_sources(ctx: ContexteAgent) -> list[dict[str, str]]:
    from .veille_sources import SOURCES

    return [s.en_dict() for s in SOURCES]


def telecharger_source(ctx: ContexteAgent, url: str) -> dict[str, Any]:
    """Télécharge une source officielle (liste blanche de domaines) ; renvoie empreinte et taille."""
    from .veille_sources import DomaineNonAutorise, domaine_autorise, telecharger

    if not domaine_autorise(url):
        raise DomaineNonAutorise("domaine hors liste blanche")
    if not ctx.reseau:
        return {"url": url, "statut": "non_verifie", "motif": "hors_ligne"}
    return telecharger(url, client=ctx.services.get("http"))


def _chemin_instantanes() -> Path:
    from controldone.config import get_settings

    return Path(get_settings().data_dir) / "veille" / "instantanes.json"


def lire_instantanes(ctx: ContexteAgent) -> dict[str, Any]:
    p = _chemin_instantanes()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def enregistrer_instantanes(ctx: ContexteAgent, instantanes: dict[str, dict[str, str]]) -> int:
    """État propre de l'agent de veille (empreintes des pages), hors base métier."""
    p = _chemin_instantanes()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(instantanes, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return len(instantanes)


CATALOGUE: dict[str, Outil] = {o.nom: o for o in (
    Outil("lire_client", "Raison sociale, offre et réglages utiles du client", lire_client),
    Outil("lister_lots", "Lots du client (statut, canal, résumé)", lister_lots),
    Outil("lire_dossiers_du_lot", "Dossiers d'un lot et pièces manquantes (P1)", lire_dossiers_du_lot),
    Outil("lister_extractions_peu_fiables", "Dossiers à valeurs lues de faible confiance",
          lister_extractions_peu_fiables),
    Outil("lister_constats_publies", "Constats publiés (validés) du client", lister_constats_publies),
    Outil("lister_litiges", "Dossiers de demande d'avoir du client", lister_litiges),
    Outil("lister_litiges_inactifs", "Litiges en cours sans activité depuis N jours", lister_litiges_inactifs),
    Outil("lister_ecarts_a_reclamer", "Écarts validés pas encore demandés, par transitaire",
          lister_ecarts_a_reclamer),
    Outil("proposer_courriel_client", "Brouillon de courriel au client (validation du fondateur)",
          proposer_courriel_client),
    Outil("proposer_facture", "Brouillon de facture (validation du fondateur)", proposer_facture),
    Outil("proposer_note_veille", "Note de veille pour le fondateur (brouillon)", proposer_note_veille),
    Outil("signaler_alerte", "Alerte au fondateur", signaler_alerte),
    Outil("demander_job", "Demande de job (traitement d'un lot, préparation d'un dossier)", demander_job),
    Outil("planifier_relances", "Brouillons de relance au client échus", planifier_relances),
    Outil("lire_sources", "Sources officielles suivies", lire_sources),
    Outil("telecharger_source", "Téléchargement d'une source officielle (liste blanche)", telecharger_source),
    Outil("lire_instantanes", "Dernières empreintes des sources", lire_instantanes),
    Outil("enregistrer_instantanes", "Nouvelles empreintes des sources", enregistrer_instantanes),
)}
