# Lecture par modèle de langage (D-4001 à D-4008)

Bloc : activation de l'extracteur `llm` (décision du fondateur D-4000, point 1).

## Fait

- **Appel seulement si le déterministe est faible, complément sans remplacement** (D-4001) — `extract/llm.py`
  (`motif_appel`, `completer`), une ligne dans `pipeline._extraire`.
- **Ancrage obligatoire, valeurs introuvables rejetées, confiance ≤ 0,65** (D-4003) — `localiser`,
  `PLAFOND_CONFIANCE_LLM`.
- **Coût depuis l'usage (cache compris), tarifs datés** `config/llm_tarifs.yaml` ; **plafond mensuel vérifié avant
  chaque appel** (worker -> `OptionsPipeline`) (D-4004).
- **Minimisation** : pages du document seulement, texte seul par défaut (D-4005).
- **`controldone llm verifier` / `couts`** (D-4006) ; **opt-out** `reglages.llm_desactive` (D-4007).
- **Mesure** `scripts/mesure_llm.py` prête, testée avec un faux client (D-4008).
- Registre RGPD, DPA, SPEC, `.env.example`, `EXPLOITATION.md`, `MISE_EN_LIGNE.md` mis à jour.

## À faire

- **Lancer la mesure dès que la clé existe** — `python scripts/mesure_llm.py --corpus bench/corpus_g4 --limit 20
  --confirmer-depense`, puis `--effort medium` pour comparer. Décider l'effort (et éventuellement
  `claude-sonnet-5-5`) sur le coût par dossier et l'exactitude ; consigner les chiffres dans D-4008.
  Impact : le choix `low` (D-4002) n'est pas encore mesuré.
- **Interface : case « lecture par Claude » sur la fiche client** — aujourd'hui l'opt-out s'écrit dans
  `reglages["llm_desactive"]` (pas de case dédiée ; `web/routes_admin.py` écrit déjà `reglages` pour le plafond).
  Équipe interface. Impact : le fondateur doit passer par la base ou l'API pour désactiver.
- **Alerte 100 % quand un appel est refusé par anticipation** — `CostGuard` refuse un appel dont l'estimation
  dépasserait le plafond alors que le coût réel est encore sous 100 % : aucune alerte `cout_ia_plafond` n'est émise
  dans ce cas (le lot est seulement « extraction partielle »). Proposition : remonter l'avertissement
  `plafond_client` au handler et signaler l'alerte. Faible impact (le seuil 80 % a déjà alerté).
- **Les valeurs du modèle entrent dans le réseau d'identités (D-1700)** — une ligne lue par le modèle (ancrée,
  0,65) peut confirmer, par une somme imprimée, un montant lu par le déterministe. C'est conforme à D-1700 (les
  valeurs `llm` y sont des valeurs lues), et les chiffres sont imprimés sur la page ; à surveiller dans la mesure
  D-4008 (nouveaux faux certains). Option si besoin : exclure `Methode.llm` des confirmations
  (`controls/corroboration.py`, équipe moteur).
- **Coût du test `controldone llm verifier` non rattaché à un client** — affiché seulement ; quelques jetons.
- **Banc avec modèle en CI** — non : la CI ne doit jamais dépenser ; la mesure reste manuelle.
- **Tarifs** — redater `config/llm_tarifs.yaml` à chaque changement de prix ou de modèle (source :
  https://www.anthropic.com/pricing) ; vérifier `CONTROLDONE_USD_EUR`.
