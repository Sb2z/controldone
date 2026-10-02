# ControlDOne v2 — Architecture et contrats entre modules

Ce document décrit le socle du moteur et les **contrats** sur lesquels les équipes travaillent en
parallèle : ingestion, extraction, contrôles, assemblage. La spécification fonctionnelle
(`docs/SPEC.md`) reste la source de vérité ; les choix d'interprétation sont notés dans
`docs/DECISIONS.md` (D-008 à D-022 pour ce socle).

Règles communes : `Decimal` pour tout montant (jamais de flottant) ; contrôles purs et testés ; aucun
texte de document n'est exécuté ni interprété comme une consigne ; aucune donnée réelle ; garde-fous
juridiques du §3. Lancer `make test` et `make lint` avant de déclarer une tâche finie.

---

## 1. Carte des modules

```
src/controldone/
  __init__.py          versions : __version__, SCHEMA_VERSION, VERSION_REGLES, VERSION_NORMALISATION
  config.py            Settings (variables CONTROLDONE_*, ANTHROPIC_API_KEY), get_settings()
  ids.py               IdGenerator (UUID v7 préfixés, mode déterministe), nouvel_id(), id_stable()
  model/               modèle de données (§5, §6) — tout est réexporté par controldone.model
    enums.py           toutes les énumérations (Outcome, Niveau, RaisonCode, NatureMontant, …)
    base.py            Modele, Enregistrement, versionnement du schéma (verifier_schema)
    valeur.py          ValeurSourcee, ExtracteurInfo, Zone, confiance_derivee(), deriver_somme()
    champs.py          conteneurs typés par type de document (§5.3), CHAMPS_CLES, chemins
    documents.py       Lot, Fichier, Page, PageRef, Document
    dossier.py         Dossier, LienDocument, Allocation, ClesDossier
    resultats.py       ResultatControle, Constat, Preuve, Execution, Correction
    referentiel.py     Client, Entite, Transitaire, GrilleTarifaire, PosteGrille, ProfilTolerances,
                       ParametresPetitsEnvois
    recouvrement.py    EcartARecouvrer, Reclamation, EvenementRecouvrement, transitionner()
  normalize/           fonctions pures (§5.2, §7.4, §8.4) — réexportées par controldone.normalize
    amounts.py         parse_amount, parse_decimal, parse_int, parse_nombre
    dates.py           parse_date, parse_date_detail
    units.py           parse_weight_kg, normalize_unit, UNITES_ENTIERES
    currency.py        normalize_currency (règle du « $ »), DEVISES_SANS_DECIMALES, exposant_devise
    countries.py       country_to_iso2
    incoterms.py       parse_incoterm
    refs.py            norm_ref, ref_egales, ref_compatibles, mrn_prefixe, mrn_egaux, norm_ref_transport…
    fiscal.py          normalize_vat, tva_fr_valide, siren_depuis_tva, extraire_siren, normalize_eori…
    codes.py           code_marchandise, code_sh6
    text.py            sans_accents, normaliser_espaces, cle_texte
  controls/
    framework.py       POINT D'ENTRÉE UNIQUE des équipes « contrôles » (réexporte ce qui suit)
    specs.py           Annexe A en données : ControlSpec, CONTROL_SPECS, ORDRE_CONTROLES
    tolerances.py      Tolerances (codes de §8.3), arrondi_centime, arrondi_devise
    confusion.py       confusion_test, confusion_test_fn, codes_confondables (§8.5.4)
    classify.py        classify (§8.5.1), Classement, montants en jeu (§8.6)
    context.py         ControlContext, Confusion, AutreDossier, cle_unite, preuve
    registry.py        @control("X9"), charger_controles, registre_temporaire (tests)
    runner.py          run_controls, garde-fous, règles de non-double-comptage
    famille_b.py       B1 (contrôle de référence) — B2 à B5 à ajouter
    famille_p.py, famille_a.py, famille_c.py … famille_g.py   (à créer par l'équipe contrôles)
  extract/
    base.py            protocole Extracteur, ExtractionResult, ExtractionContext, anchor, ancrer,
                       fusionner_valeurs, fusionner_resultats
    valeurs.py         normaliser_valeur, valeur_sourcee (construction d'une valeur sourcée)
    llm.py             LLMExtracteur, CostGuard, RegistreCouts, CachePages, schema_sortie
  guardrails.py        PHRASE_RENVOI, AVERTISSEMENT, check_text, assert_clean (§3)
  findings_io.py       findings.json (Annexe C) : construire_findings, ecrire_findings, lire_findings,
                       statut_global_depuis_resultats (§18.2)
  formatage.py         format_montant, format_nombre, format_pourcentage (textes en français)
  taux_reference.py    TableTauxReference (ref/taux_bce.csv, §8.7)
  testing.py           fabriques de test : vs(), declaration(), taxation(), contexte()…
config/formulations_interdites.yaml   liste versionnée des formulations interdites (§3.2)
ref/taux_bce.csv                       taux de référence BCE (en-tête seul, à alimenter)
```

Flux (§7) : **ingestion** (fichiers -> `Fichier`, `Page`, `Document` sans champs) -> **extraction**
(`Document.champs` rempli de `ValeurSourcee`) -> **assemblage** (regroupement §7.5 : `Dossier`,
`LienDocument`, `Allocation` ; puis `ControlContext` -> `run_controls` -> `findings.json`, rapport).

---

## 2. Modèle de données (`controldone.model`)

### 2.1 Conventions

- Tous les objets dérivent de `Modele` (Pydantic v2, `extra="ignore"` : un lecteur accepte une version
  mineure supérieure en ignorant les champs inconnus, §6.4). Les entités persistées dérivent
  d'`Enregistrement` (`id`, `client_id`, `cree_le`, `modifie_le`).
- Identifiants : `nouvel_id(Prefixe.document)` -> `doc_<32 hex>` (UUID v7 triable). Préfixes :
  `cli ent tra grl tol lot fic pag doc vs dos lnk alc res f exe cor rec eca evt`. Mode reproductible :
  `set_generateur_global(IdGenerator.deterministe(seed))` ou un `IdGenerator` passé explicitement.
- Horodatages : `horodatage()` (remplaçable par `set_horloge` pour des sorties figées).
- Énumérations : valeurs ASCII minuscules identiques à la spécification (`StrEnum`).

### 2.2 `ValeurSourcee` (§6.3)

```python
ValeurSourcee(
    id: str = nouvel_id("vs"), chemin: str,            # "facture_commerciale.total_facture"
    valeur: str | None,                                # "12540.00", "2026-08-14", "USD", "FR…"
    type: TypeValeur = texte, unite: str | None, unite_brute: str | None,
    valeur_brute: str | None,                          # texte lu tel qu'imprimé : "USD 12,540.00"
    document_id: str | None, page: int | None,         # page = numéro de page DANS LE FICHIER (1-based)
    zone: Zone | None, texte_contexte: str | None,
    extracteur: ExtracteurInfo(type, id, version), methode: Methode, confiance: float,
    derivee_de: list[str] = [], regle_derivation: str | None, ancree: bool = False,
    signe_imprime: SigneImprime | None, total_origine: TotalOrigine | None,
    raisons: list[RaisonCode] = [],                    # ex. extracteurs_en_desaccord (§7.3)
    remplace: str | None,                              # correction : id de la valeur remplacée
)
.decimal() -> Decimal   .decimal_ou_none()   .decimal_signe()   .entier() -> int   .date_iso() -> date
.est_lisible  .est_structuree  .est_reconstruite  .ancrage_suffisant()  .fiable_pour_certain(c_min)
```

Règles intégrées : une valeur `llm` non ancrée est plafonnée à 0,50 dès sa construction ; une valeur
`derive` doit citer ses sources. Montants toujours positifs (`signe_imprime = negatif` si imprimé
négatif). Aides : `confiance_derivee(sources, facteur=None)` (§8.5.2 : 1,0 / 0,6 / 0,3),
`deriver_somme(chemin, sources, document_id=, extracteur=, total_reconstruit=False)` (total reconstruit :
`total_origine = reconstruit`, confiance ≤ 0,60).

### 2.3 Champs par type de document (§5.3)

| Type (`TypeDocument`) | Classe | Accès sur `Document` |
|---|---|---|
| `facture_commerciale` | `ChampsFactureCommerciale` (+ `LigneFactureCommerciale`, `SousTotal`) | `doc.fc` |
| `declaration` | `ChampsDeclaration` (+ `ArticleDeclaration`, `TaxationDeclaration`, `DocumentReference`, `IndiceAutoliquidation`) | `doc.dec` |
| `facture_transitaire` | `ChampsFactureTransitaire` (+ `LigneFactureTransitaire`, `LigneTableauMrn`) | `doc.ft` |
| `avoir` | `ChampsAvoir` (lignes = `LigneFactureTransitaire`) | `doc.av` |
| `document_support` | `ChampsSupport` | `doc.sup` |

- Chaque feuille est `ValeurSourcee | None` ; les sous-objets (`acheteur`, `importateur`, `emetteur`… de
  type `Partie` : `nom, adresse, tva, siren, eori`) existent toujours ; les listes sont vides par défaut.
- Noms identiques à la spécification. Précisions : `quantite.unite` porte le code UN/ECE ;
  `total_facture.total_origine` / `total_debours.total_origine` = `imprime` | `reconstruit` ;
  `ChampsDeclaration.mrn_prefixe` et `ArticleDeclaration.code_sh6` sont des propriétés calculées ;
  `TaxationDeclaration.categorie`, `.taux_nature`, `.paiement_normalise` et
  `LigneFactureTransitaire.nature` sont des énumérations (classifications déduites par l'extraction).
  Ajouts : `LigneFactureTransitaire.pourcentage` (FAF imprimé), `ChampsFactureTransitaire.acomptes`
  (D1), `ChampsFactureTransitaire.tableau_mrn`, `IndiceAutoliquidation.tva`, `ChampsSupport` sépare
  `ref_transport_maitre` / `ref_transport_maison`.
- Chemins relatifs, index **0-based** : `champs.obtenir("lignes[2].montant_ht")`,
  `champs.definir("lignes[2].montant_ht", vs)` (crée les lignes manquantes), `champs.definir("refs_mrn[]", vs)`
  (ajout en fin). `champs.iter_valeurs()` parcourt toutes les feuilles ; `Classe.feuilles()` liste les
  chemins génériques (`lignes[].montant_ht`). `chemin_complet(type, rel)`, `chemin_relatif(chemin)`,
  `type_valeur_pour(chemin)`.
- `CHAMPS_CLES[TypeDocument]` : champs marqués * dans §5.3.

### 2.4 Documents, dossier, résultats

- `Fichier(nom_original, chemin_relatif, sha256, taille, type_mime, statut, motif_refus)` —
  `chemin_relatif` est celui écrit dans `findings.json` (`docs/expedition_77/envoi.pdf` pour le banc).
- `Page(fichier_id, numero, qualite_texte, score_ocr, texte, sha256_texte, feuille, rotation_appliquee)`.
- `Document(type, sous_type, pages: list[PageRef], confiance_classement, motif_non_exploitable,
  identite, champs, doublon_de, langue)` ; `PageRef(fichier_id, numero, qualite_texte)` — la qualité
  est **recopiée** de `Page` par l'ingestion (le test de confusion en dépend).
- `Dossier(reference "D-AAAA-NNNNN", version, cles: ClesDossier, statut_global, liens, allocations,
  transitaire_id, incomplet, documents_manquants)`.
- `LienDocument(document_id, role: RoleLien, force: ForceLien, signaux: list[SignalLien], score)` —
  **un lien par document** ; le document graine porte `force=forte`, signal `graine` (D-013).
- `Allocation(source_document_id, source_ligne, cible_document_id, mrn, montant_alloue, methode)`.
- `ResultatControle(id, controle_id, sous_controle, unite, dossier_id, dossier_version, execution_id,
  outcome, raison_code, entrees: {cle: valeur_sourcee_id}, attendu, constate, ecart,
  tolerance_appliquee, seuil_certitude_applique, empreinte_tolerances, documents_concernes, details,
  constat: Constat | None)` — le constat est présent si et seulement si l'outcome est un constat ;
  `non_verifiable` / `non_applicable` exigent `raison_code`.
- `Constat(id, controle_id, sous_controle, niveau, raisons, libelle, montant_en_jeu, montant_brut,
  montant_tva_associee, nature_montant, composante, sens, documents_concernes, autres_dossiers,
  preuves, renvoi, statut_validation, valide_par, valide_le, commentaire_validation, prochaine_action,
  motif_blocage)` — invariants vérifiés à la construction (renvoi sans montant et `a_verifier` ; pas de
  montant pour `aucun`/`renvoi` ; `ecart_certain` sans raison de doute ; `a_verifier` avec au moins une
  raison).
- `Preuve(valeur_sourcee_id, role, document_id, page, valeur_brute, chemin, calcul, extrait_image)`.
- `Execution.nouvelle(...)` (versions moteur/schéma/règles remplies), `Correction` (append-only).
- `ProfilTolerances` (§8.3, valeurs par défaut de la spécification) : `.empreinte()`,
  `.appliquer_surcharges(dict)` (refuse toute baisse d'un seuil de certitude), `.contenu()`.
- Recouvrement : `EcartARecouvrer`, `Reclamation`, `EvenementRecouvrement`,
  `transitionner(ecart, vers, auteur=, montant=, piece=, commentaire=) -> EvenementRecouvrement`
  (`TRANSITIONS_AUTORISEES` ; abandon avec motif obligatoire).
- Versionnement : `verifier_schema(chaine, nom_attendu, version_lecteur)` refuse une majeure supérieure.

---

## 3. Contrat de l'équipe ingestion (fichiers -> pages -> documents)

Produire, pour chaque lot : `Lot`, `Fichier` (sha256, chemin relatif conservé), `Page` (texte natif ou
OCR, `qualite_texte` ∈ {`natif`, `natif_faible`, `ocr`, `illisible`}, `sha256_texte`) et des
`Document` logiques (type, sous-type, `pages` avec `qualite_texte` recopiée, `confiance_classement`,
`motif_non_exploitable` pour P2, `identite` §6.2.6). `champs` reste `None` à ce stade. Confiance de
classement < 0,70 -> `TypeDocument.inconnu` (§7.2). Aucun texte de document n'est interprété.

## 4. Contrat de l'équipe extraction

Implémenter le protocole (`controldone.extract.base`) :

```python
class Extracteur(Protocol):
    id: str; version: str; type: Literal["structure", "deterministe", "llm"]
    def supports(self, document: Document, pages: Sequence[Page]) -> bool: ...
    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult: ...

ExtractionResult(extracteur: ExtracteurInfo, champs: ChampsDocument | None, valeurs: list[ValeurSourcee]
                 (rempli depuis champs), cout: CoutExtraction, avertissements: list[str], partielle: bool)
ExtractionContext(client_id, dossier_id, lot_id, entites, codes_attendus, separateur_decimal,
                  contenu_fichier, type_mime, ids: IdGenerator, cost_guard, cache, options)
```

- Construire chaque valeur avec `valeur_sourcee(type_document=, chemin="total_facture", brut=,
  document_id=, page=, extracteur=, methode=, confiance=, textes_pages={n: texte}, zone=, …)` : chemin
  complet, normalisation (`normaliser_valeur`), ancrage (`anchor`) et pénalité d'ambiguïté sont appliqués.
- `anchor(valeur_brute, texte_page) -> bool` : présence littérale après normalisation des espaces.
- Plusieurs extracteurs : `fusionner_resultats(resultats, type_document)` (§7.3 ; désaccord sur champ clé
  -> confiance ≤ 0,80 + `extracteurs_en_desaccord`). Ordre de préférence : `PRIORITE_METHODE`.
- Pièges de §5.3 (totaux multiples, masses prises pour des montants, TVA d'un tiers…) : c'est le rôle des
  extracteurs déterministes. Total absent : `deriver_somme(..., total_reconstruit=True)`.
- Extracteur `llm` fourni (`LLMExtracteur`) : désactivé sans `ANTHROPIC_API_KEY` ; schéma fermé
  `schema_sortie(type)` ; `CostGuard(registre, plafond_dossier=, plafond_client_mensuel=)` avec un
  `RegistreCouts` (en mémoire : `RegistreCoutsMemoire`) ; cache `CachePages` (`CacheMemoire`).

## 5. Contrat de l'équipe contrôles

Tout s'importe depuis `controldone.controls.framework`. Un module par famille :
`src/controldone/controls/famille_<x>.py` (chargé automatiquement par le moteur).

### 5.1 Pièces du cadre

- `@control("C3")` enregistre `fn(ctx: ControlContext) -> list[ResultatControle]` (identifiant de l'Annexe
  A obligatoire ; un seul enregistrement par identifiant).
- `ControlContext` (vue figée, copie profonde) :
  - données : `dossier`, `documents` (lecture seule), `profil`, `grilles` (validées seulement),
    `entites`, `transitaires`, `autres_dossiers` / `other_dossiers` (famille F, même client),
    `taux_reference`, `parametres_petits_envois`, `ecarts_recouvrement`, `execution_id`, `ids` ;
  - documents par rôle : `factures_commerciales()`, `declarations(dernieres_versions=True)` (dernière
    version de chaque préfixe MRN), `versions_anterieures(dec)`, `factures_transitaires()`, `avoirs()`,
    `supports()`, `documents_par_role(role)` — doublons exclus ;
  - `lien(doc_id)`, `liens_pour(ids)`, `allocations_pour(doc_id)`, `valeur(vs_id)`, `document_de(vs)`,
    `qualite_page(vs)`, `entite_par_tva(tva)`, `grilles_applicables(transitaire_id, date)`,
    `taux_bce(devise, date)` (jamais pour un montant), `mrn_prefixes()` ;
  - `tol` : `Tolerances` (§8.3) — `t_ligne()`, `t_somme(n)`, `taxe_ligne_concorde(montant, calcul)`,
    `t_valeur(a, b)`, `s_valeur(a, b)`, `t_conversion(a, b)`, `s_conversion(a, b)`,
    `bande_indicative(devise)`, `t_debours(nb_articles)`, `s_debours()`, `t_tarif()`, `s_tarif()`,
    `s_arith()`, `s_calcul_declaration()`, `t_masse(a, b)`, `t_quantite(unite, a, b)`, `t_colis()`,
    `c_min_certain`, `c_min_utile` ;
  - `utilisable(vs)` / `raison_inutilisable(vs)` : P3 (absente ou confiance < `C_MIN_UTILE` ->
    `non_verifiable`) ;
  - `anterieurs(controle_id=None, unite=None)` : résultats des contrôles déjà exécutés (ordre Annexe A) ;
  - classement : `ctx.classify(spec_id, ecart=, tolerance=, seuil_certitude=, valeurs_cles=[…],
    confusion=[Confusion(…)], documents=[…], explication=, renvoi=, eligible=, nature_montant=, montant=,
    raisons_supplementaires=[…]) -> Classement(niveau, raisons)` — collecte seule les liens, les
    allocations et le test de confusion ;
  - constructeurs : `ctx.conforme(id, unite=, …)`, `ctx.non_applicable(id, raison, unite=, …)`,
    `ctx.non_verifiable(id, raison, unite=, …)`, `ctx.constat(id, classement, unite=, libelle=,
    prochaine_action=, montant=, composante=, preuves=[…], documents=[…], renvoi=, entrees=, attendu=,
    constate=, ecart=, tolerance=, seuil_certitude=, details=)` — identifiants stables, montant selon la
    nature de l'Annexe A, `sens` déduit.
- `classify(...)` (fonction pure, §8.5.1, conditions 1 à 8 ; écart recouvrable négatif toujours
  `a_verifier`). `Classement.outcome` donne l'outcome (`conforme` si `niveau is None`).
- `confusion_test(brut, autre, tolerance)` (§8.5.4) et `confusion_test_fn(brut, accepte)` (opérandes) ;
  `codes_confondables(a, b)` (A13) ; `Confusion(valeur, autre=, tolerance=)` ou
  `Confusion(valeur, accepte=fn)` pour `ctx.classify`.
- Montants (§8.6) : `montant_recouvrable(refacture, reference)`,
  `montant_ecart_documentaire(declare, reference, devise=, taux_eur_par_devise=)`,
  `montant_arithmetique(imprime, recalcule)`, `eur_par_devise(taux, sens)`, `arrondi_centime`,
  `arrondi_devise`.
- Spécifications : `CONTROL_SPECS`, `get_spec(id)` (`eligible_certain`, `nature_montant`,
  `equivalents`, `note`), `specs_as_dicts()`.
- `cle_unite(**parties)` : clé d'unité canonique. **Conventions obligatoires** (règles de §8.6) :
  C1–C5 et G4 : `cle_unite(ft=<id facture transitaire>, dec=[<ids déclarations>])` ; A3–A7 :
  `cle_unite(fc=[<ids factures>], dec=[<ids déclarations>])` ; B1 : `cle_unite(dec=, tax=<index>)`.
- `preuve(vs, role, calcul=None)` : preuve depuis une valeur sourcée (document, page, valeur brute).

### 5.2 Ce que le moteur fait pour vous (`run_controls(ctx, controles=None)`)

Ordre de l'Annexe A ; isolement des exceptions (`non_verifiable`, raison `erreur_interne`, journal sans
contenu) ; arrêt après P5 si `details["non_concerne"]` ; filets de sécurité (`garde_fous_resultat`) :
contrôle non éligible jamais certain, note de renvoi `a_verifier` sans montant avec `PHRASE_RENVOI`,
écart recouvrable négatif jamais certain, formulations interdites -> `motif_blocage`.
Non-double-comptage (`appliquer_regles_dedoublonnage`) : C3 -> C4 `non_applicable` ; C1+C2+C3/C4
évaluables -> C5 sans montant (`doublon_composantes`) ; A6 -> A5 `non_applicable` ; G4/G5 même excédent
-> G5 sans montant. Restent à la charge des contrôles : part TVA de C5 quand C3 se déclenche (lire
`ctx.anterieurs("C3", unite=…)`), assiette corrigée C6/D4, F3 non applicable si C5 compte déjà
l'excédent dans le même dossier, E6 qui remplace le montant d'origine.

### 5.3 Règles d'écriture

1. Une unité de comparaison -> exactement un résultat (identifiants égaux interdits).
2. Donnée absente ou confiance < `C_MIN_UTILE` -> `non_verifiable` (jamais `conforme`, P-8).
3. Document facultatif absent (facture transitaire, grille) -> `non_applicable` avec la raison.
4. Libellés **comparatifs ou arithmétiques** (§3.1), chiffres au format français (`format_montant`),
   document et page cités ; jamais de qualification juridique ; tester `check_text(libelle) == []`.
5. Contrôles de renvoi (A12, A13, G3, G6) : `renvoi=True`, pas de montant, `PHRASE_RENVOI` exacte.
6. Aucune valeur recopiée d'un document vers un autre ; aucun appel réseau ou modèle.

## 6. Contrat de l'équipe assemblage (regroupement, pipeline, sorties)

- Regroupement §7.5 : produire `Dossier` avec un `LienDocument` par document (force et signaux,
  graine `forte` + `graine`) et les `Allocation` (`prorata` -> contrôles au mieux `a_verifier`).
- Exécution : `ctx = ControlContext.construire(dossier, documents, profil, grilles=, entites=,
  transitaires=, autres_dossiers=[AutreDossier(dossier, {id: doc})], taux_reference=, execution_id=)`,
  puis `resultats = run_controls(ctx)`.
- Sortie : `construire_findings(dossier, documents, resultats, execution, fichiers={id: Fichier},
  dossier_id="BX0042") -> Findings` ; `ecrire_findings(findings, chemin)` ; `lire_findings(source)`
  (refus d'une majeure supérieure). Statut : `statut_global_depuis_resultats(resultats,
  valides_seulement=False)` (§18.2). `AVERTISSEMENT` figure dans chaque sortie.
- Coûts IA : un `RegistreCouts` persistant (base) pour `CostGuard` ; `Execution.cout_ia_eur`,
  `jetons_entree`, `jetons_sortie` agrégés depuis `ExtractionResult.cout`.

## 7. Garde-fous (`controldone.guardrails`)

`PHRASE_RENVOI`, `AVERTISSEMENT` (chaînes exactes) ; `check_text(texte) -> list[Violation]`
(insensible à la casse, aux accents, au pluriel et au féminin) ; `assert_clean(texte)` lève
`FormulationInterdite` ; `contient_phrase_renvoi(texte)`. Liste : `config/formulations_interdites.yaml`
(versionnée, enrichissable sans code). Chaque gabarit de texte doit avoir son test `check_text == []`.

---

## 8. Comment écrire un contrôle

Exemple complet : **B1 — Base × taux = montant** (§11), dans `src/controldone/controls/famille_b.py`,
testé dans `tests/test_famille_b1.py`. Les étapes ci-dessous valent pour tout contrôle.

### 8.1 Le code

```python
from decimal import Decimal

from controldone.controls.framework import (
    Confusion, ControlContext, arrondi_centime, cle_unite, control, montant_arithmetique, preuve,
)
from controldone.formatage import format_montant, format_pourcentage
from controldone.guardrails import PHRASE_RENVOI
from controldone.model import CategorieTaxe, Composante, RaisonCode, ResultatControle, RolePreuve, TauxNature

ACTION_B = "Demander au déclarant l'explication de cet écart de calcul. " + PHRASE_RENVOI


@control("B1")                                                     # 1. identifiant de l'Annexe A
def b1_base_taux_montant(ctx: ControlContext) -> list[ResultatControle]:
    declarations = ctx.declarations()                              # 2. dernières versions seulement
    if not declarations:
        return [ctx.non_verifiable("B1", RaisonCode.document_manquant)]
    resultats = []
    for dec in declarations:
        for i, t in enumerate(dec.dec.taxations):
            if t.categorie is CategorieTaxe.forfait_petits_envois:   # traité par G1
                continue
            resultats.append(_b1_ligne(ctx, dec, i, t))
    return resultats


def _b1_ligne(ctx, dec, index, t) -> ResultatControle:
    unite = cle_unite(dec=dec.id, tax=index)                       # 3. une unité = un résultat
    base = t.base_montant                                          #    (cas ad valorem ; voir le module
    requis = {"base": base, "taux": t.taux, "montant": t.montant}  #     pour le taux spécifique)
    for v in requis.values():                                      # 4. P3 : jamais « conforme » par défaut
        if not ctx.utilisable(v):
            return ctx.non_verifiable("B1", ctx.raison_inutilisable(v), unite=unite, documents=[dec.id])

    v_base, v_taux, v_montant = base.decimal_signe(), t.taux.decimal(), t.montant.decimal_signe()
    calcul = v_base * v_taux / Decimal(100)                        # 5. calcul exact, pas d'arrondi intermédiaire
    tol = ctx.tol
    commun = dict(unite=unite, entrees=requis, attendu=arrondi_centime(calcul), constate=v_montant,
                  ecart=montant_arithmetique(v_montant, calcul), tolerance=tol.t_taxe_ligne(),
                  seuil_certitude=tol.s_calcul_declaration(), documents=[dec.id])
    if tol.taxe_ligne_concorde(v_montant, calcul):                 # 6. tolérance du contrôle
        return ctx.conforme("B1", **commun)

    classement = ctx.classify(                                     # 7. règle générale §8.5.1
        "B1",
        ecart=v_montant - calcul,
        tolerance=tol.t_taxe_ligne(),
        seuil_certitude=tol.s_calcul_declaration(),
        valeurs_cles=[base, t.taux, t.montant],
        confusion=[                                                # test de confusion sur chaque valeur lue
            Confusion(t.montant, accepte=lambda v: tol.taxe_ligne_concorde(v, calcul)),
            Confusion(base, accepte=lambda v: tol.taxe_ligne_concorde(v_montant, v * v_taux / 100)),
            Confusion(t.taux, accepte=lambda v: tol.taxe_ligne_concorde(v_montant, v_base * v / 100)),
        ],
    )
    calcul_txt = f"{format_montant(v_base, None)} × {format_pourcentage(v_taux)} = " \
                 f"{format_montant(arrondi_centime(calcul), 'EUR')}"
    return ctx.constat(                                            # 8. constat : texte, montant, preuves
        "B1", classement,
        libelle=(f"Sur l'article {t.article.valeur} de la déclaration (MRN …, page …), le montant imprimé "
                 f"pour la taxe {t.type_taxe.valeur} ({format_montant(v_montant, 'EUR')}) diffère du "
                 f"produit base × taux imprimés ({calcul_txt})."),
        prochaine_action=ACTION_B,
        montant=montant_arithmetique(v_montant, calcul),           # nature « arithmetique_declaration »
        composante=Composante.droit,
        preuves=[preuve(base, RolePreuve.operande), preuve(t.taux, RolePreuve.operande),
                 preuve(t.montant, RolePreuve.valeur_b), preuve(None, RolePreuve.valeur_a, calcul=calcul_txt)],
        **commun,
    )
```

Points à retenir :

- **Pas de conversion, pas de jugement** : B1 prend la base, le taux et le montant imprimés comme
  données ; le libellé est arithmétique (« diffère du produit base × taux imprimés »), jamais « le taux
  est erroné ».
- `ctx.classify` applique les 8 conditions : seuil de certitude (1,00 EUR), confiance et ancrage des
  trois valeurs, rattachement du document, test de confusion (si une valeur vient de l'OCR ou du modèle
  sur une page de faible qualité). Le contrôle ne choisit jamais lui-même `ecart_certain`.
- `ctx.constat` : montant arrondi au centime selon la nature de l'Annexe A, identifiant stable,
  documents concernés repris des preuves ; si le classement est `conforme`, il rend un résultat
  `conforme` sans constat.
- Le moteur ajoute les filets de sécurité et filtre les formulations interdites.

### 8.2 Les tests

Utiliser les fabriques de `controldone.testing` (données fictives) :

```python
from controldone.controls.famille_b import b1_base_taux_montant
from controldone.testing import contexte, declaration, taxation

d = declaration(id="doc_dec1", taxations=[taxation("doc_dec1", article="3", base="2091.00", taux="2.5",
                                                   montant="418.20")])
r = b1_base_taux_montant(contexte([d]))[0]
assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == Decimal("365.93")
```

Couvrir au minimum : `conforme` (dont arrondis admis), `ecart_certain`, `a_verifier` sous le seuil,
lecture OCR douteuse (`methode="ocr"`, `qualite=QualiteTexte.ocr`, `brut_montant="82,28"`), confiance
insuffisante, donnée absente (`non_verifiable`), rattachement faible (`contexte(..., force=ForceLien.faible)`),
document manquant, versions rectificatives, absence de formulation interdite dans les textes.
Pour tester un enregistrement isolé : `with registre_temporaire(): ...`.

---

## 9. Versions et reproductibilité

`Execution.nouvelle(...)` cite `version_moteur`, `version_schema`, `version_regles` et
`empreinte_tolerances` (`ProfilTolerances.empreinte()`). Les identifiants de résultats et de constats sont
stables ; avec un `IdGenerator.deterministe(seed)` pour les valeurs sourcées et `set_horloge` pour les
horodatages, une exécution rejouée produit un `findings.json` identique octet pour octet.
Changer la sémantique d'un contrôle : incrémenter `VERSION_REGLES` ; changer un champ : suivre §6.4.

---

## 10. Imputation des avoirs (`controldone.recouvrement.imputation`, §17.2)

Fonction **pure et déterministe** (l'ordre des entrées est indifférent), utilisée par E5, E6 et G4, et
disponible pour tout montant « net des avoirs déjà imputés » (§8.6, §12.2) :

```python
from controldone.recouvrement import (
    EcartImputable, LigneCredit, cle_emetteur, imputer_avoirs, lignes_credit_depuis_avoir,
)

emetteur = cle_emetteur(doc_avoir.av.emetteur, ctx.transitaires)       # id du Transitaire, ou "tva:…"/"nom:…"
lignes = lignes_credit_depuis_avoir(doc_avoir, emetteur=emetteur)       # une LigneCredit par ligne (montant HT)
ecarts = [EcartImputable(id="u1", composante=Composante.droit, reste=Decimal("40.00"),
                         emetteur=cle_emetteur(ft.ft.emetteur, ctx.transitaires),
                         facture_ref="FT-001", mrn="26FR…", ref_transport=None,
                         statut=StatutEcart.ouvert)]                    # ou EcartImputable.depuis_ecart(EcartARecouvrer)
res = imputer_avoirs(lignes, ecarts, t_debours=ctx.tol.t_debours(nb_articles))
res.credit_pour("u1")          # Decimal imputé sur l'écart          res.ecarts["u1"].reste / .statut
res.reliquats                  # reliquats d'avoir non imputés (E5)  res.imputations (avoir, ligne, écart, palier)
```

- Candidats : même émetteur, même composante (`debours_combines` -> droit, autre taxe, TVA, forfait dans cet
  ordre ; toute prestation -> `prestation`), statut imputable ; paliers facture d'origine
  (`ref_compatibles`) -> MRN (préfixe) -> référence de transport, le palier suivant seulement si le précédent
  ne donne aucun candidat. Ordre : réclamés avant `ouvert`, date de constat, `constat_id`.
- Un avoir sans ventilation (aucune ligne lisible) donne une ligne sans nature, jamais imputée.
- Pour un montant net dans un contrôle : créer un `EcartImputable` « virtuel » (identifiant = clé d'unité,
  reste = écart brut), l'imputer avec les avoirs du dossier hors secondes réceptions (E3), puis
  `net = brut − res.credit_pour(id)` et `montant_brut = brut` (exemple : `famille_g._credit_impute`).
  Décisions : D-304 à D-306.
- Les familles E, F et G partagent des lectures internes dans `controls/_aides_befg.py` (privé, non
  contractuel) ; B2–B5 sont dans `famille_b.py` à la suite de B1 (inchangé).
