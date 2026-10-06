# Brief juridique ControlDOne : France et Suisse (Belgique et Luxembourg en bref)

*Recherche faite le 2 octobre 2026. **Je ne suis pas avocat** : ce document est une recherche documentaire sourcée, pas une consultation juridique. Il sert à préparer un rendez-vous avec un avocat, pas à le remplacer. Les points marqués **« à faire confirmer par un avocat »** ne doivent pas être tranchés sans lui.*

*Méthode : recherches web et lecture des pages citées. Pour chaque source, j'indique si la page a été **lue** (texte ouvert) ou seulement **vue en résultat de recherche** (extrait du moteur, page non ouverte). Pages qui n'ont pas pu être lues : Légifrance L1222-5 C. trav. (404, texte lu sur code.travail.gouv.fr), EUR-Lex CDU (page vide), annonce URSSAF des seuils 2026 (503), WilmerHale sur l'appel Latombe (503), fiches lawplayer (403).*

*Documents du projet relus avant rédaction : `docs/recherche/legal_market.md`, `customs.md`, `einvoice.md`, `site/cgv.html`, `dpa.html`, `confidentialite.html`, `mentions-legales.html`, `tarifs.html`, `index.html`, `methode.html`, `experts-comptables.html`, `docs/RGPD_registre.md`, `docs/MACF.md`, `docs/REFERENTIEL.md`, `commercial/sequence_emails.md`, `commercial/prospects_methode.md`, `config/offres.yaml`, `config/formulations_interdites.yaml`, `config/referentiel_alias_publics.yaml`.*

---

## 0. Synthèse des verdicts

| # | Sujet | France | Suisse |
|---|---|---|---|
| 1 | Audit arithmétique et documentaire de factures de transitaires | **OK sous conditions** | **OK** (pas de monopole du conseil) |
| 1 | Audit qui juge le bien-fondé d'un droit, d'une taxe, d'un classement ou d'une clause | **Interdit** (art. 54 loi 71-1130) | OK en droit, mais à éviter par cohérence produit |
| 1 | Préparer les courriers de demande d'avoir que le client envoie | **Risque** : à reformuler en relevé factuel et modèle non juridique | OK |
| 1 | Commission de 20 % sur les avoirs | **OK sous conditions** : licite si l'activité n'est pas juridique, nulle sinon | OK |
| 1 | Commission sur des remboursements de droits obtenus de la douane | **Risque élevé** : à exclure | À éviter |
| 2 | Analyser les DAU et exports DELTA transmis par le client | **OK** | **OK** |
| 2 | Déposer, rectifier ou réclamer auprès de la douane pour le client | **Interdit** sans statut de RDE | Réservé à la personne assujettie à l'obligation de déclarer |
| 3 | Créer l'activité en restant salarié | **OK sous conditions** | **OK sous conditions** |
| 3 | Si l'employeur est un transitaire, ou un commissionnaire en douane | **Risque élevé** (concurrence, loyauté) | **Risque élevé** |
| 3 | Si le fondateur est agent public des douanes | **Autorisation préalable obligatoire** | sans objet |
| 4 | Micro-entreprise (BNC) et franchise de TVA | **OK** | Pas d'immatriculation TVA tant que le fondateur n'a pas d'établissement en Suisse (impôt sur les acquisitions chez le client) |
| 4 | Diagnostic gratuit « contre » le droit de publier | **Risque** fiscal (troc) : à restructurer | sans objet |
| 5 | RGPD : sous-traitant pour les documents, responsable pour la prospection | **OK sous conditions** | **OK sous conditions** (nLPD) |
| 5 | Transfert vers Anthropic (États-Unis) | **OK sous conditions** (CCT ; DPF en sursis) | **OK sous conditions** (addendum suisse) |
| 5 | Prospection e-mail B2B | **OK** en opt-out, si le message vise la fonction | **OK seulement en envoi individuel** ; opt-in pour les envois de masse |
| 5 | Référentiel agrégé par transitaire | **OK sous conditions** | **OK sous conditions** |
| 5 | AI Act | **OK** : obligations minimes | sans objet (droit suisse : pas de loi IA en vigueur trouvée) |
| 6 | CGV B2B, limitation de responsabilité | **OK sous conditions** | **OK sous conditions** (art. 100 CO) |
| 6 | Commission versée à un expert-comptable apporteur | **Interdit** (art. 24 ord. 1945) | Non vérifié |
| 6 | Client de 5 salariés au plus, contrat conclu hors établissement | **Risque** : droit de rétractation de 14 jours | sans objet |
| 7 | Site : mentions légales, aucun cookie, accessibilité | **OK sous conditions** | **OK** |
| 8 | RC Pro | Non obligatoire, **fortement recommandée** | Idem |

**Les trois changements prioritaires** :
1. Supprimer du produit et des textes toute qualification « contractuelle » qui suppose d'interpréter un contrat. Ne garder que des écarts chiffrés contre des documents.
2. Transformer la « demande d'avoir » en un **relevé factuel d'écarts** accompagné d'un modèle neutre, que le client adapte et envoie lui-même.
3. Restructurer l'offre de lancement (remise commerciale, avec une autorisation de publier séparée et révocable) et **supprimer toute commission aux experts-comptables**.

---

## 1. Périmètre du droit : l'audit et les courriers sont-ils licites pour un non-avocat ?

### 1.1 France : les textes

- **Art. 54 de la loi n° 71-1130.** « Nul ne peut, directement ou par personne interposée, à titre habituel et rémunéré, donner des consultations juridiques ou rédiger des actes sous seing privé, pour autrui » sans diplôme ou compétence juridique appropriée, ni sans assurance RC et garantie financière. — Légifrance (vu en recherche) : https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000039280601 ; section lue : https://www.legifrance.gouv.fr/codes/section_lc/JORFTEXT000000508793/LEGISCTA000006112891/
- **Art. 59.** Les professions réglementées peuvent donner des consultations dans les limites de leur réglementation, et rédiger les actes qui sont l'accessoire direct de leur prestation. — même section (lue)
- **Art. 60.** Les professions non réglementées titulaires d'une qualification reconnue peuvent donner des consultations relevant directement de leur activité principale, et rédiger les actes qui en sont l'accessoire nécessaire. — même section (lue)
- **Sanction.** Art. 66-2, qui renvoie à l'art. 72 : jusqu'à 1 an d'emprisonnement et 15 000 € d'amende. — même section (lue)
- **Conséquence civile.** Le contrat est nul et les honoraires sont perdus (nullité d'ordre public). — CA Paris 18 sept. 2013 n° 10/25413, commentaire lu : https://vivaldi-chronos.com/perimetre-du-droit-et-audit-des-couts/
- **Démarchage juridique.** Il est interdit aux non-professionnels du droit (art. 66-4), mais seulement si le démarchage vise à donner des consultations ou à rédiger des actes. Une prospection pour un service non juridique n'est pas visée. — Vade-mecum CNB 2023 (PDF lu), p. 72-73 : https://cnb.avocat.fr/medias/cnb-vademecum-exercice-du-droit-2023-68f77e825bf8f7.74522639.pdf

### 1.2 France : ce que disent les juges sur les sociétés d'« audit de coûts »

Source pour l'ensemble de ce paragraphe : vade-mecum CNB 2023, lu, p. 55-62.

- **Définition retenue par le CNB (AG du 18 juin 2011), reprise par les juges** : la consultation juridique est « une prestation intellectuelle personnalisée tendant, sur une question posée, à la fourniture d'un avis ou d'un conseil fondé sur l'application d'une règle de droit en vue, notamment, d'une éventuelle prise de décision ».
- **Ce qui relève de la consultation selon le CNB** : qualifier juridiquement une situation de fait, déterminer le régime juridique applicable, interpréter des normes, « la recherche d'erreurs de droit ou de fait préalable à la mise en œuvre d'un recours ».
- **Cass. 1re civ., 15 nov. 2010, n° 09-66.319 (Alma Consulting).** « La vérification, au regard de la réglementation en vigueur, du bien-fondé des cotisations […] constitue elle-même une prestation à caractère juridique », quel que soit le niveau de complexité. — arrêt lu : https://www.legifrance.gouv.fr/juri/id/JURITEXT000023113684/
- **Cass. com., 12 févr. 2013, n° 12-12.087 (Cap2e).** « La vérification, au regard de la réglementation fiscale en vigueur, de la situation des salariés » est une prestation juridique exercée à titre principal. — commentaire lu : https://www.lexbase.fr/article-juridique/8047870-jurisprudence-perimetre-du-droit-letau-se-resserre ; arrêt vu en recherche : https://www.legifrance.gouv.fr/juri/id/JURITEXT000027076288
- **CA Paris, 10 sept. 2014 (Syncost), confirmé par Cass. 1re civ., 17 févr. 2016, n° 14-29.687.** Rechercher des coûts « juridiquement non fondés » suppose d'analyser et d'interpréter les textes : c'est une prestation juridique.
- **CA Paris, 9 avr. 2018, n° 16-16683.** Phrase clé pour ControlDOne : le prestataire « ne s'est donc pas livré à **un simple calcul de cohérence entre les sommes dues et celles déclarées et réclamées** mais a procédé à une interprétation juridique personnalisée ». Par contraste, un simple calcul de cohérence n'est donc pas une consultation. Le même arrêt ajoute qu'un « diagnostic […] destiné à d'éventuelles réclamations » est juridique.
- **CA Paris, 15 sept. 2022, n° 21/07124 (CNB c/ Eiffel).** Un honoraire de 35 % des économies réalisées. L'audit y est jugé « intrinsèquement lié à la prestation juridique ». Avoir fait valider l'analyse par un avocat ne régularise rien.
- **Une validation par un avocat ne régularise pas.** Selon le CNB (« NB » p. 61), elle ne régularise pas une prestation juridique vendue par la société d'audit, car l'avocat doit être en lien direct avec le client. Même sens : CA Riom, 13 févr. 2019, n° 17/01958, commentaire lu : https://www.lexbase.fr/article-juridique/50029029-brevesirregularitedelaprestationdoptimisationdechargessocialesenlabsencedepreuvedevali
- **CA Paris, 19 janv. 2016, n° 13-09329.** Le calcul d'un préjudice n'est ni un acte juridique ni une consultation. — vade-mecum p. 73

**Rédaction d'actes sous seing privé pour autrui.** Source : vade-mecum, p. 62.
- Une réponse ministérielle de 1992 en donne le contenu : « les actes unilatéraux et les contrats, non revêtus de la forme authentique, rédigés pour autrui et **créateurs de droits ou d'obligations** » (JOAN 20/07/1992 p. 3291).
- Les modèles ou lettres-types **sans adaptation ou individualisation** n'en sont pas (Cass. 1re civ., 15 mars 1999, n° 96-21.415).

**Modèles de lettres.** Source : vade-mecum, p. 69.
- Mettre à disposition des modèles de mise en demeure, que l'utilisateur choisit lui-même, n'est pas de l'assistance juridique : c'est « une prestation matérielle de mise à disposition d'une bibliothèque documentaire » (Cass. crim., 21 mars 2017, n° 16-82.437 ; CA Paris, 6 nov. 2018, n° 17/04957, Demander Justice).
- La doctrine citée par le CNB objecte qu'un algorithme qui choisit le modèle à la place de l'utilisateur pourrait être vu comme un « syllogisme informatique ».

**Honoraires de résultat.**
- Aucun texte n'interdit à un prestataire non juridique d'être payé au pourcentage. L'interdiction du pacte de quota litis vise les avocats.
- Le risque est indirect : si la prestation est jugée juridique, le contrat est nul et la commission perdue (Eiffel, Alma).
- Il existe un texte spécial pour la sécurité sociale (art. L244-13 CSS, nullité des rémunérations d'intermédiaires qui obtiennent des remises de cotisations), cité par le vade-mecum p. 58. **Je n'ai trouvé aucun équivalent en droit douanier français. Point à faire confirmer par un avocat.**

### 1.3 France : où passe la ligne pour ControlDOne

| Activité | Verdict | Pourquoi |
|---|---|---|
| Additionner, recalculer, comparer un montant imprimé sur la facture du transitaire avec le même montant imprimé sur le DAU (droits liquidés, TVA, débours) | **OK** | « Simple calcul de cohérence » (CA Paris 2018) ; pas de règle de droit appliquée |
| Comparer une ligne facturée avec un **prix chiffré** d'une grille fournie par le client (prix × quantité) | **OK sous conditions** | Comparaison de chiffres. Elle devient juridique dès qu'il faut **interpréter** une clause (quelle grille s'applique, si une surcharge est « due », portée des CGV du transitaire, Incoterm) |
| Constater qu'une déclaration indique l'autoliquidation alors que la facture refacture de la TVA | **OK sous conditions** | Constat documentaire. Dire si l'autoliquidation **s'applique** est une question fiscale, donc renvoi obligatoire |
| Dire qu'un droit, une taxe, un classement, une origine, une valeur ou un régime est juste ou faux | **Interdit** | Cœur des arrêts Alma, Cap2e et Syncost |
| Identifier des remboursements possibles auprès de la douane (art. 116 s. CDU) et être payé au pourcentage | **Interdit / risque élevé** | « Recherche d'erreurs […] préalable à la mise en œuvre d'un recours » |
| Rédiger, au nom du client, une « demande d'avoir » individualisée qui invoque un droit (« conformément au contrat… », mise en demeure, délai, menace d'action) | **Risque élevé** | Acte unilatéral « créateur de droits ou d'obligations » ; « diagnostic destiné à d'éventuelles réclamations » |
| Fournir un **relevé factuel** (valeur A, valeur B, page, écart) et un **modèle neutre** que le client complète, modifie et signe lui-même | **OK sous conditions** | Relevé = calcul. Modèle sans argument juridique, proche des « modèles-types » admis. **À faire confirmer par un avocat** |
| Faire « valider » l'analyse juridique par un avocat sous-traitant | **Ne régularise pas** | CNB, CA Paris 2018 et 2022 |
| Orienter le client vers un avocat ou un RDE **qu'il mandate et paie directement** | **OK** | Lien direct client–avocat |

**Exception « activité accessoire » (art. 59 et 60).**
- Elle ne s'applique pas au fondateur : il n'exerce ni une profession réglementée ni une activité principale non juridique dotée d'une qualification reconnue (agrément ou certification type OPQCM, vade-mecum p. 26 et 64).
- Elle ne couvre de toute façon que ce qui est **accessoire** à une activité principale **non juridique**.
- **Conséquence** : ControlDOne doit rester purement non juridique. Il ne doit pas compter sur l'accessoire.

**Conséquences pour le produit.**
1. Remplacer partout « écarts **contractuels** » par « écarts **tarifaires** chiffrés contre la grille transmise par le client ».
2. Toute comparaison qui exige d'interpréter une clause passe en « à faire vérifier », sans montant certain.
3. Le courrier joint ne cite **aucune** règle de droit, aucune clause interprétée, aucune mise en demeure, aucun délai ni aucune menace. Il demande au transitaire de **vérifier** et d'**indiquer** s'il émettra un avoir.
4. La commission ne porte que sur des avoirs **émis par un transitaire**, jamais sur des remboursements ou des remises de droits accordés par l'administration.
5. Le LLM ne rédige pas les courriers : ils sont produits à partir de gabarits fixes, ce qui rejoint aussi la question de l'AI Act (§5.6).

### 1.4 Suisse

- **Pas de monopole du conseil juridique.** Le monopole des avocats inscrits porte sur la **représentation en justice** (LLCA art. 2 ; CPC art. 68 al. 2). Le conseil juridique n'est pas réservé. — https://lawinside.ch/22/ (ATF 140 III 555, vu en recherche) ; extraits de recherche sur la LLCA : https://www.bj.admin.ch/dam/bj/fr/data/staat/gesetzgebung/archiv/anwaltsgesetz-freizuegigkeit/vn-ber.pdf.download.pdf/vn-ber-f.pdf (vu en recherche)
- **Verdict : OK.** Courriers de réclamation et commission de résultat sont licites pour un non-avocat. Il faut seulement ne pas représenter le client devant un tribunal ou une autorité de recours.
- **Point à confirmer par un avocat suisse** : certaines lois cantonales réglementent les « agents d'affaires » (représentation, recouvrement). Aucune règle visant un simple audit n'a été trouvée.
- **Recommandation** : garder les mêmes garde-fous qu'en France, pour un produit et des textes uniques.

### 1.5 Belgique et Luxembourg (en bref)

- **Belgique.** Le conseil juridique n'est pas réservé aux avocats, seule la plaidoirie l'est (art. 440 C. jud.). — https://www.justice-en-ligne.be/Qui-pour-intervenir-au-nom-d-un (vu en recherche) ; https://e-justice.europa.eu/topics/find-legal-professional/types-legal-professions/be_fr?member=1 (vu en recherche). **Verdict : OK.**
- **Luxembourg.** La loi du 10 août 1991 (art. 2) réserverait la consultation juridique aux avocats. — https://legilux.public.lu/eli/etat/leg/loi/1991/08/10/n3/jo (vu en recherche) ; https://latribune.avocats.be/fr/le-petit-plaideur-europeen-luxembourg (vu en recherche). **Verdict : même prudence qu'en France ; à faire confirmer par un avocat luxembourgeois avant toute vente.**

---

## 2. Douane : qu'est-ce qui est réservé ?

### 2.1 France et UE

- **Représentant en douane (CDU art. 5 et 18-19).** Toute personne peut désigner un représentant en douane. La représentation est directe (au nom et pour le compte d'autrui) ou indirecte (en son nom propre pour le compte d'autrui). Celui qui se dit représentant sans habilitation est réputé agir pour son propre compte. — EUR-Lex (vu en recherche, page vide à l'ouverture) : https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32013R0952 ; Doctrine art. 18 (vu en recherche) : https://www.doctrine.fr/l/texts/eu/reglements/EULEG96A95193F6C370474500/articles/EULEGARTI74ABAAFE0ECE20E2F900
- **RDE en France.** Depuis le 1er janvier 2018, un professionnel qui accomplit **pour autrui** des actes ou formalités prévus par la réglementation douanière doit être enregistré comme RDE. Cela couvre :
  - les déclarations ;
  - les actes contentieux et non contentieux ;
  - les demandes d'autorisation ;
  - « tout acte ou formalité requis(e) pour permettre l'application de la législation douanière ».

  — fiche douane lue : https://www.douane.gouv.fr/fiche/le-representant-en-douane-enregistre ; arrêté du 13 avril 2016 (vu en recherche) : https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000032482257 ; C. douanes art. 86-87 (section vue en recherche) : https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006071570/LEGISCTA000006138873/
- **Analyse de documents.** La fiche douane ne dit rien d'une activité de **lecture et analyse** de déclarations déjà déposées. Le statut de RDE vise les actes accomplis **auprès de la douane**.

| Activité | Verdict |
|---|---|
| Lire des copies de DAU, des exports DELTA ou des avis de mise en recouvrement transmis par le client | **OK** (accès par le client seulement ; jamais d'identifiants douane du client) |
| Préparer pour le client une liste de points « à faire vérifier par un RDE ou un avocat » | **OK** |
| Déposer, rectifier ou invalider une déclaration, demander un remboursement ou une remise (art. 116 s. CDU), répondre à un contrôle pour le client | **Interdit** sans statut de RDE (et juridique, voir §1) |
| Pack MACF/CBAM : préparer des données pour le client ou son déclarant autorisé | **OK sous conditions** : ne pas déposer, ne pas dire si le MACF s'applique (déjà dans `docs/MACF.md`) |

- **Réforme du CDU.** Elle a été adoptée en septembre 2026 (voir `customs.md` §5), avec une application progressive. Il faudra relire les règles de représentation lors de son application. **Point de veille.**

### 2.2 Suisse

- **Loi sur les douanes (LD), version au 1er sept. 2022, PDF lu** : https://fedlex.data.admin.ch/filestore/fedlex.data.admin.ch/eli/cc/2007/249/20220901/fr/pdf-a/fedlex-data-admin-ch-eli-cc-2007-249-20220901-fr-pdf-a-1.pdf
  - **Art. 26.** Sont assujettis à l'obligation de déclarer : les personnes qui conduisent les marchandises, « les personnes chargées d'établir la déclaration en douane » et celles qui modifient l'emploi d'une marchandise.
  - **Art. 34 al. 3 et 4.** Seule « la personne assujettie à l'obligation de déclarer » peut demander une modification de la taxation, **dans les 30 jours** suivant la sortie de la garde de l'OFDF, avec une déclaration rectifiée.
  - **Au-delà de ce délai** : recours (art. 116 LD), dans les 60 jours selon le règlement R-10 vu en recherche : https://www.bazg.admin.ch/dam/fr/sd-web/3NtMV43K3YMy/R-10-00_Einfuhrzollveranlagungsverfahren_f.pdf
- **Pas de licence de transitaire trouvée.** Aucune licence d'État pour déclarer pour autrui n'a été trouvée : une entreprise peut dédouaner elle-même ou passer par un prestataire. — https://by-express.ch/actualites/transitaire-douane-suisse/ (vu en recherche, source secondaire). **À confirmer.**
- **Révision totale de la LD (LE-OFDF / LDD).** Adoptée le 20 juin 2025, sans référendum. Entrée en vigueur « en temps voulu, conjointement avec les ordonnances » : aucune date n'est publiée. — page lue : https://www.bazg.admin.ch/fr/revision-legislative-dazit-processus-douaniers. Les numéros d'articles changeront.
- **Verdict : OK.** L'audit des déclarations Passar/e-dec transmises par le client n'exige aucune licence. Les rectifications et recours restent faits par le client ou son déclarant.
- **Conséquence produit** : pour la Suisse, les constats qui touchent une taxation affichent « délai de rectification court (30 jours, art. 34 LD) : à transmettre sans délai à votre déclarant ».

---

## 3. Emploi : lancer l'activité en restant salarié

### 3.1 France

- **Cumul possible.** Un salarié peut être micro-entrepreneur, à trois conditions :
  - pas de clause d'exclusivité opposable ;
  - pas de concurrence avec l'employeur ;
  - activité exercée hors du temps de travail.

  La loyauté s'applique même sans clause : discrétion, ne pas nuire, ne pas concurrencer. — https://entreprendre.service-public.gouv.fr/vosdroits/F23264 (vu en recherche) ; https://www.economie.gouv.fr/entreprises/gerer-sa-micro-entreprise/peut-cumuler-un-emploi-salarie-et-une-micro-entreprise (vu en recherche)
- **Cass. soc., 14 janv. 2026, n° 24-20.799.** Licenciement pour faute grave validé pour la création d'une micro-entreprise concurrente dans le même secteur, même sans clause de non-concurrence. — actualité Service-Public du 20 mars 2026, lue : https://entreprendre.service-public.gouv.fr/actualites/A18850
- **Art. L1222-5 C. trav.** « L'employeur ne peut opposer aucune clause d'exclusivité pendant une durée d'un an au salarié qui crée ou reprend une entreprise ». — lu : https://code.travail.gouv.fr/code-du-travail/l1222-5
  - Le délai d'un an court à partir de l'immatriculation ou du début d'activité. Il peut être prolongé en cas de congé ou de temps partiel pour création.
  - Exception pour les VRP.
  - **Ni la loyauté ni l'interdiction de concurrence ne sont levées.** — https://www.lecoindesentrepreneurs.fr/clause-dexclusivite-levee-provisoire-creation-reprise-entreprise/ (lu, source secondaire)
  - Après un an, la clause revit : il faudra alors choisir.
  - Une clause d'exclusivité est impossible dans un contrat à temps partiel. — fiche F23264
- **Clause de non-concurrence.** Elle ne joue qu'**après** la rupture. Pendant le contrat, c'est la loyauté qui interdit la concurrence. — https://vives-avocats.fr/creation-entreprise-salarie-obligations-loyaute/ (lu ; cite Cass. soc. 13 févr. 2013 n° 11-27.902 et 11 mars 2008 n° 06-44.467)
- **Logiciel (art. L113-9 CPI).** Les droits patrimoniaux sur un logiciel créé « dans l'exercice de leurs fonctions ou d'après les instructions de leur employeur » appartiennent à l'employeur. Un logiciel créé hors mission, sur son temps et avec ses propres moyens, reste au salarié. Des juges ont toutefois attribué à l'employeur un logiciel créé hors temps de travail **avec le matériel de l'employeur**. — https://justice.pappers.fr/loi/LEGITEXT000006069414/article/LEGIARTI000006278890 (vu en recherche) ; https://www.village-justice.com/articles/logiciel-cree-par-salarie,22069.html (vu en recherche)
- **Inventions (art. L611-7 CPI).** L'employeur peut se faire attribuer, moyennant un « juste prix », une invention « hors mission attribuable » : faite dans le domaine d'activité de l'entreprise ou grâce à ses techniques, moyens ou données. — https://www.village-justice.com/articles/les-inventions-salaries,31977.html (vu en recherche)
- **Agent public des douanes (DGDDI).** S'il l'est, le régime est différent :
  - autorisation préalable de temps partiel pour créer une entreprise (art. L123-8 CGFP, au moins un mi-temps, 3 ans + 1 an) ;
  - saisine du référent déontologue ou de la HATVP en cas de doute sur la compatibilité avec les fonctions des 3 dernières années.

  — https://www.fonction-publique.gouv.fr/etre-agent-public/mes-droits-et-obligations/le-cumul-dactivites-et-les-passages-entre-les-secteurs-public-et-prive (vu en recherche) ; https://www.doctrine.fr/l/texts/codes/LEGITEXT000044416551/articles/LEGIARTI000044427801 (vu en recherche)

**Verdict selon l'employeur.**

| Employeur | Verdict | Raison |
|---|---|---|
| Sans lien avec l'import | **OK sous conditions** | Vérifier l'absence de clause d'exclusivité, sinon s'appuyer sur L1222-5 pendant un an |
| Importateur | **Risque** | Pas de concurrence directe, mais l'employeur est un client potentiel, avec des transitaires et des données confidentielles |
| Transitaire, commissionnaire ou RDE | **Risque élevé** | ControlDOne audite précisément ses factures : déloyauté et dénigrement possibles |
| Éditeur de logiciel douane ou cabinet de conseil douane | **Risque élevé** | Concurrence directe |
| Administration des douanes | **Interdit sans autorisation** | Régime CGFP |

**Règles pratiques, non négociables.**
- Aucun document, aucune grille et aucun nom de transitaire de l'employeur dans les données, les tests ou le référentiel (secret des affaires, loyauté).
- Aucun travail sur le temps ni avec le matériel de l'employeur (L113-9).
- Ne prospecter ni l'employeur, ni ses clients, fournisseurs ou transitaires pendant le contrat.
- Lire le contrat de travail et la convention collective (exclusivité, déclaration des activités annexes, propriété intellectuelle).
- **À faire confirmer par un avocat en droit du travail** : faut-il informer l'employeur par écrit ? L'information est recommandée par les sources secondaires, mais pas toujours obligatoire.

### 3.2 Suisse

- **Art. 321a al. 3 CO.** Pendant le contrat, le travailleur « ne doit pas accomplir du travail rémunéré pour un tiers dans la mesure où il lèse son devoir de fidélité et, notamment, fait concurrence à l'employeur ». Une activité accessoire hors temps de travail n'est pas interdite par principe. — SECO, FAQ activité accessoire (vu en recherche) : https://www.seco.admin.ch/fr/faq-activite-accessoire ; https://www.lausanne.ch/vie-pratique/travail/protection-des-travailleurs/travailleur/contrat-de-travail-regles/devoir-de-fidelite-du-travailleur.html (vu en recherche)
- **Art. 17 LDA.** L'employeur exerce seul les droits sur un logiciel créé « dans l'exercice de son activité au service de l'employeur et conformément à ses obligations contractuelles ». Le lieu et l'heure de création ne sont pas décisifs. — LDA (vu en recherche) : https://fedlex.data.admin.ch/filestore/fedlex.data.admin.ch/eli/cc/1993/1798_1798_1798/20230701/fr/pdf-a/fedlex-data-admin-ch-eli-cc-1993-1798_1798_1798-20230701-fr-pdf-a.pdf
- **Inventions** : art. 332 CO (non relu ici).
- **Verdict : OK sous conditions**, avec les mêmes règles qu'en France. Vérifier si le contrat impose d'annoncer les activités accessoires.

---

## 4. Statut, TVA et facturation

### 4.1 France : statut

- **Micro-entreprise (micro-BNC).** Le régime s'applique de plein droit sous le seuil de recettes.
  - La fiche officielle de mars 2026 indique **77 700 €** (recettes 2025) pour les prestations de services. — PDF lu : https://www.impots.gouv.fr/sites/default/files/media/3_Documentation/depliants/pro_fiche_regimes_reserves_aux_petites_entreprises_2026.pdf
  - Des sources secondaires annoncent **83 600 €** à partir de 2026 (revalorisation triennale) : https://blog.tiime.fr/nouveaux-plafonds-microentrepreneur-chiffre-daffaires (vu en recherche). L'annonce URSSAF n'a pas pu être lue (503) : https://www.autoentrepreneur.urssaf.fr/portail/accueil/sinformer-sur-le-statut/toutes-les-actualites/2026--modification-des-seuils-de.html. **Seuil 2026 à vérifier.** Sans effet au démarrage.
  - Versement libératoire : 2,2 % pour les BNC, sous condition de revenu fiscal de référence (29 315 € par part pour 2026). — même fiche
- **Micro ou SASU ?** Pour un salarié qui teste un marché, la micro-entreprise est la plus simple : déclaration en ligne, comptabilité minimale, cotisations proportionnelles aux recettes. La SASU n'apporte un intérêt qu'avec des charges importantes ou des associés (avis, pas une source).
- **Facture des micro-entrepreneurs.** Mentions « EI » et « TVA non applicable, art. 293 B du CGI » en franchise. — fiche impots.gouv ci-dessus ; https://entreprendre.service-public.gouv.fr/vosdroits/F31228 (cité dans `legal_market.md`)

### 4.2 France : franchise de TVA en 2026

- **Seuils maintenus.** 37 500 € (seuil majoré 41 250 €) pour les services. La franchise est perdue dès le dépassement de 41 250 €.
- **Fin de la saga 2025.**
  - Le seuil unique de 25 000 € de la loi de finances 2025 a été suspendu, puis abrogé par la **loi n° 2025-1044 du 3 novembre 2025**. — Service-Public, actualité du 5 nov. 2025, lue : https://entreprendre.service-public.gouv.fr/actualites/A17995
  - La fiche impots.gouv de mars 2026 confirme que les modifications de la LF 2025, « puis dans la loi de finances pour 2026, ne sont pas entrées en vigueur ». — PDF lu ci-dessus
- **Conséquence pour `config/offres.yaml`.**
  - Au démarrage, `tva_applicable: false` avec la mention art. 293 B.
  - Prévoir le basculement automatique à 41 250 € de recettes dans l'année.
  - Les clients étant assujettis, la franchise ne pénalise pas le prix.

### 4.3 France : facturation électronique et commission

- **Réception.** Obligatoire pour **toutes** les entreprises assujetties depuis le 1er septembre 2026, y compris un micro-entrepreneur en franchise (c'est un assujetti). Il faut donc choisir une plateforme agréée dès maintenant. Voir `einvoice.md` §1.
- **Émission.** Au plus tard le 1er septembre 2027 pour les TPE et micro-entreprises. Voir `einvoice.md` §1.
- **Quatre nouvelles mentions** (SIREN du client, catégorie d'opération, option sur les débits, adresse de livraison). Selon des sources secondaires, elles sont obligatoires pour les PME à partir de leur date d'émission électronique (1er septembre 2027) : https://www.kwixeo.fr/blog/mentions-obligatoires-facture-electronique-2026/ (vu en recherche). **À vérifier sur impots.gouv.** Les mettre dès maintenant ne coûte rien.
- **Moment de facturer la commission.**
  - La facture est émise « dès la réalisation de la prestation ».
  - Une facture **récapitulative mensuelle** est admise : émise au plus tard à la fin du mois civil où la taxe est devenue exigible, avec quelques jours de tolérance. — BOFiP vu en recherche : https://bofip.impots.gouv.fr/bofip/13245-PGP.html/identifiant=BOI-TVA-DECLA-30-20-10-40-20210813
  - **Conséquence** : facturer chaque mois les avoirs **déclarés** par le client le mois précédent. Les CGV doivent le dire.

### 4.4 France : diagnostic « gratuit contre droit de publier » (troc)

- **Règle.** Un échange de services est une « double vente dont le prix est payé en nature ». La base d'imposition comprend les paiements en nature (valeur des services reçus en contrepartie). — BOFiP vu en recherche : https://bofip.impots.gouv.fr/bofip/700-PGP.html/identifiant=BOI-TVA-BASE-10-20-30-20120912 ; https://bofip.impots.gouv.fr/bofip/1461-PGP.html/identifiant=BOI-TVA-BASE-10-10-20220511
- **Risque.** Écrire « diagnostic offert **en échange** du droit de publier » crée un lien direct entre la prestation et une contrepartie (la publicité). C'est une opération à titre onéreux, avec une recette en nature à valoriser (390 €) et à déclarer, y compris en micro.
- **Verdict : Risque**, faible en montant mais facile à éviter. **À faire confirmer par l'expert-comptable.**
- **Solution.** Présenter le diagnostic comme une **remise commerciale de lancement à 100 %**, facturée à 0 €. L'autorisation de publier est demandée **à part**, facultative et révocable avant publication, sans effet sur la gratuité. Il n'y a alors plus de contrepartie.

### 4.5 Suisse

- **Assujettissement TVA.** Il est obligatoire dès 100 000 CHF de chiffre d'affaires mondial pour qui fournit des prestations en Suisse. Mais **sont libérées les entreprises sises à l'étranger** qui fournissent en Suisse « exclusivement des prestations […] soumises à l'impôt sur les acquisitions ». C'est le cas d'un service B2B à un client suisse, selon le principe du lieu du destinataire. Le client suisse paie l'impôt sur les acquisitions s'il n'est pas assujetti et dépasse 10 000 CHF par an. — AFC, page lue : https://www.estv.admin.ch/estv/fr/accueil/taxe-sur-la-valeur-ajoutee/tva-assujettissement/entreprises-etrangeres.html ; https://www.estv.admin.ch/estv/fr/accueil/taxe-sur-la-valeur-ajoutee/tva-assujettissement/impot-acquisitions.html (vu en recherche)
- **Conséquence (fondateur établi en France)** : aucune immatriculation TVA suisse. La facture française porte « Autoliquidation » / « TVA due par le preneur » côté suisse (mention française exacte à faire valider par l'expert-comptable).
- **Si le fondateur s'établit en Suisse** (raison individuelle) : inscription au registre du commerce obligatoire dès 100 000 CHF de chiffre d'affaires annuel (art. 931 CO), facultative en dessous. — https://www.kmu.admin.ch/kmu/fr/home/savoir-pratique/creation-pme/differentes-formes-juridiques/entreprise-individuelle.html (vu en recherche) ; https://www.vs.ch/web/ext-rc/entreprise-individuelle (vu en recherche). Affiliation AVS d'indépendant à vérifier.

---

## 5. Protection des données et IA

### 5.1 Rôles RGPD

| Traitement | Rôle de ControlDOne | Base légale | Statut dans le projet |
|---|---|---|---|
| Documents d'import des clients (noms et coordonnées sur les pièces) | **Sous-traitant** (art. 28) | celle du client | DPA présent (`site/dpa.html`) |
| Prospection, clients, facturation, site | **Responsable** | intérêt légitime ; contrat ; obligation légale | Registre partie 2 présent |
| Référentiel agrégé tiré des dossiers clients | **À clarifier** : l'anonymisation est elle-même un traitement, fait sur instruction du client (sous-traitant) ; le résultat est anonyme et hors RGPD s'il l'est vraiment | instruction du client (DPA) | Texte du DPA à corriger (§9) |

### 5.2 Transferts vers Anthropic (États-Unis)

- **DPF.** Le Tribunal de l'UE a rejeté le recours Latombe le **3 septembre 2025** (T-553/23). Un pourvoi est pendant devant la Cour de justice (**C-703/25 P**, formé le 31 octobre 2025) ; aucune audience n'était annoncée en mai 2026. La décision d'adéquation reste valide à ce jour. — https://iapp.org/news/a/european-general-court-dismisses-latombe-challenge-upholds-eu-us-data-privacy-framework (vu en recherche) ; https://www.wilmerhale.com/en/insights/blogs/wilmerhale-privacy-and-cybersecurity-law/20251201-european-court-of-justice-to-review-challenge-to-eu-us-data-privacy-framework (vu en recherche, page en 503)
- **DPA d'Anthropic (en vigueur depuis le 24 février 2025)** — page lue : https://www.anthropic.com/legal/data-processing-addendum
  - incorpore les **CCT modules 2 et 3**, sous droit irlandais ;
  - contient un **addendum suisse** (PFPDT compétent) et un addendum britannique ;
  - préavis « raisonnable » pour les nouveaux sous-traitants, avec **15 jours** pour s'opposer ;
  - notification d'incident sous **48 h** ;
  - suppression ou restitution sous 30 jours en fin de contrat.
- **Certification DPF d'Anthropic.** Les sources secondaires se contredisent (« pas de certification » contre « participe au DPF ») : https://compound.law/en-DE/tools/anthropic-scc/ (vu en recherche). **À vérifier sur dataprivacyframework.gov.** Dans tous les cas, les CCT suffisent comme garantie.
- **Verdict : OK sous conditions.**
  - Fonder le transfert sur les CCT du DPA d'Anthropic, sans dépendre du DPF.
  - Faire une analyse d'impact du transfert (TIA) courte.
  - Minimiser : n'envoyer que des pages sans données personnelles inutiles.
  - Garder l'option « LLM désactivé » (déjà prévue).
  - Aligner le DPA client sur les délais d'Anthropic : on ne peut pas promettre 30 jours de préavis si Anthropic n'en garantit que 15 d'opposition.

### 5.3 Prospection B2B par e-mail : France

- **Régime.** Opt-out B2B si le message est en rapport avec la fonction ; identification ; désinscription dans chaque message ; opposition possible dès la collecte. Déjà sourcé dans `legal_market.md` §1 (https://www.cnil.fr/fr/la-prospection-commerciale-par-courrier-electronique).
- **Durée de conservation : 3 ans confirmés.** Les données d'un prospect peuvent être conservées « trois ans à compter de leur collecte […] ou du dernier contact **émanant du prospect** ». La simple ouverture d'un e-mail n'est pas un contact. Le référentiel couvre aussi la prospection « à destination de professionnels ». — référentiel CNIL « gestion des activités commerciales », PDF lu : https://www.cnil.fr/sites/cnil/files/atoms/files/referentiel_traitements-donnees-caractere-personnel_gestion-activites-commerciales.pdf
- **Conséquence** : un e-mail **envoyé** par ControlDOne ne relance pas le délai. Corriger le registre et la politique de confidentialité.

### 5.4 Anonymisation et référentiel par transitaire

- **Trois critères (G29, repris par la CNIL).** Impossible d'isoler une personne (individualisation), de relier des jeux de données (corrélation) ou de déduire une information (inférence). Des données agrégées ne sont anonymes que si les événements individuels ne sont plus identifiables. — https://cnil.fr/fr/technologies/lanonymisation-de-donnees-personnelles (vu en recherche) ; avis WP216 : https://www.cnil.fr/sites/default/files/atoms/files/wp216_fr.pdf (vu en recherche)
- **Les données de prix sont surtout des données d'entreprises.** Elles relèvent moins du RGPD que :
  1. de la **confidentialité contractuelle** entre le client et son transitaire (grilles négociées) ;
  2. du **dénigrement**.
- **Dénigrement.** Divulguer une information qui jette le discrédit sur les services d'une entreprise est fautif, même sans concurrence entre les parties, sauf sujet d'intérêt général, **base factuelle suffisante** et **mesure** dans l'expression (jurisprudence de la Cour de cassation, Cass. com. 4 mars 2020, n° 18-15.651 selon les sources secondaires). — https://novlaw.fr/ressource/denigrement-en-droit-des-affaires-definition-jurisprudence-preuve-et-recours-devant-le-juge (vu en recherche) ; https://www.actu-juridique.fr/affaires/societes/deloyaute-par-denigrement-et-evidence-de-linformation-portee-a-la-connaissance-du-public/ (vu en recherche)
- **Verdict : OK sous conditions.**
  - Publier des **statistiques de prix**, pas des « taux d'erreur » par transitaire **nommé**.
  - Ne nommer un transitaire qu'avec son **accord écrit**. Retirer la mention « ou acteur notoire » de `referentiel_alias_publics.yaml`.
  - Le client garantit qu'il peut transmettre les grilles.
- **Point à faire confirmer par un avocat** : un benchmark de prix par transitaire, même agrégé, est un échange d'informations au sens du droit de la concurrence. Il est a priori sans risque s'il est historique, agrégé et public, mais à vérifier.

### 5.5 Prospection : Suisse et Belgique

- **Suisse (art. 3 al. 1 let. o LCD).** Les envois **de masse** exigent le **consentement préalable** (opt-in), en B2B comme en B2C, avec identification et désinscription. Exception : clients existants, pour des produits analogues. — OFCOM, lu : https://www.bakom.admin.ch/fr/quand-les-envois-en-masse-sont-ils-autorises ; https://swissprivacy.law/412/ (lu)
- **Envoi individuel.** Selon une source secondaire, un envoi individuel et personnalisé, en lien avec l'activité du destinataire, n'est pas un envoi « de masse ». — https://proxio.ch/blog/cold-email-suisse-lpd-legal/ (vu en recherche). **À faire confirmer par un avocat suisse.**
- **Conséquence Suisse** : des e-mails rédigés un par un (ce que prévoit déjà `sequence_emails.md`), jamais d'outil d'envoi groupé, et relances limitées.
- **Belgique.** Prospection par e-mail sans consentement admise vers des adresses **impersonnelles** de personnes morales (info@). Une adresse nominative exige le consentement (AR du 4 avril 2003 ; art. XII.13 CDE). — https://www.ejustice.just.fgov.be/eli/arrete/2003/04/04/2003011238/justel (vu en recherche) ; https://www.digitalwallonia.be/fr/publications/regles-publicite-en-ligne/ (vu en recherche)

### 5.6 AI Act (règlement (UE) 2024/1689, modifié par le règlement (UE) 2026/1744)

- **Règlement « Digital Omnibus IA » = règlement (UE) 2026/1744**, en vigueur depuis le **27 juillet 2026**. — page lue : https://artificialintelligenceact.eu/ai-act-explorer/digital-omnibus/
  - Systèmes à haut risque de l'annexe III reportés au **2 décembre 2027**, ceux de l'annexe I au 2 août 2028.
  - L'art. 4 (culture de l'IA) est reformulé : prendre des mesures pour soutenir la maîtrise de l'IA.
  - L'art. 50(2) (marquage des contenus synthétiques) s'applique au **2 décembre 2026** pour les systèmes déjà sur le marché.
- **Qualification de ControlDOne.**
  - Lire des documents pour en extraire des données n'est pas un usage de l'annexe III : **pas de haut risque**.
  - ControlDOne est **déployeur** d'un modèle à usage général. S'il intègre le modèle dans son propre service, il est sans doute aussi **fournisseur** d'un système d'IA.
  - L'art. 50(2) vise les systèmes qui **génèrent du texte synthétique**. Si le LLM rédige les courriers, il faudrait un marquage, sauf exception pour une « fonction d'assistance » à l'édition. **À faire confirmer.**
- **Verdict : OK.** Le plus simple est de limiter le LLM à l'extraction et de produire les courriers à partir de gabarits fixes, ce qui sert aussi le §1. Ajouter une phrase de transparence dans les CGV et le DPA.

### 5.7 Suisse : nLPD (en vigueur depuis le 1er septembre 2023)

- **Sous-traitance (art. 9 LPD).** Un contrat est nécessaire ; le DPA actuel peut couvrir la LPD avec une clause d'extension.
- **Transferts.** Les pays de l'UE sont adéquats (annexe 1 OPDo). États-Unis : **Swiss-US DPF** en vigueur depuis le **15 septembre 2024**, seulement pour les entreprises certifiées ; à défaut, CCT avec addendum suisse (prévu par le DPA d'Anthropic). — https://www.homburger.ch/en/insights/new-swiss-u-s-data-privacy-framework (vu en recherche)
- **Registre.** Dispense si moins de 250 collaborateurs, sauf données sensibles à grande échelle ou profilage à risque élevé (art. 24 OPDo). — https://www.activemind.ch/fr/legislation/opdo/article-24/ (vu en recherche). Le registre RGPD tenu de toute façon suffit.
- **Sanctions.** Amendes **jusqu'à 250 000 CHF visant la personne physique responsable**, pas l'entreprise, notamment pour manquement au devoir d'informer ou à la diligence en sous-traitance (art. 60-61). — https://www.cnci.ch/la-revision-de-la-loi-federale-sur-la-protection-des-donnees-et-son-impact-pour-les-entreprises (vu en recherche) ; https://obersonabels.com/wp-content/uploads/2023/10/Pahud-Pittet-Jusletter-2023-infractions-penales-LPD.pdf (vu en recherche)
- **Devoir d'informer.** Art. 19 (non relu).
- **Représentant en Suisse.** Art. 14 LPD (non relu). Il est exigé seulement si le traitement est à grande échelle, régulier et à risque élevé, ce qui est improbable ici. **À confirmer.**
- **Verdict : OK sous conditions** : clause LPD dans le DPA et la politique de confidentialité, mention du PFPDT.

---

## 6. Contrats

### 6.1 CGV B2B (France)

- **Bases.** Mentions de L441-1, délais et pénalités de L441-10, indemnité de 40 € (D441-5) : sourcés dans `legal_market.md` §4. Les CGV actuelles les reprennent correctement (art. 10).
- **Limitation de responsabilité.** Une clause qui « prive de sa substance l'obligation essentielle du débiteur est réputée non écrite » (art. 1170 C. civ., qui codifie Chronopost 1996 et Faurecia, Cass. com. 29 juin 2010, n° 09-11.841). Un plafond n'est écarté que s'il est **dérisoire**. — https://gdroit.fr/droit-des-contrats/lobligation-essentielle-du-contrat-ou-la-consecration-des-jurisprudences-chronopost-et-faurecia/ (vu en recherche) ; https://www.village-justice.com/articles/arret-Faurecia-revolution,8173.html (vu en recherche)
  - **Risque.** Pour un diagnostic gratuit (offre de lancement), le plafond « montant payé sur 12 mois » vaut **0 €** : il est dérisoire, donc la clause tombe.
  - **Correction** : plancher fixe, par exemple « ou, s'il est supérieur, [5 000] EUR », aligné sur le plafond de la RC Pro.
- **Clause de commission.** Licite si le service n'est pas juridique (§1). La rendre vérifiable :
  - assiette HT ;
  - liste fermée de ce qui est exclu ;
  - période fixe ;
  - facturation mensuelle ;
  - preuve par le registre ;
  - pas de commission sur les remboursements de l'administration.
- **Publication des résultats anonymisés.** Accord **séparé**, écrit et révocable avant publication, avec relecture par le client. Ne nommer aucun transitaire sans son accord (§5.4).
- **Confidentialité.** Ajouter une garantie du client : il peut transmettre les grilles et factures de ses transitaires malgré d'éventuelles clauses de confidentialité.
- **Petits clients (art. L221-3 C. conso).** Le droit de rétractation de 14 jours, les obligations d'information et la nullité s'étendent au professionnel :
  - employant **5 salariés au plus** ;
  - pour un contrat **conclu hors établissement** (présence physique, hors des locaux du prestataire) ;
  - dont l'objet n'entre pas dans son **activité principale**.

  Selon la Cour de cassation (Cass. com. 4 sept. 2024, n° 23-16.886, d'après la source secondaire), les **contrats à distance** (e-mail, en ligne, téléphone) ne sont pas concernés. — https://kohenavocats.fr/2026/09/18/droit-retractation-entre-professionnels-article-l221-3-code-consommation-nullite/ (lu) ; https://dunan-avocats.fr/2026/03/02/champ-activite-principale-l221-3-contrat-hors-etablissement-professionnels/ (vu en recherche)

  **Conséquence** : faire signer à distance (devis accepté par e-mail ou en ligne), jamais sur place chez un client de 5 salariés au plus. Sinon, remettre le formulaire de rétractation. La phrase des CGV « Elles ne s'appliquent pas aux consommateurs » ne suffit pas à écarter ce régime.
- **Recouvrement amiable pour autrui.** Quiconque procède, même occasionnellement, au recouvrement amiable de créances pour autrui doit :
  - avoir une assurance RC ;
  - avoir un compte bancaire dédié ;
  - signer une convention écrite avec le créancier ;
  - faire une déclaration préalable au procureur (art. R124-1 s. CPCE).

  — https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000025024948/LEGISCTA000025938360/ (vu en recherche)

  **Conséquence** : ControlDOne ne doit jamais relancer le transitaire, encaisser ou recevoir des fonds. Les textes doivent dire « suivi des avoirs », pas « suivi du recouvrement ».

### 6.2 Prescripteurs : experts-comptables

- **Art. 24 de l'ordonnance n° 45-2138.** Les honoraires des experts-comptables sont « exclusifs de toute autre rémunération indirecte, d'un tiers, à quelque titre que ce soit ». — Légifrance, lu : https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000038586826 (et texte vu en recherche)
- **Art. 22.** L'activité est incompatible avec « toute activité commerciale ou acte d'intermédiaire » autre que ceux de la profession, sauf à titre accessoire et sans mettre en péril la déontologie. — Légifrance, lu : https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000038586819
- **Art. 162 du code de déontologie.** La collaboration rémunérée avec d'autres professionnels est admise pour des affaires déterminées, dans le respect des règles. — Légifrance, lu (résumé) : https://www.legifrance.gouv.fr/codes/id/LEGISCTA000025599334
- **Verdict : Interdit** de verser une commission d'apport à un expert-comptable pour ses clients.
  - Admis : un partenariat sans rémunération. Le cabinet facture ses propres honoraires à son client pour l'exploitation du rapport.
  - **À faire confirmer** auprès du Conseil régional de l'Ordre : une prestation réelle facturée par le cabinet à ControlDOne est-elle possible ?
- **Autres apporteurs (non réglementés).** Commission possible par contrat écrit. Attention à ne pas créer un statut d'agent commercial (indemnité de fin de contrat) : à rédiger avec un avocat.

### 6.3 Suisse

- **Art. 100 al. 1 CO.** Est nulle toute exclusion anticipée de responsabilité pour dol ou faute grave. La clause actuelle (« ces limites ne s'appliquent pas en cas de faute lourde ou dolosive ») est compatible. — https://admintech.ch/fr-ch/contrats-de-services/comment-limiter-la-responsabilite-contractuelle/ (vu en recherche)
- **Droit applicable et for.** Pour les clients suisses, un choix du droit français et du for de [ville] est en principe possible en B2B. **À faire confirmer** (reconnaissance d'un jugement français en Suisse : Convention de Lugano).

---

## 7. Site web

- **Mentions légales (art. 1-1 LCEN depuis la loi SREN).** Le brouillon `mentions-legales.html` est complet dans sa structure. Deux ajouts :
  - pour un entrepreneur individuel, le nom suivi de « EI » ;
  - l'immatriculation au **RNE** (une micro-entreprise BNC n'est pas au RCS).

  Sources dans `legal_market.md` §4.
- **Cookies.** Aucun cookie ni traceur : pas de bandeau nécessaire. **OK.**
- **Accessibilité (directive (UE) 2019/882, en application depuis le 28 juin 2025).** Elle vise certains services **aux consommateurs** (commerce électronique…). Les **micro-entreprises qui fournissent des services** en sont exclues (moins de 10 salariés et moins de 2 M€). — https://www.august-debouzy.com/fr/blog/2215-entree-en-vigueur-de-la-directive-ue-2019882-laccessibilite-by-design (vu en recherche) ; https://www.fevad.com/e-commerce-et-accessibilite-numerique-ce-qui-change-a-partir-de-juin-2025/ (vu en recherche). **Verdict : non applicable** (B2B et micro). Bonne pratique : viser le RGAA sans le déclarer.
- **Nom et marque.** Avant dépôt et publication, chercher « ControlDOne » et les variantes proches (« Control Done », « ControlD ») :
  - bases INPI (data.inpi.fr), EUIPO (TMview) et Swissreg ;
  - noms de domaine ;
  - RNE.

  Déposer au moins en France, classes 35, 36 et 42 (choix des classes à faire confirmer par un conseil en propriété industrielle). Aucune recherche d'antériorité n'a été faite ici.

---

## 8. Assurance

- **RC Pro.** Elle n'est pas légalement obligatoire pour un consultant non réglementé, mais elle est essentielle, car le risque principal est le **dommage immatériel non consécutif** (perte financière due à une erreur de calcul). — https://www.giva.fr/blog/assurance-professionnelle-consultant (vu en recherche) ; https://brokin.fr/couverture-contre-les-dommages-immateriels/ (vu en recherche)
- **Exclusions fréquentes** : engagements de résultat, amendes et pénalités, activités non déclarées, faute intentionnelle. — https://www.rcpro.fr/lexique-exclusion-garantie/ (vu en recherche)
- **Conséquences.**
  1. Déclarer l'activité exacte à l'assureur (« contrôle de cohérence documentaire et arithmétique, sans conseil juridique ni douanier »). Une activité mal déclarée ouvre une exclusion.
  2. Vérifier que les **dommages immatériels non consécutifs** et la **cyber** (fuite de documents clients) sont couverts.
  3. Ne jamais promettre de résultat (déjà dans `formulations_interdites.yaml`).
  4. Aligner le plafond des CGV sur celui de l'assurance.
- **Activité exercée hors du champ légal.** Elle risque la nullité du contrat (§1) **et** un refus de garantie. C'est une raison de plus pour les garde-fous du §1.

---

## 9. Modifications proposées dans les fichiers du projet

*Je n'ai modifié aucun fichier. Textes à reprendre après relecture par un avocat.*

### 9.1 `site/cgv.html`

| Article | Texte actuel | Texte proposé |
|---|---|---|
| 1 | « Elles ne s'appliquent pas aux consommateurs. » | « Elles ne s'appliquent pas aux consommateurs. Le contrat est conclu à distance (acceptation du devis par écrit électronique). Lorsqu'il est exceptionnellement conclu hors établissement avec un professionnel employant au plus cinq salariés et pour un objet n'entrant pas dans le champ de son activité principale, le Client bénéficie des articles L221-3 et suivants du Code de la consommation, notamment d'un droit de rétractation de quatorze jours. » |
| 2 | « Demande d'avoir : courrier préparé pour le Client, à son nom, qu'il peut adresser à son transitaire. » | « Relevé d'écarts : document factuel qui présente, pour chaque écart, les valeurs comparées, leur emplacement dans les documents et le calcul. Il est accompagné d'un modèle de courrier neutre que le Client complète, modifie, signe et envoie lui-même s'il le décide. » (remplacer « demande d'avoir » par « relevé d'écarts » dans tout le texte) |
| 3 | « Le Prestataire constate des écarts factuels, documentaires et contractuels entre documents. » | « Le Prestataire constate des écarts factuels (calculs), documentaires (deux documents ne portent pas la même valeur) et tarifaires (un montant facturé diffère du prix chiffré figurant dans la grille ou le devis transmis par le Client). Lorsqu'une comparaison suppose d'interpréter une clause d'un contrat ou de conditions générales, elle est signalée comme « à faire vérifier », sans montant certain. » |
| 3 (ajout) | — | « Le Prestataire n'accomplit aucun acte ou formalité auprès de l'administration des douanes, ne dépose ni ne rectifie aucune déclaration, ne prépare aucune demande de remboursement ou de remise de droits et ne rédige aucune mise en demeure ni réclamation contentieuse. » |
| 4 | « Contrôle des nouveaux dossiers à réception, suivi du recouvrement. » | « Contrôle des nouveaux dossiers à réception, suivi des avoirs reçus. » |
| 5 | « Assiette : montants [HT OU TTC]. » | « Assiette : montant hors taxes des avoirs émis par un transitaire. Sont exclus de l'assiette les remboursements, remises ou dégrèvements accordés par une administration, notamment douanière ou fiscale. » |
| 5 | « La commission est facturée [À COMPLÉTER : mensuellement / à chaque avoir]. » | « La commission est facturée mensuellement, par facture récapitulative, au titre des avoirs déclarés au cours du mois précédent. » |
| 6 | « Les demandes d'avoir sont préparées pour que le Client les envoie lui-même, à son nom, sans signature du Prestataire. » | « Le relevé d'écarts et son modèle de courrier sont remis au Client, qui décide seul de leur usage. Le modèle se borne à exposer les écarts constatés et à demander au transitaire de vérifier sa facture et d'indiquer s'il émettra un avoir ; il ne cite aucune règle de droit ni ne qualifie juridiquement la situation. Le Prestataire ne contacte jamais le transitaire, ne relance pas pour le compte du Client et n'encaisse aucune somme pour son compte. » |
| 7 (ajout) | — | « Le Client garantit qu'il est en droit de communiquer au Prestataire les factures, devis et grilles tarifaires de ses transitaires, au regard des engagements de confidentialité qui le lient à eux. » |
| 11 | « …au montant hors taxes payé par le Client au titre du contrat pendant les 12 mois précédant le fait générateur [À VALIDER]. » | « …au montant hors taxes payé par le Client au titre du contrat pendant les 12 mois précédant le fait générateur ou, s'il est supérieur, à [5 000] EUR. » (aligner sur la RC Pro) |
| 14 | « les transitaires y sont désignés par un identifiant non réversible, sauf alias public » | « les transitaires y sont désignés par un identifiant non réversible ; un transitaire n'est nommé qu'avec son accord écrit. Le référentiel publie des statistiques de prix, jamais de taux d'écart ou d'erreur attribués à un transitaire identifiable. » |
| 15 | « …le diagnostic peut être fourni sans frais en échange de l'autorisation de publier les résultats… » | « Dans la limite de trois clients, le diagnostic est fourni avec une remise commerciale de lancement de 100 %. Le Prestataire propose en outre au Client, par un accord distinct et facultatif, d'autoriser la publication de résultats anonymisés dans les conditions de l'article 14 ; le Client relit le texte avant publication et peut retirer son accord jusque-là, sans effet sur la remise. » |
| 13 (ajout) | — | « Le modèle de langage éventuellement utilisé sert à lire les documents ; les relevés et modèles de courrier sont produits à partir de gabarits. Pour les Clients établis en Suisse, l'accord de sous-traitance vaut contrat au sens de l'article 9 de la loi fédérale sur la protection des données. » |

### 9.2 `site/dpa.html`

| Article | Texte actuel | Texte proposé |
|---|---|---|
| 3 | « Le Prestataire n'utilise pas les données pour ses propres finalités, sous réserve de la production de statistiques agrégées et anonymisées prévue à l'article 14 des CGV, qui ne contiennent aucune donnée personnelle. » | « Sur instruction du Client, le Prestataire anonymise et agrège des données tarifaires issues des dossiers validés pour constituer le référentiel prévu à l'article 14 des CGV ; aucune donnée personnelle n'est utilisée dans ce calcul ni n'y figure. Le Client peut retirer cette instruction à tout moment. » |
| 3 | « lecture automatisée (structurée, déterministe et, si le Client ne l'a pas désactivée, par modèle de langage) » | Inchangé. Retirer « et rédaction de textes » dans le tableau de l'article 7 si les courriers passent en gabarits. |
| 7 (tableau, ligne LLM) | « [À COMPLÉTER : fournisseur du modèle de langage…] » ; « [À COMPLÉTER : clauses contractuelles types ou autre garantie] » | « Anthropic, PBC (États-Unis) — lecture de pages de documents — États-Unis — clauses contractuelles types (décision (UE) 2021/914, modules 2 et 3) incorporées à l'accord de traitement d'Anthropic du 24 février 2025 ; addendum suisse pour les données soumises à la LPD. Désactivable par le Client. » |
| 7 | « au moins 30 jours à l'avance » | « dès qu'il en est lui-même informé et au moins 15 jours à l'avance » (Anthropic ne garantit qu'un préavis « raisonnable » et 15 jours d'opposition) |
| 8 | « Si le fournisseur du modèle de langage traite des données hors de l'Union, le Client en est informé avant la signature… » | « Lorsque la lecture par modèle de langage est activée, des pages de documents sont transférées aux États-Unis vers Anthropic, PBC, sur le fondement des clauses contractuelles types ; le Prestataire tient à disposition du Client son évaluation de ce transfert. Le Client peut désactiver ce mode à tout moment, sans frais. » |
| Ajout (art. 14 nouveau) | — | « Protection des données suisse : pour les données soumises à la loi fédérale sur la protection des données (LPD), les références au RGPD s'entendent des dispositions correspondantes de la LPD, et l'autorité de contrôle est le Préposé fédéral à la protection des données et à la transparence (PFPDT). » |

### 9.3 `site/confidentialite.html`

| Rubrique | Texte actuel | Texte proposé |
|---|---|---|
| Durée de prospection | « 3 ans après le dernier contact [À VALIDER] » | « 3 ans à compter de la collecte ou du dernier contact émanant de vous (réponse, demande) ; la liste d'opposition est conservée pour la respecter » |
| Prospection | « Aucune donnée n'est collectée par extraction automatisée de réseaux sociaux. » | Ajouter : « Votre adresse provient de [la page de votre site où l'entreprise la publie] ; cette source est indiquée dans le premier message. » |
| Transferts | « [À COMPLÉTER : indiquer tout transfert…] » | « Aucun transfert hors de l'Union européenne pour les données décrites ici [à vérifier selon la messagerie choisie]. Pour les documents des clients qui ont activé la lecture par modèle de langage, voir l'accord de sous-traitance. » |
| Vos droits | « …auprès de la CNIL (cnil.fr). » | « …auprès de la CNIL (cnil.fr) ; si vous êtes en Suisse, auprès du PFPDT (edoeb.admin.ch). » |

### 9.4 `site/mentions-legales.html`

- « Immatriculation : [À COMPLÉTER : SIREN / RCS et ville du greffe] » → « Immatriculation : SIREN [ ] — immatriculé au Registre national des entreprises (RNE) ».
- « Nom ou dénomination : [À COMPLÉTER : nom et prénom suivis de « EI »… » : à conserver tel quel.

### 9.5 `site/tarifs.html`, `site/index.html`, `site/methode.html`

| Fichier | Texte actuel | Texte proposé |
|---|---|---|
| `tarifs.html` | « Suivi du recouvrement et relances suggérées » | « Suivi des avoirs reçus et rappels de vos échéances internes » |
| `tarifs.html` | « Demandes d'avoir prêtes, à envoyer par vos soins » | « Relevé d'écarts et modèle de courrier, à utiliser par vos soins » |
| `tarifs.html`, offre de lancement | « Trois diagnostics offerts — En échange du droit de publier les résultats… » | « Trois diagnostics offerts (remise de lancement). Si vous l'acceptez, et seulement dans ce cas, nous publions ensuite des résultats anonymisés, après votre relecture. » |
| `index.html` | « ControlDOne constate des écarts factuels et contractuels entre documents. » | « ControlDOne constate des écarts factuels, documentaires et tarifaires entre documents. » |
| `index.html`, offre de lancement | « En échange, elles acceptent que les résultats soient publiés… » | « Si elles l'acceptent, par un accord distinct, des résultats anonymisés sont ensuite publiés… » |
| `methode.html` | « et contractuels (une ligne facturée sort de la grille convenue) » | « et tarifaires (une ligne facturée diffère du prix chiffré de la grille que vous nous transmettez ; toute question d'interprétation du contrat vous est signalée à part) » |

### 9.6 `site/experts-comptables.html`

- **Texte actuel** : « Rémunération du cabinet : à valider [À VALIDER] Nous ne promettons aucune rétrocession ni commission d'apport. … »
- **Texte proposé** : « Aucune commission d'apport n'est versée aux cabinets : l'article 24 de l'ordonnance du 19 septembre 1945 prévoit que les honoraires de l'expert-comptable sont exclusifs de toute rémunération indirecte d'un tiers. Le cabinet facture librement à son client le temps qu'il consacre à l'exploitation du rapport. »

### 9.7 `config/offres.yaml`

- `coupons.LANCEMENT-3-DIAGNOSTICS.libelle: "Offre de lancement : diagnostic gratuit contre le droit de publier les résultats anonymisés"` → `"Remise de lancement (100 %) — accord de publication proposé séparément"`.
- `consentement_requis: true` → le remplacer par `consentement_publication: optionnel`, sans effet sur la remise.
- `tva.tva_applicable: true` → `false` au démarrage (franchise art. 293 B, seuil 37 500 € / 41 250 €). Ajouter un champ pour le seuil majoré et l'alerte de dépassement.
- `commission`, ajouter : `assiette: HT`, `exclusions: ["remboursements ou remises accordés par une administration"]`, `facturation: mensuelle_recapitulative`.
- Ajouter la mention Suisse : `mention_autoliquidation_ch` (texte à valider par l'expert-comptable).

### 9.8 `config/formulations_interdites.yaml` (nouvelle catégorie)

```yaml
  - id: acte_juridique_pour_autrui
    pourquoi: Le modèle de courrier ne doit pas devenir un acte juridique ni une réclamation contentieuse
    remplacer_par: Exposé des valeurs comparées et demande de vérification
    expressions:
      - mise en demeure
      - nous vous mettons en demeure
      - en application de l'article
      - conformément aux dispositions
      - à défaut de régularisation
      - action en justice
      - nous nous réservons le droit
      - vous êtes tenu de
  - id: recouvrement_pour_autrui
    pourquoi: Pas de recouvrement amiable pour autrui (art. R124-1 s. CPCE)
    remplacer_par: « suivi des avoirs reçus »
    expressions:
      - suivi du recouvrement
      - relance au transitaire
```

Pour la publication : interdire « taux d'erreur » associé à un nom de transitaire, dans les sorties du référentiel.

### 9.9 `config/referentiel_alias_publics.yaml`

- **Texte actuel** : « Ne lister qu'un transitaire dont le nom peut être rendu public (accord écrit ou acteur notoire) »
- **Texte proposé** : « Ne lister qu'un transitaire qui a donné son accord écrit (référence de l'accord à indiquer) ».

### 9.10 `docs/RGPD_registre.md`

- §2.1 Durée : « 3 ans après le dernier contact [À VALIDER] » → « 3 ans à compter de la collecte ou du dernier contact émanant du prospect (référentiel CNIL gestion des activités commerciales) ».
- §1.3 et §1.4 (ligne LLM) : « Anthropic, PBC — États-Unis — CCT modules 2 et 3 (DPA Anthropic du 24/02/2025), addendum suisse ; TIA à rédiger ».
- **Ajouter** un traitement « Anonymisation pour le référentiel », fait en qualité de sous-traitant sur instruction du client.
- **Ajouter** une section « Suisse » : registre non obligatoire (art. 24 OPDo) mais tenu ; autorité : PFPDT.

### 9.11 `commercial/prospects_methode.md`

- §5, dernier point (« …elle n'a pas été relue sur cnil.fr lors de cette collecte : **à vérifier** ») → « Confirmé : référentiel CNIL "gestion des activités commerciales" (3 ans à compter de la collecte ou du dernier contact émanant du prospect ; la simple ouverture d'un e-mail ne compte pas) ».
- **Ajouter** une section « Suisse et Belgique » :
  - Suisse : opt-in pour tout envoi de masse (art. 3 al. 1 let. o LCD), donc uniquement des e-mails individuels et personnalisés, sans outil d'envoi groupé ;
  - Belgique : adresses impersonnelles (info@) seulement, sans consentement ; adresses nominatives exclues.
- **Ajouter** : ne jamais prospecter l'employeur actuel du fondateur, ni ses clients, fournisseurs ou transitaires.

### 9.12 `commercial/sequence_emails.md`

| Message | Texte actuel | Texte proposé |
|---|---|---|
| E-mail 1 | « En échange, je demande le droit de publier les résultats sous forme anonymisée… » | « Si vous l'acceptez ensuite, par un accord séparé, je publierai des résultats anonymisés (ni nom, ni montant permettant de vous reconnaître), après votre relecture. » |
| E-mail 1, variante DAF | « Une ligne de TVA refacturée alors que la TVA à l'importation est autoliquidée sur la déclaration de TVA… » | « Une ligne de TVA refacturée alors que la déclaration en douane indique l'autoliquidation… » (constat entre documents, pas d'affirmation fiscale) |
| E-mail 2, LinkedIn | « contre le droit de publier les résultats anonymisés » | « avec, si vous l'acceptez, publication de résultats anonymisés » |
| Pied commun | « [Prénom Nom], fondateur de ControlDOne, [SIREN à compléter] » | « [Prénom Nom] EI, fondateur de ControlDOne, SIREN [ ] » |

### 9.13 `docs/MACF.md`

Aucun changement de fond. Ajouter au §2 : « ControlDOne n'est pas déclarant MACF autorisé et n'agit pas en qualité de représentant ; les brouillons aux fournisseurs sont des courriers commerciaux du client, sans qualification juridique. »

---

## 10. Points à faire confirmer par un avocat (liste pour le rendez-vous)

1. **Périmètre du droit (France).** Le relevé d'écarts et son modèle de courrier neutre (§1.3, §9.1 art. 6) échappent-ils à la « rédaction d'actes pour autrui » et à la « consultation » ? La commission de 20 % aggrave-t-elle le risque de requalification ?
2. Les comparaisons « contre la grille » restent-elles du calcul quand la grille est un devis chiffré, et à partir de quand deviennent-elles une interprétation de contrat ?
3. Existe-t-il en droit douanier un équivalent de l'art. L244-13 CSS (nullité des rémunérations d'intermédiaires sur des remises) ?
4. **Contrat de travail du fondateur** : clause d'exclusivité, L1222-5, information de l'employeur, propriété intellectuelle (selon l'employeur réel).
5. Référentiel par transitaire : dénigrement et droit de la concurrence (échange d'informations).
6. Formulation des CGV : plafond de responsabilité, L221-3, durée de la commission après la fin du contrat.
7. **Expert-comptable** : traitement fiscal de l'offre de lancement restructurée ; mention de facture pour les clients suisses ; seuil micro 2026.
8. **Luxembourg** : monopole de la consultation, à vérifier avant toute vente.
9. **Suisse** : prospection individuelle hors « masse » (LCD), agents d'affaires cantonaux, choix du droit et du for.
10. AI Act : l'art. 50(2) s'applique-t-il si le LLM est limité à l'extraction ? (Probablement non.)

---

## Annexe A — Report des modifications du §9 (2 octobre 2026)

*Ajout postérieur à la recherche : les textes du §9 ont été reportés dans les fichiers du projet (site, CGV, DPA, confidentialité, mentions légales, `config/offres.yaml`, `config/referentiel_alias_publics.yaml`, registre RGPD, textes commerciaux, `docs/MACF.md`, `docs/FACTURATION.md`, `README.md`, `RAPPORT_DU_MATIN.md`). Tout reste un brouillon à relire par un avocat. Points non reportés ou reportés en partie :*

- **`config/offres.yaml`, `consentement_requis`** : laissé à `true`. Le code (`ServiceFacturation.proposer_diagnostic`) suppose un consentement présent ; avec `false` et sans consentement, il lève `AttributeError`. Le champ cible `consentement_publication: optionnel` est ajouté, à titre descriptif. Tant que le code n'est pas corrigé, le coupon de lancement exige encore un accord de publication signé, ce qui contredit le §4.4 : **à corriger dans le code avant le premier diagnostic**.
- **`config/offres.yaml`, seuils de franchise, alerte de dépassement et mention suisse** : champs ajoutés, mais non lus par le code (aucune alerte ni mention imprimée à ce jour).
- **`config/formulations_interdites.yaml`** : non modifié (fichier tenu par l'équipe garde-fous). Catégories proposées ci-dessous (annexe B).
- **Rapport de démonstration `site/demo/report.html`** : produit par le moteur ; il emploie encore « demande d'avoir ». À régénérer après la mise à jour des gabarits du moteur.
- **Brouillons Gmail déposés le 2 octobre 2026** : ils portent l'ancienne formulation de l'offre de lancement. Les fichiers `commercial/brouillons/` sont à jour ; le texte des brouillons Gmail est à remplacer avant tout envoi.

## Annexe B — Catégories proposées pour `config/formulations_interdites.yaml`

Complètent le §9.8. **Portée à régler avant intégration** : `test_aucune_formulation_interdite` applique la liste à toutes les pages du site. Or les CGV emploient légitimement « mise en demeure » (art. 3 : le Prestataire « ne rédige aucune mise en demeure » ; art. 9 et 10 : mise en demeure entre les parties). La catégorie `acte_juridique_pour_autrui` du §9.8 doit donc viser les **modèles de courrier et les sorties du moteur** seulement, ou le test doit exclure les pages juridiques (`cgv.html`, `dpa.html`). De même, « taux d'erreur » figure dans `commercial/sequence_emails.md` pour dire qu'aucun chiffre n'existe : la règle sur le référentiel doit viser ses seules sorties.

```yaml
  - id: contrepartie_publication
    pourquoi: L'offre de lancement est une remise ; la publication n'en est pas la contrepartie (troc taxable, §4.4)
    remplacer_par: « remise de lancement ; si vous l'acceptez, par un accord séparé, publication de résultats anonymisés »
    expressions:
      - en échange du droit de publier
      - en échange de l'autorisation de publier
      - contre le droit de publier
      - contre le droit d'en publier
      - en contrepartie de la publication
  - id: qualification_contractuelle
    pourquoi: Qualifier un écart de « contractuel » suppose d'interpréter un contrat (§1.3)
    remplacer_par: « écart tarifaire chiffré contre la grille transmise par le client »
    expressions:
      - écarts contractuels
      - écart contractuel
      - constat contractuel
  - id: courrier_reclamation
    pourquoi: Le client reçoit un relevé d'écarts et un modèle neutre, pas un acte de réclamation (§1.3, §9.1 art. 6)
    remplacer_par: « relevé d'écarts » ; « modèle de courrier neutre que le client adapte et envoie lui-même »
    expressions:
      - dossier de réclamation
      - dossiers de réclamation
  # Sorties du référentiel seulement (pas les textes commerciaux) :
  - id: referentiel_taux_erreur_transitaire
    pourquoi: Dénigrement ; statistiques de prix seulement, transitaire nommé avec accord écrit (§5.4)
    remplacer_par: « statistique de prix »
    expressions:
      - taux d'erreur
      - taux d'écart du transitaire
```

Tous les textes modifiés passent la liste actuelle ; avec les catégories du §9.8 et de cette annexe, seules les trois occurrences de « mise en demeure » des CGV ressortent (voir la portée ci-dessus).
