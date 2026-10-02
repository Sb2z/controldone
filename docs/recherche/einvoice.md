# Réforme française de la facturation électronique B2B : état au 2 octobre 2026

**Accès web :** oui. J'ai lu les pages et PDF officiels d'impots.gouv.fr ainsi que la page Factur-X du FNFE-MPE. Deux pages n'ont pas pu être lues : economie.gouv.fr (erreur HTTP 403) et le PDF de la norme XP Z12-012 sur impots.gouv.fr (le lien renvoie une page HTML, pas le PDF). Pour les statuts de cycle de vie, les sources officielles lues ne donnent pas la liste complète (voir plus bas).

---

## 1. Calendrier

| Date | Obligation |
|---|---|
| 1er septembre 2026 | **Réception** obligatoire pour toutes les entreprises assujetties, quelle que soit leur taille, via une plateforme agréée |
| 1er septembre 2026 | **Émission** et transmission des données (e-reporting et données de paiement) pour les **grandes entreprises (GE) et les ETI**, ainsi que pour les administrations publiques |
| Au plus tard le 1er septembre 2027 | **Émission** et e-reporting pour les **PME, TPE et micro-entreprises** |

- **Sanctions en 2026 :** l'administration annonce une « approche pédagogique et proportionnée ». Pendant la phase de démarrage, une entreprise engagée dans une « trajectoire sérieuse de mise en conformité » ne sera pas sanctionnée. L'administration précise que ce n'est « ni un report ni une suspension de l'obligation ».
- **Textes les plus récents :** décret n° 2026-677 et arrêté du 27 juillet 2026, article 123 de la loi de finances pour 2026. Textes plus anciens : décrets 2022-1299 et 2024-266, article 91 de la loi de finances pour 2024.

## 2. Plateformes agréées (PA, anciennement PDP) et rôle de l'État

- Les PA émettent, transmettent et reçoivent les factures, et transmettent à l'administration les données de facturation, de transaction et de paiement (article 289 bis du CGI pour le recours obligatoire à une PA, article 289 E pour la transmission des données).
- Une PA est immatriculée par l'administration fiscale pour **3 ans renouvelables**. Une « solution compatible » non immatriculée ne peut pas transmettre de factures ni de données à l'administration.
- Environ 150 plateformes étaient agréées au 1er août 2026, dont plus d'une dizaine avec une offre gratuite ou sans surcoût.
- Exigences imposées aux PA :
  - certification ISO 27001 ;
  - offre qualifiée SecNumCloud si l'hébergement cloud est externalisé ;
  - données hébergées dans l'UE ;
  - authentification renforcée et audits réguliers.
- **Pas de portail public gratuit :** la France a renoncé à un portail public unique pour la circulation des factures. L'État garde la régulation, les standards et la gestion de l'**annuaire national**, qui permet d'adresser chaque facture à la bonne plateforme. La documentation cite aussi un « concentrateur » et un « système d'échange » exploités par l'État.
- **Client sans PA :** s'il n'est pas dans l'annuaire, la facture est rejetée ou non délivrée. Elle peut alors exceptionnellement être envoyée par e-mail ou par courrier.
- Le réseau **Peppol est facultatif** en France.

## 3. Formats et normes

- **Socle de formats :** UBL, CII et Factur-X, présentés comme les « 3 formats obligatoires en réception » selon la norme AFNOR XP Z12-012. La base sémantique est la norme EN 16931.
- **Spécifications externes en vigueur : version 3.2 du 30 avril 2026.** Versions précédentes : v3.1 (31 octobre 2025) et v3.0 (18 décembre 2024). Elles couvrent le B2B, le GtoB et le BtoG (Chorus Pro), avec schémas XSD et fichiers Swagger.
- **Normes AFNOR**, téléchargeables gratuitement sur la boutique AFNOR :
  - **XP Z12-012** : formats et profils des messages « Factures » et « Statuts de cycle de vie » ;
  - **XP Z12-013** : API entre le système d'information de l'entreprise et la PA ;
  - **XP Z12-014** : cas d'usage B2B de la réforme.
- **Factur-X :**
  - dernière version selon la page FNFE : **1.09.2 / ZUGFeRD 2.5.2, publiée le 4 août 2026** (voir aussi la section Hypothèses : une autre source parle de 1.08) ;
  - 5 profils : MINIMUM, BASIC WL, BASIC, EN 16931, EXTENDED ;
  - il existe un sous-profil français **EXTENDED-CTC-FR** ;
  - MINIMUM et BASIC WL ne contiennent que l'en-tête et le pied de facture, sans les lignes.

## 4. Données obligatoires

- Une facture électronique comporte **34 données obligatoires** en format structuré.
- Parmi elles, **4 nouvelles mentions** servent à l'adressage :
  1. le **SIREN du client** ;
  2. la **catégorie de l'opération** : livraison de biens, prestation de services, ou les deux ;
  3. l'**option pour le paiement de la TVA d'après les débits**, le cas échéant ;
  4. l'**adresse de livraison**, si elle diffère de l'adresse du client.
- Les mentions obligatoires sont fixées notamment à l'article 242 nonies A de l'annexe II du CGI.
- **E-reporting :** il couvre les opérations avec des non-assujettis (B2C) et les opérations internationales. Les données transmises sont des bases cumulées par jour et par taux de TVA. La fréquence d'envoi dépend du régime de TVA de l'entreprise.
- **Hors champ :** opérations exonérées de TVA et dispensées de facture (articles 261 à 261 E du CGI : santé, enseignement, immobilier, banque, assurance…), ainsi que les factures adressées aux particuliers.

## 5. Statuts du cycle de vie

- Les sources officielles lues confirment seulement :
  - l'existence de statuts « horodatés et opposables » ;
  - la distinction entre **« rejetée »** (anomalie détectée par une plateforme : format, donnée manquante, routage…) et **« refusée »** (décision de l'acheteur, obligatoirement motivée).
- Le statut **« refusée »** ne peut être utilisé que pour trois motifs prévus par la norme :
  - non-conformité réglementaire que la PA de réception n'a pas détectée ;
  - facture mal adressée ;
  - non-respect de conditions contractuelles empêchant le traitement.

  Il ne doit pas servir pour un simple litige commercial.
- Une facture réémise après un refus doit porter un **nouveau numéro**.
- Le détail des 14 statuts et des 4 statuts obligatoires vient de sources non officielles (voir la section Hypothèses).

## 6. Sanctions (article 1737 du CGI)

Montants tirés de résultats de recherche secondaires, non relus sur Légifrance :

| Manquement | Amende | Plafond annuel |
|---|---|---|
| Facture non émise sous forme électronique | 15 € par facture | 15 000 € |
| Défaut d'e-reporting | 250 € par transmission | 15 000 € |
| Manquement d'une plateforme | 15 € par facture | 45 000 € |

---

## Faits vérifiés

- Réception obligatoire pour toutes les entreprises et émission obligatoire pour les GE et ETI depuis le 1er septembre 2026 ; émission pour les PME, TPE et micro « au plus tard » le 1er septembre 2027. Source : https://www.impots.gouv.fr/actualite/facturation-electronique et la FAQ https://www.impots.gouv.fr/sites/default/files/media/1_metier/2_professionnel/EV/2_gestion/290_facturation_electronique/faq_tout_savoir_facturation-electronique.pdf
- Pas de sanction en 2026 pour les entreprises engagées dans une trajectoire de conformité ; ce n'est ni un report ni une suspension. Source : https://www.impots.gouv.fr/sites/default/files/media/1_metier/2_professionnel/EV/2_gestion/290_facturation_electronique/guide_pratique_facturation_electronique.pdf
- 34 données obligatoires, dont les 4 nouvelles mentions (SIREN du client, catégorie d'opération, option TVA sur les débits, adresse de livraison). Source : la FAQ ci-dessus et https://www.impots.gouv.fr/japprofondis-mes-connaissances-sur-la-reforme
- Rôle des PA, immatriculation de 3 ans renouvelable, différence avec une solution compatible. Source : https://www.impots.gouv.fr/facturation-electronique-et-plateformes-agreees
- Environ 150 PA au 1er août 2026, pas de portail public gratuit, annuaire national géré par l'État, Peppol facultatif, exigences ISO 27001 et SecNumCloud. Source : la FAQ ci-dessus
- Distinction rejet / refus, motifs de refus limités, nouveau numéro après un refus, articles 289 bis, 289 E et 242 nonies A du CGI. Source : le guide pratique ci-dessus
- Textes de référence : décret 2026-677 et arrêté du 27 juillet 2026, article 123 de la loi de finances 2026, décrets 2022-1299 et 2024-266. Source : https://www.impots.gouv.fr/sites/default/files/media/1_metier/2_professionnel/EV/2_gestion/290_facturation_electronique/facturation-electronique_documentation-juridique.pdf
- Spécifications externes v3.2 du 30 avril 2026 et rôle des normes XP Z12-012, 013 et 014. Source : https://www.impots.gouv.fr/specifications-externes-b2b
- Factur-X 1.09.2 / ZUGFeRD 2.5.2 du 4 août 2026, 5 profils, EXTENDED-CTC-FR, Factur-X comme l'un des 3 formats obligatoires en réception. Source : https://fnfe-mpe.org/factur-x/

## Hypothèses non vérifiées

1. **Liste des statuts (confiance moyenne-haute).** 14 statuts codés de 200 à 213 : Déposée (200), Émise par la plateforme, Reçue par la plateforme, Mise à disposition, Prise en charge, Approuvée, Approuvée partiellement, En litige, Suspendue, Complétée, Refusée (210), Paiement transmis, Encaissée (212), Rejetée (213). Les autres codes ne sont pas confirmés. Les 4 statuts obligatoires vers l'administration seraient **Déposée, Rejetée, Refusée et Encaissée**, les autres étant recommandés et échangés seulement entre plateformes. Le statut Encaissée concernerait surtout les prestations de services avec TVA exigible à l'encaissement. Sources non officielles : https://plateforme-agree.org/comprendre/cycle-de-vie/ et https://libeo.io/fiches-pratiques/statuts-cycle-vie-facture-electronique. À vérifier dans XP Z12-012 et dans les spécifications externes v3.2.
2. **Version de Factur-X (confiance moyenne).** Une source secondaire indique « 1.08 = ZUGFeRD 2.4, janvier 2026 » (https://facturxapi.com/blog/facturx-108-zugferd-24-nouveautes-developpeurs), alors que la page FNFE lue indique 1.09.2 / 2.5.2. Je retiens la version FNFE, mais elle n'a pas été recoupée avec la page de téléchargement.
3. **Profils MINIMUM et BASIC WL (confiance moyenne).** Ils ne seraient pas acceptés comme factures dans le cadre de la réforme, car ils ne portent pas toutes les données obligatoires. Le profil minimal pour la réforme serait EN 16931 ou EXTENDED-CTC-FR. Non confirmé par une source officielle.
4. **Sanctions (confiance moyenne-haute).** Les montants viennent de sources secondaires et ne sont pas relus sur Légifrance (https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006069577/LEGISCTA000006163056/). Une éventuelle amende spécifique pour absence de PA de réception (montant non confirmé) ajoutée par la loi de finances 2026 n'est pas vérifiée.
5. **Portail public réduit à l'annuaire (confiance moyenne-haute).** Selon des articles de presse (par exemple https://comptaverse.fr/posts/decret-arrete-27-juillet-2026-facturation-electronique/), les textes de juillet 2026 limitent le portail public au rôle d'annuaire central et remplacent officiellement « PDP » par « plateformes agréées ». C'est cohérent avec la FAQ officielle, mais le texte n'a pas été relu sur Légifrance.
6. **Seuils de taille (confiance haute, non relus).** Les seuils seraient ceux de la LME (décret 2008-1354) :
   - **PME** : moins de 250 salariés, et soit chiffre d'affaires ≤ 50 M€, soit bilan ≤ 43 M€ ;
   - **ETI** : moins de 5 000 salariés, et soit chiffre d'affaires ≤ 1,5 Md€, soit bilan ≤ 2 Md€ ;
   - **grande entreprise** : au-delà de ces seuils.
7. **Socle de formats côté émission (confiance haute).** Une PA doit accepter les trois formats UBL, CII et Factur-X, et l'émetteur peut choisir l'un d'eux. Le PDF de XP Z12-012 n'a pas pu être lu.