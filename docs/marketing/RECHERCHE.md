# Recherche marketing et design : ControlDOne

*Version 1.0, 7 octobre 2026. Document de travail pour le fondateur. Toutes les pages citées ont été ouvertes le 2026-10-07 ; la liste complète, avec les URL, est en fin de document (références [R1] à [R62]). Quand un point n'a pas de source, il est marqué « avis » ou « non vérifié ».*

Ce document part de l'existant : `site/index.html`, `site/tarifs.html`, `site/methode.html`, `docs/SPEC.md` (§3, garde-fous), `commercial/plan_actions_commerciales.md`, `commercial/sequence_emails.md` et `commercial/prospects_methode.md`. Il ne remplace aucun de ces fichiers. Il ne constitue pas un avis juridique : la partie 5 résume des textes et des pages d'autorités, à faire relire par un avocat avant toute mise en ligne.

Trois constats d'ensemble, avant le détail :

1. Les textes actuels sont exacts et prudents. Ce qui les fait « sonner IA », c'est surtout la forme : formules nominales sans verbe, rythmes en trois temps, titres en paire « Le problème / slogan », question rhétorique en titre principal. Le fond (preuve par écart, calcul déterministe, renvoi RDE/avocat) est le meilleur argument du produit et il est déjà là.
2. Le site public est aujourd'hui sans script ni police externe, et un test le vérifie (`tests/site`). Toute animation sur le site public oblige à trancher : rester en CSS seul, ou accepter un script servi localement (Motion) en modifiant le test et la CSP. La partie 4 traite les deux cas.
3. Deux affirmations du site sont à revoir avant publication : la date d'émission obligatoire des factures électroniques pour les PME (1er septembre 2027) n'apparaît pas sur la page impots.gouv.fr consultée ([R55]) ; et l'idée d'« hébergement en France » ne doit pas être utilisée, la page Méthode indiquant un hébergement dans l'UE et une lecture par un modèle de langage aux États-Unis.

---

## 1. Positionnement et message

### 1.1 Le cadre utilisé

**Positionnement (April Dunford).** Cinq composantes, dans cet ordre : alternatives concurrentes, capacités différenciantes, valeur pour le client, segment cible, catégorie de marché. La question de départ est « que ferait le client si votre offre n'existait pas ? » ([R13]). L'ordre compte : une capacité n'est différenciante que comparée aux alternatives réelles.

**Jobs to be done (Christensen, Moesta).** Le client « embauche » un produit pour progresser dans une situation donnée ; chaque job a une dimension fonctionnelle, sociale et émotionnelle ([R14], [R15]). Bob Moesta décrit quatre forces qui décident d'un changement : la poussée de la situation actuelle, l'attrait de la nouvelle solution, l'anxiété qu'elle suscite et l'habitude du présent ([R16]).

**Entretiens (The Mom Test, Rob Fitzpatrick).** Parler de la vie du client plutôt que de l'idée, demander des faits passés précis plutôt que des intentions, écouter plus que parler ; un rendez-vous réussi se termine par un engagement (du temps, une introduction, de l'argent) ([R17], [R18]).

### 1.2 Application à ControlDOne

**Alternatives réelles (ce que fait la PME aujourd'hui).** Avis, à vérifier en entretien :

| Alternative | Ce qu'elle fait bien | Ce qu'elle ne fait pas |
|---|---|---|
| Rien : on paie la facture du transitaire | Zéro effort, relation tranquille | Aucun rapprochement avec la déclaration |
| Contrôle visuel au moment du paiement (comptable, ADV) | Repère les montants aberrants | Ne compare ni ligne à ligne, ni à la grille tarifaire, ni d'un dossier à l'autre (doublons) |
| Tableur maison | Adapté à l'entreprise | Dépend d'une personne ; rarement tenu dossier par dossier |
| Expert-comptable à la révision | Regard externe, connaît le client | Travaille sur la comptabilité, pas sur la déclaration en douane |
| Audit douane par un RDE ou un avocat | Avis juridique, peut engager des démarches | Coût et périmètre différents ; ne pointe pas forcément les frais refacturés |

Le concurrent principal est donc le statu quo. Dunford insiste sur ce point : la première alternative à battre est souvent un tableur, un processus manuel ou « ne rien faire » ([R13]).

**Capacités différenciantes (vérifiées dans le dépôt).**
- Quatre documents rapprochés dossier par dossier : facture commerciale, déclaration, facture du transitaire, avoirs (`site/index.html`).
- Chaque écart cite deux valeurs, le document, la page et le calcul, avec la tolérance affichée (`docs/SPEC.md` §3.1).
- Calcul déterministe : un modèle de langage peut aider à lire, il ne calcule ni ne rédige (`site/methode.html`).
- Deux totaux séparés, « écart certain » et « à vérifier », jamais additionnés.
- Un écart en faveur du client est aussi signalé (montant négatif, niveau « à vérifier ») (`docs/SPEC.md` §8.6). C'est un argument d'honnêteté rarement mis en avant.
- Aucun avis juridique ; phrase de renvoi exacte vers un RDE ou un avocat.
- Le client reste l'expéditeur de toute demande au transitaire.
- Rémunération partiellement liée au résultat (20 % des avoirs obtenus).

**Valeur, dite simplement.** Savoir, pièces à l'appui, si ce que l'on paie au transitaire correspond à la déclaration et au devis ; obtenir des avoirs sur des écarts documentés ; le faire sans y passer des soirées et sans se fâcher avec un prestataire dont on a besoin.

**Segment cible.** Celui de `prospects_methode.md` : entreprises de 10 à 249 salariés (tranches INSEE 11 à 31), qui importent hors UE par un transitaire, sans service douane apparent. À affiner après les trois diagnostics : nombre de dossiers par an, part des débours dans la facture, type de transitaire.

**Catégorie de marché.** « Contrôle des factures de transitaire » est compris immédiatement par un DAF. « Audit » est déjà employé avec la mention « audit technique » ; garder ce qualificatif pour ne pas évoquer un audit juridique.

**Déclaration de positionnement (brouillon).**

> Pour les PME qui importent hors de l'UE par un transitaire et n'ont pas de service douane, ControlDOne compare chaque facture du transitaire à la déclaration en douane et à la grille tarifaire du même dossier. Chaque écart est chiffré, avec la page qui le prouve. Contrairement à une vérification au moment du paiement, le contrôle porte sur tous les dossiers, document contre document. Contrairement à un audit douane, il ne se prononce jamais sur le droit : les questions réglementaires sont renvoyées à un professionnel.

### 1.3 Le job, côté acheteur

Énoncé proposé (à valider en entretien, dans les mots du client) :

> Quand je règle les factures de notre transitaire, je veux être sûr que les droits, la TVA et les frais refacturés correspondent à ce qui a été réellement déclaré et à ce qui était prévu, pour payer le bon montant sans y passer mon temps et sans abîmer la relation.

Les quatre forces appliquées ([R16]) :

| Force | Pour ControlDOne (hypothèses à vérifier) |
|---|---|
| Poussée | Un écart découvert par hasard ; un contrôle fiscal ou douanier ; un changement de transitaire ; la réception des factures électroniques depuis le 1er septembre 2026 ([R55]) ; un nouveau droit forfaitaire de 3 EUR par article sur les envois de faible valeur depuis le 1er juillet 2026 ([R54]) |
| Attrait | Un rapport lisible avec preuves ; des avoirs ; un modèle de courrier neutre prêt à adapter |
| Anxiété | Confier des documents ; froisser le transitaire ; payer pour rien ; risque juridique ; « encore une IA » |
| Habitude | « Notre transitaire est sérieux » ; « on a toujours fait comme ça » |

Moesta note qu'ajouter des fonctions pour renforcer l'attrait augmente aussi l'anxiété, et que le levier le plus utile est de la réduire : information, garanties, risque limité ([R16]). Pour ControlDOne, cela veut dire que la page d'accueil doit répondre à l'anxiété plus qu'empiler des contrôles.

**Trois personnes, trois angles.** NN/g distingue, en B2B, ceux qui utilisent (détails, quotidien) et ceux qui choisissent (coût, fiabilité, retour sur investissement), et recommande de fournir de quoi convaincre en interne ([R5]).

| Lecteur | Ce qu'il cherche en premier | Pièce à lui donner |
|---|---|---|
| DAF / dirigeant | Coût total, risque, montant en jeu | Calcul de seuil de rentabilité (§2.8), conditions de la commission, sécurité |
| Responsable import / achats | Charge de travail, relation transitaire | Liste des pièces à fournir, exemple de courrier neutre, ton non accusatoire |
| Expert-comptable | Sérieux de la méthode, déontologie | Page Méthode, rapport de démonstration, limites écrites |

### 1.4 Objections d'un DAF et réponses honnêtes

| Objection | Réponse honnête | Preuve à montrer |
|---|---|---|
| « Je ne confie pas mes documents à un inconnu. » | Dire exactement ce qui est fait : isolement par client, chiffrement au repos avec une clé par client, TLS, double facteur pour le fondateur, journal d'audit, purge des fichiers bruts 180 jours après clôture, restitution puis suppression sous 30 jours en fin de contrat. Dire aussi ce qui reste à compléter : nom de l'hébergeur (UE) et lecture par un modèle de langage chez Anthropic aux États-Unis, sous clauses contractuelles types, désactivable. | `site/methode.html`, accord de sous-traitance, registre RGPD. Ne jamais écrire « hébergé en France » ni « souverain » : ce serait une allégation fausse au sens de L121-2 ([R30]). |
| « Mon transitaire est fiable. » | C'est probablement vrai, et le rapport peut le montrer : le diagnostic peut conclure que tout est cohérent, il signale aussi les écarts en faveur du client, et le ton ne met jamais le transitaire en cause (SPEC §3.1, règle 3). Le contrôle sert à documenter, pas à accuser. | Phrase type : « Un dossier sans écart est un résultat. Il figure au rapport comme tel. » |
| « Je n'ai pas le temps. » | Le client dépose des documents tels quels ; le fondateur fait le reste. La durée réelle côté client n'est pas encore mesurée : l'annoncer après les trois diagnostics, pas avant. | Liste des pièces demandées (plan d'actions, étape 1). |
| « Combien ça me coûte vraiment ? » | Diagnostic 390 € HT. Commission de 20 % des avoirs obtenus. Avec ces deux chiffres, le diagnostic est couvert dès 487,50 € HT d'avoirs (390 ÷ 0,8). C'est un calcul, pas une promesse. | Calculateur de seuil (§2.8). |
| « Et si ça ne trouve rien ? » | Aujourd'hui le forfait reste dû (FAQ tarifs). C'est défendable, mais c'est l'anxiété n° 1 d'un acheteur. Option à étudier : remboursement du forfait si aucun écart certain n'est trouvé sur un lot complet. Décision commerciale du fondateur. | FAQ tarifs. |
| « Je ne veux pas de risque juridique. » | ControlDOne ne donne aucun avis sur un droit, une taxe, un classement, une origine ou une valeur ; la phrase de renvoi est toujours la même ; le client décide seul d'écrire au transitaire, avec un modèle neutre sans argumentation juridique. | Phrase de renvoi exacte (SPEC §3.3). |
| « Pourquoi pas mon expert-comptable ? » | Il peut le faire, et il est un partenaire naturel : il ne travaille pas sur la déclaration en douane ligne à ligne. Le rapport lui est utile. | Page Experts-comptables. |
| « C'est de l'IA, donc ça se trompe. » | Les montants viennent d'un programme testé ; chaque valeur lue renvoie à sa page ; chaque constat est relu par le fondateur. Sur fichiers de test synthétiques, les mesures sont publiques (§2.3). | Banc d'essai, page Méthode. |

---

## 2. Page d'accueil et conversion

### 2.1 Ce que disent les études

- 79 % des utilisateurs testés parcourent une page au lieu de la lire ; 16 % lisent mot à mot. Sur le même site, un texte concis est 58 % plus utilisable, un texte facile à parcourir 47 %, un langage objectif 27 %, les trois ensemble 124 % (NN/g, étude de 1997, toujours citée par NN/g) ([R1]).
- En B2B, le prix est la première information cherchée ; des participants partent chez un concurrent quand il manque ; NN/g conseille d'afficher au moins des prix pour des scénarios types ([R4], [R5]).
- La confiance tient à quatre facteurs : qualité de conception, transparence d'emblée (contacts, coûts), contenu complet et à jour, liens avec le reste du web ([R3]).
- Une proposition de valeur se lit en environ cinq secondes : un titre, un sous-titre de deux ou trois phrases, trois points, un visuel ; la clarté avant la persuasion ; pas de superlatifs ni de jargon ([R8]).

### 2.2 Le haut de page (hero)

**Trois formules de titre** (CXL ([R8]) : dire ce que c'est, ce que le client obtient, ce qu'il peut faire). Propositions pour ControlDOne :

1. Ce que c'est : « Chaque ligne de la facture de votre transitaire, comparée à votre déclaration en douane. »
2. Ce que le client obtient : « La liste des écarts entre ce que facture votre transitaire et ce que dit votre déclaration, avec la page qui le prouve. »
3. Ce qu'il peut faire : « Envoyez vos 20 derniers dossiers d'import. Vous saurez lesquels ont été facturés au-delà de la déclaration ou du devis. »

Sous-titre proposé (spécifique, avec mécanisme) : « Pour chaque dossier, je mets côte à côte la facture du fournisseur, la déclaration, la facture du transitaire et ses avoirs. Chaque écart est chiffré au centime, avec les deux montants, la page où ils figurent et le calcul. »

Règles :
- Pas de question en titre principal (voir §3).
- Un seul bouton principal : « Demander un diagnostic ». Un lien secondaire : « Voir un rapport d'exemple ». La carte de constat fictif actuelle est le bon visuel : la garder, en grand, avec son étiquette « DONNÉES FICTIVES ».
- Le prix ou l'offre de lancement doit être visible sans défiler ou juste en dessous, car c'est l'information la plus cherchée en B2B ([R4]).

### 2.3 Preuve sociale sans clients (et sans rien inventer)

Ce qui est interdit, et pourquoi : affirmer que des avis proviennent de clients sans l'avoir vérifié, diffuser de faux avis ou de fausses recommandations (L121-4, 27° et 28°), afficher un label sans autorisation (2°) ([R31]). L'article L121-5 étend ces règles aux pratiques qui visent les professionnels ([R30]). NN/g ajoute que des chiffres faibles affichés comme preuve sociale produisent l'effet inverse ([R6]) : pas de compteur « 3 clients ».

Ce qui reste possible, par ordre d'utilité (avis, appuyé sur [R3], [R6], [R19]) :

1. **Le fondateur, nommé.** Google demande qui a écrit, comment et pourquoi ([R19]). Une page « Qui est derrière » avec nom, parcours vérifiable, photo réelle, raison d'avoir construit l'outil, et engagement de relecture personnelle de chaque constat. C'est la preuve la plus forte disponible aujourd'hui.
2. **La méthode publique.** La page Méthode existe ; la lier depuis chaque bloc d'argument.
3. **Le rapport de démonstration**, déjà marqué « DONNÉES FICTIVES ». NN/g note que démonstrations et captures montrent ce que le texte n'explique pas ([R5]).
4. **Les mesures du banc d'essai, présentées comme telles.** Exemple de bloc honnête, chiffres tirés de `docs/banc/holdout2_final_code_definitif.md` :

   > **Mesuré sur 48 dossiers fictifs générés pour le test, jamais vus pendant le développement** (148 erreurs injectées). Écarts classés « certains » : 46, tous justes (précision 100 % ; borne basse à 95 % : 92,3 %). Erreurs retrouvées : 74,3 %. Constats « à vérifier » non fondés : 1,7 par dossier en moyenne. Ces chiffres ne disent rien de la fréquence des erreurs sur de vrais dossiers.

   Montrer aussi les limites (rappel de 74 %, bruit des « à vérifier ») : NN/g relève que des témoignages équilibrés sont jugés plus crédibles que des éloges uniformes ([R6]). Recalculer ces chiffres à chaque version publiée et dater le bloc.
5. **Le diagnostic offert et ses conditions écrites.** C'est l'inversion du risque la plus nette.
6. **Plus tard, des résultats anonymisés** des trois diagnostics, avec l'accord distinct déjà prévu. Un témoignage n'est publié qu'avec nom, fonction et entreprise (ou anonymisé et dit comme tel), jamais réécrit au point d'en changer le sens.

### 2.4 Bouton d'action

- Un libellé qui décrit l'action et sa suite : « Demander un diagnostic » plutôt que « Commencer » ; sous le bouton, une ligne « Réponse du fondateur sous 48 h ouvrées. Aucun engagement. » (à tenir réellement). CXL recommande de dire ce qui se passe après le clic ([R9]).
- Pas de formulaire aujourd'hui (le site n'en a pas, par choix). Le `mailto:` suffit ; préremplir l'objet et trois questions (nombre de dossiers par an, transitaire unique ou plusieurs, pays d'origine).
- Texte de bouton en verbe d'action, contraste suffisant (4,5:1 pour le texte normal, [R24]).

### 2.5 Page tarifs

NN/g : afficher les prix, au moins par scénarios ; cacher le prix donne une impression d'évasion ([R4]). CXL : rester simple, aider à choisir, traiter les craintes près des prix (FAQ, garantie, sécurité), dire ce qui se passe ensuite ([R9]).

**Ancrage, utilisé honnêtement.** CXL décrit l'effet d'ancrage (montrer d'abord le prix le plus élevé) et le leurre (une offre un peu moins bonne à côté de la cible) ([R9]), tout en notant que les preuves sont minces pour le SaaS. Pour ControlDOne :
- Ancre légitime : le seuil de rentabilité calculé (487,50 € HT d'avoirs pour couvrir le diagnostic), ou le montant de la carte de constat fictive, présenté comme fictif. Jamais une « valeur estimée » inventée.
- Pas de leurre : ne pas créer d'offre fictive pour pousser une autre. Les trois cartes actuelles ne sont pas des paliers ; les présenter comme deux points d'entrée (diagnostic une fois, contrôle continu mensuel) et une commission commune aux deux, affichée sur une ligne à part.
- « Dès 99 € HT par mois » doit être suivi de la grille par volume, même approximative ([R4]).

**Gratuité.** L121-4, 19° vise le fait de dire « gratuit » quand il faut payer autre chose que des coûts inévitables ([R31]). L'offre de lancement dit « offert » et précise que la commission reste due : garder cette précision collée au mot, jamais en note, et ne pas écrire « gratuit » seul.

**Rareté.** « Trois diagnostics offerts » est vrai ; le retirer ou le mettre à jour dès que les trois places sont prises. Une rareté fausse est une pratique réputée trompeuse (L121-4, 7°, [R31]). Cialdini lui-même recommande de ne parler que de ce qui est réellement rare ([R12]).

**Inversion du risque.** Moesta : la garantie réduit l'anxiété ([R16]). Voir l'option « remboursement si aucun écart certain » (§1.4).

### 2.6 FAQ

Une FAQ qui répond aux objections du §1.4, dans les mots des acheteurs (à récolter pendant les entretiens, méthode de [R17] et [R52]). Questions à ajouter à celles de `tarifs.html` :
- « Où sont mes documents et qui les lit ? »
- « Le transitaire saura-t-il que j'utilise ControlDOne ? » (Non, sauf si vous le lui dites.)
- « Que se passe-t-il si un écart est en ma faveur ? »
- « Que faites-vous de mes données à la fin ? »
- « Est-ce un conseil juridique ? »

Le balisage HTML natif `<details>/<summary>` reste lisible sans script. NN/g recommande de rendre FAQ et pages d'aide accessibles sans connexion ([R5]).

### 2.7 Signaux de confiance

- Identité complète de l'éditeur, SIREN, adresse, téléphone : c'est le facteur « transparence d'emblée » de NN/g ([R3]). Tant que les `[À COMPLÉTER]` ne sont pas remplis, ne pas publier.
- Bloc « Sécurité » court sur l'accueil, renvoyant à la Méthode, avec uniquement des faits vérifiables (voir §1.4).
- Baymard observe que les utilisateurs jugent la sécurité à l'apparence plus qu'à la technique, et que 19 % des répondants de son étude 2025 ont abandonné un achat faute de confiance ([R25]). Leçon pour ControlDOne : la zone de dépôt de documents dans l'application doit être visuellement distincte et porter une phrase de sécurité précise, sans badge inventé (un faux label est interdit, [R31]).
- RGPD : lien visible vers la politique de confidentialité et l'accord de sous-traitance ; mention du registre ; pas de cookie ni de traceur (déjà le cas, à dire).

### 2.8 Calculateur de rentabilité

Le problème : il n'existe pas de taux d'erreur mesuré sur les factures de transitaires (le site le dit déjà). Un calculateur classique « vous économiserez X € » serait donc inventé. Proposition : un **calculateur de seuil**, qui ne suppose aucun taux d'erreur.

- Entrées : nombre de dossiers d'import par an ; formule choisie (diagnostic seul ou contrôle continu, prix saisi selon la grille).
- Sorties : montant d'avoirs nécessaire pour couvrir le coût (diagnostic : 390 ÷ 0,8 = 487,50 € HT ; contrôle continu à 99 € HT par mois : 1 188 ÷ 0,8 = 1 485 € HT par an) et ce que cela représente par dossier (seuil ÷ dossiers).
- Formule affichée en clair sous le résultat.

Recommandations NN/g appliquées ([R7]) : intégré dans la page, sans inscription, résultat immédiat qui se met à jour, chaque champ expliqué, valeurs par défaut qui n'induisent pas en erreur, algorithme exposé, pas d'IA. NN/g note aussi que les configurateurs complexes sont peu utilisés en B2B ([R4]) : deux champs, pas plus.

Sans script (contrainte actuelle du site), une version statique est possible : un tableau de seuils pour 20, 50, 100 et 200 dossiers par an.

### 2.9 Vitesse, lisibilité, accessibilité

- Signaux web essentiels, seuils « bons » au 75e centile : LCP ≤ 2,5 s, INP ≤ 200 ms, CLS ≤ 0,1 ([R20]). Le site actuel, statique et sans script, part avec un avantage ; l'ajout de polices et d'animations ne doit pas le perdre (précharger une seule police de titre, `font-display: swap`, dimensions explicites des images, déjà présentes sur la capture).
- Contraste 4,5:1 pour le texte courant, 3:1 pour le grand texte ([R24]).
- Tout mouvement qui démarre seul, dure plus de cinq secondes et coexiste avec du contenu doit pouvoir être mis en pause (critère 2.2.2, niveau A) ([R23]) ; les animations déclenchées par une interaction doivent pouvoir être désactivées (2.3.3, AAA) ([R22]) ; respecter `prefers-reduced-motion` ([R21]).
- Lisibilité : phrases courtes, langage simple ; Joanna Wiebe vise un niveau de lecture très accessible ([R10]).

---

## 3. Écrire comme une personne, pas comme un modèle

### 3.1 Pourquoi c'est un sujet commercial

NN/g a mesuré que le langage promotionnel (« marketese ») rend un texte moins utilisable, et qu'un langage objectif l'améliore de 27 % ([R1]). Les pages d'aide de Wikipédia qui recensent les marques d'écriture par IA décrivent des tics proches : vocabulaire gonflé, rythme en trois, parallélismes négatifs, tirets cadratins, gras et listes partout, ton promotionnel ou « langue de bois » ([R26], [R27]). Un DAF lit ces tics comme du remplissage. Pour un produit dont l'argument est la preuve, c'est contre-productif.

### 3.2 Liste noire

La liste anglaise s'appuie sur [R26] et [R8] ; la liste française s'appuie sur [R27] et, pour les expressions précises, sur l'observation éditoriale (avis, non sourcé).

**Ponctuation et mise en forme**
- Tiret cadratin ou demi-cadratin en incise (« — ») : remplacer par une virgule, des parenthèses ou deux phrases.
- Gras dans le corps du texte pour « souligner » ; titres de section en forme de question ; majuscules à l'anglaise dans les titres ; émojis.
- Listes à puces là où une phrase suffit.

**Structures**
- Le rythme en trois : « Simple. Rapide. Fiable. » ; « vérifier, chiffrer, récupérer ».
- Paragraphes et cartes symétriques (trois cartes de même longueur, même construction).
- Parallélismes négatifs : « Ce n'est pas X, c'est Y » ; « Pas seulement X, mais aussi Y » ; en anglais « not just X, but Y ».
- Questions rhétoriques en cascade (« Vous perdez du temps ? Vous doutez de vos factures ? »).
- « Que vous soyez… ou… » ; « Whether you're X or Y ».
- Ouvertures de contexte creuses : « Dans un monde où… », « À l'heure où… », « In today's fast-paced world ».
- Conclusions de section : « En somme », « En définitive », « In summary ».
- Formules nominales sans verbe empilées : « Calcul fait par du code testé, preuve page par page ».

**Mots et expressions (français)**
- Découvrez, Plongez, Explorez, Libérez.
- révolutionner, transformer, réinventer, repenser.
- en toute sérénité, en toute simplicité, en un clic, sans effort, clé en main, tout-en-un.
- solution innovante, de pointe, nouvelle génération, intelligente, puissante.
- crucial, essentiel, incontournable, véritable (levier), au cœur de, au service de.
- Il est important de noter que, Il convient de souligner.
- permettre de (« ControlDOne permet de… » : dire ce que l'outil fait).
- optimiser, booster, maximiser sans chiffre derrière.
- accompagner (« nous vous accompagnons »).
- garantir (aussi interdit par la SPEC §3.2 : « nous garantissons »).
- N'attendez plus, Ne laissez plus…

**Mots et expressions (anglais, pour `site/en/`)**
- delve, tapestry, testament, pivotal, crucial, underscore ([R26]).
- seamless, unlock, empower, elevate, leverage, harness, streamline, supercharge, robust, cutting-edge, next-gen, best-in-class, all-in-one, game-changer, revolutionize, effortless, peace of mind, navigate the complexities of.
- « It's important to note », « serves as » à la place de « is » ([R26]).

Ajouter ces expressions à un fichier de configuration testé, comme `config/formulations_interdites.yaml` l'est pour les formulations juridiques : une liste séparée « style » (avertissement) et la liste juridique existante (blocage).

### 3.3 Règles positives

1. **Des chiffres précis, avec leur source.** « 2 356,28 EUR », « tolérance 0,05 EUR », « 180 jours ». Copyhackers recommande une passe de relecture dédiée aux formulations vagues ([R10]).
2. **Le vocabulaire du client.** « Écrivez à partir des mots de vos clients » est la méthode de Joanna Wiebe ([R52]). Pour ControlDOne : noter mot pour mot, pendant les rendez-vous, comment les acheteurs nomment les choses (« débours », « frais de dédouanement », « avance de fonds », « la facture du transitaire », « la déclaration »), et réutiliser ces mots tels quels.
3. **Phrases courtes, un sujet, un verbe.** Une idée par phrase ([R10]).
4. **La première personne du fondateur.** Une entreprise d'une personne qui écrit « nous » sonne comme un gabarit. « Je relis chaque constat avant de vous l'envoyer » est vrai et rassurant. Garder « ControlDOne » pour l'outil.
5. **Montrer le mécanisme.** Dire comment le résultat est obtenu : quels documents, quelle comparaison, quelle tolérance. Google valorise le « comment » ([R19]).
6. **Des verbes simples.** comparer, lire, chiffrer, envoyer, relire. Basecamp rappelle que le texte fait partie de l'interface et mérite le même soin que le visuel ([R11]).
7. **Dire les limites dans la même voix.** « Je ne dis pas si le droit est juste. Je dis si deux documents disent la même chose. »
8. **Lire à voix haute.** Si une phrase ne se dit pas à un DAF au téléphone, la réécrire (avis).

### 3.4 Avant / après sur trois phrases de `site/index.html`

**1. Titre principal**

- Avant : « Vos factures de transitaire disent-elles la même chose que vos déclarations en douane ? »
- Ce qui accroche : question rhétorique ; « disent la même chose » est abstrait ; aucun mécanisme.
- Après : « Chaque ligne de la facture de votre transitaire, comparée à votre déclaration en douane. »

**2. Titre de la section « Le problème »**

- Avant : « Quatre documents, trois émetteurs, personne pour les rapprocher »
- Ce qui accroche : rythme en trois, formule de slogan sans verbe.
- Après : « Pour un même envoi, vous recevez la facture du fournisseur, la déclaration du déclarant et la facture du transitaire. Dans une PME sans service douane, personne n'a le temps de les mettre côte à côte. »

**3. Point de réassurance sous le titre**

- Avant : « Calcul fait par du code testé, preuve page par page »
- Ce qui accroche : deux groupes nominaux juxtaposés ; « code testé » parle au développeur, pas au DAF.
- Après : « Les montants sont calculés par un programme : les mêmes documents donnent toujours le même résultat. Chaque écart renvoie à la page du document où il figure. »

---

## 4. Étude visuelle et du mouvement

### 4.1 Méthode

Pages d'accueil ouvertes le 2026-10-07 dans Chromium sans interface (fenêtre 1440 × 900), styles calculés relevés sur le titre principal et les paragraphes, feuilles de style téléchargées pour les familles déclarées, les courbes d'accélération et les durées de transition, captures à cinq hauteurs de défilement. Les valeurs sont celles de ce jour et d'un écran de bureau ; elles changent souvent. Aucun texte, image, logo ni code de ces sites n'est repris ici : seulement des mesures et des descriptions de principes.

Limites honnêtes :
- **tesla.com** : réponse « Access Denied » du réseau de diffusion, à la fois en requête simple et en navigateur sans interface ; l'archive web n'était pas joignable depuis l'environnement. **Non étudié.**
- **openai.com** : une première ouverture a affiché un grand visuel plein écran (étude de cas client) et une page très longue (environ 60 000 px) ; les ouvertures suivantes ont été bloquées par une vérification anti-robot. Typographie **non mesurée** ; seules ces observations générales sont retenues.

### 4.2 Mesures

| Site | Fond | Titre principal (famille, taille, graisse, interlettrage) | Texte courant | Rapport titre / texte | Boutons |
|---|---|---|---|---|---|
| anthropic.com | ivoire `#FAF9F5` | sans-serif maison, 61 px, 700, 0 ; un second titre en serif maison 80 px, 400, −0,015 em | 18 px ; chapeau 24 px | ≈ 3,4 | noir plein, coins peu arrondis (relevé sur capture, non mesuré) |
| stripe.com | blanc, dégradé animé dans une `canvas` | Söhne, 48 px, **300**, −0,02 em, titre en deux tons (première phrase foncée, suite grisée) | 16 à 18 px | ≈ 2,7 | violet plein, rayon 4 px |
| linear.app | quasi noir `#08090A` | Inter Variable, 64 px, 510, −0,022 em, deux tons | 15 px | ≈ 4,3 | pilule claire (rayon 9999 px) |
| vercel.com | `#FAFAFA` | Geist, 64 px, **400**, −0,06 em | 24 px en chapeau | ≈ 2,7 | noir ou contour, rayon 6 px et pilule |
| neuralink.com | vidéo plein écran, puis papier beige texturé | Untitled Sans, 48 px, 500, −0,06 em | 16 à 18 px | ≈ 3 | pilules (rayon 80 px), blanc sur image |
| spacex.com | noir `#000`, vidéo | D-DIN gras, capitales, 60 px, −0,017 em ; petites capitales espacées (+0,02 em) dans le menu | 16 px | ≈ 3,75 | contour fin, rayon 4 px, libellé en capitales |
| starlink.com | photo nocturne plein cadre, puis noir | DIN, 64 px, 700 | 14 à 16 px | ≈ 4 à 4,6 | blanc plein et gris translucide, rayon 4 px ; prix mensuel en très gros dans le haut de page |
| meta.com | vidéo plein cadre, puis blanc | Optimistic (maison), affichage très grand intégré au visuel, titre HTML 36 px, 500 | 12 à 16 px | n. s. | pilules colorées |

Familles déclarées dans les feuilles de style : Anthropic Sans / Serif / Mono et JetBrains Mono (Anthropic), Söhne et Source Code Pro (Stripe), Inter Variable et Berkeley Mono (Linear), Geist, Geist Mono et des variantes « pixel » (Vercel), UntitledSans (Neuralink), D-DIN, D-DIN-PRO et Roboto Mono (SpaceX), DIN (Starlink), Optimistic Display / Text / VF (Meta).

Courbes et durées relevées dans les feuilles de style :

| Site | Courbes les plus fréquentes | Durées les plus fréquentes | `prefers-reduced-motion` présent |
|---|---|---|---|
| anthropic.com | `cubic-bezier(0.16, 1, 0.3, 1)`, `(.165,.84,.44,1)` | 0,2 s (très majoritaire), 0,3 à 0,4 s | oui (7 occurrences) |
| stripe.com | `(.25,1,.5,1)`, `(.4,0,.2,1)`, `(.16,1,.3,1)` | 0,3 s, 0,15 à 0,5 s | oui (7) |
| linear.app | jeu complet de jetons `--ease-*` (quad à expo) | 120 à 220 ms | oui (2) |
| vercel.com | `(.4,0,.2,1)`, `(.32,.72,0,1)` | 0,1 à 0,25 s | oui (6) |
| meta.com | `(.4,0,.2,1)`, `(.165,.84,.44,1)` | 0,1 à 0,5 s | oui (6) |
| neuralink.com | non relevé | 0,2 à 0,5 s | **non** |
| spacex.com | `(.25,.8,.25,1)` | 0,4 s | **non** |

### 4.3 Ce qui produit l'impression « haut de gamme »

Observations (avis fondé sur les mesures ci-dessus) :

1. **Peu de mots au-dessus de la ligne de flottaison.** Vercel affiche environ 130 mots sur toute la page d'accueil, SpaceX et Neuralink environ 250 ; Stripe et Linear vont au-delà de 1 300, mais en blocs très espacés.
2. **Un grand écart de taille entre titre et texte** (rapport de 2,7 à 4,6), avec un texte courant petit (15 à 18 px) et un titre à graisse moyenne ou légère (300 à 510 chez Stripe, Vercel, Linear). Le contraste vient de la taille, pas de la graisse.
3. **Interlettrage négatif sur les titres** (−0,02 à −0,06 em), nul ou positif sur les petites capitales.
4. **Titres en deux tons** (Stripe, Linear) : la première phrase dit ce que c'est, la suite grisée précise. Bonne idée à reprendre pour ControlDOne, car elle permet un titre long et précis qui reste lisible.
5. **Une couleur de marque, le reste en neutres.** Anthropic : ivoire et une terre cuite ; Vercel et Linear : quasi monochromes ; Stripe : un violet et un dégradé.
6. **Images vraies ou abstraites, jamais de banque d'images.** Vidéo de produit en usage (Neuralink, SpaceX, Meta), interface du produit dans un cadre (Vercel, Stripe, Linear), illustrations au trait étiquetées comme des figures techniques (« FIG 0.1 » en monospace chez Linear).
7. **Une grille visible.** Stripe et Linear laissent voir des filets verticaux de colonnes ; les étiquettes en monospace renforcent l'effet « instrument ».
8. **Mouvement court et discret.** Transitions de 0,1 à 0,3 s ; courbes à décélération forte (type « expo-out ») ; animations d'entrée au chargement (Linear : le haut de page est vide sur une capture à 5 s, puis apparaît) ; menu qui se condense en barre flottante au défilement (Starlink) ; cartes décalées verticalement (Neuralink) ; compteur qui défile en direct (Stripe, un indicateur chiffré au-dessus du titre).
9. **Les chiffres comme héros.** Starlink met le prix mensuel en très grand dans le haut de page ; Stripe met un compteur chiffré au-dessus du titre. Pour ControlDOne, l'équivalent honnête est le montant de l'écart dans la carte de constat fictive.

Points à ne pas reprendre : vidéo plein écran (poids, LCP ; rien à filmer pour ControlDOne), dégradés en `canvas` (coût, distraction), absence de `prefers-reduced-motion` (Neuralink, SpaceX), titres en capitales grasses condensées (lecture difficile en français accentué, avis).

### 4.4 Ce qu'il faut pour ControlDOne

Le registre visé est celui d'un instrument de mesure : sobre, précis, chiffré. Le haut de gamme viendra de la typographie, de l'espace et de la justesse des chiffres, pas d'effets.

- Fond clair chaud (proche de l'ivoire actuel `--bg: #f7f6f2`) et thème sombre presque noir ; une seule couleur d'accent (le vert `--accent` actuel ou le bleu `--brand`), le rouge réservé aux écarts certains et l'ambre aux « à vérifier », comme aujourd'hui.
- Titre principal 56 à 64 px sur ordinateur (`clamp()` jusqu'à 34 à 38 px sur téléphone), graisse 500 à 600, interlettrage −0,02 em ; texte courant 17 à 18 px, interligne 1,55 à 1,6 ; largeur de lecture 60 à 70 caractères (la variable `--text: 42rem` actuelle convient).
- Montants et références en chasse fixe avec chiffres tabulaires, alignés à droite dans les tableaux.
- Étiquettes de section en petites capitales espacées (+0,06 em) ou en monospace, à la manière de figures techniques : « CONSTAT 01 », « DOSSIER FIC-0501 ».
- Espacement vertical généreux entre sections (96 à 160 px sur ordinateur).

### 4.5 Deux associations de polices sous licence libre

Les polices propriétaires des sites étudiés ne peuvent pas être reprises. Les deux options ci-dessous sont sous **SIL Open Font License 1.1**, auto-hébergeables. L'application sert déjà **Geist** et **Geist Mono** (OFL 1.1, [R50]), selon `docs/DECISIONS.md`.

**Point de licence important.** La FAQ de l'OFL considère qu'un sous-ensemble (subset) est une modification, qui ne permet normalement pas de garder un « nom de police réservé » ([R51], question 2.6). IBM Plex (nom réservé « Plex ») et Source Serif (nom réservé « Source ») sont concernés : servir les fichiers officiels non modifiés, ou renommer la famille si on les découpe. Inter et JetBrains Mono ne déclarent pas de nom réservé dans leur licence ([R46], [R49]).

**Option A : « Éditorial et preuve »**

| Usage | Famille exacte | Licence |
|---|---|---|
| Titres | **Source Serif 4** (variable, axe de taille optique `opsz` 8 à 60, graisses 200 à 900, vérifié sur l'API Google Fonts et le dépôt Adobe [R48]) | OFL 1.1, Adobe, nom réservé « Source » : https://github.com/adobe-fonts/source-serif/blob/release/LICENSE.md |
| Texte, interface | **Inter** (InterVariable ; chiffres tabulaires `tnum`, zéro barré `zero`, taille optique [R47]) | OFL 1.1, The Inter Project Authors : https://github.com/rsms/inter/blob/master/LICENSE.txt |
| Montants, MRN, numéros de facture | **JetBrains Mono** | OFL 1.1, The JetBrains Mono Project Authors : https://github.com/JetBrains/JetBrainsMono/blob/master/OFL.txt |

Effet : un serif à taille optique en grand donne le ton « document de référence » ; Inter reste neutre et très lisible en petit ; le monospace marque tout ce qui est une preuve. Variante si l'on veut une seule famille sans serif entre site et application : remplacer Inter par Geist et JetBrains Mono par Geist Mono (déjà présents dans l'application).

**Option B : « Instrument »**

| Usage | Famille exacte | Licence |
|---|---|---|
| Titres et texte | **IBM Plex Sans** (graisses Thin à Bold, [R53]) | OFL 1.1, IBM Corp., nom réservé « Plex » : https://github.com/IBM/plex/blob/master/LICENSE.txt |
| Montants, références | **IBM Plex Mono** | même licence |
| Pages longues (Méthode, CGV), facultatif | **IBM Plex Serif** | même licence |

Effet : une seule famille dessinée comme un système, des chiffres nets, un registre « ingénierie » et finance. Moins de caractère éditorial que l'option A, cohérence maximale.

Mise en œuvre commune : fichiers `woff2` servis depuis `site/assets/fonts/`, `@font-face` avec `font-display: swap`, préchargement de la seule police de titre, ajout de `font-src 'self'` à la CSP conseillée dans `site/README.md` (elle est aujourd'hui en `default-src 'none'`), copie des licences à côté des fichiers, mise à jour du test « aucune ressource externe » (les polices restent locales).

### 4.6 Vocabulaire du mouvement

Fondements : NN/g recommande 100 à 500 ms, environ 100 ms pour un retour simple, 200 à 300 ms pour un changement d'écran, une sortie un peu plus courte que l'entrée, une décélération (ease-out) pour les entrées, jamais de mouvement linéaire, et des animations plus courtes quand elles sont fréquentes ([R2]). web.dev recommande de n'animer que `transform` et `opacity` ([R40]).

| Jeton | Valeur | Usage |
|---|---|---|
| `--duree-micro` | 120 ms | survol, focus, bascule |
| `--duree-courte` | 200 ms | ouverture d'un menu, d'une info-bulle ; sortie d'un panneau |
| `--duree-moyenne` | 280 ms | entrée d'un panneau, d'un bloc |
| `--duree-section` | 400 ms | révélation d'une section au défilement (une fois) |
| `--courbe-entree` | `cubic-bezier(0.16, 1, 0.3, 1)` | entrées (décélération forte, relevée chez Anthropic et Stripe) |
| `--courbe-standard` | `cubic-bezier(0.4, 0, 0.2, 1)` | changements d'état (relevée chez Vercel et Meta) |
| `--courbe-sortie` | `cubic-bezier(0.4, 0, 1, 1)` | sorties (accélération) |
| ressort | `{ type: "spring", visualDuration: 0.3, bounce: 0 }` | manipulation directe (curseur du calculateur) ; pas de rebond, registre financier |
| `--deplacement` | 8 à 16 px | translation verticale maximale à l'entrée |
| `--decalage` | 40 à 60 ms | décalage entre éléments d'une liste |

Règles :
- Animer ce qui explique (l'apparition d'une preuve, la mise en relation de deux valeurs), pas ce qui décore.
- Une animation d'entrée ne se rejoue pas à chaque passage.
- Aucune boucle infinie ; rien qui dure plus de cinq secondes sans bouton pause ([R23]).
- Pas de parallaxe : web.dev la cite comme déclencheur de vertiges ([R21]).
- `prefers-reduced-motion: reduce` : suppression des translations et des tracés ; au plus un fondu d'opacité de 120 ms ; les compteurs affichent directement la valeur finale ([R21], [R22]). L'application lit déjà ce réglage dans `app.js` (variable `reduit`).

### 4.7 Dix motifs à implémenter

API de Motion d'après la documentation de motion.dev ([R57] à [R61]) : `animate(cible, valeurs, options)` (durée par défaut 0,3 s, transformations indépendantes `x`, `y`, `scale`, tracés SVG via `pathLength`, rappel `onUpdate` pour une valeur numérique) ; `scroll(animation ou rappel, { target, offset })`, accéléré par `ScrollTimeline` quand le navigateur le permet ; `inView(cible, rappel, { margin, amount })`, construit sur IntersectionObserver ; `stagger(durée, { startDelay, from })` ; options de ressort `stiffness`, `damping`, `mass`, `visualDuration`, `bounce`. L'application embarque **Motion 14.0.0** (`docs/DECISIONS.md`) et utilise déjà `animate`, `inView`, `scroll` et `stagger` (`app.js`) ; vérifier chaque option ci-dessous contre la version 14 avant de l'utiliser, la documentation consultée étant celle de la version courante.

| # | Motif | Où | API Motion | Sans Motion / mouvement réduit |
|---|---|---|---|---|
| 1 | **La preuve qui se construit** : dans la carte de constat du haut de page, les deux valeurs apparaissent l'une après l'autre, puis la ligne « écart constaté » se trace entre elles | Site, accueil | `animate` + `stagger(0.06)` ; tracé SVG `pathLength` 0 → 1 | Carte statique (état final) |
| 2 | **Compteur de montant** : le montant de l'écart passe de 0 à sa valeur, une seule fois, en chiffres tabulaires | Site (carte fictive), application (totaux du rapport) | `inView` puis `animate(0, valeur, { duration: 0.5, onUpdate })` | Valeur finale affichée |
| 3 | **Révélation de section** : opacité 0 → 1 et `y` 12 → 0 px, 400 ms, une fois | Site, toutes pages | `inView(..., { amount: 0.3 })` + `animate` | CSS seul possible ; rien en mouvement réduit |
| 4 | **Liste en cascade** : familles de contrôles A à G, quatre étapes | Site, Méthode et accueil | `animate` + `stagger(0.05)` | Liste statique |
| 5 | **Surlignage de la preuve** : au survol ou au focus d'un constat, la zone correspondante s'encadre sur la vignette du document | Application, vue dossier ; démonstration | `animate` sur l'opacité et le contour d'un `rect` SVG, 120 ms | Encadré visible sans transition |
| 6 | **Fil des quatre étapes** : une ligne verticale se trace au fil du défilement de la section « Fonctionnement » | Site, accueil | `scroll(animate(ligne, { pathLength: [0, 1] }), { target: section, offset: ["start end", "end center"] })` | Ligne pleine |
| 7 | **En-tête qui se condense** : au-delà de 80 px de défilement, l'en-tête réduit sa hauteur et passe en fond opaque | Site | `scroll(progression => ...)` qui bascule une classe ; transition CSS 200 ms | Bascule sans transition |
| 8 | **Barre de lecture** : fine barre en haut des pages longues (Méthode, CGV) | Site | `scroll(animate(barre, { scaleX: [0, 1] }))` | Masquée |
| 9 | **Calculateur de seuil** : le résultat se met à jour à chaque saisie, le nombre glisse vers sa nouvelle valeur | Site, Tarifs | `animate(ancien, nouveau, { type: "spring", visualDuration: 0.3, bounce: 0, onUpdate })` | Valeur remplacée directement |
| 10 | **Retour de bouton** : pression `scale` 0,98, relâchement en ressort court ; focus clavier visible | Site et application | `animate(bouton, { scale: 0.98 }, { duration: 0.12 })` puis ressort | Aucun changement d'échelle ; focus conservé |

Accordéon de la FAQ : garder `<details>` natif ; Motion n'anime au plus que l'opacité du contenu révélé.

**Site public et absence de script.** Aujourd'hui, le site ne charge aucun script et un test l'impose. Les motifs 3, 4, 7 et 10 se font en CSS seul (transitions, `@media (prefers-reduced-motion)`). Les motifs 1, 2, 6, 8 et 9 demandent du JavaScript : soit le fondateur accepte un unique script local (`site/assets/motion.min.js` + `site/assets/site.js`, CSP `script-src 'self'`, test adapté), soit ces motifs restent réservés à l'application.

---

## 5. Cadre juridique des allégations et de la prospection

*Résumé de textes consultés. À faire valider par un avocat. Le dépôt contient déjà `docs/recherche/juridique_france_suisse.md` et `docs/recherche/legal_market.md`, à lire avec cette partie.*

### 5.1 Pratiques commerciales trompeuses (France)

- Les pratiques déloyales sont interdites ; les pratiques trompeuses (L121-2 à L121-4) en sont une catégorie (L121-1) ([R28]).
- Une pratique est trompeuse si elle repose sur des allégations fausses ou de nature à induire en erreur, notamment sur les caractéristiques essentielles du service et **les résultats attendus de son utilisation**, le prix, les engagements, l'identité et les qualités du professionnel (L121-2) ([R29]).
- Une omission d'information substantielle, ou une information donnée de façon ambiguë ou à contretemps, est aussi trompeuse (L121-3) ([R30]).
- **L121-5 : ces articles s'appliquent aussi aux pratiques qui visent les professionnels.** Le B2B n'est donc pas une zone libre ([R30]).
- L121-4 liste des pratiques réputées trompeuses en toutes circonstances, dont : afficher un label ou un certificat sans autorisation (2°), déclarer faussement qu'une offre n'est disponible que très peu de temps (7°), qualifier de « gratuit » ce qui oblige à payer autre chose que des coûts inévitables (19°), présenter des avis comme venant de clients sans vérification (27°), diffuser de faux avis ou de fausses recommandations (28°) ([R31]).

Règles pratiques pour ControlDOne :
1. Aucun montant d'économie promis ; aucun taux d'erreur sans source (le site le fait déjà).
2. Les chiffres du banc d'essai toujours accompagnés de « mesuré sur fichiers de test synthétiques ».
3. Aucun témoignage, logo ou cas client avant qu'il existe et que sa publication soit autorisée par écrit.
4. Pas de label, badge ou certification que l'on ne détient pas ; pas de « conforme RGPD certifié ».
5. « Offert » toujours suivi, au même endroit, de « la commission de 20 % sur les avoirs obtenus reste due ».
6. Offre limitée : mettre la page à jour dès que les trois places sont prises.
7. Ne pas écrire « hébergé en France » tant que ce n'est pas vrai ; écrire ce qui est vrai (UE, prestataire nommé, lecture par modèle de langage aux États-Unis désactivable).

### 5.2 Publicité comparative

Licite seulement si elle n'est pas trompeuse, porte sur des services répondant aux mêmes besoins et compare objectivement des caractéristiques essentielles, pertinentes, vérifiables et représentatives (L122-1) ; l'annonceur doit pouvoir prouver rapidement l'exactitude de ses énonciations (L122-5) ([R32]). Pour ControlDOne : ne nommer ni un transitaire ni un concurrent ; comparer à des pratiques (« vérification au moment du paiement ») plutôt qu'à des entreprises ; garder les preuves de chaque comparaison.

### 5.3 Prospection B2B par e-mail (France)

- L34-5 CPCE : la prospection par courrier électronique utilisant les coordonnées d'une **personne physique** exige son consentement préalable, sauf exception client ; tout message doit indiquer des coordonnées valables pour demander l'arrêt, sans frais ; il est interdit de dissimuler l'identité de l'émetteur ou d'utiliser un objet sans rapport avec le service. La décision n° 2026-1210 QPC du 25 juin 2026 a déclaré contraires à la Constitution certains alinéas relatifs au cumul de poursuites, avec abrogation reportée au 31 octobre 2027 ([R33]).
- CNIL : entre professionnels, la prospection est possible sans consentement si l'objet est **en rapport avec la profession** de la personne démarchée, celle-ci ayant été informée et pouvant s'opposer ; chaque message doit identifier l'émetteur et permettre de s'opposer par un moyen simple et gratuit ; les adresses génériques de personnes morales (contact@, info@) ne relèvent pas de ces principes ([R34]).
- Information : quand les données ne viennent pas de la personne, l'informer au plus tard au premier contact et dans un délai d'un mois au maximum, en indiquant la source des données ([R36]).
- Conservation : données d'un prospect conservées trois ans à compter de la collecte ou du **dernier contact venant du prospect** (un clic sur un lien en est un exemple) ; à l'échéance, sans réponse positive explicite, suppression ou archivage ; liste d'opposition conservée au moins trois ans, pour ce seul usage ([R35]).
- Pixels de suivi : la recommandation CNIL publiée le 14 avril 2026 encadre les pixels dans les courriels et ne reconnaît une exemption de consentement que dans des cas limités (notamment la mesure individuelle de délivrabilité pour un service demandé) ([R37]). Le plus simple pour de la prospection : **aucun pixel, aucun lien traceur**.

### 5.4 Suisse

- **LCD art. 3 al. 1 let. o** : l'envoi de publicité de masse par voie électronique exige le consentement préalable (opt-in), sauf clients existants pour des produits analogues ; l'expéditeur doit être identifié, avec une personne de contact, et chaque message doit permettre de refuser facilement et sans frais ([R38]). L'OFCOM ne fixe pas de seuil chiffré de « masse » ([R38]) : rester sur des e-mails rédigés un par un, comme le prévoit déjà `sequence_emails.md`, et faire valider ce point par un avocat suisse.
- **PFPDT** : la publicité par e-mail relève d'abord de la LCD ; la personne peut demander l'origine de ses données (art. 25 LPD) ; les e-mails illicites peuvent être signalés au SECO ([R39]).
- **nLPD, art. 19** : devoir d'informer **avant** la collecte, y compris quand les données ne viennent pas de la personne : identité et coordonnées du responsable, finalité, destinataires, et pays étrangers avec garanties en cas de communication hors de Suisse ([R62]).

### 5.5 Règles pour un module de prospection

Chaque règle ci-dessous est une contrainte d'implémentation.

1. Champ obligatoire **source de l'adresse** (URL de la page de l'entreprise où elle est publiée) ; refus d'enregistrer une adresse sans source.
2. Champ **type d'adresse** : générique ou nominative. Aucune adresse nominative devinée (prenom.nom@) : refus si l'adresse n'apparaît pas telle quelle dans la source.
3. Champ **pays** (FR, CH, BE…) qui active les règles du pays : CH = un message individuel à la fois, aucun envoi groupé ; BE = adresses impersonnelles seulement (règle déjà retenue dans `sequence_emails.md`).
4. Champ **lien avec la profession** (fonction visée) obligatoire pour une adresse nominative en France.
5. **Pied de message** imposé par gabarit : identité, SIREN, adresse, source de l'adresse, moyen d'opposition (« répondez STOP »), avertissement général.
6. **Liste d'opposition** consultée avant chaque envoi, alimentée le jour même, conservée trois ans au moins, sans autre usage.
7. **Durée de conservation** : purge automatique trois ans après la collecte ou le dernier contact initié par le prospect ; l'ouverture d'un e-mail n'est pas un contact.
8. **Arrêt automatique** de la séquence à la première réponse, quelle qu'elle soit.
9. **Aucun pixel, aucune redirection de lien** ; un seul lien en clair au plus.
10. **Validation humaine** de chaque message avant envoi ; plafond quotidien bas ; journal de chaque envoi.
11. Filtre de texte : formulations juridiques interdites (`check_text`) et liste de style (§3.2).
12. Export du registre pour le droit d'accès (y compris l'origine des données, exigence suisse [R39]).

---

## 6. Prospection sortante B2B

### 6.1 Profil client idéal

Point de départ (`prospects_methode.md`), à réviser après les trois diagnostics :

- Entreprise française ou suisse active, 10 à 249 salariés (tranches INSEE 11 à 31).
- Activité de commerce de gros (division 46 de la NAF, « commerce de gros, à l'exception des automobiles et des motocycles » [R44]) ou marque qui fait fabriquer hors UE.
- Importations hors UE prouvées par une citation de son propre site.
- Pas de service douane apparent ; passe par un ou plusieurs transitaires.
- À ajouter après les diagnostics : nombre minimal de dossiers par an pour que le seuil de rentabilité soit atteignable (§2.8).

### 6.2 Signaux vérifiables

| Signal | Où le vérifier | Remarque |
|---|---|---|
| Importe hors UE | Site de l'entreprise (citation courte + URL) | Déjà la règle du fichier |
| Taille, activité, état | API Recherche d'entreprises (data.gouv) | Déjà utilisée |
| Numéro EORI valide | Outil de validation EORI de la Commission ([R43]) | Seulement si le numéro est publié par l'entreprise ; l'outil valide un numéro, il ne sert pas à en chercher |
| Ventes à distance de petits envois | Site (boutique en ligne, livraison depuis l'étranger) | Concerné par le droit forfaitaire de 3 EUR par article depuis le 1er juillet 2026 ([R54]) |
| Offre d'emploi « assistant import », « ADV import » | Sites d'emploi | Indique un volume ; à citer avec l'URL |
| Membre d'une fédération d'importateurs | Annuaire public de la fédération | Repérage seulement |

Interdits : achat de fichiers (Google le déconseille aussi pour la délivrabilité [R41]), enrichissement automatique, extraction de profils, adresses nominatives devinées.

### 6.3 Séquence et rythme

La séquence actuelle (J0, J+5, J+12, arrêt à la première réponse) est raisonnable. Aucune source fiable consultée ne fixe de nombre optimal de relances ou de longueur idéale d'e-mail ; les chiffres qui circulent viennent souvent d'éditeurs d'outils (non vérifié). Règles retenues (avis) :

- Trois e-mails au maximum, dernier message annoncé comme tel (déjà le cas).
- Moins de 120 mots dans le corps, une demande unique et claire (« 20 minutes la semaine prochaine ? »).
- Envoi un par un, depuis la boîte du fondateur, en semaine.

### 6.4 Personnalisation à partir de faits vérifiés

- Une phrase d'accroche par prospect, tirée de son propre site, avec l'URL conservée dans le fichier (déjà prévu).
- Pas de flatterie générique, pas de fausse familiarité. Cialdini : l'appréciation repose sur des points communs réels et des compliments sincères ([R12]).
- Mom Test pour le premier rendez-vous : faire raconter le dernier dossier d'import et la dernière facture du transitaire, pas demander si l'idée plaît ; finir par un engagement concret (envoi d'un lot, introduction au DAF) ([R18]).

### 6.5 Délivrabilité

Exigences des messageries, applicables même à faible volume :

- Google, tous expéditeurs : SPF **ou** DKIM, DNS direct et inverse valides, TLS, taux de plainte sous 0,3 % (viser moins de 0,1 %) ; au-delà de 5 000 messages par jour : SPF **et** DKIM, DMARC (politique `none` acceptée), alignement du domaine `From`, désinscription en un clic pour les messages marketing ([R41]).
- Google, bonnes pratiques : augmenter le volume lentement, envoyer à rythme régulier, ne pas mélanger les types de contenu, ne pas acheter d'adresses ([R41]).
- Yahoo : mêmes seuils de plainte (0,3 %) ; pour les gros volumes, DMARC au moins `p=none` et désinscription honorée sous deux jours ([R42]).

Pour ControlDOne (avis) : domaine d'envoi dédié au fondateur, SPF + DKIM (clé 2048 bits si possible) + DMARC dès le départ même sous le seuil ; texte brut ou HTML minimal ; un seul lien en clair (le site), aucun raccourcisseur, aucune pièce jointe au premier contact ; 5 envois par jour au début (déjà la règle du plan d'actions).

### 6.6 Réponses

| Réponse | Action |
|---|---|
| STOP, « pas intéressé » | Liste d'opposition le jour même ; remerciement bref, sans relance |
| « Ce n'est pas moi » | Demander à qui transmettre ; ne pas deviner l'adresse de la personne citée |
| Question | Réponse sous 48 h ouvrées, sans pièce jointe non demandée |
| Intérêt | Proposer deux créneaux ; envoyer la liste des pièces et l'accord de diagnostic |
| Objection | Réponse du §1.4 ; noter la formulation exacte du prospect pour la FAQ |

### 6.7 Mesures à suivre

Sans pixel de suivi, le taux d'ouverture n'est pas mesuré ([R37]). Suivre plutôt :
- messages envoyés, par segment et par variante ;
- taux de réponse, et part des réponses positives ;
- rendez-vous tenus ; diagnostics signés ; délai entre premier contact et diagnostic ;
- STOP et plaintes (le taux de plainte doit rester très en dessous de 0,3 % [R41]) ;
- rebonds (adresse invalide) : retirer l'adresse ;
- objections reçues, mot pour mot.

Le critère d'arrêt de `plan_actions_commerciales.md` (moins de 3 accords après 40 prospects et 4 semaines) reste la bonne règle de décision.

---

## 7. Liste de contrôle priorisée

Priorité : **P1** avant toute mise en ligne ou envoi, **P2** dans le mois, **P3** ensuite.

### Site public

1. **P1** Remplacer le titre principal par une des trois formules du §2.2 ; supprimer la question rhétorique.
2. **P1** Réécrire les titres de section en phrases complètes avec verbe (exemples du §3.4).
3. **P1** Ajouter un test de style (`tests/site`) qui signale les expressions de la liste §3.2 dans le texte visible, FR et EN, en avertissement séparé du filtre juridique.
4. **P1** Retirer ou corriger l'affirmation « émission obligatoire pour les PME au plus tard le 1er septembre 2027 » tant qu'elle n'est pas confirmée sur une source officielle ([R55]).
5. **P1** Ajouter le bloc « Mesuré sur fichiers de test synthétiques » (§2.3) avec date, version du moteur et lien vers la Méthode.
6. **P1** Coller « la commission de 20 % sur les avoirs obtenus reste due » à chaque occurrence de « offert ».
7. **P1** Créer une section ou une page « Qui est derrière » : nom, parcours, photo réelle, engagement de relecture.
8. **P2** Restructurer `tarifs.html` : deux points d'entrée (diagnostic, contrôle continu) et une ligne commission commune ; publier la grille du contrôle continu par volume.
9. **P2** Ajouter le calculateur de seuil (version statique en tableau si le site reste sans script).
10. **P2** Compléter la FAQ avec les cinq questions du §2.6.
11. **P2** Choisir l'option de polices A ou B ; servir les `woff2` officiels non modifiés depuis `site/assets/fonts/`, ajouter `font-src 'self'` à la CSP, copier les licences.
12. **P2** Appliquer l'échelle typographique du §4.4 (`clamp()` sur les titres, chiffres tabulaires sur les montants, étiquettes en petites capitales).
13. **P2** Décider « site sans script » ou « un script local » ; dans le second cas, ajouter Motion et `site.js`, CSP `script-src 'self'`, adapter le test.
14. **P2** Motifs 3, 4, 7 et 10 en CSS, avec `@media (prefers-reduced-motion: reduce)`.
15. **P3** Mesurer LCP, INP et CLS sur la page d'accueil publiée et les garder sous 2,5 s, 200 ms et 0,1 ([R20]).

### Application

16. **P1** Isoler visuellement la zone de dépôt de documents et y écrire une phrase de sécurité factuelle (chiffrement, purge, lieu de traitement), sans badge.
17. **P1** Totaux « écart certain » et « à vérifier » toujours séparés, en chiffres tabulaires alignés à droite ; écart en faveur du client affiché comme tel.
18. **P2** Créer les jetons de durée et de courbe du §4.6 dans `app.css` et les utiliser partout à la place des valeurs isolées.
19. **P2** Motif 5 (surlignage de la preuve sur la vignette du document) dans la vue dossier.
20. **P2** Motif 2 (compteur des totaux) une seule fois à l'ouverture du rapport, valeur finale directe si `reduit`.
21. **P2** Vérifier chaque appel Motion contre la version 14.0.0 embarquée (options `spring`, `pathLength`, `scroll` avec `target`).
22. **P2** Aligner les polices de l'application sur l'option choisie (ou garder Geist et Geist Mono et les utiliser aussi sur le site).
23. **P3** Contrôle de contraste automatique (4,5:1) sur les deux thèmes, y compris les couleurs « certain » et « à vérifier » ([R24]).

### Module de prospection

24. **P1** Champs obligatoires : URL source de l'adresse, type (générique / nominative), pays, fonction visée ; refus d'enregistrement sinon.
25. **P1** Liste d'opposition consultée avant chaque envoi ; ajout immédiat sur STOP ; conservation trois ans pour ce seul usage ([R35]).
26. **P1** Gabarit de pied de message non modifiable (identité, SIREN, adresse, source de l'adresse, moyen d'opposition, avertissement).
27. **P1** Aucun pixel ni lien traceur ; un seul lien en clair ([R37]).
28. **P1** Règles par pays : CH = envoi individuel, jamais groupé ([R38]) ; BE = adresses impersonnelles seulement.
29. **P1** Arrêt automatique de la séquence à la première réponse ; trois messages au maximum.
30. **P2** Purge automatique trois ans après la collecte ou le dernier contact initié par le prospect (l'ouverture ne compte pas) ([R35]).
31. **P2** Vérification DNS avant le premier envoi : SPF, DKIM, DMARC, DNS inverse ([R41]).
32. **P2** Tableau de bord sans ouverture : envoyés, réponses, rendez-vous, diagnostics, STOP, rebonds, objections mot pour mot.
33. **P2** Validation humaine de chaque message, plafond quotidien configurable (5 par jour au départ), journal d'envoi exportable pour le droit d'accès.

---

## Références

Toutes consultées le **2026-10-07**.

| Réf. | Source | URL |
|---|---|---|
| R1 | NN/g, How Users Read on the Web (1997) | https://www.nngroup.com/articles/how-users-read-on-the-web/ |
| R2 | NN/g, Executing UX Animations: Duration and Motion Characteristics | https://www.nngroup.com/articles/animation-duration/ |
| R3 | NN/g, Trustworthiness in Web Design: 4 Credibility Factors (2016) | https://www.nngroup.com/articles/trustworthy-design/ |
| R4 | NN/g, State the Price to Give B2B Sites a Competitive Advantage (2013) | https://www.nngroup.com/articles/show-price/ |
| R5 | NN/g, B2B vs. B2C Websites: Key UX Differences (2016) | https://www.nngroup.com/articles/b2b-vs-b2c/ |
| R6 | NN/g, Social Proof in the User Experience (2014) | https://www.nngroup.com/articles/social-proof-ux/ |
| R7 | NN/g, 12 Design Recommendations for Calculator and Quiz Tools (2024) | https://www.nngroup.com/articles/recommendations-calculator/ |
| R8 | CXL, Unique Value Proposition: How to Create a UVP | https://cxl.com/blog/value-proposition-examples-how-to-create/ |
| R9 | CXL, 10 Principles of Effective Pricing Pages | https://cxl.com/blog/10-principles-of-effective-pricing-pages/ |
| R10 | Copyhackers (Joanna Wiebe), How to be specific in your copywriting | https://copyhackers.com/how-to-be-specific/ |
| R11 | Basecamp, Getting Real, « Copywriting is Interface Design » | https://basecamp.com/gettingreal/09.7-copywriting-is-interface-design |
| R12 | Influence at Work (Robert Cialdini), principes de persuasion | https://www.influenceatwork.com/7-principles-of-persuasion/ |
| R13 | April Dunford, A Quickstart Guide to Positioning | https://www.aprildunford.com/post/a-quickstart-guide-to-positioning |
| R14 | Christensen Institute, Jobs to Be Done | https://www.christenseninstitute.org/theory/jobs-to-be-done/ |
| R15 | Christensen, Hall, Dillon, Duncan, « Know Your Customers' Jobs to Be Done », HBR, sept. 2016 (page partiellement accessible) | https://hbr.org/2016/09/know-your-customers-jobs-to-be-done |
| R16 | Bob Moesta, Unpacking the Progress Making Forces Diagram | https://jobstobedone.org/radio/unpacking-the-progress-making-forces-diagram/ |
| R17 | Rob Fitzpatrick, The Mom Test (site du livre) | https://www.momtestbook.com/ |
| R18 | Unusual Ventures, résumé de The Mom Test (source secondaire) | https://www.unusual.vc/rob-fitzpatricks-mom-test/ |
| R19 | Google Search Central, Creating helpful, reliable, people-first content | https://developers.google.com/search/docs/fundamentals/creating-helpful-content |
| R20 | web.dev, Web Vitals | https://web.dev/articles/vitals |
| R21 | web.dev, prefers-reduced-motion | https://web.dev/articles/prefers-reduced-motion |
| R22 | W3C, Understanding SC 2.3.3 Animation from Interactions | https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html |
| R23 | W3C, Understanding SC 2.2.2 Pause, Stop, Hide | https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html |
| R24 | W3C, Understanding SC 1.4.3 Contrast (Minimum) | https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html |
| R25 | Baymard Institute, How Users Perceive Security During the Checkout Flow | https://baymard.com/blog/perceived-security-of-payment-form |
| R26 | Wikipedia, Signs of AI writing | https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing |
| R27 | Wikipédia, Aide : Identifier l'usage d'une IA générative | https://fr.wikipedia.org/wiki/Aide:Identifier_l%27usage_d%27une_IA_g%C3%A9n%C3%A9rative |
| R28 | Légifrance, Code de la consommation, art. L121-1 | https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032227301 |
| R29 | Légifrance, Code de la consommation, art. L121-2 | https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032227297 |
| R30 | Légifrance, Code de la consommation, sous-section « Pratiques commerciales trompeuses » (L121-2 à L121-5) | https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006069565/LEGISCTA000032220953/ |
| R31 | Légifrance, Code de la consommation, art. L121-4 | https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000044563107 |
| R32 | Légifrance, Code de la consommation, section « Publicité comparative » (L122-1 à L122-7) | https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006069565/LEGISCTA000032221021/ |
| R33 | Légifrance, CPCE, section L34-1 à L34-6 (art. L34-5) | https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006070987/LEGISCTA000006165910/ |
| R34 | CNIL, La prospection commerciale par courrier électronique | https://www.cnil.fr/fr/la-prospection-commerciale-par-courrier-electronique |
| R35 | CNIL, Questions-réponses sur les référentiels gestion des activités commerciales et impayés | https://www.cnil.fr/fr/questions-reponses-sur-les-referentiels-relatifs-la-gestion-des-activites-commerciales-et-des |
| R36 | CNIL, Conformité RGPD : comment informer les personnes et assurer la transparence | https://www.cnil.fr/fr/conformite-rgpd-information-des-personnes-et-transparence |
| R37 | CNIL, Pixels de suivi dans les courriers électroniques : recommandations | https://www.cnil.fr/fr/recommandation-pixel-suivi-courriels |
| R38 | OFCOM (BAKOM), Quand les envois en masse sont-ils autorisés ? | https://www.bakom.admin.ch/fr/quand-les-envois-en-masse-sont-ils-autorises |
| R39 | PFPDT (EDÖB), Publicité et marketing | https://www.edoeb.admin.ch/fr/publicite-et-marketing |
| R62 | PFPDT, La nouvelle LPD du point de vue du PFPDT | https://www.edoeb.admin.ch/fr/la-nouvelle-loi-federale-sur-la-protection-des-donnees-du-point-de-vue-du-pfpdt |
| R40 | web.dev, Animations guide (performance) | https://web.dev/articles/animations-guide |
| R41 | Google, Email sender guidelines | https://support.google.com/a/answer/81126 et https://support.google.com/mail/answer/81126 |
| R42 | Yahoo, Sender Best Practices | https://senders.yahooinc.com/best-practices/ |
| R43 | Commission européenne, validation EORI | https://ec.europa.eu/taxation_customs/dds2/eos/eori_validation.jsp |
| R44 | INSEE, NAF rév. 2, division 46 | https://www.insee.fr/fr/metadonnees/nafr2/division/46 |
| R57 | motion.dev, animate() | https://motion.dev/docs/animate |
| R58 | motion.dev, scroll() | https://motion.dev/docs/scroll |
| R59 | motion.dev, inView() | https://motion.dev/docs/inview |
| R60 | motion.dev, stagger() | https://motion.dev/docs/stagger |
| R61 | motion.dev, spring | https://motion.dev/docs/spring |
| R46 | Inter, licence | https://github.com/rsms/inter/blob/master/LICENSE.txt |
| R47 | Inter, site de la famille (fonctions OpenType) | https://rsms.me/inter/ |
| R48 | Source Serif, licence et dépôt ; API Google Fonts (axes `opsz` 8..60, `wght` 200..900) | https://github.com/adobe-fonts/source-serif/blob/release/LICENSE.md ; https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,200..900 |
| R49 | JetBrains Mono, licence | https://github.com/JetBrains/JetBrainsMono/blob/master/OFL.txt |
| R50 | Geist, licence | https://github.com/vercel/geist-font/blob/main/OFL.txt |
| R51 | SIL, OFL FAQ (questions 2.6 et 2.7) | https://openfontlicense.org/ofl-faq/ |
| R52 | Copyhackers (Joanna Wiebe), How to Find Your Message Using Review Mining (2014) | https://copyhackers.com/2014/10/amazon-review-mining/ |
| R53 | IBM Plex, site et licence | https://www.ibm.com/plex/ ; https://github.com/IBM/plex/blob/master/LICENSE.txt |
| R54 | Commission européenne, DG TAXUD, droit forfaitaire temporaire sur les envois de faible valeur | https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en |
| R55 | impots.gouv.fr, Facturation électronique | https://www.impots.gouv.fr/actualite/facturation-electronique |
| R56 | Sites étudiés (partie 4) | https://www.anthropic.com/ ; https://openai.com/ ; https://www.starlink.com/ ; https://neuralink.com/ ; https://www.tesla.com/ (inaccessible) ; https://www.spacex.com/ ; https://www.meta.com/ ; https://stripe.com/ ; https://linear.app/ ; https://vercel.com/ |

