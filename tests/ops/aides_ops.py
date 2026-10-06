"""Aides des tests d'exploitation : clients FICTIFS peuplés de dossiers, documents et constats."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from controldone.auth.roles import Acteur, Role
from controldone.model.dossier import ClesDossier
from controldone.model.dossier import Dossier as DossierModele
from controldone.storage.models import Constat, Document, Entite, Resultat, Transitaire

FONDATEUR = Acteur("usr_fondateur", Role.fondateur)
SYSTEME = Acteur.systeme("tests")
T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def doc_row(
    doc_id: str,
    type_: str,
    champs: dict[str, str],
    *,
    dossier_id: str | None = None,
    lot_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Document:
    contenu = {
        "id": doc_id,
        "type": type_,
        "champs": {k: {"valeur": v, "confiance": 0.97, "chemin": f"{type_}.{k}"} for k, v in champs.items()},
    }
    contenu.update(extra or {})
    return Document(id=doc_id, type=type_, dossier_id=dossier_id, lot_id=lot_id, contenu=contenu)


def constat_row(
    cid: str,
    dossier_id: str,
    *,
    controle: str = "C1",
    niveau: str = "ecart_certain",
    montant: str | None = "240.00",
    nature: str = "recouvrable",
    composante: str | None = "droit",
    statut: str = "valide",
    docs: tuple[str, ...] = (),
    libelle: str = "",
    preuves: list[dict[str, Any]] | None = None,
    resultat_id: str | None = None,
) -> Constat:
    contenu = {
        "id": cid,
        "controle_id": controle,
        "niveau": niveau,
        "raisons": [] if niveau == "ecart_certain" else ["autre"],
        "libelle": libelle
        or (
            "La facture du transitaire (page 1) indique un montant refacturé de 1 240,00 EUR ; "
            "la déclaration (page 1) indique 1 000,00 EUR."
        ),
        "montant_en_jeu": montant,
        "nature_montant": nature,
        "composante": composante,
        "documents_concernes": list(docs),
        "preuves": preuves or [],
        "renvoi": nature == "renvoi",
        "statut_validation": statut,
        "prochaine_action": "",
    }
    return Constat(
        id=cid,
        resultat_id=resultat_id,
        dossier_id=dossier_id,
        dossier_version=1,
        controle_id=controle,
        niveau=niveau,
        montant_en_jeu=Decimal(montant) if montant else None,
        nature_montant=nature,
        statut_validation=statut,
        valide_par="usr_fondateur" if statut == "valide" else None,
        valide_le=T0 if statut == "valide" else None,
        contenu=contenu,
    )


def peupler_litige(
    db,
    tenant: str,
    *,
    suffixe: str = "",
    transitaire: str = "tra_x",
    montants: tuple[str, ...] = ("240.00", "60.00"),
    lot_id: str | None = None,
) -> dict[str, Any]:
    """Un dossier avec une facture transitaire FICTIVE, une déclaration, deux constats validés
    recouvrables (droit, TVA), un constat proposé, un constat ``a_verifier`` validé et un renvoi."""
    s = suffixe or tenant[-1]
    dos = f"dos_{s}1"
    ft, dec = f"doc_ft_{s}", f"doc_dec_{s}"
    with db.tenant(tenant, SYSTEME) as sc:
        sc._ajouter_interne(
            Entite(
                id=f"ent_{s}",
                raison_sociale=f"IMPORT {s.upper()} SAS FICTIF",
                tva="FR00999999999",
                contenu={"adresses": ["1 rue Fictive, 75000 Paris"]},
            )
        )
        sc._ajouter_interne(
            Transitaire(
                id=transitaire,
                nom=f"TRANSIT {s.upper()} FICTIF",
                tva="FR11888888888",
                contenu={
                    "adresse": "2 quai Fictif, 13000 Marseille",
                    "contact_reclamation": "litiges@transit-fictif.test",
                },
            )
        )
        d = DossierModele(
            id=dos,
            client_id=tenant,
            reference="D-2026-00001",
            transitaire_id=transitaire,
            cles=ClesDossier(
                num_facture_transitaire=[f"FT-{s}-001"],
                mrn=["26FR00000000000001"],
                ref_transport=["AWB-FICTIF-1"],
            ),
            lot_ids=[lot_id] if lot_id else [],
        )
        sc.enregistrer_dossier(d, lot_id=lot_id)
        sc._ajouter_interne(doc_row(ft, "facture_transitaire", {"numero": f"FT-{s}-001"}, dossier_id=dos))
        sc._ajouter_interne(doc_row(dec, "declaration", {"mrn": "26FR00000000000001"}, dossier_id=dos))
        sc._ajouter_interne(
            Resultat(
                id=f"res_{s}1",
                dossier_id=dos,
                dossier_version=1,
                controle_id="C1",
                outcome="ecart_certain",
                contenu={"attendu": "1000.00", "constate": "1240.00"},
            )
        )
        preuves = [
            {"role": "valeur_b", "document_id": ft, "page": 1, "valeur_brute": "1 240,00"},
            {"role": "valeur_a", "document_id": dec, "page": 1, "valeur_brute": "1 000,00"},
        ]
        sc._ajouter_interne(
            constat_row(
                f"f_{s}1",
                dos,
                montant=montants[0],
                composante="droit",
                docs=(ft, dec),
                preuves=preuves,
                resultat_id=f"res_{s}1",
            )
        )
        sc._ajouter_interne(
            constat_row(
                f"f_{s}2",
                dos,
                controle="C4",
                montant=montants[1],
                composante="tva",
                docs=(ft, dec),
                preuves=preuves,
            )
        )
        sc._ajouter_interne(
            constat_row(
                f"f_{s}3",
                dos,
                controle="D3",
                montant="15.00",
                composante="prestation",
                statut="propose",
                docs=(ft,),
            )
        )
        sc._ajouter_interne(
            constat_row(
                f"f_{s}4",
                dos,
                controle="D2",
                niveau="a_verifier",
                montant="30.00",
                composante="prestation",
                docs=(ft,),
            )
        )
        sc._ajouter_interne(
            constat_row(
                f"f_{s}5",
                dos,
                controle="A13",
                niveau="a_verifier",
                montant=None,
                nature="renvoi",
                composante=None,
            )
        )
        sc.flush()
    return {
        "dossier": dos,
        "transitaire": transitaire,
        "ft": ft,
        "dec": dec,
        "constats": [f"f_{s}{i}" for i in range(1, 6)],
    }
