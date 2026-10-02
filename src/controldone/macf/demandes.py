"""Liste des données à obtenir des fournisseurs et brouillons de demande (jamais envoyés).

Les brouillons sont rédigés à la première personne du client, qui les relit et les envoie lui-même à
son fournisseur. Ils passent par la file sortante (``email_client`` : mise à disposition du client),
qui applique les garde-fous ; rien n'est envoyé par ce module.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from controldone.guardrails import AVERTISSEMENT, PHRASE_RENVOI, assert_clean
from controldone.macf.selection import LigneMACF

__all__ = [
    "DONNEES_A_DEMANDER",
    "MENTION_PREPARATION",
    "DonneeADemander",
    "brouillons_demandes",
    "proposer_brouillons",
]

MENTION_PREPARATION = "préparation — à vérifier par le déclarant MACF autorisé"


@dataclass(frozen=True)
class DonneeADemander:
    id: str
    libelle: str
    precision: str
    libelle_en: str


DONNEES_A_DEMANDER: tuple[DonneeADemander, ...] = (
    DonneeADemander("installation", "Identification de l'installation de production",
                    "Nom, adresse, pays et identifiant de l'installation (et de l'exploitant) où les marchandises "
                    "ont été produites ; coordonnées géographiques si disponibles.",
                    "Identification of the production installation (name, address, country, identifier, operator)"),
    DonneeADemander("emissions_directes", "Émissions intrinsèques directes",
                    "Émissions directes par tonne de marchandise (t CO2e/t), avec la méthode de détermination "
                    "et la période de déclaration de l'installation.",
                    "Direct embedded emissions per tonne of goods (t CO2e/t), with method and reporting period"),
    DonneeADemander("emissions_indirectes", "Émissions intrinsèques indirectes",
                    "Émissions liées à l'électricité consommée, si elles sont communiquées, avec leur source.",
                    "Indirect embedded emissions (electricity consumed), if provided, with source"),
    DonneeADemander("valeurs_reelles_ou_defaut", "Nature des valeurs",
                    "Préciser si les valeurs communiquées sont des valeurs réelles mesurées ou des valeurs "
                    "par défaut, et joindre tout rapport de vérification disponible.",
                    "Whether values are actual or default values; any verification report available"),
    DonneeADemander("procede", "Voie de production",
                    "Voie de production ou procédé utilisé pour les marchandises livrées.",
                    "Production route / process used for the goods delivered"),
    DonneeADemander("prix_carbone", "Prix du carbone payé dans le pays d'origine",
                    "Montant, devise, période et justificatif d'un éventuel prix du carbone effectivement payé "
                    "pour ces émissions, et toute remise ou compensation reçue.",
                    "Carbon price effectively paid in the country of origin (amount, currency, period, evidence)"),
    DonneeADemander("correspondance", "Correspondance avec les livraisons",
                    "Références de facture et quantités livrées couvertes par ces données.",
                    "Invoice references and quantities delivered covered by the data"),
)


def _liste_fr() -> str:
    return "\n".join(f"- {d.libelle} : {d.precision}" for d in DONNEES_A_DEMANDER)


def _liste_en() -> str:
    return "\n".join(f"- {d.libelle_en}" for d in DONNEES_A_DEMANDER)


def _detail_lignes(lignes: Sequence[LigneMACF]) -> str:
    out = []
    for li in lignes:
        masse = f"{li.masse_nette_kg} kg" if li.masse_nette_kg is not None else "masse non lue"
        out.append(f"- code {li.code_imprime or 'non lu'} ; origine {li.pays_origine or 'non lue'} ; {masse} ; "
                   f"déclaration {li.mrn or 'non lue'} du {li.date_acceptation or 'date non lue'}")
    return "\n".join(out)


def brouillons_demandes(lignes: Iterable[LigneMACF], *, annee: int, client: str) -> list[dict[str, Any]]:
    """Un brouillon de demande par fournisseur (nom imprimé), contenu prêt pour la file sortante."""
    par_fournisseur: dict[str, list[LigneMACF]] = {}
    for li in lignes:
        if li.annee == annee:
            par_fournisseur.setdefault(li.fournisseur or "fournisseur non lu", []).append(li)
    brouillons = []
    for fournisseur in sorted(par_fournisseur):
        ls = par_fournisseur[fournisseur]
        objet = f"Données MACF (CBAM) {annee} — demande d'informations / CBAM data request"
        corps_fournisseur = (
            f"Bonjour,\n\nNous avons importé dans l'Union européenne en {annee} les marchandises ci-dessous, "
            f"livrées par {fournisseur}. Pour préparer notre déclaration MACF (CBAM), pourriez-vous nous "
            f"communiquer, pour chaque installation de production concernée :\n{_liste_fr()}\n\n"
            f"Livraisons concernées (données lues sur nos déclarations d'import) :\n{_detail_lignes(ls)}\n\n"
            "Merci d'avance.\n\n[Signature du client]\n\n"
            "---\n\nHello,\n\n"
            f"We imported into the European Union in {annee} the goods listed above, supplied by {fournisseur}. "
            "To prepare our CBAM declaration, could you please send us, for each production installation:\n"
            f"{_liste_en()}\n\nThank you.\n\n[Client signature]"
        )
        note_client = (
            f"Brouillon de demande à votre fournisseur {fournisseur}, préparé par ControlDOne à partir de vos "
            f"déclarations ({len(ls)} ligne(s)). Relisez-le, complétez l'adresse du destinataire et envoyez-le "
            f"vous-même si vous le souhaitez. Mention : {MENTION_PREPARATION}.\n\n{PHRASE_RENVOI}\n\n{AVERTISSEMENT}"
        )
        for t in (objet, corps_fournisseur, note_client):
            assert_clean(t)
        cle = hashlib.sha256(f"{client}|{annee}|{fournisseur}".encode()).hexdigest()[:16]
        brouillons.append({
            "objet": objet,
            "corps": note_client + "\n\n=== Brouillon pour le fournisseur ===\n\n" + corps_fournisseur,
            "destinataires": [],
            "destinataire_role": "client",
            "nature": "macf_demande_fournisseur",
            "fournisseur": fournisseur,
            "annee": annee,
            "ref": cle,
            "refs": sorted({li.declaration_id for li in ls}),
        })
    return brouillons


def proposer_brouillons(file: Any, brouillons: Iterable[dict[str, Any]], acteur: Any, *, tenant_id: str) -> list[Any]:
    """Dépose chaque brouillon dans la file sortante (statut ``brouillon`` ; jamais envoyé ici)."""
    actions = []
    for b in brouillons:
        actions.append(file.proposer("email_client", b, acteur, tenant_id=tenant_id,
                                     idempotency_key=f"macf:{tenant_id}:{b['annee']}:{b['ref']}"))
    return actions
