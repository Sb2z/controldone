# Backlog — bloc P, fiabilité de la production (octobre 2026)

Constats repérés pendant le bloc P (sauvegarde PostgreSQL, alertes poussées, migrations, verrou de maintenance)
et non traités, faute de périmètre. Décisions du bloc : D-3501 à D-3505.

- **Image Docker sans PostgreSQL.** Constat : `deploy/Dockerfile` installe `requirements.lock` (sans `pg8000`) et
  pas `postgresql-client` ; la sauvegarde PostgreSQL a besoin de `pg_dump` / `pg_restore` **de la même version
  majeure que le serveur**. Impact : passer `CONTROLDONE_DATABASE_URL` à PostgreSQL en production échouerait au
  démarrage (pilote absent) puis à la sauvegarde (code 2, alerte). Proposition : argument de construction
  `AVEC_POSTGRES=1` qui ajoute `pg8000` (extra `postgres`) et `postgresql-client-<version>` (dépôt PGDG), plus
  un contrôle au démarrage du scheduler (`pg_dump --version` contre `SHOW server_version`). **Fait (D-4101)** :
  `PG_CLIENT_MAJOR` (défaut 16, dépôt PGDG, clé versionnée), image construite et sauvegarde / restauration
  PostgreSQL vérifiées dans le conteneur. Reste : le contrôle de version au démarrage (pg_dump refuse déjà un
  serveur plus récent, code 2 + alerte).
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
  `pg_try_advisory_lock` sur une connexion tenue pendant l'opération. **Fait (D-4701)** : verrou consultatif
  de session sur une connexion dédiée, détenteur identifié, testé sur une grappe jetable.
- **Effacement RGPD d'un client sans le verrou.** **Fait (D-4103).** Constat : `storage/retention.supprimer_client` supprime le
  coffre d'un client sans prendre le verrou de maintenance. Impact : faible — une sauvegarde concurrente peut
  manquer des objets d'un client en cours d'effacement (le contrôle approfondi le signalerait comme « contenu
  référencé absent ») ; aucune perte pour un client conservé. Proposition : prendre le verrou (attente courte) et
  refuser l'effacement pendant une sauvegarde. À faire (faible).
- **Démarrage refusé pendant une mise à jour qui migre.** Constat : avec une migration en attente, `web` et
  `worker` sortent en code 3 et `restart: unless-stopped` les relance en boucle jusqu'à `controldone migrer`
  (procédure `docs/DEPLOIEMENT.md` § 13). Impact : indisponibilité tant que l'exploitant n'a pas migré.
  Proposition : service compose ponctuel `migrer` (profil `maintenance`) dont `web` dépend
  (`service_completed_successfully`), avec sauvegarde vers `/backups`. **Fait (D-4102)** : service ponctuel
  `migrer` (sans profil : il tourne à chaque `up`), attente puis sortie unique des processus en production.
- **Historique des notifications invisible.** Constat : `notifications_alertes` (envoyée, échec, essais) n'est
  lisible qu'en base ; `/admin/alertes` ne dit pas si une alerte a été poussée ni si un canal est en panne.
  Proposition : colonne « notifiée » et encart « canaux : webhook OK / courriel en échec depuis … » sur
  `/admin/alertes` (sans afficher l'URL ni l'adresse). **API faite (D-4104)** — voir « Historique des
  notifications : mode d'emploi » ci-dessous ; **page faite (D-4304)** : `/admin/notifications`.
- **Bandeau des alertes de sauvegarde sur `/admin`.** Constat : les libellés sont faits (D-3505), pas le bandeau
  tant qu'une alerte `sauvegarde_*` n'est pas lue. **Fait (D-4303).**
- **Notification quand le scheduler est arrêté.** Constat : les notifications sont envoyées par le conteneur
  `scheduler` ; s'il ne tourne plus, rien ne part. Impact : seul `BACKUP_PING_URL` couvre ce cas. Proposition :
  faire de la sonde « homme mort » un point obligatoire de la liste de contrôle d'ouverture (`docs/DEPLOIEMENT.md`
  § 15) et envoyer aussi un battement quotidien du scheduler. À faire (procédure).
- **Une sauvegarde PostgreSQL ne contient que le schéma courant.** Constat : `pg_dump` sauvegarde le schéma de
  `CONTROLDONE_DATABASE_URL` (`current_schema`), pas les rôles ni les réglages du serveur (`pg_dumpall
  --globals-only`). Impact : restaurer sur un serveur neuf demande de recréer l'utilisateur applicatif à la main.
  Proposition : documenter la commande dans la procédure de restauration, ou ajouter `globals.sql` (sans mots de
  passe) à l'archive. À faire (faible).

## Bloc P3 (octobre 2026)

Décisions D-4101 à D-4106. Faits : image avec client PostgreSQL 16 (D-4101), service `migrer` et attente au
démarrage (D-4102), effacement sous verrou (D-4103), ntfy de premier rang et historique (D-4104), deux
sauvegardes par jour (D-4105), traces d'envoi chiffrées (D-4106), D-3601 à D-3605 reportés dans
`docs/SECURITY.md`.

### Historique des notifications : mode d'emploi pour l'interface (D-4104)

```python
from controldone.services.notifications import historique
h = historique(plateforme.db, limite=50, jours=30)    # lecture seule, une transaction courte
h.actif, h.motif_inactif                  # notifications actives ? sinon pourquoi (« aucun canal configuré … »)
h.canaux_configures                       # ("webhook",) / ("courriel", "webhook") — jamais l'URL, le jeton ni l'adresse
h.erreurs_configuration                   # variables mal remplies (texte écrit par notre code)
h.canaux                                  # {"webhook": EtatCanal(canal, dernier_succes, dernier_echec, en_echec)}
for n in h.notifications:                 # storage.alertes.NotificationEnvoyee, la plus récente d'abord
    h.libelle(n.kind), n.jour, n.nombre, n.statut, n.envoyee, n.essais, n.canaux, n.premier_essai, n.envoyee_le
```

- `n.kind == "essai"` : notification d'essai lancée par le fondateur (`controldone alertes essai`).
- `n.canaux` : `{"webhook": "ok", "courriel": "echec"}` ; `n.statut` : `envoyee` (au moins un canal) ou `echec`
  (retenté au passage suivant, 5 essais par jour au plus).
- Encart suggéré sur `/admin/alertes` : « Notifications : actives (webhook) — dernier envoi réussi le … » ou
  « canal webhook en échec depuis … » si `EtatCanal.en_echec` ; colonne « notifiée » d'une alerte :
  `Alerte.notifiee_le` (traitée) et la ligne d'historique du même `kind` et du même jour.
- Ligne de commande équivalente : `controldone alertes historique [--limite N]`.
- Heures en UTC en base (`datetime` naïf sous SQLite) : afficher en Europe/Paris comme le reste de l'interface.

### Constats du bloc P3, hors périmètre

- **Test de bout en bout de `docker compose up` avec le service `migrer`.** Constat : la composition est
  validée (`docker compose config`) et chaque commande vérifiée dans l'image, mais pas une montée de version
  réelle avec Caddy et un domaine. Proposition : l'ajouter à la répétition générale de `docs/MISE_EN_LIGNE.md`.
  À faire (procédure).
- **Facturation modifiée a minima.** `facturation/service.py` (`ExpediteurFacture`) chiffre désormais sa copie
  locale (D-4106). Si une relecture est voulue (« télécharger la facture émise ») : `TracesEnvoi.lire(chemin)`.
  À faire (si besoin, bloc facturation).
- **Contrôle de version `pg_dump` / serveur au démarrage du scheduler.** Voir plus haut. À faire (faible).
- **Aucune étape de schéma ajoutée par ce bloc** (D-4104 réutilise la colonne `canaux` ; la 5, `langue_utilisateur`,
  vient du bloc interface).

## Bloc P4 (octobre 2026)

Décisions D-4701 à D-4704. Faits : verrou de maintenance entre hôtes (verrou consultatif PostgreSQL, D-4701),
exercice mensuel sur la dernière vraie archive avec compte rendu daté sans donnée client et planification
désactivée par défaut (D-4702), empreinte publique de la clé et procédure de contrôle de la copie papier
(D-4703), suivi mensuel des vulnérabilités de l'image sans réseau (D-4704), `docs/A_FAIRE.md` § 2 remis à jour.
Commandes : `controldone sauvegarde exercice-mensuel`, `make suivi-cve`, `make test-pg-plateforme`.

### Constats du bloc P4, hors périmètre

- **Mise en service d'une restauration encore manuelle** (`docs/backlog/sauvegardes.md`) : toujours à faire ;
  l'exercice mensuel ne remplace pas `controldone sauvegarde mettre-en-service`.
- **Tests PostgreSQL hors de la CI** : `make test-pg-plateforme` s'ajoute à `make test-pg-securite` et
  `make restauration-test-pg` ; les trois sont à mettre dans le job CI manuel (décision du fondateur sur la CI).
  Plusieurs tests PostgreSQL anciens (`test_migrations.py`, `test_sauvegarde_postgresql.py`) ne portent pas le
  marqueur `postgresql` et ne tournent donc pas avec `-m postgresql`. Proposition : les marquer, puis une seule
  cible `make test-pg`. À faire (outillage).
- **Exercice mensuel et espace disque** : la copie jetable est créée à côté de l'archive (`/backups`). Un volume
  de sauvegarde presque plein fait échouer l'exercice (code 1, alerte) sans gêner les sauvegardes suivantes
  (copie supprimée). Proposition : contrôle de l'espace libre avant de restaurer (taille en clair du manifeste
  × 1,2). À faire (faible).
- **Libellé dédié pour l'échec de l'exercice mensuel** : il réutilise `sauvegarde_verification_echec` (message
  « Exercice mensuel en échec sur … »). Un type `exercice_mensuel_echec` demanderait un libellé dans l'écran
  Alertes et les notifications. À décider (interface), faible.
- **`make audit-image` dans la routine mensuelle** : demande Docker et un accès réseau à la base de Trivy depuis
  le poste du fondateur ; la comparaison (`make suivi-cve`) est hors ligne. Proposition : job CI mensuel
  programmé qui construit, audite et publie `suivi-cve.md` comme artefact. À faire (CI, décision du fondateur).
- **Battement quotidien du scheduler** (plus haut) : toujours à faire ; l'exercice mensuel planifié ne
  s'exécute pas si le scheduler est arrêté (le compte rendu du mois manquant le montre à la routine).

