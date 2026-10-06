# Constats transverses (orchestrateur)

- **Dépôt Git lourd (609 Mo).** Les corpus de banc sont versionnés, alors qu'ils sont reproductibles à l'octet près
  par leur graine. Proposition : ne plus versionner les prochains corpus, les régénérer par `make` ; nettoyer
  l'historique seulement avec l'accord du fondateur (réécriture irréversible). À faire.
- **CI en déclenchement manuel** (`.github/workflows/ci.yml`) : activer sur push/PR demande l'accord du fondateur
  (minutes GitHub). À faire, sur décision.
- **Lecture par modèle de langage inactive** (pas de clé d'API) : c'est la réponse prévue aux mises en page vraiment
  inconnues. Sur décision du fondateur.
- **Serveur de démo** : la limitation de débit des connexions est en mémoire ; après une vingtaine de connexions
  de test, il faut redémarrer le serveur (vu pendant les captures de l'interface). Traité par le bloc sécurité.
