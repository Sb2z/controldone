"""Connecteur ``PlateformeAgreeeEntrante`` : réception, **avant paiement**, des factures électroniques des
transitaires depuis la plateforme agréée (PA) partenaire du client — interface et bouchon.

**ControlDOne n'est pas une plateforme agréée.** Il n'émet, ne transmet ni ne reçoit de factures sur le
réseau de la réforme, ne gère pas les statuts de cycle de vie et ne fait pas d'e-reporting (SPEC §21.2,
``docs/recherche/einvoice.md``). Ce connecteur lit, avec l'accord du client, les factures que **sa** PA
met à sa disposition (API du partenaire, à brancher derrière ``ClientPA``) ; il en fait un lot contrôlé
avant paiement (job ``controle_avant_paiement``) et, si des écarts sont constatés, **propose** au client
de passer lui-même la facture au statut « en litige » dans sa PA (brouillon ``statut_litige_pa`` validé
par le fondateur puis par le client). Le produit ne pose jamais ce statut lui-même. Le statut « refusée »
n'est jamais proposé : il est réservé à trois motifs prévus par la norme, pas au litige commercial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable

from controldone.auth.roles import Acteur
from controldone.formatage import format_montant
from controldone.guardrails import AVERTISSEMENT
from controldone.litiges import destinataires_client
from controldone.litiges.redaction import LIBELLES_COMPOSANTE
from controldone.model.enums import Composante
from controldone.outbox import FileSortante
from controldone.storage.db import Database
from controldone.storage.models import Constat
from controldone.storage.models import Dossier as DossierRow

from .base import Depot, ResultatDepot

__all__ = [
    "NOTE_PA",
    "ClientPA",
    "ClientPAFictif",
    "FacturePA",
    "PlateformeAgreeeEntrante",
    "proposer_statut_litige",
]

NOTE_PA = (
    "ControlDOne n'est pas une plateforme agréée : il ne transmet aucun statut de cycle de vie. Le statut "
    "« en litige » ci-dessus est une proposition ; c'est vous qui décidez de l'appliquer, depuis votre "
    "plateforme agréée. Le statut « refusée » n'est pas adapté à un écart de montant : il est réservé aux cas "
    "prévus par la norme (facture mal adressée, non-conformité non détectée, conditions contractuelles "
    "empêchant le traitement)."
)


@dataclass(frozen=True)
class FacturePA:
    identifiant: str  # identifiant de la facture chez la PA
    format: str  # factur-x | ubl | cii
    nom_fichier: str
    contenu: bytes
    numero: str | None = None
    date_echeance: date | None = None


@runtime_checkable
class ClientPA(Protocol):
    """Accès en lecture aux factures reçues par le client sur sa PA (API du partenaire)."""

    def factures_recues(self) -> list[FacturePA]: ...

    def accuser_lecture(self, identifiant: str) -> None:
        """Mémorise localement que la facture a été lue (aucun statut n'est transmis)."""
        ...


@dataclass
class ClientPAFictif:
    """Bouchon : factures en mémoire, ou lues dans un dossier (``depuis_dossier``) pour une démonstration."""

    factures: list[FacturePA] = field(default_factory=list)
    lues: set[str] = field(default_factory=set)

    @classmethod
    def depuis_dossier(cls, dossier: Path | str) -> ClientPAFictif:
        sortie = []
        for p in sorted(Path(dossier).glob("*")):
            if p.is_file() and p.suffix.lower() in (".xml", ".pdf"):
                fmt = "factur-x" if p.suffix.lower() == ".pdf" else "ubl"
                sortie.append(
                    FacturePA(identifiant=p.stem, format=fmt, nom_fichier=p.name, contenu=p.read_bytes())
                )
        return cls(sortie)

    def factures_recues(self) -> list[FacturePA]:
        return [f for f in self.factures if f.identifiant not in self.lues]

    def accuser_lecture(self, identifiant: str) -> None:
        self.lues.add(identifiant)


class PlateformeAgreeeEntrante:
    nom = "plateforme_agreee"

    def __init__(self, tenant_id: str, client: ClientPA) -> None:
        self.tenant_id = tenant_id
        self.client = client

    def relever(self) -> list[Depot]:
        return [
            Depot(
                tenant_id=self.tenant_id,
                canal="api",
                source=self.nom,
                elements=[(f"plateforme_agreee/{f.identifiant}/{f.nom_fichier}", f.contenu)],
                reference=f.identifiant,
                meta={
                    "facture_pa_id": f.identifiant,
                    "controle_avant_paiement": True,
                    "format": f.format,
                    "numero": f.numero,
                    "date_echeance": f.date_echeance.isoformat() if f.date_echeance else None,
                },
            )
            for f in self.client.factures_recues()
        ]

    def acquitter(self, depot: Depot, resultat: ResultatDepot) -> None:
        if depot.reference and resultat.statut in ("lot_cree", "deja_recu"):
            self.client.accuser_lecture(depot.reference)


def proposer_statut_litige(
    db: Database,
    tenant_id: str,
    lot_id: str,
    facture_pa_id: str,
    *,
    numero: str | None = None,
    date_echeance: str | None = None,
) -> str | None:
    """Après le contrôle avant paiement : si des écarts certains recouvrables sont constatés (constats non
    rejetés), brouillon ``statut_litige_pa`` adressé au **client** (validation du fondateur, puis décision
    du client). Renvoie l'identifiant du brouillon, ou ``None`` s'il n'y a rien à proposer."""
    acteur = Acteur.systeme("controle_avant_paiement")
    with db.tenant(tenant_id, acteur, lecture=True) as sc:
        dossiers = [d.id for d in sc.lister(DossierRow, lot_id=lot_id)]
        constats = [
            c
            for c in sc.lister(Constat, ordre=Constat.id)
            if c.dossier_id in dossiers
            and c.niveau == "ecart_certain"
            and c.nature_montant == "recouvrable"
            and c.statut_validation != "rejete"
            and c.montant_en_jeu
            and c.montant_en_jeu > 0
        ]
        reglages = sc.client().reglages or {}
    if not constats:
        return None
    total = sum((Decimal(c.montant_en_jeu) for c in constats), Decimal("0.00"))
    par_comp: dict[str, Decimal] = {}
    for c in constats:
        comp = (c.contenu or {}).get("composante")
        libelle = LIBELLES_COMPOSANTE.get(Composante(comp), comp) if comp else "autres"
        par_comp[libelle] = par_comp.get(libelle, Decimal("0.00")) + Decimal(c.montant_en_jeu)
    detail = " ; ".join(f"{k} : {format_montant(v, 'EUR')}" for k, v in sorted(par_comp.items()))
    motif = f"Écarts constatés entre documents : {format_montant(total, 'EUR')} ({detail})."
    echeance = f" (échéance {date_echeance})" if date_echeance else ""
    corps = (
        f"Bonjour,\n\nLa facture n° {numero or facture_pa_id}{echeance}, reçue sur votre plateforme agréée, a été "
        f"contrôlée avant paiement. {motif}\n\nNous vous proposons, si vous le souhaitez, de lui appliquer le "
        "statut « en litige » depuis votre plateforme agréée, avec le motif ci-dessus, le temps d'obtenir les "
        f"explications ou un avoir de votre transitaire.\n\n{NOTE_PA}\n\n{AVERTISSEMENT}"
    )
    payload = {
        "objet": f"Contrôle avant paiement — facture n° {numero or facture_pa_id} : statut « en litige » proposé",
        "corps": corps,
        "destinataires": destinataires_client(reglages, tenant_id),
        "destinataire_role": "client",
        "facture_pa_id": facture_pa_id,
        "statut_propose": "en_litige",
        "motif": motif,
        "validation_client_requise": True,
        "transmission_par": "client",
        "refs": [c.id for c in constats],
    }
    return (
        FileSortante(db)
        .proposer(
            "statut_litige_pa",
            payload,
            acteur,
            tenant_id=tenant_id,
            idempotency_key=f"statut_litige_pa:{tenant_id}:{facture_pa_id}",
        )
        .id
    )
