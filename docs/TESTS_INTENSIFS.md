# Tests intensifs et généralisation — octobre 2026

Toutes les données sont **fictives** (générées) ou **publiques** (échantillons officiels de normes de facturation électronique).
Aucun document réel d'entreprise n'a été utilisé.

## En bref

- **Le moteur se trompait beaucoup sur des mises en page qu'il n'avait jamais vues.** Un second générateur, écrit à
  l'aveugle, produit d'autres transitaires, d'autres mises en page, six langues et d'autres formats. Sur sa partie
  tenue à l'écart, 30 des 36 écarts donnés comme « certains » étaient faux (précision 16,7 %).
- **Après le chantier, sur un troisième jeu entièrement neuf** (80 dossiers, graine 20261005, jamais vu par les équipes
  qui ont corrigé le code), on compte **50 écarts certains justes et 1 faux**. La précision est de 98,0 % (borne basse
  de Wilson à 95 % : 89,7 %), le rappel de 85,1 %, et **le seuil bloquant est franchi**.
- **Aucune régression sur les anciens corpus** : précision de 100 % sur les trois jeux tenus à l'écart, seuil passé
  partout.
- **Robustesse** : 571 entrées hostiles (archives piégées, PDF corrompus ou chiffrés, XML malveillants, fichiers
  géants) ne produisent aucun plantage, aucune perte silencieuse et aucun dépassement de mémoire. Une endurance de
  1 010 dossiers a été menée sans fuite.
- **Corpus public** : 859 fichiers officiels (ZUGFeRD, Factur-X, EN 16931, Peppol) sont traités sans aucune exception.
  Les champs structurés sont lus à 99,7 %.

## Sources de test

| Source | Contenu | Usage |
|---|---|---|
| Corpus public (`scripts/corpus_public.py`, `docs/CORPUS_PUBLIC.md`) | 859 factures électroniques officielles : ZUGFeRD 1/2, Factur-X, EN 16931 (CII, UBL), Peppol | robustesse et lecture des formats structurés |
| `bench/corpus` (générateur 1) | 202 dossiers de développement + 48 tenus à l'écart | non-régression |
| `bench/corpus_h2` (générateur 1, autre graine) | 48 dossiers tenus à l'écart | non-régression |
| `bench/corpus_g2` (générateur 2, écrit à l'aveugle) | 232 dossiers de développement + 68 tenus à l'écart ; 4 nouveaux clients, 12 familles de transitaires, 6 mises en page de déclaration, de/it/es/nl/en/fr, XML, CSV, XLSX, UBL, CII, courriels | généralisation |
| `bench/corpus_g3` (générateur 2, graine neuve) | 80 dossiers, tous tenus à l'écart, 188 erreurs, 246 pièges | mesure vierge finale |
| Campagne hostile (`scripts/fuzz/`, `docs/ROBUSTESSE.md`) | 571 entrées cassées ou malveillantes, 300 mutations | robustesse |

## Résultats, avant et après

### Lecture des documents (développement du nouveau corpus, `scripts/mesure_extraction.py`)

| Document | Avant | Après |
|---|---|---|
| Déclarations : champs obligatoires | 35,5 % | 85,9 % |
| Déclarations : champs clés | 49,4 % | 92,1 % |
| Factures de transitaire : champs obligatoires | 51 % | 76,7 % (89,4 % hors conventions de vérité) |
| Factures commerciales : champs obligatoires | 61,9 % | 86,2 % |
| Factures commerciales : champs clés (TVA acheteur, devise, numéro, total) | 61,3 % | 95,8 % |
| Documents support (listes de colisage, titres de transport) | 31,5 % | 88,0 % |
| Classement des pages par type | 76,4 % | 99,4 % |
| Regroupement en dossiers (F1) | 0,846 | 0,959 |

Quand la confiance affichée est d'au moins 0,90, les valeurs lues sont justes à 99,9 % ou plus, pour chaque type de
document.

### Contrôles (seuil bloquant `docs/SPEC.md` §19.7)

| Jeu tenu à l'écart | Écarts certains vrais / faux | Précision | Borne basse (Wilson 95 %) | Rappel | Montants justes | Seuil |
|---|---|---|---|---|---|---|
| `corpus_g2` avant le chantier | 6 / 30 | 16,7 % | 7,9 % | 31,5 % | 72,2 % | échoue |
| `corpus_g2` après | 34 / 0 | 100 % | 89,9 % | 80,8 % | 92,9 % | passe |
| `corpus_g3` (vierge), première mesure | 50 / 9 | 84,7 % | 73,5 % | 85,1 % | 94,6 % | échoue |
| `corpus_g3`, mesure finale | **50 / 1** | **98,0 %** | **89,7 %** | **85,1 %** | 94,6 % | **passe** |
| `corpus_h2` (non-régression) | 43 / 0 | 100 % | 91,8 % | 75,0 % | 92,6 % | passe |
| `corpus` (non-régression) | 44 / 0 | 100 % | 92,0 % | 83,2 % | 98,3 % | passe |

## Ce qu'il faut savoir sur ces chiffres

1. **La partie tenue à l'écart de `corpus_g2` n'est plus vierge.** La mesure intermédiaire a montré quatre écarts
   arithmétiques faux sur les taxes et les masses des déclarations. Je les ai lus pour en comprendre la nature. La
   correction (D-2210) a ensuite été écrite par une équipe qui ne voyait que les jeux de développement, à partir de la
   seule description des symptômes. C'est pourquoi un troisième jeu neuf a été généré.
2. **`corpus_g3` a été vu sous forme agrégée.** Après la première mesure (84,7 %), j'ai consulté le nombre d'écarts
   faux par contrôle : B2 ×3, B4 ×1, C8 ×2 sur des pièges, D5 ×2, D4 ×1. Aucun dossier n'a été ouvert. Les équipes ont
   corrigé ces familles sur les jeux de développement uniquement (D-2210 à D-2214). La mesure finale reste donc
   légèrement optimiste. Il faudra une nouvelle graine pour une mesure parfaitement vierge.
3. **Un arbitrage entre corpus.** Le cas d'une facture de transitaire adressée à l'acheteur, alors que la déclaration
   nomme un autre importateur, est un écart certain dans le corpus 1 et un piège dans le corpus 2. J'ai retenu la
   prudence : ce cas passe en « à vérifier ». Deux vrais écarts certains du corpus 1 deviennent donc « à vérifier ».
   Ils restent détectés (D-2211).
4. **Le rappel des écarts certains reste moyen** : 56 % sur `corpus_g3`, entre 62 et 69 % ailleurs. Le moteur préfère
   classer « à vérifier » plutôt que d'accuser à tort. Ces constats restent visibles et passent par votre validation.
5. **Les durées des bancs ne sont pas représentatives.** Les pages étaient déjà en cache (OCR fait une fois). Première
   passe sur `corpus_g3`, OCR compris : 5,2 s par dossier en moyenne, p95 15,9 s.
6. **Le cas réel reste à mesurer.** Des documents générés, même par un générateur écrit à l'aveugle, ne remplacent pas
   des documents de clients. Sur une mise en page vraiment inconnue, l'extracteur par modèle de langage (désactivé
   faute de clé d'API) est la réponse prévue. Un premier dossier réel, anonymisé, avec l'accord du client, donnera le
   vrai chiffre.

## Défauts trouvés et corrigés pendant ces tests

- **Plantages et pertes silencieuses** sur les archives corrompues ou vides. Les XML géants consommaient 2,6 Go de
  mémoire, ramenés à 0,4 Go. Les fichiers XLSX géants prenaient 93 s, ramenés à 3 s (D-1600 à D-1608).
- **ZUGFeRD 1.0** : 0 fichier lu sur 25, puis 25 sur 25. Les arrondis BT-114 et les notes d'en-tête CII sont aussi
  traités.
- **Déclarations, factures et supports multilingues** : vocabulaire de/it/es/nl, intitulés cités confondus avec des
  titres, colonnes « Montant CNY » mal découpées, groupements de chiffres indiens, mètre lu comme mètre cube
  (D-2001 à D-2013).
- **Classement et regroupement** : un PDF fusionné finissait dans un seul dossier. Les déclarations de MRN différents
  étaient fusionnées, et des références tronquées par l'OCR citaient plusieurs factures (D-2101 à D-2113).
- **Régression introduite puis corrigée** : un bon de commande intitulé « PURCHASE ORDER / FACTURE » était pris pour
  une facture, si bien que la facture manquante n'était plus signalée (D-2114).
- **Contrôles** :
  - règle de lecture corroborée (D-1700) ;
  - structure du tableau des taxes et des masses validée avant toute certitude (D-2210) ;
  - entité facturée attestée par une autre déclaration (C8) ;
  - doublons non établis (D5) ;
  - assiettes alternatives de la commission d'avance (D4) (D-2201 à D-2214).
- **Banc** : quatre erreurs de vérité ou de notation dans le générateur 2 ont été corrigées par son auteur (D-907,
  version 2.0.1).

## Reproduire

```bash
source .venv/bin/activate
CONTROLDONE_PAGES_CACHE_DIR=var/cache/g3_pages python -m controldone.bench_run \
  --corpus bench/corpus_g3 --split holdout --out bench/out/g3 --workers 3
python -m bench.score --corpus bench/corpus_g3 --split holdout --run bench/out/g3 --gate
```

Tests : 1 896 passent ; `ruff check src tests scripts` est propre ; la démonstration complète
(`scripts/demo_complete.sh --sans-serveur`) se termine sans erreur.
