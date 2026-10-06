# ControlDOne v2 — Spécification fonctionnelle

- **Version du document** : 1.0.0 (2 octobre 2026)
- **Statut** : référence pour l'équipe « générateur de corpus » et pour l'équipe « extraction et contrôles ». Ces deux équipes travaillent à partir de ce seul document, sans se parler.
- **Langue** : français. Les identifiants techniques (noms de champs JSON, identifiants de contrôles, valeurs d'énumération) sont en ASCII minuscule, sans accent.
- **Documents liés** : `docs/DECISIONS.md` (choix structurants), `docs/SECURITY.md` (sécurité et cloisonnement).
- **Conventions de rédaction** : « DOIT » marque une exigence, « NE DOIT PAS » une interdiction, « PEUT » une option. Un chiffre en gras dans un tableau de tolérances est une valeur par défaut, modifiable par client (voir §8.3).

---

## Table des matières

1. Objet et périmètre
2. Glossaire
3. Garde-fous juridiques
4. Acteurs et rôles
5. Documents d'entrée
6. Modèle de données du dossier
7. Pipeline de traitement
8. Contrôles : règles communes
9. Famille P — Préalables (complétude, exploitabilité, rattachement)
10. Famille A — Facture commerciale contre déclaration
11. Famille B — Cohérence interne de la déclaration
12. Famille C — Facture du transitaire contre déclaration
13. Famille D — Facture du transitaire contre grille tarifaire ou devis
14. Famille E — Avoirs
15. Famille F — Doublons entre dossiers
16. Famille G — Petits envois (droit forfaitaire par article)
17. Suivi du recouvrement
18. Rapport de diagnostic
19. Banc d'évaluation
20. Exigences non fonctionnelles
21. Hors périmètre
- Annexe A — Liste récapitulative des identifiants de contrôle
- Annexe B — Schéma `truth.json` (JSON Schema)
- Annexe C — Schéma de sortie `findings.json`

---

## 1. Objet et périmètre

### 1.1 Objet

ControlDOne v2 est un service de contrôle indépendant pour les PME françaises qui importent des marchandises. Pour chaque **dossier d'import**, il :

1. rapproche la facture commerciale, la déclaration en douane (données du jeu H1, ou H7 pour les petits envois), la facture du transitaire et ses avoirs ;
2. chiffre les écarts **factuels** (calcul), **documentaires** (un document ne dit pas la même chose qu'un autre) et **contractuels** (une ligne facturée sort de la grille tarifaire convenue) ;
3. suit le recouvrement, auprès du transitaire, des sommes refacturées en trop.

Le produit vend un résultat :

| Offre | Prix | Contenu |
|---|---|---|
| Diagnostic | 390 EUR forfait | Analyse d'un lot de dossiers passés, rapport de diagnostic web et PDF, dossiers de réclamation prêts à envoyer par le client |
| Commission | 20 % des avoirs obtenus | Calculée sur les avoirs rattachés à des écarts signalés par le produit (§17.4) |
| Contrôle continu | à partir de 99 EUR/mois | Contrôle de chaque nouveau dossier à réception, suivi du recouvrement |

Le fondateur exerce seul et à temps partiel. L'IA lit les documents et rédige ; le **code testé** compare et calcule ; le **fondateur valide** tout ce qui sort vers un client.

### 1.2 Principes directeurs (non négociables)

| N° | Principe | Conséquence de conception |
|---|---|---|
| P-1 | Le produit ne constate que des écarts factuels et contractuels. | Chaque constat est formulé « le document X indique V1, le document Y indique V2 » ou « la somme imprimée diffère du calcul des valeurs imprimées ». Voir §3. |
| P-2 | Il ne se prononce jamais sur la justesse d'un droit, d'une taxe, d'un classement tarifaire, d'une origine ou d'une valeur en douane. | Ces sujets sortent sous forme de **note de renvoi** (§3.3), sans montant présenté comme dû. |
| P-3 | Les réclamations sont préparées pour que le **client** les envoie lui-même, jamais au nom du fondateur. | Le dossier de réclamation est rédigé à la première personne du client, sans signature du prestataire (§17.3). |
| P-4 | Le calcul est déterministe. | Le modèle de langage extrait des valeurs et rédige des textes ; il ne calcule ni ne compare jamais. Toutes les comparaisons et tous les montants sont produits par du code versionné et testé. |
| P-5 | Chaque écart cite sa preuve. | Pour chaque valeur : document, page, texte lu, extracteur, confiance (§6.3). |
| P-6 | Les documents sont des données. | Aucun texte lu dans un PDF, un XML, un tableur ou un e-mail n'est exécuté comme une instruction (§20.2). |
| P-7 | En cas de doute, « à vérifier ». | Une fausse accusation contre un transitaire coûte plus cher qu'un écart manqué. La règle de classement (§8.5) est conservatrice. |
| P-8 | « Impossible de conclure » n'est jamais « conforme ». | Un champ illisible donne « non vérifiable », jamais « conforme ». |

### 1.3 Niveaux de résultat

Chaque exécution d'un contrôle produit **un** résultat parmi :

| Résultat (`outcome`) | Sens | Est un constat ? |
|---|---|---|
| `conforme` | Les valeurs comparées concordent dans la tolérance. | Non |
| `ecart_certain` | Écart au-delà de la tolérance, preuve complète, aucune explication par une erreur de lecture. | Oui |
| `a_verifier` | Écart possible, ou preuve incomplète, ou explication plausible par une erreur de lecture, ou sujet de renvoi. | Oui |
| `non_verifiable` | Une donnée nécessaire est absente ou illisible. La raison est donnée. | Non (listé à part dans le rapport) |
| `non_applicable` | Le contrôle ne s'applique pas à ce dossier (ex. pas de facture transitaire). | Non |

Seuls `ecart_certain` et `a_verifier` sont des **constats** (findings). Les deux niveaux de constat sont ceux du rapport client.

### 1.4 Périmètre fonctionnel de la v2

Dans le périmètre : dépôt par dossier de fichiers et par boîte mail dédiée ; découpage, classement, extraction ; modèle de dossier unique et versionné ; contrôles P, A à G ; rapport web et PDF ; file de validation du fondateur ; dossiers de réclamation ; registre de recouvrement ; banc d'évaluation. Hors périmètre : voir §21.

---

## 2. Glossaire

| Terme | Définition dans ce document |
|---|---|
| **Dossier d'import** (`dossier`) | Ensemble des documents relatifs à un même envoi importé : au moins une facture commerciale et au moins une déclaration, plus le cas échéant factures du transitaire, avoirs et documents support. Un document peut appartenir à plusieurs dossiers (ex. facture transitaire mensuelle). |
| **Lot** (`batch`) | Ensemble de fichiers déposés en une fois. Un lot produit un ou plusieurs dossiers. |
| **Facture commerciale** | Facture du fournisseur étranger pour les marchandises. Inclut pro forma, facture « valeur pour la douane seulement », facture sans valeur commerciale, facture générée par un intégrateur express pour le compte de l'expéditeur. C'est le document de référence. |
| **Déclaration** | Déclaration en douane d'importation : données H1 (mise en libre pratique), H7 (petits envois), imprimé DAU à cases numérotées, preuve de dédouanement imprimée par un logiciel de déclarant ou un intégrateur express, export XML ou CSV. |
| **MRN** | Numéro de référence de mouvement attribué par la douane. 18 caractères. Les 15 premiers sont réputés stables entre une déclaration et ses versions rectifiées (« préfixe stable »). |
| **LRN** | Référence locale du déclarant. |
| **Transitaire** | Commissionnaire de transport, déclarant en douane ou intégrateur express qui facture au client ses prestations et lui refacture des **débours**. Le transitaire n'est jamais utilisateur du produit. |
| **Débours** | Sommes payées par le transitaire pour le compte du client et refacturées à l'identique : droits de douane, autres taxes, TVA à l'importation. |
| **Prestations** | Rémunération propre du transitaire : frais de dédouanement, frais d'avance de fonds, lignes supplémentaires, magasinage, transport, manutention, surcharges. |
| **Frais d'avance de fonds** (FAF) | Prestation rémunérant l'avance des débours ; souvent un pourcentage des débours avec minimum et parfois maximum. |
| **Autoliquidation** (ATVAI) | Régime où la TVA à l'importation n'est pas payée en douane mais déclarée par l'importateur sur sa déclaration de TVA. Indices sur la déclaration : code document 1008 suivi du numéro de TVA (H1), référence fiscale complémentaire FR7 (H7), mode de paiement de la ligne TVA différent d'un paiement comptant. Le produit lit ces indices ; il ne dit pas si l'autoliquidation était applicable. |
| **Grille tarifaire** | Tarif convenu entre le client et un transitaire (devis accepté, contrat, barème). Saisie ou importée par le client et validée par le fondateur (§6.2.4). |
| **Avoir** | Note de crédit émise par le transitaire (ou le fournisseur) qui annule tout ou partie d'une facture. |
| **Constat** (`finding`) | Résultat `ecart_certain` ou `a_verifier` d'un contrôle. |
| **Montant en jeu** | Montant signé en EUR attaché à un constat (§8.6). |
| **Note de renvoi** | Mention qui signale un sujet réglementaire hors périmètre et renvoie vers un RDE ou un avocat (§3.3). |
| **RDE** | Représentant en douane enregistré. |
| **Valeur sourcée** | Valeur extraite accompagnée de sa provenance (§6.3). |
| **Fondateur** | Opérateur unique du service ; valide les constats et les dossiers de réclamation avant publication au client. |
| **Extracteur** | Composant qui transforme un document en valeurs sourcées : `structure` (XML/CSV), `deterministe` (texte PDF/OCR + règles), `llm` (modèle de langage). |
| **Tolérance** | Écart maximal sous lequel deux valeurs sont réputées concordantes. |
| **Seuil de certitude** | Écart minimal au-delà duquel un constat peut être `ecart_certain` (toujours supérieur ou égal à la tolérance). |

---

## 3. Garde-fous juridiques

Le service n'est pas une profession réglementée du droit. Il réalise un **audit technique** : rapprochements, calculs, incohérences entre documents, écarts à un tarif contractuel. Il NE DOIT PAS donner de consultation juridique ni rédiger d'acte pour autrui. Toute formulation produite par le système (rapport, interface, dossier de réclamation, e-mail) respecte les règles ci-dessous. Ces règles sont testées automatiquement (§3.5).

### 3.1 Règles de formulation

1. **Toujours comparatif ou arithmétique.** Un constat cite deux sources ou un calcul :
   - « La déclaration (MRN …, page 2) indique 12 450,00 EUR ; la facture commerciale n° … (page 1) indique 12 540,00 USD. »
   - « Le montant imprimé (418,20 EUR) diffère du produit de la base imprimée (2 091,00 EUR) par le taux imprimé (2,5 %) : 52,28 EUR. »
   - « La facture du transitaire refacture 1 240,00 EUR de TVA à l'importation ; la déclaration indique pour cette TVA le mode de paiement “autoliquidation” (code document 1008). »
2. **Jamais de qualification juridique.** Le système ne dit pas qu'une somme est « due », « indue », « illégale », « non conforme », « à rembourser par la douane ».
3. **Le transitaire n'est pas accusé.** On écrit « montant refacturé supérieur au montant liquidé sur la déclaration », jamais « surfacturation frauduleuse » ni « erreur du transitaire ».
4. **Le doute est explicite.** Un constat `a_verifier` porte une raison lisible parmi l'énumération de §8.5.3 (ex. « lecture probablement erronée : 6 et 8 souvent confondus à l'OCR »).
5. **Les montants dus ne sont jamais affirmés.** Le « montant en jeu » d'un écart de recouvrement est présenté comme « montant de l'écart constaté entre les documents », pas comme une créance.
6. **Les tolérances appliquées sont affichées** à côté de chaque constat.

### 3.2 Formulations interdites

Le générateur de textes, les gabarits et les sorties du modèle DOIVENT être filtrés. Toute sortie contenant l'une des expressions suivantes (insensible à la casse et aux accents, y compris au pluriel ou au féminin) est bloquée et part en file de validation avec le motif `formulation_interdite` :

| Interdit | Pourquoi | Remplacer par |
|---|---|---|
| « le bon code », « le code correct », « mauvais classement », « erreur de classement », « devrait être classé » | Avis de classement tarifaire | « le code imprimé sur A diffère du code imprimé sur B » |
| « droit dû », « droits dus », « taxe due », « montant dû à la douane », « trop payé en douane », « remboursement des droits » | Avis sur le bien-fondé de l'imposition | « montant liquidé indiqué sur la déclaration » |
| « valeur en douane incorrecte », « sous-évaluation », « sur-évaluation » | Avis sur la valeur en douane | « le montant facturé déclaré diffère du total de la facture commerciale » |
| « origine incorrecte », « origine fausse », « préférence injustifiée », « préférence applicable », « droit préférentiel » | Avis sur l'origine ou la préférence | « le pays d'origine imprimé sur A diffère de celui imprimé sur B » |
| « taux erroné », « mauvais taux », « le taux applicable est » | Avis sur le taux | « le montant imprimé diffère du produit base × taux imprimés » |
| « non conforme à la réglementation », « illégal », « irrégulier », « en infraction », « fraude », « frauduleux » | Qualification juridique | (supprimer) |
| « nous réclamons », « ControlDOne réclame », « au nom de notre client », « mandaté par » | La réclamation n'est pas faite au nom du prestataire | Rédaction à la première personne du client (§17.3) |
| « vous devez déposer une demande de remboursement », « déposez une réclamation en douane », « il faut rectifier la déclaration » | Recommandation d'une démarche juridique | « point à faire vérifier par un RDE ou un avocat » (phrase de renvoi) |
| « nous garantissons », « certifié conforme » | Engagement de résultat juridique | (supprimer) |

La liste est un fichier de configuration versionné (`config/formulations_interdites.yaml`), enrichissable sans code.

### 3.3 Phrase de renvoi obligatoire

Tout sujet qui touche au bien-fondé d'un droit, d'une taxe, d'un classement tarifaire, d'une origine, d'une préférence, d'une valeur en douane, d'un régime douanier ou de l'applicabilité de l'autoliquidation ou du droit forfaitaire petits envois est signalé avec **exactement** cette phrase (chaîne constante `PHRASE_RENVOI`) :

> **« Ce point relève d'une appréciation réglementaire : il est à faire vérifier par un représentant en douane enregistré ou un avocat. ControlDOne ne se prononce pas sur ce point. »**

Règles :

- La note de renvoi porte au plus des **valeurs lues**, jamais un montant présenté comme dû ou récupérable. Son `montant_en_jeu` est `null` (§8.6).
- Elle est toujours de niveau `a_verifier`.
- Elle est comptée à part dans le rapport (« Points à faire vérifier par un professionnel »), hors des totaux chiffrés.

### 3.4 Avertissement général

Chaque rapport (web, PDF, JSON en champ `avertissement`), chaque dossier de réclamation et le pied de chaque e-mail portent :

> « Ce document est un contrôle technique de cohérence entre documents et de calcul. Il ne constitue ni un conseil juridique, fiscal ou douanier, ni un avis sur la conformité des opérations. Les montants indiqués sont des écarts constatés entre documents ; ils ne préjugent pas des sommes légalement dues. »

### 3.5 Tests de garde-fou

- Test unitaire sur chaque gabarit de texte : aucune expression interdite.
- Test sur 100 % des textes produits par le banc (§19) : aucune expression interdite ; chaque constat de famille A portant sur le code marchandise, l'origine ou la préférence contient `PHRASE_RENVOI`.
- Test : aucun constat avec `nature_montant = renvoi` n'a de `montant_en_jeu` non nul.

---

## 4. Acteurs et rôles

| Acteur | Rôle | Droits |
|---|---|---|
| **Client** (personne morale importatrice) | Souscrit une offre, possède ses entités, transitaires, grilles, dossiers. | Isolé des autres clients (§20.1). |
| **Utilisateur client** | Salarié du client (administration des ventes, comptabilité fournisseurs, service import). Dépose des documents, lit les rapports publiés, corrige des champs, télécharge et envoie lui-même les dossiers de réclamation, déclare l'envoi d'une réclamation et la réception d'un avoir. | Lecture/écriture sur les données de son client. Ne voit que les constats **publiés**. |
| **Fondateur** (opérateur) | Valide ou rejette chaque constat, corrige des champs, valide les grilles tarifaires, publie les rapports, déclenche les dossiers de réclamation. | Accès à tous les clients via une interface d'administration tracée. |
| **Système** | Exécute le pipeline, propose les constats, rédige les brouillons de texte. | Aucun envoi externe autre que les notifications au client et au fondateur. |
| **Modèle de langage** | Classe des pages, extrait des champs dans un schéma fermé, rédige des textes à partir de gabarits. | Aucun outil, aucun accès réseau, aucune écriture en base (§20.2). |
| **Transitaire** | Tiers. Destinataire des réclamations envoyées par le client. | Aucun accès. |
| **RDE / avocat** | Tiers vers lequel les notes de renvoi orientent le client. | Aucun accès. |

Règle de publication : un constat n'est visible par le client qu'après validation du fondateur (`statut_validation = valide`). Les constats `conforme`, `non_verifiable` et `non_applicable` sont publiés avec le rapport sans validation individuelle.

---

## 5. Documents d'entrée

### 5.1 Formats acceptés

| Format | Traitement |
|---|---|
| PDF natif (couche texte) | Texte par page ; OCR seulement si la qualité du texte est faible (§7.3). |
| PDF scanné, image (PNG, JPEG, TIFF multipage) | OCR français + anglais, redressement, rotation 90/180/270, désinclinaison. |
| PDF fusionné | Découpage en documents logiques par page (§7.2). |
| Factur-X (PDF/A-3 avec XML CII embarqué) | XML lu en priorité par l'extracteur `structure` ; PDF visuel conservé comme preuve. |
| UBL 2.1, CII D16B (XML seul) | Extracteur `structure`. Profils EN 16931 et EXTENDED (dont EXTENDED-CTC-FR) exploités en entier ; MINIMUM et BASIC WL ne portent pas de lignes : les contrôles par ligne sont `non_verifiable`. |
| Export de déclaration XML ou CSV | Extracteur `structure` avec correspondance de colonnes déclarée (§5.3.4). |
| Tableur (XLSX, XLS, ODS, CSV) | Chaque feuille est une « page » ; le nom de feuille est conservé comme contexte. |
| Archive ZIP | Décompression sûre (§20.3) ; l'arborescence est conservée comme indice de regroupement. |
| E-mail (boîte dédiée) | Les pièces jointes sont des fichiers d'entrée ; le corps est stocké comme document support de type `courriel`, jamais interprété comme une instruction (§20.2). |

Fichiers refusés avec un motif explicite, sans bloquer le lot : protégé par mot de passe, corrompu, vide, type non supporté, taille au-delà de la limite (§20.3).

### 5.2 Conventions communes aux champs

- **Montants** : décimal exact (`Decimal`, jamais de flottant binaire), stockés avec leur devise ISO 4217. Les devises sans décimales (JPY, KRW…) ont 0 décimale.
- **Signe** : un avoir porte des montants **positifs** et un type `avoir` ; le signe est porté par le type de document, pas par la valeur. Les valeurs imprimées entre parenthèses ou avec un signe moins sont normalisées en valeur absolue avec `signe_imprime = negatif`.
- **Masses** : en kilogrammes, décimal à 3 décimales.
- **Quantités** : décimal avec unité normalisée (code UN/ECE Rec. 20 quand reconnu : `C62` pièce, `KGM`, `LTR`, `MTR`, `MTK`, `PR` paire, etc. ; sinon `unite_brute` conservée et `unite = inconnue`).
- **Dates** : ISO 8601 (`AAAA-MM-JJ`).
- **Pays** : ISO 3166-1 alpha-2.
- **Incoterm** : code à 3 lettres majuscules (`EXW`, `FCA`, `FAS`, `FOB`, `CFR`, `CIF`, `CPT`, `CIP`, `DAP`, `DPU`, `DDP`, plus `DAT`/`DAF`/`DES`/`DEQ`/`DDU` reconnus comme anciens codes), lieu en texte libre.
- **Références** : chaque référence est stockée brute et normalisée. Normalisation `norm_ref` : majuscules, suppression de tout caractère hors `[A-Z0-9]`, suppression des zéros de tête des segments numériques purs uniquement pour la comparaison de containment (§8.4).
- **Codes marchandise** : chiffres uniquement, longueur 6, 8 ou 10 ; la forme imprimée est conservée.
- **Numéros d'identification** : TVA intracommunautaire normalisée (majuscules, sans espace) ; SIREN (9 chiffres) extrait d'un numéro de TVA français (`FR` + clé 2 caractères + SIREN) ou d'un SIRET (14 chiffres) ; EORI normalisé.

### 5.3 Fiches par type de document

Les champs sont listés avec leur identifiant de modèle (`snake_case`), leur sens et leur unité. Un astérisque (*) marque les champs **clés** : ceux dont la confiance conditionne un `ecart_certain` (§8.5).

#### 5.3.1 Facture commerciale (`facture_commerciale`)

Sous-types (`sous_type`) : `facture`, `pro_forma`, `valeur_douane_seulement`, `sans_valeur_commerciale`, `facture_integrateur`. Tous sont acceptés comme référence.

En-tête :

| Champ | Sens | Unité / format |
|---|---|---|
| `numero`* | Numéro de facture tel qu'imprimé | texte + `norm_ref` |
| `date` | Date de facture | date |
| `vendeur.nom`, `vendeur.adresse`, `vendeur.tva` | Vendeur / exportateur | texte |
| `acheteur.nom`, `acheteur.adresse`, `acheteur.tva`*, `acheteur.siren` | Acheteur / facturé à | texte, TVA normalisée, SIREN |
| `destinataire.nom`, `destinataire.tva` | Livré à ; utilisé seulement si l'acheteur n'identifie pas l'entité | texte |
| `eori_importateur` | Informatif | texte |
| `devise`* | Devise de la facture | ISO 4217 |
| `total_facture`* | Total général : dernier total libellé payable, ou total pour la douane | montant |
| `total_origine` | `imprime` (lu sur le document) ou `reconstruit` (somme des lignes) | énumération |
| `sous_totaux` | Lignes de pied distinctes : `marchandises`, `fret`, `assurance`, `emballage`, `remise`, `autre` | liste de montants |
| `incoterm`, `incoterm_lieu` | Conditions de livraison | code, texte |
| `ref_transport` | LTA / connaissement imprimé | texte + `norm_ref` |
| `masse_nette_totale`, `masse_brute_totale` | | kg |
| `nombre_colis` | | entier |
| `quantite_totale` | Si imprimée | décimal + unité |

Lignes (`lignes[]`) : `numero_ligne`, `reference_article`, `description`, `quantite` + `unite`, `prix_unitaire`, `montant_ligne`, `devise_ligne` (si différente), `code_marchandise_imprime` (6 à 10 chiffres, ponctuation conservée en brut), `pays_origine`, `masse_nette`, `masse_brute`.

Pièges que l'extraction DOIT gérer :

- Le total peut être sur la ligne sous son libellé. Les lignes de masse (« total gross weight … kg ») et de nombre de colis ne sont **jamais** des montants : une valeur suivie d'une unité de masse ou précédée d'un libellé de poids est rejetée comme candidat total.
- Plusieurs « total » coexistent (sous-total, fret, total général, total de page) : retenir le dernier total payable ou le « total pour la douane ». Un « total » de page sur une facture multipage n'est pas le total général.
- Total absent : `total_facture` = somme des `montant_ligne`, `total_origine = reconstruit`, confiance plafonnée à 0,60. Un total reconstruit est une **borne basse** (des lignes peuvent manquer).
- Codes marchandise confondus avec téléphones, numéros de TVA, SIREN, LTA, numéros de facture ; code découpé sur deux lignes ; zéro final perdu sur un code à 10 chiffres. Une liste de codes attendus du client PEUT servir de **filtre technique** pour écarter des nombres mal lus ; elle ne valide jamais un code.
- Numéro de TVA lu qui est celui du déclarant ou du transporteur (présent dans le pavé d'un tiers) : il ne devient `acheteur.tva` que s'il est dans le pavé acheteur.
- Formats numériques : `1.234,56`, `1,234.56`, `1 234,56` (espace fine ou insécable), `1'234.56`, devises sans décimales avec séparateur de milliers (`1,250,000 KRW` = un million deux cent cinquante mille).
- Document intitulé « facture » qui n'en est pas une : pré-alerte, liste de réparation ou d'expédition, bon de livraison sans valeur, document d'export ou de perfectionnement passif, devis, bon de commande. Il est classé `document_non_exploitable` avec un motif (§9, P2), jamais traité comme une facture manquante silencieusement.
- Avoir fournisseur ressemblant à une facture : détecté par libellé (« credit note », « avoir », « nota de crédito ») ou total négatif ; classé `avoir`.
- Langues : français, anglais, espagnol au minimum ; libellés multilingues configurables.

#### 5.3.2 Déclaration en douane (`declaration`)

Sous-types : `h1`, `h7`, `dau_cases`, `preuve_dedouanement`, `export_xml`, `export_csv`.

En-tête :

| Champ | Sens | Unité / format |
|---|---|---|
| `mrn`* | MRN ; `mrn_prefixe` = 15 premiers caractères normalisés | texte |
| `lrn`, `numero_declaration` | Autres références, gardées distinctes du MRN | texte |
| `date_acceptation` | Date d'acceptation ou de mainlevée | date |
| `version` | Rang si plusieurs versions du même préfixe (rectificative) | entier |
| `importateur.nom`, `importateur.tva`*, `importateur.eori` | Importateur / référence fiscale | texte |
| `declarant.nom`, `declarant.tva`, `representant.nom` | Déclarant, représentant | texte |
| `destinataire.nom` | | texte |
| `devise_facture`* | Monnaie de facturation (DE 14 05) | ISO 4217 |
| `montant_total_facture`* | Montant total facturé (DE 14 06) | montant dans `devise_facture` |
| `taux_change`* | Taux de change appliqué (DE 14 09) tel qu'imprimé, + `taux_change_sens` (`eur_par_devise` ou `devise_par_eur`, §8.7) | décimal (5 déc.) |
| `incoterm`, `incoterm_lieu` | DE 14 01 | code, texte |
| `pays_expedition`, `pays_destination` | | ISO |
| `masse_brute_totale` | DE 18 03 | kg |
| `nombre_colis_total` | Somme DE 18 06 004 ou total imprimé | entier |
| `nombre_articles` | Nombre d'articles (positions) imprimé | entier |
| `documents_references[]` | DG 12 03 : `{type_code, reference}` — factures (N380, N325 pro forma…), titres de transport, document précédent, code 1008 | liste |
| `indices_autoliquidation` | Présence du code 1008 suivi d'un numéro de TVA, de la référence FR7, ou mode de paiement TVA non comptant ; chaque indice est une valeur sourcée | liste |
| `total_droits_taxes` | Montant total des droits et taxes (DE 14 16) | EUR |
| `total_a_payer` | Total à payer ou à garantir imprimé | EUR |

Articles (`articles[]`) : `numero_article`, `code_marchandise` (8 ou 10 chiffres ; `code_sh6` dérivé), `description`, `pays_origine`, `pays_origine_preferentielle`, `code_preference`, `regime`, `regime_complementaire`, `montant_facture_article` (DE 14 08), `valeur_statistique` (EUR, lue, **jamais jugée**), `masse_nette`, `masse_brute`, `quantite_unite_supplementaire` + `unite`, `nombre_colis`, `references_facture` (si par article).

Lignes de taxation (`taxations[]`, par article) — DG 14 03 :

| Champ | Sens |
|---|---|
| `article` | Numéro d'article de rattachement (`null` si niveau déclaration) |
| `type_taxe` | Code tel qu'imprimé (ex. A00 droits de douane, B00 TVA ; liste non limitative) + `categorie` normalisée : `droit`, `autre_taxe`, `tva`, `forfait_petits_envois`, `inconnue` |
| `base_montant`, `base_quantite`, `base_unite` | Base d'imposition (DG 14 03 040) |
| `taux` | Taux imprimé (pourcentage, ou montant par unité si spécifique) + `taux_nature` : `ad_valorem` / `specifique` |
| `montant` | Montant de la taxe imprimé (DE 14 03 040 043) |
| `montant_a_payer` | DE 14 03 042 |
| `mode_paiement` | Code ou libellé imprimé ; `paiement_normalise` : `comptant`, `differe`, `autoliquide`, `garanti`, `inconnu` |

Pièges :

- MRN, LRN et numéro de déclaration se ressemblent : les garder distincts ; le MRN a 18 caractères alphanumériques avec l'année en tête (2 chiffres) et le code pays (`FR`).
- Le tableau de taxation est aplati par l'OCR : montants et types doivent être réassociés par position de colonne. La colonne « mode de paiement / statut » contient de petits entiers ou lettres qui NE DOIVENT PAS être lus comme des montants.
- Les taxes de plusieurs articles se somment. Une composante (souvent « autres taxes ») peut manquer à l'extraction alors que le total est lu : voir C5 et la règle de complétude (§12.1).
- Plusieurs versions (rectificatives) partagent le préfixe MRN : regrouper, retenir la **dernière** version pour les contrôles, ne jamais additionner les taxes de deux versions.
- Une page peut porter plusieurs numéros de TVA du client (entités d'un groupe).
- Le montant facturé peut être en devise étrangère ou déjà converti en EUR.
- Pages de continuation sans en-tête : rattachées à la déclaration précédente tant que le MRN ne change pas.
- H7 : peu de détail (pas toujours de taux de change, souvent un seul article par code).

#### 5.3.3 Facture du transitaire (`facture_transitaire`)

| Champ | Sens | Unité |
|---|---|---|
| `numero`*, `date` | | texte, date |
| `emetteur.nom`, `emetteur.tva` | Transitaire ; sa TVA ne doit jamais être prise pour celle du client | texte |
| `client_facture.nom`, `client_facture.tva` | Client facturé | texte |
| `refs_transport[]` | LTA, LTA maison, connaissements (avec espaces ou barres en brut) | liste |
| `refs_mrn[]` | MRN cités, éventuellement en tableau `{ref_transport, mrn, date}` | liste |
| `refs_facture_commerciale[]` | Si citées | liste |
| `devise` | En principe EUR | ISO |
| `lignes[]` | Voir ci-dessous | |
| `total_debours` | Total des débours, `imprime` ou `reconstruit` | EUR |
| `total_ht`, `total_tva`, `total_ttc`, `net_a_payer` | | EUR |
| `est_releve` | Vrai si relevé ou facture mensuelle couvrant plusieurs envois | booléen |

Lignes (`lignes[]`) : `libelle`, `nature` (énumération ci-dessous), `quantite`, `prix_unitaire`, `montant_ht`, `taux_tva`, `marqueur_tva` (lettre imprimée), `montant_tva`, `montant_ttc`, `mrn` (si ligne rattachée à un MRN), `ref_transport`, `code_marchandise`, `base_droit`, `base_tva`, `date_debut`, `date_fin` (magasinage).

Énumération `nature` des lignes :

| Valeur | Famille | Exemples de libellés |
|---|---|---|
| `debours_droits` | débours | droits de douane, duty |
| `debours_autres_taxes` | débours | autres taxes, accises, droits antidumping refacturés |
| `debours_tva` | débours | TVA import, import VAT |
| `debours_combines` | débours | « droits et taxes » sans ventilation |
| `debours_forfait_petits_envois` | débours | droit forfaitaire par article |
| `frais_dedouanement` | prestation | dédouanement, customs clearance |
| `frais_avance_fonds` | prestation | avance de fonds, disbursement fee |
| `frais_ligne_supplementaire` | prestation | ligne/article supplémentaire |
| `magasinage` | prestation | storage, magasinage |
| `transport` | prestation | livraison, enlèvement |
| `manutention` | prestation | handling |
| `surcharge` | prestation | carburant, sûreté, haute saison |
| `autre_prestation` | prestation | tout le reste |

Pièges : total des débours non imprimé (le reconstruire, `total_origine = reconstruit`) ; montant « droits et taxes » combiné qui NE DOIT PAS être lu comme « droits seuls » ; lettres de statut TVA à côté des montants ; pages de conditions générales et lettres d'accompagnement à écarter ; une facture couvrant plusieurs MRN ; un MRN facturé par une facture initiale plus une facture complémentaire ; facture de débours et facture de prestations séparées pour un même envoi ; un nom d'intégrateur figurant sur une facture commerciale comme mode d'expédition ne fait pas de ce document une facture transitaire.

#### 5.3.4 Avoir (`avoir`)

| Champ | Sens |
|---|---|
| `numero`*, `date`, `emetteur` | |
| `refs_facture_origine[]` | Factures créditées (peut être vide) |
| `refs_mrn[]`, `refs_transport[]` | |
| `lignes[]` | Mêmes champs et même énumération `nature` que la facture transitaire ; montants positifs |
| `total_credite_ht`, `total_tva`, `total_credite_ttc`, `devise` | |
| `motif` | Texte du motif, stocké comme donnée |

Pièges : avoir présenté comme une facture à total négatif ; avoir partiel ; avoir couvrant plusieurs factures ; avoir sans référence ; même avoir reçu deux fois (e-mail et relevé) ; avoir arrivant des mois plus tard ; avoir portant sur des prestations et non des débours.

#### 5.3.5 Documents support (`document_support`)

Sous-types : `titre_transport` (LTA, connaissement, CMR), `liste_colisage`, `pre_alerte`, `conditions_generales`, `lettre_accompagnement`, `courriel`, `certificat`, `preuve_paiement`, `autre`. Champs utiles : `ref_transport` (maître et maison), expéditeur, destinataire, `nombre_colis`, `masse_brute`, `masse_taxable`, `refs_facture[]`. Ils servent au rattachement et aux contrôles de masse/colis ; ils ne sont jamais lus comme une valeur marchande. Un document qui porte une référence de transport **et** un intitulé de facture n'est pas un titre de transport.

#### 5.3.6 Correspondance des exports structurés

Pour chaque format d'export de déclaration (XML ou CSV), une **fiche de correspondance** versionnée (`config/mappings/<format_id>.yaml`) associe chaque colonne ou chemin XPath à un champ du modèle et à son unité. L'ajout d'un format ne nécessite pas de code. Une colonne inconnue est ignorée et journalisée.

---

## 6. Modèle de données du dossier

### 6.1 Vue d'ensemble

```
Client ─┬─ Entite (1..n)          Transitaire (0..n) ── GrilleTarifaire (0..n, versionnée)
        ├─ ProfilTolerances (1, versionné)
        └─ Lot (0..n) ── Fichier (1..n) ── Page (1..n)
                                   └── Document (1..n, logique) ── ValeurSourcee (n)
Dossier (versionné) ── LienDocument (n..n, avec rôle et allocation)
        ├── ResultatControle (n) ── Constat (0..1) ── Preuve (1..n)
        ├── Reclamation (0..n) ── EvenementRecouvrement (n)
        └── Correction (n, événements, append-only)
Execution (run) : versions moteur / schéma / règles / tolérances / extracteurs
```

### 6.2 Entités

Toutes les entités ont `id` (UUID v7), `client_id` (sauf `Execution` globale), `cree_le`, `modifie_le`. Les champs ci-dessous sont normatifs ; les types sont ceux du JSON exporté.

#### 6.2.1 Client, Entite

- `Client` : `raison_sociale`, `offre` (`diagnostic`, `continu`), `plafond_cout_ia_mensuel_eur`, `retention_jours`, `boite_mail_dediee`, `expediteurs_autorises[]`.
- `Entite` : entité juridique contrôlée du client. `raison_sociale`, `tva` (normalisée), `siren`, `eori`, `alias[]` (noms, abréviations, codes internes), `adresses[]`. Un alias n'est accepté pour identifier une entité que s'il désigne **une seule** entité ; l'alias le plus long (le plus spécifique) l'emporte sur un alias plus court qu'il contient.

#### 6.2.2 Transitaire

`nom`, `tva`, `alias[]`, `adresse`, `contact_reclamation` (texte libre saisi par le client). Aucun nom de transitaire réel n'est livré avec le produit.

#### 6.2.3 ProfilTolerances

Ensemble des tolérances de §8.3, versionné (`version` entière), avec `empreinte` SHA-256 du contenu canonique. Chaque résultat de contrôle cite l'empreinte utilisée.

#### 6.2.4 GrilleTarifaire

| Champ | Sens |
|---|---|
| `transitaire_id`, `reference` (n° de devis ou contrat), `valide_du`, `valide_au` | |
| `statut` | `brouillon`, `validee` (seule une grille validée par le fondateur sert aux contrôles D) |
| `postes[]` | `{code_poste, nature (énumération §5.3.3), libelles_reconnus[], mode ("forfait" \| "unitaire" \| "pourcentage" \| "par_jour"), prix, unite_base, pourcentage, base_pourcentage ("debours_total" \| "debours_hors_tva" \| "droits" …), minimum, maximum, franchise_jours, inclus (nombre d'unités comprises dans le forfait, ex. articles), devise}` |
| `prestations_hors_grille` | `interdites` (toute ligne non listée est un écart) ou `tolerees` (signalées `a_verifier`) |
| `preuve` | Document source de la grille (devis PDF) avec page |

#### 6.2.5 Lot, Fichier, Page

- `Lot` : `canal` (`depot`, `courriel`, `api`), `recu_le`, `expediteur` (si courriel), `statut`.
- `Fichier` : `nom_original`, `chemin_relatif` (arborescence d'origine conservée), `sha256`, `taille`, `type_mime`, `statut` (`ok`, `refuse`), `motif_refus`.
- `Page` : `fichier_id`, `numero` (1-based), `rotation_appliquee`, `qualite_texte` (`natif`, `natif_faible`, `ocr`, `illisible`), `score_ocr` (0–1), `texte` (chiffré au repos), `sha256_texte`, `feuille` (tableur).

#### 6.2.6 Document

Document **logique** (une facture répartie sur 3 pages d'un PDF fusionné est un document).

| Champ | Sens |
|---|---|
| `type` | `facture_commerciale`, `declaration`, `facture_transitaire`, `avoir`, `document_support`, `document_non_exploitable`, `inconnu` |
| `sous_type` | Voir §5.3 |
| `pages[]` | `{fichier_id, numero}` ordonnées |
| `confiance_classement` | 0–1 |
| `motif_non_exploitable` | Si applicable (énumération P2) |
| `identite` | Clé de dédoublonnage : `sha256` du fichier si document = fichier entier, sinon `(type, norm_ref(numero), emetteur normalisé, montant total)` |
| `champs` | Objet dont chaque feuille est une `ValeurSourcee` (§6.3), structure conforme à §5.3 |
| `doublon_de` | `document_id` si doublon intra-client (F1) |

#### 6.2.7 Dossier

| Champ | Sens |
|---|---|
| `reference` | Lisible : `D-AAAA-NNNNN` |
| `version` | Entier, +1 à chaque changement (document ajouté/retiré, correction, re-rattachement, nouvelle exécution) |
| `cles` | `{num_facture_transitaire[], ref_transport[], mrn[], num_facture_commerciale[]}` — toujours dans cet ordre à l'affichage |
| `statut_global` | Voir §18.2 |
| `liens[]` | `LienDocument` |
| `allocations[]` | Répartition plusieurs-à-plusieurs (§6.2.8) |
| `transitaire_id` | |
| `incomplet` | Booléen + liste des documents obligatoires manquants |

#### 6.2.8 LienDocument et Allocation

- `LienDocument` : `{document_id, role ("facture_commerciale" | "declaration" | "facture_transitaire" | "avoir" | "support"), force ("forte" | "moyenne" | "faible" | "manuelle"), signaux[] (liste des indices ayant justifié le lien, ex. "mrn_cite", "ref_facture_citee", "ref_transport", "montant_egal", "meme_dossier_source", "meme_fichier_source", "tva", "codes_communs", "nom_fichier"), score}`.
- `Allocation` : relie une facture commerciale à une déclaration, ou une ligne de facture transitaire à un MRN, avec `montant_alloue` et `methode` (`totalite`, `reference_explicite`, `ligne_par_mrn`, `prorata`, `manuelle`). Une allocation `prorata` rend les contrôles qui en dépendent au mieux `a_verifier`.

#### 6.2.9 ResultatControle, Constat, Preuve

- `ResultatControle` : `{controle_id, dossier_id, dossier_version, execution_id, outcome (§1.3), raison_code, entrees: {cle: valeur_sourcee_id}, attendu, constate, ecart, tolerance_appliquee, seuil_certitude_applique}`.
- `Constat` (si `outcome` ∈ {`ecart_certain`, `a_verifier`}) : `{id, controle_id, niveau, raisons[] (§8.5.3), libelle (texte généré), montant_en_jeu (décimal ou null), nature_montant (§8.6), composante (droit | autre_taxe | tva | forfait_petits_envois | prestation | valeur | null), sens ("defaveur_client" | "faveur_client" | null), documents_concernes[], preuves[], renvoi (booléen), statut_validation ("propose" | "valide" | "rejete" | "modifie"), valide_par, valide_le, commentaire_validation, prochaine_action}`.
- `Preuve` : `{valeur_sourcee_id, role ("valeur_a" | "valeur_b" | "operande" | "contexte"), extrait_image (rognage de page, optionnel)}`.

#### 6.2.10 Reclamation, EvenementRecouvrement

Voir §17.

#### 6.2.11 Correction

Événement append-only : `{id, cible (valeur_sourcee_id ou lien), ancienne_valeur, nouvelle_valeur, auteur, role_auteur, motif, le}`. Une correction crée une nouvelle `ValeurSourcee` d'extracteur `saisie_humaine` qui **remplace** la précédente pour les contrôles, sans l'effacer. Toute correction incrémente `Dossier.version` et relance les contrôles.

#### 6.2.12 Execution

`{id, demarre_le, termine_le, version_moteur, version_schema, version_regles, empreinte_tolerances, versions_extracteurs{}, modele_llm (identifiant exact ou null), cout_ia_eur, jetons_entree, jetons_sortie, duree_s}`. Toute sortie (rapport, JSON, banc) référence son `execution_id`. Rejouer une exécution avec les mêmes versions et les mêmes valeurs sourcées DOIT donner des résultats identiques octet pour octet (hors horodatages).

### 6.3 Provenance : la valeur sourcée

Chaque valeur utilisée par un contrôle est une `ValeurSourcee` :

```json
{
  "id": "vs_018f...",
  "chemin": "facture_commerciale.total_facture",
  "valeur": "12540.00",
  "type": "montant",
  "unite": "USD",
  "valeur_brute": "USD 12,540.00",
  "document_id": "doc_...",
  "page": 2,
  "zone": {"x0": 0.61, "y0": 0.83, "x1": 0.92, "y1": 0.86},
  "texte_contexte": "TOTAL AMOUNT DUE  USD 12,540.00",
  "extracteur": {"type": "deterministe", "id": "pdf_regles", "version": "1.4.0"},
  "methode": "texte_natif",
  "confiance": 0.97,
  "derivee_de": [],
  "regle_derivation": null,
  "ancree": true
}
```

| Champ | Règle |
|---|---|
| `methode` | `xml_structure`, `csv_structure`, `texte_natif`, `ocr`, `llm`, `saisie_humaine`, `derive` |
| `confiance` | 0–1. `xml_structure`/`csv_structure` = 1,0 si le schéma valide ; `saisie_humaine` = 1,0 ; `derive` = minimum des confiances sources × facteur de §8.5.2 |
| `zone` | Coordonnées relatives à la page (0–1). Obligatoire pour `texte_natif`, `ocr`, `llm` quand l'ancrage est trouvé |
| `ancree` | Vrai si `valeur_brute` a été retrouvée **littéralement** dans le texte de la page citée (après normalisation des espaces). Une valeur `llm` non ancrée a sa confiance plafonnée à 0,50 et ne peut jamais fonder un `ecart_certain` |
| `derivee_de` | Liste d'identifiants de valeurs sources si `methode = derive` (ex. total reconstruit = somme des lignes) |

Règle d'or : **aucune valeur n'est recopiée d'un document vers un autre**. Si un champ manque sur la facture, la valeur de la déclaration n'est reprise que si cette valeur exacte (ou une somme de lignes égale) est retrouvée dans le texte de la facture ; elle devient alors une valeur sourcée de la facture, ancrée sur ce texte.

### 6.4 Versionnement du schéma

- `version_schema` suit SemVer et figure dans chaque JSON produit (`"schema": "controldone.dossier/2.1.0"`).
  - **majeure** : suppression ou changement de sens d'un champ, changement d'énumération incompatible ;
  - **mineure** : ajout de champ optionnel, ajout de valeur d'énumération ;
  - **correctif** : clarification sans effet sur les données.
- Les migrations sont des scripts numérotés, en avant uniquement, idempotents, testés sur un jeu de dossiers figés.
- Un lecteur DOIT refuser un document de version majeure supérieure à la sienne et accepter les mineures supérieures en ignorant les champs inconnus.
- Le dossier lui-même est versionné (`Dossier.version`) ; chaque `ResultatControle` cite `dossier_version`. Le rapport publié est figé sur une version ; une modification ultérieure produit un nouveau rapport, l'ancien reste consultable.
- Les identifiants de contrôle (Annexe A) sont stables : un contrôle supprimé garde son identifiant réservé ; un changement de sémantique crée un nouvel identifiant.

---

## 7. Pipeline de traitement

Chaque étape est un **job** de la file en base (voir `docs/DECISIONS.md`, D-004), idempotent, avec une clé d'idempotence déterministe. Une étape relancée avec les mêmes entrées ne produit aucun doublon.

| # | Étape | Entrée → sortie | Clé d'idempotence |
|---|---|---|---|
| 1 | Réception | Fichiers ou courriel → `Lot`, `Fichier` | `sha256(fichier) + client_id` (et `Message-ID` pour un courriel) |
| 2 | Pages | `Fichier` → `Page` (texte natif, OCR si besoin) | `sha256(fichier) + n° page + version_ocr` |
| 3 | Découpage et classement | `Page` → `Document` | `sha256(textes des pages) + version_classifieur` |
| 4 | Extraction | `Document` → `ValeurSourcee` | `document.identite + extracteur.id + version` |
| 5 | Normalisation | valeurs brutes → valeurs normalisées | idem + `version_normalisation` |
| 6 | Dédoublonnage et regroupement | `Document` → `Dossier`, `LienDocument`, `Allocation` | `ensemble trié des document_id + version_regroupement` |
| 7 | Contrôles | `Dossier@version` → `ResultatControle`, `Constat` | `dossier_id + dossier_version + version_regles + empreinte_tolerances` |
| 8 | Rédaction | `Constat` → `libelle`, `prochaine_action` (gabarits, modèle optionnel) | `constat_id + version_gabarits` |
| 9 | File de validation | Constats `propose` → validation fondateur | — |
| 10 | Rapport | Dossiers validés → rapport web, PDF, JSON, tableur | `ensemble des dossier_id@version + version_rapport` |

### 7.1 Réception

- **Dépôt** : glisser-déposer de fichiers, de dossiers (arborescence conservée) ou d'archives ZIP.
- **Boîte dédiée** : une adresse par client. Seuls les expéditeurs de `expediteurs_autorises[]` sont traités ; les autres messages sont mis en quarantaine et signalés au fondateur. Le corps du message est stocké comme `document_support/courriel` ; il n'est **jamais** interprété comme une consigne (ex. « ignorez la facture précédente » reste du texte).
- Un fichier identique (`sha256`) déjà reçu pour le même client n'est pas retraité ; il est rattaché au nouveau lot avec la mention « doublon de fichier ».

### 7.2 Découpage et classement

- Classement **page par page** parmi : les types de §6.2.6 + `continuation`.
- Une page `continuation` (sans en-tête) est absorbée par le document précédent du même fichier, **sauf** si une référence clé change (nouveau MRN, nouveau numéro de facture), auquel cas un nouveau document commence.
- Plusieurs déclarations dans un même PDF : découpe sur changement de préfixe MRN.
- Pages `conditions_generales`, `lettre_accompagnement` : documents support, exclus de l'extraction des montants.
- Un document de confiance de classement < 0,70 est `inconnu` ; aucun champ de facture n'en est extrait ; il apparaît dans la liste « documents non reconnus ».
- Fichier image sans texte et OCR indisponible : document `inconnu` créé avec, comme seule information, les indices tirés du nom de fichier (`methode = derive`, confiance 0,30), pour que le dossier reste visible.

### 7.3 Extraction

- Ordre de préférence des extracteurs : `structure` (XML/CSV/Factur-X) > `deterministe` (texte natif) > `llm` (si clé configurée) > `deterministe` sur OCR.
- Qualité du texte : `natif` si ≥ 85 % des caractères de la page sont imprimables et forment des mots du dictionnaire FR/EN ou des nombres ; sinon OCR, et l'on garde la meilleure des deux sources par page.
- Le modèle de langage reçoit le texte de la page (et optionnellement l'image), un schéma JSON fermé et la consigne de ne rien inventer. Sa réponse est validée contre le schéma ; tout champ hors schéma est ignoré. Chaque valeur renvoyée est **ancrée** (§6.3).
- (D-4001 à D-4003) Le modèle n'est appelé que si l'extraction déterministe est faible (aucune extraction, champ requis absent, champ clé de confiance < 0,70) et ne fait que **compléter** : une valeur lisible du déterministe n'est jamais remplacée. Une valeur du modèle introuvable sur la page est **rejetée** ; une valeur retrouvée prend le texte imprimé et une confiance ≤ 0,65 : elle ne fonde jamais seule un `ecart_certain`.
- Plusieurs extracteurs PEUVENT tourner sur le même document ; en cas de désaccord sur un champ clé, la valeur de plus haute confiance est retenue, sa confiance est plafonnée à 0,80 et la raison `extracteurs_en_desaccord` est mémorisée.

### 7.4 Normalisation

Nombres (§5.2), devises (symboles `$` ambigu → `USD` seulement si le pays du vendeur ou un code ISO présent sur la page le confirme, sinon `inconnue`), dates, pays, unités, références, codes marchandise (reconstitution d'un zéro final perdu seulement si le code à 9 chiffres complété par `0` correspond exactement à un code présent sur un autre document du dossier ; la valeur reconstituée est `derive`).

### 7.5 Regroupement en dossiers

Algorithme (déterministe, ordonné) :

1. **Frontière dure** : deux documents issus de dossiers d'origine différents (arborescence de dépôt ou de ZIP, au niveau du dossier parent le plus profond qui contient des documents de types différents) ne sont jamais regroupés automatiquement. Les courriels forment chacun une frontière, sauf référence explicite commune (MRN ou référence de transport).
2. **Graine** : chaque facture commerciale exploitable.
3. **Déclarations** rattachées par, dans l'ordre de force : référence de facture citée sur la déclaration (forte), référence de transport commune (forte), même fichier source (moyenne), montant facturé égal dans la tolérance A1 (moyenne), même TVA importateur + codes SH6 communs (faible), convention de nom de fichier (faible, indice optionnel).
4. **Factures transitaires** rattachées par MRN cité (forte), référence de transport (forte), total des débours égal au total des taxes (moyenne), même fichier source (moyenne).
5. **Avoirs** rattachés par facture d'origine citée (forte), MRN ou référence de transport (moyenne).
6. Score = somme des poids (forte 3, moyenne 2, faible 1) ; un lien n'est créé que si score ≥ 2 ; un lien de score 2 a `force = faible` et est affiché comme « rattachement faible » (P4).
7. Documents restants : chaque déclaration ou facture transitaire orpheline devient son propre dossier `incomplet`. Rien n'est silencieusement abandonné.
8. Plusieurs factures pour une déclaration : toutes rattachées ; une facture répartie sur plusieurs déclarations : `Allocation` par référence explicite, sinon répartition au prorata des montants déclarés (`methode = prorata`).

Le fondateur et l'utilisateur client PEUVENT fusionner, scinder un dossier ou déplacer un document ; l'action est une `Correction` de lien (`force = manuelle`).

### 7.6 Contrôles, constats, rédaction

Les contrôles sont des fonctions pures : `(dossier figé, profil de tolérances, grilles validées, référentiels) → ResultatControle`. Aucun appel réseau, aucun appel au modèle. Le libellé est produit par gabarit ; le modèle PEUT reformuler un gabarit pour la lisibilité, puis le texte passe le filtre de §3.2 et un contrôle de **conservation des nombres** : tous les nombres du texte reformulé doivent figurer dans le gabarit source, sinon le gabarit brut est utilisé.

### 7.7 File de validation

Le fondateur voit, par priorité : (1) `ecart_certain` à montant recouvrable décroissant ; (2) `a_verifier` à montant décroissant ; (3) notes de renvoi ; (4) documents non reconnus ; (5) rattachements faibles. Pour chaque constat : les deux valeurs, la tolérance, les extraits de page côte à côte, les boutons `valider`, `rejeter` (motif obligatoire), `rétrograder en à vérifier`, `corriger une valeur`. Il NE PEUT PAS promouvoir un `a_verifier` en `ecart_certain` sans corriger ou confirmer par `saisie_humaine` la valeur douteuse (ce qui relance le contrôle).

---

## 8. Contrôles : règles communes

### 8.1 Forme d'un contrôle

Chaque contrôle est spécifié par : **identifiant** (lettre de famille + numéro, stable, Annexe A), **entrées** (chemins du modèle), **règle déterministe**, **tolérance** et **seuil de certitude**, **classement** (`ecart_certain` / `a_verifier`), **montant en jeu**, **preuve exigée**. Un contrôle s'exécute **une fois par unité de comparaison** (dossier, couple facture/déclaration, déclaration, ligne de taxation, ligne de facture, MRN…) précisée dans sa fiche. Un même contrôle peut donc produire plusieurs constats dans un dossier.

Notation : `a` = valeur de référence (document le plus en amont : facture commerciale pour A, déclaration pour C/G, grille pour D) ; `b` = valeur comparée ; `écart = b − a`.

### 8.2 Arithmétique

- Décimal exact ; arrondi **au centime, demi vers le haut** (`ROUND_HALF_UP`) pour tout montant calculé en EUR ; à l'unité de la devise pour les devises sans décimales.
- Jamais d'arrondi intermédiaire dans une somme ; on arrondit le résultat final.
- Conversion en EUR uniquement au taux imprimé sur la déclaration du dossier (§8.7). Aucun montant en jeu n'est calculé à partir d'un taux indicatif.

### 8.3 Tolérances par défaut (profil modifiable par client)

| Code | Usage | Valeur par défaut | Justification |
|---|---|---|---|
| `T_LIGNE` | Arithmétique d'une ligne (quantité × prix unitaire, base × taux de TVA d'une prestation) | **0,01** EUR | Arrondi au centime d'un seul calcul. |
| `T_SOMME` | Somme de n lignes contre un total imprimé | **min(0,01 × n ; 0,50)** EUR, au moins 0,01 | Chaque ligne peut porter un demi-centime d'arrondi ; plafond pour ne pas masquer un écart réel. |
| `T_TAXE_LIGNE` | B1 : base × taux contre montant imprimé | **0,01** EUR, ou montant égal à l'arrondi à l'euro (inférieur, supérieur ou au plus proche) du calcul | Certains systèmes arrondissent les droits à l'euro. |
| `T_VALEUR` | A4 : total facture contre montant facturé déclaré (même devise) | **max(1 unité de devise ; 0,1 %)** | Le montant déclaré est une recopie ; seul un arrondi à l'unité est admis. |
| `S_VALEUR` | Seuil de certitude A4 | **max(5 unités ; 0,5 %)** | En dessous, une ligne de pied (remise, frais bancaires) ou une lecture partielle reste plausible. |
| `T_CONVERSION` | A5 : montant EUR déclaré contre montant facture × taux imprimé | **max(1,00 EUR ; 0,1 %)** | Taux imprimé à 5 décimales et arrondi à l'unité possible. |
| `S_CONVERSION` | Seuil de certitude A5 | **max(5,00 EUR ; 0,5 %)** | Idem A4. |
| `BANDE_INDICATIVE` | A7 : ordre de grandeur au taux indicatif | **± 25 %** ; **± 40 %** pour les devises de la liste `devises_volatiles` | Un taux indicatif ne sert qu'à détecter une erreur d'ordre de grandeur. |
| `T_DEBOURS` | C1–C5, G4 : débours refacturés contre montants liquidés, par composante et par déclaration | **max(0,05 ; min(0,01 × nb_articles ; 0,50))** EUR | Écarts d'arrondi par article contre arrondi global. |
| `S_DEBOURS` | Seuil de certitude C, F3, G4, G5 | **1,00** EUR | Aucune réclamation pour moins d'un euro d'écart ; entre la tolérance et 1 EUR : `a_verifier`. |
| `T_TARIF` | D2–D9 : prix facturé contre grille | **0,01** EUR par ligne | Le tarif est contractuel, au centime. |
| `S_TARIF` | Seuil de certitude D | **0,10** EUR par ligne | Évite de réclamer des écarts d'arrondi d'un pourcentage. |
| `S_ARITH` | Seuil de certitude D1, E4 | **1,00** EUR | Un écart d'arithmétique interne de quelques centimes est un arrondi ; au-delà d'1 EUR il est significatif. |
| `T_MASSE` | A10, B4 | **max(0,5 kg ; 0,5 %)** | Arrondi des masses par article ; emballage. |
| `T_QUANTITE` | A9 | **0** pour les unités entières (pièces, paires), **0,5 %** sinon | Une quantité en pièces se recopie exactement. |
| `T_COLIS` | A11, B5 | **0** | Nombre entier recopié. |
| `C_MIN_CERTAIN` | Confiance minimale de chaque valeur clé pour `ecart_certain` | **0,90** | Au-dessous, l'écart peut venir de la lecture. |
| `C_MIN_UTILE` | Confiance minimale pour exécuter le contrôle (sinon `non_verifiable`) | **0,50** | Une valeur plus douteuse n'est pas exploitable. |

Règles de configuration : une tolérance client ne peut être **qu'élargie** par rapport au défaut pour les seuils de certitude (`S_*`, `C_MIN_CERTAIN`), jamais réduite, afin de préserver la prudence. Chaque résultat enregistre la tolérance et le seuil effectivement appliqués.

### 8.4 Comparaison de références

- `ref_egales(x, y)` : `norm_ref(x) == norm_ref(y)`.
- `ref_compatibles(x, y)` : égales, ou l'une contient l'autre et la plus courte a au moins 5 caractères (préfixes, troncatures).
- MRN : comparaison sur `mrn_prefixe` (15 caractères).
- Références de transport : comparaison après suppression des espaces, tirets et barres ; un préfixe compagnie de 3 chiffres séparé (`999-11112222`) est égal à la forme collée.

### 8.5 Classement « écart certain » / « à vérifier »

#### 8.5.1 Règle générale

Un contrôle dont l'écart dépasse la tolérance produit `ecart_certain` **si et seulement si toutes** les conditions suivantes sont vraies ; sinon `a_verifier` :

1. **Contrôle éligible** : la fiche du contrôle autorise `ecart_certain` (certains contrôles sont `a_verifier` par construction, voir Annexe A).
2. **Écart significatif** : `|écart| > seuil de certitude` du contrôle.
3. **Confiance** : chaque valeur clé entrant dans le calcul a `confiance ≥ C_MIN_CERTAIN` et `ancree = true` (ou `methode` ∈ {`xml_structure`, `csv_structure`, `saisie_humaine`}).
4. **Pas de dérivation fragile** : aucune valeur clé n'est un total `reconstruit` dont la reconstruction pourrait expliquer l'écart (un total reconstruit inférieur à la valeur comparée est toujours `a_verifier`, raison `total_reconstruit`).
5. **Rattachement solide** : les documents comparés sont liés au dossier par un lien `forte` ou `manuelle`, et l'allocation éventuelle n'est pas `prorata`.
6. **Aucune explication par la lecture** : le test de confusion (§8.5.4) est négatif.
7. **Aucune explication documentée** : aucune ligne de pied, aucun avoir déjà imputé, aucune version rectificative de la déclaration n'explique l'écart dans la tolérance.
8. **Pas de renvoi** : le constat n'est pas une note de renvoi.

#### 8.5.2 Confiance des valeurs dérivées

`confiance(dérivée) = min(confiances sources) × f`, avec `f = 1,0` pour une somme de valeurs toutes ancrées, `0,6` pour un total reconstruit depuis des lignes OCR, `0,3` pour une valeur tirée d'un nom de fichier.

#### 8.5.3 Raisons (`raisons[]`) d'un constat `a_verifier`

`ecart_sous_seuil`, `confiance_insuffisante`, `valeur_non_ancree`, `lecture_douteuse` (test de confusion positif), `total_reconstruit`, `rattachement_faible`, `allocation_prorata`, `ecart_explique_par_ligne_de_pied`, `devise_incertaine`, `unites_differentes`, `extracteurs_en_desaccord`, `renvoi_reglementaire`, `controle_signal_seulement`, `document_manquant`, `document_non_exploitable`, `plusieurs_entites`, `point_fiscal`. Chaque raison a un libellé en clair dans le gabarit (ex. `lecture_douteuse` → « à vérifier : un chiffre probablement mal lu (6 et 8 souvent confondus) expliquerait l'écart »).

#### 8.5.4 Test de confusion de lecture

Appliqué seulement si au moins une des deux valeurs a `methode` ∈ {`ocr`, `llm`} sur une page de `qualite_texte` ∈ {`ocr`, `natif_faible`}. Le test est positif si l'une des transformations suivantes, appliquée **une seule fois** à la chaîne brute de cette valeur, ramène l'écart dans la tolérance :

- substitution d'un chiffre par un autre de la même classe : {0, 6, 8, 9}, {3, 5, 8}, {1, 4, 7} ;
- substitution lettre/chiffre : O↔0, D↔0, l/I↔1, S↔5, B↔8, Z↔2, G↔6 ;
- perte ou ajout d'un zéro final (codes) ;
- interprétation inverse du séparateur décimal (facteur 100 ou 1000).

Une permutation de deux chiffres adjacents n'est **pas** considérée comme une confusion de lecture (c'est une erreur de saisie typique, donc un vrai écart).

### 8.6 Montant en jeu

| `nature_montant` | Familles | Calcul | Signe | Compté dans… |
|---|---|---|---|---|
| `recouvrable` | C, D, F3, F4, G4, G5 | Montant refacturé − montant de référence, en EUR | `> 0` = refacturé au-delà de la référence (en défaveur du client) | Totaux « montant recouvrable » |
| `ecart_documentaire` | A4, A5, A6, F5 | Valeur comparée − valeur de référence, convertie en EUR au taux imprimé de la déclaration (ou `null` si la conversion est impossible) | `> 0` = la déclaration indique plus que la facture | « Écarts de valeur entre documents » — jamais additionné aux montants recouvrables, jamais présenté comme un montant de droits |
| `arithmetique_declaration` | B1, B2, B3, G1, G2 | Montant imprimé − montant recalculé à partir des valeurs imprimées | `> 0` = montant imprimé supérieur au calcul | « Écarts de calcul sur la déclaration », avec renvoi dans la prochaine action |
| `renvoi` | A12, A13, G3, G6 | `null` | — | Liste « à faire vérifier par un professionnel » |
| `aucun` | P, A1–A3, A7–A11, A14, A15, B4, B5, C7, C8, E1–E5, F1, F2 | `null` | — | — |

Règles :

- Le montant en jeu est **signé** et en **EUR**, arrondi au centime. Un écart en faveur du client (montant refacturé inférieur à la référence) est signalé avec un montant négatif, en `a_verifier`, et n'entre jamais dans une réclamation.
- Le montant d'un constat `recouvrable` est **net des avoirs déjà imputés** au moment du contrôle ; le montant brut est conservé (`montant_brut`).
- Pas de double comptage : si C3 (TVA autoliquidée refacturée) se déclenche pour une déclaration, C4 et la part TVA de C5 sont `non_applicable` pour cette déclaration ; si C1, C2 et C4 sont tous évaluables, C5 est calculé mais son montant n'entre pas dans les totaux (`montant_en_jeu` de C5 = `null`, raison `doublon_composantes`) ; C6 n'ajoute que les frais d'avance de fonds calculés sur l'excédent.

### 8.7 Taux de change

- Le taux imprimé est lu tel quel avec son sens. Sens déterminé ainsi : si un libellé l'indique (« 1 EUR = », « EUR/USD »), on le suit ; sinon on choisit le sens qui rend le taux le plus proche du taux de référence BCE du jour d'acceptation (table locale datée `ref/taux_bce.csv`), et la valeur `taux_change_sens` a la méthode `derive` (confiance 0,85, donc jamais suffisante seule pour un `ecart_certain` qui dépendrait du sens).
- Le taux de référence ne sert **qu'à** déterminer le sens et à A7 (ordre de grandeur). Il ne sert jamais à calculer un montant en jeu.

---

## 9. Famille P — Préalables

Ces contrôles conditionnent les autres. Ils produisent des constats `a_verifier` (jamais `ecart_certain`) et n'ont jamais de montant.

| ID | Unité | Règle | Sortie |
|---|---|---|---|
| **P1** Complétude | Dossier | Le dossier contient au moins une `facture_commerciale` exploitable **et** au moins une `declaration`. | Si non : constat `a_verifier`, raison `document_manquant`, `attendu` = types manquants ; statut du dossier `document_manquant` ; les contrôles A, B (si pas de déclaration), C, G qui dépendent du document manquant sont `non_verifiable`. Une facture transitaire absente n'est pas un manque : C et D deviennent `non_applicable` avec une mention informative. |
| **P2** Document non exploitable | Document | Document intitulé facture mais reconnu comme : `pre_alerte`, `liste_reparation`, `liste_expedition`, `bon_livraison_sans_valeur`, `document_export`, `perfectionnement_passif`, `devis`, `bon_commande`, `recu`, `hors_sujet`, `illisible`, `protege`, `corrompu`. | Constat `a_verifier` avec le motif ; P1 précise « facture présente mais non exploitable : <motif> ». |
| **P3** Champ clé illisible | Document × champ clé | Un champ clé (*) a une confiance < `C_MIN_UTILE` ou est absent. | `non_verifiable` sur les contrôles dépendants, raison listée dans la section « non vérifiable » du rapport ; pas de constat. |
| **P4** Rattachement faible | Lien | Un document est lié avec `force = faible`. | Constat `a_verifier`, raison `rattachement_faible`, signaux affichés ; tous les constats qui dépendent de ce lien sont au plus `a_verifier`. |
| **P5** Dossier non concerné | Dossier | Le pavé acheteur de la facture commerciale identifie avec confiance ≥ 0,90 une entité qui n'est pas une entité du client, et la déclaration ne porte aucune TVA du client. | Statut `non_concerne` ; aucun autre contrôle n'est exécuté. |

---

## 10. Famille A — Facture commerciale contre déclaration

Unité par défaut : le couple (ensemble des factures commerciales allouées, déclaration). Quand plusieurs factures sont allouées à une déclaration, leurs totaux sont additionnés (devise identique exigée, sinon A3). Quand une facture est répartie sur plusieurs déclarations, la comparaison porte sur la somme des montants déclarés de ces déclarations contre le total facture (et sur chaque allocation explicite si elle existe).

### A1 — Entité importatrice

- **Entrées** : `acheteur.tva`, `acheteur.siren`, `acheteur.nom` (puis `destinataire.*` si l'acheteur n'identifie rien) ; `importateur.tva` ; entités du client.
- **Règle** : identifier l'entité E_f de la facture : TVA normalisée exacte, sinon SIREN imprimé (9 chiffres, même si la clé TVA est abîmée), sinon alias unique le plus spécifique. Identifier E_d de la déclaration par TVA importateur. Cas :
  - E_f = E_d, entité du client → `conforme` ;
  - E_f et E_d sont deux entités différentes du client → constat « entité du groupe différente » ;
  - E_d n'est pas une entité du client alors que E_f l'est → constat « importateur déclaré hors des entités du client » ;
  - la déclaration porte plusieurs TVA du client → `a_verifier`, raison `plusieurs_entites` ;
  - E_f illisible et E_d entité du client → `a_verifier`, raison `confiance_insuffisante` ;
  - la TVA lue sur la facture n'est pas celle du client (probablement celle du déclarant) mais E_d est l'entité du client et A4 est `conforme` → `a_verifier`.
- **Classement** : `ecart_certain` possible pour les deux premiers cas de constat si TVA lues ≥ 0,90 des deux côtés.
- **Montant** : `aucun`.
- **Preuve** : pavé acheteur (page, texte), case importateur (page, texte), fiche entité du client.
- **Formulation** : « La facture est adressée à <entité X> ; la déclaration indique comme importateur <entité Y>. » Jamais « l'importateur aurait dû être ».

### A2 — Référence de la facture citée sur la déclaration

- **Entrées** : `facture_commerciale.numero` ; `declaration.documents_references[]` de type facture/pro forma.
- **Règle** : `conforme` si une référence citée est `ref_compatibles` avec le numéro. Sinon constat.
- **Classement** : `a_verifier` uniquement (contrôle de signal ; les références sont souvent tronquées).
- **Montant** : `aucun`.

### A3 — Devise de facturation

- **Entrées** : `facture_commerciale.devise`, `declaration.devise_facture`.
- **Règle** : égales → `conforme`. Différentes et `devise_facture = EUR` → le contrôle est **délégué à A5** (montant converti) : A3 `conforme` avec raison `montant_converti` si A5 est `conforme`. Différentes dans tout autre cas → constat. Une devise illisible d'un côté → `non_verifiable` (et les comparaisons de valeur passent au mieux en `a_verifier`, raison `devise_incertaine`).
- **Classement** : `ecart_certain` possible si les deux codes ISO sont lus (pas un symbole ambigu) avec confiance ≥ 0,90 ; si les deux montants sont numériquement égaux (dans `T_VALEUR`), voir A6.
- **Montant** : `aucun`.

### A4 — Valeur facturée (même devise)

- **Entrées** : `Σ total_facture` des factures allouées ; `montant_total_facture` de la (des) déclaration(s) ; sous-totaux de pied.
- **Règle** : si devises égales, `écart = déclaré − facturé` ; `conforme` si `|écart| ≤ T_VALEUR`.
- **Classement** : `ecart_certain` si `|écart| > S_VALEUR` et règle générale. `a_verifier` avec raison `ecart_explique_par_ligne_de_pied` si `|écart|` est égal (dans `T_VALEUR`) à une ligne de pied ou à une somme de lignes de pied (fret, assurance, emballage, remise) : dans ce cas la prochaine action du constat contient la **phrase de renvoi** (le traitement de ces éléments dans la valeur relève du déclarant), le constat garde `renvoi = false` et son montant reste `ecart_documentaire` informatif. Total facture `reconstruit` et inférieur au déclaré → `a_verifier`, raison `total_reconstruit`.
- **Montant** : `ecart_documentaire` = `écart` converti en EUR (taux imprimé) ; `null` si devise non EUR et taux absent.
- **Preuve** : total facture (page, texte), montant déclaré (page, texte), tolérance.
- **Formulation** : « Le montant total facturé indiqué sur la déclaration (X) diffère du total de la facture commerciale (Y) de Z. » Jamais « valeur en douane ».

### A5 — Montant converti au taux imprimé

- **Entrées** : total facture en devise D ≠ EUR ; montant déclaré en EUR ; `taux_change` et son sens.
- **Règle** : `attendu = total_facture × taux (EUR par unité de D)` arrondi au centime ; `écart = déclaré_EUR − attendu` ; `conforme` si `|écart| ≤ T_CONVERSION`. Taux absent → A7.
- **Classement** : `ecart_certain` si `|écart| > S_CONVERSION`, sens du taux lu (non dérivé) ou écart supérieur dans les deux sens, et règle générale.
- **Montant** : `ecart_documentaire` = `écart` (déjà en EUR).

### A6 — Montant repris sans conversion

- **Entrées** : total facture (devise D ≠ EUR), montant déclaré, devise déclarée.
- **Règle** : constat si la déclaration indique `EUR` et que `|déclaré − total_facture| ≤ T_VALEUR` (même nombre, devises différentes) alors qu'un taux imprimé différent de 1 (écart > 2 %) figure sur la déclaration ou que le taux de référence de D s'écarte de 1 de plus de 10 %.
- **Classement** : `ecart_certain` si la devise de la facture vient d'un code ISO lu avec confiance ≥ 0,95 (ou d'un XML) et si le taux imprimé est lu ; sinon `a_verifier`, raison `devise_incertaine` (la devise de la facture a pu être mal lue).
- **Montant** : `ecart_documentaire` = `déclaré − total_facture × taux_imprimé` si taux imprimé ; sinon `null`.
- **Note** : A5 n'est pas exécuté quand A6 se déclenche (pas de double constat).

### A7 — Ordre de grandeur au taux indicatif

- **Entrées** : total facture en D ≠ EUR, montant déclaré en EUR, **sans taux imprimé**.
- **Règle** : `ratio = déclaré / (total_facture × taux_BCE(date_acceptation))` ; constat si `ratio` hors de `1 ± BANDE_INDICATIVE`.
- **Classement** : `a_verifier` uniquement. **Montant** : `null` (aucun montant calculé au taux indicatif).

### A8 — Incoterm

- **Règle** : codes à 3 lettres égaux → `conforme` ; différents → constat ; lieu non comparé ; un côté illisible → `non_verifiable`.
- **Classement** : `a_verifier` uniquement, avec la phrase de renvoi (l'effet sur la valeur relève du déclarant). **Montant** : `aucun`.

### A9 — Quantités

- **Unité** : couple (ligne de facture, article de déclaration) rapproché par code SH6 commun, sinon total.
- **Règle** : comparé seulement si les unités normalisées sont identiques ; sinon `non_verifiable`, raison `unites_differentes`. Constat si `|écart| > T_QUANTITE`.
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

### A10 — Masses

- **Entrées** : masses nette et brute totales de la facture, ou à défaut de la liste de colisage ou du titre de transport ; masses de la déclaration.
- **Règle** : constat si `|écart| > T_MASSE`, pour la nette et pour la brute séparément.
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

### A11 — Nombre de colis

- **Règle** : nombre de colis (facture, liste de colisage ou titre de transport) contre total déclaré ; exact.
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

### A12 — Pays d'origine imprimés (signal + renvoi)

- **Unité** : couple (ligne de facture, article) rapproché par SH6 ; à défaut, ensemble des origines.
- **Règle** : constat si le pays d'origine imprimé sur la ligne de facture diffère de celui de l'article rapproché. L'origine préférentielle et le code de préférence ne sont **jamais** comparés à un droit ; ils sont seulement affichés.
- **Classement** : `a_verifier`, `renvoi = true`, phrase de renvoi. **Montant** : `null`.
- **Formulation** : « Le pays d'origine imprimé sur la facture (CN) diffère de celui indiqué sur l'article 2 de la déclaration (VN). » + phrase de renvoi.

### A13 — Codes marchandise imprimés (signal + renvoi)

- **Entrées** : `code_marchandise_imprime` des lignes de facture ; `code_marchandise` des articles.
- **Règle** : normaliser (chiffres seuls) ; comparer à 6 chiffres. Pour chaque code SH6 de la facture absent de la déclaration : constat ; si un code SH6 de la déclaration diffère de 1 ou 2 chiffres d'une même classe de confusion → raison `lecture_douteuse`. Réciproquement, les articles dont le SH6 n'apparaît sur aucune ligne de facture sont listés dans le même constat. Facture sans aucun code → `non_verifiable` (« la facture ne porte pas de code »), jamais un écart.
- **Classement** : `a_verifier` uniquement, `renvoi = true`. **Montant** : `null`.
- **Interdit** : dire quel code est correct ; filtrer ou valider les codes contre une nomenclature ; calculer un droit à partir d'un code.

### A14 — Chronologie des dates

- **Règle** : constat si `date_acceptation` de la déclaration est antérieure à la date de la facture commerciale de plus de 1 jour (une pro forma est exclue).
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

### A15 — Références produit (signal)

- **Règle** : pour chaque `reference_article` de la facture (≥ 4 caractères), rechercher sa présence (normalisée) dans les désignations des articles. Constat listant les références introuvables, seulement si **toutes** les désignations de la déclaration contiennent au moins une référence d'article (sinon le déclarant n'a manifestement pas l'usage de les reprendre : `non_applicable`).
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

---

## 11. Famille B — Cohérence interne de la déclaration

La famille B vérifie que les chiffres imprimés sur la déclaration sont cohérents entre eux. Elle **ne juge jamais un taux**, une base ou un code : elle prend les valeurs imprimées comme données. La prochaine action de chaque constat B contient : « Demander au déclarant l'explication de cet écart de calcul. » suivie de la phrase de renvoi si une rectification est envisagée.

### B1 — Base × taux = montant (par ligne de taxation)

- **Unité** : ligne de taxation, hors forfait petits envois (traité par G1).
- **Règle** : si `taux_nature = ad_valorem` : `calcul = base_montant × taux / 100` ; si `specifique` : `calcul = base_quantite × taux`. `conforme` si `|montant − calcul| ≤ 0,01` ou si `montant ∈ {⌊calcul⌋, ⌈calcul⌉, arrondi(calcul, 0)}` (`T_TAXE_LIGNE`). Taux ou base absent → `non_verifiable`.
- **Classement** : `ecart_certain` si `|écart| > 1,00 EUR` et règle générale ; sinon `a_verifier`.
- **Montant** : `arithmetique_declaration` = `montant − calcul`.
- **Preuve** : base, taux, montant (page, texte) et le calcul affiché.
- **Formulation** : « Sur l'article 3, le montant imprimé pour la taxe A00 (418,20 EUR) diffère du produit base × taux imprimés (2 091,00 × 2,5 % = 52,28 EUR). » Jamais « le taux est erroné ».

### B2 — Sommes des taxes

- **Règle** : (a) pour chaque catégorie, `Σ montants par article` contre total imprimé de la catégorie, s'il existe ; (b) `Σ toutes catégories payables` contre `total_droits_taxes` (DE 14 16) ou `total_a_payer`. Tolérance `T_SOMME` (n = nombre de lignes sommées). La TVA autoliquidée est incluse ou exclue selon que le total imprimé l'inclut : les deux hypothèses sont testées, `conforme` si l'une concorde.
- **Classement** : `ecart_certain` si `|écart| > 1,00 EUR`, tous les articles lus (nombre d'articles lus = `nombre_articles` imprimé) et règle générale ; sinon `a_verifier` (une ligne non extraite est l'explication la plus fréquente).
- **Montant** : `arithmetique_declaration` = total imprimé − somme.

### B3 — Somme des montants facturés des articles

- **Règle** : `Σ montant_facture_article` contre `montant_total_facture`, même devise, `T_SOMME`.
- **Classement** : comme B2. **Montant** : `arithmetique_declaration`.

### B4 — Masses

- **Règle** : (a) pour chaque article et au total, `masse_nette ≤ masse_brute + T_MASSE` ; (b) `Σ masse_brute articles` contre `masse_brute_totale`, tolérance `T_MASSE`.
- **Classement** : (a) `ecart_certain` possible ; (b) `a_verifier` uniquement. **Montant** : `aucun`.

### B5 — Colis

- **Règle** : `Σ nombre_colis articles` contre `nombre_colis_total` (exact), quand les deux existent.
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

---

## 12. Famille C — Facture du transitaire contre déclaration

Contrôles au cœur du recouvrement. La déclaration est la **référence** : ses montants sont pris tels qu'imprimés, jamais recalculés à partir des taux.

### 12.1 Montants de référence par déclaration

Pour chaque déclaration `d` (dernière version de son préfixe MRN) et chaque catégorie `k` ∈ {`droit`, `autre_taxe`, `tva`, `forfait_petits_envois`} :

- `liquide[d][k]` = Σ `montant_a_payer` (à défaut `montant`) des lignes de taxation de catégorie `k` dont `paiement_normalise` ≠ `autoliquide`.
- `autoliquide[d]` = vrai si au moins un indice d'autoliquidation lu avec confiance ≥ 0,90 porte sur la TVA de `d` (code 1008 + TVA, référence FR7, ou mode de paiement de la ligne TVA normalisé `autoliquide`). Si `autoliquide[d]`, alors `liquide[d][tva] = 0` pour la comparaison.
- `liquide_total[d]` = Σ_k `liquide[d][k]`. **Règle de complétude** : si `total_a_payer` imprimé est supérieur à cette somme de plus de `T_SOMME` et que la différence correspond à une composante non extraite, `liquide_total[d] = total_a_payer` et les comparaisons par composante concernées passent en `non_verifiable` (seul C5 s'exécute).

### 12.2 Montants refacturés

Pour une facture transitaire `f` et une déclaration `d` rattachée : `refacture[f][d][k]` = Σ des lignes de débours de nature correspondante qui citent le MRN de `d`. Si les lignes ne citent pas de MRN et que `f` ne couvre qu'une déclaration du dossier, toutes ses lignes de débours lui sont affectées ; si `f` couvre plusieurs déclarations sans ventilation, la comparaison se fait sur la **somme** des déclarations couvertes (unité = `f`), et le constat cite tous les MRN. Une facture initiale et une facture complémentaire pour le même MRN sont additionnées. Les avoirs déjà imputés sont déduits (§17.2).

### C1 — Droits de douane refacturés

- **Unité** : (facture transitaire, déclaration) ou (facture transitaire, ensemble des déclarations) selon §12.2.
- **Règle** : `écart = refacture[droit] − liquide[droit]` ; `conforme` si `|écart| ≤ T_DEBOURS`.
- **Classement** : `ecart_certain` si `|écart| > S_DEBOURS` et règle générale ; montant négatif (refacturé inférieur) → toujours `a_verifier`.
- **Montant** : `recouvrable` = `écart`.
- **Preuve** : chaque ligne de débours (page, texte), chaque ligne de taxation sommée (article, page, texte), le calcul.

### C2 — Autres taxes refacturées

Identique à C1 pour `autre_taxe`.

### C3 — TVA à l'importation refacturée alors que la déclaration indique l'autoliquidation

- **Règle** : `autoliquide[d] = vrai` et `refacture[tva] > T_DEBOURS` → constat.
- **Classement** : `ecart_certain` si l'indice d'autoliquidation et la ligne de TVA refacturée sont lus avec confiance ≥ 0,90 et règle générale ; sinon `a_verifier`. Le texte constate la contradiction entre les deux documents ; il ne dit pas si l'autoliquidation était applicable.
- **Montant** : `recouvrable` = `refacture[tva]`.
- **Formulation** : « La facture du transitaire refacture 1 240,00 EUR de TVA à l'importation ; pour cette déclaration, la TVA est indiquée comme autoliquidée (code document 1008 suivi du numéro FR…, page 1). »

### C4 — TVA à l'importation refacturée (payée en douane)

- **Règle** : si `autoliquide[d] = faux` : `écart = refacture[tva] − liquide[tva]`, comme C1.
- **Classement, montant** : comme C1.

### C5 — Total des débours

- **Règle** : `écart = Σ_k refacture[k] − liquide_total` (débours combinés inclus). Exécuté toujours ; seul porteur du montant quand le transitaire ne donne qu'un montant combiné ou quand une composante de la déclaration est `non_verifiable`.
- **Classement** : comme C1.
- **Montant** : `recouvrable` = `écart`, **sauf** si C1, C2 et C3/C4 sont tous évaluables (montant `null`, raison `doublon_composantes`, §8.6).

### C6 — Frais d'avance de fonds calculés sur des débours en écart

- **Entrées** : ligne `frais_avance_fonds` ; taux du FAF (grille validée, sinon pourcentage imprimé sur la ligne) ; excédent de débours constaté par C1–C5 (positif uniquement).
- **Règle** : `excedent_faf = arrondi(taux × excédent_débours)` borné par la grille (si le FAF facturé est au minimum de la grille, l'excédent est 0). Constat si `excedent_faf > T_TARIF`.
- **Classement** : `ecart_certain` seulement si le constat de débours dont il dépend est `ecart_certain` et le taux est connu (grille validée ou taux imprimé lu ≥ 0,90) ; sinon `a_verifier`.
- **Montant** : `recouvrable` = `excedent_faf`. Si D4 constate aussi un écart sur le même FAF, D4 est calculé sur l'assiette **corrigée** pour éviter tout double comptage.

### C7 — Références de la facture transitaire

- **Règle** : chaque MRN cité sur la facture transitaire doit correspondre (préfixe) à une déclaration du dossier ; chaque référence de transport citée doit être `ref_compatibles` avec celle de la déclaration ou de la facture commerciale. Constat listant les références sans correspondance.
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

### C8 — Client facturé

- **Règle** : `client_facture.tva` (ou nom/alias) contre l'entité importatrice du dossier (A1). Constat si le transitaire a facturé une autre entité (du groupe ou extérieure).
- **Classement** : `ecart_certain` possible si les deux TVA sont lues ≥ 0,90 ; sinon `a_verifier`. **Montant** : `aucun`.

---

## 13. Famille D — Facture du transitaire contre grille tarifaire ou devis

D1 s'exécute toujours. D2 à D9 exigent une grille `validee`, valide à la date de la facture, pour le transitaire émetteur ; sinon ils sont `non_applicable` avec la mention « aucune grille tarifaire validée pour ce transitaire ».

Rapprochement ligne ↔ poste de grille : par `nature` puis par libellé normalisé contenu dans `libelles_reconnus[]`. Une ligne qui correspond à plusieurs postes est `a_verifier` (raison `confiance_insuffisante`).

### D1 — Arithmétique interne de la facture transitaire

- **Règles** (chacune produit son propre résultat, référencé `D1` avec un `sous_controle`) :
  - `ligne` : `quantite × prix_unitaire = montant_ht` (`T_LIGNE`) ;
  - `tva_ligne` : `montant_ht × taux_tva = montant_tva` (`T_LIGNE`) ;
  - `total_debours` : Σ lignes de débours = total des débours imprimé (`T_SOMME`) ;
  - `total_ht` : Σ montants HT (débours + prestations, selon la présentation) = total HT imprimé (`T_SOMME`) ;
  - `total_ttc` : total HT + total TVA = total TTC (`T_SOMME`) ;
  - `net_a_payer` : TTC − acomptes imprimés = net à payer.
- **Classement** : `ecart_certain` si `écart > S_ARITH` et règle générale ; sinon `a_verifier`.
- **Montant** : `recouvrable` = total imprimé − total recalculé, seulement pour les sous-contrôles `total_*` et `net_a_payer` quand l'écart est positif (le client paie plus que la somme des lignes) ; `null` sinon.

### D2 — Ligne hors grille

- **Règle** : ligne de prestation sans poste correspondant dans la grille.
- **Classement** : si `prestations_hors_grille = interdites` → `ecart_certain` possible (libellé et montant lus ≥ 0,90) ; si `tolerees` → `a_verifier`.
- **Montant** : `recouvrable` = montant HT de la ligne (et la TVA correspondante en `montant_tva_associee`, informative).

### D3 — Prix supérieur à la grille

- **Règle** : `forfait` : `écart = montant_ht − prix` ; `unitaire` : `écart = montant_ht − quantite × prix` ; constat si `écart > T_TARIF`.
- **Classement** : `ecart_certain` si `écart > S_TARIF` et règle générale. Écart négatif : `conforme` (pas de constat).
- **Montant** : `recouvrable` = `écart`.

### D4 — Frais d'avance de fonds contre la grille

- **Règle** : `attendu = clamp(arrondi(pourcentage × assiette), minimum, maximum)` où `assiette` est, selon `base_pourcentage`, la somme des débours refacturés **retenus** (débours facturés moins excédents constatés par C) ; `écart = facturé − attendu` ; constat si `écart > T_TARIF`.
- **Classement, montant** : comme D3.

### D5 — Ligne en double dans une même facture

- **Règle** : deux lignes de même `nature`, même libellé normalisé, même montant, même MRN ou référence de transport (ou aucune), sur la même facture.
- **Classement** : `ecart_certain` si toutes ces valeurs sont lues ≥ 0,90 et que la grille ne prévoit pas de quantité multiple pour ce poste ; sinon `a_verifier`.
- **Montant** : `recouvrable` = montant de la ligne en double (une occurrence).

### D6 — Magasinage

- **Règle** : `jours_factures` = quantité facturée (ou `date_fin − date_debut + 1`) ; `jours_attendus = max(0, (date_fin − date_debut + 1) − franchise_jours)` ; `attendu = jours_attendus × prix` ; `écart = facturé − attendu`.
- **Classement** : `ecart_certain` si dates et prix lus ≥ 0,90 et `écart > S_TARIF` ; sinon `a_verifier`.
- **Montant** : `recouvrable` = `écart`.

### D7 — Surcharges

- **Règle** : surcharge sans poste → comme D2 ; surcharge en pourcentage → `attendu = pourcentage_grille × base_grille` ; comme D3.
- **Classement, montant** : comme D2/D3.

### D8 — TVA facturée sur une ligne de débours

- **Règle** : une ligne de nature `debours_*` porte un `montant_tva > 0`.
- **Classement** : `a_verifier` uniquement, raison `point_fiscal` ; prochaine action : « faire confirmer le traitement de TVA par votre expert-comptable ».
- **Montant** : `recouvrable` = `montant_tva` de la ligne (affiché comme « montant de TVA facturé sur un débours », non additionné aux totaux certains).

### D9 — Lignes supplémentaires

- **Règle** : poste `frais_ligne_supplementaire` de mode `unitaire` avec `unite_base = article` et un nombre d'articles inclus `n_inclus` (champ `inclus` du poste) ; `attendu_qte = max(0, nombre_articles_declaration − n_inclus)` ; `écart = (qte_facturee − attendu_qte) × prix`.
- **Classement** : `ecart_certain` si le nombre d'articles est lu sur une déclaration structurée ou ≥ 0,90 et `écart > S_TARIF` ; sinon `a_verifier`.
- **Montant** : `recouvrable` = `écart` si positif.

---

## 14. Famille E — Avoirs

### E1 — Rattachement de l'avoir

- **Règle** : l'avoir cite une facture d'origine trouvée chez le même émetteur (`ref_compatibles`) → `conforme`. Sinon, rattachement par MRN ou référence de transport → `a_verifier` (raison `rattachement_faible`) ; aucun rattachement → `a_verifier` « avoir non rattaché ».
- **Montant** : `aucun`.

### E2 — Avoir supérieur à l'origine

- **Règle** : pour chaque nature, `Σ avoirs imputés ≤ montant facturé d'origine + T_SOMME`. Sinon constat.
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

### E3 — Avoir reçu deux fois

- **Règle** : deux documents `avoir` de même émetteur et même `norm_ref(numero)`, ou de même montant total et même facture d'origine à moins de 7 jours d'écart. Le second n'est pas imputé.
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

### E4 — Arithmétique interne de l'avoir

Mêmes sous-contrôles que D1. **Montant** : `aucun` (un avoir mal additionné est signalé, pas réclamé).

### E5 — Avoir sans écart ouvert correspondant

- **Règle** : après imputation (§17.2), un reliquat d'avoir > `T_SOMME` ne correspond à aucun écart ouvert.
- **Classement** : `a_verifier` uniquement (information : l'avoir peut régler un sujet non détecté). **Montant** : `aucun`.

### E6 — Avoir partiel

- **Règle** : un écart réclamé n'est couvert que partiellement par les avoirs imputés ; reste à recouvrer > `T_DEBOURS`.
- **Classement** : `a_verifier` (sert la relance). **Montant** : `recouvrable` = reste à recouvrer (ce constat **remplace** le montant de l'écart d'origine dans les totaux, il ne s'y ajoute pas).

---

## 15. Famille F — Doublons entre dossiers

Fenêtre de recherche : tous les dossiers du **même client** sur 24 mois glissants (paramètre). Jamais entre clients.

### F1 — Document en double

- **Règle** : même `sha256` de fichier, ou même `identite` de document, présent dans deux dossiers ou deux fois dans un dossier. Le doublon est écarté des contrôles (une seule occurrence comptée).
- **Classement** : `a_verifier` (information). **Montant** : `aucun`.

### F2 — Numéro de facture transitaire réutilisé

- **Règle** : même émetteur, même `norm_ref(numero)`, contenus différents (montant total différent de plus de `T_SOMME`).
- **Classement** : `a_verifier` uniquement. **Montant** : `aucun`.

### F3 — Même déclaration refacturée deux fois

- **Règle** : deux factures transitaires **distinctes** (numéros différents) refacturent des débours pour le même `mrn_prefixe` ; aucun avoir n'annule l'une d'elles ; la seconde n'est pas une facture complémentaire (une facture complémentaire porte des montants qui, additionnés à la première, égalent `liquide_total` dans `T_DEBOURS` : dans ce cas `conforme`).
- **Classement** : `ecart_certain` si le MRN est lu ≥ 0,90 sur les deux factures, que les débours des deux sont égaux dans `T_DEBOURS` et `> S_DEBOURS` ; sinon `a_verifier`.
- **Montant** : `recouvrable` = débours de la facture la plus récente (date, puis numéro) pour ce MRN. Le constat est porté par le dossier de la facture la plus récente et cite l'autre dossier.
- **Interaction** : C5 sur le dossier concerné compte déjà l'excédent si les deux factures sont dans le même dossier ; dans ce cas F3 est `non_applicable` (pas de double comptage).

### F4 — Même prestation facturée deux fois

- **Règle** : deux factures distinctes du même émetteur portent une ligne de prestation de même `nature`, même référence de transport ou MRN, même montant.
- **Classement** : `a_verifier` uniquement (une prestation peut légitimement se répéter). **Montant** : `recouvrable` = montant de la ligne la plus récente.

### F5 — Même facture commerciale sur plusieurs déclarations

- **Règle** : une facture commerciale (même émetteur, même `norm_ref(numero)`) est citée par plusieurs déclarations de MRN de préfixes différents et `Σ montants déclarés > total_facture + T_VALEUR`.
- **Classement** : `a_verifier` uniquement (envois partiels possibles). **Montant** : `ecart_documentaire` = somme déclarée − total facture, en EUR si convertible, sinon `null`.

---

## 16. Famille G — Petits envois (droit forfaitaire par article)

Contexte : un droit de douane forfaitaire par article (3 EUR par article à la date de rédaction) s'applique à certains envois de faible valeur depuis le 1er juillet 2026, jusqu'au 1er juillet 2028. Un « article » est défini par le classement tarifaire, pas par la quantité. Le produit **ne décide pas** si ce droit s'applique, ni combien d'articles il aurait fallu retenir : il vérifie la **cohérence des nombres imprimés**.

**Détection** : une ligne de taxation est de catégorie `forfait_petits_envois` si son code de type de taxe figure dans la liste configurable `codes_forfait_petits_envois` ou si son libellé correspond à `libelles_forfait_petits_envois`. Le montant unitaire de référence (`3,00 EUR`) est un paramètre daté (`forfait_unitaire[date]`) utilisé **uniquement** pour reconnaître la ligne quand le taux n'est pas imprimé ; tout calcul utilise le taux imprimé s'il existe.

### G1 — Nombre d'articles × montant unitaire = montant du forfait

- **Règle** : `calcul = base_quantite (nombre d'articles imprimé) × taux imprimé` ; comparé au montant imprimé, tolérance 0,01 EUR.
- **Classement** : `ecart_certain` si `|écart| > 1,00 EUR` et règle générale. **Montant** : `arithmetique_declaration`.

### G2 — Base du forfait contre nombre d'articles de la déclaration

- **Règle** : `base_quantite` imprimée sur la ligne de forfait contre le nombre d'articles (positions) de la déclaration (`nombre_articles` imprimé, ou nombre de blocs articles si égal). Exact.
- **Classement** : `ecart_certain` si les deux nombres sont lus ≥ 0,90 (ou déclaration structurée) ; sinon `a_verifier`.
- **Montant** : `arithmetique_declaration` = `(base_quantite − nombre_articles) × taux imprimé`, avec renvoi dans la prochaine action.

### G3 — Base du forfait contre codes marchandise distincts (signal + renvoi)

- **Règle** : nombre de codes marchandise distincts (à 10 chiffres, puis à 6 chiffres) des articles de la déclaration contre `base_quantite` ; constat si la base diffère des deux comptages.
- **Classement** : `a_verifier` uniquement, `renvoi = true` (la granularité de l'« article » relève de l'appréciation réglementaire). **Montant** : `null`.

### G4 — Forfait refacturé contre forfait liquidé

- **Règle** : comme C1 pour la catégorie `forfait_petits_envois` (lignes `debours_forfait_petits_envois` de la facture transitaire, ou ligne de droits si le transitaire ne distingue pas et que la déclaration ne porte que ce droit).
- **Classement, montant** : comme C1 (`recouvrable`).

### G5 — Base de refacturation du transitaire

- **Règle** : si la ligne du transitaire imprime une base (ex. « 3,00 × 5 »), `écart = (n_transitaire − base_quantite_declaree) × montant unitaire refacturé`. Typiquement : le transitaire a compté des unités au lieu d'articles.
- **Classement** : `ecart_certain` si les deux nombres sont lus ≥ 0,90 et `écart > S_DEBOURS` ; sinon `a_verifier`.
- **Montant** : `recouvrable` = `écart`. Si G4 constate le même excédent, G4 porte le montant et G5 a `montant_en_jeu = null` (raison `doublon_composantes`).

### G6 — Applicabilité (renvoi seulement)

- **Règle** : une ligne de forfait figure sur une déclaration acceptée avant la date de début ou après la date de fin configurées, ou le montant facturé total de l'envoi dépasse le seuil configuré (150 EUR) converti au taux imprimé.
- **Classement** : `a_verifier`, `renvoi = true`. **Montant** : `null`. Le texte constate les valeurs lues et renvoie au professionnel ; il ne dit pas que le forfait était ou non dû.

---

## 17. Suivi du recouvrement

### 17.1 Écart à recouvrer et réclamation

- Un **écart à recouvrer** naît de chaque constat validé de `nature_montant = recouvrable` et de montant positif. Il porte : `constat_id`, `transitaire_id`, `facture_transitaire_id`, `mrn`, `composante` (`droit`, `autre_taxe`, `tva`, `forfait_petits_envois`, `prestation`), `montant_initial`, `montant_credite`, `reste`, `statut`.
- Une **réclamation** regroupe des écarts d'un même transitaire (par défaut : un dossier, ou un lot de dossiers au choix du client).

Statuts (transitions autorisées) :

```
ouvert ──> reclame ──> partiellement_credite ──> credite
   │          │                 │
   │          ├──> conteste ────┤ (le transitaire refuse ; reste ouvert à la relance)
   └──────────┴─────────────────┴──> abandonne (motif obligatoire)
```

Chaque transition est un `EvenementRecouvrement` append-only : `{ecart_id, de, vers, le, auteur, piece (avoir_id, courriel…), montant, commentaire}`. Le passage à `reclame` est déclaré par l'utilisateur client (c'est lui qui envoie). Âge d'un écart = jours depuis `reclame` ; relance suggérée à 30, 60 et 90 jours.

### 17.2 Imputation des avoirs (déterministe)

Pour chaque avoir rattaché (E1), lignes triées par nature :

1. Écarts candidats : même émetteur, même facture d'origine (ou, à défaut, même MRN, puis même référence de transport), même composante (`debours_droits` → `droit`, etc. ; toute nature `frais_*`, `magasinage`, `surcharge`, `autre_prestation` → `prestation`), statut ∈ {`reclame`, `partiellement_credite`, `conteste`, `ouvert`}.
2. Ordre : `reclame` avant `ouvert`, puis date de constat croissante, puis `constat_id`.
3. Imputer au centime : `impute = min(reste_avoir, reste_ecart)`. Mettre à jour `reste`, puis le statut (`credite` si `reste ≤ T_DEBOURS`, sinon `partiellement_credite`).
4. Ligne d'avoir combinée (« droits et taxes ») : imputer sur les écarts de composante `droit`, `autre_taxe`, `tva`, `forfait_petits_envois` dans cet ordre.
5. Reliquat d'avoir : E5. Le fondateur peut corriger une imputation (événement `Correction`).

### 17.3 Dossier de réclamation (rédigé pour le client)

Généré en PDF et en texte prêt à coller dans un e-mail, **modifiable par le client avant envoi**. Contenu :

1. En-tête : coordonnées de l'**entité du client** (expéditeur), transitaire destinataire, objet « Demande d'avoir — factures n° … ».
2. Corps à la première personne du client (« Nous avons constaté… », « Nous vous remercions de bien vouloir émettre un avoir… »), sans mention du prestataire, sans signature autre que celle à compléter par le client.
3. Tableau des écarts : facture, MRN, composante, montant refacturé, montant de référence (avec le document de référence), écart.
4. Pièces : pour chaque écart, extraits de page côte à côte (rognages) et calcul.
5. Total demandé = Σ écarts validés `ecart_certain` du transitaire. Les écarts `a_verifier` n'y figurent que si le client les coche explicitement, avec la mention « à confirmer ».
6. Rien sur la légalité, aucun délai légal, aucune menace, aucune expression interdite (§3.2).

Le fondateur valide chaque dossier de réclamation avant mise à disposition. Le système **n'envoie jamais** lui-même de réclamation au transitaire.

### 17.4 Base de commission

`base_commission(période) = Σ montants imputés (§17.2) sur des écarts issus de constats validés`, par client. La facturation elle-même relève du module de facturation (hors de cette spécification).

---

## 18. Rapport de diagnostic

### 18.1 Formats

- **Web** (pages serveur, lisibles sans JavaScript) ; **PDF** (même contenu, numéroté, horodaté) ; **JSON** (`controldone.rapport/1.x`, source de vérité de l'interface, Annexe C) ; **tableur** (onglets : synthèse, dossiers, constats, contrôles, documents, non lus, méthode, avec colonnes vides de revue humaine).
- Le rapport est figé sur un ensemble `(dossier_id, dossier_version)` et une `execution_id`.

### 18.2 Statut global d'un dossier

Ordre de priorité (le premier qui s'applique) : `non_concerne` (P5) > `document_manquant` (P1) > `ecart_certain` (au moins un constat validé de ce niveau) > `a_verifier` > `conforme` (tous les contrôles exécutés sont `conforme`, `non_applicable` ou `non_verifiable` non bloquant). Un dossier dont un contrôle C ou A4/A5 est `non_verifiable` ne peut pas être `conforme` : il est `a_verifier` avec la raison « contrôle non réalisable ».

### 18.3 Structure

1. **Page de garde** : client, période couverte, nombre de dossiers, date, versions.
2. **Synthèse** :
   - nombre de dossiers par statut ;
   - **montant recouvrable certain** (Σ `recouvrable` des constats `ecart_certain` validés, nets d'avoirs) ;
   - **montant recouvrable à vérifier** (Σ `recouvrable` positifs des constats `a_verifier`), affiché séparément, jamais additionné au précédent ;
   - répartition par composante (droits, autres taxes, TVA, forfait petits envois, prestations), par transitaire, par mois de facture ;
   - écarts de valeur entre documents (A4–A6, F5) en nombre et en montant absolu, à part ;
   - nombre de points à faire vérifier par un professionnel.
3. **Prochaines actions** classées : P1 envoyer les réclamations prêtes (par transitaire, montant) ; P2 lever les points à vérifier (liste) ; P3 transmettre les points réglementaires à un RDE ou un avocat ; P4 compléter les documents manquants.
4. **Tableau des dossiers** : une ligne par dossier ; clés dans l'ordre fixe (facture transitaire, transport, MRN, facture commerciale), TVA acheteur et importateur, montant facturé et montant déclaré avec devises, statut, raisons en une ligne, montant recouvrable.
5. **Fiche dossier** : documents (type, fichier, pages, confiance) ; liens et signaux ; constats avec, pour chacun, la valeur A et la valeur B **côte à côte** (rognage de page + texte lu + page), le calcul, la tolérance, le niveau, la raison, le montant en jeu, la prochaine action ; tableau des contrôles exécutés (attendu, constaté, résultat) ; lignes de facture et articles de déclaration côte à côte (rapprochés par SH6) ; état du recouvrement.
6. **Points à faire vérifier par un professionnel** : notes de renvoi, avec la phrase de renvoi, sans montant.
7. **Documents non lus ou non reconnus** : fichier, motif.
8. **Méthode** : tolérances appliquées (profil et empreinte), versions moteur/règles/extracteurs, modèle utilisé, limites.
9. **Avertissement** (§3.4).

---

## 19. Banc d'évaluation

### 19.1 Principe et séparation des équipes

- Le **générateur** (écrit par un agent qui ne voit ni le code d'extraction ni le code des contrôles) produit des dossiers synthétiques fictifs avec erreurs injectées connues, à partir de cette seule spécification.
- L'**équipe extraction/contrôles** ne voit ni le code du générateur ni le split `holdout`.
- Le **correcteur** (`bench/score`) compare les constats produits aux vérités. Il est écrit à partir de cette section et testé sur des cas jouets.
- Tout est fictif : noms d'entreprises inventés, adresses inventées, SIREN commençant par `000` et valides au sens de Luhn, numéros de TVA FR calculés à partir de ces SIREN (clé = `(12 + 3 × (SIREN mod 97)) mod 97`), EORI `FR` + SIREN + `00000`, MRN au format `AAFR` + 14 caractères alphanumériques aléatoires. Aucun nom de transitaire ou de logiciel réel.

### 19.2 Arborescence

```
bench/
  corpus/
    clients/<client_id>/profil.json          # entrées du système : entités, transitaires, tolérances
    clients/<client_id>/grilles/<grille_id>.json   # grilles tarifaires validées (§6.2.4)
    dev/<dossier_id>/truth.json              # vérité (lue seulement par le correcteur)
    dev/<dossier_id>/docs/...                # fichiers d'entrée, arborescence éventuelle
    holdout/<dossier_id>/truth.json
    holdout/<dossier_id>/docs/...
    manifest.json                            # liste des dossiers, split, seed, version du générateur, sha256 de chaque fichier
  out/<run_id>/<dossier_id>/findings.json    # sortie du système (Annexe C)
  out/<run_id>/metrics.json                  # sortie du correcteur
```

- `dossier_id` : `BX` + 4 chiffres (`BX0001`). `client_id` : `CL` + 2 chiffres.
- **Split** : `holdout` si `int(sha256(dossier_id)[0:8], 16) mod 5 == 0`, sinon `dev` (≈ 20 %). Le split est déterministe et figé dans `manifest.json`.
- Le système reçoit, pour chaque client, `profil.json`, les grilles et l'ensemble des dossiers `docs/` du split ; il traite chaque dossier comme un **lot** dont l'arborescence `docs/` est la frontière de regroupement. Les contrôles F voient tous les dossiers du même client dans le split.
- `profil.json` : `{"schema": "controldone.bench.profil/1.0.0", "client_id", "entites": [{"raison_sociale", "tva", "siren", "eori", "alias": []}], "transitaires": [{"transitaire_id", "nom", "tva", "alias": []}], "tolerances": {} (vide = défauts)}`.
- Génération reproductible : même `seed` + même version de générateur ⇒ fichiers identiques octet pour octet (PDF générés sans horodatage variable).

### 19.3 Contrat `truth.json`

Schéma complet en Annexe B. Champs :

```json
{
  "schema": "controldone.bench.truth/1.0.0",
  "dossier_id": "BX0042",
  "split": "dev",
  "client_id": "CL03",
  "generator_version": "1.2.0",
  "seed": 424242,
  "transitaire_template": "T3",
  "declaration_layout": "L2",
  "degradation": "d2",
  "scenario_tags": ["multi_declarations", "pdf_fusionne", "autoliquidation"],
  "files": [
    {"path": "docs/expedition_77/envoi.pdf", "sha256": "…", "pages": 6}
  ],
  "documents": [
    {
      "doc_id": "fc1",
      "type": "facture_commerciale",
      "sous_type": "facture",
      "format": "pdf_scan",
      "degradation": "d2",
      "file": "docs/expedition_77/envoi.pdf",
      "pages": [1, 2],
      "transitaire_template": null,
      "language": "en"
    }
  ],
  "truth_values": {
    "fc1": {
      "numero": "INV-2026-0815",
      "date": "2026-08-14",
      "devise": "USD",
      "total_facture": "12540.00",
      "total_imprime": true,
      "acheteur.tva": "FR32000123459",
      "incoterm": "FOB",
      "lignes": [
        {"code_marchandise_imprime": "8471.30", "quantite": "10", "unite": "C62", "montant_ligne": "12540.00", "pays_origine": "CN"}
      ]
    }
  },
  "expected_links": [
    {"from": "fc1", "to": "dec1", "role": "declaration"},
    {"from": "ft1", "to": "dec1", "role": "facture_transitaire"}
  ],
  "injected_errors": [
    {
      "error_id": "BX0042-E1",
      "control_id": "C3",
      "accepted_control_ids": ["C3"],
      "expected_level": "ecart_certain",
      "expected_amount_eur": "2508.00",
      "amount_nature": "recouvrable",
      "composante": "tva",
      "documents": ["ft1", "dec1"],
      "fields": ["ft1.lignes[2].montant_ht", "dec1.indices_autoliquidation"],
      "injection": "tva_refacturee_malgre_autoliquidation",
      "description": "Le transitaire refacture la TVA alors que la déclaration porte le code 1008."
    }
  ],
  "traps": [
    {
      "trap_id": "BX0042-T1",
      "control_id": "C1",
      "max_level": "conforme",
      "documents": ["ft1", "dec1"],
      "description": "Écart d'arrondi de 0,03 EUR entre droits par article et droits refacturés."
    }
  ],
  "expected_outcome": "ecart_certain",
  "expected_totals": {"recouvrable_certain_eur": "2508.00", "recouvrable_a_verifier_eur": "0.00"}
}
```

#### 19.3.1 Règles du contrat

- Montants en **chaînes décimales** (point décimal, pas de séparateur de milliers), EUR pour `expected_amount_eur`, signe selon §8.6. `null` si la nature de montant est `aucun` ou `renvoi`, ou si le montant n'est pas calculable (ex. A4 en devise sans taux).
- `documents[].type` et `sous_type` : énumérations de §6.2.6 et §5.3. `format` ∈ {`pdf_natif`, `pdf_scan`, `image`, `factur_x`, `ubl`, `cii`, `xml_declaration`, `csv_declaration`, `xlsx`, `eml`}.
- `pages` : numéros 1-based dans `file` (pour un tableur : rang de feuille ; pour un XML : `[1]`).
- Un PDF fusionné apparaît comme un `file` contenant plusieurs `documents`.
- `truth_values` : clés = chemins du modèle (§5.3) relatifs au document ; les **champs obligatoires** de vérité par type sont :
  - facture commerciale : `numero`, `date`, `devise`, `total_facture`, `total_imprime`, `acheteur.tva`, `incoterm`, `lignes[].{code_marchandise_imprime, quantite, unite, montant_ligne, pays_origine}`, `masse_brute_totale`, `nombre_colis` ;
  - déclaration : `mrn`, `date_acceptation`, `importateur.tva`, `devise_facture`, `montant_total_facture`, `taux_change`, `taux_change_sens`, `incoterm`, `nombre_articles`, `documents_references`, `indices_autoliquidation` (booléen), `articles[].{code_marchandise, pays_origine, masse_nette, masse_brute}`, `taxations[].{article, type_taxe, categorie, base_montant, base_quantite, taux, montant, paiement_normalise}`, `total_a_payer` ;
  - facture transitaire : `numero`, `date`, `emetteur.tva`, `client_facture.tva`, `refs_mrn`, `refs_transport`, `lignes[].{nature, libelle, quantite, prix_unitaire, montant_ht, taux_tva, montant_tva, mrn}`, `total_debours`, `total_ht`, `total_tva`, `total_ttc` ;
  - avoir : `numero`, `date`, `refs_facture_origine`, `lignes[].{nature, montant_ht}`, `total_credite_ttc`.

  Ces valeurs sont les valeurs **vraies telles qu'imprimées** (après injection d'erreur, donc l'erreur fait partie de la vérité du document). Elles servent à mesurer l'exactitude d'extraction par champ.
- `injected_errors[]` : une entrée par erreur. `control_id` est l'identifiant principal (Annexe A) ; `accepted_control_ids` est rempli **mécaniquement** à partir de la table d'équivalence de l'Annexe A (le générateur ne l'invente pas). `documents` liste les `doc_id` qui portent les valeurs en conflit. `injection` est un code du catalogue (§19.5).
- `expected_level` est fixé **mécaniquement** par le générateur :
  - `ecart_certain` si (1) le contrôle est éligible à ce niveau (Annexe A), (2) tous les documents concernés ont `degradation` ∈ {`d0`, `d1`} ou un format structuré, (3) `|montant d'écart| ≥ 3 ×` le seuil de certitude du contrôle (pour les contrôles sans montant : écart d'au moins 3 unités ou une valeur entièrement différente), (4) la valeur injectée n'est pas une substitution de la classe de confusion (§8.5.4), (5) les liens attendus sont explicites (référence citée) ;
  - `a_verifier` sinon.
- `traps[]` : situations qui ne doivent **pas** produire de constat au-delà de `max_level` (`conforme` ou `a_verifier`). Exemples obligatoires dans le corpus : arrondis sous tolérance, conversion légitime en EUR au taux imprimé, TVA autoliquidée **non** refacturée, facture complémentaire légitime, frais de fret expliquant A4, codes à 10 chiffres sur la déclaration et 6 sur la facture, pro forma acceptée, références tronquées compatibles, transporteur cité comme mode d'expédition sur une facture commerciale.
- Un dossier sans erreur a `injected_errors: []` et `expected_outcome: "conforme"`.
- `expected_links` sert à mesurer le regroupement ; il n'entre pas dans les métriques de contrôle.

### 19.4 Règle d'appariement constats ↔ erreurs injectées

Entrées : constats produits (`findings.json`, Annexe C) de niveau `ecart_certain` ou `a_verifier` ; erreurs injectées et pièges.

1. **Correspondance des documents** : un document produit `p` correspond au document de vérité `t` si même `file` (chemin relatif à `docs/`) et au moins 50 % des pages de `t` sont dans `p`.
2. **Candidat** : un couple (constat `f`, erreur `e`) est candidat si :
   - même `dossier_id` (pour F3–F5 : le dossier du constat est l'un des dossiers cités par `e`) ;
   - `f.controle_id ∈ e.accepted_control_ids` ;
   - au moins un document de `f.documents_concernes` correspond à un document de `e.documents` ;
3. **Appariement** : un-à-un, glouton déterministe, en triant les candidats par (écart de montant absolu croissant, `null` en dernier ; départage ; `error_id` ; `finding_id`). **Départage** à écart égal : on préfère le constat du contrôle principal de l'erreur (`control_id`), puis le constat de niveau `ecart_certain` (ajouté après le premier holdout, D-905 ; vaut pour tous les splits).
4. **Montant correct** : si `e.expected_amount_eur` et `f.montant_en_jeu` sont tous deux non nuls, `|f − e| ≤ max(0,05 ; 1 % × |e|)`. Si `e` attend `null` et que `f` porte un montant (ou l'inverse), le montant est incorrect, sauf pour les natures `recouvrable` où `f = null` avec raison `doublon_composantes` est accepté si un autre constat apparié du même dossier porte le montant.
5. Classes :
   - **VP certain** : `f` de niveau `ecart_certain` apparié avec montant correct ;
   - **FP certain** : `f` de niveau `ecart_certain` non apparié, ou apparié avec montant incorrect, ou apparié à un piège de `max_level` inférieur ;
   - **Surclassement** : VP certain dont l'erreur attendait `a_verifier` (compté VP pour la précision, rapporté à part) ;
   - **VP détection** : tout `f` apparié (tout niveau) ;
   - **FN** : erreur non appariée ;
   - **Sous-classement** : erreur attendue `ecart_certain` appariée à un `f` `a_verifier`.
   - Un constat non apparié de niveau `a_verifier` est un **FP à vérifier** (mesure de bruit pour le fondateur).
6. Métriques par contrôle (sur l'identifiant **principal** de l'erreur ; un FP est compté sur `f.controle_id`) et globales :
   - `precision_certain = VP certain / (VP certain + FP certain)` ;
   - `rappel = erreurs appariées / erreurs injectées` ;
   - `rappel_certain = erreurs attendues certain appariées à un ecart_certain / erreurs attendues certain` ;
   - `precision_detection = VP détection / constats produits` ;
   - `exactitude_montant = appariés à montant correct / appariés avec montant attendu` ;
   - `taux_surclassement`, `bruit_a_verifier_par_dossier` ;
   - exactitude d'extraction par champ obligatoire (`truth_values`) : égalité après normalisation (§5.2), montants à 0,005 près ;
   - regroupement : F1 des liens (`expected_links`) ;
   - **coût IA** (EUR) et **durée** (s) par dossier : moyenne, médiane, p95, maximum.

### 19.5 Catalogue d'injections (non limitatif, codes stables)

| Code `injection` | Contrôle principal | Effet |
|---|---|---|
| `entite_groupe_differente` | A1 | TVA importateur = autre entité du client |
| `entite_tierce` | A1 | TVA importateur hors client |
| `ref_facture_absente` | A2 | Déclaration sans référence de la facture |
| `devise_differente` | A3 | Devise déclarée ≠ devise facture, montant identique ou non |
| `valeur_transposee` | A4 | Deux chiffres adjacents permutés dans le montant déclaré |
| `valeur_modifiee` | A4 | Montant déclaré ± x % |
| `conversion_fausse` | A5 | Montant EUR ≠ montant × taux imprimé |
| `non_converti` | A6 | Montant étranger repris en EUR |
| `incoterm_different` | A8 | |
| `quantite_differente` | A9 | |
| `masse_differente` | A10 | |
| `colis_different` | A11 | |
| `origine_differente` | A12 | |
| `code_sh6_different` | A13 | |
| `date_anterieure` | A14 | |
| `taxe_base_taux_incoherente` | B1 | |
| `somme_taxes_incoherente` | B2 | |
| `somme_articles_incoherente` | B3 | |
| `nette_superieure_brute` | B4 | |
| `droits_surfactures` | C1 | |
| `autres_taxes_surfacturees` | C2 | |
| `tva_refacturee_malgre_autoliquidation` | C3 | |
| `tva_surfacturee` | C4 | |
| `debours_combines_surfactures` | C5 | |
| `faf_sur_excedent` | C6 | |
| `mrn_cite_inconnu` | C7 | |
| `client_facture_different` | C8 | |
| `total_faux` | D1 | |
| `ligne_hors_grille` | D2 | |
| `prix_superieur_grille` | D3 | |
| `faf_hors_grille` | D4 | |
| `ligne_doublee` | D5 | |
| `magasinage_excessif` | D6 | |
| `surcharge_non_prevue` | D7 | |
| `tva_sur_debours` | D8 | |
| `lignes_supplementaires_excessives` | D9 | |
| `avoir_sans_reference` | E1 | |
| `avoir_excessif` | E2 | |
| `avoir_double` | E3 | |
| `avoir_total_faux` | E4 | |
| `avoir_partiel` | E6 | |
| `fichier_double` | F1 | |
| `numero_reutilise` | F2 | |
| `mrn_refacture_deux_fois` | F3 | |
| `prestation_refacturee` | F4 | |
| `facture_sur_deux_declarations` | F5 | |
| `forfait_base_x_taux_faux` | G1 | |
| `forfait_base_differente` | G2 | |
| `forfait_codes_distincts` | G3 | |
| `forfait_surfacture` | G4 | |
| `forfait_unites_au_lieu_articles` | G5 | |
| `forfait_hors_periode` | G6 | |
| `facture_manquante`, `declaration_manquante` | P1 | |
| `faux_document_facture` | P2 | |

### 19.6 Composition du corpus

- **≥ 200 dossiers** au total (cible 250), répartis sur **au moins 4 clients** fictifs (dont un groupe à 3 entités).
- **8 gabarits de transitaire fictifs** (`T1`–`T8`), chacun dans ≥ 20 dossiers :

| Gabarit | Caractéristiques imposées |
|---|---|
| T1 | Débours ventilés droits / autres taxes / TVA, prestations séparées, total des débours imprimé, français |
| T2 | Tableau à trois colonnes (base droits, droits, TVA) par code marchandise, marqueurs de statut TVA en lettre, anglais |
| T3 | Un seul montant « droits et taxes » combiné, pas de total des débours imprimé |
| T4 | Relevé mensuel couvrant 3 à 8 MRN, tableau `transport / MRN / date`, débours par MRN |
| T5 | Facture de débours et facture de prestations séparées pour un même envoi |
| T6 | Copie de la déclaration et conditions générales fusionnées dans le même PDF, lettre d'accompagnement en page 1 |
| T7 | Facture électronique Factur-X (profil EN 16931) avec PDF visuel |
| T8 | Mise en page dense bilingue FR/EN, montants négatifs entre parenthèses pour les avoirs, références de transport avec espaces et barres |

- **Mises en page de déclaration** : `L1` imprimé H1 par articles, `L2` preuve de dédouanement condensée, `L3` formulaire à cases numérotées, `L4` H7, `X1` export XML, `X2` export CSV ; chacune ≥ 15 dossiers.
- **Dégradation** : `d0` PDF natif (40 %), `d1` scan propre 300 dpi (25 %), `d2` scan 200 dpi avec inclinaison ≤ 3°, bruit et une page tournée (20 %), `d3` type télécopie 150 dpi noir et blanc, grille de tableau marquée (15 %).
- **Scénarios** (part minimale des dossiers) : PDF fusionné 30 % ; plusieurs factures pour une déclaration 10 % ; une facture sur plusieurs déclarations 8 % ; facture transitaire couvrant plusieurs MRN 10 % ; autoliquidation 40 % ; devise étrangère 50 % (dont JPY ou KRW 5 %) ; avoirs 15 % ; petits envois (forfait) 8 % ; facture électronique (Factur-X, UBL ou CII) 10 % ; tableur 5 % ; dossiers sans erreur injectée ≥ 25 % ; dossiers à 2 erreurs ou plus ≥ 20 %.
- **Couverture** : chaque contrôle A1–G6 (hors P) reçoit ≥ 6 erreurs injectées au total, dont ≥ 2 dans `holdout` ; chaque contrôle éligible à `ecart_certain` reçoit ≥ 3 erreurs attendues `ecart_certain`.

### 19.7 Seuil bloquant de la construction

La construction (CI) échoue si, sur le split `holdout` :

1. `precision_certain` globale **< 0,97** ; ou
2. pour un contrôle ayant au moins 10 constats `ecart_certain` produits, `precision_certain` **< 0,95** ; ou
3. le nombre total de constats `ecart_certain` produits est inférieur à 30 **et** au moins un FP certain existe (petit échantillon : tolérance zéro) ; ou
4. `rappel` de P1 **< 1,0** (aucun document manquant ne doit passer) ; ou
5. une expression interdite (§3.2) apparaît dans un texte produit, ou une note de renvoi porte un montant.

**Justification du seuil 0,97.** Un diagnostic type contient environ 20 à 40 écarts certains. À 0,97, on attend moins d'une fausse accusation par diagnostic, que la validation du fondateur doit intercepter ; à 0,90, on en attendrait 2 à 4, ce qui détruit la crédibilité du client face à son transitaire. Le seuil par contrôle (0,95) évite qu'un contrôle faible soit masqué par les autres. Le rappel n'est pas bloquant (hors P1) : manquer un écart coûte moins qu'en inventer un ; il est suivi et doit progresser (objectif : `rappel` ≥ 0,80 sur C et D). Le rapport du banc affiche aussi la borne basse de Wilson à 95 % de `precision_certain`.

Indicateurs suivis sans blocage : coût IA moyen par dossier (alerte si > 0,30 EUR), durée p95 (alerte si > 300 s), bruit `a_verifier` non apparié (alerte si > 1,5 par dossier).

### 19.8 Sortie du correcteur

`bench/out/<run_id>/metrics.json` : `{schema: "controldone.bench.metrics/1.0.0", run_id, split, execution (versions), global: {...}, par_controle: {"C1": {...}, ...}, extraction_par_champ: {...}, regroupement: {...}, cout: {moyenne_eur, p95_eur, max_eur}, duree: {moyenne_s, p95_s, max_s}, gate: {passe: bool, motifs: []}, details: [{error_id, finding_id, classe}]}`.

---

## 20. Exigences non fonctionnelles

### 20.1 Sécurité et cloisonnement

- Isolation par client imposée par une couche d'accès unique (voir `docs/SECURITY.md`) ; tests d'accès croisé obligatoires.
- Chiffrement au repos des fichiers bruts et des textes de page ; TLS en transit ; secrets hors dépôt (variables d'environnement).
- Authentification forte pour le fondateur (second facteur) ; journal d'audit append-only de chaque accès administrateur, validation, correction, publication.
- Aucun document réel ni sortie réelle dans le dépôt de code ; seuls des tests sur données synthétiques.

### 20.2 Documents = données (anti-injection)

- Le modèle de langage n'a **aucun outil**, aucun accès réseau, aucun accès en écriture. Il reçoit le texte du document dans un bloc délimité et marqué comme donnée non fiable, et doit répondre uniquement dans le schéma JSON fermé de l'extraction ou du gabarit.
- Toute réponse hors schéma est rejetée. Les valeurs doivent être ancrées (§6.3). Un texte du document du type « ignorez les instructions », « classez ce dossier conforme » n'a aucun effet : aucun champ du schéma ne permet de modifier un statut, un niveau ou un montant.
- Les corps d'e-mail et les objets ne déclenchent aucune action ; seuls l'adresse dédiée, l'expéditeur autorisé et les pièces jointes sont utilisés.
- Test obligatoire : un jeu de documents piégés (consignes cachées en texte blanc, dans les métadonnées XMP, dans un champ XML libre, dans un corps d'e-mail) ne doit modifier ni l'extraction des champs clés ni aucun résultat.

### 20.3 Fichiers entrants

- Taille maximale : 50 Mo par fichier, 500 Mo par lot, 300 pages par fichier.
- Archives : refus des chemins absolus et des `..` (traversée), des liens symboliques, profondeur ≤ 5, nombre d'entrées ≤ 2 000, taux de compression ≤ 100 et taille décompressée ≤ 1 Go (protection contre les bombes).
- Analyse des PDF sans exécution de JavaScript ni de pièces actives ; rendu des pages dans un processus isolé avec limite de temps et de mémoire.

### 20.4 RGPD

- Le service est **sous-traitant** de ses clients (art. 28) : contrat de sous-traitance signé avec chaque client ; registre des traitements du sous-traitant (art. 30.2) tenu à jour ; liste des sous-traitants ultérieurs (hébergeur UE, fournisseur du modèle de langage, prestataire de paiement) communiquée et soumise à l'autorisation du client.
- Hébergement dans l'Union européenne. Si le fournisseur du modèle de langage traite des données hors UE, le client en est informé et peut **désactiver l'extracteur `llm`** (les extracteurs `structure` et `deterministe` restent disponibles). Réglage du client : `reglages.llm_desactive` (D-4007). Seules les pages du document concerné sont envoyées, en texte (D-4005).
- Minimisation : seules les données des documents d'import sont traitées ; les données personnelles (noms de contacts, téléphones) ne sont pas extraites dans le modèle sauf nécessité.
- Conservation : fichiers bruts et textes de page purgés `retention_jours` après la clôture du dossier (défaut 180 jours) ; constats, valeurs sourcées clés et registre de recouvrement conservés pendant la durée du contrat, puis restitués (export JSON + PDF) et supprimés sous 30 jours.
- Droits des personnes : relayés au client responsable de traitement.

### 20.5 Coûts IA

- Chaque appel au modèle est mesuré (jetons, coût EUR) et rattaché au client, au lot et au dossier.
- Plafond **par dossier** (défaut 0,50 EUR) : au-delà, les documents restants passent en extraction déterministe et le dossier est marqué « extraction partielle ».
- Plafond **mensuel par client** (`plafond_cout_ia_mensuel_eur`, défaut 8 EUR pour l'abonnement, 20 EUR par diagnostic) : à 80 %, alerte au fondateur ; à 100 %, arrêt des appels au modèle pour ce client jusqu'à décision du fondateur. Vérifié **avant chaque appel** avec une estimation majorante ; coût réel calculé depuis l'usage renvoyé (cache de prompt compris) aux tarifs datés de `config/llm_tarifs.yaml` (D-4004).
- Cache par `sha256` de page et version d'extracteur : une page déjà extraite n'est jamais renvoyée au modèle.

### 20.6 Idempotence, reproductibilité, robustesse

- Jobs idempotents (clés de §7), reprise après panne sans doublon, attente exponentielle, statut « mort » après 5 essais avec alerte.
- Une erreur sur un fichier n'arrête jamais le lot ; elle est listée dans « documents non lus ».
- Contrôles purs et déterministes ; rejouer une exécution donne le même résultat (§6.2.12).
- Indicateur d'avancement par lot ; page de santé indiquant la disponibilité de l'OCR et du modèle.

### 20.7 Performance

- Dossier de 10 pages : p95 ≤ 5 minutes de bout en bout hors file d'attente.
- Rapport web de 200 dossiers : affichage ≤ 2 s ; PDF ≤ 60 s.

### 20.8 Observabilité

- Journaux structurés **sans contenu de document** (identifiants, durées, compteurs, codes d'erreur seulement).
- Tableau de bord fondateur : file de validation, coûts par client, erreurs de jobs.

---

## 21. Hors périmètre

### 21.1 Hors périmètre juridique (jamais traité, seulement renvoyé)

Le produit **ne vérifie pas** et **ne dit jamais** :

- si le **taux** d'un droit ou d'une taxe est le bon (B1 vérifie seulement le calcul base × taux imprimés) ;
- si le **code marchandise** (classement tarifaire) est correct ;
- si la **valeur en douane** est juste (incluant fret, assurance, ajustements, méthode d'évaluation, effet de l'Incoterm) ;
- si l'**origine** déclarée est exacte, si une **préférence tarifaire** était applicable ou justifiée ;
- si le **régime douanier** choisi était le bon ;
- si l'**autoliquidation** de la TVA était applicable (le produit constate seulement ce qu'indique la déclaration) ;
- si le **droit forfaitaire petits envois** était applicable, ni la bonne définition d'un « article » ;
- si une **rectification de déclaration** ou une **demande de remboursement** auprès de la douane est possible ou due ;
- le traitement **TVA** d'une opération (D8 renvoie à l'expert-comptable).

Ces sujets apparaissent uniquement comme **notes de renvoi** (§3.3) : niveau `a_verifier`, valeurs lues citées, **aucun montant** présenté comme dû, phrase de renvoi exacte. Aucun calcul de droit « qui aurait dû être payé » n'est fait, aucune nomenclature tarifaire n'est consultée pour juger un code.

### 21.2 Hors périmètre fonctionnel de la v2

- Envoi des réclamations au transitaire (le client envoie lui-même) ; signature au nom du client ou du fondateur.
- Toute démarche auprès de la douane (rectification, remboursement, recours).
- Fonctions de plateforme agréée de facturation électronique : le produit **reçoit** des factures Factur-X, UBL ou CII déposées par le client ; il n'émet, ne transmet ni ne reçoit de factures sur le réseau de la réforme, ne gère pas les statuts de cycle de vie, ne fait pas d'e-reporting.
- Déclarations MACF/CBAM, obligations du déclarant CBAM.
- Calcul de droits à partir du tarif, simulation de droits, conseil en classement, origine ou valeur.
- Contrôle des factures fournisseurs hors import (achats domestiques).
- Comptabilisation, rapprochement bancaire, paiement des factures.
- Accès des transitaires à la plateforme.
- Application mobile.

---

## Annexe A — Liste récapitulative des identifiants de contrôle

Colonne « Certain ? » : le contrôle peut-il produire `ecart_certain`. Colonne « Équivalents banc » : `accepted_control_ids` à écrire dans `truth.json` pour une erreur dont c'est le contrôle principal.

| ID | Libellé | Unité | Certain ? | Nature du montant | Équivalents banc |
|---|---|---|---|---|---|
| P1 | Complétude du dossier | dossier | non | aucun | P1 |
| P2 | Document non exploitable | document | non | aucun | P2, P1 |
| P3 | Champ clé illisible (pas de constat) | champ | — | — | — |
| P4 | Rattachement faible | lien | non | aucun | P4 |
| P5 | Dossier non concerné (statut) | dossier | — | — | — |
| A1 | Entité importatrice | couple | oui | aucun | A1 |
| A2 | Référence de facture citée | couple | non | aucun | A2 |
| A3 | Devise de facturation | couple | oui | aucun | A3, A6 |
| A4 | Valeur facturée (même devise) | couple | oui | ecart_documentaire | A4, A5 |
| A5 | Montant converti au taux imprimé | couple | oui | ecart_documentaire | A5, A4 |
| A6 | Montant repris sans conversion | couple | oui | ecart_documentaire | A6, A3, A5 |
| A7 | Ordre de grandeur au taux indicatif | couple | non | aucun | A7, A6 |
| A8 | Incoterm | couple | non | aucun | A8 |
| A9 | Quantités | ligne/article | non | aucun | A9 |
| A10 | Masses facture/déclaration | couple | non | aucun | A10 |
| A11 | Nombre de colis | couple | non | aucun | A11, B5 |
| A12 | Pays d'origine imprimés (renvoi) | ligne/article | non | renvoi | A12 |
| A13 | Codes marchandise imprimés (renvoi) | couple | non | renvoi | A13 |
| A14 | Chronologie des dates | couple | non | aucun | A14 |
| A15 | Références produit (signal) | couple | non | aucun | A15 |
| B1 | Base × taux = montant | ligne de taxation | oui | arithmetique_declaration | B1, B2 |
| B2 | Sommes des taxes | déclaration | oui | arithmetique_declaration | B2, B1 |
| B3 | Somme des montants facturés des articles | déclaration | oui | arithmetique_declaration | B3 |
| B4 | Masses nette/brute | déclaration | oui (a), non (b) | aucun | B4, A10 |
| B5 | Colis | déclaration | non | aucun | B5, A11 |
| C1 | Droits refacturés | facture transitaire × déclaration(s) | oui | recouvrable | C1, C5 |
| C2 | Autres taxes refacturées | idem | oui | recouvrable | C2, C5 |
| C3 | TVA refacturée malgré autoliquidation | idem | oui | recouvrable | C3, C5 |
| C4 | TVA refacturée (payée) | idem | oui | recouvrable | C4, C5 |
| C5 | Total des débours | idem | oui | recouvrable | C5, C1, C2, C3, C4 |
| C6 | FAF sur débours en écart | ligne FAF | oui | recouvrable | C6, D4 |
| C7 | Références de la facture transitaire | facture transitaire | non | aucun | C7 |
| C8 | Client facturé | facture transitaire | oui | aucun | C8 |
| D1 | Arithmétique interne | facture transitaire | oui | recouvrable (totaux) | D1 |
| D2 | Ligne hors grille | ligne | oui | recouvrable | D2, D7 |
| D3 | Prix supérieur à la grille | ligne | oui | recouvrable | D3 |
| D4 | FAF contre grille | ligne FAF | oui | recouvrable | D4, C6 |
| D5 | Ligne en double | facture | oui | recouvrable | D5 |
| D6 | Magasinage | ligne | oui | recouvrable | D6, D3 |
| D7 | Surcharges | ligne | oui | recouvrable | D7, D2, D3 |
| D8 | TVA sur débours | ligne | non | recouvrable (informatif) | D8 |
| D9 | Lignes supplémentaires | ligne | oui | recouvrable | D9, D3 |
| E1 | Rattachement de l'avoir | avoir | non | aucun | E1 |
| E2 | Avoir supérieur à l'origine | avoir | non | aucun | E2 |
| E3 | Avoir reçu deux fois | avoir | non | aucun | E3, F1 |
| E4 | Arithmétique de l'avoir | avoir | non | aucun | E4 |
| E5 | Avoir sans écart ouvert | avoir | non | aucun | E5 |
| E6 | Avoir partiel | écart | non | recouvrable (reste) | E6 |
| F1 | Document en double | document | non | aucun | F1, E3 |
| F2 | Numéro de facture transitaire réutilisé | facture | non | aucun | F2 |
| F3 | Même déclaration refacturée deux fois | MRN | oui | recouvrable | F3, C5 |
| F4 | Même prestation facturée deux fois | ligne | non | recouvrable | F4, D5 |
| F5 | Facture commerciale sur plusieurs déclarations | facture | non | ecart_documentaire | F5, A4 |
| G1 | Nombre d'articles × montant unitaire | ligne forfait | oui | arithmetique_declaration | G1, B1 |
| G2 | Base du forfait contre nombre d'articles | déclaration | oui | arithmetique_declaration | G2 |
| G3 | Base contre codes distincts (renvoi) | déclaration | non | renvoi | G3, G2 |
| G4 | Forfait refacturé contre liquidé | facture transitaire × déclaration | oui | recouvrable | G4, G5, C1, C5 |
| G5 | Base de refacturation du transitaire | ligne | oui | recouvrable | G5, G4 |
| G6 | Applicabilité du forfait (renvoi) | déclaration | non | renvoi | G6 |

---

## Annexe B — Schéma `truth.json` (JSON Schema 2020-12, résumé normatif)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "controldone.bench.truth/1.0.0",
  "type": "object",
  "required": ["schema", "dossier_id", "split", "client_id", "generator_version", "seed",
               "degradation", "files", "documents", "truth_values", "expected_links",
               "injected_errors", "traps", "expected_outcome", "expected_totals"],
  "properties": {
    "schema": {"const": "controldone.bench.truth/1.0.0"},
    "dossier_id": {"type": "string", "pattern": "^BX[0-9]{4}$"},
    "split": {"enum": ["dev", "holdout"]},
    "client_id": {"type": "string", "pattern": "^CL[0-9]{2}$"},
    "generator_version": {"type": "string"},
    "seed": {"type": "integer"},
    "transitaire_template": {"enum": ["T1","T2","T3","T4","T5","T6","T7","T8", null]},
    "declaration_layout": {"enum": ["L1","L2","L3","L4","X1","X2", null]},
    "degradation": {"enum": ["d0","d1","d2","d3"]},
    "scenario_tags": {"type": "array", "items": {"type": "string"}},
    "files": {"type": "array", "items": {
      "type": "object", "required": ["path", "sha256", "pages"],
      "properties": {"path": {"type": "string", "pattern": "^docs/"},
                     "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                     "pages": {"type": "integer", "minimum": 1}}}},
    "documents": {"type": "array", "items": {
      "type": "object", "required": ["doc_id", "type", "format", "degradation", "file", "pages"],
      "properties": {
        "doc_id": {"type": "string"},
        "type": {"enum": ["facture_commerciale","declaration","facture_transitaire","avoir",
                          "document_support","document_non_exploitable"]},
        "sous_type": {"type": ["string","null"]},
        "format": {"enum": ["pdf_natif","pdf_scan","image","factur_x","ubl","cii",
                            "xml_declaration","csv_declaration","xlsx","eml"]},
        "degradation": {"enum": ["d0","d1","d2","d3"]},
        "file": {"type": "string"},
        "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "transitaire_template": {"type": ["string","null"]},
        "language": {"enum": ["fr","en","es","fr_en"]}}}},
    "truth_values": {"type": "object", "additionalProperties": {"type": "object"}},
    "expected_links": {"type": "array", "items": {
      "type": "object", "required": ["from","to","role"],
      "properties": {"from": {"type": "string"}, "to": {"type": "string"},
                     "role": {"enum": ["declaration","facture_transitaire","avoir","support"]}}}},
    "injected_errors": {"type": "array", "items": {
      "type": "object",
      "required": ["error_id","control_id","accepted_control_ids","expected_level",
                   "expected_amount_eur","amount_nature","documents","injection"],
      "properties": {
        "error_id": {"type": "string"},
        "control_id": {"type": "string", "pattern": "^[PABCDEFG][0-9]{1,2}$"},
        "accepted_control_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "expected_level": {"enum": ["ecart_certain","a_verifier"]},
        "expected_amount_eur": {"type": ["string","null"], "pattern": "^-?[0-9]+\\.[0-9]{2}$"},
        "amount_nature": {"enum": ["recouvrable","ecart_documentaire","arithmetique_declaration","renvoi","aucun"]},
        "composante": {"enum": ["droit","autre_taxe","tva","forfait_petits_envois","prestation","valeur",null]},
        "documents": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "other_dossiers": {"type": "array", "items": {"type": "string"}},
        "fields": {"type": "array", "items": {"type": "string"}},
        "injection": {"type": "string"},
        "description": {"type": "string"}}}},
    "traps": {"type": "array", "items": {
      "type": "object", "required": ["trap_id","control_id","max_level","documents"],
      "properties": {"trap_id": {"type": "string"}, "control_id": {"type": "string"},
                     "max_level": {"enum": ["conforme","a_verifier"]},
                     "documents": {"type": "array", "items": {"type": "string"}},
                     "description": {"type": "string"}}}},
    "expected_outcome": {"enum": ["non_concerne","document_manquant","ecart_certain","a_verifier","conforme"]},
    "expected_totals": {"type": "object",
      "required": ["recouvrable_certain_eur","recouvrable_a_verifier_eur"],
      "properties": {"recouvrable_certain_eur": {"type": "string"},
                     "recouvrable_a_verifier_eur": {"type": "string"}}}
  }
}
```

`other_dossiers` est obligatoire pour les erreurs F2–F5 (dossiers qui portent l'autre occurrence).

---

## Annexe C — Schéma de sortie `findings.json` (par dossier)

```json
{
  "schema": "controldone.findings/1.0.0",
  "dossier_id": "BX0042",
  "dossier_version": 3,
  "execution": {"execution_id": "…", "version_moteur": "…", "version_regles": "…",
                "empreinte_tolerances": "…", "modele_llm": null,
                "cout_ia_eur": "0.12", "duree_s": 41.3},
  "statut_global": "ecart_certain",
  "documents": [
    {"document_id": "doc_…", "type": "facture_transitaire", "sous_type": null,
     "file": "docs/expedition_77/envoi.pdf", "pages": [5, 6], "confiance_classement": 0.94}
  ],
  "liens": [{"document_id": "doc_…", "role": "declaration", "force": "forte", "signaux": ["mrn_cite"]}],
  "valeurs": {"doc_…": {"numero": {"valeur": "FT-88812", "page": 5, "confiance": 0.98, "methode": "texte_natif"}}},
  "resultats": [
    {"controle_id": "C1", "outcome": "conforme", "attendu": "812.40", "constate": "812.40",
     "ecart": "0.00", "tolerance": "0.05"}
  ],
  "constats": [
    {"finding_id": "f_…", "controle_id": "C3", "niveau": "ecart_certain",
     "raisons": [], "montant_en_jeu": "2508.00", "nature_montant": "recouvrable",
     "composante": "tva", "renvoi": false,
     "documents_concernes": ["doc_ft", "doc_dec"],
     "preuves": [{"document_id": "doc_ft", "page": 5, "valeur_brute": "2 508,00", "role": "valeur_b"},
                 {"document_id": "doc_dec", "page": 2, "valeur_brute": "1008 FR32000123459", "role": "valeur_a"}],
     "libelle": "…", "prochaine_action": "…", "statut_validation": "propose"}
  ],
  "avertissement": "Ce document est un contrôle technique…"
}
```

Le correcteur du banc lit `constats[]` (et `documents[]` pour la correspondance des fichiers et pages) ; il n'utilise pas `statut_validation` (le banc évalue la sortie avant validation humaine).
