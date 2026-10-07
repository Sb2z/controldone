# Qualité du code : vérifications, couverture, tests de propriétés

Outillage de développement seulement (rien n'entre dans l'image). Décisions D-3901 à D-3904, D-4901 à D-4903 ; constats et suites
dans `docs/backlog/outillage.md`.

| Commande | Effet |
|---|---|
| `make hooks` | installe le crochet git avant enregistrement (une fois, par choix du développeur) |
| `make pre-commit` | toutes les vérifications sur tout le dépôt (aussi en CI) |
| `make couverture` | suite complète sous couverture : `var/couverture/paquets.md`, HTML `var/couverture/html/` ; échoue sous les seuils (§ 2) |
| `make proprietes [PROFIL=dev\|ci\|intensif]` | tests de propriétés (Hypothesis) |
| `make corpus-g6`, `make corpus GRAINE=… PREFIXE=…` | corpus de banc non versionnés (`bench/README.md`) |

Outils (extras `dev` de `pyproject.toml`, licences) : pytest (MIT), ruff (MIT), pytest-cov (MIT), coverage
(Apache-2.0), Hypothesis (MPL-2.0, copyleft faible au fichier : outil de test, jamais modifié ni distribué),
pre-commit (MIT). `requirements.lock` (exécution) ne les contient pas.

## 1. Vérifications avant enregistrement (D-3901)

`.pre-commit-config.yaml`, crochets **locaux** (aucun téléchargement) : `ruff check` (src, tests, scripts) ;
espaces en fin de ligne ; fichiers de plus de 2 Mo (corpus `bench/corpus*/` exclus) ; clés privées et jetons d'API
(Anthropic, Stripe réel, webhook Stripe, AWS, GitHub, Slack — une valeur fictive assumée se marque
`pragma: allowlist secret`) ; syntaxe JSON et YAML ; pas de `print(` dans les paquets cœur (contrôles,
normalisation, extraction, modèle, web, rapport, ingestion). `ruff format` n'est pas vérifié : le code n'est pas
formaté par ruff (301 fichiers sur 363), voir le backlog.

## 2. Couverture : base de référence et seuils (2026-10-07, D-4901, D-4903)

Mesure : `make couverture` (`pytest --cov`, branches comprises), suite complète hors tests de propriétés. Trois
mesures : 2026-10-06 (première base, D-3902) ; 2026-10-07 avant le bloc O4 (2 602 tests, 2 échecs web en cours de
correction par leur bloc) ; 2026-10-07 après les tests du bloc O4 (**mesure de référence** : 2 910 tests, aucun
échec, aucun fichier modifié pendant l'exécution). Une mesure intermédiaire, faite pendant que les blocs moteur et
production modifiaient `controls/` et `storage/sauvegarde.py`, donnait 88,1 % (`controls` 85,3 %) : un fichier
modifié pendant l'exécution fausse sa mesure, d'où une seule mesure de référence prise au calme.

| Paquet (total, lignes + branches) | 2026-10-06 | 2026-10-07 avant O4 | 2026-10-07 après O4 |
|---|---:|---:|---:|
| `ingest` | 77,6 % | 84,4 % | 84,4 % |
| `extract` | 86,2 % | 86,4 % | 86,4 % |
| racine (`cli`, `pipeline`, `formatage`…) | 84,0 % | 84,9 % | 86,7 % |
| `agents` | 86,2 % | 86,7 % | 86,7 % |
| `services` | 73,2 % | 71,5 % | **89,3 %** |
| `connecteurs` | 89,3 % | 89,3 % | 89,3 % |
| `jobs` | 91,1 % | 90,0 % | 90,0 % |
| `referentiel` | 90,6 % | 90,6 % | 90,6 % |
| `controls` | 91,1 % | 86,3 % | 90,8 % |
| `storage` | 64,5 % | 81,7 % | **91,3 %** |
| `web` | 77,8 % | 82,9 % | **92,4 %** |
| `rapport` | 93,2 % | 93,2 % | 93,2 % |
| `outbox` | 92,9 % | 93,5 % | 93,5 % |
| `api` | 93,4 % | 87,8 % | 93,6 % |
| `facturation` | 94,1 % | 94,1 % | 94,3 % |
| `litiges` | 94,5 % | 94,5 % | 94,5 % |
| `recouvrement` | 95,8 % | 95,8 % | 94,9 % |
| `normalize` | 94,6 % | 96,7 % | 96,7 % |
| `macf` | 97,0 % | 97,0 % | 97,0 % |
| `model` | 97,0 % | 97,0 % | 97,0 % |
| `demo` | 97,9 % | 97,9 % | 97,9 % |
| `auth` | 85,6 % | 93,5 % | **98,3 %** |
| **Total** (lignes / branches) | **84,6 %** (87,5 / 76,2) | **86,2 %** (89,2 / 77,6) | **89,7 %** (92,1 / 82,7) |

Une part des hausses de `services` (`services/exercice_mensuel.py` 0 -> 81 %), `storage` (`storage/sauvegarde.py`,
`storage/retention.py`) et `web` (`web/i18n.py`, `web/routes_finances.py`) vient des tests livrés en même temps par
les blocs production et interface ; la part du bloc O4 est détaillée au § 3.

**Seuils bloquants (D-4903)** : mesure de référence moins 1 point, arrondie à l'entier inférieur. `make couverture`
(défauts du Makefile) et le job `complet` de la CI échouent sous **COUV_MIN=88** (total 89,7 %) ou sous un minimum
de paquet : `controls` ≥ 89 % (90,8 %), `auth` ≥ 97 % (98,3 %). Valeurs identiques dans `Makefile` (`COUV_MIN`,
`COUV_MIN_PAQUETS`) et `.github/workflows/ci.yml`, vérifiées par `tests/outillage/test_couverture_seuils.py`.
Mesurer sans bloquer : `make couverture COUV_MIN=0 COUV_MIN_PAQUETS=`. Relever les seuils quand une mesure stable
les dépasse de plus de 2 points ; ne jamais les baisser pour faire passer une livraison sans décision.

## 3. Modules critiques les moins couverts

Critiques : contrôles, normalisation des montants, authentification, sécurité web, cloisonnement et coffre.

| Module (base) | Total | Suite |
|---|---:|---|
| `storage/securite.py` | 39,8 % | **traité** (bloc O4, ci-dessous) |
| `web/securite.py` | 44,2 % | **traité** (bloc O4) |
| `auth/revocation.py` | 63,8 % | **traité** (bloc O4) |
| `storage/scope.py` | 65,7 % | **traité** (bloc O4) |
| `auth/jetons.py` | 80,1 % | **traité** par le bloc sécurité (99,5 % le 2026-10-07) |
| `auth/cli_securite.py` | 80,8 % | **traité** (bloc O4) |
| `web/rendu.py` | 81,8 % | **traité** : filtres d'affichage, garde de redirection, texte visible |
| `controls/corroboration.py` | 83,0 % | **traité** : réseau de la facture commerciale (pieds, remise, sous-total) |
| `auth/debit.py` | 84,3 % | **traité** : base indisponible -> repli en mémoire qui limite encore |
| `controls/famille_e.py`, `controls/structure_declaration.py` | 87,7 %, 88,9 % | **traité** pour la structure (nature du taux, masses partielles) ; E à reprendre par le bloc moteur |

Tests ajoutés (aucune modification de `src/`) et effet mesuré sur une exécution ciblée (tests des contrôles, de la
normalisation, de la sécurité ; avant -> après) :

| Module | Avant | Après | Tests |
|---|---:|---:|---|
| `controls/corroboration.py` | 81,5 % | 88,9 % | `tests/controls/test_corroboration_facture_commerciale.py` |
| `controls/structure_declaration.py` | 88,9 % | 94,9 % | `tests/controls/test_structure_declaration_branches.py` |
| `controls/tolerances.py` | 94,0 % | 97,6 % | `tests/proprietes/test_prop_tolerances.py` |
| `auth/debit.py` | 78,4 % | 98,5 % | `tests/security/test_debit_secours.py` |
| `web/rendu.py` | 62,7 % | 91,0 % | `tests/web/test_rendu_filtres.py`, `tests/proprietes/test_prop_web.py` |
| `web/listes.py` | 70,3 % | 83,1 % | `tests/proprietes/test_prop_web.py` |
| `services/saisie.py` | 67,7 % | 100 % | `tests/test_normalize_branches.py`, `tests/proprietes/test_prop_montants.py` |
| `normalize/amounts.py` | 90,5 % | 96,7 % | idem |
| `normalize/currency.py` | 92,9 % | 99,0 % | `tests/test_normalize_branches.py` |

### Bloc O4 (2026-10-07, D-4901, D-4902)

Tests de comportement (chemins d'erreur, droits et cloisonnement, cas limites), sur la suite complète (avant ->
après, mesures du § 2) :

| Module | Avant | Après | Tests | Comportements vérifiés |
|---|---:|---:|---|---|
| `storage/scope.py` | 88,2 % | 99,1 % | `tests/platform/test_scope_branches.py` | fondateur hors `OperatorScope`, session système ou déjà liée à un autre client, client désactivé, membre au mauvais rôle, clé d'API révoquée / d'un autre client / autre rôle, filtre `tenant_id` interdit partout, suppression (append-only, lecteur, autre client, journal du fondateur), recontrôle qui conserve ou annule la validation, rétrogradation, correction hors dossier, journal du client limité à ses entrées, recherche du journal (joker échappé), alertes |
| `storage/securite.py` | 85,2 % | 96,7 % | `tests/security/test_securite_partagee_branches.py` | insertion concurrente rejouée (3 essais puis erreur), révocations cumulées, purge bornée, effacement journalisé, chiffrement du volume (`/sys` simulé : LUKS direct, LVM sur LUKS, cycle), alerte de démarrage une fois par mois et jamais bloquante |
| `auth/revocation.py` | 75,4 % | 100 % | idem | base indisponible : aucune requête bloquée, révocation locale conservée, journal sans identifiant ; purge au plus une fois par période |
| `auth/cli_securite.py`, `storage/cles.py` | 80,8 %, 50,6 % | 100 %, 100 % | `tests/platform/test_cli_securite_cles.py` | déblocage ciblé (IP, clé d'API, compte) ou total, réinitialisation refusée (compte inconnu, mot de passe faible, confirmation différente) ou réussie (sessions révoquées, compteurs remis à zéro) ; clé absente en production, clé de développement 0600, rotation, secret altéré |
| `storage/migrations.py` | 89,7 % | 98,3 % | `tests/platform/test_migrations_branches.py` | étapes idempotentes sur base partielle, colonne NOT NULL refusée, inscription concurrente, étape appliquée pendant l'attente |
| `web/securite.py` | 80,6 % | 97,6 % | `tests/web/test_securite_web_branches.py` | URL publique invalide ou en http en production, jamais l'hôte de la requête, hôtes admis ; mode dev exposé ; limite de corps (`Content-Length` mensonger, réponse commencée) ; rapports CSP réduits (aucune URL complète, aucun extrait) |
| `services/admin.py` | 80,8 % | 99,7 % | `tests/platform/test_admin_services_branches.py` | réservé au fondateur, saisies refusées en 400 (raison sociale, offre, plafond, courriel, rôle, SIREN), compte fondateur jamais rattaché à un client, grilles CSV/JSON mal formées, statut et client jamais pris du fichier |
| `services/reclamations.py` | 78,1 % | 95,5 % | `tests/platform/test_reclamations_branches.py` | écart d'un constat non publié invisible au client, transitions refusées proprement, montants d'avoir NaN / infini / négatifs / flottants, échéances de rappel mal saisies, relevé d'un autre client ignoré |
| `services/validation.py` | 83,2 % | 99,2 % | `tests/web/test_validation_branches.py` | décision unique, motifs obligatoires, écart ouvert une fois, correction hors dossier ou illisible, recontrôle idempotent |
| `services/vignettes.py` | 49,4 % | 99,4 % | `tests/test_vignettes.py` | plafond de pixels (page aberrante), page hors document, extrait autour d'une valeur, cache borné, erreur de rendu = pas d'image |

Défaut trouvé et corrigé (D-4902) : `services.admin.ajouter_entite` dérivait l'identifiant de l'entité de la TVA
**telle que saisie** ; « fr 40 303 265 045 » puis « FR40303265045 » créaient deux entités de même TVA. Identifiant
désormais dérivé de la TVA normalisée (test de non-régression
`test_entite_tva_ecrite_autrement_pas_de_doublon`). Restent les moins couverts, modules modifiés par
d'autres blocs pendant O4 (non traités ici) : `storage/verrou.py` (70 %), `services/exercice_restauration.py`
(78 %), `storage/sauvegarde.py` (79 %), `web/routes_finances.py` (80 %), `services/exercice_mensuel.py` (81 %).

## 4. Tests de propriétés (D-3903)

`tests/proprietes/` (marqueur `proprietes`), 38 propriétés. Profils (`HYPOTHESIS_PROFILE`) : `dev` 100 exemples
(défaut), `ci` 150 exemples, graine fixe, sans base d'exemples (CI), `intensif` 2 000 exemples (à la main, ~2 min 30).

| Fichier | Propriétés |
|---|---|
| `test_prop_montants.py` | tout montant écrit en usage français (espace, insécable, fine), anglais, allemand, suisse (`'` et `’`), indien (lakh/crore) ou sans séparateur est relu exactement ; signe moins avant/après/Unicode, parenthèses, devise avant/après ; `format_montant` relu à l'arrondi de la devise ; `format_nombre` relu exactement quand le séparateur décimal est connu ; entiers ; saisie d'interface aller-retour, jamais d'erreur 500, aucun chiffre perdu ; lecture robuste sur texte quelconque (jamais d'exception, `Decimal` fini ≥ 0) |
| `test_prop_tolerances.py` | tolérances symétriques en (a, b) et en signe, `Decimal` exact (jamais `float`), base = plus grande valeur, seuil de certitude ≥ tolérance, monotonie, bornes de `T_SOMME`/`T_DEBOURS`, arrondis idempotents et symétriques, concordance des taxes arrondies à l'euro |
| `test_prop_identifiants.py` | TVA FR : clé calculée valide, bruit de saisie (casse, espaces, points, tirets) sans effet, mauvaise clé refusée, SIREN relu ; Luhn : un seul chiffre de contrôle ; `normalize_vat` idempotent ; MRN : bruit sans effet, préfixe stable entre versions, égalité symétrique ; clé de confusion OCR invariante par substitution dans une classe (0/O/Q/D, 1/I/L…) ; comparaisons de références symétriques |
| `test_prop_dates.py` | toute date 1970–2069 écrite en ISO, `jj/mm/aaaa`, `j.m.aaaa`, `jj-mm-aaaa`, année sur 2 chiffres, compact, français (« 1er », capitales), anglais US/UK, allemand, espagnol est relue ; ambiguïté jour/mois signalée et tranchée par l'ordre ; robustesse |
| `test_prop_web.py` | redirection : le résultat est toujours un chemin interne (ni schéma, ni hôte, ni `//`, `\`, `:`, `@`, caractère de contrôle), un chemin interne valide est conservé ; paramètres de liste : valeur sûre ou `RequeteInvalide` (400), jamais d'erreur 500, liens réémis relus à l'identique ; pagination complète sans doublon ; numéros de page |

Résultat : aucun défaut trouvé (profils `dev` et `intensif`). Limite connue, documentée : `format_nombre` à 3
décimales (« 1,234 ») n'est relu exactement qu'avec le séparateur décimal indiqué (ambiguïté des milliers, D-2006).
