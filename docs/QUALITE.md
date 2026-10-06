# Qualité du code : vérifications, couverture, tests de propriétés

Outillage de développement seulement (rien n'entre dans l'image). Décisions D-3901 à D-3904 ; constats et suites
dans `docs/backlog/outillage.md`.

| Commande | Effet |
|---|---|
| `make hooks` | installe le crochet git avant enregistrement (une fois, par choix du développeur) |
| `make pre-commit` | toutes les vérifications sur tout le dépôt (aussi en CI) |
| `make couverture` | suite complète sous couverture : `var/couverture/paquets.md`, HTML `var/couverture/html/` |
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

## 2. Couverture : base de référence (2026-10-06)

Mesure : `pytest --cov` (branches comprises), suite complète hors tests de propriétés, sur le dépôt du
2026-10-06 (2 185 tests, 1 échec dû à une modification en cours du bloc web). Les blocs sécurité et stockage
modifiaient `web/securite.py` et `storage/securite.py` pendant la mesure : leurs chiffres sont indicatifs.

| Paquet | Lignes | Branches | Total |
|---|---:|---:|---:|
| `storage` | 70,3 % | 41,3 % | 64,5 % |
| `services` | 76,5 % | 59,4 % | 73,2 % |
| `ingest` | 81,3 % | 68,3 % | 77,6 % |
| `web` | 81,1 % | 62,2 % | 77,8 % |
| racine (`cli`, `pipeline`, `formatage`…) | 85,7 % | 79,3 % | 84,0 % |
| `auth` | 88,2 % | 72,9 % | 85,6 % |
| `extract` | 89,6 % | 79,6 % | 86,2 % |
| `agents` | 90,0 % | 72,4 % | 86,2 % |
| `connecteurs` | 92,1 % | 78,9 % | 89,3 % |
| `referentiel` | 93,7 % | 81,1 % | 90,6 % |
| `controls` | 93,4 % | 85,5 % | 91,1 % |
| `jobs` | 93,6 % | 78,1 % | 91,1 % |
| `outbox` | 95,1 % | 83,3 % | 92,9 % |
| `rapport` | 95,6 % | 83,8 % | 93,2 % |
| `api` | 95,8 % | 73,3 % | 93,4 % |
| `facturation` | 96,6 % | 84,9 % | 94,1 % |
| `litiges` | 96,0 % | 87,8 % | 94,5 % |
| `normalize` | 96,6 % | 89,9 % | 94,6 % |
| `recouvrement` | 97,4 % | 90,3 % | 95,8 % |
| `model` | 98,3 % | 88,2 % | 97,0 % |
| `macf` | 97,9 % | 93,0 % | 97,0 % |
| `demo` | 98,9 % | 93,9 % | 97,9 % |
| **Total** | **87,5 %** | **76,2 %** | **84,6 %** |

Pas encore de seuil bloquant (`make couverture COUV_MIN=…`) : à fixer quand les blocs en cours auront livré.
Une seconde mesure pendant leurs travaux (2026-10-06, 15 h 30) n'est pas exploitable : fichiers modifiés pendant
l'exécution, 56 échecs web en cours de correction par leur bloc.

## 3. Modules critiques les moins couverts

Critiques : contrôles, normalisation des montants, authentification, sécurité web, cloisonnement et coffre.

| Module (base) | Total | Suite |
|---|---:|---|
| `storage/securite.py` | 39,8 % | en cours de réécriture par le bloc sécurité (débit en base, révocation) : tests à sa charge |
| `web/securite.py` | 44,2 % | idem (en-têtes, CSP, Trusted Types, URL publique) |
| `auth/revocation.py` | 63,8 % | idem |
| `storage/scope.py` | 65,7 % | en cours de modification par le bloc stockage (cloisonnement) : tests à sa charge |
| `auth/jetons.py` | 80,1 % | bloc sécurité |
| `auth/cli_securite.py` | 80,8 % | commande d'exploitation, testée par le bloc sécurité |
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
