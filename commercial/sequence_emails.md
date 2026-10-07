# Séquence de prospection ControlDOne — 3 e-mails + 2 messages LinkedIn

*Version 1.0 — 2 octobre 2026. Brouillons à valider par le fondateur. Rien n'est envoyé automatiquement.*

> La séquence par défaut du module **Marketing** de l'application (J0, J+4, J+10, J+20) est une réécriture plus courte de ces messages, modifiable dans l'interface ; voir `docs/PROSPECTION.md`.

## Règles d'usage (à relire avant chaque envoi)

- **Cible** : la fonction du destinataire doit avoir un lien direct avec l'offre (dirigeant, responsable achats/import, DAF). C'est la condition de l'intérêt légitime en prospection B2B par e-mail (CNIL, https://www.cnil.fr/fr/la-prospection-commerciale-par-courrier-electronique).
- **Origine des données** : chaque message dit où l'adresse a été trouvée (page Contact du site, mentions légales). Ne jamais écrire à une adresse qui n'a pas été publiée par l'entreprise elle-même.
- **Désinscription** : chaque message propose « répondez STOP ». Un STOP est noté le jour même dans `prospects.csv` (colonne `raison_ciblage` : « STOP reçu le … ») et l'adresse n'est plus jamais utilisée.
- **Volume** : envois un par un, depuis la boîte du fondateur, pas d'outil d'envoi en masse. Si l'adresse est générique (contact@, info@), demander à qui transmettre.
- **Suisse et Belgique** : en Suisse, uniquement des e-mails individuels et personnalisés, jamais d'envoi groupé (art. 3 al. 1 let. o LCD) ; en Belgique, uniquement des adresses impersonnelles (info@, contact@). Voir `prospects_methode.md` §5 bis.
- **Offre de lancement** : la gratuité est une remise commerciale de lancement de 100 %. L'accord de publication est proposé à part, facultatif et révocable jusqu'à la publication, sans effet sur la remise. Ne jamais écrire « en échange », « contre » ou « en contrepartie » à propos de la publication.
- **Arrêt de la séquence** : dès qu'il y a une réponse (positive, négative ou STOP), on n'envoie plus les relances.
- **Interdits** : aucune promesse de gain chiffrée, aucun avis sur un droit, une taxe, un classement, une origine, une valeur en douane, aucun faux témoignage, aucun chiffre sans source.
- Les champs entre crochets `[...]` sont à remplir. `[accroche]` = un fait public, sourcé, tiré du site de l'entreprise (voir `brouillons/`).

## Chiffres autorisés (et leur source)

| Chiffre | Formulation à utiliser | Source |
|---|---|---|
| Droit de douane forfaitaire de 3 EUR par article | « Depuis le 1er juillet 2026, les envois de faible valeur (jusqu'à 150 EUR) vendus à distance supportent un droit forfaitaire de 3 EUR par article (règlement (UE) 2026/382, applicable jusqu'au 1er juillet 2028). » | https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en |
| Facturation électronique | « Depuis le 1er septembre 2026, toute entreprise assujettie doit pouvoir recevoir ses factures par une plateforme agréée ; les PME émettront au plus tard le 1er septembre 2027. » | https://www.impots.gouv.fr/actualite/facturation-electronique |
| Taux d'erreur sur les factures de transitaires | « Aucune mesure indépendante du taux d'erreur sur les factures de transitaires n'existe à notre connaissance : le diagnostic sert à mesurer votre propre situation. » | — (aucun chiffre utilisé) |

Dès qu'un message évoque le droit forfaitaire, la TVA à l'importation ou un autre sujet réglementaire, il contient la phrase de renvoi exacte :

> Ce point relève d'une appréciation réglementaire : il est à faire vérifier par un représentant en douane enregistré ou un avocat. ControlDOne ne se prononce pas sur ce point.

## Pied commun à tous les e-mails

```
--
[Prénom Nom] EI, fondateur de ControlDOne, SIREN [ ]
[adresse postale professionnelle] — [téléphone]
Vous recevez ce message parce que votre adresse professionnelle figure sur [source exacte, ex. : la page Contact de votre site]. Si vous ne souhaitez plus recevoir de message de ma part, répondez simplement STOP : je supprimerai votre adresse de mon fichier.
ControlDOne est un contrôle technique de cohérence entre documents et de calcul. Il ne constitue ni un conseil juridique, fiscal ou douanier, ni un avis sur la conformité des opérations.
```

---

## E-mail 1 — J0 (premier contact)

**Objet (au choix)** :
- A. « Factures de votre transitaire : un contrôle croisé gratuit sur vos dossiers passés »
- B. « [Raison sociale] : 3 diagnostics gratuits pour des importateurs »

**Variante dirigeant**

```
Bonjour [Madame/Monsieur Nom | si adresse générique : Bonjour],

Je m'appelle [Prénom Nom] et j'ai fondé ControlDOne, un service qui rapproche, pour chaque dossier d'import, quatre documents que personne ne compare en entier faute de temps : la facture du fournisseur, la déclaration en douane, la facture du transitaire et ses avoirs.

[accroche : un fait public tiré de votre site, ex. « Votre site indique que vous importez directement des fruits d'Amérique latine et d'Afrique. »]

Le service relève des écarts de fait : un montant refacturé qui ne correspond pas à celui de la déclaration, un prix facturé différent du prix chiffré de votre grille tarifaire, un total qui ne correspond pas à la somme de ses lignes, un avoir annoncé mais jamais reçu. Il ne se prononce pas sur le bien-fondé des droits et taxes : ces points-là sont renvoyés vers votre représentant en douane ou un avocat.

Pour démarrer, je propose 3 diagnostics gratuits (remise de lancement) à des PME importatrices, sur un lot de dossiers passés (par exemple les 20 derniers). Si vous l'acceptez ensuite, par un accord séparé, je publierai des résultats anonymisés (ni nom, ni montant permettant de vous reconnaître), après votre relecture. Je ne promets pas de montant : le diagnostic peut aussi conclure que tout est cohérent.

Seriez-vous d'accord pour un échange de 20 minutes la semaine prochaine ? Si ce n'est pas vous qui suivez les factures du transitaire, à qui puis-je m'adresser ?

Bien cordialement,
[pied commun]
```

**Variante responsable achats / import** — remplacer le 2e paragraphe par :

```
Vous recevez chaque mois les factures de votre transitaire, avec leurs débours (droits, TVA, frais) et leurs prestations. Les vérifier ligne à ligne contre la déclaration et contre la grille tarifaire prend du temps, et c'est souvent ce qui passe en dernier.
```

**Variante DAF** — remplacer le 2e paragraphe par :

```
Côté comptabilité, les factures du transitaire mélangent débours et prestations. Une ligne de TVA refacturée alors que la déclaration en douane indique l'autoliquidation, ou un avoir annoncé mais jamais reçu, se voit mal au moment du paiement.
```

---

## E-mail 2 — J+5 (relance courte, avec un exemple concret)

**Objet** : « Re : [objet de l'e-mail 1] — un exemple concret »

```
Bonjour [Madame/Monsieur Nom | Bonjour],

Je me permets une relance courte, avec un exemple (cas fictif, inventé pour l'illustration) de ce que le diagnostic fait ressortir :

« La facture du transitaire refacture 1 840,00 EUR de TVA à l'importation. Sur la déclaration en douane du même dossier, la TVA est indiquée comme autoliquidée et aucun montant de TVA n'est à payer au dédouanement. Les deux documents ne disent pas la même chose : la question est à poser au transitaire, pièces à l'appui. »

Le rapport donne, pour chaque écart, les deux valeurs, la page du document où elles figurent et la tolérance appliquée. Les sujets réglementaires (autoliquidation, droits, classement) sont signalés à part. Ce point relève d'une appréciation réglementaire : il est à faire vérifier par un représentant en douane enregistré ou un avocat. ControlDOne ne se prononce pas sur ce point.

L'offre de lancement tient toujours : 3 diagnostics gratuits, avec, si vous l'acceptez, publication de résultats anonymisés. Un créneau de 20 minutes vous conviendrait-il ?

Bien cordialement,
[pied commun]
```

---

## E-mail 3 — J+12 (dernier message)

**Objet** : « Dernier message — diagnostics gratuits ControlDOne »

```
Bonjour [Madame/Monsieur Nom | Bonjour],

C'est mon dernier message sur ce sujet : je ne vous relancerai pas ensuite.

Deux éléments de contexte, sans lien avec votre situation particulière :
- depuis le 1er septembre 2026, toute entreprise assujettie doit pouvoir recevoir ses factures par une plateforme agréée (les PME émettront au plus tard le 1er septembre 2027 ; source : impots.gouv.fr). Les factures de transitaire arriveront donc de plus en plus sous forme structurée, ce qui facilite leur rapprochement avec la déclaration ;
- pour qui vend à distance des petits envois venant de pays tiers, un droit forfaitaire de 3 EUR par article s'applique depuis le 1er juillet 2026 (règlement (UE) 2026/382) ; le nombre d'articles retenu se lit sur la déclaration et sur la facture du transitaire. Ce point relève d'une appréciation réglementaire : il est à faire vérifier par un représentant en douane enregistré ou un avocat. ControlDOne ne se prononce pas sur ce point.

Si le sujet devient d'actualité chez [Raison sociale], il suffit de répondre « diagnostic » à ce message. Sinon, merci de m'avoir lu.

Bien cordialement,
[pied commun]
```

---

## LinkedIn — demande de connexion (299 caractères maximum)

*Uniquement vers une personne dont la fonction est en lien avec l'offre, sans outil d'automatisation, sans extraction de profils.*

```
Bonjour [Prénom], je lance ControlDOne, un contrôle croisé facture fournisseur / déclaration / facture transitaire pour PME importatrices. Je cherche 3 entreprises pour un diagnostic gratuit (publication anonymisée si vous l'acceptez). Pas concerné ? Ignorez simplement ce message.
```

(Longueur : 281 caractères.)

## LinkedIn — message de suivi (après acceptation uniquement)

```
Merci pour la connexion, [Prénom].

En deux lignes : ControlDOne rapproche, dossier par dossier, la facture du fournisseur, la déclaration en douane, la facture du transitaire et ses avoirs, et chiffre les écarts de fait (montant refacturé différent de la déclaration, prix différent de la grille tarifaire, avoir jamais reçu). Pas d'avis sur les droits et taxes : ces points sont renvoyés vers un représentant en douane ou un avocat.

J'offre 3 diagnostics gratuits sur des dossiers passés ; si vous l'acceptez, et seulement dans ce cas, des résultats anonymisés seront publiés après votre relecture. Est-ce un sujet chez [entreprise] ? Si vous préférez ne plus recevoir de message de ma part, dites-le simplement : je n'insisterai pas.

[Prénom Nom] EI, fondateur de ControlDOne, SIREN [ ]
```
