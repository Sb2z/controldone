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
  nombre de constats) sur `dossiers`, puis filtres SQL. À faire si un client dépasse ~5 000 dossiers.
- **Retour après action dans une liste filtrée.** Constat : `retour_sur` (`web/rendu.py`) refuse `%` et `+` ; après
  « Valider » sur une file filtrée avec un texte encodé, on revient à la file non filtrée. Impact : confort.
  Proposition : accepter une requête encodée validée par `urllib.parse` (chemin interne seulement). À faire.
- **Colonne « Créée » des tâches.** Constat : `admin/jobs.html.j2` affiche `run_after` (prochain essai) sous le
  titre « Créée », alors que le tri est sur `cree_le` ; `JobInfo` n'expose pas `cree_le`. Proposition : ajouter
  `cree_le` à `JobInfo` et afficher les deux. À faire.
