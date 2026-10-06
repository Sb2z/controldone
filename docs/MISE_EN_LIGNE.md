# ControlDOne — Mise en ligne pas à pas (procédure du fondateur)

Décision 9A (D-4000) : **tu choisis l'hébergeur et tu fais la mise en ligne toi-même**. Ce document te guide,
commande par commande. Rien n'a été acheté, aucun compte n'a été créé et rien n'a été déployé pendant sa
préparation.

- Référence technique détaillée : `docs/DEPLOIEMENT.md`. Exploitation courante : `docs/EXPLOITATION.md`.
  Sauvegardes : `deploy/README.md`. Sécurité : `docs/SECURITY.md`.
- Conventions de ce document :
  - `app.exemple.fr` est **ton** sous-domaine applicatif ;
  - `<IP>` est l'adresse IPv4 de ta machine ;
  - `cdadmin` est le compte d'administration que tu vas créer ;
  - une ligne qui commence par `$` se tape **sur ton ordinateur** ; une ligne qui commence par `#` se tape **sur
    le serveur, en root** (après `sudo -i`) ;
  - les blocs sans préfixe se tapent sur le serveur, en root.
- Durée totale : une demi-journée la première fois. Ne pas compter la propagation DNS ni la validation du
  compte Stripe.
- Prix : tous **hors taxes**, relevés le **6 octobre 2026** sur les pages officielles citées. Un chiffre qui n'a
  pas pu être vérifié est marqué **non vérifié**. Les prix changent : les relire au moment de commander.

---

## Sommaire

1. Choisir l'hébergeur
2. Nom de domaine et DNS
3. Préparer le serveur
4. Installer l'application
5. Stripe en réel, pages juridiques, sous-traitants
6. Ouverture, retour arrière, routine mensuelle

Annexe : sources consultées.

---

## 1. Choisir l'hébergeur

### 1.1 Ce dont l'application a besoin

- **Une machine virtuelle Linux** avec Docker (4 conteneurs : `migrer` ponctuel, `web`, `worker`, `scheduler`,
  plus `caddy`).
  - 2 vCPU et 4 Go de RAM pour démarrer : l'OCR prend environ 400 Mo par page traitée en parallèle
    (`CONTROLDONE_PAGES_PARALLELE=2`).
  - 8 Go si les lots de plusieurs centaines de pages scannées deviennent courants.
- **Un disque de données chiffré**, pour le point RS-21 : la base SQLite vivante est en clair (le coffre et les
  sauvegardes sont déjà chiffrés par l'application). On le chiffre nous-mêmes avec LUKS (§ 3.6), quel que soit
  l'hébergeur. Il faut donc un **volume bloc séparé** (le plus simple) ou, à défaut, un fichier conteneur LUKS
  sur le disque principal.
- **Un stockage objet compatible S3**, dans l'UE ou en Suisse, pour la copie hors site quotidienne des
  sauvegardes (`rclone`, § 4.9).
- PostgreSQL géré : **pas nécessaire en v1**. SQLite sur le volume chiffré suffit pour un seul serveur. La
  colonne du tableau ci-dessous sert seulement à l'avenir.

### 1.2 Comparatif (relevé le 2026-10-06)

| | **Scaleway** (France) | **OVHcloud** (France) | **Hetzner** (Allemagne) | **Infomaniak** (Suisse) |
|---|---|---|---|---|
| Lieu des données | Paris (zone PAR-1, choisie à la création) | France si un datacenter français est choisi à la commande ; VPS aussi proposés en Asie-Pacifique et ailleurs | Allemagne (Falkenstein, Nuremberg) ou Finlande (Helsinki). **Éviter** les régions États-Unis et Singapour | Suisse uniquement (Genève, canton de Vaud) |
| Contrat de sous-traitance RGPD (DPA) | Oui : téléchargeable dans la console (Settings > Organization contracts) ou sur la page Contracts [S4] | Annexe « traitement de données » intégrée aux conditions et applicable à tous les clients d'après une source secondaire [O4]. **À confirmer** dans l'espace client | Oui : à conclure en ligne dans le compte client, `accounts.hetzner.com/account/dpa` [H3] | Oui : à générer et signer dans le Manager [I3] |
| Chiffrement du disque | Volumes bloc : LUKS par nous (§ 3.6). L'hébergeur propose un chiffrement au repos pour ses bases gérées [S6] | VPS : LUKS par nous (fichier conteneur si pas de disque additionnel). Disque additionnel **non vérifié** | « Vous êtes responsable du chiffrement » (doc Hetzner) [H3] : LUKS par nous | Block storage Ceph « chiffré (3 réplicats, LUKS) » côté hébergeur [I1]. LUKS par nous en plus, recommandé |
| PostgreSQL géré | Oui. DB-DEV-S (2 vCPU, 2 Go) ≈ **11,47 €/mois** + stockage ; chiffrement au repos activable [S3][S6] | Oui (page produit Public Cloud PostgreSQL) ; prix **non vérifié** [O3] | Aucune offre trouvée sur les pages consultées | « Database Service » listé dans les tarifs Public Cloud ; moteurs et prix **non vérifiés** [I2] |
| Instantanés et sauvegardes | Instantané de volume bloc ≈ 0,036 €/Go/mois (0,000049 €/Go/h) [S2] | VPS : sauvegarde quotidienne (24 h) incluse ; snapshots dès 0,30 € HT/mois ; sauvegarde Premium sur 7 jours dès 1,10 € HT/mois [O1] | Oui (snapshots, sauvegardes) ; prix **non vérifiés** | Un snapshot inclus gratuitement (VPS Cloud) [I4] ; Public Cloud : snapshots facturés au Go, prix **non vérifié** |
| Stockage objet (cible rclone) | Object Storage fr-par : multi-AZ ≈ 0,016 €/Go/mois, une zone ≈ 0,008 €/Go/mois ; 75 Go de sortie gratuits par mois [S2] | Oui ; prix **non vérifié** | Object Storage FSN1, NBG1, HEL1, verrouillage d'objets ; forfait de base avec 1 To inclus, montant **non lisible** sur la page (rendu dynamique) [H4] | Object Storage Swift compatible S3, objets chiffrés ; prix **non vérifié** [I1] |
| VM 2 vCPU / 4 Go | DEV1-M (3 vCPU, 4 Go) ≈ **14,74 €/mois** ; PLAY2-NANO (2 vCPU, 4 Go) ≈ **20,10 €/mois** ; BASIC3-X2C-4G ≈ **28,79 €/mois** [S1] | VPS-1 (2 vCores, 4 Go, 40 Go NVMe) « à partir de **3,81 € HT/mois** » (gamme VPS 2027, prix d'appel lié à un engagement de 12 mois d'après le lien de commande) [O1] ; sans engagement, l'ancienne gamme VPS-1 était passée à 6,49 € au 1er avril 2026 [O2] | CX23 (2 vCPU, 4 Go, 40 Go) **5,49 €/mois** ; CAX11 (ARM, 2 vCPU, 4 Go) **5,99 €/mois**, tarifs du 15 juin 2026 [H1][H2]. IPv4 incluse ou non : **non vérifié**. La page affichait « not available » le jour du relevé | Public Cloud : exemple affiché 4 CPU / 8 Go / 50 Go à **CHF 16.10/mois** [I1] ; VPS Cloud « dès CHF 38.41/mois » [I4]. 2 vCPU / 4 Go : prix **non vérifié** |
| VM 2 vCPU / 8 Go | BASIC3-X2C-8G ≈ **43,23 €/mois** ; DEV1-L (4 vCPU, 8 Go) ≈ **31,27 €/mois** ; POP2-2C-8G ≈ 53,65 €/mois [S1] | VPS-2 (4 vCores, 8 Go, 75 Go) « à partir de **7,21 € HT/mois** » [O1] ; 9,99 € sans engagement depuis avril 2026 [O2] | CX33 (4 vCPU, 8 Go, 80 Go) **8,49 €/mois** ; CAX21 (ARM, 4 vCPU, 8 Go) **10,49 €/mois** [H1][H2] | voir ci-dessus (4 CPU / 8 Go : CHF 16.10/mois) |
| Adresse IPv4 publique | **En plus** (« attached public IPv4 addresses are excluded » [S1]). Montant **non confirmé** : la page réseau indique 0,005 €/h pour une « additional IP address » [S5], soit ≈ 3,65 €/mois | 1 IPv4 incluse dans le VPS ; IP additionnelle 2,00 €/mois depuis avril 2026 [O2] | Facturée séparément (« Primary IPs ») ; montant **non vérifié** [H5] | **non vérifié** |

Notes de lecture :

- Scaleway indique « Prices before tax », la sortie réseau et l'IPv6 étant incluses [S1]. Les montants mensuels
  sont des estimations de Scaleway (prix horaire × heures du mois).
- Hetzner CAX est en **ARM64**. L'image se construit sur la machine (`docker compose build`) et
  `pip --only-binary` échoue tout de suite s'il manque une roue ARM. Pour éviter toute surprise, préférer la
  série x86 (CX).
- Pour OVHcloud, les deux chiffres ne se contredisent pas :
  - 3,81 € HT est un prix d'appel de la gamme « VPS 2027 » (page produit) ;
  - 6,49 € est le prix mensuel sans engagement de l'ancienne gamme VPS-1 (billet officiel de hausse des prix).

  Relire le prix exact dans le configurateur avant de commander.

### 1.3 Recommandation : **Scaleway, région Paris (PAR-1)**

Pour démarrer, la machine **DEV1-M** (3 vCPU, 4 Go, ≈ 14,74 €/mois) avec :

- un volume bloc de 20 Go (5K IOPS, ≈ 0,095 €/Go/mois, soit ≈ 1,90 €/mois) ;
- une IPv4 (≈ 3 à 4 €/mois, **montant à relire**) ;
- un compartiment Object Storage `fr-par` (quelques centimes pour moins de 10 Go).

**Ordre de grandeur : 20 à 25 € HT/mois**, hors IA et hors domaine. Si un engagement de disponibilité compte
plus que le prix, passer en BASIC3-X2C-4G (gamme « General Purpose »). Monter en 8 Go
(BASIC3-X2C-8G ou DEV1-L) quand l'OCR sature (voir § 6.3).

Pourquoi ce choix, pour des clients en France et en Suisse :

1. **Données en France, chez une société française.** Pour un client français, c'est l'argument le plus simple.
   Pour un client suisse, la France (UE) figure dans la liste des États à protection adéquate du droit suisse : le
   transfert vers Paris n'exige pas de garanties supplémentaires. L'inverse vaut aussi : la Suisse bénéficie
   d'une décision d'adéquation de l'UE.
2. **Tout est dans une seule console** : VM, volume bloc, pare-feu (groupes de sécurité), stockage objet S3
   pour rclone, PostgreSQL géré si un jour nécessaire. Un seul contrat et un seul DPA, téléchargeable
   immédiatement [S4]. La liste des sous-traitants à déclarer reste courte (§ 5.3).
3. **Facturation à l'heure, sans engagement** : on peut créer une machine d'essai, la détruire, ou en créer une
   le temps d'un exercice de restauration.
4. Cohérent avec `docs/DEPLOIEMENT.md` et les exemples de `deploy/` (point d'accès `s3.fr-par.scw.cloud`).

Alternatives raisonnables :

- **Infomaniak (Suisse)** : si tes premiers clients sont surtout suisses et demandent des données en Suisse.
  - Avantages : disque chiffré par l'hébergeur, interlocuteur à Genève, CHF 300 de crédit d'essai sur 3 mois
    [I1].
  - Inconvénients : facturation en CHF, console OpenStack un peu plus technique.
- **Hetzner** : le moins cher sur le papier (CX23 à 5,49 €/mois), mais en Allemagne. IPv4 et disponibilité du
  modèle à vérifier le jour de la commande.
- **OVHcloud VPS** : très bon prix (engagement 12 mois), français. Mais un VPS se prête moins bien à un volume
  chiffré séparé : utiliser alors la variante « fichier conteneur » du § 3.6.

La suite du document suit Scaleway. Les gestes sont les mêmes ailleurs ; seuls les noms de menus changent.

---

## 2. Nom de domaine et DNS

### 2.1 Choisir un registraire

- Prendre un registraire **européen**, avec double authentification et DNSSEC, par exemple :
  - Gandi (France) ;
  - OVHcloud (France) ;
  - Infomaniak (Suisse) ;
  - Scaleway Domains (France).
- Prix des domaines : **non vérifiés**, de l'ordre de quelques euros à quelques dizaines d'euros par an selon
  l'extension.
- Extension :
  - `.fr` pour une clientèle française ;
  - `.ch` si la clientèle suisse domine ;
  - `.com` en complément pour protéger la marque.
- Activer, en plus de la double authentification sur le compte du registraire :
  - le **verrouillage du transfert** ;
  - le **renouvellement automatique** (un domaine expiré coupe l'application et les certificats).

### 2.2 Enregistrements à créer (zone DNS)

L'application vit sur un sous-domaine, par exemple `app.exemple.fr`. Le site vitrine (`site/`) vit sur
`www.exemple.fr` ou `exemple.fr`, hébergé à part (voir `site/README.md`).

```
app.exemple.fr.   300  A      <IPv4 de la VM>
app.exemple.fr.   300  AAAA   <IPv6 de la VM>          (si la VM a une IPv6 ; Scaleway en fournit une)
exemple.fr.       3600 CAA    0 issue "letsencrypt.org"
exemple.fr.       3600 CAA    0 issue "sectigo.com"    (ZeroSSL, autorité de secours utilisée par Caddy)
exemple.fr.       3600 CAA    0 iodef "mailto:<ton adresse>"
```

Caddy obtient son certificat de Let's Encrypt et bascule sur ZeroSSL en cas d'échec : le CAA doit autoriser les
deux. Si tu ne veux autoriser que Let's Encrypt, ne mets que la première ligne CAA.

**Courriel : pas nécessaire en v1.** Les alertes partent sur ton téléphone par ntfy (§ 4.10). Si le domaine
n'envoie aucun courriel, publie ces trois enregistrements : personne ne pourra alors envoyer de faux courriels à
ton nom.

```
exemple.fr.          3600 MX   0 .                    (« null MX » : le domaine ne reçoit pas de courriel)
exemple.fr.          3600 TXT  "v=spf1 -all"
_dmarc.exemple.fr.   3600 TXT  "v=DMARC1; p=reject"
```

Si tu veux plus tard une adresse de contact sur ce domaine (pages juridiques, `ACME_EMAIL`), remplace ces trois
enregistrements par ceux de ton fournisseur de messagerie. En attendant, `ACME_EMAIL` peut être une adresse
existante.

Vérifier depuis ton ordinateur (`dig` sous macOS et Linux ; sous Windows, `nslookup app.exemple.fr`) :

```
$ dig +short app.exemple.fr A
$ dig +short app.exemple.fr AAAA
$ dig +short exemple.fr CAA
```

Le DNS doit répondre l'IP de la VM **avant** le premier démarrage de Caddy (§ 4.5).

---

## 3. Préparer le serveur

### 3.1 Compte hébergeur

1. Créer le compte Scaleway au nom de l'entreprise. **Activer la double authentification** et renseigner la
   facturation.
2. Télécharger le DPA (Settings > Organization contracts) et le ranger avec tes contrats. Il te sert pour ton
   registre RGPD (§ 5.3).
3. Optionnel mais conseillé : une **alerte de facturation** (budget mensuel) dans la console.

### 3.2 Clé SSH (sur ton ordinateur)

```
$ ssh-keygen -t ed25519 -C "controldone-prod"
```

- Accepter l'emplacement proposé (`~/.ssh/id_ed25519`) et choisir une phrase de passe.
- La commande fonctionne aussi sous Windows 10 et 11 (PowerShell).
- Copier le contenu de `~/.ssh/id_ed25519.pub` (la clé **publique**) dans la console : Settings > SSH keys >
  Add.
- La clé **privée** ne quitte jamais ton ordinateur. En garder une copie dans ton gestionnaire de mots de passe.

### 3.3 Créer la VM, le volume et le pare-feu

1. **Groupe de sécurité** (Instances > Security groups > Create) :
   - politique entrante par défaut : **Drop** ; sortante : **Accept** ;
   - règles entrantes **Accept** :
     - TCP 22, de préférence depuis **ton IP fixe seulement** ;
     - TCP 80 ;
     - TCP 443 ;
     - UDP 443.
2. **Instance** (Instances > Create instance) :
   - zone **PAR-1** ;
   - type **DEV1-M** (ou BASIC3-X2C-4G) ;
   - image **Debian 13** (ou Debian 12, ou Ubuntu 24.04 LTS) ;
   - IPv4 publique et IPv6 ;
   - ta clé SSH et le groupe de sécurité ci-dessus ;
   - nom : `controldone-prod`.
3. **Volume bloc** (Block Storage > Create volume) :
   - 20 Go, 5K IOPS, **même zone PAR-1** ;
   - nom : `controldone-donnees` ;
   - l'attacher à l'instance.
4. Noter l'**IPv4** et l'**IPv6**, puis créer les enregistrements DNS du § 2.2.

### 3.4 Premier accès, compte d'administration sans root

```
$ ssh root@<IP>
```

Selon l'image, l'utilisateur initial peut être `root`, `debian` ou `ubuntu` : la console de l'hébergeur
l'indique. Dans ce cas, se connecter avec ce nom puis taper `sudo -i`.

```
# adduser cdadmin                                  # choisir un mot de passe (sert à sudo)
# usermod -aG sudo cdadmin
# mkdir -p /home/cdadmin/.ssh && cp ~/.ssh/authorized_keys /home/cdadmin/.ssh/
# chown -R cdadmin:cdadmin /home/cdadmin/.ssh && chmod 700 /home/cdadmin/.ssh && chmod 600 /home/cdadmin/.ssh/authorized_keys
```

Dans un **second terminal**, sans fermer le premier, vérifier que la connexion marche :

```
$ ssh cdadmin@<IP>
$ sudo -i            # doit demander le mot de passe de cdadmin puis donner un shell root
```

Ensuite seulement, fermer l'accès root et les mots de passe SSH :

```
# cat > /etc/ssh/sshd_config.d/00-controldone.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
# sshd -t && systemctl reload ssh
```

Le fichier commence par `00-` parce que sshd retient la **première** valeur lue. Certaines images contiennent un
`50-cloud-init.conf` qui réactive les mots de passe : le nôtre est lu avant. Revérifier `ssh cdadmin@<IP>` dans
un nouveau terminal avant de fermer l'ancien.

À partir d'ici, toujours se connecter en `ssh cdadmin@<IP>` puis `sudo -i`.

### 3.5 Mises à jour automatiques et pare-feu de la machine

```
# apt update && apt -y full-upgrade
# apt -y install unattended-upgrades apt-listchanges ufw cryptsetup rclone git curl ca-certificates
# dpkg-reconfigure -plow unattended-upgrades       # répondre « Oui »
```

Les correctifs de sécurité de Debian s'installent alors seuls, chaque jour.

**Ne pas activer le redémarrage automatique** (`Unattended-Upgrade::Automatic-Reboot` reste `false`, la valeur
par défaut). Après un redémarrage, le volume chiffré attend ta phrase de passe (§ 3.6) : un redémarrage
automatique la nuit couperait le service jusqu'à ton intervention. Quand `/var/run/reboot-required` existe,
planifie toi-même le redémarrage (§ 6.3).

Pare-feu de la machine, en doublure du groupe de sécurité :

```
# ufw default deny incoming && ufw default allow outgoing
# ufw allow 22/tcp            # mieux : ufw allow from <ton IP fixe> to any port 22 proto tcp
# ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
# ufw enable                  # répondre « y » ; la session SSH en cours reste ouverte
# ufw status verbose
```

Docker ouvre lui-même les ports qu'il publie, sans passer par ufw. Seul `caddy` publie des ports (80 et 443) :
c'est voulu, et c'est pourquoi le groupe de sécurité de l'hébergeur compte autant que ufw.

### 3.6 Volume chiffré LUKS pour les données (RS-21)

Repérer le volume bloc : le disque de 20 Go **sans partition**, souvent `/dev/sdb` ou `/dev/vdb`.

```
# lsblk -o NAME,SIZE,TYPE,MOUNTPOINT
```

**Attention** : la commande suivante efface le disque désigné. Vérifier deux fois qu'il s'agit bien du volume
vide de 20 Go, et pas du disque système.

```
# cryptsetup luksFormat --type luks2 /dev/sdb       # taper YES puis une phrase de passe longue (5 mots ou plus)
# cryptsetup open /dev/sdb cd_data
# mkfs.ext4 -L controldone /dev/mapper/cd_data
# mkdir -p /srv/controldone && mount /dev/mapper/cd_data /srv/controldone
# mkdir -p /srv/controldone/{app,var,backups,caddy/data,caddy/config}
# chown -R 10001:10001 /srv/controldone/var /srv/controldone/backups
# chmod 700 /srv/controldone/var /srv/controldone/backups
# cryptsetup luksHeaderBackup /dev/sdb --header-backup-file /root/luks-entete-controldone.img
```

Ranger dans ton gestionnaire de mots de passe :

- la **phrase de passe LUKS** ;
- une copie de l'**en-tête LUKS** (`/root/luks-entete-controldone.img`, à rapatrier par
  `scp cdadmin@<IP>:...` après l'avoir copié dans `/home/cdadmin` et rendu lisible) ;
- une copie papier sous scellé de la phrase de passe.

Sans phrase de passe, les données sont perdues. C'est voulu.

**Variante sans volume séparé** (VPS OVHcloud, par exemple) : un fichier conteneur sur le disque principal, avec
le même résultat.

```
# fallocate -l 30G /srv/controldone.luks
# cryptsetup luksFormat --type luks2 /srv/controldone.luks
# cryptsetup open /srv/controldone.luks cd_data
#   … puis la suite comme ci-dessus à partir de mkfs.ext4
```

**Déverrouillage après chaque redémarrage**, une procédure de 5 minutes à garder sous la main :

```
$ ssh cdadmin@<IP>
$ sudo -i
# cryptsetup open /dev/sdb cd_data          # (ou /srv/controldone.luks) ; phrase de passe
# mount /dev/mapper/cd_data /srv/controldone
# systemctl start docker                    # les conteneurs « unless-stopped » repartent seuls
# cd /srv/controldone/app/deploy && docker compose ps
```

Le service web vérifie au démarrage que la base est bien sur un volume chiffré (D-3605). Si ce n'est pas le cas,
il émet l'alerte « Volume de la base non chiffré » dans `/admin/alertes`.

### 3.7 Installer Docker (dépôt officiel Docker, Debian)

```
# install -m 0755 -d /etc/apt/keyrings
# curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
# chmod a+r /etc/apt/keyrings/docker.asc
# echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
# apt update && apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# docker compose version
```

Sous Ubuntu, remplacer `debian` par `ubuntu` dans les deux URL.

Docker ne doit démarrer **qu'après** le montage du volume chiffré. Sinon, il recréerait des répertoires vides à
la place de tes données. On désactive donc son démarrage automatique :

```
# systemctl disable docker.service docker.socket
```

Les mises à jour automatiques ne couvrent pas le dépôt Docker : on le met à jour chaque mois (§ 6.3).

N'ajoute pas `cdadmin` au groupe `docker` : ce groupe équivaut à root. On passe par `sudo -i`.

---

## 4. Installer l'application

### 4.1 Récupérer le code

Le dépôt est privé : on crée une **clé de déploiement en lecture seule** propre au serveur.

```
# ssh-keygen -t ed25519 -f /root/.ssh/controldone_deploy -N "" -C "controldone-prod-deploy"
# cat /root/.ssh/controldone_deploy.pub
```

Sur GitHub, ouvrir le dépôt, puis Settings > Deploy keys > Add deploy key. Coller la clé, **sans** cocher « Allow
write access ».

```
# cat >> /root/.ssh/config <<'EOF'
Host github.com
  IdentityFile /root/.ssh/controldone_deploy
  IdentitiesOnly yes
EOF
# git clone git@github.com:<compte>/<depot>.git /srv/controldone/app
# cd /srv/controldone/app && git log -1 --oneline
```

### 4.2 Créer `.env.prod`

```
# cd /srv/controldone/app/deploy
# cp .env.prod.example .env.prod && chmod 600 .env.prod
# ln -s .env.prod .env
# nano .env.prod
```

Le lien `.env` sert à `docker compose` pour remplacer le domaine, les chemins et la version dans
`docker-compose.yml`.

Le fichier modèle (`deploy/.env.prod.example`) commente chaque variable. Voici ce qu'il faut remplir, section par
section.

**Section 1 — Docker compose**

| Variable | Valeur | Explication |
|---|---|---|
| `CONTROLDONE_DOMAIN` | `app.exemple.fr` | Domaine servi par Caddy. L'application n'accepte que cet hôte, et l'utilise pour les liens de paiement Stripe. **Obligatoire** : compose refuse de démarrer sans. |
| `ACME_EMAIL` | ton adresse | Contact de Let's Encrypt (avis d'expiration). **Obligatoire.** |
| `CONTROLDONE_HOST_VAR`, `_BACKUPS`, `_CADDY` | laisser `/srv/controldone/...` | Répertoires sur le volume chiffré. |
| `CONTROLDONE_VERSION` | `2.0.0` | Étiquette de l'image. À changer à chaque mise à jour pour pouvoir revenir en arrière (§ 6.2). |
| `SCHED_BACKUP_HHMM` | laisser la valeur du modèle (`0215,1415`) | Heures UTC des deux sauvegardes quotidiennes (RPO 12 h). |
| `CONTROLDONE_VOLUME_CHIFFRE` | laisser commenté | Utile seulement si le disque est chiffré par l'hébergeur sans LUKS visible. Ici, on a LUKS. |
| `BACKUP_PING_URL` | facultatif | Sonde « homme mort » (type Healthchecks). Elle t'alerte si les sauvegardes s'arrêtent complètement. Voir § 4.10. |

**Section 2 — Plateforme (obligatoire)**

| Variable | Valeur | Explication |
|---|---|---|
| `CONTROLDONE_ENV` | `prod` | Ne jamais mettre `dev` en production. En `prod`, l'application refuse de démarrer sans les deux clés ci-dessous. |
| `CONTROLDONE_MASTER_KEY` | clé générée (ci-dessous) | Clé maîtresse : elle chiffre le coffre, les sauvegardes et les secrets TOTP. **Sans elle, rien n'est lisible.** |
| `CONTROLDONE_SECRET_KEY` | secret généré (ci-dessous) | Signature des sessions et du CSRF (48 caractères ou plus). |
| `CONTROLDONE_LOG_LEVEL` | `INFO` | |

Générer les deux secrets **sur le serveur** :

```
# python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"   # -> CONTROLDONE_MASTER_KEY
# python3 -c "import secrets; print(secrets.token_urlsafe(48))"                               # -> CONTROLDONE_SECRET_KEY
```

La première commande produit exactement le format d'une clé Fernet, celui de `nouvelle_cle()`. Une fois
l'image construite, la commande officielle donne le même format :
`docker compose run --rm --no-deps web python -c "from controldone.storage import nouvelle_cle; print(nouvelle_cle())"`.

**Copier immédiatement `CONTROLDONE_MASTER_KEY` hors de la machine** : gestionnaire de mots de passe, plus une
copie papier sous scellé. Les sauvegardes ne la contiennent jamais.

**Sections 3 et 9 — File de tâches et divers** : garder les valeurs du modèle, en particulier
`CONTROLDONE_LOT_DUREE_MAX_S=1800`, `CONTROLDONE_TMP_DIR=/app/var/tmp` et `CONTROLDONE_PAGES_PARALLELE=2`.
Passer ce dernier à 3 ou 4 seulement avec 8 Go de RAM.

**Section 4 — Lecture par Claude** (décision 1A : activée, avec plafond)

| Variable | Valeur | Explication |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-…` | Clé créée dans la console Anthropic (API Keys). **Elle ne va qu'ici**, jamais dans un message, un ticket ou Git. Sans cette clé, seules les lectures structurée et déterministe tournent. |
| `CONTROLDONE_LLM_MODEL` | laisser la valeur du modèle | |
| `CONTROLDONE_LLM_PLAFOND_DOSSIER_EUR` | `0.50` | Plafond par lot traité. |
| `CONTROLDONE_LLM_PLAFOND_CLIENT_MENSUEL_EUR` | `8.00` | Plafond mensuel par défaut d'un client « continu », modifiable ensuite sur sa fiche. |
| `CONTROLDONE_LLM_PLAFOND_DIAGNOSTIC_EUR` | `20.00` | Plafond d'un client « diagnostic ». |
| `CONTROLDONE_USD_EUR` | taux du jour | Taux utilisé pour convertir le coût IA en euros. |

Activer la clé Anthropic fait d'Anthropic, PBC (États-Unis) un **sous-traitant ultérieur** (§ 5.3).

Dans la console Anthropic, pense aussi à fixer une **limite de dépense** du compte : c'est une seconde barrière,
en plus des plafonds de l'application.

Vérifier la clé après le démarrage (un seul appel de quelques jetons, moins d'un centime ; la clé n'est jamais
affichée) : `docker compose exec app controldone llm verifier` — « clé Anthropic : présente » puis « appel de test :
OK ». Sans appel : `controldone llm verifier --sans-appel`. Coût du mois et plafond de chaque client :
`controldone llm couts`. Un client qui refuse l'envoi de ses documents à Anthropic : sur sa fiche, réglage
`llm_desactive` = `true` (D-4007). Détails : `docs/EXPLOITATION.md` § 5 et D-4001 à D-4008.

**Section 5 — Stripe** : au premier démarrage, **mode test** seulement (`sk_test_…`, `whsec_…` du webhook de
test). Laisser `STRIPE_LIVE_OK` vide. Le passage en réel est décrit au § 5.1.

**Section 6 — Mentions du vendeur** : raison sociale, forme juridique, SIREN, RCS, TVA, adresse, IBAN et BIC,
plus `CONTROLDONE_TVA_APPLICABLE` (`0` en franchise en base, `1` sinon). Ces mentions apparaissent sur tes
factures Factur-X. Sans elles, les factures portent « À COMPLÉTER ».

**Section 7 — Agents et connecteurs** :

- `CONTROLDONE_VEILLE_RESEAU=1` si tu veux que la veille télécharge les sources officielles ;
- `CONTROLDONE_IMAP_<NOM>` seulement pour la boîte dédiée d'un client ;
- tout le reste peut rester commenté.

**Section 8 — Notifications sur téléphone (ntfy, décision 8B)** : voir § 4.10. En résumé :

```
CONTROLDONE_NOTIF_WEBHOOK_URL=https://ntfy.sh/<ton-sujet-secret>
CONTROLDONE_NOTIF_WEBHOOK_FORMAT=texte
```

**Section 10 — Copie hors site** : ces variables se mettent dans la **crontab de l'hôte** (§ 4.9), pas dans les
conteneurs.

Contrôler que la configuration est complète, sans rien démarrer :

```
# docker compose config --quiet && echo "configuration OK"
```

### 4.3 Construire l'image

```
# cd /srv/controldone/app/deploy
# docker compose build
```

La construction prend plusieurs minutes : elle installe tesseract et les dépendances figées, dont les empreintes
sont vérifiées.

### 4.4 Créer le schéma de la base (`controldone migrer`, une seule fois)

Sur une base neuve, `controldone migrer` crée toutes les tables et inscrit les migrations. Sur une base
existante, il fait d'abord une sauvegarde chiffrée, puis applique les étapes en attente.

```
# docker compose run --rm migrer
```

Attendu : « migrations en attente : … », puis « schéma à jour. », code 0.

- `docker compose up` relance aussi ce service ponctuel automatiquement avant `web`, `worker` et `scheduler` ;
  le lancer à la main d'abord permet de lire son message.
- Équivalent sans le service `migrer` : `docker compose run --rm --no-deps scheduler controldone migrer`.
- Pour voir l'état sans rien changer : `docker compose run --rm --no-deps scheduler controldone migrer --etat`.

### 4.5 Démarrer et obtenir le certificat TLS

Avant de démarrer, vérifier deux points :

- le DNS pointe vers la VM (`dig +short app.exemple.fr` répond `<IP>`) ;
- les ports 80 et 443 sont ouverts (§ 3.3 et § 3.5).

```
# docker compose up -d
# docker compose ps
# docker compose logs --tail 50 caddy | grep -i -E "certificate|error"
```

Attendu :

- `web` est `healthy` ; `worker`, `scheduler` et `caddy` sont `running` ;
- `migrer` est `exited (0)`.

Caddy obtient le certificat en moins d'une minute. S'il échoue, c'est presque toujours le DNS ou un port
fermé. Corriger le problème, puis lancer `docker compose restart caddy`.

### 4.6 Contrôles de santé

Depuis **ton ordinateur** :

```
$ curl -fsS https://app.exemple.fr/sante                 # {"statut":"ok"}
$ curl -sI http://app.exemple.fr | head -3               # redirection 308 vers https://
$ curl -sI https://app.exemple.fr/sante | grep -i strict-transport-security
```

Sur le serveur :

```
# docker compose logs --tail 30 web worker scheduler      # aucune erreur ; scheduler : « tache_ok »
# docker compose exec scheduler controldone alertes etat  # canaux de notification configurés
# df -h /srv/controldone                                  # le volume /dev/mapper/cd_data
```

### 4.7 Créer ton compte fondateur et le second facteur (TOTP)

En production, **n'utilise jamais** `controldone init-demo` : il crée des données fictives et des identifiants de
démonstration.

```
# docker compose run --rm --no-deps web controldone creer-fondateur --email <ton adresse>
```

- Le mot de passe est **saisi** deux fois : 12 caractères minimum, jamais passé en argument.
- La commande affiche **une seule fois** le secret TOTP et l'URI `otpauth://…`. Ajoute aussitôt le secret dans
  ton application d'authentification : saisie manuelle du secret, ou QR code généré **sur ton ordinateur** à
  partir de l'URI. Garde une copie du secret dans ton gestionnaire de mots de passe : c'est ton seul moyen de
  secours.
- La commande refuse de modifier un compte existant.

Connexion : `https://app.exemple.fr/admin`, mot de passe puis code à 6 chiffres. Ouvre `/admin/alertes` : il ne
doit y avoir **aucune** alerte « Volume de la base non chiffré ».

Si tu t'es bloqué par trop d'essais : `docker compose run --rm --no-deps web controldone debit effacer --email
<ton adresse> --motif "essais"`.

### 4.8 Sauvegarde et exercice de restauration sur le serveur

1. Faire une première sauvegarde tout de suite, sans attendre la nuit :

   ```
   # docker compose exec scheduler /app/deploy/backup-cron.sh
   # docker compose exec scheduler controldone sauvegarde verifier --dernier --destination /backups
   # ls -l /srv/controldone/backups
   ```

2. Lancer l'**exercice de restauration de bout en bout**. C'est ce que fait `make restauration-test` sur un poste
   de développement ; `make` et l'environnement Python ne sont pas sur le serveur, donc on lance la même commande
   dans l'image :

   ```
   # docker compose run --rm --no-deps scheduler controldone sauvegarde exercice
   ```

   L'exercice travaille sur une base fictive neuve, dans un répertoire temporaire, avec une clé jetable. Il
   enchaîne : sauvegarde, contrôles négatifs, effacement, restauration, comparaison, puis démarrage du web sur
   les données restaurées avec connexion TOTP. Il ne touche **pas** à tes données. Attendu : chaque étape
   marquée `[ok]` avec sa durée, puis « RÉSULTAT : CONFORME », code 0.

3. Tester la restauration d'une **vraie archive**, celle qui vient d'être faite. Cela prouve que ta clé
   maîtresse ouvre tes sauvegardes :

   ```
   # mkdir -p /srv/controldone/restauration && chown 10001:10001 /srv/controldone/restauration
   # ARCHIVE=$(ls -t /srv/controldone/backups/controldone-*.tar.gz.enc | head -1)
   # (cd /srv/controldone/backups && sha256sum -c "$(basename "$ARCHIVE").sha256")
   # time docker compose run --rm --no-deps -v /srv/controldone/restauration:/restauration scheduler \
       controldone sauvegarde restaurer "/backups/$(basename "$ARCHIVE")" /restauration/essai --controler
   # rm -rf /srv/controldone/restauration/essai
   ```

   Attendu : « OK » pour l'empreinte, puis « résultat : CONFORME ». Noter la durée affichée.

### 4.9 Copie hors site avec rclone (Object Storage Scaleway `fr-par`)

1. **Console Scaleway** : Object Storage > Create bucket.
   - Nom : `controldone-sauvegardes-<suffixe>` (les noms sont uniques) ; région **fr-par** ; **privé**.
   - Ajouter une **règle de cycle de vie** qui supprime les objets après **35 jours**. La disponibilité de cette
     option dans la console est **à vérifier** ; elle existe aussi par l'API S3. Sans règle, supprime à la main
     chaque mois les archives de plus de 35 jours.
2. **Clé d'API dédiée** (IAM) : une application « controldone-sauvegardes » limitée à Object Storage, puis une
   clé d'accès (Access key + Secret key).
3. **Sur le serveur**, configurer rclone de façon interactive. Ainsi, les secrets ne restent pas dans
   l'historique du shell.

   ```
   # rclone config
   ```

   Répondre :

   - `n` (nouveau distant) ; nom **`objeu`** ;
   - type `s3` ; fournisseur `Scaleway` ;
   - `access_key_id` et `secret_access_key` : la clé de l'étape 2 ;
   - région `fr-par` ; point d'accès `s3.fr-par.scw.cloud` ;
   - ACL `private` ; le reste par défaut.

   Puis :

   ```
   # chmod 600 /root/.config/rclone/rclone.conf
   # rclone lsd objeu:                                         # le compartiment apparaît
   ```

4. **Premier envoi, à la main**, puis vérification :

   ```
   # BACKUP_RCLONE_REMOTE=objeu:controldone-sauvegardes-<suffixe> \
     BACKUP_ALERTE_COMPOSE=/srv/controldone/app/deploy/docker-compose.yml \
     /srv/controldone/app/deploy/backup-cron.sh --hors-site
   # rclone ls objeu:controldone-sauvegardes-<suffixe>
   ```

   Attendu : « copie hors site terminée et contrôlée ». Les fichiers `.tar.gz.enc` et `.sha256` sont visibles à
   distance.
5. **Crontab root** (`crontab -e`), une seule ligne :

   ```
   45 2,14 * * * BACKUP_RCLONE_REMOTE=objeu:controldone-sauvegardes-<suffixe> BACKUP_ALERTE_COMPOSE=/srv/controldone/app/deploy/docker-compose.yml /srv/controldone/app/deploy/backup-cron.sh --hors-site >> /var/log/controldone-backup.log 2>&1
   ```

   Pour un autre hébergeur, seul le distant rclone change : Hetzner `fsn1`, Infomaniak S3 ou OVHcloud. Les
   archives sont chiffrées avant l'envoi : le stockage objet ne voit jamais de données en clair.

### 4.10 Alertes sur ton téléphone (ntfy) et essai

1. Installer l'application **ntfy** sur ton téléphone (Android ou iOS).
2. Choisir un **sujet secret**. Sur le serveur public ntfy.sh, il n'y a pas de compte : « le sujet est en pratique
   un mot de passe » [N1]. Génère-le au hasard :

   ```
   # python3 -c "import secrets; print('controldone-' + secrets.token_urlsafe(24))"
   ```

3. Dans l'application, s'abonner à ce sujet (serveur `ntfy.sh`).
4. Dans `.env.prod`, renseigner :

   ```
   CONTROLDONE_NOTIF_WEBHOOK_URL=https://ntfy.sh/controldone-<la suite générée>
   CONTROLDONE_NOTIF_WEBHOOK_FORMAT=texte
   ```

5. Appliquer et tester :

   ```
   # docker compose up -d                                       # les conteneurs relisent .env.prod
   # docker compose exec scheduler controldone alertes etat     # « notifications : actives », canal webhook
   # docker compose exec scheduler controldone alertes essai    # « essai envoyé : webhook »
   ```

   Ton téléphone doit sonner dans la minute.

Ce qui part sur ntfy, et rien d'autre :

- le type d'alerte, un libellé fixe, un nombre, l'heure et le chemin `/admin/alertes` ;
- **jamais** de nom de client, de fichier ni de contenu (D-3502).

ntfy.sh garde les messages en cache 12 heures [N2]. Le lieu de ses serveurs n'est pas indiqué dans sa politique
de confidentialité ; c'est une raison de plus pour n'y mettre aucune donnée client. Pour tout garder chez toi, ntfy
peut aussi être auto-hébergé : l'URL change, la configuration reste la même.

**Sonde « homme mort »** (recommandée) : ntfy ne prévient que si l'application tourne. Pour être prévenu quand
**plus rien** ne tourne (serveur arrêté, volume non déverrouillé), crée un contrôle sur un service de type
Healthchecks (hébergé ou auto-hébergé) et mets son URL dans `BACKUP_PING_URL`, dans `.env.prod` et dans la ligne
de crontab. La sonde reçoit un signal à chaque sauvegarde et t'alerte si ce signal cesse.

Fais aussi surveiller `https://app.exemple.fr/sante` toutes les 5 minutes par une sonde de disponibilité
externe, au choix.

---

## 5. Stripe en réel, pages juridiques, sous-traitants

### 5.1 Passer Stripe en réel (tes gestes seulement)

Prérequis : le parcours de test est validé de bout en bout (`docs/FACTURATION.md`, « Mise en place de Stripe en
mode test ») :

- paiement avec la carte de test `4242 4242 4242 4242` ;
- webhook reçu (`stripe trigger checkout.session.completed`) ;
- facture Factur-X émise.

- [ ] **Activer le compte** dans le tableau de bord Stripe : identité du dirigeant, entreprise (SIREN), IBAN de
      versement, descriptif de l'activité. Attendre la validation.
- [ ] Double authentification sur le compte Stripe ; aucun autre utilisateur avec le rôle administrateur.
- [ ] En mode **réel**, Facturation > Paramètres : **désactiver l'envoi automatique des factures Stripe** (seule
      ta facture Factur-X fait foi) et activer le **portail client** (résiliation en ligne).
- [ ] Recréer en mode réel les produits et prix s'ils ont été configurés côté Stripe en mode test : les deux
      modes sont séparés.
- [ ] Développeurs > Webhooks, en mode **réel** : ajouter le point de terminaison
      `https://app.exemple.fr/webhooks/stripe` avec les événements :
      - `checkout.session.completed` ;
      - `invoice.paid` ;
      - `invoice.payment_failed` ;
      - `customer.subscription.updated` ;
      - `customer.subscription.deleted`.

      Copier son **nouveau** secret `whsec_…`.
- [ ] Développeurs > Clés API, en mode réel : la clé secrète `sk_live_…`. Une clé restreinte est préférable si tu
      sais la configurer.
- [ ] Dans `.env.prod` :
  - `STRIPE_SECRET_KEY=sk_live_…` ;
  - `STRIPE_WEBHOOK_SECRET=whsec_…` (celui du webhook réel) ;
  - `STRIPE_LIVE_OK=1`.

  L'application refuse une clé `sk_live_` sans `CONTROLDONE_ENV=prod` **et** `STRIPE_LIVE_OK=1`. Puis lancer
  `docker compose up -d`.
- [ ] Paiement réel de faible montant avec ta propre carte. Vérifier dans `/admin` que le paiement est enregistré,
      puis le rembourser depuis Stripe.
- [ ] Récupérer dans le contrat Stripe **l'entité contractante** et son pays. Pour la France, c'est
      vraisemblablement Stripe Payments Europe, Ltd. (Irlande), **à vérifier** dans ton contrat. Reporter ensuite
      cette entité dans `site/dpa.html`, `site/confidentialite.html` et `docs/RGPD_registre.md`.

### 5.2 Pages juridiques à publier (site vitrine)

Les fichiers sont dans le dépôt, en **brouillon à faire relire par un avocat**. Chaque page porte le bandeau
« BROUILLON — À RELIRE PAR UN AVOCAT ». Avant publication, remplir chaque `[À COMPLÉTER : …]`, trancher chaque
`[À VALIDER]` et retirer le bandeau une fois la relecture faite.

| Fichier | Contenu | À compléter pour l'hébergement |
|---|---|---|
| `site/mentions-legales.html` | Éditeur, directeur de la publication, **hébergeur du site** (nom, adresse, téléphone), lieu de stockage des données | Nom, adresse et téléphone de l'hébergeur : à recopier depuis les mentions légales officielles de Scaleway (ou de l'hébergeur choisi) |
| `site/cgv.html` | Conditions générales de vente (diagnostic, abonnement, commission), paiement via Stripe | Identité du vendeur, délais, tribunal compétent |
| `site/confidentialite.html` | Politique de confidentialité (site et prospection) | Hébergeur et durée de conservation de ses journaux, entité Stripe |
| `site/dpa.html` | Accord de sous-traitance (art. 28 RGPD, art. 9 LPD), section 7 « Sous-traitants ultérieurs » | Les lignes du § 5.3 ci-dessous |
| `site/methode.html` | Encadré « Hébergement dans l'Union européenne » | Nom de l'hébergeur |

Interne, non publié : `docs/RGPD_registre.md` (§ 1.3, sous-traitants ultérieurs ; journaux de l'hébergeur).

Le site vitrine est statique. L'héberger à part, dans l'UE, en HTTPS, avec les en-têtes conseillés dans
`site/README.md`. Un compartiment Object Storage en mode « site web » ou un petit serveur conviennent. Vérifier
avant publication : `pytest tests/site -q` sur ton poste.

### 5.3 Liste des sous-traitants ultérieurs à déclarer

| Sous-traitant | Rôle | Lieu | Garanties | Quand |
|---|---|---|---|---|
| **Scaleway SAS** (ou l'hébergeur choisi) | VM, volume chiffré, base, coffre | France, Paris (PAR-1) | DPA Scaleway (console > Organization contracts) | toujours |
| **Scaleway SAS** — Object Storage | Copie hors site des sauvegardes **chiffrées avant envoi** | France (fr-par) | même DPA | toujours |
| **Anthropic, PBC** | Lecture de pages de documents par modèle de langage | États-Unis | Clauses contractuelles types incorporées au DPA d'Anthropic (voir `site/dpa.html`). Addendum suisse **[À VALIDER]**. TIA à rédiger. Désactivable par client | si `ANTHROPIC_API_KEY` est défini (décision 1A : oui) |
| **Stripe** (entité à recopier du contrat) | Paiement par carte, abonnements. Ne reçoit que les données de facturation du client, jamais ses documents | à recopier du contrat | DPA Stripe. Stripe est probablement responsable de traitement pour une partie des données **[À VALIDER]** | dès l'encaissement |
| **ntfy.sh** (ou ton instance auto-hébergée) | Notifications d'alerte sur ton téléphone | non indiqué par le service | **Ne reçoit aucune donnée client** (type d'alerte et compteur seulement) : à mentionner par transparence dans le registre, pas dans le DPA client | si `CONTROLDONE_NOTIF_WEBHOOK_URL` pointe vers ntfy.sh |
| Service de sonde (Healthchecks ou autre), registraire DNS, GitHub | Surveillance, nom de domaine, code source | — | Aucune donnée client | registre interne seulement |

Après le choix de l'hébergeur, mettre à jour **les quatre endroits** :

- `site/dpa.html` § 7 ;
- `site/confidentialite.html` ;
- `site/mentions-legales.html` ;
- `docs/RGPD_registre.md` § 1.3.

Ajouter ou changer un sous-traitant ultérieur impose d'informer chaque client à l'avance, selon le préavis fixé
dans le DPA.

---

## 6. Ouverture, retour arrière, routine mensuelle

### 6.1 Liste de contrôle avant ouverture

**Hébergeur et machine**

- [ ] Compte hébergeur avec double authentification ; DPA téléchargé et rangé.
- [ ] VM en région Paris (ou Suisse) ; groupe de sécurité : 22 (ton IP), 80 et 443 seulement ; `ufw status`
      conforme.
- [ ] SSH par clé seulement ; `PermitRootLogin no` ; connexion `cdadmin` puis `sudo` vérifiée.
- [ ] `unattended-upgrades` actif ; redémarrage automatique **désactivé**.
- [ ] Volume LUKS monté sur `/srv/controldone`. Phrase de passe et en-tête LUKS rangés hors machine. Docker
      désactivé au démarrage.

**Configuration**

- [ ] `.env.prod` en mode 0600 avec `CONTROLDONE_ENV=prod`.
- [ ] `CONTROLDONE_MASTER_KEY` copiée hors machine (gestionnaire + papier).
- [ ] Clé Anthropic en place, plafonds réglés, limite de dépense posée dans la console Anthropic.

**Service et accès**

- [ ] `https://app.exemple.fr/sante` répond `{"statut":"ok"}`.
- [ ] `http://` redirige vers `https://` ; certificat valide ; CAA en place.
- [ ] Compte fondateur créé par `creer-fondateur` ; connexion TOTP vérifiée ; secret TOTP sauvegardé.
- [ ] Aucune base de démonstration en production ; aucune alerte « volume non chiffré ».

**Sauvegardes et alertes**

- [ ] Sauvegarde locale faite.
- [ ] Exercice `controldone sauvegarde exercice` réussi ; restauration de la vraie archive « CONFORME », durée
      notée.
- [ ] Copie hors site faite et contrôlée ; ligne de crontab en place ; règle de 35 jours sur le compartiment.
- [ ] `controldone alertes essai` reçu sur le téléphone ; sonde « homme mort » et sonde `/sante` actives.

**Stripe et site**

- [ ] Stripe : test validé ; passage en réel fait selon le § 5.1 (ou différé, en connaissance de cause).
- [ ] Pages juridiques complétées, relues par l'avocat et publiées ; sous-traitants à jour aux quatre endroits.

### 6.2 Retour arrière

**Pendant la toute première mise en ligne** (aucun client encore) : `docker compose down`, corriger, puis
`docker compose up -d`. Rien à restaurer.

**Lors d'une mise à jour** (procédure complète : `docs/DEPLOIEMENT.md` § 13) :

1. Avant la mise à jour :
   - `docker compose exec scheduler /app/deploy/backup-cron.sh` (sauvegarde) ;
   - noter la valeur actuelle de `CONTROLDONE_VERSION` ;
   - changer `CONTROLDONE_VERSION` dans `.env.prod` (par exemple `2.0.1`) avant `docker compose build`.
     L'ancienne image reste alors disponible.
2. Si la nouvelle version pose problème **et qu'aucune migration n'a tourné** (le journal du service `migrer`
   indique « migrations en attente : aucune ») :

   ```
   # cd /srv/controldone/app && git checkout <ancien commit>
   # sed -i 's/^CONTROLDONE_VERSION=.*/CONTROLDONE_VERSION=2.0.0/' deploy/.env.prod
   # cd deploy && docker compose up -d && docker compose ps
   ```

3. Si une **migration a modifié la base**, revenir à l'ancienne image ne suffit pas : il faut aussi restaurer la
   sauvegarde faite juste avant. `controldone migrer` en fait une automatiquement ; c'est la plus récente de
   `/srv/controldone/backups` avant l'heure de la mise à jour. Procédure : `docs/EXPLOITATION.md` § 3.2, en
   remplaçant `var/` par `/srv/controldone/var/`. Les grandes étapes :
   - `docker compose stop web worker scheduler` ;
   - restaurer avec `--controler` dans un répertoire vide ;
   - mettre de côté la base et le coffre actuels, puis mettre les fichiers restaurés à leur place ;
   - revenir à l'ancienne version (étape 2).

   Prévenir les clients : ce qui a été déposé depuis la sauvegarde est à redéposer.
4. Perte totale de la VM : nouvelle VM (§ 3), même `.env.prod` (clé maîtresse depuis ton gestionnaire), archive
   récupérée par `rclone copy objeu:<compartiment>/<archive> /srv/controldone/backups/`, restauration, bascule du
   DNS. Objectif : 4 heures ouvrées, non mesuré ; voir « RPO / RTO » dans `deploy/README.md`.

### 6.3 Routine mensuelle (une heure, le même jour chaque mois)

- [ ] **Alertes** : `/admin/alertes` vide ou traité ; `docker compose logs --since 720h scheduler | grep
      tache_echec` ne renvoie rien d'inquiétant.
- [ ] **Sauvegardes** :
  - `ls -lt /srv/controldone/backups | head` (archive du jour présente) ;
  - `rclone ls objeu:<compartiment> | tail` (copies distantes présentes ; rien de plus vieux que 35 jours) ;
  - `tail -n 20 /var/log/controldone-backup.log`.
- [ ] **Exercice de restauration** sur une vraie archive **téléchargée depuis le stockage objet** (§ 4.8, point 3,
      en partant de `rclone copy`). Noter la durée.
- [ ] **Système** :
  - `apt update && apt -y upgrade` (met aussi à jour Docker) ;
  - si `/var/run/reboot-required` existe, redémarrer à une heure creuse (`reboot`), puis appliquer la procédure
    de déverrouillage du § 3.6.
- [ ] **Image** : sauvegarde, puis `git pull --ff-only` s'il y a une version, puis `docker compose build --pull`
      (correctifs Debian et tesseract) et `docker compose up -d`. Vérifier `/sante`. Voir `docs/DEPLOIEMENT.md`
      § 13.
- [ ] **Disque** : `df -h / /srv/controldone`. Agrandir le volume au-delà de 80 % d'occupation.
- [ ] **Mémoire** : `docker stats --no-stream`. Si le worker approche la RAM disponible pendant les lots, passer
      en 8 Go.
- [ ] **Coûts** :
  - page Finances de `/admin` (coût IA par client, plafonds) ;
  - console Anthropic (dépense du mois) ;
  - facture de l'hébergeur ;
  - versements Stripe.
- [ ] **Accès** : `last -n 20` (connexions SSH attendues seulement) ; liste des clés de déploiement GitHub ;
      membres du compte hébergeur et du compte Stripe.
- [ ] **Juridique** : sous-traitants inchangés ? Sinon, mettre à jour les quatre endroits du § 5.3 et prévenir
      les clients.

Une fois par an :

- relire les prix et les contrats (DPA) de l'hébergeur ;
- renouveler le domaine (vérifier le renouvellement automatique) ;
- envisager une rotation de la clé maîtresse (`docs/SECURITY.md` § 3).

---

## Annexe — Sources consultées le 2026-10-06

Pages officielles des hébergeurs, sauf mention « source secondaire ».

- [S1] Scaleway, prix des instances (zone PAR-1, « Prices before tax ») : https://www.scaleway.com/en/pricing/virtual-instances/
- [S2] Scaleway, prix du stockage (Block Storage, snapshots, Object Storage fr-par, sortie) : https://www.scaleway.com/en/pricing/storage/
- [S3] Scaleway, prix des bases gérées PostgreSQL/MySQL : https://www.scaleway.com/en/pricing/managed-databases/
- [S4] Scaleway, téléchargement des contrats (DPA, mesures techniques et organisationnelles) : https://www.scaleway.com/en/docs/account/support/download-scaleway-contracts/ et https://www.scaleway.com/en/contracts/
- [S5] Scaleway, prix réseau (« Additional IP address » 0,005 €/h ; correspondance avec l'IPv4 flexible **non confirmée**) : https://www.scaleway.com/en/pricing/network/
- [S6] Scaleway, chiffrement au repos des bases gérées (LUKS, clé gérée par Scaleway) : https://www.scaleway.com/en/docs/managed-databases-for-postgresql-and-mysql/api-cli/setting-up-encryption-at-rest/
- [O1] OVHcloud, gamme VPS (VPS 2027 : spécifications, prix d'appel, sauvegarde, snapshots) : https://www.ovhcloud.com/fr/vps/
- [O2] OVHcloud, billet officiel « Évolutions tarifaires… » (VPS au 1er avril 2026, IPv4 additionnelle 2,00 €) : https://blog.ovhcloud.com/evolutions-tarifaires-de-public-cloud-bare-metal-et-vps-chez-ovhcloud/
- [O3] OVHcloud, PostgreSQL géré (page produit ; prix non relevé) : https://www.ovhcloud.com/fr/public-cloud/postgresql/
- [O4] DPA OVHcloud : **source secondaire** https://donneespersonnelles.fr/ovhcloud-rgpd. Page officielle à consulter : https://www.ovhcloud.com/fr/personal-data-protection/
- [H1] Hetzner, ajustement de prix du 15 juin 2026 (CX23, CX33, CAX11, CAX21…) : https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- [H2] Hetzner, gamme « Cost-Optimized » (spécifications, emplacements ; prix non affichés sans JavaScript) : https://www.hetzner.com/cloud/cost-optimized
- [H3] Hetzner, protection des données (DPA dans le compte client, chiffrement à la charge du client) : https://docs.hetzner.com/general/company-and-policy/data-protection-at-hetzner
- [H4] Hetzner, Object Storage (emplacements, verrouillage d'objets, forfait de base) : https://www.hetzner.com/storage/object-storage/
- [H5] Hetzner, FAQ Primary IPs (facturation séparée) : https://docs.hetzner.com/cloud/servers/primary-ips/faq/
- [I1] Infomaniak, Public Cloud (Suisse, Ceph chiffré LUKS, Object Storage chiffré, exemple CHF 16.10/mois, crédit CHF 300) : https://www.infomaniak.com/fr/hebergement/public-cloud
- [I2] Infomaniak, tarifs Public Cloud (catégories dont « Database Service ») : https://www.infomaniak.com/fr/hebergement/public-cloud/tarifs
- [I3] Infomaniak, FAQ 2820 « Comprendre la sécurité des données (LPD et RGPD) » (DPA dans le Manager, données en Suisse) : https://www.infomaniak.com/fr/support/faq/2820/comprendre-la-securite-des-donnees-lpd-et-rgpd
- [I4] Infomaniak, VPS Cloud (« dès CHF 38.41 / mois », snapshot inclus) : https://www.infomaniak.com/fr/hebergement/vps-cloud
- [N1] ntfy, publication (« the topic is essentially a password ») : https://docs.ntfy.sh/publish/
- [N2] ntfy, politique de confidentialité (cache de 12 h) : https://docs.ntfy.sh/privacy/

Non vérifiés et laissés comme tels :

- le prix exact de l'IPv4 chez Scaleway et chez Hetzner ;
- les prix du stockage objet chez Hetzner, OVHcloud et Infomaniak ;
- les prix du PostgreSQL géré chez OVHcloud et Infomaniak ;
- le prix d'une VM 2 vCPU / 4 Go chez Infomaniak ;
- l'option de disque additionnel des VPS OVHcloud ;
- la règle de cycle de vie dans la console Scaleway ;
- les prix des noms de domaine ;
- l'entité contractante de Stripe.
