# Correcteur du banc (`bench/score`)

Compare les constats produits par le système (`findings.json`, SPEC Annexe C) aux vérités du
générateur (`truth.json`, SPEC §19.3 / Annexe B). Le correcteur ne lit que ces deux contrats
JSON : ni le code du moteur (`src/`), ni celui du générateur.

```bash
source .venv/bin/activate
python -m bench.score --corpus bench/corpus --split holdout --run bench/out/<run_id> [--gate]
# option : --formulations chemin/vers/formulations.yaml
```

- Lit chaque `<corpus>/<split>/<dossier_id>/truth.json` et `<run>/<dossier_id>/findings.json`.
- Écrit `<run>/metrics.json` (§19.8) et `<run>/metrics.md` (résumé en français).
- Avec `--gate` : code retour **1** si le seuil bloquant (§19.7) échoue, les motifs sont
  affichés. Code **2** si le corpus ou le run est introuvable. Sinon 0.
- Tests : `pytest -q tests/bench`.

## 1. Constats pris en compte

Seuls les éléments de `constats[]` de niveau `ecart_certain` ou `a_verifier` sont évalués
(`statut_validation` est ignoré). Un `finding_id` absent est remplacé par `<dossier>#<rang>`.

Un `findings.json` **absent** ou **illisible** (JSON invalide) : toutes les erreurs du dossier
sont des FN ; le dossier est listé dans `dossiers.findings_absents` / `findings_illisibles`
et dans `metrics.md`. Ce n'est pas en soi un motif de blocage (sauf via le rappel de P1).

## 2. Correspondance des documents (§19.4-1)

Un document produit `p` (`findings.documents[]`) correspond au document de vérité `t` si :

- ils appartiennent au **même dossier** (les chemins sont relatifs au `docs/` du dossier) ;
- même fichier : chemins comparés après normalisation (`\` → `/`, `./` et préfixe `docs/`
  retirés, donc `docs/a/b.pdf` = `a/b.pdf`) ;
- `|pages(t) ∩ pages(p)| ≥ 50 % × |pages(t)|`. Si `t` n'a pas de pages, ou si `p` n'a pas de
  champ `pages`, le fichier entier fait foi.

Les identifiants de `documents_concernes` d'un constat sont résolus d'abord parmi les
documents de son dossier, sinon parmi les documents produits de **tous** les dossiers du run
(un contrôle F peut citer un document d'un autre dossier).

Les `documents` d'une erreur ou d'un piège sont des `doc_id` du dossier de l'erreur ; la forme
qualifiée `BX0043/ft1` (ou `BX0043:ft1`) désigne un document d'un autre dossier.

## 3. Candidats (§19.4-2)

Un couple (constat `f`, erreur `e`) est candidat si **toutes** les conditions sont vraies :

1. même dossier, **ou** `e.control_id ∈ {F3, F4, F5}` et le dossier de `f` est dans
   `e.other_dossiers` ;
2. `f.controle_id ∈ e.accepted_control_ids` (à défaut, équivalents de l'Annexe A) ;
3. au moins un document de `f.documents_concernes` correspond (§2) à un document de
   `e.documents`. **Cas F3–F5 depuis l'autre dossier** : si aucun document ne correspond
   directement, on accepte un document de `f` qui correspond à un document de vérité du dossier
   de `f` ayant le même `type` que l'un des documents de `e` (les `doc_id` de `e` sont locaux
   au dossier de l'erreur).

## 4. Appariement (§19.4-3)

Un-à-un, glouton, déterministe, sur l'ensemble du split : les candidats sont triés par

1. écart de montant absolu `|f.montant_en_jeu − e.expected_amount_eur|` croissant ; les couples
   où l'un des deux montants est `null` passent **après** tous les autres ;
2. **départage** à écart égal : d'abord le constat dont `controle_id` est le contrôle
   **principal** de l'erreur (`e.control_id`), puis le constat de niveau `ecart_certain` ;
3. `error_id` ;
4. `finding_id` (puis `dossier_id` pour départager des `finding_id` identiques entre dossiers).

Le départage (2) a été ajouté après le premier holdout (D-905) : une erreur B4 (acceptée B4/A10)
était appariée au constat A10 `a_verifier` dont le `finding_id` triait avant, et le constat B4
`ecart_certain` du même document était compté FP certain. Il s'applique à tous les splits.

On parcourt la liste et on retient un couple si ni le constat ni l'erreur ne sont déjà pris.

## 5. Montant correct (§19.4-4)

- `e` et `f` non nuls : `|f − e| ≤ max(0,05 ; 1 % × |e|)` (montants signés, `Decimal`).
- `e` et `f` tous deux `null` : correct.
- l'un `null` et l'autre non : incorrect, **sauf** : nature `recouvrable`, `f` `null` avec
  `doublon_composantes` dans `raisons`, et un **autre constat apparié du même dossier** porte un
  montant non nul.
- Un montant illisible (chaîne non décimale) compte comme « porte un montant » incorrect.

## 6. Classes (§19.4-5)

Constat apparié à une erreur :

| Niveau | Montant | Classe |
|---|---|---|
| `ecart_certain` | correct | `vp_certain` (+ `surclassement` si l'erreur attendait `a_verifier`) |
| `ecart_certain` | incorrect | `fp_certain` (motif `montant_incorrect`) — reste une **VP détection**, l'erreur n'est pas FN |
| `a_verifier` | indifférent | `vp_a_verifier` (+ `sous_classement` si l'erreur attendait `ecart_certain`) |

Constat **non apparié**, évalué dans cet ordre :

1. **Piège** (voir §7) dont `max_level` est inférieur au niveau du constat : `fp_certain` ou
   `fp_a_verifier`, motif `piege`, `trap_id` renseigné.
2. **Neutres** (ni VP ni FP, comptés dans `neutres`, rapportés dans `details`) — interprétation
   du correcteur, voir §10 :
   - `miroir_inter_dossiers` : constat F3–F5 candidat d'une erreur déjà appariée à un constat
     posé dans **un autre dossier** cité par l'erreur (les deux occurrences d'un doublon) ;
   - `redondant_doublon_composantes` : constat sans montant, raison `doublon_composantes`,
     candidat d'une erreur `recouvrable` déjà appariée à un autre constat du même dossier qui
     porte un montant (ex. C5 recalculé alors que C1 porte l'écart, §8.6).
3. Piège dont `max_level` est atteint sans être dépassé (`a_verifier` sur un piège
   `a_verifier`) : `piege_tolere` (neutre, pas du bruit).
4. Sinon `fp_certain` / `fp_a_verifier`, motif `non_apparie`.

Erreur non appariée : `fn`.

## 7. Règle des pièges

Un piège n'est jamais apparié **avant** les erreurs : seuls les constats restés sans erreur
après l'appariement §4 sont confrontés aux pièges. Un constat `f` relève du piège `t` si :

- même dossier ;
- `f.controle_id` = `t.control_id` **ou** fait partie des équivalents banc de `t.control_id`
  dans l'Annexe A (ex. un piège C1 couvre C1 et C5) ;
- au moins un document de `f` correspond (§2) à un document de `t.documents`.

Si plusieurs pièges s'appliquent, on retient le plus restrictif (`conforme` avant `a_verifier`,
puis `trap_id`). Ordre des niveaux : `conforme < a_verifier < ecart_certain`. Le constat viole
le piège si son niveau est strictement supérieur à `max_level`.

## 8. Métriques

Par contrôle (`par_controle`) : les compteurs liés aux **erreurs** (n erreurs, appariées, FN,
VP certain, rappel, rappel certain, exactitude des montants, sur/sous-classement) sont rangés
sous le contrôle **principal** de l'erreur ; les compteurs liés aux **constats** (constats
produits, FP certain, FP à vérifier, précision de détection) sous `f.controle_id`.

- `precision_certain = vp_certain / (vp_certain + fp_certain)` (spec : VP sur l'erreur, FP sur
  le constat) et `precision_certain_wilson_bas` (Wilson, z = 1,96) ;
- `precision_certain_constats` : même ratio entièrement compté sur `f.controle_id` — c'est
  celle qu'utilise la condition 2 du seuil (un contrôle « ayant au moins 10 constats
  `ecart_certain` produits ») ;
- `rappel = appariées / erreurs` ; `rappel_certain = erreurs attendues certain appariées à un
  ecart_certain / erreurs attendues certain` ;
- `precision_detection = constats appariés / constats produits` ;
- `exactitude_montant = appariés à montant correct / appariés dont le montant attendu est non nul` ;
- `taux_surclassement = surclassements / vp_certain` ; `taux_sous_classement = sous-classements
  / erreurs attendues certain appariées` ;
- `bruit_a_verifier_par_dossier = fp_a_verifier / dossiers du split`.

**Extraction par champ** (si `findings.json` contient `valeurs`) : chaque document de vérité est
associé au document produit qui le recouvre le mieux (§2 ; puis le moins de pages en trop, puis
l'identifiant). Pour chaque champ obligatoire de §19.3.1 présent dans `truth_values`, la valeur
produite (forme `{"valeur": …}` ou brute ; clé à plat `acheteur.tva`, préfixée par le type,
ou imbriquée ; lignes en liste `lignes: [...]` ou `lignes[i].champ`, rang 0) est comparée après
normalisation : montants à 0,005 près, autres nombres par égalité décimale, booléens, références
et numéros de TVA par `norm_ref` (majuscules, `[A-Z0-9]` seulement), codes marchandise par leurs
chiffres, listes comme multi-ensembles, textes sans accents ni casse ni espaces multiples. Une
valeur absente est fausse. Les lignes sont comparées rang à rang.

**Regroupement** : les `expected_links` sont traduits en documents produits (même association
que ci-dessus) et comparés comme paires non orientées (le rôle est ignoré) aux `liens` produits
s'ils portent une source (`from`/`de`/`source…` et `to`/`vers`/`document_id`). Les liens de la
forme de l'Annexe C (`document_id` seul) sont évalués sur l'ensemble des documents rattachés
(mode `documents`). Micro-F1 sur le split.

**Coût et durée** : `execution.cout_ia_eur` et `execution.duree_s` ; moyenne, médiane, p95
(rang le plus proche : ⌈0,95 n⌉-ième valeur triée), maximum.

## 9. Seuil bloquant (§19.7)

Échoue si l'une des conditions est vraie (motif numéroté comme dans la spec) :

1. `precision_certain` globale < 0,97 (non évaluée si aucun constat certain) ;
2. un contrôle avec ≥ 10 constats `ecart_certain` produits a `precision_certain_constats` < 0,95 ;
3. moins de 30 constats `ecart_certain` produits **et** au moins un FP certain ;
4. `rappel` de P1 < 1,0 (si le split contient des erreurs P1) ;
5. une formulation interdite dans un `libelle`, une `prochaine_action` ou l'`avertissement`,
   ou une note de renvoi (`renvoi: true` ou `nature_montant: "renvoi"`) avec un
   `montant_en_jeu` non nul.

Formulations : `config/formulations_interdites.yaml` s'il existe et contient au moins une
expression (listes de chaînes, ou objets à clé `expression`/`texte`/`formulation`, clé `regex`
pour une expression régulière brute ; les clés `pourquoi`, `remplacer_par`… sont ignorées),
sinon copie intégrée du tableau de §3.2. Recherche insensible à la casse et aux accents,
tolérante au pluriel et au féminin, traits d'union facultatifs, bornes de mot. Note : par
insensibilité aux accents, « droit dû » couvre aussi « droit du ».

Alertes non bloquantes : coût IA moyen > 0,30 EUR, durée p95 > 300 s, bruit > 1,5 par dossier.

## 10. Choix d'interprétation

- **Occurrences miroir F3–F5** : l'appariement est un-à-un, mais un doublon entre dossiers peut
  être signalé dans les deux dossiers. La seconde occurrence n'est ni VP ni FP
  (`miroir_inter_dossiers`).
- **`doublon_composantes`** : « un autre constat apparié du même dossier porte le montant » =
  un autre constat apparié du même dossier a un `montant_en_jeu` non nul. Un constat redondant
  non apparié de ce type est neutre (sinon le comportement imposé par §8.6 serait un FP).
- **Précision par contrôle pour le seuil** : calculée sur le contrôle du constat (voir §8).
- **Pièges** : appariés seulement aux constats restés sans erreur ; un `a_verifier` sur un
  piège `a_verifier` est toléré et n'est pas compté comme bruit.
