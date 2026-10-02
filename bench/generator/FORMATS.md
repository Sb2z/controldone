# Formats d'export de déclaration du banc (X1 XML, X2 CSV)

Ce document est **public** : l'équipe « extraction et contrôles » peut le lire pour écrire ses fiches de
correspondance (`config/mappings/<format_id>.yaml`, SPEC §5.3.6). Il décrit seulement la forme des fichiers,
pas la manière dont le corpus est construit. Les deux formats sont **inventés** pour le banc ; ils ne
reproduisent aucun format réel de logiciel ou d'administration.

Conventions communes aux deux formats :

- encodage UTF-8 ; dates ISO `AAAA-MM-JJ` en XML, `JJ/MM/AAAA` en CSV ;
- montants en euros sauf `montant_total_facture` et `montant_facture` des articles, exprimés dans la
  **monnaie de facturation** déclarée ;
- les devises sans décimales (JPY, KRW) ont des montants sans partie décimale ;
- masses en kilogrammes à 3 décimales ;
- codes de type de taxe tels qu'« imprimés » : `A00` droits de douane, `B00` TVA, `A30`/`A35` droits
  antidumping, `X01` droit spécifique fictif, `FPE` droit forfaitaire petits envois (liste non limitative) ;
- mode de paiement : une lettre, `A` comptant, `E` paiement différé, `G` TVA autoliquidée ;
- taux de change : 5 décimales, avec un **sens** explicite :
  `devise_par_eur` (« 1 EUR = x unités de devise ») ou `eur_par_devise` (« 1 unité de devise = x EUR ») ;
  la devise concernée est donnée à part (`devise` / `devise_taux`) ;
- chaque fichier porte la mention « DONNÉES FICTIVES — DOCUMENT DE TEST ».

## X1 — export XML

Espace de noms : `urn:fictif:bench:declaration-export:1`, élément racine `DeclarationExport` (attribut
`version="1.0"`).

| Chemin | Sens |
|---|---|
| `Avertissement` | Mention de données fictives (texte, à ignorer) |
| `Entete/MRN` | MRN (18 caractères) |
| `Entete/LRN` | Référence locale du déclarant |
| `Entete/Version` | Rang de version (1 = initiale, 2 = rectifiée…) |
| `Entete/JeuDonnees` | `H1` |
| `Entete/TypeDeclaration` | Type de déclaration (`IM A`) |
| `Entete/DateAcceptation` | Date d'acceptation |
| `Entete/Importateur/Nom`, `/TVA`, `/EORI` | Importateur |
| `Entete/Declarant/Nom`, `/TVA` | Déclarant ou représentant |
| `Entete/ConditionsLivraison/@incoterm`, `/@lieu` | Incoterm et lieu |
| `Entete/PaysExpedition` | Pays d'expédition (ISO alpha-2) |
| `Entete/MonnaieFacturation` | Monnaie de facturation (ISO 4217) |
| `Entete/MontantTotalFacture` | Montant total facturé, dans la monnaie de facturation |
| `Entete/TauxChange` | Taux de change (absent si aucun taux n'est imprimé) ; attributs `sens` et `devise` |
| `Entete/MasseBruteTotale` | Masse brute totale (attribut `unite="KGM"`) |
| `Entete/NombreColisTotal` | Nombre total de colis |
| `Entete/NombreArticles` | Nombre d'articles |
| `DocumentsReferences/Document/@code`, `/@reference` | Documents produits : `N380` facture, `N325` pro forma, `N740` LTA, `N705` connaissement, `1008` autoliquidation (référence = numéro de TVA) |
| `Articles/Article/@numero` | Numéro d'article |
| `Article/CodeMarchandise` | Code marchandise (10 chiffres) |
| `Article/Designation` | Désignation |
| `Article/PaysOrigine` | Pays d'origine |
| `Article/CodePreference` | Code de préférence (lu, jamais jugé) |
| `Article/Regime`, `Article/RegimeComplementaire` | Régime |
| `Article/MontantFacture` | Montant facturé de l'article (monnaie de facturation) |
| `Article/ValeurStatistique` | Valeur statistique (EUR, informative) |
| `Article/MasseNette`, `Article/MasseBrute` | Masses de l'article |
| `Article/QuantiteSupplementaire` | Quantité en unités supplémentaires (attribut `unite`, ex. `p/st`, `pa`, `l`, `m`) ; absente si sans objet |
| `Article/NombreColis` | Colis de l'article |
| `Article/Taxations/Taxation/@type` | Code de type de taxe |
| `Taxation/@nature` | `ad_valorem` (taux en %) ou `specifique` (montant par unité) |
| `Taxation/BaseMontant` | Base d'imposition en EUR (ad valorem) |
| `Taxation/BaseQuantite` | Base en quantité (spécifique ; attribut `unite`) |
| `Taxation/Taux` | Taux tel qu'imprimé (pourcentage ou EUR par unité) |
| `Taxation/Montant` | Montant de la taxe |
| `Taxation/MontantAPayer` | Montant à payer (0 si la ligne est autoliquidée) |
| `Taxation/ModePaiement` | Mode de paiement (`A`, `E`, `G`) |
| `Totaux/TotalParType/@type` | Total imprimé par type de taxe |
| `Totaux/TotalDroitsTaxes` | Total des droits et taxes |
| `Totaux/TotalAPayer` | Total à payer ou à garantir (hors TVA autoliquidée) |

Exemple abrégé :

```xml
<DeclarationExport xmlns="urn:fictif:bench:declaration-export:1" version="1.0">
  <Entete>
    <MRN>26FR0000000000000A</MRN>
    <MonnaieFacturation>USD</MonnaieFacturation>
    <MontantTotalFacture>12540.00</MontantTotalFacture>
    <TauxChange sens="devise_par_eur" devise="USD">1.12500</TauxChange>
  </Entete>
  <Articles>
    <Article numero="1">
      <CodeMarchandise>8471300000</CodeMarchandise>
      <Taxations>
        <Taxation type="A00" nature="ad_valorem"><BaseMontant>11146.67</BaseMontant><Taux>0</Taux>
          <Montant>0.00</Montant><MontantAPayer>0.00</MontantAPayer><ModePaiement>E</ModePaiement></Taxation>
      </Taxations>
    </Article>
  </Articles>
</DeclarationExport>
```

## X2 — export CSV

- séparateur `;`, fin de ligne CRLF, pas de BOM ; un champ contenant `;` ou `"` est entouré de guillemets ;
- **décimales à la française** (virgule), sans séparateur de milliers (`12540,00`) ;
- fichier **multi-enregistrements** : la première colonne donne le type d'enregistrement ; une ligne
  commençant par `#` est l'en-tête des colonnes de ce type et précède ses enregistrements.

| Type | Colonnes (après la colonne de type) |
|---|---|
| `ENTETE` | `mrn`, `lrn`, `version`, `date_acceptation`, `importateur_nom`, `importateur_tva`, `importateur_eori`, `declarant_nom`, `declarant_tva`, `incoterm`, `incoterm_lieu`, `pays_expedition`, `devise_facture`, `montant_total_facture`, `taux_change` (vide si aucun), `sens_taux`, `devise_taux`, `masse_brute_totale`, `nombre_colis_total`, `nombre_articles`, `total_droits_taxes`, `total_a_payer` |
| `DOCUMENT` | `code`, `reference` (mêmes codes que X1) |
| `ARTICLE` | `numero`, `code_marchandise`, `designation`, `pays_origine`, `code_preference`, `regime`, `montant_facture`, `valeur_statistique`, `masse_nette`, `masse_brute`, `quantite_supplementaire`, `unite_supplementaire`, `nombre_colis` |
| `TAXE` | `article` (vide = niveau déclaration), `type`, `base_montant`, `base_quantite`, `base_unite`, `taux`, `nature_taux`, `montant`, `montant_a_payer`, `mode_paiement` |
| `TOTAL` | `type`, `montant` (total imprimé par type de taxe) |
| `COMMENTAIRE` | `texte` (mention de données fictives, à ignorer) |

Exemple abrégé :

```
#ENTETE;mrn;lrn;version;date_acceptation;…;devise_facture;montant_total_facture;taux_change;sens_taux;devise_taux;…
ENTETE;26FR0000000000000A;LRN-0000000;1;14/08/2026;…;USD;12540,00;1,12500;devise_par_eur;USD;…
#DOCUMENT;code;reference
DOCUMENT;N380;INV-2026-0000
#TAXE;article;type;base_montant;base_quantite;base_unite;taux;nature_taux;montant;montant_a_payer;mode_paiement
TAXE;1;A00;11146,67;;;0;ad_valorem;0,00;0,00;E
```

## Autres formats structurés présents dans le corpus

- **Factur-X** (PDF/A-3 + XML CII D16B, profil EN 16931) : factures et avoirs d'un transitaire ; les MRN et
  références de transport sont dans `ApplicableHeaderTradeAgreement/AdditionalReferencedDocument`
  (`TypeCode` 916, `Name` = `MRN` ou `LTA/BL`) et dans la note de ligne ; catégorie TVA `E` pour les débours,
  `S` pour les prestations ; le code de poste interne est dans `SpecifiedTradeProduct/SellerAssignedID`.
- **CII seul** (profil EXTENDED) et **UBL 2.1** : factures commerciales de fournisseurs ; code SH dans
  `DesignatedProductClassification/ClassCode` (CII) ou `CommodityClassification/ItemClassificationCode`
  (UBL, `listID="HS"`), origine dans `OriginTradeCountry` / `OriginCountry`, frais de pied (fret,
  assurance, emballage, remise) en `SpecifiedTradeAllowanceCharge` / `AllowanceCharge`, Incoterm en
  `ApplicableTradeDeliveryTerms` (CII) ou `DeliveryTerms` (UBL), masses et nombre de colis en note
  d'en-tête, référence LTA/BL en document additionnel.
- **XLSX** : facture commerciale sur une feuille `Invoice` (en-tête en paires libellé / valeur, tableau des
  lignes, totaux de pied, masses et colis en bas) et une feuille `Notes`.
