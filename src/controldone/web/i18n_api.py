"""Page de documentation de l'API (``/api/v1/docs``) en anglais (bloc I4, D-4802).

Le schéma OpenAPI (``/api/v1/openapi.json``) reste tel quel (en français) ; seule la page HTML rendue par le
serveur suit la langue de l'interface : résumés et descriptions des opérations traduits par ce catalogue (clé :
texte français exact du schéma), introduction anglaise. L'avertissement exact reste en français (SPEC §3.3),
suivi de sa traduction de courtoisie. Un test exige une traduction pour chaque résumé et description du schéma."""

from __future__ import annotations

import re

__all__ = ["DESCRIPTION_EN", "NATURE_EN", "description_operation", "resume_operation"]

NATURE_EN = (
    "Factual discrepancies observed between documents (comparisons and calculations); this is neither legal, tax "
    "or customs advice, nor an opinion on sums legally owed."
)

DESCRIPTION_EN = f"""ControlDOne API (technical consistency check of import documents).

**Authentication**: `Authorization: Bearer cdk_<prefix>_<secret>` (a client's API key, created by the founder).
The client is the key's client; an identifier belonging to another client returns `404`, like an identifier that
does not exist.

**Publication**: only findings validated by the founder are returned.

**Nature of the results**: {NATURE_EN}

**Language**: field names, codes and the texts of findings, reports and statements are in French (the French text
prevails); this page is a translation of the documentation.
"""

#: Résumé d'une opération (``summary`` du schéma, texte français exact) -> anglais.
RESUMES_EN: dict[str, str] = {
    "Déposer un dossier (fichiers ou archive ZIP)": "Upload a file (documents or ZIP archive)",
    "État d'un dépôt": "Status of an upload",
    "Réception d'une facture électronique (Factur-X, UBL, CII) : contrôle avant paiement": (
        "Receive an e-invoice (Factur-X, UBL, CII): check before payment"
    ),
    "Lister les dossiers": "List files",
    "Lire un dossier (documents et constats publiés)": "Read a file (documents and published findings)",
    "Constats publiés d'un dossier": "Published findings of a file",
    "Rapports et relevés d'écarts mis à disposition": "Reports and discrepancy statements made available",
    "Télécharger un rapport (PDF, HTML ou JSON)": "Download a report (PDF, HTML or JSON)",
    "Suivi des avoirs reçus (écarts constatés et avoirs enregistrés)": (
        "Credit notes received (observed discrepancies and recorded credit notes)"
    ),
    "Suivre un écart et ses avoirs": "Follow a discrepancy and its credit notes",
    "Enregistrer un événement : courrier envoyé par vous, avoir reçu": (
        "Record an event: letter sent by you, credit note received"
    ),
    "Suivi des avoirs reçus (alias de /litiges)": "Credit notes received (alias of /litiges)",
    "Suivre un écart (alias de /litiges/{id})": "Follow a discrepancy (alias of /litiges/{id})",
    "Enregistrer un événement (alias de /litiges/{id}/evenements)": (
        "Record an event (alias of /litiges/{id}/evenements)"
    ),
}

#: Description d'une opération (docstring, espaces normalisés) -> anglais.
DESCRIPTIONS_EN: dict[str, str] = {
    "Point d'entrée simple pour une facture électronique **reçue par le client** (Factur-X en PDF, UBL ou CII en "
    "XML) : dépôt d'un lot `api` marqué « avant paiement » et mise en file du contrôle. Le produit n'est pas une "
    "plateforme de facturation électronique : ni émission, ni transmission, ni statut de cycle de vie. Corps : "
    "multipart (champ `fichier`) ou octets bruts (`Content-Type: application/xml` ou `application/pdf`, nom "
    "facultatif dans l'en-tête `X-Filename`).": (
        "Simple entry point for an e-invoice **received by the client** (Factur-X as PDF, UBL or CII as XML): "
        "upload of an `api` batch marked “before payment” and queuing of the check. The product is not an "
        "e-invoicing platform: no issuing, no transmission, no lifecycle status. Body: multipart (field "
        "`fichier`) or raw bytes (`Content-Type: application/xml` or `application/pdf`, optional name in the "
        "`X-Filename` header)."
    ),
}


def _normal(texte: str) -> str:
    return re.sub(r"\s+", " ", texte or "").strip()


def resume_operation(texte: str, langue: str) -> str:
    return RESUMES_EN.get(texte, texte) if langue == "en" else texte


def description_operation(texte: str, langue: str) -> str:
    if langue != "en" or not texte:
        return texte
    return DESCRIPTIONS_EN.get(_normal(texte), texte)
