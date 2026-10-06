# Backlog — bloc sécurité (octobre 2026)

Constats repérés pendant le bloc C (`docs/REVUE_SECURITE_2.md`) et non traités, ou traités ici en passant.

- **Trusted Types.** Imposés (`trusted-types 'none'`, D-3204) après le passage du filtrage en direct à
  `XMLHttpRequest` (`responseType = "document"`). Non vérifié ici dans un navigateur (aucun navigateur dans
  l'environnement du bloc sécurité) : l'essai réel est celui du bloc interface (0 erreur). Proposition : ajouter un
  parcours Playwright sous cette CSP à la CI. **Fait / vérification navigateur à faire.**
- **HSTS `preload`.** `max-age=63072000; includeSubDomains` posé par l'application et Caddy, sans `preload`.
  Impact : la toute première visite reste exposée à une rétrogradation HTTP. Proposition : décision du fondateur
  (l'inscription sur la liste de préchargement engage tout le domaine et se retire lentement). **À décider.**
- **Image Docker non auditée.** **Fait (bloc S, D-3609)** : `make audit-image` (Trivy) ; bloque sur une
  vulnérabilité grave corrigeable. Reste : l'ajouter à la CI manuelle (Docker requis).
- **`requirements.lock` sans empreintes.** **Fait (D-3609)** : empreintes, `make lock`, `--require-hashes` et
  backend de construction figé dans le Dockerfile (image construite et vérifiée le 6 octobre).
- **Paquets installés hors du fichier figé.** **Fait (D-3609)** : `alembic`, `mako` retirés (Alembic écarté,
  D-3503) ; `python-dateutil`, `six` sont des dépendances de `pg8000` (extra `postgres`, D-3501), hors de l'image.
- **Rendu OCR des PDF sans plafond de pixels.** `ingest/pages.py` rend chaque page à 300 dpi dans le processus isolé
  sans borne de taille ; une page de 5 m × 5 m échoue sous `RLIMIT_AS` (page illisible) après une grosse allocation.
  Proposition : plafonner l'échelle comme les vignettes (`services.vignettes.MAX_PIXELS`), au-delà de A0. Sans effet
  sur le banc. **Fait (D-3606)** : 40 Mpx (A2 à 300 dpi reste intact), `VERSION_PAGES` inchangée.
- **ODS : `content.xml` lu en entier.** Borné par les limites de conteneur (1 Go décompressé, taux 100) et par le
  processus isolé ; un plafond propre (ex. 200 Mo) donnerait un motif lisible plutôt qu'un dépassement de mémoire.
  **À faire (faible).**
- **Révocations en mémoire non bornées.** `GestionnaireSessions._revoquees` (copie locale) grossit d'un `sid` par
  déconnexion pendant la vie du processus. Impact : quelques Mo après des centaines de milliers de déconnexions.
  Proposition : borne LRU (la base fait foi). **Fait (D-3604)** : 10 000 entrées, expirées d'abord.
- **Cookies secondaires sans préfixe `__Host-`.** `cd_2fa` et `cd_flash` restent sans préfixe en production
  (`HttpOnly`, `Secure`, `SameSite` posés). Proposition : `__Host-cd_2fa`, `__Host-cd_flash` en `prod`. **Fait
  (D-3604).**
- **Sessions actives.** Pas de liste des sessions d'un compte ni de bouton « fermer mes autres sessions » (la
  révocation en base le permet désormais). **API faite (D-3603, voir « Sessions actives : mode d'emploi » plus
  bas) ; page à faire (interface).**
- **PostgreSQL non testé pour le débit et les révocations.** Le chemin `SELECT … FOR UPDATE` + nouvel essai sur
  conflit est écrit mais la suite tourne sous SQLite. **Fait (D-3610)** : `make test-pg-securite` (6 tests verts) ;
  reste à l'ajouter à la CI manuelle.
- **Taille du corps de `/csp-rapport` côté Caddy.** L'application lit au plus 8 Ko en flux ; Caddy accepte 60 Mo sur
  ce chemin. **Fait (D-3608)** : 16 Kio ; « autres » ramené de 60 Mo à 4 Mio (l'application refuse à 2 Mio).
- **Points ouverts de la première revue** : RS-16 (mode `dev` par défaut), RS-18 (URL Stripe depuis `Host`), RS-19
  (veille sans plafond de téléchargement), RS-20 (vignettes dans le processus web), RS-21 (base SQLite en clair).
  RS-17 est **fait** (D-3202). **Faits (bloc S)** : RS-16 (D-3601), RS-18 (D-3602), RS-19 (10 Mo lus en flux),
  RS-20 (D-3607), RS-21 (constat et alerte au démarrage, D-3605 ; le chiffrement reste celui du volume LUKS).
- **Fait pendant le bloc** : déduction XML quadratique (REV2-01), images multi-cadres et agrandissement (REV2-03),
  `csv.excel` modifié pour tout le processus par une grille CSV (REV2-04), `?page=²` en erreur 500 (REV2-05).

## Bloc S (suivi des revues, octobre 2026)

### Sessions actives : mode d'emploi pour l'interface (D-3603)

Tout passe par `request.app.state.securite` (`EtatSecurite`) et sa propriété `sessions` (`GestionnaireSessions`) ;
la session de la requête est `request.state.session` (`DonneesSession` : `sid`, `user_id`…).

```python
etat = request.app.state.securite
s = request.state.session                      # après acteur_de(request)
liste = etat.sessions.sessions_actives(s.user_id, sid_courant=s.sid)
# -> list[storage.securite.SessionActive] : sid, debut, vu (époque, secondes), appareil (« Firefox · Linux »),
#    reseau (« 203.0.113.0/24 », chaîne vide si inconnue), courante (bool) ; la plus récemment active d'abord.
n = etat.sessions.fermer_autres_sessions(s.user_id, s.sid)   # POST (CSRF), renvoie le nombre fermé
ok = etat.sessions.fermer_session(s.user_id, sid_vise)       # POST (CSRF) ; False si ce sid n'est pas à ce compte
```

- Ne jamais afficher le `sid` en entier dans la page (c'est l'identifiant du jeton) : pour le bouton « fermer
  cette session », passer un identifiant dérivé, ex. `hashlib.sha256(sid.encode()).hexdigest()[:16]`, et
  retrouver la session dans `sessions_actives` côté serveur.
- `vu` est la dernière **émission** du jeton (rotation toutes les 15 min) : afficher « active il y a moins de
  15 min » plutôt qu'une heure exacte. `debut` : heure de connexion (Europe/Paris).
- Les sessions ouvertes avant cette version ne sont pas listées (elles expirent au plus tard 8 h après).
- Les nouvelles connexions doivent passer par `etat.ouvrir_session(request, reponse, acteur, deux_facteurs=…)`
  (c'est le cas de `/connexion`, `/connexion/totp` et du changement de mot de passe).

### Constats du bloc S, hors périmètre

- **Paquets Debian graves sans correctif dans l'image** (Trivy, 6 octobre) : 77 HIGH/CRITICAL non corrigés par
  Debian 13.7, dont libxml2 (CRITICAL), libtiff, expat, curl et **libtesseract5** (6 HIGH). Tesseract et libtiff
  lisent des fichiers hostiles, mais dans le processus isolé (sans secrets, mémoire et délai bornés). Proposition :
  relancer `make audit-image` à chaque construction ; reconstruire dès qu'un correctif paraît (l'audit bloque
  alors). **À suivre.**
- **PostgreSQL en production sans pilote dans l'image** : `pg8000` est un extra (`postgres`) hors de
  `requirements.lock` ; une image pointée sur PostgreSQL échouerait au démarrage. Proposition : si PostgreSQL est
  retenu pour la production, l'ajouter à `requirements.lock` puis `make lock` (empreintes) et `make audit`.
  **À décider (bloc P).**
- **Libellé de l'alerte `volume_non_chiffre`** (D-3605) dans l'écran Alertes. **À faire (interface).**
- **`docs/DEPLOIEMENT.md`** : nouvelles variables `CONTROLDONE_URL_PUBLIQUE`, `CONTROLDONE_HOTES_AUTORISES`,
  `CONTROLDONE_VOLUME_CHIFFRE`, `CONTROLDONE_DEV_RESEAU` documentées dans `deploy/.env.prod.example` et D-3601 à
  D-3605 ; `make audit-image` et `make lock` à citer dans la procédure de mise à jour. **À faire (doc).**
- **Rendu des vignettes** : chaque vignette coûte un processus (≈ 50 ms) ; une page qui en affiche beaucoup d'un
  coup pourrait les grouper en un seul appel isolé. **À mesurer (faible).**
