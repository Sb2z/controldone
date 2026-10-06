# Banc d'essai ControlDOne v2 (données FICTIVES)

| Répertoire | Contenu |
|---|---|
| `generator/`, `generator2/` | générateurs de corpus synthétiques (jamais lus par l'équipe moteur, sauf `FORMATS.md`) |
| `score/` | correcteur (`python -m bench.score`) |
| `corpus/` | corpus de travail (`dev` + `holdout`), régénéré en CI, non versionné |
| `corpus_g3/`, `corpus_g4/`, `corpus_g5/` | corpus historiques **versionnés** (conservés tels quels) |
| `corpus_g6/` et suivants | corpus **non versionnés** : régénérés par commande, contrôlés par empreinte |
| `corpus_empreintes.json` | recette (générateur, graine, options) et empreinte attendue de chaque corpus non versionné |

## Corpus non versionnés (D-3904)

Les corpus sont reproductibles à l'octet près par leur graine : à partir de `corpus_g6`, on ne les versionne plus
(le dépôt pesait 609 Mo, surtout à cause des PDF de corpus). `.gitignore` ignore tout `bench/corpus_*/` sauf
`corpus_g3`, `corpus_g4` et `corpus_g5`, déjà suivis. Nettoyer l'historique Git demande l'accord du fondateur
(réécriture irréversible) : non fait.

Régénérer et vérifier, depuis la racine du dépôt :

```sh
make corpus-g6                 # régénère bench/corpus_g6 (sauté s'il est déjà conforme), puis vérifie l'empreinte
make corpus-g6 FORCE=1         # efface et régénère
make corpus-verifier           # vérifie seulement (CORPUS=corpus_g6 par défaut)
make corpus GRAINE=20261101 PREFIXE=GU [NOMBRE=160] [PAR_CONTROLE=3] [SORTIE=bench/corpus_gu]
```

`make corpus-g6` exécute la recette consignée dans `docs/backlog/orchestrateur.md` :

```sh
python -m bench.generator2 --out bench/corpus_g6 --prefix GV --ext --all-holdout \
  --per-control 3 --count 160 --seed 20261008 --split holdout --jobs 2
```

puis contrôle l'empreinte (160 dossiers) :

```sh
cd bench/corpus_g6 && find holdout -name truth.json | sort | xargs sha256sum | sha256sum
# d604e7b4936af4b1473c79bd4ee557dd0702cead3d197aded56776299511b554
```

Durée : environ 3 min 30 (le générateur plafonne à 2 processus).

**Octets de remplissage TIFF.** La reproductibilité « à l'octet près » ne tient pas pour les TIFF : Pillow (LZW
via libtiff) laisse un octet de remplissage non initialisé avant le répertoire de l'image. Une régénération de
`corpus_g6` (2026-10-06) a donné les mêmes pixels mais 6 TIFF différant d'un octet, donc 4 `truth.json` (qui
citent l'empreinte de chaque fichier) et une empreinte globale différente. La vérification accepte alors
l'**empreinte des pixels** (`sha256_pixels` dans `bench/corpus_empreintes.json`, calculée par
`python scripts/corpus.py empreinte --pixels bench/corpus_g6` : l'empreinte d'octets de chaque TIFF cité est
remplacée par celle de ses pixels décodés) et le signale. Correction durable côté générateur (écrire des TIFF
déterministes) : voir `docs/backlog/outillage.md`.

**Nouveau corpus** : `make corpus GRAINE=… PREFIXE=…` affiche son empreinte ; l'ajouter à
`bench/corpus_empreintes.json` (même forme que `corpus_g6`) pour que `make corpus-verifier CORPUS=corpus_xx` et
la régénération par nom fonctionnent. Un test (`tests/outillage/test_outillage.py`) vérifie que l'empreinte de
`corpus_g6` consignée ici et dans `docs/backlog/orchestrateur.md` est la même.
