# ControlDOne v2 — Revue de sécurité indépendante

Date : 2 octobre 2026. Relecteur : agent de revue indépendant (n'a écrit aucune partie du code revu).
Périmètre de code : `src/controldone/` (version 2.0.0), tests `tests/`. Les dépôts historiques n'ont pas été
ouverts. Aucune donnée réelle n'a été utilisée : toutes les preuves tournent sur la base de démonstration fictive.

Les correctifs sont **non validés en git** (aucun commit), conformément à la consigne.

---

## 1. Périmètre

| Domaine | Composants examinés |
|---|---|
| Cloisonnement et contrôle d'accès | `storage/scope.py`, `storage/garde.py`, `auth/` (rôles, sessions, TOTP, clés d'API, débit), `web/` (toutes les routes `/espace`, `/admin`, `/admin/finances`, `/connexion`, `/compte`), `api/routes.py`, `mcp_server.py`, `jobs/` (handlers et worker), `agents/` (outils, liste blanche), `services/` (lecture, dépôt, publication, réclamations, validation), `outbox/` |
| Injections | SQL (requêtes brutes), traversée de chemin (coffre, dépôts, ZIP, téléchargements, worker, restauration), XML (XXE, expansion d'entités) dans `ingest/structure.py`, `ingest/pages.py`, `facturation/avant_paiement.py` et la bibliothèque `factur-x`, formules de tableur (CSV, XLSX), HTML/JS (Jinja, rapport HTML, PDF reportlab), en-têtes (pièces jointes, sorties), injection de consignes vers le modèle de langage et les agents, SSRF de la veille, désérialisation, sous-processus OCR, bombes ZIP/PDF/images |
| Secrets et configuration | dépôt (recherche de clés), `.env.example`, mode `dev`/`prod`, clé maîtresse, cookies, HSTS/CSP, webhook Stripe, clés Stripe, TOTP, Argon2, clés d'API, limitation de débit, chaîne d'audit |
| Dépendances | versions installées dans `.venv`, `requirements.lock`, licences |
| Protection des données | journaux, purge de conservation, effacement RGPD, export de restitution, chiffrement au repos (coffre, base, caches) |

## 2. Méthode

1. Lecture des documents de conception (`SECURITY.md`, `ARCHITECTURE.md`, `API.md`, `MCP.md`, `EXPLOITATION.md`,
   `AGENTS.md`, `FACTURATION.md`), puis lecture adverse du code de chaque point d'entrée (web, API, MCP, jobs,
   agents, connecteurs, webhooks) jusqu'à la couche d'accès.
2. Pour chaque soupçon : **preuve exécutable d'abord** (test qui échoue), puis correctif minimal, puis test vert.
   Toutes les preuves sont dans `tests/security/test_revue_securite.py` (39 tests ; `tests/security/conftest.py`
   réutilise le monde de démonstration des tests web).
3. Balayages systématiques : toutes les routes POST de l'interface sans jeton CSRF ou avec un faux jeton (toutes
   répondent 403), clé d'API d'un client sur tous les identifiants d'un autre client (404 indistinct), lecteur
   sur toutes les écritures (403), jeton de session forgé ou sans second facteur (refusé), recherche de secrets
   dans les sources, couverture de l'effacement par rapport à toutes les tables cloisonnées.
4. Essais directs : XXE et « milliard de rires » sur `lxml` 6.1 (analyseur durci et analyseur par défaut utilisé
   par `factur-x`), limites de décompression de `pypdf` 6.19 (75 Mo par flux) et de Pillow.
5. Audit des dépendances par `pip-audit` 2.x (base PyPI/OSV, réseau disponible) sur les paquets réellement
   installés (`uv pip freeze` du `.venv`) et sur `requirements.lock`.
6. Suite complète (`pytest -q`) et `ruff` sur les fichiers modifiés.

## 3. Constats

Sévérité : **Élevée** (exploitable à distance, effet sur l'argent ou sur les données de plusieurs clients),
**Moyenne** (exploitable sous condition réaliste), **Faible** (défense en profondeur, condition forte),
**Info**. Statut : **corrigé** (correctif + test) ou **ouvert** (risque accepté ou action d'exploitation).

| Id | Sév. | Composant | Description | Preuve | Statut | Correctif |
|---|---|---|---|---|---|---|
| RS-01 | Élevée | `facturation/paiements.py`, `POST /webhooks/stripe` | Sans `STRIPE_SECRET_KEY` (cas par défaut, bouchon) et sans `STRIPE_WEBHOOK_SECRET`, le point d'entrée **public** vérifiait les signatures avec une constante écrite dans le code (`whsec_bouchon_local_controldone`). N'importe qui pouvait forger un `checkout.session.completed` / `invoice.paid` accepté : encaissement fictif rattaché à une facture, abonnement marqué actif, brouillons de facture créés, `client_id` arbitraire. | `test_rs01_*` (signature avec l'ancienne constante acceptée avant correctif ; le test de recherche de secrets la trouvait aussi) | corrigé | Secret du bouchon aléatoire par instance (`secrets.token_urlsafe(32)`), plus aucune constante ; le bouchon signe et vérifie avec la même instance (service mis en cache sur la plateforme). |
| RS-02 | Moyenne | `mcp_server.py` (`deposer_dossier(chemin=…)`) | Sans `CONTROLDONE_MCP_RACINE` (variable « facultative »), l'outil lisait **n'importe quel fichier** accessible au processus MCP — qui tourne sur la machine du service avec la base et la clé maîtresse — et le versait dans l'espace du client de la clé (puis téléchargeable par `/espace/fichiers/…`) : dépôts surveillés d'un autre client, traces d'envoi en clair, etc. Un assistant piloté par injection de consignes (texte d'un document renvoyé par `lire_ecarts`) pouvait déclencher l'appel. | `test_rs02_mcp_depot_par_chemin_exige_un_repertoire_autorise` | corrigé | Dépôt par chemin refusé tant que `CONTROLDONE_MCP_RACINE` n'est pas défini (base64 toujours possible) ; `docs/MCP.md` mis à jour ; test MCP existant adapté. |
| RS-03 | Moyenne | `ingest/decoupage.py`, `ingest/pages.py` (`CachePagesDisque`) | Si `CONTROLDONE_PAGES_CACHE_DIR` est défini (proposé par `deploy/.env.prod.example`), le **texte OCR de chaque page de chaque client** est écrit **en clair** sur disque, indexé par empreinte (sans client), hors coffre chiffré, hors purge de conservation et hors effacement RGPD, avec les droits par défaut (0644). | `test_rs03_cache_des_pages_ignore_en_production`, `test_rs03_cache_des_pages_prive` | corrigé | Variable ignorée quand `CONTROLDONE_ENV=prod` (banc et développement seulement) ; fichiers 0600, répertoires 0700. |
| RS-04 | Moyenne | `services/vignettes.py` (`/espace/documents/…/pages/N.png`, vignettes, extraits de preuve) | Rendu des pages **dans le processus web** sans borne de taille : une page PDF de 1 pt × 5 m (ou une image PNG 1 × 30 000 px, sous le seuil « bombe » de Pillow) réclamait un bitmap de 1 240 × 17,8 M pixels (≈ 66 Go) : déni de service du service web pour tous les clients, déclenchable par n'importe quel client qui dépose un fichier. | `test_rs04_rendu_pdf_borne_en_pixels`, `test_rs04_rendu_image_bornee_en_pixels` (espions sur `PdfPage.render` / `Image.resize`) | corrigé | Échelle plafonnée (`MAX_PIXELS` ≈ 5,4 Mpx, marge d'arrondi) pour PDF et images. |
| RS-05 | Faible | `services/lecture.py` (`lire_lot`), `GET /api/v1/lots/{id}`, MCP `lire_lot` | Le résumé du lot renvoyé au client contenait `constats` (nombre de constats **non publiés**, avant validation du fondateur) et `llm` : fuite contraire à la règle de publication §4. | `test_rs05_resume_du_lot_sans_compte_de_constats_non_publies` | corrigé | Liste blanche des clés du résumé pour les rôles client (`CLES_RESUME_CLIENT`) ; le fondateur garde le résumé complet. |
| RS-06 | Faible | `storage/retention.py` (`exporter_client`, rôle `client_admin`) | L'export de restitution d'un `client_admin` contenait **toutes** les actions sortantes du client (brouillons, refus et motifs internes, corrections, statuts de litige proposés), alors que l'espace client ne montre que les actions mises à disposition. | `test_rs06_export_client_admin_sans_actions_non_mises_a_disposition` | corrigé | Rôle client : seules les actions `envoye` ; fondateur : inchangé. |
| RS-07 | Faible | `storage/retention.py` (`supprimer_client`) | L'effacement RGPD laissait les traces **en clair** de l'expéditeur fichier (`<data_dir>/outbox_envoyee/<kind>/<id>.json` : corps des courriels, dossiers de réclamation, questions du client). | `test_rs07_effacement_client_supprime_ses_traces_d_envoi` | corrigé | Suppression des traces du client (paramètre `dossier_sorties`, défaut `<data_dir>/outbox_envoyee`) ; compteur `traces_envoi` ; `docs/EXPLOITATION.md` mis à jour. |
| RS-08 | Faible | `services/reclamations.py` (`enregistrer_avoir`) ; API, web, MCP | Montant d'avoir `NaN`, `sNaN`, `Infinity` ou `1E+999999` : exception non gérée (`InvalidOperation`) → erreur 500 au lieu d'un refus. | `test_rs08_*` (5 valeurs) | corrigé | Montant fini et ≤ 1 milliard exigé, sinon `RequeteInvalide` (400). |
| RS-09 | Faible | `web/securite.py` (`acteur_de`), sessions | Un jeton de session signé restait valable jusqu'à 8 h après la **désactivation du compte** (ou le retrait du rôle fondateur) : le fondateur n'était jamais revérifié en base. | `test_rs09_compte_client_desactive_perd_sa_session`, `test_rs09_fondateur_desactive_perd_sa_session` | corrigé | Compte relu en base à chaque requête de l'interface (inactif, supprimé ou rôle fondateur changé → session révoquée, redirection vers la connexion) ; `storage.comptes.desactiver_utilisateur` (fondateur, journalisé). |
| RS-10 | Faible | `connecteurs/imap.py` | `secret_env` pouvait nommer **n'importe quelle** variable (`CONTROLDONE_MASTER_KEY`, `STRIPE_SECRET_KEY`…), envoyée comme mot de passe au serveur IMAP configuré. Condition : modifier les réglages d'un client (fondateur). | `test_rs10_imap_secret_limite_aux_variables_dediees` | corrigé | Seules les variables `CONTROLDONE_IMAP_[A-Z0-9_]+` ; une configuration refusée n'interrompt plus le relevé des autres clients. |
| RS-11 | Faible | `rapport/export.py` (`findings.xlsx`) | Les chaînes lues dans les documents ou les noms de fichiers déposés commençant par `=` étaient écrites comme **formules** par openpyxl (`=HYPERLINK(…)`, `=cmd|…`) : exécution dans le tableur du fondateur ou du destinataire du rapport. | `test_rs11_xlsx_neutralise_les_formules` | corrigé | `neutraliser_formules` : toute cellule typée formule redevient du texte (valeur affichée identique). L'export CSV des finances neutralisait déjà `= + - @`. |
| RS-12 | Faible | `ingest/structure.py` | Un nom de colonne CSV inconnu (texte du document) était écrit en clair dans les journaux (`colonne_inconnue … colonne=<texte>`), contrairement à la règle « aucun contenu de document dans les journaux ». | `test_rs12_colonne_csv_inconnue_non_journalisee` | corrigé | Longueur et empreinte SHA-256 tronquée seulement. |
| RS-13 | Moyenne | `extract/llm.py` | (a) Le rang `index` renvoyé par le modèle n'était pas borné : `champs.definir` complète la liste, un rang de 5 000 000 créait 5 000 001 lignes (mesuré), un rang de 10⁹ épuisait la mémoire du worker — déclenchable par un document piégé qui pousse le modèle à répondre ainsi. (b) Le texte du document pouvait **fermer** le bloc `</document_non_fiable>` et écrire hors du bloc de données. | `test_rs13_index_de_liste_demesure_ignore`, `test_rs13_le_document_ne_peut_pas_fermer_le_bloc_non_fiable` | corrigé | Rang > 999 ignoré (`INDEX_MAX`) ; balises du bloc neutralisées dans le texte des pages. Le schéma fermé, l'ancrage et le plafond de confiance des valeurs non ancrées étaient déjà en place. |
| RS-14 | Faible | `ingest/pages.py` (`_extraire_isole`) | Le processus isolé qui analyse les fichiers hostiles (pdfplumber, Tesseract, openpyxl) héritait de **tout** l'environnement : clé maîtresse, secrets Stripe, clé Anthropic, mots de passe IMAP, URL de base. Une faille d'analyseur y aurait exposé tous les secrets. | `test_rs14_processus_d_analyse_sans_secrets` | corrigé | Environnement filtré (`_environnement_sans_secrets`). |
| RS-15 | Info | `tests/platform/test_audit.py` | Le test « insertion dans la chaîne d'audit » était sans effet une fois sur 16 (`'f'||substr(prev_hash,2)` ne change rien si le haché commence déjà par `f`) : échec aléatoire observé pendant la revue. Le code de vérification est correct. | échec observé dans la suite complète | corrigé | Premier caractère toujours modifié. |
| RS-16 | Moyenne | Configuration (`storage/cles.py`, `CONTROLDONE_ENV`) | Le mode par défaut est `dev` (échec « ouvert ») : si `CONTROLDONE_ENV` est oublié en production, clé maîtresse générée sur le disque à côté des données, cookie sans `Secure` ni préfixe `__Host-`, pas de HSTS, cache de pages autorisé. | lecture du code | ouvert | Le modèle de déploiement (`deploy/.env.prod.example`) fixe `prod`. Recommandé : défaut `prod` hors du dépôt de développement, ou refus de démarrer `serve` sur une interface non locale en mode `dev`. |
| RS-17 | Faible | Sessions (`auth/jetons.py`) | Révocation en mémoire d'un seul processus ; un changement de mot de passe ne révoque pas les autres sessions ouvertes. | lecture du code (point ouvert déjà connu) | ouvert | Table de sessions (révocation persistante, « déconnecter partout » au changement de mot de passe). |
| RS-18 | Faible | `web/routes_finances.py` (`_url_base`) | L'URL de retour Stripe est construite avec l'en-tête `Host` de la requête (aucun `TrustedHostMiddleware`). Route réservée au fondateur : impact limité à un lien de paiement mal formé. | lecture du code | ouvert | Fixer l'URL publique par configuration (`CONTROLDONE_DOMAIN`) ou ajouter `TrustedHostMiddleware`. |
| RS-19 | Faible | `agents/veille_sources.py` | Téléchargement d'une source officielle sans borne de taille de réponse (le domaine est sur liste blanche HTTPS, redirections revérifiées, pas de suivi automatique). | lecture du code | ouvert | Lire en flux avec un plafond (ex. 10 Mo). |
| RS-20 | Faible | Rendu PDF/images dans le processus web (`pypdfium2`, Pillow) | Les vignettes sont rendues hors du processus isolé (taille désormais bornée, RS-04). Une faille mémoire de pdfium toucherait le processus web. | lecture du code | ouvert | Rendre les vignettes dans le processus isolé (ou à l'ingestion, stockées chiffrées dans le coffre). |
| RS-21 | Info | Base SQLite vivante | Métadonnées, valeurs extraites, constats et textes de libellés en clair dans `controldone.db` (coffre et sauvegardes chiffrés). | point ouvert déjà documenté | ouvert | Volume chiffré (LUKS, prévu par `deploy/`) ou PostgreSQL chiffré au repos. |

### Points vérifiés sans constat

- **Cloisonnement** : trois barrières (`TenantScope`, critère automatique `do_orm_execute`, contrôle au flush)
  conformes à `SECURITY.md` ; aucune requête SQL brute hors `BEGIN` (`exec_driver_sql`) et déclencheurs DDL ;
  `tenant_id` toujours pris de l'acteur (session, clé d'API, contexte de job ou d'agent), jamais d'un paramètre.
  Balayage : clé d'API du client B sur les lots, dossiers, constats, litiges et rapports du client A → 404
  `introuvable` identique à un identifiant inexistant ; un acteur client forgé avec un autre `tenant_id` est
  refusé (appartenance vérifiée en base). Les images de page, fichiers et pièces sont lus dans le coffre du
  client de la session (clé HKDF par client).
- **Rôles** : `client_lecteur` → 403 sur dépôt, réclamation, avoir ; un rôle client n'atteint aucune route
  `/admin` (404) ; constats non validés et résultats bruts jamais servis à un rôle client (API, MCP, web, agents).
- **Fondateur sans second facteur** : jeton de session non signé par le service ou sans drapeau « 2f » refusé ;
  TOTP RFC 6238 à comparaison constante, anti-rejeu par pas, débit limité ; secret TOTP chiffré.
- **CSRF** : 37 routes POST de l'interface (fondateur, client, finances, compte, connexion, déconnexion) → 403
  sans jeton ou avec un faux jeton ; jeton lié à la session ; l'API n'accepte que les clés (aucun cookie), le
  webhook est signé. **Redirections** : cibles fixes ou `retour_sur` (chemin interne seulement). **Fixation de
  session** : nouvel identifiant à la connexion.
- **XML** : analyseurs `lxml` durcis (`resolve_entities=False`, `no_network`, `load_dtd=False`, `huge_tree=False`)
  ; l'analyseur par défaut de `factur-x` sous lxml 6.1 ne résout pas les entités externes et libxml2 arrête
  l'expansion exponentielle (`test_xml_hostile_ni_xxe_ni_expansion`).
- **ZIP** : chemins absolus et `..`, liens symboliques, profondeur, nombre d'entrées, taux et taille décompressée
  contrôlés, lecture bornée en flux. **PDF** : `pypdf` 6.19 borne chaque flux à 75 Mo ; analyse dans un processus
  séparé (temps et mémoire bornés, `RLIMIT_AS`). **Sous-processus** : commande fixe (`python -m
  controldone.ingest._worker`), paramètres par l'entrée standard, aucun `shell=True`.
- **HTML/PDF** : Jinja à échappement automatique partout (aucun `|safe`, aucun `Markup`) ; rapport HTML servi en
  pièce jointe par l'API et sous CSP fermée (`default-src 'none'`) dans l'interface ; tout texte variable passé à
  `reportlab.Paragraph` est échappé ; noms de fichiers des en-têtes `Content-Disposition` assainis/encodés.
- **Désérialisation** : ni `pickle` ni `yaml.load` (seulement `yaml.safe_load`) ; aucun `eval`/`exec`.
- **Agents** : le modèle ne choisit aucun outil (code déterministe) ; liste blanche d'outils, paramètres validés,
  client fixé par le contexte ; reformulation rejetée si elle introduit un nombre, une référence ou une
  formulation interdite ; aucun outil n'écrit dans les constats. **Veille** : HTTPS 443 sur liste blanche,
  redirections revérifiées, pas d'identifiants dans l'URL.
- **Stripe** : `construct_event` (tolérance 300 s) ; clé `sk_live_` refusée hors `prod` + `STRIPE_LIVE_OK=1`.
- **Clés d'API** : 256 bits, SHA-256 seul stocké, comparaison constante, préfixe public, révocation vérifiée à
  chaque ouverture de périmètre. **Mots de passe** : Argon2id (paramètres par défaut d'argon2-cffi 25.1),
  12 caractères minimum, empreinte leurre pour un compte inconnu.
- **En-têtes** : CSP sans script en ligne, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`,
  `Cache-Control: no-store`, HSTS en HTTPS ; cookie `__Host-`, `Secure`, `HttpOnly`, `SameSite=Strict` en `prod`.
- **Secrets** : aucun secret dans le dépôt (`.env`, `.env.prod` ignorés ; modèles vides) ; test permanent
  `test_aucun_secret_dans_les_sources`. Coffre : fichiers 0600.
- **Effacement** : toutes les tables cloisonnées sont dans `MODELES_CLIENT` (test permanent). Les tables de
  facturation (factures émises, paiements) sont conservées volontairement (obligation légale, `FACTURATION.md`).

## 4. Audit des dépendances

- `pip-audit` (base PyPI/OSV) sur les **80** paquets du `.venv` (`uv pip freeze`) : **aucune vulnérabilité
  connue**. Même résultat sur les **73** paquets de `requirements.lock`.
- Versions notables : cryptography 50.0.2, lxml 6.1.3, pypdf 6.19.0, pypdfium2 5.13.0, Pillow 12.3.0,
  starlette 1.7.0, fastapi 0.142.2, python-multipart 0.0.32, jinja2 3.1.6, urllib3 2.8.0, PyJWT 2.15.1,
  anyio 4.15.1, stripe 16.0.0, mcp 2.2.0.
- Licences : toutes permissives (MIT, BSD, Apache-2.0, MPL-2.0 pour `certifi`, MIT-CMU pour Pillow), **aucune
  AGPL/GPL**. Exception à noter : `python-stdnum` 2.2 (dépendance de `factur-x`) est **LGPL-2.1+** — copyleft
  faible, compatible avec un usage par import non modifié ; à mentionner dans les notices de distribution.
  Tesseract (binaire système) est Apache-2.0.
- `uvicorn` et `python-multipart` sont utilisés à l'exécution mais absents de `dependencies` dans
  `pyproject.toml` (présents dans `requirements.lock`) : à ajouter pour une installation reproductible.

## 5. Risques restants et prochaines étapes recommandées

1. **RS-16** — rendre le mode `prod` impossible à oublier (défaut strict, ou refus de servir hors `127.0.0.1` en
   `dev`). Vérifier que `deploy/.env.prod.example` n'invite plus à définir `CONTROLDONE_PAGES_CACHE_DIR` en
   production (la variable y est désormais ignorée, RS-03).
2. **RS-17** — sessions persistantes en base (révocation multi-processus, « déconnecter partout »), révocation au
   changement de mot de passe ; limiteur de débit partagé (point ouvert 3 de `SECURITY.md`).
3. **RS-20** — déplacer le rendu des vignettes dans le processus isolé ou à l'ingestion.
4. Ancrage externe de la tête de chaîne d'audit (point ouvert 1 de `SECURITY.md`).
5. Chiffrement du volume de la base (RS-21) et rotation testée de la clé maîtresse en exploitation.
6. RS-18, RS-19 : URL publique configurée, plafond de taille pour la veille.
7. Rejouer `pip-audit` à chaque mise à jour de `requirements.lock` (intégration continue) et ajouter `uvicorn`,
   `python-multipart` à `pyproject.toml`.
8. Garder `tests/security/` dans la suite : tout nouveau point d'entrée doit y gagner un cas (CSRF, IDOR, rôle).
