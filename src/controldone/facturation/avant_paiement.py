"""Côté client : contrôle **avant paiement** d'une facture électronique de transitaire.

Deux entrées, un même chemin (``connecteurs.jobs.controle_avant_paiement``) :

- connecteur ``PlateformeAgreeeEntrante`` (factures que la PA du client met à sa disposition) ;
- API ``POST /api/v1/einvoices`` : le lot déposé est marqué « avant paiement » et ce module met en file
  le job ``controle_avant_paiement`` (en plus de ``traiter_lot``).

Le job traite le lot puis, s'il y a des écarts certains recouvrables, **propose** au client (brouillon
``statut_litige_pa`` validé par le fondateur) de passer lui-même la facture au statut « en litige » dans
sa PA, avec le motif chiffré. ControlDOne ne pose aucun statut : il n'est pas une plateforme agréée.

Le numéro et l'échéance de la facture sont lus dans le XML comme des **données** (analyseur sans entités
ni réseau), uniquement pour libeller la proposition.
"""

from __future__ import annotations

from datetime import date

from lxml import etree

from controldone.storage.db import Database
from controldone.storage.file_jobs import JobStore

__all__ = ["lire_reference_facture", "mettre_en_file_controle"]

_PARSEUR = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
_XP = {
    "numero": (
        "//*[local-name()='ExchangedDocument']/*[local-name()='ID']",
        "/*[local-name()='Invoice']/*[local-name()='ID']",
    ),
    "echeance": (
        "//*[local-name()='SpecifiedTradePaymentTerms']/*[local-name()='DueDateDateTime']/*",
        "/*[local-name()='Invoice']/*[local-name()='DueDate']",
    ),
}


def _xml(contenu: bytes) -> bytes | None:
    if contenu[:5] == b"%PDF-":
        try:
            import facturx

            _nom, xml = facturx.get_xml_from_pdf(contenu, check_xsd=False)
            return xml or None
        except Exception:
            return None
    return contenu


def lire_reference_facture(contenu: bytes | None) -> tuple[str | None, str | None]:
    """``(numéro, échéance ISO)`` lus dans une facture CII, UBL ou Factur-X ; ``(None, None)`` si illisible."""
    if not contenu:
        return None, None
    xml = _xml(contenu)
    if not xml:
        return None, None
    try:
        racine = etree.fromstring(xml, parser=_PARSEUR)
    except etree.XMLSyntaxError:
        return None, None
    sortie: dict[str, str | None] = {"numero": None, "echeance": None}
    for cle, chemins in _XP.items():
        for xp in chemins:
            r = racine.xpath(xp)
            if r and (r[0].text or "").strip():
                sortie[cle] = r[0].text.strip()[:35]
                break
    ech = sortie["echeance"]
    if ech and len(ech) == 8 and ech.isdigit():
        ech = f"{ech[:4]}-{ech[4:6]}-{ech[6:]}"
    try:
        ech = date.fromisoformat(ech).isoformat() if ech else None
    except ValueError:
        ech = None
    return sortie["numero"], ech


def mettre_en_file_controle(db: Database, tenant_id: str, lot_id: str, contenu: bytes | None) -> str:
    """Met en file ``controle_avant_paiement`` pour un lot reçu par l'API (idempotent par lot)."""
    numero, echeance = lire_reference_facture(contenu)
    pa_id = f"api:{lot_id}"
    payload = {
        "lot_id": lot_id,
        "facture_pa_id": pa_id,
        **({"numero": numero} if numero else {}),
        **({"date_echeance": echeance} if echeance else {}),
    }
    job, _ = JobStore(db).enqueue(
        "controle_avant_paiement", payload, f"controle_avant_paiement:{tenant_id}:{pa_id}", tenant_id
    )
    return job.id
