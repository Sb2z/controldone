# Fiches de correspondance des exports de déclaration (SPEC §5.3.6)

Une fiche `<format_id>.yaml` par format ; l'ajout d'un format ne demande pas de code
(`controldone.ingest.structure.FicheCorrespondance`, chargées depuis ce dossier). Une fiche invalide
(champ cible absent du modèle `ChampsDeclaration`) est refusée au chargement et journalisée.

```yaml
format_id: mon_format            # identifiant stable (cité dans les avertissements d'extraction)
version: "1.0.0"
type: xml | csv
sous_type: export_xml | export_csv
detection:                       # tout doit correspondre
  racine: NomLocalRacine         # xml
  espace_noms: "urn:…"           # xml, facultatif
  colonnes_requises: [col, …]    # csv (« TYPE.col » en mode multi-enregistrements)
  marqueur: "regex"              # facultatif, cherché dans les 4 premiers Ko
  ignorer: [nom, …]              # éléments / colonnes connus sans champ (non journalisés)
xml: {espaces_noms: {d: "urn:…"}}
csv: {separateur: ";", separateur_decimal: ",", format_date: "%d/%m/%Y",
      multi_enregistrements: true, type_entete: ENTETE,   # « #TYPE;col… » déclare les colonnes d'un type
      commentaire: "#"}                                   # CSV à plat : lignes de commentaire ignorées (D-1802)
devise_par_defaut: EUR           # montants sans devise (sauf montant_total_facture / montant_facture_article,
                                 # exprimés dans devise_facture)
entete:                          # chemin du modèle -> XPath (relatif à la racine) ou colonne
  mrn: d:Entete/d:MRN
  montant_total_facture: {source: …, unite: EUR | source_unite: …}
  taux_change_sens: {source: …, valeurs: {1EUR: devise_par_eur}}   # valeur imprimée traduite (D-1802)
constantes: {chemin: valeur}     # valeur fixée par la définition du format
listes:                          # articles, taxations, documents_references
  taxations:
    source: d:Articles/d:Article/d:Taxations/d:Taxation      # xml : nœuds répétés
    type_enregistrement: TAXE                                # csv : type d'enregistrement
    cle: colonne                                             # csv à plat : dédoublonnage
    champs: {article: ../../@numero, type_taxe: "@type", …}
    enumerations: {taux_nature: "@nature"}                   # énumérations du modèle lues telles quelles
    requis: colonne                                          # élément retenu seulement si renseignée (D-1802)
  documents_references:
    eclater: {source: pieces, separateur: "|", motif: "(?P<c>[^:]+):(?P<r>.+)"}   # une cellule, n éléments
    champs: {type_code: c, reference: r}                     # sources = groupes nommés du motif
tables:
  categorie: {A00: droit, B00: tva, …}       # type_taxe -> categorie
  paiement: {A: comptant, E: differe, G: autoliquide}
```

Les indices d'autoliquidation (§5.3.2) sont déduits après lecture : document de code `1008` (numéro de
TVA en référence), référence `FR7…`, ligne de TVA de paiement `autoliquide`.
