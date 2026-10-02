# Brief réglementaire : douane UE, TVA import France, droit de 3 €, MACF/CBAM, réforme du CDU

*Recherche faite le 2 octobre 2026. Le web était accessible. Deux pages n'ont rien renvoyé : la page EUR-Lex du règlement 2026/382 et le communiqué du Parlement européen sur la réforme. eucdm.softdev.eu.com a répondu 403. Pour les numéros de données, la source vérifiée est le guide opérateur AIS de l'administration fiscale irlandaise (Revenue), version 3.07. C'est une transposition nationale de l'Annexe B, pas le texte du règlement lui-même.*

## 1. Jeu de données H1 (mise en libre pratique), Annexe B des actes délégué et d'exécution du CDU

**Faits vérifiés**
- Les exigences en données des déclarations figurent à l'Annexe B de l'acte délégué (RD 2015/2446) et de l'acte d'exécution (RE 2015/2447) du CDU. La version actuelle du modèle de données douanier de l'UE (EUCDM) est la 7.0.11, publiée en août 2026. Source : https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/eu-customs-data-model-eucdm_en

Numéros des données (DE) et des groupes de données (DG), avec l'ancien numéro entre parenthèses. Source pour tout le tableau : https://www.revenue.ie/en/online-services/support/software-developers/documents/ais/cci/trader-guide.pdf

| Donnée | Numéro Annexe B | Ancien n° | Remarque |
|---|---|---|---|
| Conditions de livraison (Incoterm) | DG 14 01 000 000 / DE 14 01 035 000 (code INCOTERM, a3) | 4/1 | Obligatoire au niveau de l'envoi pour H1 |
| Droits et taxes | DG 14 03 000 000 | nouveau | |
| Type de taxe | DE 14 03 039 000 (an3) | 4/3 | |
| Mode de paiement | DE 14 03 038 000 (a1) | 4/8 | Un seul mode de paiement par déclaration |
| Base d'imposition | DG 14 03 040 000 | 4/4 | Contient : unité de mesure 14 03 040 005, quantité 040 006, montant 040 014 |
| Taux d'imposition | DE 14 03 040 041 | 4/5 | |
| Montant de la taxe (par base) | DE 14 03 040 043 (n..16,6) | — | |
| Montant de taxe à payer | DE 14 03 042 000 | 4/6 | |
| Montant total des droits et taxes | DE 14 16 000 000 | — | |
| Monnaie nationale | DE 14 17 000 000 | — | |
| Monnaie de facturation | DG 14 05 000 000 / DE 14 05 001 000 | 4/10 | |
| Montant total facturé | DG 14 06 000 000 (sous-élément 14 06 001 000) | 4/11 | |
| Indicateurs d'évaluation | DE 14 07 001 000 | 4/13 | |
| Montant facturé de l'article | DE 14 08 001 000 | 4/14 | |
| Taux de change | DE 14 09 001 000 (n..12,5) | — | |
| Méthode d'évaluation | DG 14 10 000 000 / DE 14 10 001 000 | 4/16 | |
| Préférence | DE 14 11 001 000 (n3) | 4/17 | |
| Pays d'origine | DE 16 08 001 000 | 5/15 | |
| Pays d'origine préférentielle | DE 16 09 001 000 | 5/16 | |
| Masse nette (kg) | DE 18 01 001 000 | 6/1 | |
| Masse brute totale (kg) | DE 18 03 001 000 | nouveau | |
| Masse brute (kg) | DE 18 04 001 000 | 6/5 | |
| Nombre de colis | DE 18 06 004 000 | 6/10 | Type de colis : DE 18 06 003 000 (6/9) |
| Code marchandise | DG 18 09 000 000 | — | SH 18 09 056, NC 18 09 057 (6/14), TARIC 18 09 058 (6/15), code additionnel TARIC 18 09 059 (6/16), codes additionnels nationaux 18 09 060 (6/17) |
| Valeur statistique | DE 99 06 001 000 (n..16,2, en euros) | 8/6 | Obligatoire au niveau article pour H1 |
| Régime | DE 11 09 001 000 | 1/10 | |
| Régime complémentaire | DE 11 10 001 000 | 1/11 | |
| Document d'accompagnement | DG 12 03 000 000 | 2/3 | |
| Référence fiscale complémentaire | DE 13 16 000 000 | 3/40 | |

Le guide irlandais ne contient aucune donnée intitulée « valeur en douane » dans H1. On n'y trouve qu'une mention « Amendment of the customs value » (code A10).

## 2. Autoliquidation de la TVA à l'importation (ATVAI) en France

**Faits vérifiés**
- Depuis le 1er janvier 2022, l'autoliquidation est obligatoire et automatique, sans autorisation préalable. Elle concerne les assujettis identifiés à la TVA en France et les personnes non assujetties qui ont un numéro de TVA intracommunautaire français valide. Source : https://www.douane.gouv.fr/demarche/beneficier-automatiquement-de-lautoliquidation-de-la-tva-limport
- Sur la déclaration en douane, l'importateur indique son numéro de TVA français. Dans DELTA G ou DELTA X import, c'est le code document 1008 suivi du numéro de TVA. Dans DELTA H7, c'est la référence fiscale complémentaire FR7 suivie du numéro de TVA. Source : même page.
- La TVA est déclarée et déduite en même temps sur la CA3, mensuelle ou trimestrielle, donc sans avance de trésorerie. La DGFiP pré-remplit la CA3 vers le 14 du mois suivant à partir des données douanières. L'entreprise vérifie via le service en ligne « Données ATVAI » et peut corriger jusqu'au 24. Sources : même page, et https://www.douane.gouv.fr/actualites/partir-du-1er-janvier-2022-autoliquider-sa-tva-limportation-devient-obligatoire-et (vue en résultat de recherche).
- Le dispositif exclut les régimes suspensifs et les opérations non taxables. Les entreprises au régime simplifié d'imposition (RSI) ou en franchise doivent régulariser leur situation avant d'importer. Source : page démarche ci-dessus.
- Textes de référence : BOD n° 7440 du 23 novembre 2021 (https://www.douane.gouv.fr/sites/default/files/uploads/files/BOD%207440%20blanc%20op%C3%A9rateurs.pdf) et Q/R ATVAI 2022 (https://www.douane.gouv.fr/sites/default/files/2021-12/27/Questions-Reponses-Dispositif-ATVAI-2022-Operateurs.pdf). Ces deux documents ont été vus en résultats de recherche, pas lus.

## 3. Droit de douane forfaitaire de 3 € sur les petits envois

**Faits vérifiés**
- Base légale : règlement du Conseil (UE) 2026/382. Il est accompagné d'un acte délégué CDU modifié, adopté le 30 avril 2026, et d'un acte d'exécution CDU publié au JO le 8 juin 2026. Source : https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en
- Calendrier : application du 1er juillet 2026 au 1er juillet 2028. Les identifiants produit (PID) sont facultatifs au départ et deviennent obligatoires le 1er novembre 2026. Source : même page.
- Définition d'un « article » : il se détermine par le classement tarifaire, pas par la quantité. Cinq T-shirts font un seul article, donc 3 €. Un T-shirt et une montre font deux articles, donc 6 €. Sources : https://commission.europa.eu/news-and-media/news/ensuring-fairness-and-safety-eur3-customs-duty-low-value-parcels-2026-06-29_en et la page guidance ci-dessus.
- Champ : envois d'une valeur jusqu'à 150 €, dans le cadre de ventes à distance de biens importés, quel que soit le régime TVA (IOSS, régime particulier ou régime normal). Exclusion : les marchandises sous accord préférentiel ou mesure d'union douanière, si la TVA n'est pas perçue via l'IOSS et si la déclaration est faite en H1. Le redevable est le déclarant, c'est-à-dire le vendeur ou l'importateur. Source : page guidance ci-dessus.

## 4. MACF/CBAM : période définitive

**Faits vérifiés** (source : https://www.dehst.de/EN/Topics/CBAM/CBAM-definitive-regime-2026/cbam-definitive-regime-2026_node.html, site de l'autorité allemande compétente)
- La période définitive a commencé le 1er janvier 2026.
- Le statut de déclarant autorisé est obligatoire avant d'importer de l'électricité, de l'hydrogène, ou plus de 50 tonnes par an d'autres marchandises CBAM. Sous ce seuil de 50 t cumulées (hors électricité et hydrogène), l'importateur est exempté.
- Une importation reste possible en attendant l'autorisation si la demande a été déposée avant le 31 mars 2026. Elle se déclare avec le code TARIC Y238.
- La première déclaration annuelle (année 2026) et la restitution des certificats sont dues au 30 septembre 2027, puis chaque 30 septembre.
- Les certificats sont vendus sur la plateforme centrale à partir de février 2027.
- À partir de 2027, le déclarant doit détenir chaque trimestre des certificats couvrant au moins 50 % des émissions intrinsèques importées depuis le début de l'année.

## 5. Réforme du Code des douanes de l'Union

**Faits vérifiés**
- La réforme a été adoptée le 16 septembre 2026. Le Bureau européen des douanes (EUCA) sera installé à Lille et mis en place en 2027. La plateforme de données douanières de l'UE (EU Customs Data Hub) sera ouverte à l'e-commerce le 1er juillet 2028, aux opérateurs volontaires en 2031, et deviendra obligatoire pour tous le 1er mars 2034. Les frais de traitement (« handling fee ») doivent être introduits au plus tard le 1er novembre 2026. Source : https://taxation-customs.ec.europa.eu/customs/eu-customs-reform_en
- Publication au JO le 19 septembre 2026, entrée en vigueur le 20 septembre 2026, application progressive. Source : https://kpmg.com/us/en/taxnewsflash/news/2026/09/tnf-eu-customs-reform-enters-into-force-with-new-e-commerce-rules.html
- **Point à vérifier :** la page de la Commission indique une entrée en vigueur au 21 septembre 2026, alors que KPMG indique le 20 septembre.
- L'accord politique entre le Parlement et le Conseil date du 26 mars 2026. Source : https://www.europarl.europa.eu/news/en/press-room/20260323IPR38815/deal-reached-on-union-customs-code-reform (vu en résultat de recherche, page vide au fetch).

## Hypothèses non vérifiées

- **Confiance moyenne :** le nouveau CDU serait le règlement (UE) 2026/2108, applicable pour l'essentiel à partir du 21 septembre 2027. L'information vient de résumés de recherche (vatupdate, globallawexperts). Elle n'a été confirmée ni sur EUR-Lex ni sur la page KPMG lue, qui ne cite ni ce numéro ni cette date. La date du 21 septembre 2027 évoquée dans votre demande n'est donc pas confirmée par une source officielle.
- **Confiance moyenne-haute :** le règlement (UE) 2025/2083 aurait repoussé la première déclaration CBAM du 31 mai 2027 au 30 septembre 2027 et introduit le seuil de 50 t. Ce lien n'a été vu que dans des résumés de sites secondaires. Le texte EUR-Lex n'a pas été lu.
- **Confiance haute :** pour le droit de 3 €, « article » renverrait à la sous-position tarifaire distincte (code NC/TARIC) dans l'envoi. Les sources officielles parlent de « tariff classification » sans préciser à combien de chiffres. Le texte du règlement 2026/382 n'a pas pu être lu.
- **Confiance haute :** les codes de type de taxe seraient A00 pour les droits de douane et B00 pour la TVA à l'import. Ce n'est pas vérifié ici. Ces codes viennent de la liste nationale ou de l'EUCDM, pas des pages consultées.
- **Confiance moyenne :** le mode de paiement utilisé en France pour l'ATVAI dans DELTA (lettre de la donnée 14 03 038) n'a pas été vérifié. Seuls le code document 1008 et la référence FR7 sont confirmés.
- **Confiance moyenne :** dans l'Annexe B, H1 ne comporterait pas de donnée « valeur en douane » distincte. La valeur en douane passerait par la base d'imposition (14 03 040) et par les éléments d'évaluation (méthode, ajustements, taux de change). À confirmer sur l'EUCDM 7.0.11.
- **Confiance haute :** les numéros relevés dans le guide irlandais correspondent à ceux de l'Annexe B en vigueur. Les statuts « facultatif » ou « obligatoire » qu'il affiche sont en revanche propres à l'Irlande et peuvent différer de DELTA en France.