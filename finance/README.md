# Modèle financier 12 mois — ControlDOne

> **Tous les chiffres sont des hypothèses, pas des prévisions.** ControlDOne est en pré-lancement : aucun client, aucun chiffre d'affaires et aucune traction à ce jour.

Fichier : `modele_12_mois.xlsx`. Il a été généré avec openpyxl, puis recalculé avec LibreOffice (headless). Les trois scénarios ont été vérifiés : aucune erreur `#REF!`, `#VALUE!` ou `#N/A`.

## Feuilles

| Feuille | Contenu |
|---|---|
| **Lisez-moi** | Avertissement, mode d'emploi, simplifications |
| **Hypothèses** | Toutes les entrées (cellules jaunes, texte bleu), en trois colonnes : prudent, central et ambitieux. Chaque ligne indique sa source, ou la mention « hypothèse du fondateur à valider ». La colonne F affiche la valeur du scénario actif. On y trouve aussi la rampe mensuelle des diagnostics et le bloc de coût d'IA. |
| **Modèle** | 12 colonnes mensuelles, uniquement des formules. Le scénario se choisit dans la cellule **B3** (liste déroulante). La feuille calcule les volumes, les avoirs obtenus, les revenus par flux, les coûts variables et fixes, la marge brute, le résultat, la trésorerie cumulée, le temps du fondateur et les mois d'équilibre. |

## Hypothèses principales (prudent / central / ambitieux)

| Paramètre | Valeurs | Source |
|---|---|---|
| Prix du diagnostic | 390 € | Prix de lancement (SPEC §1.1) |
| Abonnement | 99 €/mois | Prix de lancement, « à partir de » (SPEC §1.1) |
| Commission | 20 % des avoirs obtenus | Prix de lancement (SPEC §1.1). Repère : Ownwell prend 25–35 % (Crunchbase News) |
| Diagnostics vendus sur 12 mois | 23 / 39 / 69 (rampe mois par mois) | Hypothèse du fondateur à valider |
| Conversion diagnostic → abonnement | 15 % / 25 % / 40 % | Hypothèse du fondateur à valider |
| Avoirs obtenus par diagnostic | 300 / 800 / 1 500 € | Hypothèse du fondateur à valider. Les taux d'erreur annoncés par les éditeurs vont de 2 % à 30 %, mais aucune mesure indépendante n'existe. |
| Avoirs obtenus par abonné | 50 / 150 / 300 € par mois | Hypothèse du fondateur à valider |
| Délai avant encaissement de l'avoir | 3 / 2 / 2 mois | Hypothèse du fondateur à valider |
| Attrition mensuelle | 8 % / 5 % / 3 % | Hypothèse. Contexte : les apps d'IA perdent leurs payants 30 % plus vite (RevenueCat, State of Subscription Apps 2026) |
| Coût d'IA par dossier | **0 €** aujourd'hui (extraction déterministe) | SPEC P-4, DECISIONS D-018 |
| … si un LLM est activé | Opus 5.5 ≈ 0,24 €, Sonnet 5.5 ≈ 0,12 €, Haiku 4.5 ≈ 0,06 € par dossier | Prix catalogue 2026 : 4/20, 2/10 et 1/5 $ par million de jetons (entrée/sortie). Volumes supposés : 25 000 jetons en entrée et 8 000 en sortie par dossier ; 1 $ = 0,92 € (hypothèses). |
| Hébergement UE | 20 / 10 / 10 €/mois | Fourchette de 0,43 € (Scaleway) à 19,99 € HT (OVHcloud VPS-3), cf. `docs/recherche/legal_market.md` §6 |
| RC Pro | 25 / 13 / 13 €/mois | Hiscox, à partir de 13 €/mois. La valeur prudente est une hypothèse. |
| Stripe | 2,2 % / 2 % / 2 % + 0,25 € par transaction | Hypothèse, à vérifier sur la grille Stripe |
| Expert-comptable | 100 / 70 / 70 €/mois | Hypothèse |
| Plateforme agréée (facturation électronique) | 25 / 15 / 15 €/mois | Hypothèse. La réception est obligatoire depuis le 1er septembre 2026, l'émission pour les PME au plus tard le 1er septembre 2027 (economie.gouv.fr) |
| Temps du fondateur | 40 / 40 / 60 h disponibles par mois | Hypothèse. Le temps n'est pas rémunéré ; un taux théorique de 35 €/h sert à un second seuil d'équilibre. |

## Ce que le modèle produit (état livré, sans LLM)

| Indicateur (hypothèses) | Prudent | Central | Ambitieux |
|---|---|---|---|
| Revenus sur 12 mois | ≈ 11 200 € | ≈ 24 900 € | ≈ 58 900 € |
| Résultat avant rémunération du fondateur | ≈ 8 900 € | ≈ 23 100 € | ≈ 56 300 € |
| Équilibre mensuel | M2 | M1 | M1 |
| Équilibre après rémunération théorique | M8 | M3 | M2 |
| Capacité horaire dépassée ? | non | non | non |

L'équilibre arrive vite pour deux raisons :

- les coûts fixes sont faibles, environ 110 à 170 € par mois ;
- le temps du fondateur n'est pas payé.

L'indicateur utile est donc plutôt le **revenu horaire implicite**, c'est-à-dire le résultat divisé par les heures. Il figure à la ligne 51 de la feuille « Modèle ».

## Ce qu'il faut retenir

1. **Le point sensible, ce sont les avoirs obtenus par client.** Dans le scénario central, un abonné obtient 1 800 € d'avoirs par an. Or la viabilité en solo suppose de trouver au moins 3 000 à 4 000 € par client et par an (calcul propre de l'auteur). Le modèle l'affiche : « NON — revoir l'hypothèse ». Seul le scénario ambitieux (3 600 €) dépasse ce seuil. C'est la première chose à mesurer pendant les premiers diagnostics.
2. Les revenus centraux viennent surtout des diagnostics (≈ 61 %), puis des commissions (≈ 22 %) et des abonnements (≈ 17 %). Le modèle reste donc très sensible au rythme de vente des diagnostics.
3. Activer un LLM coûte peu dans ces hypothèses : environ 144 € sur 12 mois avec Sonnet dans le scénario central. Ce coût est par ailleurs plafonné par client dans le produit (D-018).
4. Le modèle ne tient compte ni de la TVA, ni de l'impôt, ni des cotisations du fondateur, car le statut n'est pas choisi.

## Modifier le modèle

Il suffit de modifier les cellules jaunes de la feuille « Hypothèses » et de choisir le scénario en `Modèle!B3`. Excel et LibreOffice recalculent automatiquement à l'ouverture.
