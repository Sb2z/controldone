"""Données de démonstration du module de prospection (``controldone init-demo``) : sociétés **fictives** seulement,
marquées FICTIF, domaines en ``.test`` (jamais résolus), aucun courriel préparé (la file de validation de la
démonstration reste celle des clients fictifs). Identifiants fixes ``prs_demo_*`` (tests de l'interface)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from controldone.auth.roles import Acteur
from controldone.prospection.exclusion import normaliser_nom
from controldone.prospection.service import ServiceProspection
from controldone.storage import prospection as stock
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database

__all__ = ["PROSPECTS_DEMO", "semer_demo"]

PROSPECTS_DEMO: list[dict[str, Any]] = [
    {
        "id": "prs_demo_1",
        "raison_sociale": "COMPTOIR ASIE DÉMO FICTIF SAS",
        "naf": "46.38B",
        "tranche_effectif": "12",
        "departement": "69",
        "ville": "Lyon",
        "statut": "qualifie",
        "preuve_import": "« Nous importons nos produits directement de Thaïlande et du Vietnam » (texte FICTIF)",
        "domaine": "comptoir-asie-demo-fictif.test",
        "adresse": "contact",
        "douane": "oui",
    },
    {
        "id": "prs_demo_2",
        "raison_sociale": "JOUETS IMPORT DÉMO FICTIF SARL",
        "naf": "46.49Z",
        "tranche_effectif": "21",
        "departement": "13",
        "ville": "Marseille",
        "statut": "a_repondu",
        "preuve_import": "« Importateur de jouets fabriqués en Chine depuis 1995 » (texte FICTIF)",
        "domaine": "jouets-import-demo-fictif.test",
        "adresse": "info",
        "douane": "oui",
        "reponse": "Bonjour, le sujet nous intéresse. Pouvez-vous m'appeler la semaine prochaine ? (réponse FICTIVE)",
    },
    {
        "id": "prs_demo_3",
        "raison_sociale": "CAFÉS VERTS DÉMO FICTIF",
        "naf": "46.37Z",
        "tranche_effectif": "11",
        "departement": "76",
        "ville": "Rouen",
        "statut": "a_qualifier",
        "preuve_import": None,
        "domaine": "cafes-verts-demo-fictif.test",
        "adresse": None,
        "douane": "inconnu",
    },
    {
        "id": "prs_demo_4",
        "raison_sociale": "TEXTILES DU MONDE DÉMO FICTIF SAS",
        "naf": "46.41Z",
        "tranche_effectif": "22",
        "departement": "59",
        "ville": "Roubaix",
        "statut": "rendez_vous",
        "preuve_import": "« Nos tissus viennent d'Inde et du Pakistan » (texte FICTIF)",
        "domaine": "textiles-monde-demo-fictif.test",
        "adresse": "commercial",
        "douane": "inconnu",
    },
    {
        "id": "prs_demo_5",
        "raison_sociale": "HORLOGERIE DÉMO FICTIF SA",
        "naf": "46.48Z",
        "tranche_effectif": "12",
        "departement": None,
        "ville": "Lausanne",
        "pays": "CH",
        "statut": "a_qualifier",
        "preuve_import": "« Composants achetés en Asie » (texte FICTIF)",
        "domaine": "horlogerie-demo-fictif.test",
        "adresse": "contact",
        "douane": "non",
    },
    {
        "id": "prs_demo_6",
        "raison_sociale": "OUTILLAGE DÉMO FICTIF",
        "naf": "46.74A",
        "tranche_effectif": "03",
        "departement": "33",
        "ville": "Bordeaux",
        "statut": "perdu",
        "preuve_import": None,
        "domaine": "outillage-demo-fictif.test",
        "adresse": None,
        "douane": "inconnu",
    },
]


def semer_demo(db: Database, acteur: Acteur) -> int:
    """Insère les prospects fictifs (idempotent) ; renvoie le nombre de prospects créés."""
    svc = ServiceProspection(db)
    n = 0
    aujourdhui = maintenant()
    with db.transaction_systeme() as s:
        for i, d in enumerate(PROSPECTS_DEMO):
            if stock.lire_prospect(s, d["id"]) is not None:
                continue
            site = f"https://{d['domaine']}"
            p = stock.inserer_prospect(
                s,
                id=d["id"],
                raison_sociale=d["raison_sociale"],
                nom_normalise=normaliser_nom(d["raison_sociale"]),
                naf=d["naf"],
                tranche_effectif=d["tranche_effectif"],
                pays=d.get("pays", "FR"),
                departement=d["departement"],
                ville=d["ville"],
                site_web=site,
                statut="a_qualifier",
                source="demo",
                source_url=f"{site}/mentions-legales",
                source_detail="démonstration : données FICTIVES",
                preuve_import=d["preuve_import"],
                preuve_url=f"{site}/qui-sommes-nous" if d["preuve_import"] else None,
                sans_service_douane=d["douane"],
                collecte_le=date.today() - timedelta(days=30 - 3 * i),
                demo=True,
            )
            svc._evenement(s, p.id, "creation", acteur.id, vers="a_qualifier", details={"source": "demo"})
            if d["adresse"]:
                a = f"{d['adresse']}@{d['domaine']}"
                from controldone.prospection import contacts as adr

                stock.ajouter_contact(
                    s,
                    id=f"pct_demo_{i + 1}",
                    prospect_id=p.id,
                    genre="courriel",
                    adresse=a,
                    nature=adr.nature_adresse(a),
                    empreinte=adr.empreinte(a),
                    source_url=f"{site}/contact",
                    origine="demo",
                    cree_par=acteur.id,
                    cree_le=aujourdhui,
                )
            svc._rescorer(s, p)
            if d["statut"] != "a_qualifier":
                for etape in ("qualifie", "contacte", "a_repondu", "rendez_vous"):
                    if d["statut"] == "perdu" and etape == "contacte":
                        break
                    svc._evenement(s, p.id, "statut", acteur.id, de=p.statut, vers=etape)
                    p.statut = etape
                    if etape == d["statut"]:
                        break
                if d["statut"] == "perdu":
                    svc._evenement(s, p.id, "statut", acteur.id, de=p.statut, vers="perdu")
                    p.statut = "perdu"
            if d.get("reponse"):
                svc._evenement(s, p.id, "reponse", acteur.id, texte=d["reponse"])
                p.derniere_interaction_le = aujourdhui
            svc._evenement(
                s, p.id, "note", acteur.id, texte="Prospect de démonstration : société et faits FICTIFS."
            )
            n += 1
    return n
