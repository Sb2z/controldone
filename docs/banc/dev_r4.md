# Banc ControlDOne — exécution `dev_r4` (split `dev`)

**Seuil bloquant (§19.7) : PASSE**

## Synthèse globale

| Indicateur | Valeur |
|---|---|
| Dossiers évalués | 202 |
| Erreurs injectées (dont attendues certain) | 369 (144) |
| Constats produits (certain / à vérifier) | 588 (114 / 474) |
| VP certain / FP certain | 114 / 0 |
|   dont FP non apparié / montant incorrect / piège | 0 / 0 / 0 |
| Précision certain | 100,0 % |
| Borne basse de Wilson 95 % | 96,7 % |
| Rappel | 81,3 % |
| Rappel certain | 73,6 % |
| Précision de détection | 51,0 % |
| Exactitude des montants | 95,8 % |
| Surclassements (taux) | 8 (7,0 %) |
| Sous-classements (taux) | 24 (18,5 %) |
| FN (erreurs manquées) | 69 |
| FP à vérifier (bruit) / par dossier | 285 / 1,4109 |
| Violations de pièges | 40 |
| Constats neutres (miroir, doublon de composantes, piège toléré) | 3 |

## Par contrôle

Erreurs, VP certain, FN, rappel et exactitude des montants : sur le contrôle **principal** de l'erreur. Constats produits, FP et précision « constats » : sur le contrôle du constat.

| Contrôle | Erreurs | dont certain | Constats certain produits | VP certain | FP certain | FN | Précision certain | Précision (constats) | Rappel | Exactitude montant |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 9 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| P2 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| P4 | 0 | 0 | 0 | 0 | 0 | 0 | — | — | — | — |
| A1 | 5 | 4 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| A2 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A3 | 5 | 4 | 3 | 3 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | — |
| A4 | 11 | 7 | 5 | 5 | 0 | 1 | 100,0 % | 100,0 % | 90,9 % | 100,0 % |
| A5 | 5 | 3 | 4 | 4 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | 100,0 % |
| A6 | 5 | 5 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| A7 | 5 | 0 | 0 | 0 | 0 | 1 | — | — | 80,0 % | — |
| A8 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A9 | 5 | 0 | 0 | 0 | 0 | 2 | — | — | 60,0 % | — |
| A10 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A11 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A12 | 5 | 0 | 0 | 0 | 0 | 2 | — | — | 60,0 % | — |
| A13 | 5 | 0 | 0 | 0 | 0 | 1 | — | — | 80,0 % | — |
| A14 | 5 | 0 | 0 | 0 | 0 | 2 | — | — | 60,0 % | — |
| A15 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| B1 | 5 | 3 | 3 | 3 | 0 | 2 | 100,0 % | 100,0 % | 60,0 % | 100,0 % |
| B2 | 5 | 4 | 0 | 0 | 0 | 3 | — | — | 40,0 % | 50,0 % |
| B3 | 5 | 5 | 5 | 5 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| B4 | 5 | 5 | 4 | 4 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| B5 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| C1 | 6 | 5 | 5 | 5 | 0 | 1 | 100,0 % | 100,0 % | 83,3 % | 100,0 % |
| C2 | 6 | 3 | 3 | 3 | 0 | 3 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| C3 | 5 | 3 | 4 | 4 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | 100,0 % |
| C4 | 6 | 5 | 4 | 4 | 0 | 2 | 100,0 % | 100,0 % | 66,7 % | 100,0 % |
| C5 | 29 | 22 | 15 | 15 | 0 | 10 | 100,0 % | 100,0 % | 65,5 % | 94,7 % |
| C6 | 16 | 9 | 12 | 12 | 0 | 2 | 100,0 % | 100,0 % | 87,5 % | 100,0 % |
| C7 | 12 | 0 | 0 | 0 | 0 | 3 | — | — | 75,0 % | — |
| C8 | 10 | 8 | 6 | 6 | 0 | 2 | 100,0 % | 100,0 % | 80,0 % | — |
| D1 | 5 | 3 | 2 | 2 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | 75,0 % |
| D2 | 5 | 3 | 3 | 3 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | 100,0 % |
| D3 | 6 | 3 | 2 | 2 | 0 | 1 | 100,0 % | 100,0 % | 83,3 % | 60,0 % |
| D4 | 5 | 4 | 2 | 2 | 0 | 2 | 100,0 % | 100,0 % | 60,0 % | 100,0 % |
| D5 | 5 | 3 | 3 | 3 | 0 | 2 | 100,0 % | 100,0 % | 60,0 % | 100,0 % |
| D6 | 5 | 4 | 2 | 2 | 0 | 3 | 100,0 % | 100,0 % | 40,0 % | 100,0 % |
| D7 | 5 | 4 | 2 | 2 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | 75,0 % |
| D8 | 5 | 0 | 0 | 0 | 0 | 1 | — | — | 80,0 % | 100,0 % |
| D9 | 5 | 4 | 4 | 4 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| E1 | 8 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E2 | 6 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E3 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E4 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E5 | 22 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E6 | 6 | 0 | 0 | 0 | 0 | 2 | — | — | 66,7 % | 100,0 % |
| F1 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| F2 | 5 | 0 | 0 | 0 | 0 | 1 | — | — | 80,0 % | — |
| F3 | 4 | 4 | 0 | 0 | 0 | 1 | — | — | 75,0 % | 100,0 % |
| F4 | 4 | 0 | 0 | 0 | 0 | 1 | — | — | 75,0 % | 100,0 % |
| F5 | 5 | 0 | 0 | 0 | 0 | 1 | — | — | 80,0 % | 100,0 % |
| G1 | 5 | 3 | 3 | 3 | 0 | 2 | 100,0 % | 100,0 % | 60,0 % | 100,0 % |
| G2 | 5 | 3 | 3 | 3 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | 100,0 % |
| G3 | 9 | 0 | 0 | 0 | 0 | 4 | — | — | 55,6 % | — |
| G4 | 9 | 7 | 7 | 7 | 0 | 2 | 100,0 % | 100,0 % | 77,8 % | 100,0 % |
| G5 | 5 | 4 | 4 | 4 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | 100,0 % |
| G6 | 5 | 0 | 0 | 0 | 0 | 1 | — | — | 80,0 % | — |

## Exactitude d'extraction par champ obligatoire

202 dossier(s) ; global : 58,2 % (36666/62977).

| Champ | n | Corrects | Exactitude |
|---|---|---|---|
| `avoir.date` | 33 | 33 | 100,0 % |
| `avoir.lignes[].montant_ht` | 33 | 31 | 93,9 % |
| `avoir.lignes[].nature` | 33 | 0 | 0,0 % |
| `avoir.numero` | 33 | 33 | 100,0 % |
| `avoir.refs_facture_origine` | 33 | 0 | 0,0 % |
| `avoir.total_credite_ttc` | 33 | 33 | 100,0 % |
| `declaration.articles[].code_marchandise` | 1494 | 1337 | 89,5 % |
| `declaration.articles[].masse_brute` | 1494 | 1067 | 71,4 % |
| `declaration.articles[].masse_nette` | 1494 | 1040 | 69,6 % |
| `declaration.articles[].pays_origine` | 1494 | 1260 | 84,3 % |
| `declaration.date_acceptation` | 310 | 290 | 93,5 % |
| `declaration.devise_facture` | 310 | 301 | 97,1 % |
| `declaration.documents_references` | 310 | 0 | 0,0 % |
| `declaration.importateur.tva` | 310 | 290 | 93,5 % |
| `declaration.incoterm` | 310 | 299 | 96,5 % |
| `declaration.indices_autoliquidation` | 310 | 0 | 0,0 % |
| `declaration.montant_total_facture` | 310 | 293 | 94,5 % |
| `declaration.mrn` | 310 | 250 | 80,7 % |
| `declaration.nombre_articles` | 310 | 285 | 91,9 % |
| `declaration.taux_change` | 310 | 170 | 54,8 % |
| `declaration.taux_change_sens` | 310 | 171 | 55,2 % |
| `declaration.taxations[].article` | 3101 | 2398 | 77,3 % |
| `declaration.taxations[].base_montant` | 3101 | 2260 | 72,9 % |
| `declaration.taxations[].base_quantite` | 3101 | 58 | 1,9 % |
| `declaration.taxations[].categorie` | 3101 | 0 | 0,0 % |
| `declaration.taxations[].montant` | 3101 | 2310 | 74,5 % |
| `declaration.taxations[].paiement_normalise` | 3101 | 0 | 0,0 % |
| `declaration.taxations[].taux` | 3101 | 2102 | 67,8 % |
| `declaration.taxations[].type_taxe` | 3101 | 2385 | 76,9 % |
| `declaration.total_a_payer` | 310 | 270 | 87,1 % |
| `facture_commerciale.acheteur.tva` | 308 | 283 | 91,9 % |
| `facture_commerciale.date` | 308 | 288 | 93,5 % |
| `facture_commerciale.devise` | 308 | 297 | 96,4 % |
| `facture_commerciale.incoterm` | 308 | 300 | 97,4 % |
| `facture_commerciale.lignes[].code_marchandise_imprime` | 1465 | 1076 | 73,5 % |
| `facture_commerciale.lignes[].montant_ligne` | 1465 | 1196 | 81,6 % |
| `facture_commerciale.lignes[].pays_origine` | 1465 | 1208 | 82,5 % |
| `facture_commerciale.lignes[].quantite` | 1465 | 1119 | 76,4 % |
| `facture_commerciale.lignes[].unite` | 1465 | 0 | 0,0 % |
| `facture_commerciale.masse_brute_totale` | 308 | 279 | 90,6 % |
| `facture_commerciale.nombre_colis` | 308 | 296 | 96,1 % |
| `facture_commerciale.numero` | 308 | 283 | 91,9 % |
| `facture_commerciale.total_facture` | 308 | 283 | 91,9 % |
| `facture_commerciale.total_imprime` | 308 | 0 | 0,0 % |
| `facture_transitaire.client_facture.tva` | 245 | 228 | 93,1 % |
| `facture_transitaire.date` | 245 | 230 | 93,9 % |
| `facture_transitaire.emetteur.tva` | 245 | 229 | 93,5 % |
| `facture_transitaire.lignes[].libelle` | 1966 | 966 | 49,1 % |
| `facture_transitaire.lignes[].montant_ht` | 1966 | 1239 | 63,0 % |
| `facture_transitaire.lignes[].montant_tva` | 1966 | 1136 | 57,8 % |
| `facture_transitaire.lignes[].mrn` | 1966 | 1365 | 69,4 % |
| `facture_transitaire.lignes[].nature` | 1966 | 0 | 0,0 % |
| `facture_transitaire.lignes[].prix_unitaire` | 1966 | 1242 | 63,2 % |
| `facture_transitaire.lignes[].quantite` | 1966 | 1541 | 78,4 % |
| `facture_transitaire.lignes[].taux_tva` | 1966 | 1482 | 75,4 % |
| `facture_transitaire.numero` | 245 | 229 | 93,5 % |
| `facture_transitaire.refs_mrn` | 245 | 0 | 0,0 % |
| `facture_transitaire.refs_transport` | 245 | 0 | 0,0 % |
| `facture_transitaire.total_debours` | 245 | 223 | 91,0 % |
| `facture_transitaire.total_ht` | 245 | 227 | 92,7 % |
| `facture_transitaire.total_ttc` | 245 | 229 | 93,5 % |
| `facture_transitaire.total_tva` | 245 | 226 | 92,2 % |

## Regroupement (liens attendus)

VP 1136, FP 57, FN 26 — précision 95,2 %, rappel 97,8 %, F1 96,5 % (modes : {'documents': 202}).

## Coût IA et durée par dossier

| | n | Moyenne | Médiane | p95 | Maximum |
|---|---|---|---|---|---|
| Coût IA (EUR) | 202 | 0,0000 | 0,0000 | 0,0000 | 0,0000 |
| Durée (s) | 202 | 0,3474 | 0,2235 | 1,1610 | 2,5590 |

_Formulations interdites : source `/home/user/v2/config/formulations_interdites.yaml`._
