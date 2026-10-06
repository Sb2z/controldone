# Bloc D — sauvegardes et restauration : améliorations repérées

- **PostgreSQL sans sauvegarde automatique.** Constat : `src/controldone/storage/sauvegarde.py` (`main`, commande
  `sauvegarder`) refuse une base non SQLite (code 2) ; `docs/EXPLOITATION.md` § 3.1 renvoie à un `pg_dump` manuel.
  Impact : un passage à PostgreSQL laisserait la production sans sauvegarde ni vérification ni exercice. Proposition :
  `pg_dump -Fc` envoyé dans le même flux chiffré `CDSAV2` (entrée `base/controldone.dump`), manifeste avec les
  lignes par table lues dans la base, restauration par `pg_restore` dans une base vide, exercice sur un PostgreSQL
  jetable. **Fait (D-3501)** : `make restauration-test-pg` conforme sur PostgreSQL 16 ; reste l'image Docker
  (`docs/backlog/production.md`).

- **Compression gzip niveau 9 sur un coffre déjà chiffré.** Constat : `sauvegarder` ouvre le tar en `w|gz` (niveau
  9 par défaut) ; le coffre est chiffré donc incompressible. Mesure (poste de développement, coffre de 200 Mo) :
  création 7,1 s contre 1,7 s pour la restauration. Impact : sauvegarde 4 fois plus lente que nécessaire (aucun verrou
  pris, mais le processeur du scheduler est occupé). Proposition : niveau 1 (Python ≥ 3.12 accepte `compresslevel` en mode
  flux) ou compression de la seule base. À faire.

- **Libellés des alertes de sauvegarde dans l'interface.** Constat : `src/controldone/web/templates/admin/alertes.html.j2`
  ne traduit que `job_mort` et `cout_ia_*` ; les nouvelles alertes `sauvegarde_echec`, `sauvegarde_verification_echec`,
  `sauvegarde_absente`, `sauvegarde_hors_site_echec` s'affichent sous leur nom technique. Impact : lisibilité.
  Proposition : ajouter les libellés (« Sauvegarde en échec », « Sauvegarde non conforme », « Aucune sauvegarde
  récente », « Copie hors site en échec ») et un bandeau sur `/admin` tant qu'une alerte de sauvegarde n'est pas
  lue. **Libellés faits (D-3505)** ; bandeau à faire (bloc interface).

- **Alertes non poussées.** Constat : les alertes fondateur (`storage/alertes.py`) ne sont visibles qu'en se
  connectant à `/admin` ; aucun courriel n'existe dans le code. Impact : une sauvegarde en panne peut rester
  inaperçue plusieurs jours si `BACKUP_PING_URL` n'est pas configuré (RPO non borné). Proposition : configurer la
  sonde externe à l'ouverture (liste de contrôle de `docs/DEPLOIEMENT.md` § 15) ; à terme, une notification par
  courriel des alertes critiques. **Fait (D-3502)** : webhook et courriel, désactivés tant que non configurés ;
  reste le choix du prestataire (décision du fondateur) et la configuration à l'ouverture.

- **RPO de 24 h.** Constat : une seule sauvegarde par jour (`SCHED_BACKUP_HHMM`). Impact : jusqu'à une journée de
  dépôts et de décisions perdue si le volume est perdu. Proposition : deux sauvegardes par jour (coût : quelques
  secondes et un peu d'espace), ou expédition continue du WAL SQLite (outil type Litestream, licence Apache 2.0)
  vers le stockage objet UE. **Fait (D-4105)** : deux sauvegardes par jour (02:15 et 14:15 UTC), RPO 12 h ;
  expédition continue du journal écartée pour l'instant.

- **Mise en service d'une restauration encore manuelle.** Constat : `docs/EXPLOITATION.md` § 3.2, étapes 4 et 5
  (déplacer base, coffre et traces). Impact : erreurs de manipulation possibles sous stress (RTO). Proposition :
  `controldone sauvegarde mettre-en-service <répertoire_restauré>` qui refuse si le web ou le worker tournent
  (verrou), met de côté l'existant avec un horodatage et déplace atomiquement sur le même volume. À faire.

- **Copie séquestrée de la clé maîtresse jamais testée.** Constat : la documentation demande une copie papier sous
  scellé de `CONTROLDONE_MASTER_KEY`, mais rien ne vérifie qu'elle ouvre réellement les archives. Impact : clé mal
  recopiée découverte le jour du sinistre. Proposition : `controldone sauvegarde verifier --cle-stdin` (clé saisie,
  jamais en argument ni en variable), à faire lors de l'exercice mensuel. À faire.

- **Exercice mensuel sur une vraie archive encore manuel.** Constat : `make restauration-test` couvre une base
  fictive ; l'exercice sur l'archive de production téléchargée depuis le stockage objet (`docs/DEPLOIEMENT.md` § 14)
  dépend de la discipline du fondateur. Proposition : routine mensuelle sur une VM de test jetable (téléchargement
  rclone, `restaurer --controler`, durée notée). À faire.

- **Traces d'envoi en clair sur le disque.** Constat : `src/controldone/outbox/expediteurs.py` (`ExpediteurFichier`)
  écrit `var/outbox_envoyee/<kind>/<id>.json` en clair (protégé seulement par le volume LUKS) ; elles sont désormais
  sauvegardées (chiffrées dans l'archive). Impact : copie en clair de rapports hors du coffre chiffré. Proposition :
  passer ces traces par le coffre (`FileVault`) ou les chiffrer avec une clé dérivée. **Fait (D-4106)** : clé
  dérivée `outbox_envoyee`, fichiers existants chiffrés par `controldone migrer`, contrôle approfondi.

- **Purge lancée à la main pendant une sauvegarde.** Constat : le planificateur fait maintenant la sauvegarde avant
  la purge (D-3306), mais une purge mise en file à la main pendant la copie peut retirer un objet que l'instantané
  référence. Impact : objet manquant dans l'archive, signalé par le contrôle approfondi (« contenu référencé
  absent »), sans conséquence pour un contenu de toute façon expiré. Proposition : verrou consultatif partagé
  sauvegarde/purge dans `var/`. **Fait (D-3306 pour le cas planifié, D-3504 pour le cas manuel)** : verrou
  `flock` partagé par sauvegarde, purge et restauration ; purge reportée de 10 minutes.
