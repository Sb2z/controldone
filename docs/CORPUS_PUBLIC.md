# Corpus public de factures électroniques

Ce document recense les spécimens publics utilisés pour éprouver la lecture des factures électroniques
(Factur-X / ZUGFeRD, XRechnung, CII, UBL, Peppol BIS 3). Il indique aussi comment les récupérer et ce que la
mesure a donné. Décisions associées : D-1500 à D-1509 (`docs/DECISIONS.md`, section « Corpus public »).

## Principe

- **Aucun fichier tiers n'est versionné.** `scripts/corpus_public.py fetch` clone les dépôts (`git clone --depth 1`)
  dans `var/corpus_public/<source>/`. Ce répertoire est ignoré par git (`.gitignore` : `var/`).
- Le dépôt ne contient que le script et ce document.
- Les tests unitaires n'emploient que des XML minimaux écrits à la main, avec des données FICTIVES
  (`tests/ingest/test_ingest_structure_public.py`). Aucun spécimen n'y est recopié.
- Seuls servent des fichiers publiés comme exemples ou fichiers de test. Les dossiers qui contiennent, ou
  pourraient contenir, de vrais documents d'entreprise sont exclus (voir plus bas).
- Le contenu des fichiers est une donnée : rien n'est exécuté ni interprété.

```
python scripts/corpus_public.py fetch                    # clone / met à jour les 4 dépôts
python scripts/corpus_public.py run --workers 3          # pipeline complet + diagnostic, résultats JSON + .md
python scripts/corpus_public.py run --sans-diagnostic --source en16931 --ecarts
python scripts/corpus_public.py compare avant.json apres.json
```

Les résultats sont écrits dans `var/corpus_public/rapport/` (`resultats.json` et `.md`). Les rapports de diagnostic
de chaque fichier vont dans un dossier temporaire (`--diag-out`).

## Sources

| Source (`--source`) | Dépôt | Licence | Révision mesurée | Fichiers retenus |
|---|---|---|---|---|
| `zugferd` | https://github.com/ZUGFeRD/corpus | Apache-2.0 (fichier `LICENSE` du dépôt). Les exemples ZUGFeRD 1.0 et `XML-Rechnung` dérivent des exemples FeRD, diffusés sous la licence d'usage gratuite de FeRD rappelée en tête des XML. | `d891458` (2026-08-11) | 237 |
| `en16931` | https://github.com/ConnectingEurope/eInvoicing-EN16931 | EUPL-1.2 | `b6c9e06` (2026-04-14) | 351 (dont 277 tests unitaires) |
| `peppol` | https://github.com/OpenPEPPOL/peppol-bis-invoice-3 | Pas de fichier `LICENSE` dans le dépôt. © OpenPeppol AISBL, exemples publiés avec la spécification. Usage local de test seulement, sans redistribution. | `261c458` (2026-03-16) | 258 (dont 246 tests unitaires ou extraits) |
| `facturx` | https://github.com/akretion/factur-x | BSD-3-Clause | `6ce0740` (2026-10-04) | 13 |

Dossiers retenus par source (motifs du script) :

- `zugferd` : `ZUGFeRDv1/`, `ZUGFeRDv2/` (dossiers `correct` et `fail`), `XML-Rechnung/` (FX, CII, UBL), `PEPPOL/`,
  `fatturaPA/` (format italien non pris en charge : il doit finir en « non reconnu », sans erreur) et `other/`
  (fichiers de test EICAR).
- `en16931` : `cii/examples/`, `ubl/examples/`, `test/testfiles/`, `test/cii/`, `edifact/examples/` (EDIFACT en XML,
  non pris en charge). Les tests unitaires `test/Invoice-unit-UBL/` et `test/CreditNote-unit-UBL/` servent à la
  robustesse seulement : ce sont des enveloppes `testSet`, pas des factures.
- `peppol` : `rules/examples/`, `rules/national-examples/`. Les tests unitaires `rules/unit-*/` et les extraits
  `rules/snippets/` servent à la robustesse seulement.
- `facturx` : `tests/fixtures/` (XML Factur-X de chaque profil, ZUGFeRD 1.0, UBL, Order-X, un PDF).

### Exclusions (documents d'apparence réelle)

| Fichier ou dossier | Raison |
|---|---|
| `zugferd/unstructured/` | Facture réelle d'un hébergeur (PDF sans XML). |
| `zugferd/incoming/` | Dépôt de factures reçues par le projet (vide à cette révision). Exclu par principe. |
| `zugferd/ZUGFeRDv2/fail/FX-With-UBL-REC50304330.pdf` | Document réel partiellement pseudonymisé : numéros de client et de commande, nom de contact, numéro de TVA d'émetteur plausible. |

Le README du dépôt `ZUGFeRD/corpus` le présente comme une « collection of real, sample and test electronic
invoices ». Seuls les sous-dossiers d'éditeurs et d'organismes (FeRD, Intarsys, Mustang, Symtrax, FNFE, Konik,
4s4u, Qvalia) sont gardés. Leurs parties sont fictives (« Musterlieferant », « Lieferant GmbH », SAP « Elektromarkt
Bamby »…).

## Ce que mesure le script

Le script passe chaque fichier dans le vrai pipeline, sans IA (`OptionsPipeline(llm=False)`) :

1. réception : type par octets, refus ;
2. pages ;
3. classement ;
4. extracteurs `structure` ;
5. regroupement ;
6. contrôles et rapport complet, l'équivalent de `controldone diagnostic <fichier>` sur un lot d'un seul fichier.

L'extracteur `structure` est aussi appelé directement, parce que le pipeline isole et journalise les exceptions.

La **vérité de terrain** est lue dans le XML par un lecteur XPath indépendant, écrit dans le script et sans aucun
code de `controldone`. Pour un PDF, la pièce jointe est lue avec `pypdf`. Champs comparés :

| Clé | Terme EN 16931 | Champ du modèle |
|---|---|---|
| `type` | BT-3 (381, 261, 262, 396, 532, ou total BT-112 négatif → avoir) | type du document |
| `numero`, `date`, `devise` | BT-1, BT-2, BT-5 | `numero`, `date`, `devise` |
| `bt112_total` | BT-112 | `total_facture` / `total_ttc` / `total_credite_ttc` |
| `bt109_ht`, `bt110_tva`, `bt115_net` | BT-109, BT-110 (dans la devise BT-5), BT-115 | facture transitaire et avoir seulement : le modèle de facture commerciale ne les porte pas |
| `tva_vendeur`, `tva_acheteur` | BT-31, BT-48 (schéma `VA` / `VAT`) | `vendeur.tva` / `emetteur.tva`, `acheteur.tva` / `client_facture.tva` |
| `nb_lignes`, `montants_lignes` | nombre de BG-25 ; multiensemble des BT-131 en valeur absolue | `lignes[]` |
| `remises_frais` | montants BG-20 / BG-21 du document, plus les frais logistiques EXTENDED / ZUGFeRD 1.0 | `sous_totaux[]` |

Règles de comparaison :

- Les montants sont comparés en `Decimal`, en valeur absolue. Le signe est porté par `signe_imprime` (§5.2).
- « n/a » : rien n'est attendu, ou le champ n'existe pas dans le modèle du type obtenu.
- Une « ligne » ZUGFeRD 1.0 qui ne contient que du texte (ni article ni montant) n'est pas comptée comme ligne de
  facture.

## Résultats (révisions ci-dessus, 859 fichiers, 320 factures avec vérité XML)

Mesure refaite le 2026-10-05 après redémarrage et ajout de D-1509 : chiffres identiques, 0 régression
(`compare`).

**Avant** : code du dépôt avant ce lot de corrections. Les deux factures Qvalia géantes en sont exclues : la lecture,
quadratique, dépassait 15 minutes. **Après** : code corrigé, tous les fichiers.

| Champ | Avant | Après |
|---|---|---|
| type (facture / avoir) | 278/318 (87,4 %) | 319/320 (99,7 %) |
| numéro BT-1 | 291/318 (91,5 %) | 319/320 (99,7 %) |
| date BT-2 | 291/318 (91,5 %) | 319/320 (99,7 %) |
| devise BT-5 | 291/315 (92,4 %) | 316/317 (99,7 %) |
| total BT-112 | 291/318 (91,5 %) | 319/320 (99,7 %) |
| HT BT-109 (FT / avoir) | 15/37 (40,5 %) | 35/36 (97,2 %) |
| TVA BT-110 (FT / avoir) | 15/38 (39,5 %) | 35/36 (97,2 %) |
| TVA vendeur BT-31 | 256/297 (86,2 %) | 298/299 (99,7 %) |
| TVA acheteur BT-48 | 80/91 (87,9 %) | 84/84 (100 %) |
| nombre de lignes | 291/318 (91,5 %) | 319/320 (99,7 %) |
| montants de ligne BT-131 | 275/301 (91,4 %) | 302/303 (99,7 %) |
| remises et frais | 74/85 (87,1 %) | 71/71 (100 %) |

- **Seul écart restant** : `Large_Invoice_sample2.xml` (61 Mo) est refusé à la réception avec le motif `trop_gros`
  (limite de 50 Mo, §20.3). C'est le comportement attendu.
- **Aucune régression** : aucun champ juste avant n'est faux ou manquant après.
- **19 comparaisons sont devenues « n/a »** : 10 factures à total négatif (380 / 384) sont désormais des avoirs, et
  le modèle `avoir` ne porte ni l'acheteur ni les sous-totaux.

Détail après correction, par profil :

| Profil | n | type | numéro | total | TVA vendeur | lignes | montants de ligne |
|---|---|---|---|---|---|---|---|
| MINIMUM | 9 | 9/9 | 9/9 | 9/9 | 9/9 | 9/9 | – |
| BASIC WL | 7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | – |
| BASIC | 13 | 13/13 | 13/13 | 13/13 | 13/13 | 13/13 | 13/13 |
| EN16931 | 143 | 143/143 | 143/143 | 143/143 | 139/139 | 143/143 | 143/143 |
| EXTENDED | 17 | 17/17 | 17/17 | 17/17 | 15/15 | 17/17 | 17/17 |
| XRechnung | 19 | 19/19 | 19/19 | 19/19 | 19/19 | 19/19 | 19/19 |
| Peppol BIS 3 | 84 | 83/84 | 83/84 | 83/84 | 74/75 | 83/84 | 83/84 |
| ZUGFeRD 1.0 (BASIC / COMFORT / EXTENDED) | 25 | 25/25 | 25/25 | 25/25 | 19/19 | 25/25 | 24/24 |

Avant correction, les 25 ZUGFeRD 1.0 n'avaient aucun champ structuré : 0/25 sur le numéro et le total, et 4
seulement classés facture.

### Robustesse, classement, temps (après)

- **Exceptions non gérées : 0** sur 859 fichiers, dans chacune des étapes : extracteur direct, préparation,
  contrôles et rapport. Erreurs isolées par le pipeline : 0.
  - Avant : 1 exception, `_csv.Error` (« field larger than field limit »), sur un UBL à pièce jointe base64 pris
    pour un CSV.
  - Avant toujours : 2 fichiers refusés à tort (`non_supporte`, XML commençant par un commentaire), et une lecture
    quadratique de plus de 15 minutes sur la facture de 26 813 lignes.
- **Refus** : 1, `trop_gros`.
- **Formats reconnus** :

  | Format | Fichiers |
  |---|---|
  | Factur-X / ZUGFeRD PDF | 147 |
  | UBL | 107 |
  | CII | 62 |
  | ZUGFeRD 1.0 en XML | 3 |
  | Order-X (bon de commande, P2) | 2 |
  | Rien de structuré (tests unitaires `testSet`, FatturaPA, EDIFACT) | 538 |

- **Classement des 320 factures** : 284 factures commerciales, 35 avoirs, 1 refus. Aucune facture de transitaire :
  aucune ligne ne décrit des débours.
- **Codes de type BT-3 des 320 factures** et classement obtenu :

  | Code | n | Classement |
  |---|---|---|
  | 380 | 246 | 235 facture commerciale, 10 avoirs (total négatif, D-1504), 1 refus (`trop_gros`) |
  | 381 | 15 | 15 avoirs |
  | 384 | 10 | 10 avoirs : tous les spécimens « Rechnungskorrektur » ont un total négatif |
  | 389 (autofacture) | 10 | 10 factures commerciales |
  | 575, 387, 204, 877, 751, sans code | 39 | factures commerciales |

  Aucun spécimen n'a le code 261 : il est couvert par un test unitaire (avoir).
- **Acompte et arrondi** : 200 factures portent BT-113 (souvent à zéro), 23 portent BT-114, dont 14 non nul (exemples
  Peppol suédois et norvégien). Aucune n'est une facture de transitaire. Pour une facture de transitaire à arrondi non
  nul, le net à payer n'est pas transmis (D-1509).
- **Validité au schéma** : 300 valides, 21 non valides, lues avec une confiance de 0,95. Ce sont surtout des
  ZUGFeRD 2.0 / 2.1 antérieurs aux XSD Factur-X 1.07 embarqués, des dossiers `fail/` et des exemples grecs Peppol.
- **Temps**, avec le cache de pages chaud :

  | Mesure | Temps |
  |---|---|
  | Préparation, médiane (PDF / XML) | 0,02 s / 0,01 s |
  | Contrôles et rapport, médiane | 0,07 s à 0,18 s |
  | Facture de 26 813 lignes (25 Mo) | 31 s de préparation et 14 s de diagnostic |
  | Ensemble, 3 processus | 74 s |

## Limites connues

- Le modèle ne porte pas l'arrondi BT-114. Le net à payer d'une facture de transitaire à arrondi non nul n'est donc
  pas lu (D-1509) ; le contrôle D1 `net_a_payer` n'est pas exécuté pour elle.

- Le modèle `facture_commerciale` ne porte ni BT-109, ni BT-110, ni BT-115, ni l'acompte (BT-113). Le modèle
  `avoir` ne porte ni l'acheteur ni les remises et frais. Ces champs sont lus par le script mais pas comparés.
- Des XML valides pour leur version d'origine (ZUGFeRD 2.0, profil « comfort » d'exemples CEN anciens) sont non
  valides pour les XSD actuels : confiance 0,95, par prudence.
- FatturaPA, EDIFACT et Order-X ne sont pas des factures EN 16931 lues par ControlDOne :
  - FatturaPA et EDIFACT finissent en « document non reconnu » ;
  - Order-X et UBL `Order` sont classés `document_non_exploitable` avec le motif `bon_commande`.
