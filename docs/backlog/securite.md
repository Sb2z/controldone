# Backlog — bloc sécurité (octobre 2026)

Constats repérés pendant le bloc C (`docs/REVUE_SECURITE_2.md`) et non traités, ou traités ici en passant.

- **Trusted Types.** Imposés (`trusted-types 'none'`, D-3204) après le passage du filtrage en direct à
  `XMLHttpRequest` (`responseType = "document"`). Non vérifié ici dans un navigateur (aucun navigateur dans
  l'environnement du bloc sécurité) : l'essai réel est celui du bloc interface (0 erreur). Proposition : ajouter un
  parcours Playwright sous cette CSP à la CI. **Fait / vérification navigateur à faire.**
- **HSTS `preload`.** `max-age=63072000; includeSubDomains` posé par l'application et Caddy, sans `preload`.
  Impact : la toute première visite reste exposée à une rétrogradation HTTP. Proposition : décision du fondateur
  (l'inscription sur la liste de préchargement engage tout le domaine et se retire lentement). **À décider.**
- **Image Docker non auditée.** `make audit` couvre les paquets Python et les fichiers servis, pas les paquets
  Debian de `python:3.11-slim` ni Tesseract. Proposition : `trivy image controldone:<version>` (ou grype) dans la CI
  manuelle, après `make docker-build`. **À faire.**
- **`requirements.lock` sans empreintes.** `pip-audit` le signale ; une dépendance republiée sous la même version
  serait installée. Proposition : `uv pip compile --generate-hashes` et `pip install --require-hashes` dans le
  Dockerfile. **À faire.**
- **Paquets installés hors du fichier figé.** `alembic`, `mako`, `python-dateutil`, `six` sont présents dans `.venv`
  sans être dans `requirements.lock` ni `pyproject.toml` (aucun import dans `src/`). Impact : si un bloc s'en sert
  (migrations), l'image ne les aura pas. Proposition : les figer s'ils sont adoptés, sinon les retirer. **À faire
  (orchestrateur).**
- **Rendu OCR des PDF sans plafond de pixels.** `ingest/pages.py` rend chaque page à 300 dpi dans le processus isolé
  sans borne de taille ; une page de 5 m × 5 m échoue sous `RLIMIT_AS` (page illisible) après une grosse allocation.
  Proposition : plafonner l'échelle comme les vignettes (`services.vignettes.MAX_PIXELS`), au-delà de A0. Sans effet
  sur le banc. **À faire (bloc moteur, avec mesure).**
- **ODS : `content.xml` lu en entier.** Borné par les limites de conteneur (1 Go décompressé, taux 100) et par le
  processus isolé ; un plafond propre (ex. 200 Mo) donnerait un motif lisible plutôt qu'un dépassement de mémoire.
  **À faire (faible).**
- **Révocations en mémoire non bornées.** `GestionnaireSessions._revoquees` (copie locale) grossit d'un `sid` par
  déconnexion pendant la vie du processus. Impact : quelques Mo après des centaines de milliers de déconnexions.
  Proposition : borne LRU (la base fait foi). **À faire (faible).**
- **Cookies secondaires sans préfixe `__Host-`.** `cd_2fa` et `cd_flash` restent sans préfixe en production
  (`HttpOnly`, `Secure`, `SameSite` posés). Proposition : `__Host-cd_2fa`, `__Host-cd_flash` en `prod`. **À faire
  (faible).**
- **Sessions actives.** Pas de liste des sessions d'un compte ni de bouton « fermer mes autres sessions » (la
  révocation en base le permet désormais). **À faire (interface).**
- **PostgreSQL non testé pour le débit et les révocations.** Le chemin `SELECT … FOR UPDATE` + nouvel essai sur
  conflit est écrit mais la suite tourne sous SQLite. Proposition : job CI PostgreSQL. **À faire.**
- **Taille du corps de `/csp-rapport` côté Caddy.** L'application lit au plus 8 Ko en flux ; Caddy accepte 60 Mo sur
  ce chemin. Proposition : `request_body` dédié de 16 Ko. **À faire (faible).**
- **Points ouverts de la première revue** : RS-16 (mode `dev` par défaut), RS-18 (URL Stripe depuis `Host`), RS-19
  (veille sans plafond de téléchargement), RS-20 (vignettes dans le processus web), RS-21 (base SQLite en clair).
  RS-17 est **fait** (D-3202). **À faire.**
- **Fait pendant le bloc** : déduction XML quadratique (REV2-01), images multi-cadres et agrandissement (REV2-03),
  `csv.excel` modifié pour tout le processus par une grille CSV (REV2-04), `?page=²` en erreur 500 (REV2-05).
