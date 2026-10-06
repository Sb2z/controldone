# Outillage du dépôt (bloc O)

- **Vérifications avant enregistrement** (D-3901). `.pre-commit-config.yaml`, crochets tous locaux (hors ligne) :
  ruff, espaces en fin de ligne, fichiers > 2 Mo (corpus exclus), clés privées et jetons d'API, syntaxe JSON/YAML,
  pas de `print(` dans les paquets cœur. `make hooks` installe le crochet (choix de chaque développeur),
  `make pre-commit` vérifie tout le dépôt, la CI aussi. Fait.
- **`ruff format` non appliqué** : 301 fichiers sur 363 seraient reformatés. Le reformatage massif rendrait les
  fusions des blocs en cours pénibles et l'historique illisible ; donc pas de vérification de format. Proposition :
  un seul commit de reformatage, entre deux lots, puis activer `ruff format --check` dans le crochet. À faire, sur
  décision.
- **`print(` dans les commandes** : `cli.py`, `storage/sauvegarde.py`, `auth/cli_securite.py`, `bench_run.py`,
  `ingest/demo.py`, `agents/planificateur.py`, `connecteurs/releve.py`, `services/exercice_restauration.py`
  écrivent sur la sortie standard (63 appels) : c'est leur rôle de commande. Le crochet ne vise que les paquets
  cœur (contrôles, normalisation, extraction, modèle, web, rapport, ingestion hors démo), où il n'y en a aucun.
  Fait (périmètre volontairement restreint).
- **Couverture mesurée** (D-3902). `make couverture` : base de référence dans `docs/QUALITE.md` (84,6 %, branches
  76,2 %). Pas encore de seuil bloquant (`COUV_MIN`) : à fixer après une ou deux mesures, quand les blocs en cours
  auront fini de modifier `web/securite.py` et `storage/securite.py` (mesures instables pendant leurs travaux).
  À faire.
- **Modules critiques encore peu couverts** : `storage/securite.py`, `web/securite.py`, `storage/scope.py`
  (cloisonnement), `auth/revocation.py`, `auth/jetons.py` — en cours de modification par les blocs sécurité et
  stockage : tests à écrire par ces blocs (voir `docs/QUALITE.md` § 3). À faire.
- **Tests de propriétés** (D-3903). `tests/proprietes/` (38 propriétés, Hypothesis) : montants FR/EN/DE/CH/IN
  aller-retour, signes et devises, saisie, tolérances (symétrie, monotonie, Decimal), TVA FR et SIREN, MRN et
  confusions OCR, dates multilingues, redirection interne, paramètres de liste. Aucun défaut trouvé en profil
  `intensif` (2 000 exemples par propriété). Fait.
- **Ambiguïté connue de `format_nombre`** : `format_nombre(Decimal("1.234"))` donne « 1,234 », relu 1 234 sans
  indication du séparateur décimal (comportement documenté de la lecture, D-2006). Sans effet aujourd'hui (les
  textes formatés ne sont pas relus) ; la propriété d'aller-retour est donc testée avec `separateur_decimal=","`.
  Rien à faire, à garder en tête.
- **Corpus non versionnés** (D-3904). `make corpus-g6` / `make corpus GRAINE=… PREFIXE=…`, recettes et empreintes
  dans `bench/corpus_empreintes.json`, `.gitignore` sur `bench/corpus_*/` (g3, g4, g5 restent suivis). Fait.
- **Générateur : TIFF non déterministes à l'octet.** Une régénération de `corpus_g6` donne les mêmes pixels mais
  6 TIFF différant d'un octet (remplissage non initialisé de Pillow/libtiff en LZW, `bench/generator2/degrade.py`),
  donc 4 `truth.json` et l'empreinte globale différents. Contourné : empreinte des pixels en secours
  (`sha256_pixels`). Proposition au bloc banc : écrire les TIFF de façon déterministe (par ex. réécrire l'octet de
  remplissage, ou une compression sans libtiff), puis recalculer les empreintes des prochains corpus. À faire.
- **Historique Git lourd** (609 Mo) : purge des corpus de l'historique seulement avec l'accord du fondateur
  (réécriture irréversible). À faire, sur décision.
