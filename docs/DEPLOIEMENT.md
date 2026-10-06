# ControlDOne v2 — Déploiement en production

Ce guide prépare la mise en ligne de ControlDOne sur une machine virtuelle hébergée dans l'Union
européenne. **Rien n'est déployé et aucun compte n'est créé** : chaque étape marquée « fondateur » est à
faire par le fondateur. Fichiers : `deploy/` (Dockerfile, docker-compose.yml, Caddyfile, scripts),
`requirements.lock`, `.github/workflows/ci.yml`. Exploitation courante : `docs/EXPLOITATION.md`.
Sécurité : `docs/SECURITY.md`.

---

## 1. Architecture cible

Une seule VM, quatre conteneurs (`deploy/docker-compose.yml`) :

| Service | Rôle | Commande |
|---|---|---|
| `caddy` | HTTPS automatique (Let's Encrypt), HTTP vers HTTPS, en-têtes de sécurité, taille maximale des requêtes. Seul service exposé (ports 80 et 443). | image `caddy:2-alpine`, `deploy/Caddyfile` |
| `web` | Interface, API `/api/v1`, webhooks Stripe. Un seul processus : le limiteur de débit et la révocation de session sont en mémoire (SECURITY.md, points ouverts). | `controldone serve --sans-worker --proxy --https --init-schema` |
| `worker` | File de tâches (traitement des lots, agents, purge, référentiel). | `python -m controldone.jobs.worker` |
| `scheduler` | Boucle façon cron (`deploy/scheduler.sh`) : relevé des connecteurs (5 min), planificateur des agents (15 min), purge de conservation et sauvegarde chiffrée (chaque jour, 02:15 UTC), référentiel (le 2 du mois). | `/app/deploy/scheduler.sh` |

Données sur l'hôte, dans un volume chiffré monté en `/srv/controldone` :

```
/srv/controldone/
├── app/        clone du dépôt (code, deploy/)
├── var/        base SQLite + coffre chiffré (monté en /app/var)          propriétaire uid 10001
├── backups/    archives chiffrées quotidiennes (monté en /backups)      propriétaire uid 10001
└── caddy/      certificats TLS (data/, config/)
```

Conteneurs applicatifs : utilisateur non root (uid 10001), système de fichiers en **lecture seule**
(`read_only`, `/tmp` en mémoire), toutes les capacités Linux retirées, `no-new-privileges`. L'image
contient tesseract (fra, eng, osd) et aucune chaîne de compilation.

---

## 2. Hébergeur recommandé

### 2.1 Recommandation : **Scaleway, région Paris (PAR-1)**

Pourquoi, pour un fondateur seul qui vend à des PME françaises :

1. **Données en France**, chez un hébergeur français (droit européen, pas de société mère hors UE) :
   l'argument se dit en une phrase au client, et il simplifie la liste des sous-traitants ultérieurs du
   contrat article 28 (voir `docs/recherche/legal_market.md`, hypothèse 8).
2. **Prix d'entrée bas, facturé à l'usage** : instance DEV1-S (2 vCPU, 2 Go) **environ 6,55 €/mois**.
   L'IPv4 publique et le stockage sont facturés en plus.
   Source : https://www.scaleway.com/en/pricing/virtual-instances/ (relevé dans
   `docs/recherche/legal_market.md` § 6, recherche du 2026-10-02).
3. Tout est au même endroit : volume bloc (chiffré par LUKS, § 5), stockage objet compatible S3 pour la
   copie hors site des sauvegardes, groupes de sécurité (pare-feu), DNS.

Capacité : 2 Go de RAM suffisent pour la démonstration et les premiers clients (un lot à la fois ;
l'OCR de scans est l'étape la plus gourmande). Passer à une instance de 4 Go dès que les lots de
plusieurs centaines de pages deviennent courants (le prix exact est à relever sur la page de tarifs ; il
n'a pas été vérifié dans la recherche).

### 2.2 Alternatives sourcées

| Hébergeur | Offre | Prix indicatif | Lieu des données | Source |
|---|---|---|---|---|
| **Scaleway** (FR) | DEV1-S, 2 vCPU, 2 Go | ≈ 6,55 €/mois (+ IPv4 et stockage) | Paris | https://www.scaleway.com/en/pricing/virtual-instances/ |
| Scaleway (FR) | STARDUST1-S, 1 vCPU, 1 Go | ≈ 0,43 €/mois | Paris | même page — **trop petit** pour l'OCR ; utile pour une préproduction |
| **OVHcloud** (FR) | VPS-1 | 6,49 € HT/mois depuis le 1er avril 2026 (4,49 € avant) | France (choisir un datacenter français à la commande) | https://blog.ovhcloud.com/evolutions-tarifaires-de-public-cloud-bare-metal-et-vps-chez-ovhcloud/ |
| OVHcloud (FR) | VPS-2 | 9,99 € HT/mois depuis le 1er avril 2026 | idem | même page |
| **Hetzner** (DE) | CAX11 (ARM) | 5,99 €/mois depuis le 15 juin 2026 (4,49 € avant) | Allemagne (Falkenstein, Nuremberg) ou Finlande (Helsinki) ; **ne pas choisir** les régions États-Unis ou Singapour ; ISO 27001 | https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/ ; https://www.hetzner.com/cloud/ |

Notes : les caractéristiques des offres OVHcloud (vCPU, RAM) ne figurent pas dans la recherche : les
vérifier avant de commander. Hetzner CAX est en ARM64 : l'image se construit sur la VM elle-même
(`docker compose build`) ; `pip install --only-binary=:all:` échoue tout de suite si une roue ARM manquait.
Clever Cloud (PaaS français) est cité dans la recherche avec une confiance faible ; il n'est pas retenu
(SQLite + coffre sur disque demandent un volume persistant).

### 2.3 Coûts mensuels indicatifs

| Poste | Montant | Statut |
|---|---|---|
| VM Scaleway DEV1-S (Paris) | ≈ 6,55 € | **sourcé** (legal_market.md § 6) |
| IPv4 publique | facturée en plus | sourcé (existence) ; montant **à relever** sur la page de tarifs |
| Volume bloc 10-20 Go (données chiffrées) | quelques euros | **non vérifié** : à relever sur scaleway.com/pricing |
| Stockage objet UE pour la copie hors site (< 10 Go) | moins d'un euro à quelques euros | **non vérifié** |
| Nom de domaine | ≈ 1 €/mois (ordre de grandeur) | **non vérifié** |
| Supervision externe (sonde HTTPS) | 0 € (offre gratuite d'un service de sonde) | **non vérifié** |
| Certificats TLS (Let's Encrypt via Caddy) | 0 € | — |
| API Anthropic (facultative) | plafonnée par client (8 €/mois par défaut, `docs/EXPLOITATION.md` § 5) | réglage du produit |
| **Total hébergement hors IA** | **de l'ordre de 10 à 15 €/mois** | estimation : seule la VM est sourcée |

---

## 3. Créer le compte et la VM (fondateur)

1. **Compte** : créer un compte Scaleway (organisation au nom de l'entreprise), activer
   l'authentification à deux facteurs, renseigner la facturation. *Action du fondateur : rien n'a été
   créé.*
2. **Clé SSH** : sur le poste du fondateur, `ssh-keygen -t ed25519 -C "controldone-prod"` ; ajouter la
   clé publique dans la console (Identifiants > Clés SSH).
3. **Instance** : Instances > Créer — région **Paris (PAR-1)**, type DEV1-S, image Debian 12 ou
   Ubuntu 24.04, IPv4 publique, la clé SSH ci-dessus. Nom : `controldone-prod`.
4. **Volume bloc** : Stockage bloc > Créer (10 à 20 Go, même zone), l'attacher à l'instance.
5. Noter l'adresse IPv4 (et IPv6).

## 4. DNS

Chez le registraire du domaine, créer :

```
app.exemple.fr.   A      <IPv4 de la VM>
app.exemple.fr.   AAAA   <IPv6 de la VM>     (si IPv6 activée)
```

Vérifier : `dig +short app.exemple.fr`. Caddy obtient le certificat au premier démarrage : le DNS doit
déjà pointer vers la VM et les ports 80/443 être ouverts. Ajouter éventuellement un enregistrement CAA
(`0 issue "letsencrypt.org"`).

## 5. Système, pare-feu, volume chiffré

Sur la VM (`ssh root@<IP>`) :

```bash
# Mises à jour automatiques de sécurité, outils
apt update && apt -y full-upgrade
apt -y install unattended-upgrades ufw cryptsetup rclone git
dpkg-reconfigure -plow unattended-upgrades

# SSH : clés seulement
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

# Pare-feu de la VM (doublé par le groupe de sécurité de l'hébergeur : mêmes règles)
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp            # mieux : ufw allow from <IP fixe du fondateur> to any port 22 proto tcp
ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
ufw enable
```

Docker publie lui-même ses ports en contournant ufw : seul `caddy` publie des ports (80, 443), c'est voulu.
`web` n'est **jamais** exposé directement. Répliquer les règles dans le **groupe de sécurité** Scaleway
(entrées : 22 depuis l'IP du fondateur, 80, 443 ; tout le reste refusé).

**Chiffrement du volume** (SECURITY.md, point ouvert 4 : la base SQLite vivante est en clair sur le
disque) :

```bash
lsblk                                     # repérer le volume bloc, ex. /dev/sdb
cryptsetup luksFormat /dev/sdb            # phrase de passe longue, rangée dans le gestionnaire de secrets
cryptsetup open /dev/sdb cd_data
mkfs.ext4 /dev/mapper/cd_data
mkdir -p /srv/controldone && mount /dev/mapper/cd_data /srv/controldone
mkdir -p /srv/controldone/{app,var,backups,caddy/data,caddy/config}
chown -R 10001:10001 /srv/controldone/var /srv/controldone/backups
chmod 700 /srv/controldone/var /srv/controldone/backups
```

Choix assumé : **déverrouillage manuel** après un redémarrage (`cryptsetup open` + `mount` +
`docker compose up -d`), plutôt qu'une clé stockée sur le disque système qui annulerait la protection.
Les redémarrages sont rares (mises à jour du noyau) ; prévoir 5 minutes.

## 6. Docker et code

```bash
# Docker Engine + plugin compose (dépôt officiel Docker)
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh && less /tmp/get-docker.sh && sh /tmp/get-docker.sh
docker compose version

# Ne démarrer Docker qu'après le montage du volume chiffré
systemctl disable docker.service docker.socket   # démarrage manuel après déverrouillage (§ 5)

# Code (dépôt privé : clé de déploiement en lecture seule, GitHub > Settings > Deploy keys)
git clone git@github.com:<organisation>/<depot>.git /srv/controldone/app
cd /srv/controldone/app/deploy
```

## 7. Secrets et premier démarrage

```bash
cd /srv/controldone/app/deploy
cp .env.prod.example .env.prod && chmod 600 .env.prod
ln -s .env.prod .env            # compose lit .env pour le domaine et les chemins
nano .env.prod                  # d'abord CONTROLDONE_DOMAIN et ACME_EMAIL (compose refuse de démarrer sans)
docker compose build            # construit controldone:2.0.0 (tesseract, dépendances figées)

# Générer les deux secrets puis les coller dans .env.prod
docker compose run --rm --no-deps web python -c "from controldone.storage import nouvelle_cle; print(nouvelle_cle())"
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
nano .env.prod                  # CONTROLDONE_MASTER_KEY, CONTROLDONE_SECRET_KEY, puis options (Stripe, IA…)

docker compose up -d
docker compose ps               # web « healthy », worker/scheduler « running », caddy « running »
curl -fsS https://app.exemple.fr/sante     # {"statut":"ok"}
```

Chaque variable est décrite dans `deploy/.env.prod.example`. **Copier `CONTROLDONE_MASTER_KEY` hors de
la machine** (gestionnaire de secrets + copie papier sous scellé) : sans elle, coffre et sauvegardes sont
illisibles.

## 8. Premier compte fondateur

En production, **ne pas** utiliser `controldone init-demo` (données fictives, identifiants de
démonstration). Utiliser :

```bash
docker compose run --rm --no-deps web controldone creer-fondateur --email fondateur@exemple.fr
```

- le mot de passe est **saisi** deux fois (12 caractères minimum, jamais en argument de commande) ;
- le secret TOTP et l'URI `otpauth://` sont affichés **une seule fois** : les ajouter tout de suite dans
  l'application d'authentification (ou générer un QR code depuis l'URI sur le poste du fondateur) ;
- la commande refuse de modifier un compte existant ;
- se connecter sur `https://app.exemple.fr/admin` (mot de passe puis code TOTP).

Créer ensuite les clients et leurs comptes depuis `/admin` (`docs/EXPLOITATION.md` § 7).

## 9. Stripe (webhook)

Procédure complète : `docs/FACTURATION.md` (« Mise en place de Stripe en mode test »). Pour ce
déploiement :

- URL du point de terminaison : **`https://app.exemple.fr/webhooks/stripe`** ;
- événements : `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`,
  `customer.subscription.updated`, `customer.subscription.deleted` ;
- mettre `STRIPE_SECRET_KEY=sk_test_…` et `STRIPE_WEBHOOK_SECRET=whsec_…` dans `.env.prod`, puis
  `docker compose up -d` (les conteneurs relisent l'environnement) ;
- passage en réel plus tard : `sk_live_…` **et** `STRIPE_LIVE_OK=1` (refusé sinon).

Le webhook passe par Caddy (limite de 60 Mo, sans objet pour Stripe) ; sa signature est vérifiée par
l'application.

## 10. Sauvegardes hors site (stockage objet UE)

Sur la machine : le conteneur `scheduler` exécute chaque jour `deploy/backup-cron.sh` → `scripts/backup.sh`
(archive **chiffrée** de la base et du coffre, rotation 7 jours / 4 semaines) dans
`/srv/controldone/backups`.

Hors de la machine (une sauvegarde sur le même disque ne protège ni d'une panne ni d'une erreur
d'hébergeur) :

1. *Fondateur* : créer un compartiment de stockage objet **dans l'UE** (Scaleway Object Storage, région
   `fr-par` ; ou Hetzner Object Storage, ou OVHcloud), privé, avec une règle de cycle de vie qui supprime
   les objets après 35 jours, et une clé d'API limitée à ce compartiment.
2. Configurer rclone sur l'hôte (`rclone config`, type S3, fournisseur Scaleway, point d'accès
   `s3.fr-par.scw.cloud`), nommer le distant `objeu`.
3. Crontab root (`crontab -e`) :

   ```
   45 2 * * * BACKUP_RCLONE_REMOTE=objeu:controldone-sauvegardes BACKUP_ALERTE_COMPOSE=/srv/controldone/app/deploy/docker-compose.yml /srv/controldone/app/deploy/backup-cron.sh --hors-site >> /var/log/controldone-backup.log 2>&1
   ```

   Le script vérifie d'abord que la dernière archive locale a moins de 26 h et que son empreinte `.sha256` est
   conforme, copie, puis contrôle la copie (`rclone check`). Un échec rend un code non nul (4, 3, 5, 6), inscrit
   une alerte dans `/admin/alertes` et, si `BACKUP_PING_URL` est défini, prévient la sonde externe
   (`deploy/README.md`, « Codes de retour et alertes »).

Les archives sont déjà chiffrées par la clé dérivée de `CONTROLDONE_MASTER_KEY` : le stockage objet ne
voit jamais de données en clair. `rclone copy --immutable` n'écrase ni ne supprime rien à distance.
Sauvegarde manuelle immédiate : `docker compose exec scheduler /app/deploy/backup-cron.sh`.

## 11. Supervision

| Quoi | Comment |
|---|---|
| Disponibilité | Sonde HTTPS externe toutes les 5 min sur **`https://app.exemple.fr/sante`** (réponse `{"statut":"ok"}`), alerte par courriel. Elle vérifie aussi le certificat. |
| Conteneurs | `docker compose ps` (web a un healthcheck `/sante` ; `restart: unless-stopped` partout). |
| Journaux | `docker compose logs -f --tail 100 web worker scheduler caddy` (JSON, sans contenu de document ; rotation 5 × 10 Mo). |
| Alertes poussées | Facultatif (D-3502) : `CONTROLDONE_NOTIF_WEBHOOK_URL` (Slack, Mattermost, ntfy, Healthchecks `/fail`) et/ou `CONTROLDONE_NOTIF_SMTP_*` (courriel) dans `.env.prod` ; une notification par type d'alerte et par jour, sans donnée client ; essai : `docker compose exec scheduler controldone alertes essai`. Rien n'est envoyé sans cette configuration. |
| Sauvegardes | Sonde « homme mort » `BACKUP_PING_URL` (alerte par courriel sans signal pendant 26 h) ; alertes `sauvegarde_*` dans `/admin/alertes` ; `docker compose logs scheduler | grep sauvegarde` doit montrer un `tache_ok` par jour ; `ls -lt /srv/controldone/backups` ; `rclone ls objeu:controldone-sauvegardes`. |
| Jobs en échec, coûts IA | `/admin` (alertes `job_mort`, `cout_ia_alerte`, `cout_ia_plafond`). |
| Disque | `df -h /srv/controldone` chaque semaine (alerte à 80 %). |
| Certificat | renouvelé automatiquement par Caddy (journal `caddy`). |

## 12. Intégration continue (GitHub Actions)

`.github/workflows/ci.yml` ne se déclenche **que manuellement** (`workflow_dispatch`), pour ne pas
consommer les minutes Actions sans accord. Lancement : GitHub > Actions > CI > *Run workflow* (options :
banc oui/non ; banc avec le modèle de langage, qui consomme le secret `ANTHROPIC_API_KEY`).

Étapes : tesseract (fra, eng, osd), dépendances figées (`requirements.lock`), `ruff check src tests`,
`pytest -q`, génération du corpus (`python -m bench.generator --split all --out bench/corpus`), exécution sur
le **holdout** (`python -m controldone.bench_run --split holdout --no-score`), porte bloquante
(`python -m bench.score --split holdout --gate`, code retour 1 si le seuil SPEC §19.7 échoue), métriques en
artefact.

**Activer sur push** (décision du fondateur) : dans `ci.yml`, remplacer le bloc `on:` par

```yaml
on:
  workflow_dispatch:
    inputs: { …inchangé… }
  push:
    branches: [main]
  pull_request:
```

et, pour que le banc tourne aussi sur push (sinon les étapes `if: ${{ inputs.banc }}` sont sautées car
`inputs` est vide), remplacer `if: ${{ inputs.banc }}` par
`if: ${{ github.event_name != 'workflow_dispatch' || inputs.banc }}`. Le banc complet peut prendre de
longues minutes : le garder sur `workflow_dispatch` et ne mettre que ruff + pytest sur push est un bon
compromis.

## 13. Mise à jour

```bash
cd /srv/controldone/app
docker compose -f deploy/docker-compose.yml exec scheduler /app/deploy/backup-cron.sh   # 1. sauvegarde
git fetch && git log --oneline HEAD..origin/main                                      # 2. relire
git pull --ff-only
sed -i 's/^CONTROLDONE_VERSION=.*/CONTROLDONE_VERSION=2.0.1/' deploy/.env.prod        # 3. nouvelle étiquette
cd deploy && docker compose build                                                      # 4. reconstruction
docker compose run --rm --no-deps scheduler controldone migrer --etat                  # 5. migrations ?
docker compose stop web worker scheduler                                               #    si en attente :
docker compose run --rm --no-deps scheduler controldone migrer                         #    sauvegarde + étapes
docker compose up -d                                                                   # 6. redémarrage
docker compose ps && curl -fsS https://app.exemple.fr/sante                            # 7. contrôle
```

- Retour arrière : remettre l'ancienne valeur de `CONTROLDONE_VERSION` (l'image précédente est conservée
  localement) puis `docker compose up -d` ; si le schéma a changé entre-temps, restaurer la sauvegarde de
  l'étape 1 (§ 14).
- Le schéma (D-3503) : `--init-schema` crée les tables d'une base neuve au démarrage de `web`. Une base
  existante évolue par des **migrations versionnées** (table `schema_version`) : tant qu'une migration est en
  attente, `web` et `worker` refusent de démarrer (code 3, « schéma de la base à migrer : … ») au lieu de
  tourner sur un schéma incomplet. `controldone migrer` fait d'abord une sauvegarde chiffrée (vérifiée) puis
  applique les étapes ; `--etat` les liste sans rien faire. `CONTROLDONE_MIGRATION_AUTO=1` migre au démarrage
  (déconseillé : pas de sauvegarde préalable).
- Dépendances (D-3609) : `requirements.lock` porte une empreinte SHA-256 par archive et l'image l'installe par
  `pip --require-hashes`. Pour monter une version : la modifier dans `requirements.lock`, puis `make lock`
  (recalcule les empreintes et la fermeture des dépendances, ainsi que `deploy/requirements-build.lock`), puis
  `make audit`, et commiter avec le changement.
- Image de base et paquets système : `docker compose build --pull` une fois par mois (correctifs de
  sécurité de Debian et de tesseract), puis `make audit-image` (Trivy) : il échoue s'il reste une vulnérabilité
  grave **corrigeable** (reconstruire), et liste les autres dans `var/audit/image.md`.

## 14. Test de restauration (chaque mois)

Sur la VM (ou mieux, sur une VM de test créée pour l'occasion avec la même clé maîtresse) :

```bash
cd /srv/controldone/app/deploy
mkdir -p /srv/controldone/restauration && chown 10001:10001 /srv/controldone/restauration
ARCHIVE=$(ls -t /srv/controldone/backups/controldone-*.tar.gz.enc | head -1)
(cd /srv/controldone/backups && sha256sum -c "$(basename "$ARCHIVE").sha256")   # sans clé
time docker compose run --rm --no-deps -v /srv/controldone/restauration:/restauration scheduler \
  controldone sauvegarde restaurer "/backups/$(basename "$ARCHIVE")" /restauration/essai --controler
rm -rf /srv/controldone/restauration/essai
```

Attendu : `OK` pour l'empreinte, puis `résultat : CONFORME` (intégrité SQLite, lignes par table égales au
manifeste, chaîne d'audit intacte, chaque objet du coffre déchiffré, chaque fichier référencé présent), code 0.
**Noter la durée** (`time`) : c'est la mesure du RTO technique (`deploy/README.md`, « RPO / RTO »). Tester aussi une archive téléchargée depuis le stockage objet (`rclone copy
objeu:controldone-sauvegardes/<archive> /srv/controldone/backups/`). Restauration réelle : arrêter
`web worker scheduler`, puis suivre `docs/EXPLOITATION.md` § 3.2 en remplaçant `var/` par
`/srv/controldone/var/` ; redémarrer avec `docker compose up -d`.

## 15. Liste de contrôle avant ouverture

- [ ] Compte hébergeur avec 2FA ; VM en région UE (Paris) ; groupe de sécurité 22 (IP fondateur), 80, 443.
- [ ] Volume LUKS monté sur `/srv/controldone` ; phrase de passe dans le gestionnaire de secrets.
- [ ] `.env.prod` en 0600 ; `CONTROLDONE_ENV=prod` ; clé maîtresse copiée hors machine.
- [ ] `https://<domaine>/sante` répond ; certificat valide ; `http://` redirige vers `https://`.
- [ ] Fondateur créé par `creer-fondateur`, connexion TOTP vérifiée ; aucune base de démonstration en prod.
- [ ] Webhook Stripe en mode test reçu (`stripe trigger checkout.session.completed`).
- [ ] Une sauvegarde locale + sa copie hors site ; un test de restauration réussi (§ 14, durée notée).
- [ ] Sonde « homme mort » `BACKUP_PING_URL` active pour la sauvegarde et pour la copie hors site.
- [ ] Sonde externe active sur `/sante`.
- [ ] Mentions légales du site : hébergeur (nom, adresse, téléphone) — `docs/recherche/legal_market.md` § 4.
- [ ] Registre RGPD et liste des sous-traitants à jour (hébergeur, stockage objet, Stripe, Anthropic si activé).

---

## Annexe — ce qui a été vérifié lors de la préparation (2026-10-02)

- Image construite localement (`docker build`) : utilisateur `controldone` (uid 10001), tesseract avec
  `eng`, `fra`, `osd`, aucun compilateur, `controldone --help` liste `creer-fondateur`, `config/` et `ref/`
  trouvés. Dans le bac à sable de préparation, le mandataire réseau imposait d'ajouter son certificat pour
  `apt` (variante de test hors dépôt) ; `deploy/Dockerfile` lui-même n'en dépend pas.
- `docker compose config` valide ; `caddy validate` valide le Caddyfile.
- La pile n'a **pas** été démarrée (aucun `docker compose up`) : premier démarrage réel au § 7.
- `deploy/backup-cron.sh` (sauvegarde + rotation), restauration et `verifier_chaine` testés sur une base
  de développement ; `deploy/scheduler.sh` exécuté quelques secondes (relevé, planificateur, purge,
  sauvegarde, référentiel : `tache_ok`, arrêt propre sur SIGTERM).
