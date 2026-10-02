# Brief de recherche : cadre juridique et technique pour un service B2B solo en France

*Recherche faite le 2026-10-02. Le web était accessible. Certaines pages n'ont pas pu être lues : Légifrance L441-1 (erreur 404), la fiche DGCCRF sur les CGV (403), Doctrine (paywall). Pour ces points, j'ai utilisé l'extrait du résultat de recherche ou une source secondaire, et je l'indique à chaque fois.*

---

## 1. Prospection B2B par email et via LinkedIn (CNIL)

**Faits vérifiés**
- **Base légale.** Pour prospecter un professionnel, l'intérêt légitime suffit si le message concerne sa fonction. Exemple donné par la CNIL : présenter un logiciel au DSI d'une entreprise. — https://www.cnil.fr/fr/la-prospection-commerciale-par-courrier-electronique
- **Information préalable.** La personne doit savoir, au moment où l'on collecte son adresse, que celle-ci servira à de la prospection. Elle doit pouvoir s'y opposer. — même URL
- **Désinscription.** Il faut un moyen simple et gratuit de refuser les envois suivants, dans chaque message. — même URL
- **Identification.** Chaque envoi doit indiquer clairement qui l'émet. — même URL
- **Adresses génériques.** Les adresses du type contact@ ou info@ désignent une organisation et non une personne. Elles sortent de ce régime. — même URL
- **Textes applicables.** Art. L34-5 du CPCE et art. 21 RGPD (droit d'opposition). — même URL
- **Opposition dès la collecte.** Selon une source secondaire, la personne doit pouvoir s'opposer dès la collecte, et pas seulement à réception du premier email. Le régime d'opt-out B2B est propre à la France ; d'autres États membres exigent le consentement. — https://overloop.com/fr/blog/b2b-cold-email-france-cnil-rgpd
- **Sanction Orange.** Selon des sources secondaires, la CNIL a infligé 50 M€ à Orange pour défaut de conformité en prospection. Je n'ai pas vérifié l'année ni les motifs sur cnil.fr. — https://overloop.com/fr/blog/b2b-cold-email-france-cnil-rgpd
- **Données publiques LinkedIn.** Un profil LinkedIn et une adresse pro nominative restent des données personnelles. Les réutiliser exige une finalité, une base légale, l'information de la personne et le respect de son droit d'opposition. — https://kohenavocats.fr/2026/09/30/prospecte-linkedin-email-professionnel-sans-accord-source-effacement-opposition-cnil-reparation-2026/ (source secondaire, cabinet d'avocat)
- **Règles LinkedIn.** Selon une source secondaire, les règles de LinkedIn interdisent les messages commerciaux non ciblés ou répétitifs, et l'usage des invitations pour faire de la promotion. Le texte des règles LinkedIn n'a pas été lu. — https://cyrilvoisin.fr/ressources/prospection-linkedin-social-selling/
- **Scraping.** Le scraping de LinkedIn pour constituer un fichier de prospection pose un problème RGPD. — https://www.haas-avocats.com/non-categorise/scraping-des-donnees-linkedin-a-des-fins-de-prospection-commerciale-est-ce-legal/ (vu en recherche, non lu)

## 2. Sous-traitance (art. 28 RGPD) et registre (art. 30)

**Faits vérifiés**
- **Obligations du sous-traitant.**
  - traiter les données uniquement sur instruction du client ;
  - imposer la confidentialité aux personnes autorisées ;
  - mettre en place des mesures de sécurité ;
  - obtenir l'autorisation préalable du client avant de recourir à un sous-traitant ultérieur ;
  - aider le client à répondre aux demandes des personnes concernées ;
  - supprimer ou restituer les données en fin de service ;
  - pouvoir démontrer sa conformité.
  
  — https://www.cnil.fr/sites/cnil/files/atoms/files/rgpd-guide_sous-traitant-cnil.pdf
- **Clauses du contrat art. 28.**
  - objet et durée ;
  - nature et finalité ;
  - types de données et catégories de personnes ;
  - obligations et droits de chaque partie ;
  - sécurité ;
  - transferts hors UE ;
  - assistance au client ;
  - sort des données en fin de contrat.
  
  — même URL
- **Qui tient un registre.** Tout organisme doit tenir un registre (art. 30). — https://www.cnil.fr/fr/RGDP-le-registre-des-activites-de-traitement
- **Dérogation des moins de 250 salariés.** Elle est partielle. Il faut tout de même inscrire :
  - les traitements non occasionnels (gestion clients, paie) ;
  - les traitements à risque ;
  - les traitements portant sur des données sensibles.
  
  La CNIL conseille, en cas de doute, d'inscrire le traitement. — même URL
- **Registre du sous-traitant (art. 30.2).** Il contient :
  - l'identité de chaque client ;
  - les catégories de traitements réalisés ;
  - les sous-traitants ultérieurs ;
  - les transferts hors UE ;
  - les mesures de sécurité.
  
  — même URL
- **Modèle CNIL.** La CNIL fournit un modèle simplifié de registre au format ODS. — même URL

## 3. Périmètre du droit (loi n°71-1130, art. 54 et suivants)

**Faits vérifiés**
- **Interdiction de principe (art. 54).** Nul ne peut, de façon habituelle et rémunérée, donner des consultations juridiques ou rédiger des actes sous seing privé pour autrui sans remplir les conditions de diplôme ou de compétence juridique appropriée. Les personnes autorisées doivent aussi avoir une assurance RC et des garanties financières. — https://www.information-juridique.com/aide/loi-71-1130.php (vu en recherche) ; vade-mecum CNB : https://cnb.avocat.fr/medias/cnb-vademecum-exercice-du-droit-2023-68f77e825bf8f7.74522639.pdf (vu en recherche, non lu)
- **Exception de l'art. 60.** Il permet aux professions non réglementées de donner des consultations juridiques, à condition qu'elles relèvent directement de leur activité principale et que le professionnel ait la qualification requise. — https://www.legifrance.gouv.fr/juri/id/JURITEXT000023113684/
- **Cass. 1re civ., 15 nov. 2010, n°09-66.319 (CNB c/ Alma Consulting).** La Cour distingue deux activités. Un audit technique qui relève des erreurs de tarification est admis. En revanche, vérifier si des charges sociales sont bien fondées au regard des règles applicables est une prestation juridique, quel que soit son degré de complexité. Ici, cette prestation n'était pas accessoire : elle formait le cœur de la mission. La qualification d'Alma (« gestion d'entreprise ») ne couvrait pas le droit de la sécurité sociale. — https://www.legifrance.gouv.fr/juri/id/JURITEXT000023113684/
- **Suite de l'affaire.** Sur renvoi, la CA de Paris a jugé en 2013 que l'activité principale d'Alma, présentée comme un audit technique, était en réalité juridique. — résultat de recherche (dépêche JurisClasseur, http://web.lexisnexis.fr/depeches-jurisclasseur/depeche/26-09-2013/05, non lue)

**Ce qu'un service non réglementé peut faire, d'après ces sources**
- Admis : un contrôle factuel ou arithmétique (rapprochements, écarts de calcul, incohérences de données, erreurs de saisie ou de tarification constatées).
- Interdit : dire si une situation est conforme au droit, recommander une position juridique, rédiger des actes ou des réclamations pour le compte du client.

## 4. Mentions légales (LCEN) et CGV B2B

**Faits vérifiés**
- **Changement de numérotation.** Depuis le 23 mai 2024 (loi SREN), les mentions d'identification figurent à l'art. 1-1 de la LCEN, et non plus à l'art. 6 III. Les sanctions sont à l'art. 1-2. — https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000049568614 ; https://www.papperlaw.fr/blog/mentions-legales-obligatoires
- **Mentions requises (art. 1-1).**
  - Personne physique : nom, prénoms, adresse, téléphone, n° RCS ou RM le cas échéant.
  - Personne morale : dénomination, siège, téléphone, immatriculation, capital.
  - Dans tous les cas : directeur de la publication, et hébergeur (nom ou raison sociale, adresse, téléphone).
  
  — https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000049568614
- **Prestataires de stockage.** Il faut aussi identifier ceux qui stockent les données directement utilisées pour faire fonctionner le service. — https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000049568614 (extrait de recherche)
- **Fiche Service-Public.**
  - L'entrepreneur individuel ajoute « EI » ou « entrepreneur individuel » à son nom.
  - Il indique aussi email, téléphone, n° TVA, hébergeur, et l'autorité qui l'a autorisé si l'activité est réglementée.
  - Sanction : 1 an d'emprisonnement et 75 000 € d'amende.
  
  — https://entreprendre.service-public.gouv.fr/vosdroits/F31228
- **CGV en B2B.** Les publier n'est pas obligatoire, mais il faut les communiquer à tout acheteur professionnel qui les demande. Refus : 15 000 € d'amende. — https://entreprendre.service-public.gouv.fr/vosdroits/F31228
- **Résiliation des abonnements.** Depuis le 1er juin 2023, il faut une fonction de résiliation en ligne, visible et gratuite (amende 15 000 €). La source ne précise pas si cela vise aussi le B2B. — même URL
- **Contenu des CGV (L441-1).** Elles comprennent notamment les conditions de règlement, le barème des prix unitaires et les réductions de prix. Elles sont communiquées sur un support durable. Manquement : amende administrative jusqu'à 15 000 € (personne physique) ou 75 000 € (personne morale). — https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000038414469 (extrait de recherche, page non lue)
- **Mentions de facture (L441-9).**
  - date de règlement ;
  - conditions d'escompte ;
  - taux des pénalités exigibles le lendemain de l'échéance ;
  - montant de l'indemnité forfaitaire pour frais de recouvrement.
  
  — https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000005634379/LEGISCTA000038411051/
- **Délais et pénalités (L441-10).**
  - Délai maximal : 60 jours à compter de la facture, ou 45 jours fin de mois si c'est expressément prévu.
  - Pénalités : au moins le taux de refinancement de la BCE + 10 points, sauf clause fixant au moins 3 fois le taux d'intérêt légal.
  - Une indemnité forfaitaire de recouvrement est due de plein droit.
  
  — même URL
- **Montant de 40 €.** L'indemnité est due par facture payée en retard, sans mise en demeure. Elle doit figurer dans les CGV et sur la facture. — https://kohenavocats.fr/2026/05/12/penalite-retard-facture-calcul-indemnite-40-euros-recouvrement-2026/ ; https://www.assistant-juridique.fr/indemnite_forfaitaire.jsp
- **Limite.** Le montant de 40 € vient de D441-5, cité par des sources secondaires. Je n'ai pas lu le texte sur Légifrance.

## 5. Stripe (mode test, Billing, Checkout)

**Faits vérifiés**
- **Mode test.** On utilise des clés de test (`sk_test_…`) dans un sandbox isolé, et aucun argent ne circule. — https://docs.stripe.com/testing
- **Cartes de test.**
  - 4242 4242 4242 4242 avec une date future et n'importe quel CVC ;
  - refus : 4000000000000002 ;
  - fonds insuffisants : 4000000000009995 ;
  - 3DS exigé : 4000000000003220 ;
  - méthodes de paiement API : `pm_card_visa`.
  
  — https://docs.stripe.com/testing
- **Durée de vie en test.** Les abonnements créés en test sont annulés automatiquement après 90 jours, puis supprimés 30 jours plus tard. — https://support.stripe.com/questions/test-mode-subscription-data-retention (extrait de recherche)
- **Test clocks.** Ils permettent d'avancer le temps pour simuler les renouvellements. — https://docs.stripe.com/billing/testing/test-clocks/simulate-subscriptions (vu en recherche)
- **Checkout et abonnements.** La page hébergée par Stripe Checkout permet de vendre des abonnements à prix fixe. — https://docs.stripe.com/billing/subscriptions/build-subscriptions ; https://stripe.com/docs/billing/subscriptions/checkout
- **Webhooks.** Un webhook est indispensable, car l'essentiel du cycle d'un abonnement est asynchrone. Il faut vérifier la signature des événements. — https://docs.stripe.com/billing/subscriptions/webhooks
- **Événements clés.**
  - `customer.subscription.created`, `.updated`, `.deleted`, `.trial_will_end` ;
  - `invoice.paid` : donner l'accès, après avoir vérifié que le statut est `active` ;
  - `invoice.payment_failed` ;
  - `invoice.payment_action_required` ;
  - `invoice.finalization_failed` ;
  - `charge.dispute.created`, `charge.refunded`.
  
  — même URL
- **Statuts.**
  - `incomplete` : il reste 23 h pour payer, sinon `incomplete_expired` ;
  - `past_due` ;
  - `canceled` et `unpaid` : retirer l'accès.
  
  En sandbox, un webhook en échec est réessayé 3 fois en quelques heures (jusqu'à 3 jours en live). — même URL
- **Outils pratiques.** `stripe trigger` (CLI) déclenche des événements de test. Le Customer Portal permet au client de gérer lui-même son abonnement. — même URL

## 6. Hébergement UE à bas coût

**Faits vérifiés**
- **Scaleway (Paris PAR-1).**
  - STARDUST1-S : environ 0,43 €/mois (1 vCPU, 1 Go) ;
  - DEV1-S : environ 6,55 €/mois (2 vCPU, 2 Go) ;
  - IPv4 publique et stockage facturés en plus.
  
  — https://www.scaleway.com/en/pricing/virtual-instances/
- **OVHcloud.** Hausse au 1er avril 2026 :
  - VPS-1 : 4,49 → 6,49 € HT/mois ;
  - VPS-2 : 6,99 → 9,99 € HT/mois ;
  - VPS-3 : 13,99 → 19,99 € HT/mois.
  
  — https://blog.ovhcloud.com/evolutions-tarifaires-de-public-cloud-bare-metal-et-vps-chez-ovhcloud/
- **Hetzner.**
  - Datacenters : Falkenstein et Nuremberg (Allemagne), Helsinki (Finlande), plus États-Unis et Singapour.
  - Certification ISO 27001.
  
  — https://www.hetzner.com/cloud/
- **Hausse Hetzner.** Effective le 15 juin 2026 : en Allemagne et Finlande, le CAX11 passe de 4,49 à 5,99 €/mois. — https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- **Clever Cloud.** PaaS français, facturation à la seconde, crédits gratuits à l'inscription sans carte. — https://www.clever.cloud/pricing/

---

## Hypothèses non vérifiées

1. **LinkedIn** (confiance moyenne). Une source secondaire affirme que, selon la CNIL, la prospection par messagerie LinkedIn sans consentement viole L34-5. Je n'ai trouvé aucune page CNIL qui le dise. Hypothèse prudente : appliquer à LinkedIn les mêmes règles qu'à l'email B2B (message lié à la fonction, identification, possibilité de refuser), sans scraping, et en respectant les CGU de LinkedIn.
2. **Indemnité de 40 €** (confiance élevée). Le montant est fixé par l'art. D441-5 du Code de commerce, texte non lu sur Légifrance.
3. **Résiliation en ligne en B2B** (confiance faible à moyenne). L'obligation de résiliation en trois clics (L215-1-1 Code de la consommation) vise surtout les consommateurs. Son application à des clients purement B2B est incertaine. La proposer quand même via le Customer Portal de Stripe ne coûte rien.
4. **Frontière audit / conseil** (confiance moyenne). Un livrable qui se limite à constater des écarts chiffrés, sans dire ce que le droit impose ni quoi faire juridiquement, reste a priori hors du monopole. Cette lecture vient d'une décision de 2010 dont l'application est stricte. À faire valider par un avocat avant tout lancement.
5. **Hetzner CX22/CX23** (confiance faible). Les sources secondaires donnent environ 4,35 à 4,51 €/mois avant la hausse de 2026. Le prix actuel n'est pas confirmé sur hetzner.com.
6. **Clever Cloud** (confiance faible). La source est un site d'avis tiers, sans URL retenue ici, qui donne « nano » 1 vCPU / 512 Mo à environ 6 €/mois. Le calculateur officiel n'a pas pu être lu. L'existence de datacenters à Paris n'est pas confirmée.
7. **Sanction Orange de 50 M€** (confiance moyenne). L'année, 2024 ou 2025, et le détail des motifs ne sont pas vérifiés sur cnil.fr.
8. **Contrat art. 28 pour chaque client B2B** (confiance élevée). Le service traite des données personnelles pour ses clients : il est donc sous-traitant. Il doit signer un DPA avec chacun et tenir son propre registre art. 30.2. Ses hébergeurs et Stripe sont ses sous-traitants ultérieurs à déclarer, Stripe étant probablement responsable de traitement pour une partie des données.
9. **TVA et facture électronique** (confiance moyenne). La réforme de la facturation électronique B2B entre en vigueur le 1er septembre 2026 pour la réception. Ce sujet n'a pas fait l'objet de recherches dédiées.