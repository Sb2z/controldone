# Audit final de ControlDOne v2

*2 et 3 octobre 2026. Revue complète de la structure technique, du projet et du cadre juridique (France, Suisse), suivie des corrections et des optimisations. Rien n'a été envoyé, publié ni déployé.*

## En bref

- **Méthode.** Cinq diagnostics indépendants, faits sans modifier le code :
  - bugs du moteur ;
  - robustesse de la plateforme ;
  - performance et poids ;
  - qualité et cohérence du code ;
  - recherche juridique sourcée.

  Trois équipes ont ensuite corrigé le code (moteur, plateforme, performance) et une quatrième a aligné les textes juridiques. Une correction n'était gardée que si le banc d'évaluation restait identique ou s'améliorait.
- **Résultat.**
  - Une quarantaine de défauts réels corrigés, chacun avec un test qui échouait avant la correction.
  - Le traitement est 39 % plus rapide, avec des sorties identiques octet pour octet.
  - La mémoire est fortement réduite.
  - Le produit est reformulé pour rester du bon côté du périmètre du droit.
- **Vérification finale.**
  - 1 703 tests verts (1 542 avant l'audit) et lint propre.
  - Aucune erreur interne sur 250 dossiers.
  - Seuil bloquant franchi sur le banc de développement et sur le corpus tenu à l'écart.
  - Démonstration complète relancée : santé, connexion et API répondent 200.

## Résultats mesurés, avant et après

| Indicateur | Avant l'audit | Après l'audit |
|---|---|---|
| Tests | 1 542 | **1 703** |
| Banc de développement : écarts certains vrais / faux | 114 / 0 | **114 / 0** |
| Banc de développement : rappel | 81,3 % | **81,3 %** |
| Banc de développement : exactitude des montants | 95,8 % | **96,5 %** |
| Banc de développement : bruit « à vérifier » par dossier | 1,41 | **1,38** |
| Corpus tenu à l'écart : écarts certains vrais / faux | 46 / 0 | **46 / 0** (aucune régression) |
| Dossiers dont les totaux du rapport divergent de la vérité | 49 | **43** |
| Banc complet à froid (202 dossiers, 4 processus) | 1 171 s | **720 s** (−39 %) |
| Lot de 3 dossiers en série | 121 s | **23 s** (÷ 5) |
| Mémoire retenue après 8 rapports | 363 Mo | **168 Mo** |
| Contrôle de santé pendant un dépôt de 450 Mo | bloqué 28 s | **0,25 s au pire** |
| Attente des autres écritures pendant un gros dépôt | 27 s | **0 s** |
| Mémoire de la sauvegarde | 6,3 Go (coffre de 1,1 Go) | **77 Mo** (coffre de 1,7 Go) |
| Mémoire du serveur pour un dépôt de 450 Mo | 885 Mo | **258 Mo** |
| Même tâche exécutée deux fois après une panne de bail | oui | **non** |
| Rapports rejoués identiques (hors horodatage) | non (vote OCR dépendant du hasard) | **oui** |

## Ce qui a été corrigé

### Moteur (décisions D-1201 à D-1216)

- **Totaux du rapport.**
  - Un avoir partiel (E6) était compté en plus de l'écart qu'il remplace.
  - C5 gardait son montant à côté de C1 à C4.
  - Un même écart de valeur était compté deux fois (F5 et A4).
  - Une seule règle décide désormais de ce qui entre dans les totaux, partagée par le rapport, l'interface et l'API.
- **Faux écarts sur les relevés couvrant plusieurs MRN** : les allocations au prorata créaient des paires ±X. Arrondis corrigés (demi vers le haut, reste attribué à la dernière part).
- **Exception avalée** : une panne interne pouvait donner un dossier « conforme ». Elle donne maintenant « à vérifier », avec le motif `erreur_interne`.
- **Libellés bloqués par le filtre juridique** : ils restaient lisibles dans les exports JSON ; ils sont maintenant neutralisés partout.
- **Imputation des avoirs** : quatre implémentations différentes, réduites à une seule. Un écart D3 de 29,56 EUR passe à 10,63 EUR, net de l'avoir, comme attendu.
- **Classement des lignes** : un seul tableau de classement par nature. « Forfait dédouanement » n'est plus pris pour le droit forfaitaire des petits colis.
- **Chargement explicite** des 59 contrôles et des extracteurs : un module manquant fait échouer bruyamment au lieu de baisser le rappel en silence.
- **Filtre des formulations interdites** :
  - « droit du tarif » n'est plus bloqué, « montants dus » l'est ;
  - les contournements par trait d'union conditionnel ou espace de largeur nulle ne passent plus.
- **Divers.**
  - Clé de mémoïsation complète.
  - Tiret espacé lu à tort comme un signe moins.
  - Arrondi des frais d'avance de fonds.
  - Doublons de code et code mort supprimés.

### Plateforme (D-1301 à D-1326)

- **Purge RGPD à 180 jours** : elle n'effaçait jamais rien, la clôture des dossiers n'étant jamais enregistrée. Corrigé et testé avec un saut dans le temps.
- **Sauvegarde** : chiffrement en flux au lieu d'une archive entière en mémoire, et alerte en cas d'échec.
- **Disponibilité** : les traitements lourds (dépôt, chiffrement, PDF, mots de passe) ne bloquent plus le serveur. Le verrou d'écriture SQLite est tenu quelques millisecondes au lieu de 30 s. Les lectures du fondateur ne prennent plus ce verrou.
- **File de tâches.**
  - Bail protégé par un jeton : une tâche ne peut plus tourner deux fois.
  - Registre unique des traitements : le worker intégré au web ne tue plus les tâches des agents.
  - Ordonnancement équitable entre clients.
  - Limite de temps par fichier.
- **Facturation.**
  - Un paiement Stripe ne peut plus être écrasé par une proposition d'abonnement.
  - Un second avoir partiel n'est plus confondu avec le premier.
  - Une seule source pour le taux de commission.
  - Mois calculés en heure de Paris partout.
  - Coupon de lancement utilisable sans accord de publication.
- **Recouvrement** : le parcours réel contournait le service des litiges, de sorte qu'aucune relance n'était planifiée et aucune commission proposée. Il passe maintenant par ce service, avec un test de bout en bout depuis l'espace client.
- **Réglages** : le fichier `.env` est lu partout, ce qui règle le cas où `CONTROLDONE_ENV=prod` y était ignoré. Les plafonds de coût d'IA sont effectifs. Un analyseur strict unique traite les montants saisis (NaN, infini et valeurs absurdes refusés).
- **Requêtes** : bornées, paginées, triées avant la limite ; une requête par document en moins.
- **Schéma de base** : le service refuse de démarrer sur une base trop ancienne et liste les colonnes manquantes, au lieu d'échouer plus tard.

### Performance (D-1400 à D-1406)

Les sorties restent identiques : 202 `findings.json` et 2 409 pages OCR identiques octet pour octet, et extraction identique champ par champ.

- Images passées à Tesseract en PGM au lieu de PNG (−31 % de temps OCR, texte identique).
- Un processus de lecture par fichier, lancé depuis un serveur préchargé et sans aucun secret dans son environnement.
- Fichiers d'un lot traités en parallèle, avec ordre et identifiants inchangés. Réglable par `CONTROLDONE_PAGES_PARALLELE` : mettre 2 sur une machine de 2 Go.
- Calcul quadratique supprimé dans la lecture de texte.
- Caches d'images et de textes vidés après chaque rapport et chaque lot.
- PDF de rapport 17 % plus légers.
- numpy retiré : redressement des scans réécrit sans lui, avec des angles identiques sur 220 images de test. Gain : environ 57 Mo dans l'environnement, 72 Mo dans l'image.
- Pistes écartées car elles modifient le texte lu par l'OCR : résolution réduite, une seule langue, détection d'orientation sur image réduite.

## Juridique : ce que dit la recherche (France, Suisse)

La note complète, sourcée et marquée « à faire confirmer par un avocat », est dans `docs/recherche/juridique_france_suisse.md`. Points principaux :

- **Le calcul de cohérence entre documents est licite pour un non-avocat.** En revanche, juger si un droit, une taxe ou une clause est fondé, rechercher des remboursements auprès de la douane, ou rédiger pour le client une réclamation personnalisée qui invoque un droit relève de l'exercice du droit. Références : Cass. 1re civ. 15 nov. 2010 (Alma) ; Cass. 1re civ. 17 fév. 2016 (Syncost) ; CA Paris 9 avr. 2018 et 15 sept. 2022. **Faire valider le travail par un avocat ne régularise pas.**
  - *Conséquence appliquée :* les « dossiers de demande d'avoir » sont devenus un **relevé d'écarts** factuel et un **modèle neutre** que le client adapte et envoie lui-même. Aucune mise en demeure, aucun délai, aucune citation juridique.
- **Commission de 20 %** : licite si l'activité n'est pas juridique. Elle exclut désormais tout remboursement accordé par la douane ou une autorité et se calcule hors TVA.
- **Douane** : déposer, rectifier ou demander un remboursement pour le client est réservé aux représentants en douane enregistrés. Le produit ne le fait pas.
- **Emploi** : la création d'entreprise reste possible, la clause d'exclusivité étant inopposable un an (art. L1222-5 du code du travail), mais le devoir de loyauté demeure. **Le risque est élevé si l'employeur est un transitaire, un commissionnaire, un éditeur de logiciel douane ou un cabinet de conseil.** Un agent des douanes doit obtenir une autorisation préalable.
- **Diagnostic gratuit « contre » la publication** : risque fiscal (troc taxable). Il devient une remise de lancement de 100 % assortie d'un accord de publication séparé, facultatif et révocable.
- **Experts-comptables** : leur verser une commission d'apport est **interdit** (art. 24 de l'ordonnance de 1945). Le site le dit désormais.
- **Petits clients** (5 salariés ou moins, contrat signé hors établissement) : droit de rétractation de 14 jours. Signer à distance.
- **Référentiel** : statistiques de prix seulement, jamais de taux d'erreur par transitaire nommé ; un transitaire n'est nommé qu'avec son accord écrit.
- **Données** :
  - transfert vers Anthropic sur la base des clauses contractuelles types et de l'addendum suisse (le cadre UE–États-Unis fait l'objet d'un recours) ;
  - délai d'objection de 15 jours pour les nouveaux sous-traitants ;
  - données de prospection conservées 3 ans à compter de la collecte ou du dernier contact.
- **Suisse** :
  - le conseil juridique n'y est pas réservé ;
  - la nouvelle loi sur la protection des données (nLPD) prévoit des amendes jusqu'à 250 000 CHF, infligées à la personne responsable ;
  - prospection par e-mail individuel seulement ; opt-in pour les envois de masse ;
  - pas d'immatriculation TVA en Suisse pour un fondateur établi en France.
- **TVA et facturation** : franchise de TVA aux seuils de 37 500 / 41 250 EUR (la réforme à 25 000 EUR a été abrogée). Réception des factures électroniques obligatoire depuis le 1er septembre 2026, émission au 1er septembre 2027.
- **Responsabilité** : le plafond de responsabilité des CGV a reçu un montant minimum (sinon la clause tombe). L'assurance RC Pro n'est pas obligatoire mais fortement recommandée ; vérifier qu'elle couvre les pertes financières pures.

Textes mis à jour en conséquence :
- CGV, accord de sous-traitance, confidentialité, mentions légales ;
- pages tarifs, accueil, méthode et experts-comptables (et leur version anglaise) ;
- offres, registre RGPD, méthode de prospection, séquence d'e-mails, 20 brouillons (dont **les 13 brouillons Gmail**), posts LinkedIn.

## Tests intensifs (après l'audit)

Voir `docs/TESTS_INTENSIFS.md` : corpus public de 859 factures électroniques officielles, second générateur aveugle, campagne de 571 entrées hostiles, endurance de 1 010 dossiers. Sur un jeu vierge de 80 dossiers, la précision des écarts certains est de 98,0 % (50/51) ; la robustesse ne montre aucun plantage.

## Ce qui reste ouvert

- **Non vérifiés** :
  - plafond micro-entreprise 2026 (77 700 ou 83 600 EUR selon les sources) ;
  - date d'entrée en vigueur des nouvelles mentions de facture ;
  - certification DPF d'Anthropic ;
  - absence de règle française annulant les honoraires de résultat sur des remboursements douaniers ;
  - statut des agents en douane en Suisse.
- **Pour l'avocat** : les « prochaines actions » du rapport suggèrent au client de « demander un avoir au transitaire ». C'est une suggestion factuelle laissée à sa décision, mais à faire valider. La note juridique liste dix questions pour le rendez-vous (§10).
- **Technique** :
  - pas de migrations de base (le service refuse désormais une base trop ancienne au lieu de planter) ;
  - installation non éditable sans `config/` ni `ref/` (contournement : installation en mode éditable, comme dans le Dockerfile) ;
  - l'API `/dossiers` pagine en mémoire ;
  - le registre de coûts d'IA reste en mémoire par lot côté moteur ;
  - le dédoublonnage des avoirs n'est pas testé sous PostgreSQL ;
  - les points de sécurité RS-16 à RS-21 sont toujours ouverts ; RS-16 est atténué, le `.env` étant désormais lu.
- **Banc** : le bruit « à vérifier » reste au-dessus de l'alerte sur le corpus tenu à l'écart (1,67 par dossier). Aucun document réel n'a encore été traité.
