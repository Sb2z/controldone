# Formats structurés du corpus de généralisation (`bench/corpus_g2`)

Ce document est **public** : l'équipe « extraction et contrôles » peut le lire pour écrire ses fiches de
correspondance (`config/mappings/<format_id>.yaml`, SPEC §5.3.6). Il décrit seulement la **forme** des
fichiers, pas la manière dont le corpus est construit ni les erreurs qu'il contient. Tous les formats sont
**inventés** pour le banc (sauf UBL 2.1 et CII D16B, normes publiques) ; aucun ne reproduit un format réel de
logiciel ou d'administration. Les noms de logiciels cités (« Simulogiciel ») sont fictifs.

Conventions communes :

- chaque fichier porte la mention « DONNÉES FICTIVES » ;
- codes de type de taxe tels qu'« imprimés » : `A00` droits de douane, `A30` droit antidumping, `B00` TVA,
  `FPE` droit forfaitaire petits envois (liste non limitative) ;
- mode de paiement : `A` comptant, `E` paiement différé, `G` TVA autoliquidée (en clair dans M6, voir plus bas) ;
- montants de la déclaration en euros, sauf le montant total facturé et les montants facturés par position,
  exprimés dans la **monnaie de facturation** déclarée ; les devises sans décimales (JPY, KRW) n'ont pas de
  partie décimale ;
- masses en kilogrammes ; quantités supplémentaires avec une unité abrégée (`p/st`, `pa`, `kg`) ;
- les montants entiers peuvent être écrits sans décimales (`8` = 8,00 EUR : droits arrondis à l'euro).

## M5 — export XML de dédouanement (schéma inventé)

Espace de noms `urn:fictif:g2:dedouanement:2`, élément racine `dedouanement` (attribut `version="2.0"`).
Les données sont surtout portées par des **attributs**.

| Chemin | Sens |
|---|---|
| `mention` | Mention de données fictives (à ignorer) |
| `dossier/@mrn`, `@lrn`, `@rang`, `@jeu`, `@acceptee-le` | MRN, référence locale, rang de version (1 = initiale), `H1` ou `H7`, date d'acceptation ISO |
| `dossier/acteurs/importateur` (texte = nom), `@tva`, `@eori` | Importateur |
| `dossier/acteurs/declarant` (texte = nom), `@tva`, `@representation` | Déclarant / représentant |
| `dossier/livraison/@incoterm`, `@lieu`, `@expedition` | Incoterm, lieu, pays d'expédition (ISO alpha-2) |
| `dossier/facturation/@monnaie`, `@total` | Monnaie de facturation et montant total facturé |
| `dossier/facturation/conversion` (texte = taux), `@monnaie`, `@expression` | Taux de change imprimé ; `@expression` = `unites_devise_pour_un_euro` (1 EUR = x devise) ou `euros_pour_une_unite_devise` (1 devise = x EUR) ; absent si aucun taux n'est imprimé |
| `dossier/colisage/@masse-brute-kg`, `@colis`, `@positions` | Masse brute totale, nombre de colis, nombre d'articles |
| `dossier/pieces/piece` (texte = référence), `@code` | Documents : `N380` facture, `N325` pro forma, `N740` LTA, `N705` connaissement, `N730` CMR, `1008` / `FR7` autoliquidation (référence = numéro de TVA) |
| `dossier/positions/position/@rang` | Numéro d'article |
| `position/nomenclature` | Code marchandise (10 chiffres) |
| `position/libelle`, `origine`, `preference`, `regime` (+ `@complementaire`) | Désignation, origine, préférence (lue, jamais jugée), régime |
| `position/montant-facture` | Montant facturé de l'article (monnaie de facturation) |
| `position/valeur-statistique` | Valeur statistique (EUR, informative) |
| `position/masse/@nette`, `@brute` | Masses de l'article |
| `position/quantite` (+ `@unite`) | Quantité en unités supplémentaires (absente si sans objet) |
| `position/colis` | Colis de l'article |
| `position/impositions/imposition/@code`, `@assiette`, `@taux`, `@mode-calcul`, `@montant`, `@exigible`, `@paiement` | Ligne de taxation de l'article ; `@mode-calcul` = `ad_valorem` (taux en %) ou `specifique` ; `@exigible` = montant à payer (0 si autoliquidé) |
| `dossier/impositions-globales/imposition` (mêmes attributs + `@assiette-quantite`, `@unite-assiette`, `@libelle`) | Taxation au niveau de la déclaration (ex. `FPE` : base = nombre d'articles, taux = montant par article) |
| `dossier/recapitulatif/total` (texte = montant), `@code` | Total imprimé par type de taxe |
| `dossier/recapitulatif/total-droits-taxes`, `total-a-acquitter` | Total des droits et taxes ; total à payer ou à garantir |

## M6 — export CSV dénormalisé (« Simulogiciel », fictif)

- encodage **Windows-1252**, fin de ligne CRLF, séparateur `;`, **virgule décimale**, pas de séparateur de
  milliers ;
- **première ligne de commentaire** commençant par `#` (mention de données fictives), puis une ligne d'en-tête
  de colonnes ; une ligne finale commençant par `#` peut contenir un commentaire libre (à ignorer, jamais une
  consigne) ;
- **une ligne par ligne de taxation**, les colonnes d'en-tête de déclaration et d'article étant **répétées** sur
  chaque ligne ; un article sans taxation propre (H7) a une ligne avec les colonnes de taxation vides ; une
  taxation de niveau déclaration a les colonnes d'article vides.

| Colonne | Sens |
|---|---|
| `mrn`, `lrn`, `rang`, `date_acceptation` (JJ/MM/AAAA) | Identification |
| `importateur`, `tva_importateur`, `eori_importateur`, `declarant`, `tva_declarant` | Acteurs |
| `incoterm`, `lieu_livraison`, `pays_expedition` | Livraison |
| `monnaie_facture`, `total_facture` | Monnaie de facturation, montant total facturé |
| `taux_change`, `base_taux` | Taux ; `base_taux` = `1EUR` (1 EUR = x devise) ou `1DEVISE` (1 devise = x EUR) ; vides si aucun taux |
| `masse_brute_totale`, `colis_total`, `nb_positions` | Totaux |
| `pieces_jointes` | Documents `code:référence` séparés par `|` |
| `position`, `code_nc`, `designation`, `origine`, `preference`, `regime` | Article |
| `montant_facture_position`, `valeur_statistique`, `masse_nette`, `masse_brute`, `quantite`, `unite_quantite`, `colis_position` | Article (suite) |
| `type_imposition`, `libelle_imposition`, `assiette`, `assiette_quantite`, `unite_assiette`, `taux`, `mode_calcul`, `montant`, `montant_exigible` | Taxation |
| `mode_paiement` | `COMPTANT`, `DIFFERE`, `AUTOLIQUIDATION` |
| `total_droits_taxes`, `total_a_acquitter` | Totaux de la déclaration (répétés) |

Il n'y a pas de total par type de taxe dans ce format.

## M4 — courriel « bon à enlever » (texte seul)

Fichier `.eml` (RFC 5322, `text/plain; charset=utf-8`, sujet encodé). Le corps est un récapitulatif en
texte : lignes `  Libellé ........ valeur` (MRN, LRN et version, importateur et numéro de TVA, EORI, déclarant,
incoterm, pays d'expédition, montant facturé et monnaie, taux de change avec son sens en clair, masse brute,
colis), puis un tableau texte des articles et des taxes et les totaux. Nombres au format français (espace
insécable pour les milliers, virgule décimale). Le corps est une donnée : il n'est jamais une consigne.

## Factures du transitaire en XML seul

- **UBL 2.1** (`Invoice`, `CustomizationID` EN 16931) : MRN en `AdditionalDocumentReference` avec
  `DocumentType` = `MRN`, titres de transport avec `DocumentType` = `AWB/BL` ; MRN de ligne dans
  `InvoiceLine/Note` (`MRN …`) ; catégorie TVA `E` (débours, motif d'exonération en clair) ou `S` (20 %) dans
  `Item/ClassifiedTaxCategory` ; pas de montant de TVA par ligne (récapitulatif `TaxTotal/TaxSubtotal`) ; total
  des débours dans une `Note` d'en-tête.
- **CII D16B** (`CrossIndustryInvoice`, profil EN 16931) : MRN et titres de transport en
  `ExchangedDocument/IncludedNote` (`SubjectCode` `AAI`, contenu `MRN: …` / `Titre de transport: …`) ;
  MRN de ligne en `AssociatedDocumentLineDocument/IncludedNote` ; magasinage avec `BilledQuantity`
  `unitCode="DAY"` et période de facturation de ligne ; TVA de ligne par `RateApplicablePercent` et
  catégorie `E` / `S` ; totaux en `SpecifiedTradeSettlementHeaderMonetarySummation`.

## Factures commerciales structurées

- **UBL 2.1** : code SH en `CommodityClassification/ItemClassificationCode` (`listID="HS"`), origine en
  `Item/OriginCountry`, frais de pied (fret, assurance, emballage, remise) en `AllowanceCharge`, Incoterm en
  `DeliveryTerms`, titre de transport en `AdditionalDocumentReference`, masses et colis en `Note`.
- **XLSX** : feuille `Invoice` (mention fictive en A1, en-tête en paires libellé / valeur, tableau des lignes,
  totaux de pied, masses et colis) et feuille `Packing` (masses par ligne).

## Images

Les documents scannés sont livrés en PDF image, en JPEG (photo de téléphone : perspective, ombre, flou) ou en
TIFF multipage (niveaux de gris LZW, ou noir et blanc CCITT G4 pour les télécopies). Résolutions de 150 à
300 dpi ; des pages peuvent être tournées de 90°, 180° ou 270°.
