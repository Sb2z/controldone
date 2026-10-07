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
  dossiers de la fiche via `dossiers_page`. **Fait (bloc I3, D-4301)** : 5 000 dossiers, `/espace` 3,6 s → 0,25 s,
  fiche 1,4 s → 0,28 s.
- **Index des listes en SQL.** Constat : les requêtes de D-3801 s'appuient sur les index existants (`tenant_id`,
  `constats.dossier_id`, `ecarts.constat_id`) ; mesuré suffisant à 5 000 dossiers. Proposition : au-delà (50 000),
  index `constats(tenant_id, dossier_id, dossier_version)` comme étape de `storage/migrations.py`. À faire si besoin.
- **Recherche sans accents en base.** Constat : les références et clés sont comparées en minuscules ASCII
  (`lower`) ; une clé accentuée ne serait trouvée qu'avec ses accents (aucune n'en a : identifiants douaniers et
  numéros). Proposition : colonne normalisée si des clés accentuées apparaissent. À faire (faible).
- **Préférence de langue par compte.** Constat : la langue est un cookie du navigateur (`cd_langue`, D-3803), pas
  une préférence du compte (aucune colonne `users.langue`). Proposition : colonne par étape de migration, lue à la
  connexion. **Fait (D-4302)** : migration 5, page « Mon compte ».
- **Libellés des contrôles et textes des constats en français.** Décision 7B : restent en français. Constat : en anglais, les textes des constats
  (libellé, raisons, prochaine action, nom du contrôle), rapports et relevés restent en français, marqués
  `lang="fr"` (garde-fous écrits pour le français, SPEC §3). Proposition : version anglaise validée des gabarits
  de texte, avec une liste de formulations interdites anglaise, avant de les traduire. À décider (fondateur).
- **Messages d'erreur des services.** Constat : les messages de `RequeteInvalide` levés hors du web (saisie de
  montants, transitions d'écart, facturation) restent en français dans l'interface anglaise, sauf s'ils figurent
  au catalogue. Proposition : codes d'erreur + libellés côté web. **Fait (bloc I4, D-4801)** : catalogue des
  messages des services (clé : texte français de référence, messages paramétrés reconnus), sans toucher aux services.
- **Documentation de l'API (`/api/v1/docs`)** : en français seulement. **Fait (D-4802)** ; `openapi.json` inchangé.

# Bloc I3 — interface (octobre 2026)

- **Configuration des notifications vue par le web.** Constat : la page lit `CONTROLDONE_NOTIF_*` dans le processus
  web ; les envois partent du planificateur. Proposition : le planificateur inscrit un battement (date, canaux
  actifs) que la page affiche. À faire (faible).
- **Préférence de langue d'un autre navigateur déjà connecté.** Constat : la langue du compte est reposée à la
  connexion seulement ; une session ouverte ailleurs garde son cookie jusqu'à la reconnexion. Faible.
- **Fiche client : actions sortantes complètes.** Constat : `FileSortante.lister(tenant_id)` lit toutes les actions
  du client puis en garde 30. Impact : faible aujourd'hui. Proposition : limite en SQL. À faire (faible).
- **Pages encore en Python** : API `/api/v1` et MCP (`lister_dossiers` complet). À mesurer.
- **Migration 5 et blocs parallèles.** La colonne `users.langue` est l'étape 5 : un autre bloc qui ajoute une étape
  en parallèle doit prendre le numéro suivant (jamais réordonner). À vérifier à l'intégration.

# Bloc I4 — interface (octobre 2026)

- **Messages reconnus par leur texte.** Constat : la traduction des messages des services repose sur le texte
  français exact (D-4801) ; un service qui reformule un message le fait retomber en français dans l'interface
  anglaise. Garde : le test relève par AST les messages levés et exige leur reconnaissance (CI rouge si oubli).
  Proposition, si les messages se multiplient : codes d'erreur portés par l'exception (`RequeteInvalide(code=…)`),
  le texte français restant celui des journaux. À décider (faible).
- **Erreurs de l'API REST et du serveur MCP en français.** Constat : `{"detail": …}` reste en français (contrat
  JSON, D-4801). Proposition : champ `code` stable à côté de `detail` pour les intégrateurs anglophones. À faire si
  un client le demande.
- **Messages tronqués.** Constat : `routes_admin`/`routes_finances` tronquent `str(exc)` (250–300 caractères)
  avant traduction ; un message plus long ne serait pas reconnu et resterait en français. Aucun message actuel ne
  dépasse 130 caractères. Faible.
- **Données des documents dans un texte alternatif.** Constat : « Page 1 of Déclaration en douane n° … » mêle
  anglais et libellé de document français (un attribut ne peut porter deux langues). Faible (lecteurs d'écran).
- **Repérage du français limité à une liste de mots.** Constat : `tests/web/francais_visible.py` signale les mots
  outils, mots d'interface et accents français ; une phrase française sans accent ni mot de la liste passerait.
  Proposition : compléter la liste au fil des revues. Faible.

# Refonte visuelle et textes (octobre 2026, D-5201 à D-5206)

- **Surlignage de la preuve sur la vignette (RECHERCHE §4.7, motif 5).** Non fait : il faut la boîte de la valeur
  lue dans la page (déjà dessinée dans l'extrait) côté vignette du document. À faire avec l'équipe moteur.
- **Progression réelle de l'envoi.** Le bouton annonce l'envoi sans barre : une barre fidèle demanderait un envoi
  par `XMLHttpRequest` (événements `upload.progress`) sans perdre le message de confirmation. À étudier.
- **Valeur par dossier dans la liste des dossiers.** La fiche du dossier affiche avoirs reçus et reste ; la liste
  pourrait ajouter une colonne « avoirs reçus » (agrégat SQL sur `ecarts`). À faire si les clients le demandent.
- **Textes du fondateur.** Les pages du fondateur ont reçu une passe (incises, états vides) mais pas une réécriture
  complète ; les libellés de graphiques (`web/graphes.py`) gardent « montant recouvrable certain ». À reprendre.
- **Libellés des rapports.** Les objets de rapport produits par le moteur contiennent encore « — » (hors périmètre de
  l'interface, `rapport/`).
