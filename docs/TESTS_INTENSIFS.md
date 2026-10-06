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

## Deuxième cycle : générateur 2.1 et `corpus_g4` (5–6 octobre 2026)

**Nouveau jeu.** `bench/corpus_g4` compte 220 dossiers, 175 de développement et 45 tenus à l'écart. Il a été
produit par le générateur 2.1 (graine 20261006) avec des éléments jamais vus :
- quatre familles de transitaires (portugaise à lignes TTC, polonaise au kilo avec page récapitulative,
  suisse-allemande avec avoirs mêlés, française en paysage par MRN) ;
- trois mises en page de déclaration (feuillet + annexes, état de liquidation en paysage, XML anglais) ;
- trois mises en page de facture (portugaise, polonaise, multi-pages avec reports) ;
- cinq dégradations (fax, tampons et manuscrit, JPEG très compressé, faible contraste, deux pages par feuille) ;
- quatre situations de clients (importateur suisse avec représentant fiscal, holding, TVA espacée, nom commercial).

93 % des dossiers contiennent au moins un élément nouveau.

**Travail.** Quatre équipes ont travaillé sur les seuls dossiers de développement (D-2301 à D-2711) :
- lecture des déclarations, classement et regroupement ;
- lecture des factures ;
- prétraitement OCR des scans dégradés (`VERSION_PAGES` 1.1.0) ;
- contrôles.

Les 45 dossiers tenus à l'écart n'ont été ouverts par personne.

| `corpus_g4`, tenu à l'écart (45 dossiers) | Avant | Après |
|---|---|---|
| Écarts certains vrais / faux | 8 / 0 | **23 / 1** |
| Précision des écarts certains | 100 % (8 constats) | **95,8 %** (borne basse de Wilson 79,8 %) |
| Rappel (toutes erreurs) | 48,0 % | **78,7 %** |
| Rappel des erreurs attendues « certain » | 13,3 % | 42,2 % |
| Exactitude des montants | 80,0 % | 94,3 % |
| Constats « à vérifier » sans erreur, par dossier | 3,07 | 1,04 |
| Pièges déclenchés | 16 | 4 |
| Seuil bloquant | passe (8 constats, sans portée) | **échoue d'un seul constat** (D4) |

Non-régression sur les autres jeux tenus à l'écart (même code, OCR 1.1.0) :

| Jeu | Vrais / faux certains | Précision | Rappel | Seuil |
|---|---|---|---|---|
| `corpus_g3` (80) | 62 / 0 | 100 % | 85,6 % | passe |
| `corpus_g2` (68) | 36 / 0 | 100 % | 77,7 % | passe |
| `corpus_h2` (48) | 45 / 1 (A4) | 97,8 % | 80,4 % | passe |
| `corpus` (48) | 45 / 0 | 100 % | 84,6 % | passe |

**Lecture honnête.**
- **Sur des documents vraiment nouveaux**, l'outil trouve maintenant près de 4 erreurs sur 5. Le seuil de
  précision n'est pas atteint : 1 faux écart certain sur 24, sur la commission d'avance de fonds (D4). L'échantillon
  est petit ; un faux de moins ferait passer le seuil, un de plus le ferait chuter à 92 %.
- **Je n'ai consulté que le contrôle en cause**, pas le dossier. Pour le corriger proprement, il faudra le faire sur
  les jeux de développement puis mesurer sur une graine neuve.
- **Le rappel des erreurs attendues « certain » reste bas** sur les nouveaux éléments (42 %). Les lectures OCR
  incertaines maintiennent ces constats en « à vérifier », ce qui est le comportement voulu, mais coûte du temps de
  validation.
- **Durée par dossier, OCR 1.1.0 compris** (première passe, sans cache) : 4,6 à 8,8 s en moyenne selon le jeu,
  p95 entre 12 et 31 s.

## Troisième cycle : `corpus_g5` vierge (6 octobre 2026)

**Jeu.** `bench/corpus_g5` : 110 dossiers, tous tenus à l'écart. Il a été généré par le générateur 2.1 avec `--ext`
(graine 20261007) : 95 % des dossiers portent un élément nouveau, avec 128 erreurs dont 40 attendues « certain »,
et 505 pièges. Personne ne l'a ouvert. Avant la mesure finale, seuls les totaux de la mesure de départ ont été lus.

**Travail.** Il a été fait sur les seuls dossiers de développement :
- contrôles (D-2801 à D-2806) : commission d'avance (D4) certaine seulement si l'assiette et la grille sont
  établies, périmètre établi pour A4/A5, nouvelles identités imprimées pour le rappel ;
- lecture (D-2901 à D-2908, `VERSION_PAGES` 1.1.1) : documents de deux pages recollés, totaux par code de taxe
  lus pour confirmer, identités imprimées sur les factures de transitaire scannées, faux « deux pages par feuille »
  corrigé.

| `corpus_g5` (vierge, 110 dossiers) | Avant le cycle | Après |
|---|---|---|
| Écarts certains vrais / faux | 31 / 1 | **35 / 1** |
| Précision des écarts certains | 96,9 % | **97,2 %** (borne basse de Wilson 85,8 %) |
| Rappel (toutes erreurs) | 78,1 % | 79,7 % |
| Rappel des erreurs attendues « certain » | 62,5 % | 72,5 % |
| Exactitude des montants | 92,5 % | 90,9 % |
| Constats « à vérifier » sans erreur, par dossier | 2,02 | 1,95 |
| Pièges déclenchés (« à vérifier ») | 43 | 47 |
| Seuil bloquant | échoue | **passe** |

Tous les jeux, même code (OCR 1.1.1) :

| Jeu | Statut | Vrais / faux certains | Précision | Rappel | Seuil |
|---|---|---|---|---|---|
| `corpus_g5` (110) | vierge | 35 / 1 | 97,2 % | 79,7 % | passe |
| `corpus_g4` holdout (45) | contrôle fautif vu au cycle 2 | 29 / 0 | 100 % | 79,5 % | passe |
| `corpus_g3` (80) | vu sous forme agrégée | 65 / 0 | 100 % | 87,8 % | passe |
| `corpus_g2` holdout (68) | vu | 37 / 0 | 100 % | 81,5 % | passe |
| `corpus_h2` (48) | vu | 45 / 0 | 100 % | 80,4 % | passe |
| `corpus` holdout (48) | vu | 44 / 0 | 100 % | 84,6 % | passe |
| dev `corpus_g4` / `corpus_g2` / `corpus` | développement | 98 / 0, 113 / 0, 120 / 0 | 100 % | 82–86 % | passe |

**Lecture honnête.**
- **Le seuil est franchi de justesse sur le jeu vierge.** Il reste 1 faux sur 36 écarts certains, et un faux de plus
  ferait échouer le seuil (94,6 %). La borne basse de Wilson (85,8 %) dit la même chose : sur des documents vraiment
  nouveaux, il faut s'attendre à quelques fausses certitudes par centaine d'écarts. La validation humaine prévue reste
  indispensable.
- **Le bruit reste au-dessus de l'alerte sur ce jeu** : 1,95 constat « à vérifier » sans erreur par dossier, pour un
  seuil d'alerte de 1,5. C'est du temps de validation, pas une fausse accusation.
- **Limite connue** : les erreurs sur un total par code de taxe de la déclaration (B2 par code) ne sont pas détectées.
  Le modèle de données n'a pas de champ pour ces totaux.
- **Durée par dossier, OCR compris** : 5 à 9 s en moyenne selon le jeu, p95 entre 15 et 30 s.

## Quatrième mesure : lot moteur, sécurité, sauvegardes, interface — `corpus_g6` vierge (6 octobre 2026)

**Le jeu.** `bench/corpus_g6` compte 160 dossiers, tous tenus à l'écart, générés avec `--ext --per-control 3` et la
graine 20261008. Il contient 190 erreurs, dont 74 attendues « certain », et 767 pièges. Il n'est pas versionné : la
commande de régénération et l'empreinte de contrôle sont dans `docs/backlog/orchestrateur.md`. Personne ne l'a
ouvert ; seuls les totaux ont été lus.

| `corpus_g6` (vierge) | Avant le lot | Après |
|---|---|---|
| Écarts certains vrais / faux | 56 / 1 | **59 / 1** |
| Précision des écarts certains | 98,2 % (Wilson 90,7 %) | **98,3 %** (Wilson 91,1 %) |
| Rappel (toutes erreurs) | 74,7 % | 75,3 % |
| Rappel des erreurs attendues « certain » | 64,9 % | 68,9 % |
| Exactitude des montants | 96,3 % | 96,5 % |
| « À vérifier » sans erreur, par dossier | 2,06 | 1,89 |
| Pièges déclenchés (« à vérifier ») | 56 | 50 |
| Seuil bloquant | passe | **passe** |

Autres jeux tenus à l'écart, même code. Aucun faux certain nouveau ; tous les seuils passent.

| Jeu | Vrais / faux certains | Précision | Rappel | Bruit / dossier |
|---|---|---|---|---|
| `corpus_g5` (110) | 37 / 1 (35 / 1 avant) | 97,4 % | 81,3 % | 1,79 (1,95 avant) |
| `corpus_g4` (45) | 31 / 0 | 100 % | 80,3 % | 0,80 |
| `corpus_g3` (80) | 66 / 0 | 100 % | 88,8 % | 0,81 |
| `corpus_g2` (68) | 39 / 0 | 100 % | 83,1 % | 0,78 |
| `corpus_h2` (48) | 46 / 0 | 100 % | 81,1 % | 1,40 |
| `corpus` (48) | 45 / 0 | 100 % | 85,2 % | 0,96 |

**À retenir.**
- Sur des documents jamais vus, le bruit « à vérifier » reste au-dessus de l'alerte (1,8 à 1,9 par dossier, pour
  1,0 à 1,2 sur les jeux de développement). Les pistes restantes sont dans `docs/A_FAIRE.md` § 3 : P4 au
  regroupement, D1 sur scans, A13 sur décision.
- La marge du seuil reste faible sur les jeux de type `--ext` : 1 faux certain sur 60. La validation humaine reste
  la règle.

## Cinquième mesure : lot 2 (production, sécurité, moteur, interface, outillage) — `corpus_g7` vierge (6 octobre 2026)

**Le jeu.** `bench/corpus_g7` compte 160 dossiers, tous tenus à l'écart, générés avec `--ext --per-control 3` et la
graine 20261009. Il contient 189 erreurs, dont 74 attendues « certain », et 739 pièges. Il n'est pas versionné : sa
recette et son empreinte sont dans `docs/backlog/orchestrateur.md`.

| `corpus_g7` (vierge) | Avant le lot 2 | Après le lot 2 (D-3710 compris) |
|---|---|---|
| Écarts certains vrais / faux | 52 / 0 | **53 / 0** |
| Précision (borne basse de Wilson) | 100 % (93,1 %) | 100 % (93,2 %) |
| Rappel (toutes erreurs) | 75,1 % | 76,7 % |
| Rappel des erreurs attendues « certain » | 62,2 % | 63,5 % |
| « À vérifier » sans erreur, par dossier | 1,64 | **1,41** (sous l'alerte de 1,5) |
| Pièges déclenchés | 44 | 33 |

**Régression trouvée puis corrigée.** La première mesure après le lot 2 a montré deux faux écarts certains
nouveaux : un B2 sans erreur sur `corpus_g7`, un C5 au montant faux sur `corpus_g6`, qui faisait aussi échouer le
seuil par contrôle de ce jeu. La cause : des totaux par code de taxe déduits (D-3706) pouvaient confirmer des valeurs
jusqu'à la certitude. La correction (D-3710) a été faite sur les seuls jeux de développement, à partir du symptôme
agrégé : un total déduit ne fonde plus jamais un écart certain. Après correction, les deux faux certains ont disparu.
Pour diagnostiquer, j'ai lu le contrôle en cause sur ces deux jeux : ils ne sont donc plus parfaitement vierges.

| Jeu tenu à l'écart | Vrais / faux certains | Précision | Rappel | Bruit / dossier (avant le lot 2) |
|---|---|---|---|---|
| `corpus_g7` (160) | 53 / 0 | 100 % | 76,7 % | 1,41 (1,64) |
| `corpus_g6` (160) | 59 / 1 | 98,3 % | 75,8 % | 1,49 (1,89) |
| `corpus_g5` (110) | 37 / 1 | 97,4 % | 81,3 % | 1,55 (1,79) |
| `corpus_g4` (45) | 31 / 0 | 100 % | 80,3 % | 0,71 (0,80) |
| `corpus_g3` (80) | 66 / 0 | 100 % | 88,8 % | 0,74 (0,81) |
| `corpus_g2` (68) | 39 / 0 | 100 % | 83,1 % | 0,60 (0,78) |
| `corpus_h2` (48) | 46 / 0 | 100 % | 80,4 % | 1,33 (1,40) |
| `corpus` (48) | 45 / 0 | 100 % | 85,2 % | 0,77 (0,96) |

Tous les seuils passent. Le bruit baisse sur tous les jeux tenus à l'écart. Les deux faux certains restants (D1,
un piège sur `corpus_g6` et un non apparié sur `corpus_g5`) existaient déjà avant le lot.

## Sixième mesure : lot 3 — `corpus_g8` et `corpus_g9` vierges (6–7 octobre 2026)

**Jeux.** `corpus_g8` (graine 20261010) et `corpus_g9` (graine 20261011) comptent chacun 160 dossiers, générés avec
`--ext --per-control 3`. `corpus_g8` a 188 erreurs, dont 80 attendues « certain », et 785 pièges ; `corpus_g9` a
190 erreurs, dont 63 attendues « certain », et 772 pièges. Ils ne sont pas versionnés ; leurs recettes et empreintes
sont dans `bench/corpus_empreintes.json`.

**`corpus_g8`.** La première mesure du lot 3 donnait 55 vrais / 2 faux (D4 non apparié, D3 sur un piège), soit 96,5 %
et un seuil échoué ; avant le lot, c'était 54 / 3. Correction D-4212 à D-4215 sur les seuls jeux de développement, à
partir du seul nom des contrôles en cause : **54 vrais / 0 faux**, seuil passé. Ce jeu n'est donc plus vierge pour
D3/D4.

**`corpus_g9`, mesure vierge du code final** : 63 vrais / 1 faux (C1, montant inexact), précision 98,4 % (Wilson
91,7 %), rappel des erreurs attendues « certain » 87,3 %, bruit 1,14 par dossier, **seuil passé**.

| Jeu tenu à l'écart | Vrais / faux certains | Précision | Rappel | Bruit / dossier |
|---|---|---|---|---|
| `corpus_g9` (vierge) | 63 / 1 | 98,4 % | 73,7 % | 1,14 |
| `corpus_g8` | 54 / 0 | 100 % | 82,5 % | 0,98 |
| `corpus_g7` | 52 / 0 | 100 % | 76,7 % | 1,23 |
| `corpus_g6` | 61 / 0 | 100 % | 75,8 % | 1,31 |
| `corpus_g5` | 37 / 0 | 100 % | 80,5 % | 1,35 |
| `corpus_g4` | 32 / 0 | 100 % | 80,3 % | 0,67 |
| `corpus_g3` | 66 / 0 | 100 % | 88,3 % | 0,63 |
| `corpus_g2` | 40 / 0 | 100 % | 83,1 % | 0,57 |
| `corpus_h2` | 46 / 0 | 100 % | 79,7 % | 1,25 |
| `corpus` | 45 / 0 | 100 % | 85,2 % | 0,71 |

**À retenir.** Tous les seuils passent. Pour la première fois, le bruit est sous l'alerte de 1,5 sur tous les jeux.
Sur des documents jamais vus, il reste environ 1 faux certain pour 60 à 65 écarts certains, d'où la nécessité de la
validation humaine. La lecture par Claude (D-4001 à D-4008) n'est pas incluse : elle est inactive tant que la clé
n'est pas fournie.

## Reproduire

```bash
source .venv/bin/activate
CONTROLDONE_PAGES_CACHE_DIR=var/cache/g3_pages python -m controldone.bench_run \
  --corpus bench/corpus_g3 --split holdout --out bench/out/g3 --workers 3
python -m bench.score --corpus bench/corpus_g3 --split holdout --run bench/out/g3 --gate
```

Tests : 2 602 passent ; `ruff check src tests scripts` est propre ; la démonstration complète
(`scripts/demo_complete.sh --sans-serveur`) se termine sans erreur.
