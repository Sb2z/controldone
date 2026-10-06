# Constats transverses (orchestrateur)

- **Dépôt Git lourd (609 Mo).** Les corpus de banc sont versionnés, alors qu'ils sont reproductibles à l'octet près
  par leur graine. Proposition : ne plus versionner les prochains corpus, les régénérer par `make` ; nettoyer
  l'historique seulement avec l'accord du fondateur (réécriture irréversible). À faire.
- **CI en déclenchement manuel** (`.github/workflows/ci.yml`) : activer sur push/PR demande l'accord du fondateur
  (minutes GitHub). À faire, sur décision.
- **Lecture par modèle de langage inactive** (pas de clé d'API) : c'est la réponse prévue aux mises en page vraiment
  inconnues. Sur décision du fondateur.
- **Serveur de démo** : la limitation de débit des connexions est en mémoire ; après une vingtaine de connexions
  de test, il faut redémarrer le serveur (vu pendant les captures de l'interface). Traité par le bloc sécurité.
- **Jeu vierge `corpus_g6` non versionné** (décision d'allègement du dépôt). Régénération depuis `/home/user/v2`,
  environnement actif : `python -m bench.generator2 --out bench/corpus_g6 --prefix GV --ext --all-holdout
  --per-control 3 --count 160 --seed 20261008 --split holdout --jobs 2`. Contrôle d'intégrité, depuis
  `bench/corpus_g6` : `find holdout -name truth.json | sort | xargs sha256sum | sha256sum` doit donner
  `d604e7b4936af4b1473c79bd4ee557dd0702cead3d197aded56776299511b554`. 160 dossiers, 190 erreurs dont 74 attendues
  « certain », 767 pièges. Fait.
- **Trusted Types vérifiés dans un navigateur** (Chromium, Playwright) après activation par le bloc sécurité :
  parcours fondateur et client, palette Ctrl+K, bascule de thème, filtrage en direct des dossiers, page de suivi d'un
  dépôt — 0 erreur console, 0 rapport CSP. Fait. Reste à faire : ce contrôle en CI (cf. backlog sécurité).
- **Jeu vierge `corpus_g7` non versionné.** Régénération : `python -m bench.generator2 --out bench/corpus_g7
  --prefix GU --ext --all-holdout --per-control 3 --count 160 --seed 20261009 --split holdout --jobs 2`. Empreinte
  (depuis `bench/corpus_g7`, `find holdout -name truth.json | sort | xargs sha256sum | sha256sum`) :
  `fdd372db62cae8bd862153e953c60de69a83b6cb8733b26eab8b10b33395f944`. 160 dossiers, 189 erreurs dont 74 attendues
  « certain », 739 pièges. Correctif du générateur (copie de fichier F1 dans un PDF fusionné), sans effet sur les
  corpus existants. Fait.
