# deploy/ — mise en production de ControlDOne (préparée, non déployée)

Guide complet, en français : **`docs/DEPLOIEMENT.md`** (hébergeur UE recommandé, VM, DNS, pare-feu, volume
chiffré, premier fondateur, Stripe, sauvegardes hors site, supervision, mise à jour, restauration, coûts).

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image `python:3.11-slim`, utilisateur non root (uid 10001), tesseract fra/eng/osd, dépendances figées (`../requirements.lock`), sans outils de compilation, HEALTHCHECK `/sante`, compatible système de fichiers en lecture seule (`/app/var` et `/backups` en volumes). |
| `Dockerfile.dockerignore` | Contexte de construction minimal (ni `.venv`, ni `var/`, ni secrets). |
| `docker-compose.yml` | Services `web`, `worker`, `scheduler`, `caddy` ; seuls 80/443 publiés. |
| `Caddyfile` | HTTPS automatique, en-têtes de sécurité, taille maximale des requêtes (520 Mo pour les dépôts, 60 Mo ailleurs). |
| `scheduler.sh` | Boucle du conteneur `scheduler` : relevé des connecteurs, planificateur des agents, purge, sauvegarde, référentiel. |
| `backup-cron.sh` | Sauvegarde chiffrée quotidienne (appelle `scripts/backup.sh`) ; `--hors-site` sur l'hôte : copie rclone vers un stockage objet UE. |
| `.env.prod.example` | Toutes les variables, documentées, **sans valeur réelle**. Copier en `.env.prod` (ignoré par git). |

En bref (sur la VM, après les étapes 3 à 6 du guide) :

```bash
cd /srv/controldone/app/deploy
cp .env.prod.example .env.prod && chmod 600 .env.prod && ln -s .env.prod .env   # puis compléter
docker compose build && docker compose up -d
docker compose run --rm --no-deps web controldone creer-fondateur --email fondateur@exemple.fr
curl -fsS https://<domaine>/sante
```

Construction locale de l'image seulement : `make docker-build` (depuis la racine du dépôt).
