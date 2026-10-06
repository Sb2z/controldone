# ControlDOne v2 — Seconde revue de sécurité

Date : 6 octobre 2026. Périmètre : ce qui a changé depuis la première revue (`docs/REVUE_SECURITE.md`, 2 octobre) et
l'audit final (`docs/AUDIT_FINAL.md`), plus les chantiers du bloc C : limitation de débit, sessions, en-têtes HTTP,
dépendances. Aucune donnée réelle : toutes les preuves tournent sur des données fictives. Aucun commit.

Décisions : D-3201 à D-3205 (`docs/DECISIONS.md`). Preuves : `tests/security/test_revue_securite_2.py` (26 tests).
Constats non traités : `docs/backlog/securite.md`.

## 1. Périmètre

| Domaine | Composants examinés |
|---|---|
| Authentification | `auth/` (débit, sessions, révocation), `web/routes_auth.py`, `api/routes.py` (`acteur_api`), ligne de commande |
| En-têtes et navigateur | `web/securite.py`, `web/app.py`, `deploy/Caddyfile`, gabarits, `static/theme.js`, `static/app.js` (palette, zone de dépôt, suivi en direct, filtrage en direct), `static/vendor/motion.min.js` |
| Nouvelles entrées hostiles | `ingest/structure_deduite.py` (fiche XML déduite, D-2401), `ingest/pretraitement.py` et `ingest/pages.py` (prétraitement OCR, images, tableurs, CSV), `services/admin.py` (grille CSV) |
| Nouvelles routes | `web/listes.py`, `web/listes_vues.py` (recherche, filtres, tri, pagination), `web/suivi.py` et points JSON `/espace/suivi`, `/espace/lots/{id}/etat`, `/admin/jobs/etat` |
| Dépendances | `requirements.lock` (68 paquets), environnement `.venv`, fichiers servis de `static/vendor` |

## 2. Méthode

1. Lecture adverse du code modifié depuis le 3 octobre (fichiers plus récents que `AUDIT_FINAL.md`) et des
   chemins d'authentification.
2. Pour chaque soupçon : mesure ou test qui échoue d'abord, puis correctif minimal, puis test vert.
3. Mesures de complexité sur des XML synthétiques (déclaration fictive, 500 à 64 000 articles).
4. `pip-audit` 2.10 sur `requirements.lock` (bases PyPI **et** OSV) et sur le `uv pip freeze` du `.venv` ;
   CycloneDX 1.6 ; `pip-licenses` 5.5.
5. `pytest -q` complet et `ruff check src tests scripts`.

## 3. Constats

Sévérité comme dans la première revue (Élevée, Moyenne, Faible, Info).

| Id | Sév. | Composant | Description | Preuve | Statut |
|---|---|---|---|---|---|
| REV2-01 | Moyenne | `ingest/structure_deduite.py` | **Déni de service par un XML de quelques Mo.** `_dans` reconstruisait l'ensemble des éléments de groupe pour chaque élément du document, et le rattachement d'une taxe à son article reconstruisait `set(articles)` pour chaque ancêtre : déduction quadratique. Mesuré : 1 000 articles 0,25 s, 4 000 articles (0,5 Mo) 3,5 s ; extrapolé, ≈ 1 h 30 pour un XML sous le plafond de 1 million de balises (D-1607). L'analyse structurée tourne dans le worker, hors du processus isolé à délai : un client bloquait le worker pour tous. | `test_fiche_deduite_lineaire` (16 000 articles) | corrigé : ensembles construits une fois ; 16 000 articles 2,2 s, 64 000 articles (8 Mo) 9 s ; fiches identiques |
| REV2-02 | Moyenne | `auth/debit.py`, `auth/jetons.py` | **Limites et révocations perdues au redémarrage, non partagées** (RS-17 et point ouvert 3 de `SECURITY.md`). Un redémarrage ou un second processus remettait à zéro les compteurs de connexion ; une déconnexion ou un changement de mot de passe ne valait que pour le processus qui l'avait servie. Chaque connexion réussie consommait aussi un jeton : le fondateur bloqué après des connexions de test, débloqué seulement en relançant le serveur. | `test_verrou_de_connexion_survit_au_redemarrage…`, `test_deconnexion_revoque_dans_tous_les_processus`, `test_changement_de_mot_de_passe_ferme_les_autres_sessions`, `test_connexions_reussies_ne_bloquent_pas`, `test_limiteur_partage_*`, `test_revocation_persistante_entre_processus` | corrigé (D-3201, D-3202) |
| REV2-03 | Faible | `ingest/pages.py` (`_pages_image`) | Tous les cadres d'un TIFF/GIF étaient décodés et copiés **avant** la coupe à 300 pages ; une image basse résolution était agrandie jusqu'à × 9 en pixels sans plafond (80 Mpx à 72 dpi → 720 Mpx). Contenu par `RLIMIT_AS` du processus isolé, mais au prix d'une page illisible et d'une forte allocation. | `test_images_cadres_bornes_et_agrandissement_plafonne` | corrigé : cadres un par un ; agrandissement plafonné à 40 Mpx (une page A3 à 300 dpi en fait 17) |
| REV2-04 | Faible | `services/admin.py` (`_postes_csv`, import de grille) | Un CSV dont le séparateur n'était pas reconnu **modifiait `csv.excel` pour tout le processus** (`csv.excel.delimiter = ";"`) : exports CSV et lecture des taux BCE faussés ensuite. Un champ de plus de 128 Ko levait une `csv.Error` non rattrapée (erreur 500). Route réservée au fondateur. | `test_csv_de_grille_sans_effet_global_ni_erreur_500` | corrigé : dialecte dérivé, erreur lisible |
| REV2-05 | Faible | `web/listes.py` (`_entier`) | `?page=²` (ou `taille=⁵⁰`) : `str.isdigit` accepte les exposants, `int` les refuse → erreur 500 sur toutes les listes. | `test_listes_parametres_hostiles_sans_erreur_500` | corrigé : chiffres ASCII seulement |
| REV2-06 | Faible | Changement de mot de passe | Vérification du mot de passe actuel sans limite de débit (un cookie volé permettait de deviner le mot de passe pour le réutiliser ailleurs). | `test_changement_de_mot_de_passe_limite` | corrigé : seau du compte (5 essais / 5 min) |
| REV2-07 | Info | En-têtes | `Permissions-Policy` limitée à 4 fonctions ; HSTS différent entre Caddy (1 an) et l'application (2 ans) ; aucun retour des violations de CSP. | `test_en_tetes_durcis`, `test_rapport_csp_*`, `test_cookie_de_session_en_production` | corrigé (D-3204) |
| REV2-08 | Info | Dépendances | `pip-audit` n'était lancé qu'à la main ; ni SBOM, ni vérification des licences, ni inventaire des fichiers servis (`static/vendor`). | `test_classement_des_licences`, `test_composants_embarques_declares` | corrigé : `make audit`, étape de CI (D-3203) |

## 4. Points vérifiés sans constat

- **XML déduit** : le document est analysé par l'analyseur durci de `structure._xml` (`resolve_entities=False`,
  `no_network`, `load_dtd=False`, `huge_tree=False`, commentaires et instructions retirés) ; la déduction ne compare
  que des noms d'éléments à des listes fermées, n'évalue aucun texte et produit des chemins XPath construits à partir
  de noms locaux (pas de chaîne XPath venue du document). XXE fichier et entités imbriquées : rien n'est résolu
  (`test_fiche_deduite_xxe_et_entites`). Profondeur bornée par libxml2 (256 sans `huge_tree`).
- **Prétraitement OCR** (`pretraitement.py`) : opérations Pillow linéaires sur l'image de la page (gris, médian
  3 × 3, profils par réduction `BOX`, étirement d'histogramme) ; les redimensionnements y sont des réductions. Les
  bombes de décompression d'images sont refusées à la réception (`Image.DecompressionBombError`), les pages sont
  comptées (`n_frames` ≤ 300), et tout tourne dans le processus isolé (délai, `RLIMIT_AS`, aucun secret).
- **Tableurs et CSV** : XLSX en lecture seule bornée (colonnes, cellules, lignes, D-1604), conteneur ZIP contrôlé
  avant ouverture (D-1602) ; ODS à répétitions bornées ; CSV : limite de champ de `csv` (128 Ko) rattrapée.
- **JavaScript de l'interface** : `app.js` n'écrit que du `textContent` (palette, liste des fichiers de la zone de
  dépôt, suivi en direct, annonces) ; aucun `innerHTML`, `insertAdjacentHTML`, `document.write`, `eval`,
  `new Function` dans `app.js`, `theme.js` ni Motion 14.0.0 (test permanent `test_javascript_sans_puits_html`).
  La palette navigue vers des liens lus dans la page (rendus par le serveur) ; un `javascript:` serait de toute
  façon bloqué par la CSP. `theme.js` n'accepte que `clair` ou `sombre` depuis `localStorage`. Le filtrage en direct
  ne charge que des réponses `text/html` de même origine et les insère via `DOMParser` (document inerte, scripts non
  exécutés, CSP sans script en ligne). Gabarits : aucun script ni gestionnaire en ligne, aucun `|safe`.
- **Listes** (`listes.py`) : paramètres validés strictement (choix fermés, montants par l'analyseur strict, dates
  bornées, 200 caractères, caractères de contrôle refusés, une seule valeur par paramètre, tri sur liste fermée,
  taille 25/50/100, page ≤ 10 000) ; recherche par sous-chaîne normalisée, sans expression régulière fournie par
  l'utilisateur ; le client vient toujours de la session.
- **Suivi en direct** : points JSON authentifiés (client : son seul périmètre ; fondateur : `_fondateur`), limités
  par compte, `no-store`, sans contenu de document.
- **Sessions** : cookie `__Host-cd_session`, `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, sans `Domain`,
  `Max-Age` 8 h ; inactivité 30 min, durée absolue 8 h, rotation 15 min ; nouvel identifiant à la connexion.
- **Réinitialisation de mot de passe** : aucun parcours « mot de passe oublié » (pas de jeton par courriel) ; seule
  la ligne de commande sur la machine du service le permet (D-3202).
- **Clés d'API** : inchangées (256 bits, SHA-256 seul stocké, comparaison constante) ; débit désormais partagé.

## 5. Audit des dépendances (6 octobre 2026)

- `make audit` : 68 paquets figés, **0 vulnérabilité connue** (PyPI ; recoupé avec OSV). Même résultat sur les 79
  paquets réellement installés dans `.venv`. Aucune version à relever : aucune modification de `requirements.lock`.
- Licences : toutes permissives, sauf deux exceptions justifiées (`python-stdnum` LGPL-2.1+, dépendance de
  `factur-x` importée sans modification ; `certifi` MPL-2.0, magasin de certificats non modifié).
- Fichiers servis par l'application, déclarés et empreintés dans le SBOM : Motion 14.0.0 (MIT,
  `static/vendor/motion.min.js`, licence jointe), polices Geist et Geist Mono (OFL-1.1, licence jointe). Un nouveau
  fichier de `static/vendor` non déclaré fait échouer l'audit et le test.
- Résiduel (backlog) : paquets Debian et Tesseract de l'image non audités ; `requirements.lock` sans empreintes ;
  `alembic`, `mako`, `python-dateutil`, `six` installés dans `.venv` sans être figés (aucun import dans `src/`).

## 6. Risques restants

1. RS-16, RS-18, RS-19, RS-20, RS-21 de la première revue restent ouverts (RS-17 est corrigé).
2. Trusted Types non imposés (filtrage en direct par `DOMParser`) ; garde-fou par test en attendant (D-3204).
3. Chemin PostgreSQL du débit et des révocations écrit mais non testé (suite sous SQLite).
4. Rendu OCR des PDF démesurés borné seulement par `RLIMIT_AS` du processus isolé.
5. HSTS sans `preload` (décision du fondateur).

Détail et propositions : `docs/backlog/securite.md`.
