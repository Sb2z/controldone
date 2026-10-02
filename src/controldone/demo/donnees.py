"""Jeu de démonstration **entièrement fictif** : trois dossiers d'import.

- DEMO-1 : TVA à l'importation refacturée alors que la déclaration indique l'autoliquidation (C3) et frais
  de dédouanement facturés au-delà de la grille (D3) ;
- DEMO-2 : montant de droits imprimé différent du produit base × taux (B1) et pays d'origine imprimés
  différents entre la facture et la déclaration (A12, note de renvoi) ;
- DEMO-3 : dossier cohérent.

Sociétés, adresses, numéros (SIREN commençant par 000, valides au sens de Luhn ; TVA calculées), MRN et
montants sont inventés. Aucune donnée réelle.
"""

from __future__ import annotations

from controldone.demo.modele import Champ, DocDemo, DossierDemo, Tableau
from controldone.model.enums import (
    CategorieTaxe,
    NatureLigne,
    PaiementNormalise,
    TauxNature,
    TypeDocument,
    TypeIndiceAutoliquidation,
)

__all__ = ["CLIENT", "TRANSITAIRE", "dossiers_demo", "grille_demo", "profil_demo"]

CLIENT = {
    "raison_sociale": "ATELIERS DÉMO FICTIF SAS",
    "siren": "000100008",
    "tva": "FR15000100008",
    "eori": "FR00010000800000",
    "adresse": ["12 rue de l'Exemple (fictive)", "69000 LYON — FRANCE"],
}
TRANSITAIRE = {
    "id": "TR-DEMO",
    "nom": "TRANSIT DÉMO FICTIF SARL",
    "siren": "000100016",
    "tva": "FR39000100016",
    "adresse": ["4 quai Imaginaire (fictif)", "13000 MARSEILLE — FRANCE"],
}
MENTION = "Document fictif généré pour la démonstration ControlDOne — aucune valeur réelle."


def profil_demo() -> dict:
    return {
        "schema": "controldone.bench.profil/1.0.0",
        "client_id": "DEMO",
        "raison_sociale": CLIENT["raison_sociale"],
        "offre": "diagnostic",
        "demo": True,
        "entites": [{"raison_sociale": CLIENT["raison_sociale"], "tva": CLIENT["tva"], "siren": CLIENT["siren"],
                     "eori": CLIENT["eori"], "alias": ["ATELIERS DEMO FICTIF"]}],
        "transitaires": [{"transitaire_id": TRANSITAIRE["id"], "nom": TRANSITAIRE["nom"], "tva": TRANSITAIRE["tva"],
                          "alias": ["TRANSIT DEMO FICTIF"]}],
        "tolerances": {},
    }


def grille_demo() -> dict:
    return {
        "grille_id": "GRL-DEMO-2026",
        "transitaire_id": TRANSITAIRE["id"],
        "reference": "DEVIS FICTIF D-2026-001",
        "valide_du": "2026-01-01",
        "valide_au": "2026-12-31",
        "statut": "validee",
        "prestations_hors_grille": "tolerees",
        "postes": [
            {"code_poste": "DEDOUANEMENT", "nature": "frais_dedouanement", "mode": "forfait", "prix": "65.00",
             "libelles_reconnus": ["frais de dédouanement", "dédouanement"], "devise": "EUR"},
            {"code_poste": "FAF", "nature": "frais_avance_fonds", "mode": "pourcentage", "pourcentage": "2.5",
             "base_pourcentage": "debours_total", "minimum": "15.00", "libelles_reconnus": ["avance de fonds"],
             "devise": "EUR"},
        ],
    }


# --- fabriques ------------------------------------------------------------------------------------------


def _client(prefixe: str, titre: str = "Facturé à") -> tuple[str, list[Champ]]:
    return titre, [
        Champ(f"{prefixe}.nom", "", CLIENT["raison_sociale"]),
        Champ(None, "", CLIENT["adresse"][0]),
        Champ(None, "", CLIENT["adresse"][1]),
        Champ(f"{prefixe}.tva", "N° TVA", CLIENT["tva"]),
    ]


def _facture_commerciale(*, fichier, numero, date, fournisseur, adresse, devise, lignes, total, incoterm,
                         lieu, transport, brute, nette, colis) -> DocDemo:
    titre, dest = _client("acheteur", "Buyer / Acheteur")
    return DocDemo(
        fichier=fichier, type=TypeDocument.facture_commerciale, sous_type="facture", langue="en",
        titre="COMMERCIAL INVOICE", cle=numero,
        emetteur=[fournisseur, *adresse],
        emetteur_champs=[Champ("vendeur.nom", "", fournisseur)],
        destinataire_titre=titre, destinataire=dest,
        entete=[
            Champ("numero", "Invoice No.", numero), Champ("date", "Date", date), Champ("devise", "Currency", devise),
            Champ("incoterm", "Incoterms", incoterm), Champ("incoterm_lieu", "Place", lieu),
            Champ("ref_transport", "AWB / B/L", transport),
            Champ("nombre_colis", "Packages", colis), Champ("masse_brute_totale", "Gross weight", brute),
            Champ("masse_nette_totale", "Net weight", nette),
        ],
        tableaux=[Tableau(
            "Goods", "lignes",
            [("numero_ligne", "#", 8, False), ("description", "Description", 56, False),
             ("code_marchandise_imprime", "HS code", 20, False), ("pays_origine", "Origin", 14, False),
             ("quantite", "Qty", 14, True), ("prix_unitaire", "Unit price", 22, True),
             ("montant_ligne", "Amount", 26, True)],
            lignes,
        )],
        totaux=[Champ("total_facture", f"TOTAL {devise}", total)],
        mentions=["Origin of goods as stated per line. Fictitious document."],
    )


def _declaration(*, fichier, mrn, date, devise, montant, taux, sens, refs, articles, taxations, total_payer,
                 brute, colis, nb, incoterm, pays_exp, autoliquidation=False) -> DocDemo:
    entete = [
        Champ("mrn", "MRN", mrn), Champ("date_acceptation", "Date d'acceptation", date),
        Champ("devise_facture", "Devise de facturation", devise), Champ("montant_total_facture", "Montant facturé", montant),
    ]
    if taux:
        entete += [Champ("taux_change", "Taux de change", taux),
                   Champ("taux_change_sens", "Sens du taux", sens, valeur="devise_par_eur")]
    entete += [
        Champ("incoterm", "Conditions de livraison", incoterm), Champ("pays_expedition", "Pays d'expédition", pays_exp),
        Champ("nombre_articles", "Nombre d'articles", nb), Champ("nombre_colis_total", "Nombre de colis", colis),
        Champ("masse_brute_totale", "Masse brute totale", brute),
        Champ("declarant.nom", "Déclarant", TRANSITAIRE["nom"]),
    ]
    titre, dest = _client("importateur", "Importateur")
    objets = {}
    if autoliquidation:
        objets["indices_autoliquidation"] = [
            {"type": TypeIndiceAutoliquidation.code_1008, "valeur": "1008", "tva": CLIENT["tva"]}]
    return DocDemo(
        fichier=fichier, type=TypeDocument.declaration, sous_type="h1",
        titre="DÉCLARATION EN DOUANE — IMPORTATION (H1)", cle=mrn,
        emetteur=["Mise en libre pratique", "Bureau de dédouanement fictif FR000000"],
        destinataire_titre=titre, destinataire=dest, entete=entete,
        tableaux=[
            Tableau("Documents produits", "documents_references",
                    [("type_code", "Code", 20, False), ("reference", "Référence", 70, False)], refs),
            Tableau("Articles", "articles",
                    [("numero_article", "Art.", 9, False), ("code_marchandise", "Code marchandise", 30, False),
                     ("description", "Désignation", 36, False), ("pays_origine", "Origine", 14, False),
                     ("masse_nette", "Masse nette", 22, True), ("masse_brute", "Masse brute", 22, True),
                     ("montant_facture_article", "Montant facturé", 30, True)], articles),
            Tableau("Calcul des impositions", "taxations",
                    [("article", "Art.", 9, False), ("type_taxe", "Type", 12, False), ("base_montant", "Base", 28, True),
                     ("taux", "Taux (%)", 18, True), ("montant", "Montant", 26, True),
                     ("mode_paiement", "Mode de paiement", 36, False)],
                    [t[0] for t in taxations], [t[1] for t in taxations]),
        ],
        totaux=[Champ("total_a_payer", "Total à payer (EUR)", total_payer)],
        mentions=["Document fictif — données de démonstration."],
        objets=objets,
    )


def _facture_transitaire(*, fichier, numero, date, mrn, transport, lignes, deb, ht, tva, ttc) -> DocDemo:
    titre, dest = _client("client_facture", "Client")
    return DocDemo(
        fichier=fichier, type=TypeDocument.facture_transitaire, titre="FACTURE", cle=numero,
        emetteur=[TRANSITAIRE["nom"], *TRANSITAIRE["adresse"], f"N° TVA {TRANSITAIRE['tva']}"],
        emetteur_champs=[Champ("emetteur.nom", "", TRANSITAIRE["nom"]),
                         Champ("emetteur.tva", "", TRANSITAIRE["tva"])],
        destinataire_titre=titre, destinataire=dest,
        entete=[Champ("numero", "Facture n°", numero), Champ("date", "Date", date), Champ("devise", "Devise", "EUR"),
                Champ("refs_mrn[0]", "MRN", mrn), Champ("refs_transport[0]", "LTA", transport)],
        tableaux=[Tableau(
            "Détail", "lignes",
            [("libelle", "Désignation", 62, False), ("quantite", "Qté", 12, True),
             ("prix_unitaire", "P.U. HT", 22, True), ("montant_ht", "Montant HT", 26, True),
             ("taux_tva", "TVA %", 14, True), ("montant_tva", "TVA", 22, True)],
            [x[0] for x in lignes], [{"nature": x[1]} for x in lignes],
        )],
        totaux=[Champ("total_debours", "Total débours", deb), Champ("total_ht", "Total HT", ht),
                Champ("total_tva", "Total TVA", tva), Champ("total_ttc", "Net à payer TTC", ttc)],
        mentions=["Débours : sommes avancées pour le compte du client, non soumises à TVA.", MENTION],
    )


def _tax(article, type_taxe, base, taux, montant, mode, categorie, paiement):
    return ({"article": article, "type_taxe": type_taxe, "base_montant": base, "taux": taux, "montant": montant,
             "mode_paiement": mode},
            {"categorie": categorie, "taux_nature": TauxNature.ad_valorem, "paiement_normalise": paiement})


D, T, AUTO, CPT = CategorieTaxe.droit, CategorieTaxe.tva, PaiementNormalise.autoliquide, PaiementNormalise.comptant


def dossiers_demo() -> list[DossierDemo]:
    d1 = DossierDemo("DEMO-1", "TVA refacturée malgré l'autoliquidation ; dédouanement au-delà de la grille", [
        _facture_commerciale(
            fichier="facture_commerciale_INV-FIC-0101.pdf", numero="INV-FIC-0101", date="14/08/2026",
            fournisseur="FICTIVE TRADING CO., LTD. (FICTIF)",
            adresse=["88 Imaginary Road, Futian (fictitious)", "Shenzhen — CHINA"], devise="USD",
            lignes=[
                {"numero_ligne": "1", "description": "Industrial controller FX-200", "code_marchandise_imprime": "8537.10",
                 "pays_origine": "CN", "quantite": "40", "prix_unitaire": "185.50", "montant_ligne": "7,420.00"},
                {"numero_ligne": "2", "description": "Pressure sensor PX-9", "code_marchandise_imprime": "9026.20",
                 "pays_origine": "CN", "quantite": "160", "prix_unitaire": "32.00", "montant_ligne": "5,120.00"},
            ],
            total="12,540.00", incoterm="FOB", lieu="Shenzhen", transport="999-12345675",
            brute="412.5 kg", nette="380.0 kg", colis="12"),
        _declaration(
            fichier="declaration_26FRD1FIC000004711.pdf", mrn="26FRD1FIC000004711", date="20/08/2026", devise="USD",
            montant="12 540,00", taux="1,0850", sens="1 EUR = 1,0850 USD",
            refs=[{"type_code": "N380", "reference": "INV-FIC-0101"}, {"type_code": "N740", "reference": "999-12345675"},
                  {"type_code": "1008", "reference": CLIENT["tva"]}],
            articles=[
                {"numero_article": "1", "code_marchandise": "8537 10 99 00", "description": "Contrôleurs industriels",
                 "pays_origine": "CN", "masse_nette": "240,0 kg", "masse_brute": "262,5 kg",
                 "montant_facture_article": "7 420,00"},
                {"numero_article": "2", "code_marchandise": "9026 20 80 00", "description": "Capteurs de pression",
                 "pays_origine": "CN", "masse_nette": "140,0 kg", "masse_brute": "150,0 kg",
                 "montant_facture_article": "5 120,00"},
            ],
            taxations=[
                _tax("1", "A00", "6 838,71", "2,1", "143,61", "Comptant", D, CPT),
                _tax("2", "A00", "4 718,89", "1,7", "80,22", "Comptant", D, CPT),
                _tax("1", "B00", "6 982,32", "20", "1 396,46", "Autoliquidation", T, AUTO),
                _tax("2", "B00", "4 799,11", "20", "959,82", "Autoliquidation", T, AUTO),
            ],
            total_payer="223,83", brute="412,5 kg", colis="12", nb="2", incoterm="FOB", pays_exp="CN",
            autoliquidation=True),
        _facture_transitaire(
            fichier="facture_transitaire_FT-FIC-0501.pdf", numero="FT-FIC-0501", date="25/08/2026",
            mrn="26FRD1FIC000004711", transport="999-12345675",
            lignes=[
                ({"libelle": "Droits de douane (débours)", "quantite": "1", "prix_unitaire": "223,83",
                  "montant_ht": "223,83", "taux_tva": "0", "montant_tva": "0,00"}, NatureLigne.debours_droits),
                ({"libelle": "TVA à l'importation (débours)", "quantite": "1", "prix_unitaire": "2 356,28",
                  "montant_ht": "2 356,28", "taux_tva": "0", "montant_tva": "0,00"}, NatureLigne.debours_tva),
                ({"libelle": "Frais de dédouanement", "quantite": "1", "prix_unitaire": "95,00",
                  "montant_ht": "95,00", "taux_tva": "20", "montant_tva": "19,00"}, NatureLigne.frais_dedouanement),
            ],
            deb="2 580,11", ht="2 675,11", tva="19,00", ttc="2 694,11"),
    ])
    d2 = DossierDemo("DEMO-2", "Écart de calcul sur la déclaration ; pays d'origine imprimés différents", [
        _facture_commerciale(
            fichier="facture_commerciale_INV-FIC-0202.pdf", numero="INV-FIC-0202", date="03/09/2026",
            fournisseur="FICTIVE VALVES CO., LTD. (FICTIF)",
            adresse=["5 Example Avenue (fictitious)", "Ningbo — CHINA"], devise="EUR",
            lignes=[{"numero_ligne": "1", "description": "Brass valve DN25", "code_marchandise_imprime": "8481.80",
                     "pays_origine": "CN", "quantite": "500", "prix_unitaire": "16.00", "montant_ligne": "8,000.00"}],
            total="8,000.00", incoterm="FCA", lieu="Ningbo", transport="999-22223330",
            brute="610.0 kg", nette="580.0 kg", colis="20"),
        _declaration(
            fichier="declaration_26FRD2FIC000005822.pdf", mrn="26FRD2FIC000005822", date="09/09/2026", devise="EUR",
            montant="8 000,00", taux=None, sens=None,
            refs=[{"type_code": "N380", "reference": "INV-FIC-0202"}, {"type_code": "N740", "reference": "999-22223330"}],
            articles=[{"numero_article": "1", "code_marchandise": "8481 80 85 00", "description": "Robinetterie laiton",
                       "pays_origine": "VN", "masse_nette": "580,0 kg", "masse_brute": "610,0 kg",
                       "montant_facture_article": "8 000,00"}],
            taxations=[
                _tax("1", "A00", "8 000,00", "2,2", "196,00", "Comptant", D, CPT),
                _tax("1", "B00", "8 196,00", "20", "1 639,20", "Comptant", T, CPT),
            ],
            total_payer="1 835,20", brute="610,0 kg", colis="20", nb="1", incoterm="FCA", pays_exp="CN"),
        _facture_transitaire(
            fichier="facture_transitaire_FT-FIC-0502.pdf", numero="FT-FIC-0502", date="14/09/2026",
            mrn="26FRD2FIC000005822", transport="999-22223330",
            lignes=[
                ({"libelle": "Droits de douane (débours)", "quantite": "1", "prix_unitaire": "196,00",
                  "montant_ht": "196,00", "taux_tva": "0", "montant_tva": "0,00"}, NatureLigne.debours_droits),
                ({"libelle": "TVA à l'importation (débours)", "quantite": "1", "prix_unitaire": "1 639,20",
                  "montant_ht": "1 639,20", "taux_tva": "0", "montant_tva": "0,00"}, NatureLigne.debours_tva),
                ({"libelle": "Frais de dédouanement", "quantite": "1", "prix_unitaire": "65,00",
                  "montant_ht": "65,00", "taux_tva": "20", "montant_tva": "13,00"}, NatureLigne.frais_dedouanement),
            ],
            deb="1 835,20", ht="1 900,20", tva="13,00", ttc="1 913,20"),
    ])
    d3 = DossierDemo("DEMO-3", "Dossier cohérent", [
        _facture_commerciale(
            fichier="facture_commerciale_INV-FIC-0303.pdf", numero="INV-FIC-0303", date="12/09/2026",
            fournisseur="OUTILLAGE FICTIF SA (FICTIF)", adresse=["1 chemin Inventé (fictif)", "Lausanne — SUISSE"],
            devise="EUR",
            lignes=[
                {"numero_ligne": "1", "description": "Carbide end mill D12", "code_marchandise_imprime": "8207.70",
                 "pays_origine": "CH", "quantite": "120", "prix_unitaire": "21.25", "montant_ligne": "2,550.00"},
                {"numero_ligne": "2", "description": "Tool holder HSK63", "code_marchandise_imprime": "8466.10",
                 "pays_origine": "CH", "quantite": "20", "prix_unitaire": "85.00", "montant_ligne": "1,700.00"},
            ],
            total="4,250.00", incoterm="DAP", lieu="Lyon", transport="999-33334441",
            brute="96.0 kg", nette="88.0 kg", colis="4"),
        _declaration(
            fichier="declaration_26FRD3FIC000006933.pdf", mrn="26FRD3FIC000006933", date="16/09/2026", devise="EUR",
            montant="4 250,00", taux=None, sens=None,
            refs=[{"type_code": "N380", "reference": "INV-FIC-0303"}, {"type_code": "N740", "reference": "999-33334441"}],
            articles=[
                {"numero_article": "1", "code_marchandise": "8207 70 37 00", "description": "Fraises en carbure",
                 "pays_origine": "CH", "masse_nette": "60,0 kg", "masse_brute": "66,0 kg",
                 "montant_facture_article": "2 550,00"},
                {"numero_article": "2", "code_marchandise": "8466 10 20 00", "description": "Porte-outils",
                 "pays_origine": "CH", "masse_nette": "28,0 kg", "masse_brute": "30,0 kg",
                 "montant_facture_article": "1 700,00"},
            ],
            taxations=[
                _tax("1", "A00", "2 550,00", "2,7", "68,85", "Comptant", D, CPT),
                _tax("2", "A00", "1 700,00", "1,2", "20,40", "Comptant", D, CPT),
                _tax("1", "B00", "2 618,85", "20", "523,77", "Comptant", T, CPT),
                _tax("2", "B00", "1 720,40", "20", "344,08", "Comptant", T, CPT),
            ],
            total_payer="957,10", brute="96,0 kg", colis="4", nb="2", incoterm="DAP", pays_exp="CH"),
        _facture_transitaire(
            fichier="facture_transitaire_FT-FIC-0503.pdf", numero="FT-FIC-0503", date="21/09/2026",
            mrn="26FRD3FIC000006933", transport="999-33334441",
            lignes=[
                ({"libelle": "Droits de douane (débours)", "quantite": "1", "prix_unitaire": "89,25",
                  "montant_ht": "89,25", "taux_tva": "0", "montant_tva": "0,00"}, NatureLigne.debours_droits),
                ({"libelle": "TVA à l'importation (débours)", "quantite": "1", "prix_unitaire": "867,85",
                  "montant_ht": "867,85", "taux_tva": "0", "montant_tva": "0,00"}, NatureLigne.debours_tva),
                ({"libelle": "Frais de dédouanement", "quantite": "1", "prix_unitaire": "65,00",
                  "montant_ht": "65,00", "taux_tva": "20", "montant_tva": "13,00"}, NatureLigne.frais_dedouanement),
            ],
            deb="957,10", ht="1 022,10", tva="13,00", ttc="1 035,10"),
    ])
    return [d1, d2, d3]
