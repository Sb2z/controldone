"""Validation des sorties : schéma truth.json (Annexe B) et contrôles de cohérence du contrat (§19.3.1)."""

from __future__ import annotations

import json
import os

from jsonschema import Draft202012Validator

_SCHEMA = None

MANDATORY = {
    "facture_commerciale": ["numero", "date", "devise", "total_facture", "total_imprime", "acheteur.tva", "incoterm",
                            "lignes", "masse_brute_totale", "nombre_colis"],
    "declaration": ["mrn", "date_acceptation", "importateur.tva", "devise_facture", "montant_total_facture",
                    "taux_change", "taux_change_sens", "incoterm", "nombre_articles", "documents_references",
                    "indices_autoliquidation", "articles", "taxations", "total_a_payer"],
    "facture_transitaire": ["numero", "date", "emetteur.tva", "client_facture.tva", "refs_mrn", "refs_transport",
                            "lignes", "total_debours", "total_ht", "total_tva", "total_ttc"],
    "avoir": ["numero", "date", "refs_facture_origine", "lignes", "total_credite_ttc"],
}
LINE_FIELDS = {
    "facture_commerciale": ["code_marchandise_imprime", "quantite", "unite", "montant_ligne", "pays_origine"],
    "facture_transitaire": ["nature", "libelle", "quantite", "prix_unitaire", "montant_ht", "taux_tva", "montant_tva",
                            "mrn"],
    "avoir": ["nature", "montant_ht"],
}
ART_FIELDS = ["code_marchandise", "pays_origine", "masse_nette", "masse_brute"]
TAX_FIELDS = ["article", "type_taxe", "categorie", "base_montant", "base_quantite", "taux", "montant",
              "paiement_normalise"]


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        with open(os.path.join(os.path.dirname(__file__), "truth.schema.json"), encoding="utf-8") as fh:
            _SCHEMA = json.load(fh)
    return _SCHEMA


def validate_truth(truth: dict):
    v = Draft202012Validator(_schema())
    errs = sorted(v.iter_errors(truth), key=lambda e: list(e.path))
    if errs:
        raise ValueError("; ".join(f"{list(e.path)}: {e.message}" for e in errs[:5]))
    ids = {d["doc_id"] for d in truth["documents"]}
    files = {f["path"] for f in truth["files"]}
    for d in truth["documents"]:
        if d["file"] not in files:
            raise ValueError(f"document {d['doc_id']} : fichier inconnu {d['file']}")
        tv = truth["truth_values"].get(d["doc_id"])
        if tv is None:
            raise ValueError(f"truth_values manquant pour {d['doc_id']}")
        for k in MANDATORY.get(d["type"], []):
            if k not in tv:
                raise ValueError(f"{d['doc_id']} : champ obligatoire {k} absent")
        for line in tv.get("lignes", []):
            for k in LINE_FIELDS.get(d["type"], []):
                if k not in line:
                    raise ValueError(f"{d['doc_id']} : ligne sans {k}")
        if d["type"] == "declaration":
            for a in tv["articles"]:
                for k in ART_FIELDS:
                    if k not in a:
                        raise ValueError(f"{d['doc_id']} : article sans {k}")
            for t in tv["taxations"]:
                for k in TAX_FIELDS:
                    if k not in t:
                        raise ValueError(f"{d['doc_id']} : taxation sans {k}")
    for e in truth["injected_errors"]:
        for x in e["documents"]:
            if x not in ids:
                raise ValueError(f"{e['error_id']} : document {x} absent")
        if e["amount_nature"] in ("aucun", "renvoi") and e["expected_amount_eur"] is not None:
            raise ValueError(f"{e['error_id']} : montant non nul pour nature {e['amount_nature']}")
    for t in truth["traps"]:
        for x in t["documents"]:
            if x not in ids:
                raise ValueError(f"{t['trap_id']} : document {x} absent")
    for l in truth["expected_links"]:
        if l["from"] not in ids or l["to"] not in ids:
            raise ValueError(f"lien vers un document absent : {l}")
    if not truth["injected_errors"] and truth["expected_outcome"] != "conforme":
        raise ValueError("dossier sans erreur mais expected_outcome != conforme")


def validate_grid(g: dict):
    assert g["statut"] == "validee"
    assert g["prestations_hors_grille"] in ("interdites", "tolerees")
    natures = {"frais_dedouanement", "frais_avance_fonds", "frais_ligne_supplementaire", "magasinage", "transport",
               "manutention", "surcharge", "autre_prestation"}
    seen = set()
    for p in g["postes"]:
        assert p["nature"] in natures, p
        assert p["mode"] in ("forfait", "unitaire", "pourcentage", "par_jour"), p
        if p["mode"] == "pourcentage":
            assert p["pourcentage"] is not None and p["base_pourcentage"]
        else:
            assert p["prix"] is not None
        if p["mode"] == "par_jour":
            assert p["franchise_jours"] is not None
        if p["nature"] == "frais_ligne_supplementaire":
            assert p["inclus"] is not None
        seen.add(p["nature"])
    for n in ("frais_dedouanement", "frais_avance_fonds", "frais_ligne_supplementaire", "magasinage", "transport",
              "manutention", "surcharge"):
        assert n in seen, n
