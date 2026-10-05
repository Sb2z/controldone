# ControlDOne v2 — Robustesse aux entrées hostiles

Campagne d'octobre 2026 : entrées cassées, hostiles ou inhabituelles, passage par le point de dépôt web, essai
d'endurance sur la file de jobs. Décisions : D-1600 à D-1608 (`docs/DECISIONS.md`, section « Robustesse »).
Limites de référence : SPEC §20.3 (50 Mo par fichier, 500 Mo par lot, 300 pages par fichier ; archives :
profondeur ≤ 5, 2 000 entrées, taux ≤ 100, 1 Go décompressé) et §20.6 (une erreur sur un fichier n'arrête jamais
le lot).

## 1. Critère

Chaque entrée doit finir dans l'un de ces états :

| Issue | Sens |
|---|---|
| `traite` | au moins un fichier lu (pages produites) ; le reste éventuellement refusé ou listé non lu |
| `refuse` | refusé à la réception avec un motif explicite (`corrompu`, `protege`, `vide`, `trop_gros`, `non_supporte`, `archive_dangereuse`…) |
| `non_lu` | accepté puis listé dans les documents non lus avec un motif (`document_non_reconnu`, `aucun_dossier`…) |

Sont des **défauts** : `plantage` (exception non rattrapée, ou rattrapée par le pipeline au prix de la réception
entière), `delai` (au-delà du délai), `memoire` (au-delà du plafond), `silencieux` (ni traité, ni refusé, ni
listé : fichier disparu).

## 2. Outillage (`scripts/fuzz/`, échantillons hors git sous `var/fuzz/`)

| Script | Rôle |
|---|---|
| `generer.py` | 269 échantillons en 11 catégories (graine fixe, tout est FICTIF) et 300 mutations aléatoires de fichiers de `bench/corpus/dev` (écrasement, insertion, suppression, duplication, inversion de bits, troncature, mélange) |
| `campagne.py` | un processus par cas (`executer_un.py` : réception → pages → classement → extraction → contrôles), mesures externes |
| `reception_seule.py` | étape 1 seule (exécutée dans le processus web lors d'un dépôt) |
| `web_depot.py` | dépôts réels sur `POST /api/v1/lots` d'un serveur neuf (répertoire temporaire, port libre, arrêt à la fin) |
| `endurance.py` | dossiers déposés par `services.depot.deposer` puis traités par un `Worker` de la file en base (chemin du web) |

Garde-fous de la machine (D-1608) : chaque cas tourne sous `RLIMIT_AS` = 1 500 000 000 octets (hérité par les
processus de pages, qui ne peuvent pas le relever), délai 900 s, plafond de mémoire résidente de l'arbre de
processus 3 Go, **au plus 2 cas en parallèle** ; les bombes sont des petits fichiers compressés écrits en flux,
jamais matérialisés. Une première campagne sans ces garde-fous (3 cas parallèles, arbre jusqu'à 3,2 Go par cas) a
épuisé la mémoire du conteneur.

Le plafond de 1,5 Go est **plus strict** que celui de production (3 Go par processus de pages) : un fichier qui
aurait besoin de plus finirait `non_lu` (page illisible, motif du processus), jamais en défaut.

## 3. Catégories couvertes

| Catégorie | Exemples |
|---|---|
| `pdf_casse` (25) | tronqué à 10/50/90/99 %, en-tête seul, sans xref, `startxref` hors fichier ou négatif, xref décalée ou illisible, sans trailer, racine absente, arbre de pages en boucle, objet qui se référence, `/Count` mensonger, `/Length` faux, filtre inconnu, Flate corrompu, bombe de flux (200 Mo de zéros), 200 000 objets, 2 M d'opérateurs, dictionnaires et tableaux imbriqués, `/Prev` en boucle |
| `pdf_chiffre` (10) | mot de passe utilisateur RC4-40/128, AES-128/256 ; propriétaire seul ; `/Encrypt` invalide ou à filtre inconnu |
| `pdf_actif` (8) | JavaScript, annotation JS, `/Launch`, URI et SubmitForm, formulaire, pièces incorporées, XFA avec XXE, texte invisible d'injection |
| `pdf_taille` (17) | 0 page (deux formes), 2 000 pages, 300 et 301 pages, A0, A0 scanné, 1 pt × 5 m, 5 m × 1 pt, MediaBox géante/nulle/négative, `UserUnit` 75, 20 000 lignes, image intégrée bombe |
| `image` (36) | bombe 30 000 × 30 000, A0 600 dpi, 1 × 60 000 000 (IHDR), 9 000 × 9 000, CMJN (JPEG, TIFF), 16 bits (gris, RGB, RGBA), alpha, palette, flottant, entier 32, bitonal, TIFF 300/301/500 pages, IFD en boucle, TIFF tronqué, JPEG corrompu (scan, SOF géant, sans EOI, tronqué, en-tête seul), PNG tronqué ou à dimensions nulles, GIF animé, BMP, WebP |
| `tableur` (16) | `.xlsm` à macros (et nommé `.xlsx`), formules, lien externe, XXE dans `sharedStrings`, « milliard de rires », bombe de 1 Go, 16 384 colonnes × 200 000 lignes, dernière cellule `XFD1048576`, 1 000 feuilles, sans feuille, classeur tronqué ou cassé, stocké sans compression, faux `.xls`, ODS à répétitions |
| `csv` (26) | UTF-8 BOM, UTF-16 LE/BE avec ou sans BOM, UTF-32, UTF-7, cp1252, latin-1, Shift-JIS, surrogates invalides, octets NUL, tout NUL, CR seul, CRLF, guillemets ouverts ou alternés, injection de formule, une ligne de 10 Mo (trois variantes), 500 000 lignes, 100 000 colonnes, binaire nommé `.csv` |
| `xml` (23) | XXE fichier, paramètre et réseau, DTD externe, XInclude, PI XSLT, milliard de rires, explosion quadratique, imbrication 100 000 et CII à 5 000 niveaux, 100 000 attributs, attribut de 20 Mo, CDATA géant, texte de 30 Mo, NUL, encodage inconnu ou menteur, UTF-16, CII valide et tronqué, UBL à 100 000 espaces de noms |
| `eml` (46) | 10 000 en-têtes, en-tête géant, 5 000 pièces, multipart imbriqué 50/500/5 000, `message/rfc822` imbriqué 60, courriel dans courriel ×12, frontière absente, base64 et QP invalides, 9 jeux de caractères exotiques, 18 noms de pièce hostiles (traversée, RFC 2231, encoded-word), pièce ZIP-slip, HTML seul |
| `zip` (30) | ZIP slip, chemin absolu, antislash, lien symbolique, 2 000/2 001/100 000 entrées, imbriqué 4/6/10, zip → eml → zip → eml, bombe 1 Go, bombe masquée par de l'aléa, 42.zip réduit, taille annoncée fausse, entrées chevauchantes, chiffré, méthode inconnue, bzip2, LZMA, noms en double ou Unicode, quasi-quine, vide, répertoires seuls, EOCD seul, corrompu, tronqué, préfixé |
| `type_menteur` (32) | PDF nommé `.csv/.png/.xlsx`, ELF/EXE/HTML/script nommés `.pdf`, polyglotte PDF+ZIP, magie seule, magie tardive, 7z, rar, tar, gzip, docx, SVG à script, nom `nom;$(id);\`id\`.pdf`, nom RTL `‮`, nom de 255 caractères, fichiers de 0 et 1 octet |
| `mutations` (300) | fichiers de `bench/corpus/dev` (PDF, CSV, XML) altérés aléatoirement |
| `extra` (2) | CSV de 49 Mo, XML de 49 Mo à 1,6 million d'éléments |

## 4. Résultats de la campagne

| Issue | Avant (569 cas) | Après (571 cas) |
|---|---:|---:|
| traite | 292 | 289 |
| refuse | 155 | 163 |
| non_lu | 118 | 119 |
| **plantage** | **1** | **0** |
| **silencieux** | **3** | **0** |
| delai / memoire | 0 | 0 |

Par catégorie (après) :

| Catégorie | traite | refuse | non_lu | défauts |
|---|---:|---:|---:|---:|
| csv | 0 | 11 | 15 | 0 |
| eml | 21 | 15 | 10 | 0 |
| extra | 0 | 1 | 1 | 0 |
| image | 25 | 11 | 0 | 0 |
| mutations | 173 | 59 | 68 | 0 |
| pdf_actif | 7 | 0 | 1 | 0 |
| pdf_casse | 10 | 15 | 0 | 0 |
| pdf_chiffre | 4 | 6 | 0 | 0 |
| pdf_taille | 12 | 4 | 1 | 0 |
| tableur | 8 | 5 | 3 | 0 |
| type_menteur | 14 | 17 | 1 | 0 |
| xml | 4 | 1 | 18 | 0 |
| zip | 11 | 18 | 1 | 0 |

Durée et mémoire (après) : p95 10 s par cas, maximum 340 s (TIFF de 300 pages entièrement OCRisé ; délai
configuré pour 300 pages : 30 + 60 × 300 s) ; mémoire résidente de l'arbre ≤ 1,75 Go (avant : 3,2 Go, des
processus de pages tués au délai sur des tableurs et des XML géants).

Changements d'issue entre avant et après :

| Échantillon | Avant | Après | Correctif |
|---|---|---|---|
| `zip/zip_corrompu.zip` | plantage (`zlib.error`, réception du lot perdue) | refusé `corrompu` | D-1600 |
| `zip/zip_vide.zip`, `repertoires_seuls.zip`, `zip_eocd_seul.zip` | silencieux | refusés `vide` | D-1600 |
| `tableur/bombe_1Go.xlsx` | lu jusqu'au délai (129 s) | refusé `archive_dangereuse` | D-1602 |
| `eml/multipart_imbrique_50/500.eml` | non lu | refusé `corrompu` (imbrication > 40) | D-1603 |
| `tableur/16384_colonnes_200k_lignes.xlsx`, `derniere_cellule.xlsx` | 93 s / 79 s, 3,2 Go, page illisible au délai | 3 s / 2 s, 0,24 Go, lus (bornés), non reconnus | D-1604 |
| `xml/texte_30Mo.xml` | 90 s, 3,2 Go, page illisible au délai | 57 s, 0,82 Go, lu | D-1604 |

Après D-1607 (voir § 6), nouvelle passe des catégories concernées (`xml`, `csv`, `tableur`, `extra` : 67 cas) :
issues identiques (12 traités, 18 refusés, 37 non lus, 0 défaut), mais mémoire maximale du processus principal
1 409 → 471 Mo (`xml_49Mo_lignes.xml` : 1 409 → 330 Mo, 64 → 8 s ; `texte_30Mo.xml` : 747 → 471 Mo, 57 → 13 s),
arbre ≤ 659 Mo, aucun cas au-delà de 13 s. Le texte extrait des XML hostiles (XXE fichier, paramètre et réseau,
XInclude, DTD externe, milliard de rires) ne contient aucune entité résolue.

Points vérifiés en particulier :

- PDF chiffrés : mot de passe utilisateur (RC4-40/128, AES-128/256) → refusé `protege` ; propriétaire seul → lu
  (aucun mot de passe à deviner) ; `/Encrypt` invalide ou à filtre inconnu → refusé `corrompu`.
- PDF actifs : rien n'est exécuté (pdfplumber/pdfium sans JavaScript ni actions) ; le texte invisible n'est
  jamais utilisé pour classer (§20.2).
- XML : entités jamais résolues, ni réseau ni DTD (`resolve_entities=False`, `no_network`, `load_dtd=False`) ;
  milliard de rires et explosion quadratique sans effet.
- ZIP : traversée, chemin absolu, antislash et lien symbolique refusés `archive_dangereuse` pour l'entrée, les
  autres entrées lues ; 2 001 et 100 000 entrées, imbrication > 5, bombes : archive refusée en entier sur ses
  tailles **annoncées**, puis lecture en flux bornée (taille annoncée fausse → refus).
- PDF de 2 000 et 301 pages, TIFF de 301 et 500 pages : refusés `trop_gros` (plus de 300 pages) ; 300 pages :
  lus ; 0 page (deux formes) : refusé `vide`.

## 5. Point de dépôt web

`web_depot.py` : 80 échantillons tirés au hasard (graine 1606) parmi les échantillons et mutations, envoyés à
`POST /api/v1/lots` d'un serveur neuf (`controldone serve`, worker intégré, base et coffre temporaires, port libre,
arrêt en fin d'essai).

| Mesure | Valeur |
|---|---|
| Réponses | 80 × `201` (refus de réception portés par le lot, jamais une erreur HTTP) |
| Dépôt le plus long | 0,95 s |
| Lots | 57 `traite`, 23 `en_erreur` (tous leurs fichiers refusés avec motif : 13 `corrompu`, 6 `non_supporte`, 3 `archive_dangereuse`, 2 `vide`, 1 `trop_gros`) |
| Jobs | 57 `done`, 0 `dead`, aucune `last_error` |
| Serveur | vivant du début à la fin, mémoire résidente maximale 255 Mo, 0 trace d'exception dans le journal |

## 6. Défaut trouvé pendant cette reprise : étape 3 sur une page démesurée (D-1607)

Le pic du processus principal (qui est, en production, le worker) venait de l'étape 3, hors du processus isolé :
l'arbre lxml d'un XML à 1,6 million d'éléments (~1 Go) puis la normalisation de 25 Mo de texte pour le classement
(~1 Go de plus). Bornes ajoutées dans `ingest/decoupage.py` : pas d'analyse structurée au-delà de 1 000 000 de
balises ; classement sur un extrait de la page (1 000 000 de caractères, 20 000 lignes de 10 000 caractères). Le
texte complet reste celui de la page. Mesures (processus principal, sans plafond) :

| Échantillon | Avant | Après |
|---|---|---|
| XML 49 Mo, 1,6 M d'éléments | 2,6 Go, 61 s | 0,39 Go, 8 s |
| XML texte de 30 Mo sur une ligne | 1,0 Go | 0,46 Go |
| XML attribut de 20 Mo | 0,38 Go | 0,24 Go |

## 7. Endurance (file de jobs, chemin du web)

`endurance.py` : 5 passages des 202 dossiers de `bench/corpus/dev` = **1 010 dossiers**, chacun déposé par
`services.depot.deposer` (un client neuf par passage, donc aucun doublon) puis traité par un unique `Worker`
de longue durée sur la file en base (job `traiter_lot`, base SQLite et coffre chiffré neufs ;
`CONTROLDONE_PAGES_PARALLELE=2`, processus sous `RLIMIT_AS` 4 Go). Résultat : 1 010 jobs `done`, 0 nouvel
essai, 0 `dead`, 7 959 s (7,9 s par dossier).

| Dossiers | RSS worker (Mo) | fd ouverts | fils | enfants | fichiers temporaires | base (Mo) | coffre (Mo) | objets Python |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 90 | 7 | 1 | 0 | 0 | 0,5 | 0 | 108 014 |
| 100 | 163 | 11 | 1 | 2 | 2 | 50 | 262 | 145 278 |
| 200 | 168 | 11 | 1 | 2 | 2 | 99 | 263 | 145 411 |
| 300 | 171 | 11 | 1 | 2 | 2 | 144 | 525 | 145 337 |
| 400 | 168 | 11 | 1 | 2 | 2 | 190 | 527 | 145 247 |
| 500 | 171 | 11 | 1 | 2 | 2 | 237 | 789 | 145 323 |
| 600 | 172 | 11 | 1 | 2 | 2 | 283 | 790 | 145 210 |
| 700 | 174 | 11 | 1 | 2 | 2 | 329 | 1 052 | 145 377 |
| 800 | 175 | 11 | 1 | 2 | 2 | 375 | 1 053 | 145 283 |
| 900 | 175 | 11 | 1 | 2 | 2 | 420 | 1 315 | 145 419 |
| 1 000 | 174 | 11 | 1 | 2 | 2 | 468 | 1 317 | 145 373 |

Lecture : après l'échauffement (imports, forkserver de pages : les 2 « enfants »), mémoire résidente,
descripteurs, fils, processus enfants, fichiers temporaires et objets Python sont **plats** sur 1 000 dossiers
(RSS 163 → 174 Mo, oscillation de ±4 Mo sans tendance après 300 dossiers). La base croît linéairement
(~0,46 Mo par dossier : pages, documents, constats, journal d'audit — données, non fuite) ; le coffre croît par
marches de 262 Mo à chaque passage (dépôt des fichiers d'un nouveau client), pas pendant le traitement.

## 8. Non-régression

- Banc dev (`bench_run --split dev --workers 2`) : seuil bloquant **passé**, précision certain 1,000, rappel
  0,813 (inchangés).
- `pytest -q` : 1 866 tests verts (dont 15 de `tests/ingest/test_ingest_robustesse.py`, un par défaut corrigé,
  fixtures minuscules générées dans le test) ; `ruff check src tests scripts` propre.

## 9. Rejouer

```bash
source .venv/bin/activate
python scripts/fuzz/generer.py --out var/fuzz/samples
python scripts/fuzz/generer.py --out var/fuzz/mutations --mutations 300 --corpus bench/corpus/dev
python scripts/fuzz/campagne.py var/fuzz/samples var/fuzz/mutations var/fuzz/extra --out var/fuzz/bilan.json
python scripts/fuzz/web_depot.py var/fuzz/samples var/fuzz/mutations --nombre 80 --out var/fuzz/web.json
CONTROLDONE_PAGES_PARALLELE=2 python scripts/fuzz/endurance.py --corpus bench/corpus/dev --passages 5 \
    --out var/fuzz/endurance.json
```

Ne jamais dépasser 2 cas en parallèle sur une machine partagée (`campagne.py` le borne).
