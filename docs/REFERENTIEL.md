# ControlDOne v2 — Référentiel anonymisé de long terme

Agrégats de **prix** et de **taux d'écart** par transitaire × flux, calculés à partir des données validées
de tous les clients participants, sans aucune donnée identifiante. Code : `src/controldone/referentiel/` ;
tests : `tests/ops/test_referentiel.py` ; décisions D-620 à D-624 (`docs/DECISIONS.md`).

---

## 1. Ce qui entre

- **Clients** : actifs, hors ceux qui ont exercé l'**opt-out** prévu au contrat
  (`reglages["referentiel_opt_out"] = true`, posé par le fondateur ; effet au recalcul suivant).
- **Dossiers** : seulement ceux dont aucun constat n'attend la décision du fondateur (aucun `propose`) :
  données **validées**.
- **Valeurs lues** par dossier : pays d'origine (lignes de la facture commerciale, à défaut articles de la
  déclaration), Incoterm, régime de la déclaration (H1 / H7), mois (date d'acceptation de la déclaration),
  transitaire (nom et TVA, aussitôt anonymisés), montants HT des **prestations** de la facture du transitaire
  par nature (`frais_dedouanement`, `frais_avance_fonds`, `frais_ligne_supplementaire`, `magasinage`,
  `transport`, `manutention`, `surcharge` ; les débours ne sont pas des prix et sont exclus), présence d'au
  moins un constat « écart certain » validé.

## 2. Anonymisation

| Donnée | Traitement |
|---|---|
| Transitaire | **Alias public** s'il figure dans `config/referentiel_alias_publics.yaml` (liste tenue par le fondateur : uniquement des transitaires dont le nom peut être publié) ; sinon `T-` + 12 hexadécimaux de HMAC-SHA256(sel secret, TVA normalisée, à défaut nom normalisé). Sel : `CONTROLDONE_REFERENTIEL_SEL`, sinon dérivé de la clé maîtresse ; jamais exporté ; changer le sel change toutes les clés. |
| Client | Jamais exporté (sert seulement à compter les clients distincts). |
| Pays d'origine | Groupe : `ue`, `chine`, `asie_est`, `asie_sud_est`, `asie_sud`, `amerique_nord`, `royaume_uni`, `turquie`, `europe_autre`, `afrique_nord`, `autre`, `inconnu`. |
| Incoterm | Famille `E`, `F`, `C`, `D` (`inconnue`). |
| Régime | `standard` (H1 et assimilés) ou `petits_envois` (H7). |
| Période | Mois `AAAA-MM`. |
| Effectif | Tranche : `10-19`, `20-49`, `50-99`, `100+`. |
| Taux de dossiers avec écart | Arrondi au pas de 5 points (`0.30`). |
| Prix | Premier quartile, médiane, troisième quartile (rang le plus proche, valeur observée), arrondis à 5 EUR. |

Jamais exportés : noms et TVA de clients ou d'entités, adresses, numéros de facture, de déclaration (MRN),
de transport, identifiants internes (client, dossier, document), montants unitaires bruts.

## 3. Seuils de publication (k-anonymat)

- Un agrégat (transitaire × groupe d'origine × régime × famille d'Incoterm × mois) n'est publié que s'il
  réunit **au moins 5 clients distincts et au moins 10 dossiers**.
- Une statistique de prix d'une prestation n'est publiée que si **elle-même** réunit ces deux seuils.
- Les agrégats supprimés sont seulement **comptés** (`agregats_supprimes`), sans leur clé.
- Les seuils sont paramétrables pour les tests (`Seuils`) ; en production, ne jamais les abaisser.

Limite connue : des exports successifs à des dates différentes, croisés, peuvent permettre des différences
(attaque par différence) ; les publier à intervalle régulier (mensuel) et conserver les seuils.

## 4. Calcul et export

```bash
python -c "from controldone.jobs import enqueue; enqueue('referentiel_recalculer', {}, 'referentiel:2026-10-01')"
python -m controldone.jobs.worker --once
```

- Handler `referentiel_recalculer` → `controldone.referentiel.recalculer(db)` : écrit
  `<CONTROLDONE_DATA_DIR>/referentiel/referentiel.json` (schéma `controldone.referentiel/1.0.0`, seuils,
  arrondis, agrégats) et `referentiel.csv` (une ligne par agrégat publié ; colonnes `<nature>_p25`,
  `<nature>_mediane`, `<nature>_p75`).
- Recalcul complet à chaque exécution (pas d'état incrémental) ; un client qui exerce l'opt-out disparaît
  du calcul suivant.
- Cron conseillé : mensuel (`0 3 2 * *`).

## 5. Cadre contractuel

- La participation au référentiel figure au contrat (clause de réutilisation de données agrégées et
  anonymisées, avec faculté d'opposition) ; l'opt-out est appliqué sans délai au recalcul suivant.
- Les agrégats ne sont pas des données personnelles ni des données d'un client identifiable ; le fichier
  d'alias publics ne doit contenir aucun transitaire sans base pour publier son nom.
