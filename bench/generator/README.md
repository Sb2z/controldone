# Générateur de corpus synthétique — banc ControlDOne v2

Ce paquet produit le corpus **fictif** du banc d'évaluation (SPEC §19) : dossiers d'import complets
(factures commerciales, déclarations, factures de transitaire, avoirs, documents support) avec des
erreurs injectées connues, des pièges, et une vérité `truth.json` par dossier (contrat §19.3, schéma
Annexe B).

> Salle blanche : ce code a été écrit à partir de `docs/SPEC.md` seulement, sans lire `src/`, `tests/`
> ni les anciens dépôts. L'équipe moteur ne lit ni ce répertoire ni `bench/corpus/holdout/`
> (seule exception : `FORMATS.md`, description publique des exports X1/X2).

## Utilisation

```bash
source .venv/bin/activate
# split dev seulement (le holdout est généré plus tard par l'orchestrateur)
python -m bench.generator --out bench/corpus --split dev --count 250 --seed 20261002
# plus tard, sans rien changer au dev :
python -m bench.generator --out bench/corpus --split holdout --count 250 --seed 20261002
# auto-contrôles (couverture holdout calculée par simulation si les fichiers holdout n'existent pas)
python -m bench.generator.check --corpus bench/corpus --seed 20261002 --count 250 --determinism
```

Options : `--split dev|holdout|all`, `--count` (dossiers BX0001…), `--seed`, `--jobs N` (processus
parallèles, résultat identique), `--only BX0001,BX0002` (sous-ensemble), `--plan-only` (affiche le plan).

- **Split** : `holdout` si `int(sha256(dossier_id)[0:8], 16) % 5 == 0`, sinon `dev` (48 holdout / 202 dev).
- **Plan global** : la composition et l'affectation des erreurs sont planifiées pour les 250 dossiers, à
  partir de `(seed, count)` seulement, avant toute génération ; chaque dossier a ensuite sa propre graine
  dérivée de `(seed, dossier_id)`. Générer `--split holdout` plus tard reproduit exactement le même plan.
- **Déterminisme** : même graine + même version ⇒ fichiers identiques octet pour octet (ReportLab
  `invariant=1`, dates fixes dans Factur-X et XLSX, JSON à clés triées, bruit d'image à graine fixe).
  Vérifié par `check.py --determinism` (deux générations en répertoires temporaires + comparaison au corpus).
- **Durée** : environ 95 s pour les 202 dossiers dev avec 4 processus (≈ 0,45 s par dossier et par cœur) ;
  ≈ 260 Mo (les PDF scannés représentent l'essentiel du volume).

Sorties (`bench/corpus/`) : `clients/<CLxx>/profil.json`, `clients/<CLxx>/grilles/<grille_id>.json`,
`<split>/<BXnnnn>/docs/…`, `<split>/<BXnnnn>/truth.json`, `manifest.json` (fusionné si l'on génère les
splits séparément), `README.md`.

## Ce qui est fictif

- 4 clients : `CL01` groupe à 3 entités, `CL02`, `CL03`, `CL04` (importateur de petits envois) ;
  noms suffixés « (FICTIF) », adresses inventées (« rue Imaginaire », « Villefictive »…).
- SIREN commençant par `000`, valides au sens de Luhn ; TVA FR = `FR` + clé `(12 + 3 × (SIREN mod 97)) mod 97`
  + SIREN ; EORI = `FR` + SIREN + `00000` ; MRN = `AAFR` + 14 caractères aléatoires ; LTA préfixe `999`,
  connaissements `DEMO…`.
- 8 transitaires « Transitaire Démo Alpha … Hotel (FICTIF) », un par gabarit T1–T8 ; vendeurs étrangers
  « … (FICTITIOUS / FICTICIO) » ; intégrateurs « Express Démo Kilo (FICTIF) » ; aucun nom réel de société
  ou de logiciel. IBAN « FR00 0000 … (FICTIF) », courriels en `.invalid`.
- Chaque page, XML, CSV ou courriel porte « DONNÉES FICTIVES — DOCUMENT DE TEST ».

## Modules

| Fichier | Rôle |
|---|---|
| `plan.py` | Plan global : split, gabarit, mise en page, dégradation, client, devise, scénarios, erreurs |
| `clients.py`, `refdata.py` | Clients, entités, transitaires, grilles §6.2.4 ; produits, vendeurs, taux indicatifs |
| `build.py` | Modèle exact (Decimal) : factures commerciales, déclarations, factures transitaire |
| `inject.py` | Injections du catalogue §19.5 (A, B, C, D, E, F, G, P) |
| `truth.py` | Conséquences mécaniques, imputation des avoirs, pièges, liens, valeurs vraies, niveaux, totaux |
| `render_ci.py`, `render_decl.py`, `render_ft.py`, `render_misc.py`, `pdfkit.py` | Rendu ReportLab |
| `structured.py` | UBL 2.1, CII (EXTENDED pour les fournisseurs), Factur-X EN 16931 (T7), X1 XML, X2 CSV, XLSX, EML |
| `degrade.py` | d1–d3 : rendu pypdfium2 300/200/150 dpi, inclinaison, bruit, rotation, binarisation, PDF image seule |
| `assemble.py` | Répartition en fichiers (PDF fusionnés, doublons), rendu, `truth.json` ; simulation sans écriture |
| `validate.py`, `truth.schema.json` | Schéma Annexe B (jsonschema) + règles du contrat (champs obligatoires, renvois) |
| `check.py` | Auto-contrôles, couverture, composition, déterminisme |

## Documents produits

- **Factures commerciales** en / fr / es, 3 mises en page, sous-types `facture`, `pro_forma`,
  `valeur_douane_seulement`, `facture_integrateur` ; pieds fret / assurance / emballage / remise ; formats de
  nombres `1 234,56`, `1.234,56`, `1,234.56`, `1'234.56`, JPY/KRW sans décimales ; codes SH à 6, 8 ou 10
  chiffres (ou absents) ; masses et colis imprimés près des totaux ; transporteur cité comme mode
  d'expédition ; totaux de page sur les factures multipages ; aussi en UBL, CII et XLSX.
- **Déclarations** : L1 H1 par articles (tableau de taxation A00/B00/A30/A35/X01, colonne MP, références
  N380/N325/N740/N705, `1008` + TVA en autoliquidation, taux à 5 décimales dans les deux sens), L2 preuve
  condensée (statut de paiement en petits entiers), L3 formulaire à cases numérotées inspiré du DAU vierge,
  L4 H7 avec droit forfaitaire `FPE` 3 EUR/article et référence `FR7`, X1 XML, X2 CSV (voir `FORMATS.md`) ;
  versions rectificatives (même préfixe MRN).
- **Factures transitaire** T1–T8 conformes au tableau §19.6 (T4 relevé 3 à 8 MRN tous inclus dans le
  dossier ; T5 deux factures ; T6 lettre + facture + copie de déclaration + CG dans un PDF ; T7 Factur-X
  validé XSD ; T8 bilingue dense, parenthèses sur les avoirs, références de transport avec espaces et barres) ;
  factures complémentaires légitimes ; **avoirs** (T7 en Factur-X type 381).
- **Support** : LTA / connaissement, liste de colisage, lettre d'accompagnement, conditions générales,
  courriel `.eml` contenant une fausse consigne (donnée, jamais instruction) ; **non exploitables** (P2) :
  pré-alerte, devis, bon de commande, liste d'expédition intitulés « invoice / facture ».

## Composition (250 dossiers planifiés ; dev mesuré sur fichiers)

| | Valeurs |
|---|---|
| Gabarits (250) | T1 31, T2 31, T3 31, T4 31, T5 31, T6 31, T7 32, T8 32 |
| Mises en page (250) | L1 46, L2 46, L3 45, L4 24, X1 45, X2 44 |
| Dégradation (250) | d0 100 (40 %), d1 63 (25 %), d2 50 (20 %), d3 37 (15 %) |
| Clients (250) | CL01 60, CL02 59, CL03 61, CL04 70 |
| Sans erreur | 73 / 250 (29 %) ; dev 59 / 202 |
| 2 erreurs ou plus | dev 135 / 202 (67 %) ; holdout 29 / 48 |
| Scénarios (dev, 202) | PDF fusionné 31 % ; plusieurs factures / déclaration 14 % ; facture sur plusieurs déclarations 8 % (9 % sur 250) ; facture transitaire multi-MRN 21 % ; autoliquidation 41 % ; devise étrangère 64 % (JPY/KRW 8 %) ; avoirs 14 % (15 % sur 250) ; petits envois 9 % (10 % sur 250) ; facture électronique 20 % ; tableur 5 % |

## Erreurs, niveaux et montants

- Une erreur = une entrée de `injected_errors` ; `accepted_control_ids` est copié de l'Annexe A.
- **Conséquences mécaniques** enregistrées comme erreurs (marquées `consequence_of`) quand un contrôle
  de la spécification se déclencherait forcément : C5 pour tout excédent de débours par composante
  (montant identique, hors totaux, cf. `doublon_composantes`), C6 quand les frais d'avance de fonds sont
  calculés sur des débours en excédent, G4 pour G5, G3 pour G2, C7 pour les refacturations F3/F4 (MRN
  d'un autre dossier), C8 pour A1, A4 pour F5, E5/E6 selon l'imputation déterministe des avoirs (§17.2).
- **Niveau attendu** (§19.3.1) : `ecart_certain` si le contrôle y est éligible (Annexe A ; D2/D7 hors
  grille seulement si la grille interdit les prestations hors grille), si tous les documents concernés sont
  d0/d1 ou structurés, si |écart| ≥ 3 × seuil de certitude (écart d'au moins 3 unités ou valeur entièrement
  différente pour les contrôles sans montant), si la valeur injectée n'est pas une substitution de la
  classe de confusion (§8.5.4) et si les liens sont explicites (référence de facture citée, MRN cité) ; C6
  n'est certain que si l'erreur de débours dont il dépend l'est ; un montant négatif est toujours
  `a_verifier`.
- **Montants** en EUR signés selon §8.6 (`ROUND_HALF_UP`, taux imprimé de la déclaration) ; montants nets
  des avoirs imputés ; `expected_totals` exclut les montants portés en double (C5, G5) et remplacés par E6.
- **Pièges** (`traps`) : arrondi sous tolérance (C1), droits arrondis à l'euro (B1), conversion légitime
  au taux imprimé (A5/A3), TVA autoliquidée non refacturée (C3), facture complémentaire (F3/C4), fret
  expliquant A4 (`a_verifier`), codes à 6 / 10 chiffres (A13), pro forma (P1/P2), référence tronquée
  compatible (A2), transporteur cité comme mode d'expédition (P1), montant combiné T3 (C1), relevé multi-MRN
  (C7), version rectificative (A4/C1), devises sans décimales (A4), poids près des totaux (A4), statut de
  paiement en entiers (B2), lettres de statut TVA (D1), parenthèses d'avoir (E4), factures débours /
  prestations séparées (F4), courriel avec consigne (P1).

## Couverture par contrôle

Erreurs injectées (dont attendues `ecart_certain`) ; dev mesuré sur les fichiers, holdout calculé par
simulation sans écrire de fichier (seed 20261002, count 250). Règles §19.6 respectées : chaque contrôle
A1–G6 a ≥ 6 erreurs dont ≥ 2 en holdout, et chaque contrôle éligible a ≥ 3 erreurs attendues certaines.

| Contrôle | dev | holdout | total |
|---|---|---|---|
| A1 | 5 (4) | 2 (2) | 7 |
| A2 | 5 (0) | 2 (0) | 7 |
| A3 | 5 (4) | 2 (1) | 7 |
| A4 | 11 (7) | 5 (3) | 16 |
| A5 | 5 (3) | 2 (2) | 7 |
| A6 | 5 (5) | 2 (0) | 7 |
| A7 | 5 (0) | 2 (0) | 7 |
| A8 | 5 (0) | 2 (0) | 7 |
| A9 | 5 (0) | 2 (0) | 7 |
| A10 | 5 (0) | 2 (0) | 7 |
| A11 | 5 (0) | 2 (0) | 7 |
| A12 | 5 (0) | 2 (0) | 7 |
| A13 | 5 (0) | 2 (0) | 7 |
| A14 | 5 (0) | 2 (0) | 7 |
| A15 | 5 (0) | 2 (0) | 7 |
| B1 | 5 (3) | 2 (1) | 7 |
| B2 | 5 (4) | 2 (2) | 7 |
| B3 | 5 (5) | 2 (2) | 7 |
| B4 | 5 (5) | 2 (2) | 7 |
| B5 | 5 (0) | 2 (0) | 7 |
| C1 | 6 (5) | 2 (1) | 8 |
| C2 | 6 (3) | 2 (1) | 8 |
| C3 | 5 (3) | 2 (2) | 7 |
| C4 | 6 (5) | 2 (1) | 8 |
| C5 | 29 (22) | 12 (9) | 41 |
| C6 | 16 (9) | 8 (2) | 24 |
| C7 | 12 (0) | 6 (0) | 18 |
| C8 | 10 (8) | 4 (3) | 14 |
| D1 | 5 (3) | 2 (2) | 7 |
| D2 | 5 (3) | 2 (1) | 7 |
| D3 | 6 (3) | 2 (2) | 8 |
| D4 | 5 (4) | 2 (2) | 7 |
| D5 | 5 (3) | 2 (2) | 7 |
| D6 | 5 (4) | 2 (2) | 7 |
| D7 | 5 (4) | 2 (2) | 7 |
| D8 | 5 (0) | 2 (0) | 7 |
| D9 | 5 (4) | 2 (1) | 7 |
| E1 | 8 (0) | 3 (0) | 11 |
| E2 | 6 (0) | 2 (0) | 8 |
| E3 | 5 (0) | 2 (0) | 7 |
| E4 | 5 (0) | 2 (0) | 7 |
| E5 | 22 (0) | 8 (0) | 30 |
| E6 | 6 (0) | 2 (0) | 8 |
| F1 | 5 (0) | 2 (0) | 7 |
| F2 | 5 (0) | 2 (0) | 7 |
| F3 | 4 (4) | 2 (2) | 6 |
| F4 | 4 (0) | 2 (0) | 6 |
| F5 | 5 (0) | 2 (0) | 7 |
| G1 | 5 (3) | 2 (1) | 7 |
| G2 | 5 (3) | 2 (2) | 7 |
| G3 | 9 (0) | 4 (0) | 13 |
| G4 | 9 (7) | 4 (4) | 13 |
| G5 | 5 (4) | 2 (2) | 7 |
| G6 | 5 (0) | 2 (0) | 7 |
| P1 | 9 (0) | 3 (0) | 12 |
| P2 | 5 (0) | 2 (0) | 7 |

## Limites connues

- Les mises en page sont inventées ; la variété visuelle reste inférieure à celle de vrais documents.
  L3 s'inspire de la structure publique du DAU vierge, sans en reproduire le formulaire officiel.
- Les codes de type de taxe autres que A00/B00 (`A30`, `A35`, `X01`, `FPE`) et les codes de mode de
  paiement (`A`, `E`, `G`, statut `0/1/7` en L2) sont fictifs ; leur sens est imprimé en légende.
- Plusieurs règles de la spécification laissent une part d'interprétation ; le générateur retient une
  lecture et l'applique mécaniquement : C8 rapporte le client facturé à l'importateur déclaré ; D4 et C6
  peuvent tous deux réagir au même excédent de frais d'avance de fonds (seul C6 est attendu) ; F2/F3/F4
  sont portés par le dossier le plus récent de la paire (`other_dossiers` = l'autre dossier) ; F5 et les
  doublons F1/E3 sont intra-dossier (`other_dossiers` vide pour F5).
- Les refacturations F3/F4 citent le MRN d'un autre dossier du même client ; elles produisent aussi C7
  (enregistré comme conséquence).
- Les avoirs créditent toujours partiellement un écart (E6) ou un montant sans écart (E5) : pas de cas
  « écart entièrement soldé par avoir ».
- Les pages dégradées sont des images (JPEG en d1/d2, binaire en d3) : aucune image TIFF/PNG isolée n'est
  produite (format `image` du contrat non utilisé).
- Les profils Factur-X sont validés par XSD (bibliothèque `factur-x`) mais pas par schematron ; le PDF de
  base ReportLab embarque ses polices mais n'est pas audité PDF/A (veraPDF non disponible).
- Le split holdout n'est pas écrit par défaut : sa couverture est calculée par simulation (`check.py`).
