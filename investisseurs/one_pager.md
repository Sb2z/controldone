# ControlDOne

**Contrôle indépendant, payé au résultat, des factures de transitaires et des déclarations d'import des PME françaises.**

*Pré-lancement, 2 octobre 2026. Les projections sont des hypothèses, pas des prévisions. Chaque chiffre renvoie à une source numérotée en bas de page.*

## Problème

Pour chaque import, une PME reçoit une facture commerciale, une déclaration en douane, la facture de son transitaire et parfois des avoirs. En pratique, personne ne les rapproche. Les éditeurs de logiciels annoncent des taux d'erreur de 2 % à 30 % sur les factures de transitaires, mais aucune mesure indépendante n'existe [1]. On sait que l'argent non réclamé est fréquent ailleurs :

- moins de 1 % des refus d'assurance santé ACA sont contestés aux États-Unis [2] ;
- 12 à 17 % des marchandises éligibles à une préférence tarifaire au Royaume-Uni ne la demandent pas [3].

Les cabinets payés au résultat facturent souvent au moins ~5 000 € [4]. Une petite PME importatrice reste donc sous leur seuil.

## Solution

Un **contrôle indépendant** : le transitaire n'est jamais utilisateur du produit. Le service rapproche les quatre documents et chiffre trois types d'écarts :

- **factuels** : erreurs de calcul ;
- **documentaires** : deux documents ne disent pas la même chose ;
- **contractuels** : une ligne facturée sort de la grille tarifaire convenue.

Chaque écart cite sa preuve (document, page, valeur lue). Le code testé compare et calcule, l'IA lit et rédige, et le fondateur valide tout ce qui part chez le client. Le client envoie lui-même ses réclamations. Les questions réglementaires sont renvoyées vers un représentant en douane enregistré (RDE) ou un avocat.

## Pourquoi maintenant

La réglementation devient plus complexe, avec des dates fixées :

- droit de **3 € par article** sur les petits envois depuis le 1er juillet 2026 [5] ;
- facturation électronique : **émission** obligatoire pour les PME au plus tard le **1er septembre 2027** [6] ;
- première **déclaration MACF/CBAM** au plus tard le **30 septembre 2027** [7] ;
- nouveau **Code des douanes de l'Union** applicable le **21 septembre 2027** selon KPMG, date non confirmée par une source officielle [8].

Le marché bouge aussi :

- en février 2026, environ **1 000 Md$** de valeur boursière du logiciel ont été effacés après les plugins métiers d'Anthropic [9] ;
- YC a demandé des « services natifs IA » **3 fois** en 2025–2026 [10] ;
- une cartographie de **46** sociétés de services IA n'en compte **aucune** basée en France ou en Suisse [11].

## Pourquoi chaque nouveau modèle d'IA le renforce

ControlDOne **achète de l'intelligence, il ne la revend pas**. Le client paie un résultat, le modèle d'IA n'est qu'un coût. Quand un modèle devient meilleur ou moins cher, l'extraction couvre plus de documents et coûte moins par dossier, sans changer le prix ni la piste d'audit, car les calculs restent déterministes.

- Coût d'IA par dossier aujourd'hui : **0 €** (extraction déterministe).
- Avec un LLM : environ **0,06 € à 0,24 €** par dossier, selon les prix catalogue 2026 et nos volumes de jetons (hypothèse).

À l'inverse, les apps d'IA vendues sur abonnement gagnent 41 % de plus par client payant, mais perdent leurs clients 30 % plus vite [12].

## Modèle économique

Prix de lancement :

- **diagnostic** : 390 € ;
- **commission** : 20 % des avoirs obtenus ;
- **contrôle continu** : à partir de 99 €/mois.

Un modèle comparable existe : Ownwell prend 25–35 % des économies de taxe foncière obtenues, compte 500 000 clients et se dit rentable selon son CEO [13].

Scénario central à 12 mois (**hypothèse**) : environ 24,9 k€ de revenus pour environ 1,3 k€ de coûts fixes, fondateur non rémunéré. La viabilité en solo demande au moins 3 000–4 000 € trouvés par client et par an (**calcul propre de l'auteur**). Ce seuil n'est pas encore démontré.

## Avantage défendable

- **Données de référence anonymisées par transitaire** : grilles tarifaires, types d'écarts récurrents.
- **Historique vérifiable** des écarts validés et des avoirs obtenus.
- **Voie vers le statut de RDE**, pour élargir légalement le périmètre.

Flexport propose déjà un audit automatisé des courtiers en douane [14]. ControlDOne, lui, reste indépendant du transitaire.

## Traction

**Aucune à ce jour, pré-lancement.** Il existe un prototype logiciel et un banc d'évaluation sur des données fictives. Aucun client, aucun revenu.

## Demande

**Aucune levée à ce jour, à définir.**

## Risques

- **Périmètre juridique.** Selon l'arrêt Alma Consulting (Cass. 1re civ., 15 nov. 2010, n° 09-66.319), dire si une charge est bien fondée relève de la consultation juridique. Le service s'en tient donc aux écarts factuels et contractuels, et renvoie le reste vers un RDE ou un avocat.
- **Propriété intellectuelle.** L'art. L. 113-9 CPI attribue à l'employeur le logiciel créé par un salarié. Le code antérieur, dont la propriété est incertaine, n'est pas réutilisé : la v2 est réécrite en salle blanche à partir d'une spécification.
- **Statut.** Le fondateur est seul et à temps partiel, et la forme juridique reste à choisir. RC Pro à partir de 13 €/mois [15].
- **Marché non mesuré.** Les taux d'erreur réels et le montant des avoirs obtenus par client restent à démontrer.

---

**Sources.**

1. Chiffres d'éditeurs, sans mesure indépendante.
2. KFF.
3. GOV.UK, preference utilisation 2024.
4. Compass Financement.
5. Règlement (UE) 2026/382.
6. economie.gouv.fr.
7. Règlement (UE) 2025/2083.
8. KPMG.
9. Forbes, « SaaSpocalypse Now ».
10. YC Requests for Startups.
11. Caritas Ventures.
12. RevenueCat, State of Subscription Apps 2026.
13. Crunchbase News.
14. Flexport.
15. Hiscox.

Hypothèses détaillées : `finance/modele_12_mois.xlsx`.
