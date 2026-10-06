# deploy/ — mise en production de ControlDOne (préparée, non déployée)

Guide complet, en français : **`docs/DEPLOIEMENT.md`** (hébergeur UE recommandé, VM, DNS, pare-feu, volume
chiffré, premier fondateur, Stripe, sauvegardes hors site, supervision, mise à jour, restauration, coûts).

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image `python:3.11-slim`, utilisateur non root (uid 10001), tesseract fra/eng/osd, pilote `pg8000` et `pg_dump` / `pg_restore` 16 (dépôt PGDG, clé `pgdg.asc` ; `--build-arg PG_CLIENT_MAJOR=…`, D-4101), dépendances figées (`../requirements.lock`), sans outils de compilation, HEALTHCHECK `/sante`, compatible système de fichiers en lecture seule (`/app/var` et `/backups` en volumes). |
| `Dockerfile.dockerignore` | Contexte de construction minimal (ni `.venv`, ni `var/`, ni secrets). |
| `docker-compose.yml` | Service ponctuel `migrer` (schéma, migrations après sauvegarde, chiffrement des traces ; avant tout le reste, D-4102), services `web`, `worker`, `scheduler`, `caddy` ; seuls 80/443 publiés. |
| `pgdg.asc` | Clé publique du dépôt PostgreSQL (PGDG), empreinte `B97B 0AFC AA1A 47F0 44F2 44A0 7FCC 7D46 ACCC 4CF8`. |
| `Caddyfile` | HTTPS automatique, en-têtes de sécurité, taille maximale des requêtes (520 Mo pour les dépôts, 60 Mo ailleurs). |
| `scheduler.sh` | Boucle du conteneur `scheduler` : relevé des connecteurs, notifications, planificateur des agents, purge, deux sauvegardes par jour (`SCHED_BACKUP_HHMM=0215,1415`), référentiel. |
| `backup-cron.sh` | Sauvegarde chiffrée quotidienne relue (appelle `scripts/backup.sh`), restauration d'essai hebdomadaire, codes de retour, sonde externe ; `--hors-site` sur l'hôte : fraîcheur, empreinte, copie rclone vers un stockage objet UE puis `rclone check`. Voir « Sauvegardes et restauration » ci-dessous. |
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

## Sauvegardes et restauration

Détails d'exploitation : `docs/EXPLOITATION.md` § 3 ; mise en place hors site : `docs/DEPLOIEMENT.md` § 10 et § 14 ;
décisions D-3301 à D-3306.

### Ce qui est sauvegardé, et ce qui ne l'est pas

| Élément | Dans l'archive | Remarque |
|---|---|---|
| Base SQLite (`var/controldone.db`) | oui, `base/controldone.db` | copie **en ligne** par l'API de sauvegarde de SQLite : instantané cohérent même pendant les écritures |
| Base PostgreSQL (si `CONTROLDONE_DATABASE_URL` en `postgresql+pg8000://…`) | oui, `base/controldone.dump` | `pg_dump --format=custom` sur un instantané exporté, le même que celui du manifeste (D-3501) ; `pg_dump` de la même version majeure que le serveur |
| Coffre (`var/coffre/`) | oui, `coffre/` | objets déjà chiffrés par client ; copiés tels quels |
| Traces d'envoi (`var/outbox_envoyee/`) | oui, `outbox_envoyee/` | copies des rapports et factures mis à disposition, **chiffrées au repos** (`*.enc`, clé dérivée de la clé maîtresse, D-4106) ; le contrôle approfondi vérifie que chacune se déchiffre |
| Manifeste | oui, `MANIFESTE.json` (en dernier) | taille et SHA-256 de **chaque** fichier, lignes par table, tête de la chaîne d'audit |
| `CONTROLDONE_MASTER_KEY`, `CONTROLDONE_SECRET_KEY`, `.env.prod`, `dev_master.key` | **non, jamais** | conservés **à part** : gestionnaire de secrets + copie papier sous scellé |
| `var/tmp/`, journaux, images Docker, certificats Caddy | non | recréés au démarrage ou reconstruits depuis le dépôt |

L'archive `controldone-AAAAMMJJTHHMMSSZ.tar.gz.enc` est chiffrée en entier (format `CDSAV2`, segments authentifiés,
clé dérivée de la clé maîtresse). À côté, `….tar.gz.enc.sha256` (format `sha256sum`) permet de contrôler une copie
**sans la clé**. Sans la clé maîtresse, aucune sauvegarde n'est lisible : c'est voulu, et c'est le premier risque à
couvrir. Après une rotation de clé (`CONTROLDONE_MASTER_KEY=nouvelle,ancienne`), garder l'ancienne clé dans la liste
au moins 35 jours (durée de conservation hors site), sinon les anciennes archives deviennent illisibles.

### Commandes

```bash
controldone sauvegarde sauvegarder [--destination DIR] [--verification-profonde]   # crée, relit, rotation
controldone sauvegarde verifier --dernier --destination DIR [--profond] [--age-max-h 26]
controldone sauvegarde restaurer <archive> <répertoire_vide> --controler
controldone sauvegarde restaurer <archive> <répertoire_vide> --base-cible <url_base_pg_vide> --controler   # PostgreSQL
controldone sauvegarde controler <répertoire_restauré>
controldone sauvegarde rotation --destination DIR [--recentes 4] [--jours 7] [--semaines 4]
make restauration-test                     # exercice complet sur une base fictive, hors ligne (≈ 15 s)
make restauration-test-pg                  # le même sur PostgreSQL (serveur jetable local, ≈ 25 s)
```

- `sauvegarder` relit **toujours** l'archive qu'elle vient d'écrire (déchiffrement de chaque segment, SHA-256 de
  chaque fichier comparé au manifeste). Une archive non conforme est renommée `.invalide` : elle ne compte ni
  comme sauvegarde du jour (le rattrapage la refait), ni dans la rotation.
- `--verification-profonde` / `--profond` : restauration d'essai complète dans un répertoire temporaire **du
  même volume** (il faut autant d'espace libre que les données), puis contrôle : intégrité SQLite, lignes par
  table égales au manifeste, chaîne d'audit intacte, **chaque** objet du coffre déchiffré et conforme à sa
  référence, chaque fichier référencé par la base présent. Le conteneur `scheduler` la fait chaque dimanche
  (`BACKUP_VERIFICATION_PROFONDE_JOUR`).
- Sauvegarde, purge et restauration partagent un verrou de maintenance (`<data_dir>/.verrou-maintenance`,
  D-3504) : une purge lancée à la main pendant la copie est reportée, au lieu de retirer un objet que
  l'instantané référence.
- `restaurer` n'écrit que dans un répertoire **absent ou vide** et ne remplace jamais les données en service ;
  la mise en service suit `docs/EXPLOITATION.md` § 3.2.
- `make restauration-test` : base de démonstration neuve (`init-demo`, données fictives) dans un répertoire
  temporaire, clé neuve tenue hors des données, sauvegarde, contrôles négatifs (autre clé, octet altéré, aucune
  clé dans l'archive), **effacement** de la source, restauration ailleurs, comparaison avec la source (lignes par
  table, tête de l'audit, octets du coffre), puis `controldone serve` sur les données restaurées : connexion du
  fondateur avec son second facteur (secret TOTP chiffré), `/admin`, connexion d'un client et rapport publié
  rendu en HTML et PDF depuis le coffre restauré. `var/demo_web` n'est jamais touché. Aussi exécuté par
  `pytest` (marque `lent`).

### Conservation (rotation)

- Locale (`/srv/controldone/backups`) : les **4 archives les plus récentes** (deux jours à deux sauvegardes par
  jour, `BACKUP_RECENTES`), puis la plus récente de chacun des **7 derniers jours** et de chacune des
  **4 dernières semaines** ISO (`BACKUP_JOURS`, `BACKUP_SEMAINES`), soit environ 12 archives. La rotation retire
  aussi les empreintes orphelines et les restes de plus d'un jour d'une sauvegarde interrompue.
- Hors site : `rclone copy --immutable` (rien n'est écrasé ni supprimé à distance) ; la durée est fixée par la
  règle de cycle de vie du compartiment (**35 jours** conseillés).

### Codes de retour et alertes

| Code | Signification |
|---|---|
| 0 | succès |
| 1 | création de l'archive en échec (disque plein, base illisible…) |
| 2 | configuration : clé maîtresse absente ou invalide, `pg_dump` absent, rclone ou distant absent, verrou de maintenance pris (restauration) |
| 3 | vérification en échec : archive illisible, altérée, empreinte ou manifeste non conformes |
| 4 | aucune sauvegarde assez récente (`--age-max-h`, `BACKUP_AGE_MAX_H`, défaut 14 h) |
| 5 / 6 | copie hors site en échec / copie distante incomplète ou différente (`rclone check`) |

- Chaque échec côté application émet une alerte fondateur, une par jour et par type, visible dans
  `/admin/alertes` : `sauvegarde_echec`, `sauvegarde_verification_echec`, `sauvegarde_absente`,
  `sauvegarde_hors_site_echec` (côté hôte, si `BACKUP_ALERTE_COMPOSE` est défini).
- **Notifications poussées** (D-3502, facultatives) : webhook et/ou courriel configurés dans `.env.prod`
  (`CONTROLDONE_NOTIF_*`) ; une notification par type et par jour, sans donnée client ; rien n'est envoyé sans
  configuration (`docs/EXPLOITATION.md` § 3.3).
- **Limite** : une alerte dans l'application ne se voit qu'en se connectant (sauf notifications configurées), et
  ne part pas si le conteneur `scheduler` est arrêté. Pour être prévenu par courriel, y compris quand plus rien ne tourne, définir
  `BACKUP_PING_URL` (sonde « homme mort » type Healthchecks, auto-hébergeable) : `<url>/0` après chaque succès,
  `<url>/<code>` après un échec ; la sonde (période 12 h, grâce 2 h) alerte si aucun signal n'arrive pendant 14 h. Le contrôle hors site
  sur l'hôte vérifie aussi, indépendamment du conteneur, que la dernière archive locale a moins de 14 h.

### Objectifs de reprise (RPO / RTO) — à lire honnêtement

- **RPO (perte de données maximale)** : **12 h** (D-4105). Deux sauvegardes par jour (02:15 et 14:15 UTC,
  `SCHED_BACKUP_HHMM`) ; tout ce qui a été déposé ou décidé depuis la dernière sauvegarde est perdu si le volume
  est perdu. La copie hors site part à 02:45 et 14:45 UTC (crontab hôte `45 2,14 * * *`) : en cas de perte de
  la VM **et** de son volume, la perte peut atteindre **environ 12 h 30**. Il n'y
  a ni réplication continue, ni journal WAL expédié hors machine. Si les alertes ne sont pas lues et que la
  sonde externe n'est pas configurée, une sauvegarde en panne peut passer inaperçue et le RPO devient non borné.
  Atténuation métier : les clients gardent leurs pièces d'origine et peuvent les redéposer.
- **RTO (durée d'indisponibilité)** : **objectif 4 heures ouvrées, non mesuré en conditions réelles.** Mesuré :
  sur la base de démonstration (≈ 3 Mo), restauration + contrôle complet + démarrage du web en ≈ 3 s ; sur un
  coffre de 200 Mo (poste de développement), relecture 2 s, restauration 2 s, contrôle 1 s, création 7 s, soit
  ≈ 100 Mo/s en restauration. Le temps réel est dominé par les gestes humains : créer et préparer une VM
  (`docs/DEPLOIEMENT.md` § 3 à 7, de l'ordre d'une heure), télécharger l'archive depuis le stockage objet,
  restaurer, basculer le DNS. Une seule personne (le fondateur) sait le faire et il n'y a pas d'astreinte : hors
  heures ouvrées, compter **jusqu'au jour ouvré suivant**.
- Ces chiffres valent tant que l'exercice mensuel de restauration (`docs/DEPLOIEMENT.md` § 14, sur une vraie
  archive de production téléchargée depuis le stockage objet) réussit ; noter sa durée à chaque fois pour
  remplacer l'objectif par une mesure.
