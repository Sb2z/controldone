# Générateur n° 2 du banc — corpus de généralisation (`bench/generator2`)

Second générateur **indépendant** de dossiers synthétiques fictifs (SPEC §19). Le moteur a été réglé sur les
8 gabarits de transitaire et les 6 présentations de déclaration du premier générateur ; ce corpus sert à
mesurer la **généralisation** : autres transitaires (12 familles `G1`–`G12`), autres présentations de
déclaration (`M1`–`M6`), autres factures commerciales (langues, devises, mises en page) et autres
dégradations.

Salle blanche : écrit à partir de `docs/SPEC.md` seulement (et de `bench/generator/FORMATS.md` pour savoir que
des exports structurés existent). Il ne lit ni `src/`, ni `tests/`, ni le code de `bench/generator/`, ni les
corpus existants. Ce README est **réservé au banc** (il décrit les injections) ; l'équipe moteur ne lit que
`FORMATS.md`.

Tout est fictif et marqué « DONNÉES FICTIVES » sur chaque page / fichier : noms de sociétés fantaisistes
(« Imaginor », « Fictilog », « Simulacargo »…), SIREN `000…` valides au sens de Luhn, TVA FR à clé
`(12 + 3 × (SIREN mod 97)) mod 97`, EORI `FR` + SIREN + `00000`, MRN `AAFR` + 14 caractères, LTA à préfixe
`999`, IBAN tronqués « FICT ».

## Utilisation

```bash
source .venv/bin/activate
python -m bench.generator2 --out bench/corpus_g2 --split dev --count 300 --seed 777 --jobs 2
python -m bench.generator2 --out bench/corpus_g2 --split holdout --count 300 --seed 777 --jobs 2   # plus tard
python -m bench.generator2 --out /tmp/x --ids GX0002,GX0013     # quelques dossiers (essais)
python -m bench.generator2 --out /tmp/x --stats-only            # planification et couverture seulement
```

- `--split dev|holdout|all` : la **planification couvre toujours les `count` dossiers** ; générer un split
  plus tard redonne exactement les mêmes dossiers (octet pour octet, vérifié : deux exécutions et `--jobs 1`
  contre `--jobs 2` donnent les mêmes sha256).
- `--jobs` : 1 ou 2 processus (plafonné à 2 pour ménager la mémoire).
- Code retour 1 si l'auto-contrôle ou la validation de schéma signale un problème.
- Durée : environ 2 min pour les 232 dossiers dev avec `--jobs 2` (≈ 300 Mo).

Sorties (arborescence §19.2, même contrat que le premier corpus) :

```
bench/corpus_g2/
  clients/CL11..CL14/profil.json              # entités, transitaires, tolérances (vide = défauts)
  clients/CL11..CL14/grilles/GR-CLxx-Gy.json  # grilles validées (§6.2.4), une par transitaire du client
  dev/GX0001/truth.json, dev/GX0001/docs/...  # vérité + fichiers d'entrée (arborescence variable)
  manifest.json                               # dossiers générés, split, seed, version, sha256 de chaque fichier
  stats_generation.json                       # composition, couverture par contrôle (dev réalisé, holdout planifié)
```

- `dossier_id` : `GX` + 4 chiffres (`GX0001`…`GX0300`) ; split `holdout` si
  `int(sha256(dossier_id)[0:8], 16) % 5 == 0` (68 dossiers sur 300), sinon `dev` (232).
- Clients `CL11`–`CL14` : `CL11` groupe à 3 entités, `CL14` groupe à 2 entités, `CL12` et `CL13` mono-entité.

## Modules

| Module | Rôle |
|---|---|
| `util.py` | Décimaux (`ROUND_HALF_UP`), aléa déterministe `rng_for(seed, …)`, identifiants fictifs, formats de nombres et de dates |
| `world.py` | Clients, entités tierces, transitaires (une famille de mise en page par transitaire), fournisseurs, catalogues, libellés multilingues, grilles tarifaires |
| `model.py` | Construction des documents : facture commerciale, déclaration (articles, taxations, totaux), facture du transitaire (débours, FAF, TVA, totaux), avoir |
| `plan.py` | Répartition des injections sur les 300 dossiers (exigences de compatibilité, groupes exclusifs, dossiers partenaires F2/F3/F5), puis attributs (client, famille, présentation, dégradation, scénarios) |
| `build.py` | Dossier complet : injections (§19.5), pièges (§19.3.1), niveaux attendus mécaniques, liens attendus, modes de dégradation |
| `render_ci.py`, `render_decl.py`, `render_ft.py`, `render_misc.py` | Rendus PDF / XML / CSV / XLSX / EML |
| `pdfkit.py` | Outils reportlab déterministes (`invariant=1`, polices TTF embarquées, tampons, filigranes, écriture manuscrite simulée, texte caché) |
| `degrade.py` | Scan, photo de téléphone, faible contraste, JPEG, rotation, télécopie, TIFF multipage (PIL seul) |
| `emit.py` | Plan de fichiers (arborescence, PDF fusionnés, copie F1, consigne cachée), rendu, auto-contrôle, dégradation, écriture, `truth.json` |
| `truth.py` | `truth.json` (Annexe B), valeurs de vérité, auto-contrôle « chaque valeur est imprimée », validation `jsonschema` |
| `truth.schema.json` | Annexe B étendue : `GX`, familles `G1`–`G12`, présentations `M1`–`M6`, langues `de`, `it`, `nl` |
| `__main__.py` | CLI, profils clients, grilles, manifest, statistiques |

## Familles de transitaire (`transitaire_template`)

| Famille | Transitaire fictif | Caractéristiques |
|---|---|---|
| G1 | Fictilog Transit SAS (FR) | Paysage, TVA par ligne (colonnes HT / TVA / TTC), débours puis prestations, MRN par ligne |
| G2 | Placebo Freight Ltd (EN) | Relevé multi-envois (2–3 MRN), tableau `AWB / MRN / date`, tableau multipage avec en-têtes répétés et « carried forward / brought forward », TVA en récapitulatif par code (S/O) |
| G3 | Simulacargo GmbH (DE) | En-tête à deux colonnes entrelacées (client / facture), montants suffixés « EUR », format `1.234,56`, TVA en récapitulatif |
| G4 | Spedizioni Immaginarie Srl (IT) | Bloc des totaux **en tête**, montants préfixés « € », codes TVA `E15` / `20%` par ligne |
| G5 | Tránsitos Ficticios SL (ES) | Prestations en page 1, **annexe des débours** (suplidos) en page 2 |
| G6 | Demofret SAS (FR) | Net à payer en tête, ligne « droits et taxes » **combinée**, remise **négative**, tampon « ACQUITTÉ » sur les totaux, pas de total des débours |
| G7 | Virtuafret SAS | **UBL 2.1 seul** (sans PDF) |
| G8 | Pseudotrans Douane SARL | **CII D16B seul** (sans PDF), pas de total des débours |
| G9 | Mirage Douane & Fret (FR) | Codes TVA lettres (A/E), filigrane « COPIE », annotations **manuscrites** simulées |
| G10 | Chimera Customs Brokers Ltd (EN) | Corps à deux colonnes, montants suffixés « EUR », quantité et montant sans prix unitaire |
| G11 | Nebula Express Fictif (FR/EN) | Intégrateur express bilingue, forfait petits envois avec base imprimée (« 3,00 × n ») |
| G12 | Schaduw Expeditie B.V. (NL) | Factures de **débours** et de **prestations** séparées pour un même envoi |

## Présentations de déclaration (`declaration_layout`)

| Code | Présentation | Format (`documents[].format`) |
|---|---|---|
| M1 | H1 imprimé par articles sur **deux pages** avec page de continuation (« Suite — déclaration MRN … ») | PDF |
| M2 | Édition tabulaire **paysage** d'un logiciel fictif (police à chasse fixe) | PDF |
| M3 | **Certificat de dédouanement en anglais** d'un commissionnaire, tampon « RELEASED » | PDF |
| M4 | **Corps de courriel** texte (« bon à enlever ») | `eml` |
| M5 | Export **XML** propre (schéma inventé, attributs) | `xml_declaration` |
| M6 | Export **CSV** `;`, virgule décimale, ligne de commentaire en tête, une ligne par taxation | `csv_declaration` |

Les H7 (petits envois, droit forfaitaire `FPE`) existent en M1, M3–M6.

## Factures commerciales

Mises en page `CA` (anglais standard), `CB` (allemand, Suisse, `1'234.56`), `CC` (italien), `CD` (néerlandais,
Aruba), `CE` (espagnol, Mexique), `CE2` (anglais/turc), `CF` (chinois bilingue, total en lettres, cachet),
`CG` (totaux en tête, pro forma), `CH` (français, Suisse), `CK` (tableur XLSX), `CU` (UBL 2.1). Devises : USD,
EUR, **CNY, JPY, GBP, CHF, KRW, INR, TRY**. Pièges de lecture : codes SH à 6, 8 ou 10 chiffres avec
ponctuations variées, origine en en-tête ou par ligne, fret / assurance / emballage / remise en pied, mention
du transitaire comme mode d'expédition, pro forma.

## Dégradations

`documents[].degradation` (classe §19.6) et `degradation_mode` (détail) :

| Classe | Modes |
|---|---|
| d0 | `native` (PDF natif) ; `structured` (XML, CSV, XLSX, EML) |
| d1 | `scan300` (300 dpi, JPEG 85), `scan250j` (250 dpi, JPEG 78) |
| d2 | `skew200` (inclinaison 1–3°, taches, dernière page tournée), `photo` (photo de téléphone : perspective, fond, ombre, flou ; JPEG seul si une page), `lowcontrast`, `jpeg150` (artefacts JPEG forts), `tiff200` (TIFF multipage LZW), `rotated` (pages à 90°/270°) |
| d3 | `fax` (binarisé, demi-résolution verticale, stries, en-tête de télécopie), `faxtiff` (idem en TIFF CCITT G4) |

Un PDF fusionné peut mêler pages natives et pages scannées (la dégradation est portée par chaque document
logique) ; la classe du dossier est la pire classe de ses documents.

## Erreurs injectées, niveaux et pièges

- Catalogue §19.5 ; codes supplémentaires : `ordre_grandeur_incoherent` (A7), `reference_produit_absente`
  (A15), `colis_articles_incoherents` (B5), `avoir_sans_ecart` (E5). Erreurs **induites** enregistrées
  aussi : C6 dès qu'un excédent de débours change le FAF, E5 avec `avoir_excessif`, P1 avec
  `faux_document_facture`.
- `accepted_control_ids` copiés de l'Annexe A (`build.ANNEXE_A`), jamais inventés.
- `expected_level` calculé mécaniquement (`build.expected_level`, §19.3.1) : contrôle éligible (Annexe A) ;
  tous les documents concernés en `d0`/`d1` ou structurés (et, pour F3, la facture de l'autre dossier) ;
  `|écart| ≥ 3 ×` seuil de certitude (valeur entièrement différente pour les contrôles sans montant) ; pas de
  substitution de la classe de confusion §8.5.4 ; référence de facture citée (A) et MRN cités (C, F, G4, G5) ;
  C6 seulement si l'excédent dont il dépend est lui-même certain ; A6 seulement si la devise vient d'un
  document natif ou structuré ; D2/D7 seulement si la grille interdit les prestations hors grille.
- Montants (`expected_amount_eur`) selon §8.6, `ROUND_HALF_UP`, signés ; `null` pour `aucun` / `renvoi`, et pour
  A4 en devise sans taux imprimé. Les écarts recouvrables sont nets des avoirs (E6 remplace C1).
- Pièges (§19.3.1) : arrondi de 0,03 EUR sur les droits, conversion légitime au taux imprimé, taux dans le sens
  « 1 devise = x EUR », TVA autoliquidée non refacturée, facture complémentaire légitime, fret expliquant A4,
  codes à 6 chiffres sur la facture, pro forma, référence tronquée compatible, transitaire cité comme mode
  d'expédition, version rectificative (deux MRN de même préfixe), droits arrondis à l'euro, remise négative,
  références de transport avec espaces ou barres, base du forfait cohérente, FAF au minimum de la grille.
  Un piège qui contredirait une erreur injectée appariable (même contrôle accepté, mêmes documents) est retiré.
- Scénarios : PDF fusionnés, plusieurs factures pour une déclaration, une facture sur deux déclarations,
  relevés multi-MRN, autoliquidation, devises sans décimales, avoirs (dont avoir reçu deux fois), petits
  envois, factures électroniques, tableur, fichier en double (F1 : même octets sous un autre chemin), consigne
  cachée en texte blanc ou en commentaire (§20.2, sans effet attendu), dossiers sans erreur (≈ 20 %).

## Auto-contrôle

Pour chaque document, le rendu **natif** (avant dégradation) est relu (pypdf, lxml, openpyxl, e-mail) et
chaque valeur de vérité obligatoire (numéros, dates, devises, totaux, lignes, articles, taxations, MRN,
références…) doit y figurer sous l'une de ses écritures (`1 234,56`, `1,234.56`, `1.234,56`, `1'234.56`, dates
en toutes lettres…). Une valeur non imprimée est mise à `null` dans `truth_values` (ex. prix unitaire absent
des familles G2/G10, TVA de ligne absente des XML G7/G8). Chaque `truth.json` est validé contre
`truth.schema.json` (`jsonschema`, Draft 2020-12). Contrôles visuels : pages rendues en PNG (pypdfium2) et
examinées (familles G1–G12, M1–M6, photo, télécopie, TIFF) ; un garde-fou refuse tout tableau plus large que
la page.

## Écarts au contrat d'origine

- `dossier_id` `GX…` (l'Annexe B prévoit `BX…`), familles `G1`–`G12` et présentations `M1`–`M6` (l'Annexe B
  énumère `T1`–`T8`, `L1`–`X2`), langues `de`, `it`, `nl` : d'où `truth.schema.json` étendu. Le correcteur
  ne valide pas ces énumérations.
- Champs supplémentaires dans `documents[]` : `degradation_mode`, `ci_layout`, `declaration_layout`.
- Les erreurs F2–F5 portent `other_dossiers` ; leurs `documents` sont des `doc_id` **locaux** (le correcteur
  rapproche l'autre dossier par le type de document). La forme qualifiée `BX0043/ft1` n'est pas utilisée
  (l'expression du correcteur ne reconnaît que le préfixe `BX`).

## Corrections après revue du banc (version 2.0.1)

Revue de l'équipe contrôles sur le dev `corpus_g2` ; régénération complète (seed 777, mêmes identifiants, même
règle de split). Seuls les dossiers concernés changent (liste dans le compte rendu de régénération).

- **(b) `avoir_partiel` (E6)** : l'excédent de droits injecté n'était pas déclaré en C1 (seul E6 figurait). Le C1
  est désormais présent avec le montant **net de l'avoir** (§8.6, montant net des avoirs imputés) ; E6 porte le
  reste à recouvrer et ne s'ajoute pas aux totaux. L'erreur C6 induite (FAF calculé sur l'excédent) utilise
  l'excédent **brut** : l'avoir partiel crédite les droits, pas le FAF.
- **(c) A7 `ordre_grandeur_incoherent`** : en mode « déclaration en EUR sans taux imprimé », le taux était
  quand même imprimé (l'erreur devenait un A5 de fait). Le taux n'est plus imprimé quand `rate_printed` est faux
  (conversion faite au taux calculé, aléa consommé à l'identique) ; `taux_change` est alors `null` dans la vérité.
  `accepted_control_ids` reste celui de l'Annexe A (A7, A6).
- **(d) Dossiers appariés F2/F3/F5** : la facture commerciale copiée du dossier partenaire (F5) ou la facture de
  débours d'un autre envoi (F3) pouvait viser une autre entité du groupe que celle du dossier, créant un écart A1
  ou C8 non injecté (ex. GX0001). Le dossier reprend désormais l'entité du dossier partenaire.
