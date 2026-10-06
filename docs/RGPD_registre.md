# ControlDOne — Registre des activités de traitement (brouillon)

> **BROUILLON — À RELIRE PAR UN AVOCAT.** Document interne, non publié. Les champs
> `[À COMPLÉTER : …]` sont à remplir par le fondateur ; rien n'y est inventé.
> Modèle de référence : registre simplifié de la CNIL (https://www.cnil.fr/fr/RGDP-le-registre-des-activites-de-traitement).
> Mise à jour : 6 octobre 2026 (lecture par Claude activable, D-4000 à D-4008).

## Identification

| Champ | Valeur |
|---|---|
| Organisme | [À COMPLÉTER : dénomination, forme juridique, SIREN, adresse] |
| Représentant | [À COMPLÉTER : nom du fondateur] |
| Contact pour les données personnelles | [À COMPLÉTER : adresse e-mail] |
| Délégué à la protection des données | Non désigné [À VALIDER : non obligatoire a priori] |

---

## Partie 1 — Registre du sous-traitant (art. 30.2 RGPD)

### 1.1 Responsables de traitement pour le compte desquels ControlDOne agit

Un client par ligne ; mettre à jour à chaque signature d'un accord de sous-traitance (`site/dpa.html`).

| Client (responsable) | Contact / représentant | Date de l'accord art. 28 | Extracteur `llm` activé | Fin de contrat / restitution |
|---|---|---|---|---|
| [À COMPLÉTER] | [À COMPLÉTER] | [À COMPLÉTER] | oui / non | — |

### 1.2 Catégories de traitements effectués pour chaque client

| Traitement | Description | Données personnelles concernées |
|---|---|---|
| Réception et stockage | Dépôt de fichiers (espace web, API, adresse dédiée, dossier surveillé, plateforme agréée), stockage chiffré par client | Noms, fonctions, coordonnées professionnelles figurant sur les documents d'import ; adresses e-mail d'expéditeurs autorisés |
| Lecture automatisée | Découpage, classement, extraction structurée, déterministe (texte, OCR) et, si activée, par modèle de langage (Anthropic) : seulement pour un document que les règles lisent mal, seulement le texte des pages de ce document (8 pages au plus, pas le fichier PDF), réponse limitée à des valeurs recopiées et vérifiées sur la page (D-4001, D-4005) | Idem ; minimisation : les données personnelles ne sont pas reprises dans le modèle de dossier sauf nécessité ; noms de contacts, téléphones et e-mails jamais demandés au modèle |
| Contrôles et rapports | Comparaisons et calculs, rapport de diagnostic, relevé d'écarts et modèle de courrier neutre (gabarit) que le client adapte et envoie lui-même | Nom de l'entité et des contacts dans l'en-tête du modèle de courrier |
| Suivi des avoirs reçus | Registre des écarts, avoirs déclarés reçus par le client, rappels adressés au client seul (jamais au transitaire) | Identifiants des utilisateurs du client |
| Anonymisation pour le référentiel | Sur instruction du client (DPA art. 3, CGV art. 14) : extraction de données tarifaires des dossiers validés, agrégation, statistiques de prix seulement ; instruction retirable à tout moment | Aucune donnée personnelle utilisée ni publiée ; le résultat est anonyme (critères G29 : individualisation, corrélation, inférence) |
| Comptes utilisateurs du client | Authentification, sessions, journal d'audit | Nom, e-mail, empreinte de mot de passe, horodatages, adresses IP |
| Conservation, restitution, suppression | Purge des fichiers bruts 180 jours après clôture (réglable) ; export puis suppression sous 30 jours en fin de contrat | Toutes les données ci-dessus |

### 1.3 Sous-traitants ultérieurs

| Sous-traitant | Service | Lieu | Garanties |
|---|---|---|---|
| [À COMPLÉTER : hébergeur de l'application] | Serveurs, base, coffre de fichiers chiffré | UE [À COMPLÉTER : pays] | Contrat art. 28 |
| [À COMPLÉTER : stockage des sauvegardes] | Copie hors site des sauvegardes chiffrées | UE [À COMPLÉTER] | Contrat art. 28 ; chiffrement avant envoi |
| Anthropic, PBC — **seulement si la lecture par modèle est activée** (clé API configurée, décision D-4000) | Lecture de pages (sans outil ni accès réseau) des seuls documents que les règles lisent mal ; texte des pages du document, pas le fichier ; aucun stockage par ControlDOne chez Anthropic ; les courriers sont produits par gabarits | États-Unis | CCT modules 2 et 3 (DPA Anthropic du 24/02/2025), addendum suisse ; préavis de 15 jours pour s'opposer à un nouveau sous-traitant ; durée de conservation côté Anthropic selon ses conditions commerciales API [À VÉRIFIER : durée et option de non-conservation] ; TIA à rédiger [À COMPLÉTER] ; **désactivable par client** (réglage `llm_desactive`, D-4007) |
| Stripe [À COMPLÉTER : entité contractante] | Paiement (données de facturation du client seulement) | [À COMPLÉTER] | [À VALIDER : Stripe responsable de traitement pour partie] |

### 1.4 Transferts hors UE

Anthropic, PBC — États-Unis — CCT modules 2 et 3 (DPA Anthropic du 24/02/2025), addendum suisse ; TIA à rédiger
[À COMPLÉTER]. Seulement quand la clé API est configurée, et pour les clients qui n'ont pas désactivé l'extracteur
`llm` (`reglages.llm_desactive`). Minimisation : texte des pages du seul document concerné, et seulement quand
l'extraction déterministe est insuffisante ; dépense plafonnée par client et par mois. Le transfert ne dépend pas du
Data Privacy Framework (certification d'Anthropic à vérifier sur dataprivacyframework.gov).

### 1.5 Mesures de sécurité (art. 32) — résumé de `docs/SECURITY.md`

- Cloisonnement par client : couche d'accès unique, trois barrières indépendantes, tests d'accès croisé.
- Chiffrement au repos (Fernet, clé dérivée par client), sauvegardes chiffrées, TLS en transit, secrets hors dépôt.
- Argon2id pour les mots de passe ; second facteur TOTP pour le fondateur ; sessions limitées (30 min d'inactivité, 8 h).
- Journal d'audit append-only chaîné par SHA-256 ; chaque accès du fondateur à un client est journalisé avec motif.
- Documents traités comme des données (anti-injection) ; modèle de langage sans outil ni réseau ; aucun envoi externe sans validation.
- Journaux techniques sans contenu de document.
- Points ouverts : ancrage externe du journal d'audit, chiffrement du volume de la base (voir `docs/SECURITY.md` §6).

---

## Partie 2 — Registre du responsable de traitement (art. 30.1 RGPD)

### 2.1 Prospection commerciale B2B

| Rubrique | Contenu |
|---|---|
| Finalité | Présenter le service à des responsables de PME importatrices et à des cabinets d'expertise comptable |
| Base légale | Intérêt légitime ; message en rapport avec la fonction de la personne (art. L34-5 CPCE, CNIL) |
| Personnes concernées | Dirigeants, responsables financiers, achats ou logistique ; experts-comptables |
| Données | Nom, prénom, fonction, entreprise, e-mail et téléphone professionnels, historique des échanges |
| Source | Collecte directe, annuaires professionnels, sites d'entreprise ; **pas d'extraction automatisée de LinkedIn** |
| Information et opposition | Expéditeur identifié et lien ou réponse de désinscription dans chaque message ; liste d'opposition conservée |
| Destinataires | Fondateur ; messagerie [À COMPLÉTER : fournisseur, pays] |
| Durée | 3 ans à compter de la collecte ou du dernier contact émanant du prospect (référentiel CNIL « gestion des activités commerciales ») ; un e-mail envoyé par ControlDOne ou son ouverture ne relance pas le délai ; liste d'opposition conservée pour la respecter |
| Transferts hors UE | [À COMPLÉTER] |
| Sécurité | Compte de messagerie avec second facteur ; fichier de prospection chiffré [À COMPLÉTER] |

### 2.2 Gestion des clients et facturation

| Rubrique | Contenu |
|---|---|
| Finalité | Contrat, comptes d'accès, facturation (diagnostic, abonnement, commission), paiement des factures de ControlDOne |
| Base légale | Exécution du contrat ; obligation légale (conservation comptable) |
| Personnes concernées | Contacts et utilisateurs des clients |
| Données | Identité, coordonnées professionnelles, identifiants, factures, paiements |
| Destinataires | Fondateur ; Stripe ; [À COMPLÉTER : expert-comptable de ControlDOne] |
| Durée | Durée du contrat ; pièces comptables 10 ans |
| Transferts hors UE | [À COMPLÉTER] |

### 2.3 Messages reçus (contact par e-mail)

| Rubrique | Contenu |
|---|---|
| Finalité | Répondre aux demandes |
| Base légale | Intérêt légitime |
| Données | Nom, e-mail, entreprise, contenu du message |
| Durée | [À COMPLÉTER : par exemple 3 ans après le dernier échange] |

### 2.4 Site public

Aucun cookie, aucun traceur, aucun formulaire. Journaux techniques de l'hébergeur :
[À COMPLÉTER : hébergeur, contenu, durée].

---

## Partie 3 — Suisse (nLPD, en vigueur depuis le 1er septembre 2023)

| Rubrique | Contenu |
|---|---|
| Registre | Non obligatoire (moins de 250 collaborateurs, pas de données sensibles à grande échelle ni de profilage à risque élevé : art. 24 OPDo), mais tenu : le présent registre vaut pour la LPD |
| Sous-traitance | L'accord de sous-traitance (`site/dpa.html`) vaut contrat au sens de l'art. 9 LPD ; clause d'extension LPD (art. 13 du DPA) |
| Transferts | UE adéquate (annexe 1 OPDo) ; États-Unis : CCT avec addendum suisse (DPA Anthropic) |
| Autorité de contrôle | Préposé fédéral à la protection des données et à la transparence (PFPDT) |
| Information | Politique de confidentialité, section « Personnes en Suisse » |
| Prospection | Envois individuels et personnalisés seulement, jamais d'envoi de masse (art. 3 al. 1 let. o LCD) [À VALIDER par un avocat suisse] |
| Représentant en Suisse (art. 14 LPD) | A priori non requis [À VALIDER] |
