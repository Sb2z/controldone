# ControlDOne v2

Service de contrôle de cohérence des documents d'import (facture commerciale, déclaration en douane,
facture du transitaire, avoirs) pour les PME françaises. Branche orpheline : réécriture en salle blanche,
sans historique commun avec l'ancien code (voir `docs/DECISIONS.md`, D-001).

- Spécification fonctionnelle (source de vérité) : `docs/SPEC.md`
- Architecture et contrats entre modules : `docs/ARCHITECTURE.md`
- Décisions structurantes : `docs/DECISIONS.md`
- Règles des agents (salle blanche) : `docs/AGENTS_RULES.md`

## Démarrage en 5 minutes (démonstration, données fictives)

Prérequis : Python 3.11, `uv` (ou `pip`), et pour l'OCR des scans `tesseract-ocr` + `tesseract-ocr-fra`.

```bash
make demo-complete          # ou : scripts/demo_complete.sh
```

La commande installe l'environnement si besoin (`.venv`, `requirements.lock`), puis :

1. `controldone demo` : rapport de démonstration dans `var/demo/report.pdf` et `var/demo/report.html` ;
2. `controldone init-demo` : base web neuve dans `var/demo_web/` (un fondateur, deux clients fictifs,
   dossiers déjà traités) ; les identifiants sont affichés et enregistrés dans
   `var/demo_web/identifiants.txt` ;
3. lance l'interface sur **http://127.0.0.1:8000/connexion** avec le worker intégré (Ctrl-C pour arrêter).

Connexion fondateur (`/admin`) : adresse et mot de passe affichés, puis le code TOTP donné par
`scripts/demo_complete.sh totp` (ou le secret ajouté dans une application d'authentification). Connexion
client (`/espace`) : l'adresse `admin@ateliers-demo.test` et son mot de passe affiché. API :
`http://127.0.0.1:8000/api/v1/openapi.json`.

Diagnostic d'un dossier : `make diagnostic DOSSIER=chemin/du/lot` (rapport dans `var/diagnostic/` ;
`OUT=…` pour changer, `SANS_LLM=1` pour ne jamais appeler le modèle).

Mise en production (préparée, rien n'est déployé) : `docs/DEPLOIEMENT.md` et `deploy/`.

## Développement

```bash
source .venv/bin/activate
make install   # installation en mode éditable (+ outils de dev)
make test      # pytest
make lint      # ruff
```

Configuration : copier `.env.example` en `.env`. Sans `ANTHROPIC_API_KEY`, seuls les extracteurs
`structure` et `deterministe` sont utilisés.

Principe : le modèle de langage lit, le code testé compare et calcule, le fondateur valide.
Le produit ne constate que des écarts factuels, documentaires et tarifaires (prix chiffrés de la grille
transmise par le client) ; il ne se prononce jamais sur un droit,
une taxe, un classement, une origine ou une valeur en douane.
