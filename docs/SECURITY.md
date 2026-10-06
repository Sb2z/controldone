# ControlDOne v2 — Sécurité de la plateforme

Ce document décrit le cloisonnement des clients, le chiffrement, les clés, l'authentification et le
modèle de menace du socle d'exploitation (niveau 2). Il complète `docs/SPEC.md` §4 et §20, et les
décisions D-003, D-004 et D-450 à D-462 de `docs/DECISIONS.md`. Code : `src/controldone/storage/`,
`src/controldone/auth/`, `src/controldone/jobs/`, `src/controldone/outbox/` ; tests :
`tests/platform/` (`test_isolation.py` en premier).

---

## 1. Cloisonnement par client

Le cloisonnement n'est pas confié à la base (D-003) mais à **une couche d'accès unique**,
`TenantScope(session, tenant_id, actor)`. Toute lecture ou écriture d'une donnée client passe par elle.

### 1.1 Trois barrières indépendantes

| # | Barrière | Où | Ce qu'elle arrête |
|---|---|---|---|
| 1 | Filtre explicite `tenant_id = :client` sur chaque requête de `TenantScope` | `storage/scope.py` | Lecture, modification, suppression d'un objet d'un autre client par devinette d'identifiant |
| 2 | Critère automatique (`with_loader_criteria`) ajouté à **toute** requête ORM SELECT / UPDATE / DELETE d'une session liée à un client ; refus de toute requête sur une table client depuis une session non liée ; refus des INSERT en masse | `storage/garde.py` (`do_orm_execute`) | Requête « à la main » sur `scope.session`, jointures, alias, sous-requêtes, `session.get`, UPDATE/DELETE en masse |
| 3 | Contrôle au flush : tout objet ajouté, modifié ou supprimé doit appartenir au client de la session ; `tenant_id` ne change jamais ; session opérateur en lecture seule ; tables append-only protégées | `storage/garde.py` (`before_flush`) | `session.add` d'un objet étranger, changement de `tenant_id` par attribut, écriture depuis une session non cloisonnée |

S'y ajoute une **règle d'architecture testée** : aucun module hors de `controldone.storage` ne contient
`select(`, `.execute(`, `session.query(`, `Session(`, `sessionmaker(`, `create_engine(` ni n'importe
`sqlalchemy` (`test_pas_de_session_brute_hors_storage`). Les paquets `jobs`, `outbox` et `auth` passent par
des fonctions du stockage (`JobStore`, `storage.sorties`, `storage.comptes`).

### 1.2 Règles de comportement

- Un identifiant d'un autre client et un identifiant inexistant donnent **la même** erreur
  (`AccesRefuse("introuvable ou hors périmètre")`) : pas d'oracle d'existence.
- Les modèles SQLAlchemy n'ont **aucune** `relationship()` : pas de chargement implicite qui échapperait
  au filtre.
- Une session est liée à un seul client ; la réutiliser pour un autre client est refusé.
- `tenant_id` et `id` ne sont jamais modifiables par l'API générique ; une collision d'identifiant avec
  la ligne d'un autre client est refusée sans écrasement (erreur générique).
- Rôles (`auth/roles.py`, `peut(user, action, ressource)`, refus par défaut) :
  - `client_admin` / `client_lecteur` n'ouvrent que le périmètre de **leur** client, et doivent y être
    membres (vérifié en base à l'ouverture : un acteur forgé avec un autre `tenant_id` ou un autre rôle est
    refusé) ;
  - `client_lecteur` n'écrit rien ; `client_admin` n'écrit par l'API générique que les tables `lots`,
    `fichiers`, `pages`, `entites`, `transitaires`, `grilles` (brouillon) et `reclamations` ; dossiers,
    résultats, constats et coûts sont réservés au moteur (`systeme`) et au fondateur ;
  - un rôle client ne voit que les constats `valide` (règle de publication §4) et jamais la table des
    résultats bruts ; les champs de validation (constat, grille) exigent la permission du fondateur.
- **Fondateur** : il ne peut pas ouvrir un `TenantScope` directement. `OperatorScope(db, fondateur)`
  écrit une entrée `acces_admin` (motif obligatoire), validée **immédiatement** dans sa propre transaction,
  à chaque ouverture d'un client ; chaque écriture du fondateur dans le périmètre est aussi journalisée.
  Les lectures transversales (liste des clients, file de validation, coûts) sont journalisées.
- **Système** (worker) : ouvre le périmètre du client du job ; ne valide, ne publie et n'approuve rien.

---

## 2. Journal d'audit

Table `audit_log` append-only : `ts, actor, role, tenant_id, action, target, ip, details, prev_hash, hash`
avec `hash = SHA-256(prev_hash | JSON canonique de l'entrée)`.

- `prev_hash` est **unique** : deux écritures concurrentes ne peuvent pas créer de fourche.
- Modification et suppression refusées par l'ORM et par des déclencheurs SQL (SQLite et PostgreSQL).
- `verifier_chaine(session)` détecte une entrée modifiée, supprimée ou insérée (testé en désactivant les
  déclencheurs pour simuler un attaquant avec accès au fichier de base).
- `details` ne contient jamais de contenu de document : identifiants, compteurs, motifs courts.
- Le journal survit à l'effacement RGPD d'un client (identifiants seulement) : c'est la trace de
  l'effacement lui-même.
- Limite : une réécriture **complète** de la chaîne par quelqu'un qui contrôle la base n'est pas
  détectable sans ancrage externe (voir § 6, points ouverts).

---

## 3. Chiffrement au repos et clés

### 3.1 Coffre de fichiers (`FileVault`)

- Fichiers bruts et textes de page chiffrés par Fernet (AES-128-CBC + HMAC-SHA256), **une clé par
  client** dérivée par HKDF-SHA256 (`info = vault:<client>`) de la clé maîtresse : un blob copié dans le
  coffre d'un autre client ne se déchiffre pas.
- Adressage par contenu : `<racine>/<client>/<fichiers|textes>/<sha[:2]>/<sha256 du clair>` ; l'empreinte
  est revérifiée à la lecture (substitution ou altération détectées).
- Traversée de chemin impossible : identifiant de client et empreinte validés par expression régulière,
  chemin résolu puis vérifié sous la racine ; écriture atomique, droits 0600 (répertoires 0700).
- Contenus d'au moins 256 Kio (D-1305) : format `CDV2` chiffré **par segments** d'1 Mio, AES-256-GCM, clé par
  client dérivée HKDF (`vault-gcm:<client>`) ; nonce = préfixe aléatoire || numéro de segment ; données
  associées = en-tête || numéro || drapeau final : réordonner, tronquer ou substituer un segment est détecté.
  Écriture et lecture segment par segment (mémoire bornée). Les objets Fernet existants restent lisibles.
- Purge et dépôt concurrents (D-1324) : un contenu n'est retiré qu'après vérification, sous le verrou
  d'écriture, qu'aucune ligne ne le référence et qu'il n'a pas été redéposé à l'identique depuis moins d'une
  heure ; un dépôt revérifie la présence de ses contenus dans la transaction qui l'enregistre.
- Les métadonnées (nom d'origine, empreinte, taille) restent en base en clair ; la base est chiffrée
  dans les sauvegardes.

### 3.2 Clés

| Secret | Variable | Usage |
|---|---|---|
| Clé maîtresse (Fernet, 32 octets base64) | `CONTROLDONE_MASTER_KEY` (plusieurs valeurs séparées par des virgules : la première chiffre, toutes déchiffrent) | Dérive : clés du coffre par client, clé des sauvegardes (`sauvegarde`), clé des secrets TOTP (`secrets`) |
| Secret de signature des sessions | `CONTROLDONE_SECRET_KEY` (liste ; la dernière signe) | Jetons de session, CSRF |
| Mode | `CONTROLDONE_ENV` = `dev` \| `test` \| `prod` (valeur inconnue = `prod`) | |

- **Fichier `.env`** (D-1310) : chargé une fois dans l'environnement du processus (sans écraser une variable
  déjà définie) **avant toute lecture** : `CONTROLDONE_ENV=prod`, la clé maîtresse et le secret de session
  placés dans `.env` sont donc bien appliqués (avant : seul `Settings` le lisait ; un `.env` de production
  laissait le service en mode `dev`, clé de développement générée et cookie sans `Secure`).

- **Production** : sans clé maîtresse (ou sans secret de session), le service **refuse de démarrer**
  (`CleManquante`).
- **Développement** : une clé est générée dans `var/dev_master.key` (0600) avec un avertissement bruyant
  à chaque chargement ; jamais en production.
- **Rotation** de la clé maîtresse : préfixer la nouvelle clé (`CONTROLDONE_MASTER_KEY=nouvelle,ancienne`),
  appeler `FileVault.tourner_cles([nouvelle, ancienne])` qui rechiffre tout le coffre, puis retirer
  l'ancienne clé (les sauvegardes antérieures restent lisibles avec l'ancienne clé : la conserver hors
  ligne pendant la durée de rétention des sauvegardes). Voir `docs/EXPLOITATION.md`.

---

## 4. Authentification

- **Mots de passe** : Argon2id (argon2-cffi), 12 caractères minimum ; un compte inconnu coûte le même
  calcul (empreinte leurre) ; un seul message d'échec (« identifiants invalides »).
- **Second facteur du fondateur** : TOTP RFC 6238 (SHA-1, 6 chiffres, 30 s, tolérance ± 1 pas),
  implémenté avec `hmac` de la bibliothèque standard (vecteurs RFC 4226 et RFC 6238 testés). Le secret est
  chiffré en base (clé dérivée `secrets`). **Anti-rejeu** : le dernier pas utilisé est mémorisé ; un code
  du même pas ou d'un pas antérieur est refusé. Un jeton de session de rôle `fondateur` sans le drapeau
  « second facteur » est refusé.
- **Sessions** : jetons signés (itsdangerous, HMAC), expiration d'inactivité (30 min), durée absolue (8 h),
  rotation du jeton toutes les 15 min (`rafraichir`), révocation par identifiant de session **en base**
  (table `sessions_revoquees`, valable pour tous les processus et après un redémarrage, D-3202) ; un changement
  ou une réinitialisation du mot de passe ferme toutes les autres sessions du compte ; cookie
  `__Host-cd_session`, `HttpOnly`, `Secure`, `SameSite=Strict` en production (`parametres_cookie`). Le compte
  est relu en base à chaque requête de l'interface (`web.securite.acteur_de`) : un compte désactivé
  (`storage.comptes.desactiver_utilisateur`) ou qui n'est plus fondateur perd aussitôt ses sessions.
- **CSRF** : jeton `nonce.HMAC(secret, sid|nonce)` lié à la session, comparaison à temps constant.
- **Clés d'API par client** : `cdk_<préfixe>_<secret>` ; seul le SHA-256 du secret est stocké (secret de
  256 bits : un hachage lent est inutile) ; la clé complète n'est montrée qu'une fois ; révocable ;
  l'acteur obtenu est un rôle client rattaché au client de la clé (il ne peut ouvrir aucun autre client).
- **Limitation de débit** : seaux à jetons **en base** (`debit_compteurs`, D-3201), partagés par les processus et
  conservés au redémarrage ; clés pseudonymisées (HMAC) ; table bornée ; seuls les échecs épuisent la limite ;
  secours en mémoire si la base ne répond pas. Déblocage : `controldone debit effacer --email …` (journalisé).
- **Réinitialisation de mot de passe** : en ligne de commande sur la machine du service seulement
  (`controldone reinitialiser-mot-de-passe`) ; aucun lien de réinitialisation par courriel.
- **En-têtes** : CSP sans script ni style en ligne, violations reçues sur `/csp-rapport` (débit et taille bornés,
  journal sans donnée personnelle), `Permissions-Policy` restrictive, COOP/CORP `same-origin`, HSTS 2 ans (D-3204).
- **Dépendances** : `make audit` (vulnérabilités, SBOM CycloneDX, licences permissives seulement, D-3203).

---

## 5. Autres mesures

- **Actions sortantes** : tout envoi vers l'extérieur est un brouillon (`ActionSortante`) validé par le
  fondateur ; tout texte passe `guardrails.check_text` avant approbation **et** juste avant l'envoi ;
  autonomie `manuel` par défaut pour tous les types, modifiable par le fondateur seul ; le seul expéditeur
  livré écrit des fichiers (`var/outbox_envoyee/`) — aucun code d'envoi réel (testé).
- **Journaux** : JSON, liste blanche de champs (identifiants, durées, compteurs, codes) ; une exception est
  journalisée par son **nom de classe** seulement (son message pourrait contenir du texte de document).
- **Coûts IA** : plafond mensuel par client (alerte à 80 %, arrêt des appels au modèle à 100 %).
- **Fichiers temporaires** du worker : répertoire temporaire privé, chemins d'origine assainis
  (`..`, chemins absolus, NUL), supprimé à la fin du job. Le processus isolé qui analyse les fichiers
  déposés ne reçoit aucun secret dans son environnement (clés, Stripe, Anthropic, IMAP, URL de base).
- **Cache disque des pages** (`CONTROLDONE_PAGES_CACHE_DIR`) : texte en clair, banc et développement
  seulement ; ignoré en production (`CONTROLDONE_ENV=prod`).
- **Images de page** rendues dans le processus web : taille bornée (`services.vignettes.MAX_PIXELS`).
- **Sauvegardes** : archive chiffrée (clé dérivée `sauvegarde`), 0600, format `CDSAV2` par segments
  authentifiés (numéro et drapeau final : troncature, réordonnancement et duplication détectés, D-1320) ;
  restauration en flux refusant toute entrée hors de `base/` et `coffre/`, extraction avec le filtre `data`
  (ni chemin absolu, ni `..`, ni lien). Un échec émet l'alerte `sauvegarde_echec`.
- **Montants saisis** (web, API, MCP, import de grille) : un seul analyseur strict
  (`services.saisie.montant_saisi`, D-1316) — `NaN`, `Infinity`, notation scientifique, négatifs et valeurs
  démesurées refusés avec un message lisible (jamais une erreur 500).
- **Disponibilité** : routes web et API synchrones (groupe de fils), dépôts reçus hors transaction et en
  mémoire bornée, verrou d'écriture SQLite tenu le temps des seuls `INSERT` (D-1304), expéditeurs sortants
  appelés hors transaction (D-1323), fichiers temporaires sur le volume de données (D-1305).
- **Relevé d'écarts** : le modèle de courrier remis au client est vérifié (`litiges.redaction.verifier_modele`)
  — aucune formulation d'acte juridique pour autrui (brief juridique §9).

---

## 6. Modèle de menace (résumé)

| Menace | Mesure | Reste |
|---|---|---|
| Un client lit ou modifie les données d'un autre (devinette d'identifiant, paramètre falsifié) | Trois barrières § 1.1, appartenance vérifiée, erreur indistincte, tests adverses | Bogue dans une future route qui construirait un `TenantScope` avec un `tenant_id` lu dans la requête au lieu de la session : la route doit **toujours** prendre le client de l'acteur authentifié |
| Développeur qui contourne la couche d'accès | Test d'architecture (pas de SQL hors stockage), critère automatique, contrôle au flush | Code SQL brut (`text()`) dans `storage/` : relecture |
| Fondateur (ou son compte volé) qui consulte un client sans trace | Pas d'accès direct ; audit immédiat de chaque accès ; second facteur ; chaîne d'audit | Un administrateur système avec accès au fichier de base peut réécrire toute la chaîne |
| Vol du disque ou d'une sauvegarde | Coffre et sauvegardes chiffrés, clé hors disque (variable d'environnement) | La base SQLite vivante est en clair sur le disque (métadonnées, valeurs extraites, constats) : chiffrement du volume recommandé |
| Fuite de document par les journaux ou alertes | Liste blanche de champs, noms d'exception seulement | Les messages d'`ErreurDefinitive` / `ErreurTemporaire` sont écrits par notre code et ne doivent pas inclure de contenu |
| Texte de document piégé (injection) | Aucune action déclenchée par un contenu ; garde-fous sur les textes sortants | Voir SPEC §20.2 (équipe extraction) |
| Envoi non désiré vers l'extérieur | File de validation, mode manuel par défaut, pas d'expéditeur réel | — |
| Rejeu d'un code TOTP, vol de cookie | Anti-rejeu, `HttpOnly`/`Secure`/`SameSite`, rotation, durée absolue, révocation en base, sessions fermées au changement de mot de passe | Pas de liste des sessions actives |
| Traversée de chemin (coffre, worker, export, restauration) | Validation stricte, résolution et vérification sous la racine, filtre `data` | — |
| Dépassement des coûts IA | Registre `ai_usage`, plafonds, alertes | Dans un même lot, le pipeline actuel n'applique que le plafond par dossier (voir EXPLOITATION) |

### Points ouverts

1. Ancrage externe périodique de la tête de chaîne d'audit (courriel au fondateur, horodatage tiers).
2. Liste des sessions actives d'un compte (la révocation persistante est faite, D-3202).
3. ~~Limiteur de débit partagé entre processus~~ : fait (D-3201).
4. Chiffrement du volume qui porte la base (ou PostgreSQL avec chiffrement au repos de l'hébergeur).
5. Migrations de schéma (Alembic) : aujourd'hui `Database.creer_schema()` crée les tables manquantes ; une
   colonne manquante est détectée au démarrage du web et du worker, qui refusent de démarrer (D-1322), mais la
   migration reste manuelle.

Revue de sécurité indépendante (constats, preuves, correctifs, risques restants) : `docs/REVUE_SECURITE.md`,
puis seconde revue (octobre 2026) : `docs/REVUE_SECURITE_2.md`.
