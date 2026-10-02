# Banc ControlDOne — exécution `holdout2_final_b` (split `holdout`)

**Seuil bloquant (§19.7) : PASSE**

## Synthèse globale

| Indicateur | Valeur |
|---|---|
| Dossiers évalués | 48 |
| Erreurs injectées (dont attendues certain) | 148 (55) |
| Constats produits (certain / à vérifier) | 194 (46 / 148) |
| VP certain / FP certain | 46 / 0 |
|   dont FP non apparié / montant incorrect / piège | 0 / 0 / 0 |
| Précision certain | 100,0 % |
| Borne basse de Wilson 95 % | 92,3 % |
| Rappel | 74,3 % |
| Rappel certain | 74,6 % |
| Précision de détection | 56,7 % |
| Exactitude des montants | 90,7 % |
| Surclassements (taux) | 5 (10,9 %) |
| Sous-classements (taux) | 8 (16,3 %) |
| FN (erreurs manquées) | 38 |
| FP à vérifier (bruit) / par dossier | 80 / 1,6667 |
| Violations de pièges | 12 |
| Constats neutres (miroir, doublon de composantes, piège toléré) | 4 |

## Par contrôle

Erreurs, VP certain, FN, rappel et exactitude des montants : sur le contrôle **principal** de l'erreur. Constats produits, FP et précision « constats » : sur le contrôle du constat.

| Contrôle | Erreurs | dont certain | Constats certain produits | VP certain | FP certain | FN | Précision certain | Précision (constats) | Rappel | Exactitude montant |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 4 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| P2 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| P4 | 0 | 0 | 0 | 0 | 0 | 0 | — | — | — | — |
| A1 | 2 | 1 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| A2 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A3 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| A4 | 5 | 3 | 3 | 3 | 0 | 1 | 100,0 % | 100,0 % | 80,0 % | 100,0 % |
| A5 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| A6 | 2 | 1 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| A7 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A8 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A9 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A10 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A11 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A12 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A13 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A14 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A15 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| B1 | 2 | 1 | 1 | 1 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 50,0 % |
| B2 | 2 | 1 | 0 | 0 | 0 | 2 | — | — | 0,0 % | — |
| B3 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| B4 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| B5 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| C1 | 2 | 1 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| C2 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| C3 | 2 | 1 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| C4 | 2 | 1 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| C5 | 12 | 9 | 5 | 5 | 0 | 5 | 100,0 % | 100,0 % | 58,3 % | 71,4 % |
| C6 | 6 | 3 | 3 | 3 | 0 | 1 | 100,0 % | 100,0 % | 83,3 % | 100,0 % |
| C7 | 6 | 0 | 0 | 0 | 0 | 2 | — | — | 66,7 % | — |
| C8 | 4 | 3 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| D1 | 2 | 1 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| D2 | 2 | 1 | 0 | 0 | 0 | 1 | — | — | 50,0 % | 100,0 % |
| D3 | 2 | 1 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| D4 | 2 | 1 | 0 | 0 | 0 | 0 | — | — | 100,0 % | 50,0 % |
| D5 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| D6 | 2 | 2 | 0 | 0 | 0 | 2 | — | — | 0,0 % | — |
| D7 | 2 | 2 | 1 | 1 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 50,0 % |
| D8 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | 100,0 % |
| D9 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| E1 | 3 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E2 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| E3 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E4 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| E5 | 8 | 0 | 0 | 0 | 0 | 2 | — | — | 75,0 % | — |
| E6 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | 100,0 % |
| F1 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| F2 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| F3 | 2 | 0 | 0 | 0 | 0 | 2 | — | — | 0,0 % | — |
| F4 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | 100,0 % |
| F5 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | 100,0 % |
| G1 | 2 | 1 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| G2 | 2 | 2 | 1 | 1 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| G3 | 4 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| G4 | 4 | 3 | 3 | 3 | 0 | 1 | 100,0 % | 100,0 % | 75,0 % | 100,0 % |
| G5 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| G6 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |

## Exactitude d'extraction par champ obligatoire

48 dossier(s) ; global : 54,3 % (7336/13520).

| Champ | n | Corrects | Exactitude |
|---|---|---|---|
| `avoir.date` | 12 | 11 | 91,7 % |
| `avoir.lignes[].montant_ht` | 12 | 7 | 58,3 % |
| `avoir.lignes[].nature` | 12 | 0 | 0,0 % |
| `avoir.numero` | 12 | 12 | 100,0 % |
| `avoir.refs_facture_origine` | 12 | 0 | 0,0 % |
| `avoir.total_credite_ttc` | 12 | 9 | 75,0 % |
| `declaration.articles[].code_marchandise` | 311 | 267 | 85,9 % |
| `declaration.articles[].masse_brute` | 311 | 168 | 54,0 % |
| `declaration.articles[].masse_nette` | 311 | 160 | 51,4 % |
| `declaration.articles[].pays_origine` | 311 | 253 | 81,3 % |
| `declaration.date_acceptation` | 68 | 63 | 92,7 % |
| `declaration.devise_facture` | 68 | 64 | 94,1 % |
| `declaration.documents_references` | 68 | 0 | 0,0 % |
| `declaration.importateur.tva` | 68 | 64 | 94,1 % |
| `declaration.incoterm` | 68 | 64 | 94,1 % |
| `declaration.indices_autoliquidation` | 68 | 0 | 0,0 % |
| `declaration.montant_total_facture` | 68 | 64 | 94,1 % |
| `declaration.mrn` | 68 | 54 | 79,4 % |
| `declaration.nombre_articles` | 68 | 61 | 89,7 % |
| `declaration.taux_change` | 68 | 30 | 44,1 % |
| `declaration.taux_change_sens` | 68 | 29 | 42,6 % |
| `declaration.taxations[].article` | 647 | 453 | 70,0 % |
| `declaration.taxations[].base_montant` | 647 | 433 | 66,9 % |
| `declaration.taxations[].base_quantite` | 647 | 10 | 1,6 % |
| `declaration.taxations[].categorie` | 647 | 0 | 0,0 % |
| `declaration.taxations[].montant` | 647 | 443 | 68,5 % |
| `declaration.taxations[].paiement_normalise` | 647 | 0 | 0,0 % |
| `declaration.taxations[].taux` | 647 | 354 | 54,7 % |
| `declaration.taxations[].type_taxe` | 647 | 459 | 70,9 % |
| `declaration.total_a_payer` | 68 | 58 | 85,3 % |
| `facture_commerciale.acheteur.tva` | 64 | 57 | 89,1 % |
| `facture_commerciale.date` | 64 | 60 | 93,8 % |
| `facture_commerciale.devise` | 64 | 62 | 96,9 % |
| `facture_commerciale.incoterm` | 64 | 62 | 96,9 % |
| `facture_commerciale.lignes[].code_marchandise_imprime` | 298 | 209 | 70,1 % |
| `facture_commerciale.lignes[].montant_ligne` | 298 | 232 | 77,8 % |
| `facture_commerciale.lignes[].pays_origine` | 298 | 237 | 79,5 % |
| `facture_commerciale.lignes[].quantite` | 298 | 219 | 73,5 % |
| `facture_commerciale.lignes[].unite` | 298 | 0 | 0,0 % |
| `facture_commerciale.masse_brute_totale` | 64 | 60 | 93,8 % |
| `facture_commerciale.nombre_colis` | 64 | 58 | 90,6 % |
| `facture_commerciale.numero` | 64 | 58 | 90,6 % |
| `facture_commerciale.total_facture` | 64 | 58 | 90,6 % |
| `facture_commerciale.total_imprime` | 64 | 0 | 0,0 % |
| `facture_transitaire.client_facture.tva` | 61 | 56 | 91,8 % |
| `facture_transitaire.date` | 61 | 54 | 88,5 % |
| `facture_transitaire.emetteur.tva` | 61 | 55 | 90,2 % |
| `facture_transitaire.lignes[].libelle` | 442 | 225 | 50,9 % |
| `facture_transitaire.lignes[].montant_ht` | 442 | 273 | 61,8 % |
| `facture_transitaire.lignes[].montant_tva` | 442 | 243 | 55,0 % |
| `facture_transitaire.lignes[].mrn` | 442 | 301 | 68,1 % |
| `facture_transitaire.lignes[].nature` | 442 | 0 | 0,0 % |
| `facture_transitaire.lignes[].prix_unitaire` | 442 | 273 | 61,8 % |
| `facture_transitaire.lignes[].quantite` | 442 | 323 | 73,1 % |
| `facture_transitaire.lignes[].taux_tva` | 442 | 306 | 69,2 % |
| `facture_transitaire.numero` | 61 | 55 | 90,2 % |
| `facture_transitaire.refs_mrn` | 61 | 0 | 0,0 % |
| `facture_transitaire.refs_transport` | 61 | 0 | 0,0 % |
| `facture_transitaire.total_debours` | 61 | 50 | 82,0 % |
| `facture_transitaire.total_ht` | 61 | 53 | 86,9 % |
| `facture_transitaire.total_ttc` | 61 | 53 | 86,9 % |
| `facture_transitaire.total_tva` | 61 | 54 | 88,5 % |

## Regroupement (liens attendus)

VP 265, FP 18, FN 1 — précision 93,6 %, rappel 99,6 %, F1 96,5 % (modes : {'documents': 48}).

## Coût IA et durée par dossier

| | n | Moyenne | Médiane | p95 | Maximum |
|---|---|---|---|---|---|
| Coût IA (EUR) | 48 | 0,0000 | 0,0000 | 0,0000 | 0,0000 |
| Durée (s) | 48 | 0,3294 | 0,1975 | 1,2560 | 1,2780 |

## Alertes (non bloquantes)

- bruit a_verifier non apparié 1.6667 par dossier > 1.5

_Formulations interdites : source `/home/user/v2/config/formulations_interdites.yaml`._
