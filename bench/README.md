# Banc d'essai ControlDOne v2 (données FICTIVES)

| Répertoire | Contenu |
|---|---|
| `generator/`, `generator2/` | générateurs de corpus synthétiques (jamais lus par l'équipe moteur, sauf `FORMATS.md`) |
| `score/` | correcteur (`python -m bench.score`) |
| `corpus/` | corpus de travail (`dev` + `holdout`, générateur 1), régénéré en CI, non versionné |
| `corpus_h2/`, `corpus_g2/` | second holdout du générateur 1, corpus de développement du générateur 2 (non versionnés) |
| `corpus_g3/`, `corpus_g4/`, `corpus_g5/` | corpus historiques versionnés, à retirer de l'historique Git (décision 4A) : régénérables |
| `corpus_g6/` et suivants | corpus **non versionnés** : régénérés par commande, contrôlés par empreinte |
| `corpus_empreintes.json` | recette (générateur, graine, options) et empreintes de **chaque** corpus |

## Corpus régénérables (D-3904, D-4402, D-4403)

Aucun corpus n'a besoin d'être versionné : chacun se régénère par sa recette, consignée avec ses empreintes dans
`corpus_empreintes.json`. `.gitignore` ignore tout `bench/corpus_*/` sauf `corpus_g3`, `corpus_g4` et
`corpus_g5`, encore suivis jusqu'à la réécriture de l'historique (décision du fondateur 4A, faite par
l'orchestrateur). Depuis la racine du dépôt :

```sh
make corpus-tous               # régénère les corpus absents (présents et conformes : sautés), vérifie tout
make corpus-tous FORCE=1       # efface et régénère tout (environ 15 min, 2 Go)
make corpus-verifier           # vérifie tous les corpus présents (CORPUS=corpus_g3 : un seul)
make corpus-g6                 # un corpus (corpus-g2 … corpus-g7, corpus-h2, corpus-dev pour bench/corpus)
make corpus GRAINE=20261101 PREFIXE=GU [NOMBRE=160] [PAR_CONTROLE=3] [SORTIE=bench/corpus_gu]
```

### Recettes

| Corpus | Commande (depuis la racine, environnement actif) | Dossiers |
|---|---|---|
| `corpus` | `python -m bench.generator --out bench/corpus --split all --count 250 --seed 20261002` | 250 (202 dev, 48 holdout) |
| `corpus_h2` | `python -m bench.generator --out bench/corpus_h2 --split holdout --count 250 --seed 20261003` | 48 |
| `corpus_g2` | `python -m bench.generator2 --out bench/corpus_g2 --split all --count 300 --seed 777` | 300 (232 dev, 68 holdout) |
| `corpus_g3` | `python -m bench.generator2 --out bench/corpus_g3 --prefix GY --all-holdout --per-control 3 --count 80 --seed 20261005 --split holdout` | 80 |
| `corpus_g4` | `python -m bench.generator2 --out bench/corpus_g4 --prefix GZ --ext --count 220 --seed 20261006 --split all` | 220 (175 dev, 45 holdout) |
| `corpus_g5` | `python -m bench.generator2 --out bench/corpus_g5 --prefix GW --ext --all-holdout --count 110 --seed 20261007 --split holdout` | 110 |
| `corpus_g6` | `python -m bench.generator2 --out bench/corpus_g6 --prefix GV --ext --all-holdout --per-control 3 --count 160 --seed 20261008 --split holdout` | 160 |
| `corpus_g7` | `python -m bench.generator2 --out bench/corpus_g7 --prefix GU --ext --all-holdout --per-control 3 --count 160 --seed 20261009 --split holdout` | 160 |
| `corpus_g8` | `python -m bench.generator2 --out bench/corpus_g8 --prefix GT --ext --all-holdout --per-control 3 --count 160 --seed 20261010 --split holdout` | 160 |
| `corpus_g9` | `python -m bench.generator2 --out bench/corpus_g9 --prefix GS --ext --all-holdout --per-control 3 --count 160 --seed 20261011 --split holdout` | 160 |
| `corpus_g10` | `python -m bench.generator2 --out bench/corpus_g10 --prefix GR --ext --all-holdout --per-control 3 --count 160 --seed 20261012 --split holdout` | 160 |

`--jobs N` ne change pas le résultat. Toutes ces recettes ont été rejouées le 2026-10-06 avec le générateur
actuel (un seul passage `--split all` reproduit un corpus généré autrefois en deux passages `dev` puis `holdout`) :
voir D-4403 pour le résultat par corpus.

### Empreintes

| Clé | Portée | Comparaison |
|---|---|---|
| `sha256` | les `truth.json` (qui citent l'empreinte de chaque fichier du dossier) | octets exacts, générateur actuel |
| `sha256_historique` | idem | octets de la copie produite avant D-4402, si elle diffère |
| `sha256_pixels` | idem | TIFF par leurs pixels décodés |
| `sha256_arbre` | **tous** les fichiers (`clients/`, `manifest.json`, documents…) sauf `stats_generation.json` (durée) | octets exacts, générateur actuel |
| `sha256_arbre_pixels` | idem | TIFF par leurs pixels ; dans les JSON, l'empreinte d'un TIFF (ou d'un `truth.json` qui en cite un) est remplacée de même |

`sha256` se recalcule sans outil, depuis la racine du corpus :
`find dev holdout -name truth.json 2>/dev/null | LC_ALL=C sort | xargs sha256sum | sha256sum`.
`python scripts/corpus.py empreinte --toutes DOSSIER` affiche toutes les empreintes d'un corpus.

La vérification accepte l'empreinte exacte (`sha256` ou `sha256_historique`), sinon l'empreinte des pixels, et dit
laquelle a servi ; avec les empreintes d'arbre, elle vérifie aussi chaque fichier hors `truth.json`.

**TIFF déterministes (D-4402).** Pillow (LZW ou G4 via libtiff) laissait un octet de remplissage non initialisé
avant le répertoire TIFF : deux générations donnaient les mêmes pixels, pas toujours les mêmes octets. Le
générateur 2 (`degrade.tiff_canonique`) met désormais à zéro tout octet que la structure TIFF ne référence pas :
pixels et étiquettes inchangés, octets reproductibles. Les copies existantes de `corpus_g2` à `corpus_g7` ont été
écrites avant : leurs octets TIFF diffèrent d'une régénération (pas leurs pixels), d'où `sha256_historique`.
Le générateur 1 n'écrit pas de TIFF.

**Nouveau corpus** : `make corpus GRAINE=… PREFIXE=…` affiche ses empreintes ; les ajouter à
`corpus_empreintes.json` (même forme que les autres) pour que `make corpus-verifier` et `make corpus-tous` le
prennent en charge. Un test (`tests/outillage/test_outillage.py`) vérifie que chaque corpus a sa recette complète
et que l'empreinte de `corpus_g6` consignée dans `docs/backlog/orchestrateur.md` est la même.
