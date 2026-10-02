# ControlDOne v2

Service de contrôle de cohérence des documents d'import (facture commerciale, déclaration en douane,
facture du transitaire, avoirs) pour les PME françaises. Branche orpheline : réécriture en salle blanche,
sans historique commun avec l'ancien code (voir `docs/DECISIONS.md`, D-001).

- Spécification fonctionnelle (source de vérité) : `docs/SPEC.md`
- Architecture et contrats entre modules : `docs/ARCHITECTURE.md`
- Décisions structurantes : `docs/DECISIONS.md`
- Règles des agents (salle blanche) : `docs/AGENTS_RULES.md`

## Démarrage

```bash
source .venv/bin/activate
make install   # installation en mode éditable (+ outils de dev)
make test      # pytest
make lint      # ruff
```

Configuration : copier `.env.example` en `.env`. Sans `ANTHROPIC_API_KEY`, seuls les extracteurs
`structure` et `deterministe` sont utilisés.

Principe : le modèle de langage lit, le code testé compare et calcule, le fondateur valide.
Le produit ne constate que des écarts factuels et contractuels ; il ne se prononce jamais sur un droit,
une taxe, un classement, une origine ou une valeur en douane.
