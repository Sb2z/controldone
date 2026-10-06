# Bloc E — interface : améliorations repérées

- **Index pour le journal et les tâches.** Constat : filtres du journal (`action`, `actor`, période) et tri des
  tâches par `cree_le` sans index dédié (`storage/models.py`). Impact : nul aujourd'hui (journal parcouru par clé
  primaire, tâches terminées purgées à 30 jours), balayage complet au-delà de quelques centaines de milliers
  d'entrées. Proposition : index `audit_log(action, id)` et `jobs(cree_le)`, créés aussi sur les bases existantes —
  il faut d'abord un mécanisme de migration (`creer_schema` ne crée pas les index d'une table existante). À faire.
- **Progression fine du pipeline.** Constat : `controldone.pipeline.traiter_lot` est un appel unique (souvent dans un
  processus fils) ; le suivi ne distingue que « lecture » (pipeline entier) et « contrôles » (enregistrement)
  (`jobs/handlers.py`, D-3402). Impact : sur un gros dépôt, l'étape « lecture » dure presque tout le traitement.
  Proposition : rappel `progression(etape, n, total)` dans `OptionsPipeline`, relayé par le fils au parent par le
  tube existant, puis `JobContext.etape`. À faire (équipe moteur).
- **Trusted Types désormais possible.** Constat : le filtrage en direct n'utilise plus `DOMParser` mais
  `XMLHttpRequest` `responseType="document"` (aucune chaîne HTML vers un puits) ; essai réel avec
  `require-trusted-types-for 'script'; trusted-types 'none'` : 0 erreur de console. Impact : D-3204 écartait
  Trusted Types à cause de D-3401. Proposition : l'activer dans `web/securite.py` (bloc sécurité). À faire.
- **Filtres des listes calculés en Python.** Constat : dossiers, avoirs et file de validation lisent toutes les
  lignes du client puis filtrent (`web/listes_vues.py`). Impact : acceptable jusqu'à quelques milliers de dossiers
  par client ; `lister_dossiers` lit aussi tous les constats. Proposition : colonnes dénormalisées (montant certain,
  nombre de constats) sur `dossiers`, puis filtres SQL. **Fait (bloc I, D-3801)** : filtres, tri et pagination en
  SQL sans colonne dénormalisée (agrégats des constats en sous-requête) ; 5 000 dossiers fictifs : 1,2 s → 0,25 s.
- **Retour après action dans une liste filtrée.** Constat : `retour_sur` (`web/rendu.py`) refuse `%` et `+` ; après
  « Valider » sur une file filtrée avec un texte encodé, on revient à la file non filtrée. Impact : confort.
  Proposition : accepter une requête encodée validée par `urllib.parse` (chemin interne seulement). **Fait (D-3802).**
- **Colonne « Créée » des tâches.** Constat : `admin/jobs.html.j2` affiche `run_after` (prochain essai) sous le
  titre « Créée », alors que le tri est sur `cree_le` ; `JobInfo` n'expose pas `cree_le`. Proposition : ajouter
  `cree_le` à `JobInfo` et afficher les deux. **Fait** (colonnes « Créée » et « Prochain essai »).

# Bloc I — interface (octobre 2026)

- **Tableau de bord client et fiche client du fondateur encore en Python.** Constat : `/espace` (indicateurs,
  `lister_dossiers` + `reclamations.registre` complets) et `/admin/clients/{id}` (`services.admin.fiche_client`)
  relisent tous les dossiers et constats ; mesure non faite sur ces pages, les listes filtrées (D-3801) passaient de
  1,2 s à 0,25 s sur 5 000 dossiers. Proposition : indicateurs agrégés en SQL (`storage/listes_sql.py`), liste des
  dossiers de la fiche via `dossiers_page`. À faire.
- **Index des listes en SQL.** Constat : les requêtes de D-3801 s'appuient sur les index existants (`tenant_id`,
  `constats.dossier_id`, `ecarts.constat_id`) ; mesuré suffisant à 5 000 dossiers. Proposition : au-delà (50 000),
  index `constats(tenant_id, dossier_id, dossier_version)` comme étape de `storage/migrations.py`. À faire si besoin.
- **Recherche sans accents en base.** Constat : les références et clés sont comparées en minuscules ASCII
  (`lower`) ; une clé accentuée ne serait trouvée qu'avec ses accents (aucune n'en a : identifiants douaniers et
  numéros). Proposition : colonne normalisée si des clés accentuées apparaissent. À faire (faible).
- **Préférence de langue par compte.** Constat : la langue est un cookie du navigateur (`cd_langue`, D-3803), pas
  une préférence du compte (aucune colonne `users.langue`). Proposition : colonne par étape de migration, lue à la
  connexion. À faire (faible).
- **Libellés des contrôles et textes des constats en français.** Constat : en anglais, les textes des constats
  (libellé, raisons, prochaine action, nom du contrôle), rapports et relevés restent en français, marqués
  `lang="fr"` (garde-fous écrits pour le français, SPEC §3). Proposition : version anglaise validée des gabarits
  de texte, avec une liste de formulations interdites anglaise, avant de les traduire. À décider (fondateur).
- **Messages d'erreur des services.** Constat : les messages de `RequeteInvalide` levés hors du web (saisie de
  montants, transitions d'écart, facturation) restent en français dans l'interface anglaise, sauf s'ils figurent
  au catalogue. Proposition : codes d'erreur + libellés côté web. À faire (faible).
- **Documentation de l'API (`/api/v1/docs`)** : en français seulement. À faire (faible).
