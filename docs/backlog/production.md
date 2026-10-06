# Backlog — bloc P, fiabilité de la production (octobre 2026)

Constats repérés pendant le bloc P (sauvegarde PostgreSQL, alertes poussées, migrations, verrou de maintenance)
et non traités, faute de périmètre. Décisions du bloc : D-3501 à D-3505.

- **Image Docker sans PostgreSQL.** Constat : `deploy/Dockerfile` installe `requirements.lock` (sans `pg8000`) et
  pas `postgresql-client` ; la sauvegarde PostgreSQL a besoin de `pg_dump` / `pg_restore` **de la même version
  majeure que le serveur**. Impact : passer `CONTROLDONE_DATABASE_URL` à PostgreSQL en production échouerait au
  démarrage (pilote absent) puis à la sauvegarde (code 2, alerte). Proposition : argument de construction
  `AVEC_POSTGRES=1` qui ajoute `pg8000` (extra `postgres`) et `postgresql-client-<version>` (dépôt PGDG), plus
  un contrôle au démarrage du scheduler (`pg_dump --version` contre `SHOW server_version`). À faire (avant tout
  passage à PostgreSQL ; non testable ici : pas de Docker).
- **`pg8000` et ses dépendances hors du fichier figé.** Constat : `python-dateutil` et `six` avaient été retirés
  du venv (nettoyage des paquets non figés) alors que `pg8000` en dépend ; réinstallés pour ce bloc. Impact :
  tests PostgreSQL et `make restauration-test-pg` cassés si le venv est reconstruit sans l'extra. Proposition :
  `uv pip install -e .[dev,postgres]` dans `make install`, et l'extra dans `requirements.lock` le jour où la
  production passe à PostgreSQL. À faire (outillage).
- **Tests PostgreSQL ignorés par défaut.** Constat : `tests/platform/test_migrations.py`,
  `test_sauvegarde_postgresql.py` ne tournent qu'avec `CONTROLDONE_TEST_PG_URL` (serveur jetable). Impact : une
  régression PostgreSQL (débit `FOR UPDATE`, révocations, `SKIP LOCKED`, migrations) passe inaperçue. Proposition :
  job CI avec un conteneur `postgres:16` et `CONTROLDONE_TEST_PG_URL`, plus `make restauration-test-pg` ; à terme
  toute la suite plateforme paramétrée sur les deux moteurs. À faire (outillage, avec le point sécurité « débit
  sur PostgreSQL »).
- **Verrou de maintenance limité à un hôte.** Constat : `flock` sur `<data_dir>/.verrou-maintenance` (D-3504).
  Impact : nul avec le déploiement actuel (un hôte, volume partagé) ; avec PostgreSQL partagé entre plusieurs
  hôtes, deux machines pourraient purger et sauvegarder en même temps. Proposition : en plus du fichier,
  `pg_try_advisory_lock` sur une connexion tenue pendant l'opération. À faire (si plusieurs hôtes).
- **Effacement RGPD d'un client sans le verrou.** Constat : `storage/retention.supprimer_client` supprime le
  coffre d'un client sans prendre le verrou de maintenance. Impact : faible — une sauvegarde concurrente peut
  manquer des objets d'un client en cours d'effacement (le contrôle approfondi le signalerait comme « contenu
  référencé absent ») ; aucune perte pour un client conservé. Proposition : prendre le verrou (attente courte) et
  refuser l'effacement pendant une sauvegarde. À faire (faible).
- **Démarrage refusé pendant une mise à jour qui migre.** Constat : avec une migration en attente, `web` et
  `worker` sortent en code 3 et `restart: unless-stopped` les relance en boucle jusqu'à `controldone migrer`
  (procédure `docs/DEPLOIEMENT.md` § 13). Impact : indisponibilité tant que l'exploitant n'a pas migré.
  Proposition : service compose ponctuel `migrer` (profil `maintenance`) dont `web` dépend
  (`service_completed_successfully`), avec sauvegarde vers `/backups`. À faire (décision : migration automatique
  avec sauvegarde, ou manuelle).
- **Historique des notifications invisible.** Constat : `notifications_alertes` (envoyée, échec, essais) n'est
  lisible qu'en base ; `/admin/alertes` ne dit pas si une alerte a été poussée ni si un canal est en panne.
  Proposition : colonne « notifiée » et encart « canaux : webhook OK / courriel en échec depuis … » sur
  `/admin/alertes` (sans afficher l'URL ni l'adresse). À faire (bloc interface).
- **Bandeau des alertes de sauvegarde sur `/admin`.** Constat : les libellés sont faits (D-3505), pas le bandeau
  tant qu'une alerte `sauvegarde_*` n'est pas lue. À faire (bloc interface).
- **Notification quand le scheduler est arrêté.** Constat : les notifications sont envoyées par le conteneur
  `scheduler` ; s'il ne tourne plus, rien ne part. Impact : seul `BACKUP_PING_URL` couvre ce cas. Proposition :
  faire de la sonde « homme mort » un point obligatoire de la liste de contrôle d'ouverture (`docs/DEPLOIEMENT.md`
  § 15) et envoyer aussi un battement quotidien du scheduler. À faire (procédure).
- **Une sauvegarde PostgreSQL ne contient que le schéma courant.** Constat : `pg_dump` sauvegarde le schéma de
  `CONTROLDONE_DATABASE_URL` (`current_schema`), pas les rôles ni les réglages du serveur (`pg_dumpall
  --globals-only`). Impact : restaurer sur un serveur neuf demande de recréer l'utilisateur applicatif à la main.
  Proposition : documenter la commande dans la procédure de restauration, ou ajouter `globals.sql` (sans mots de
  passe) à l'archive. À faire (faible).
