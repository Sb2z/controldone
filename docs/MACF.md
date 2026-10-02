# Préparation des déclarations MACF (CBAM) en délégation

Module : `src/controldone/macf/` — données : `config/macf_codes_nc.yaml` — tests : `tests/macf/`.

> **Mention portée par chaque sortie : « préparation — à vérifier par le déclarant MACF autorisé ».**

## 1. Objet

Le mécanisme d'ajustement carbone aux frontières (MACF, en anglais CBAM) est entré dans sa période
définitive le 1er janvier 2026. Un importateur concerné passe par un **déclarant MACF autorisé**, qui dépose
la déclaration annuelle (première déclaration, pour l'année 2026, au 30 septembre 2027).

ControlDOne **prépare un pack de données** pour le client ou pour son déclarant MACF autorisé, à partir des
dossiers d'import que le client lui a déjà confiés :

1. **Sélection** (`selection.py`) : chaque article de déclaration dont le **code marchandise imprimé**
   commence par un code de la liste de l'annexe I (`config/macf_codes_nc.yaml`) est retenu. Un code imprimé
   trop court pour être départagé (par exemple « 7202 », face à l'exclusion « 7202 2 ») est retenu comme
   « à préciser ». Chaque ligne porte la mention « à faire vérifier » et sa provenance (déclaration, MRN,
   page).
2. **Agrégation** (`agregation.py`) : masse nette lue, par période (trimestre de la date d'acceptation
   imprimée), code imprimé, pays d'origine imprimé, fournisseur (nom du vendeur imprimé sur la facture
   commerciale du dossier) et installation (jamais lue sur ces documents : « à demander au fournisseur »).
3. **Seuil de 50 t** : cumul annuel des masses nettes lues, électricité et hydrogène exclus, comparé au seuil
   par une **simple soustraction**. Le texte produit est un calcul suivi de la phrase de renvoi exacte
   (`PHRASE_RENVOI`). Il ne dit jamais si le client est concerné ou non.
4. **Demandes aux fournisseurs** (`demandes.py`) : liste des données à obtenir (identification de
   l'installation, émissions intrinsèques directes et indirectes, valeurs réelles ou par défaut, voie de
   production, prix du carbone payé dans le pays d'origine, correspondance avec les livraisons) et un
   **brouillon** de demande par fournisseur, en français et en anglais, à la première personne du client.
   Les brouillons sont déposés dans la file sortante (`email_client`, statut `brouillon`, sans destinataire)
   et passent les garde-fous. Rien n'est envoyé : le client relit et envoie lui-même.
5. **Export** (`export.py`) : CSV (lignes, agrégats ; séparateur « ; », UTF-8 avec BOM), XLSX (synthèse,
   lignes, agrégats) et synthèse PDF. Mention en tête de chaque fichier et en bandeau sur chaque page du PDF ;
   phrase de renvoi et avertissement général (§3.4 de la spécification). Cellules commençant par `=`, `+`,
   `-` ou `@` neutralisées.

Usage :

```python
from datetime import date
from controldone.macf import (lignes_depuis_scope, preparer_pack, ecrire_pack,
                              brouillons_demandes, proposer_brouillons)

with db.tenant(client_id, acteur, lecture=True) as sc:
    lignes = lignes_depuis_scope(sc)
pack = preparer_pack(lignes, annee=2026, client="CLIENT FICTIF", date_preparation=date.today())
ecrire_pack(pack, "var/macf/cli_x/2026")
proposer_brouillons(FileSortante(db), brouillons_demandes(lignes, annee=2026, client="CLIENT FICTIF"),
                    acteur, tenant_id=client_id)
```

## 2. Ce que le module ne fait pas

- Il **ne dépose aucune déclaration MACF** et ne se connecte à aucun registre ou portail.
- Il **ne dit pas si le MACF s'applique** aux importations du client, ni si le seuil de 50 t le concerne :
  le cumul est un calcul sur les seules déclarations transmises à ControlDOne, pas sur toutes ses
  importations.
- Il **ne se prononce pas sur le classement** : la correspondance porte sur le code imprimé ; un code
  imprimé peut lui-même être à revoir.
- Il **ne calcule ni ne valide aucune valeur d'émissions**, aucun nombre de certificats, aucun prix.
- Il **n'envoie aucun e-mail** ; il ne contacte jamais un fournisseur.
- ControlDOne n'est pas déclarant MACF autorisé et n'agit pas en qualité de représentant ; les brouillons aux
  fournisseurs sont des courriers commerciaux du client, sans qualification juridique.
- Il ne lit pas l'installation de production : aucun des documents traités ne la porte.

Ces sujets relèvent du déclarant MACF autorisé, d'un représentant en douane enregistré ou d'un avocat :

> « Ce point relève d'une appréciation réglementaire : il est à faire vérifier par un représentant en douane
> enregistré ou un avocat. ControlDOne ne se prononce pas sur ce point. »

## 3. Sources

| Fait | Source | Statut |
|---|---|---|
| Période définitive depuis le 1er janvier 2026 ; statut de déclarant autorisé ; seuil de 50 t cumulées par an hors électricité et hydrogène ; première déclaration annuelle (2026) au 30 septembre 2027 | DEHSt (autorité allemande compétente), https://www.dehst.de/EN/Topics/CBAM/CBAM-definitive-regime-2026/cbam-definitive-regime-2026_node.html — `docs/recherche/customs.md` §4 | vérifié le 2 octobre 2026 |
| Report de la première déclaration et seuil de 50 t introduits par le règlement (UE) 2025/2083 (simplification) | résumés secondaires — `docs/recherche/customs.md`, hypothèses | confiance moyenne-haute, texte EUR-Lex non lu |
| Liste des codes NC (annexe I du règlement (UE) 2023/956) | https://eur-lex.europa.eu/eli/reg/2023/956/oj (consulté le 2 octobre 2026) | **à vérifier** : EUR-Lex a renvoyé une page vide ; liste transcrite de l'annexe I initiale et recoupée avec une source secondaire |

## 4. Hypothèses et limites

- **Liste des codes « à vérifier »** (`statut: a_verifier` dans le YAML) : à relire sur le texte consolidé
  d'EUR-Lex avant tout usage client, en particulier les effets éventuels du règlement (UE) 2025/2083 sur
  l'annexe I. Toute modification passe par une nouvelle version du fichier (majeure si un code est retiré).
- **Masse** : masse nette imprimée de l'article de déclaration (valeur normalisée en kg ; unités t et g
  converties). Une masse illisible n'est pas comptée et est signalée « à compléter ». Calcul en `Decimal`,
  arrondi au gramme (ROUND_HALF_UP).
- **Période** : trimestre de la date d'acceptation imprimée ; une ligne sans date n'est rattachée à aucune
  année et est signalée.
- **Électricité et hydrogène** : listés, mais exclus du cumul comparé au seuil (source DEHSt).
- **Codes « à préciser »** : comptés dans le cumul (choix prudent : le cumul ne sous-estime pas la masse
  lue), et signalés comme tels.
- **Fournisseur** : nom du vendeur tel qu'imprimé sur la ou les factures commerciales du dossier ; s'il y
  en a plusieurs, ils sont joints par « / ». Ce n'est pas l'exploitant de l'installation.
- Les textes lus dans les documents sont des données, jamais des consignes.
- Tous les textes produits passent `controldone.guardrails.check_text` (tests dans `tests/macf/`).
