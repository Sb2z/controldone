# Banc ControlDOne — exécution `holdout_final_1` (split `holdout`)

**Seuil bloquant (§19.7) : PASSE**

## Synthèse globale

| Indicateur | Valeur |
|---|---|
| Dossiers évalués | 48 |
| Erreurs injectées (dont attendues certain) | 149 (59) |
| Constats produits (certain / à vérifier) | 205 (46 / 159) |
| VP certain / FP certain | 45 / 1 |
|   dont FP non apparié / montant incorrect / piège | 1 / 0 / 0 |
| Précision certain | 97,8 % |
| Borne basse de Wilson 95 % | 88,7 % |
| Rappel | 82,5 % |
| Rappel certain | 69,5 % |
| Précision de détection | 60,0 % |
| Exactitude des montants | 96,5 % |
| Surclassements (taux) | 4 (8,9 %) |
| Sous-classements (taux) | 5 (10,9 %) |
| FN (erreurs manquées) | 26 |
| FP à vérifier (bruit) / par dossier | 78 / 1,625 |
| Violations de pièges | 12 |
| Constats neutres (miroir, doublon de composantes, piège toléré) | 3 |

## Par contrôle

Erreurs, VP certain, FN, rappel et exactitude des montants : sur le contrôle **principal** de l'erreur. Constats produits, FP et précision « constats » : sur le contrôle du constat.

| Contrôle | Erreurs | dont certain | Constats certain produits | VP certain | FP certain | FN | Précision certain | Précision (constats) | Rappel | Exactitude montant |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 3 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| P2 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| P4 | 0 | 0 | 0 | 0 | 0 | 0 | — | — | — | — |
| A1 | 2 | 2 | 1 | 1 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| A2 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A3 | 2 | 1 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| A4 | 5 | 3 | 3 | 3 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 80,0 % |
| A5 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| A6 | 2 | 0 | 1 | 1 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| A7 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A8 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A9 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A10 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A11 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A12 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A13 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | — |
| A14 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| A15 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| B1 | 2 | 1 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| B2 | 2 | 2 | 0 | 0 | 0 | 1 | — | — | 50,0 % | 100,0 % |
| B3 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| B4 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | — |
| B5 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| C1 | 2 | 1 | 0 | 0 | 0 | 2 | — | — | 0,0 % | — |
| C2 | 2 | 1 | 2 | 1 | 1 | 1 | 50,0 % | 50,0 % | 50,0 % | 100,0 % |
| C3 | 2 | 2 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| C4 | 2 | 1 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| C5 | 12 | 9 | 4 | 4 | 0 | 7 | 100,0 % | 100,0 % | 41,7 % | 100,0 % |
| C6 | 8 | 2 | 1 | 1 | 0 | 4 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| C7 | 6 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| C8 | 4 | 3 | 2 | 2 | 0 | 1 | 100,0 % | 100,0 % | 75,0 % | — |
| D1 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| D2 | 2 | 1 | 1 | 1 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| D3 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| D4 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| D5 | 2 | 2 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| D6 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| D7 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| D8 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | 100,0 % |
| D9 | 2 | 1 | 1 | 1 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| E1 | 3 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E2 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E3 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E4 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E5 | 8 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| E6 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | 50,0 % |
| F1 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| F2 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| F3 | 2 | 2 | 0 | 0 | 0 | 1 | — | — | 50,0 % | 100,0 % |
| F4 | 2 | 0 | 0 | 0 | 0 | 1 | — | — | 50,0 % | 100,0 % |
| F5 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | 100,0 % |
| G1 | 2 | 1 | 1 | 1 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| G2 | 2 | 2 | 2 | 2 | 0 | 0 | 100,0 % | 100,0 % | 100,0 % | 100,0 % |
| G3 | 4 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |
| G4 | 4 | 4 | 3 | 3 | 0 | 1 | 100,0 % | 100,0 % | 75,0 % | 100,0 % |
| G5 | 2 | 2 | 1 | 1 | 0 | 1 | 100,0 % | 100,0 % | 50,0 % | 100,0 % |
| G6 | 2 | 0 | 0 | 0 | 0 | 0 | — | — | 100,0 % | — |

## Exactitude d'extraction par champ obligatoire

48 dossier(s) ; global : 60,5 % (9328/15415).

| Champ | n | Corrects | Exactitude |
|---|---|---|---|
| `avoir.date` | 12 | 12 | 100,0 % |
| `avoir.lignes[].montant_ht` | 12 | 12 | 100,0 % |
| `avoir.lignes[].nature` | 12 | 0 | 0,0 % |
| `avoir.numero` | 12 | 12 | 100,0 % |
| `avoir.refs_facture_origine` | 12 | 0 | 0,0 % |
| `avoir.total_credite_ttc` | 12 | 12 | 100,0 % |
| `declaration.articles[].code_marchandise` | 363 | 331 | 91,2 % |
| `declaration.articles[].masse_brute` | 363 | 272 | 74,9 % |
| `declaration.articles[].masse_nette` | 363 | 254 | 70,0 % |
| `declaration.articles[].pays_origine` | 363 | 322 | 88,7 % |
| `declaration.date_acceptation` | 73 | 68 | 93,2 % |
| `declaration.devise_facture` | 73 | 70 | 95,9 % |
| `declaration.documents_references` | 73 | 0 | 0,0 % |
| `declaration.importateur.tva` | 73 | 66 | 90,4 % |
| `declaration.incoterm` | 73 | 69 | 94,5 % |
| `declaration.indices_autoliquidation` | 73 | 0 | 0,0 % |
| `declaration.montant_total_facture` | 73 | 69 | 94,5 % |
| `declaration.mrn` | 73 | 58 | 79,5 % |
| `declaration.nombre_articles` | 73 | 69 | 94,5 % |
| `declaration.taux_change` | 73 | 36 | 49,3 % |
| `declaration.taux_change_sens` | 73 | 35 | 47,9 % |
| `declaration.taxations[].article` | 753 | 604 | 80,2 % |
| `declaration.taxations[].base_montant` | 753 | 590 | 78,3 % |
| `declaration.taxations[].base_quantite` | 753 | 20 | 2,7 % |
| `declaration.taxations[].categorie` | 753 | 0 | 0,0 % |
| `declaration.taxations[].montant` | 753 | 604 | 80,2 % |
| `declaration.taxations[].paiement_normalise` | 753 | 0 | 0,0 % |
| `declaration.taxations[].taux` | 753 | 564 | 74,9 % |
| `declaration.taxations[].type_taxe` | 753 | 616 | 81,8 % |
| `declaration.total_a_payer` | 73 | 68 | 93,2 % |
| `facture_commerciale.acheteur.tva` | 70 | 65 | 92,9 % |
| `facture_commerciale.date` | 70 | 67 | 95,7 % |
| `facture_commerciale.devise` | 70 | 69 | 98,6 % |
| `facture_commerciale.incoterm` | 70 | 70 | 100,0 % |
| `facture_commerciale.lignes[].code_marchandise_imprime` | 365 | 254 | 69,6 % |
| `facture_commerciale.lignes[].montant_ligne` | 365 | 304 | 83,3 % |
| `facture_commerciale.lignes[].pays_origine` | 365 | 305 | 83,6 % |
| `facture_commerciale.lignes[].quantite` | 365 | 286 | 78,4 % |
| `facture_commerciale.lignes[].unite` | 365 | 0 | 0,0 % |
| `facture_commerciale.masse_brute_totale` | 70 | 67 | 95,7 % |
| `facture_commerciale.nombre_colis` | 70 | 67 | 95,7 % |
| `facture_commerciale.numero` | 70 | 66 | 94,3 % |
| `facture_commerciale.total_facture` | 70 | 65 | 92,9 % |
| `facture_commerciale.total_imprime` | 70 | 0 | 0,0 % |
| `facture_transitaire.client_facture.tva` | 60 | 59 | 98,3 % |
| `facture_transitaire.date` | 60 | 58 | 96,7 % |
| `facture_transitaire.emetteur.tva` | 60 | 58 | 96,7 % |
| `facture_transitaire.lignes[].libelle` | 492 | 261 | 53,0 % |
| `facture_transitaire.lignes[].montant_ht` | 492 | 322 | 65,5 % |
| `facture_transitaire.lignes[].montant_tva` | 492 | 299 | 60,8 % |
| `facture_transitaire.lignes[].mrn` | 492 | 365 | 74,2 % |
| `facture_transitaire.lignes[].nature` | 492 | 0 | 0,0 % |
| `facture_transitaire.lignes[].prix_unitaire` | 492 | 322 | 65,5 % |
| `facture_transitaire.lignes[].quantite` | 492 | 396 | 80,5 % |
| `facture_transitaire.lignes[].taux_tva` | 492 | 385 | 78,2 % |
| `facture_transitaire.numero` | 60 | 58 | 96,7 % |
| `facture_transitaire.refs_mrn` | 60 | 0 | 0,0 % |
| `facture_transitaire.refs_transport` | 60 | 0 | 0,0 % |
| `facture_transitaire.total_debours` | 60 | 55 | 91,7 % |
| `facture_transitaire.total_ht` | 60 | 57 | 95,0 % |
| `facture_transitaire.total_ttc` | 60 | 57 | 95,0 % |
| `facture_transitaire.total_tva` | 60 | 58 | 96,7 % |

## Regroupement (liens attendus)

VP 278, FP 19, FN 0 — précision 93,6 %, rappel 100,0 %, F1 96,7 % (modes : {'documents': 48}).

## Coût IA et durée par dossier

| | n | Moyenne | Médiane | p95 | Maximum |
|---|---|---|---|---|---|
| Coût IA (EUR) | 48 | 0,0000 | 0,0000 | 0,0000 | 0,0000 |
| Durée (s) | 48 | 14,2838 | 10,1880 | 36,5560 | 137,8310 |

## Alertes (non bloquantes)

- bruit a_verifier non apparié 1.625 par dossier > 1.5

_Formulations interdites : source `/home/user/v2/config/formulations_interdites.yaml`._
