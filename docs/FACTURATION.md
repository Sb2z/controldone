# ControlDOne v2 — Facturation du fondateur

Ce document décrit la facturation **des prestations du fondateur** à ses clients : offres, cycle d'une
facture, numérotation, Factur-X, paiements (Stripe en mode test ou bouchon), plateforme agréée partenaire,
suivi financier. Il décrit aussi le contrôle « avant paiement » des factures que les **clients** reçoivent
de leurs transitaires.

- Code : `src/controldone/facturation/` (logique), `src/controldone/storage/facturation.py` et
  `storage/models_facturation.py` (persistance), `src/controldone/web/routes_finances.py` (pages).
- Configuration : `config/offres.yaml`.
- Tests : `tests/facturation/`.
- Décisions : D-1001 à D-1012 (`docs/DECISIONS.md`, section « Facturation »).

> **ControlDOne n'est pas une plateforme agréée (PA) et ne prétend pas l'être.** Il ne transmet aucune
> facture ni aucune donnée à l'administration. Il ne fait pas d'e-reporting et ne gère pas l'annuaire.
> Pour ses propres factures, le fondateur passe par une PA immatriculée qu'il choisit (§7). Côté client,
> ControlDOne **propose** un statut ; c'est le client qui l'applique dans **sa** PA (§5).

---

## 1. Offres

Les offres sont définies dans `config/offres.yaml`. Elles se modifient sans toucher au code.

| Offre | Prix (HT) | Règle |
|---|---|---|
| Diagnostic | 390 EUR, forfait | Une facture par diagnostic. |
| Commission | 20 % des avoirs obtenus | Base §17.4 : crédits imputés sur des écarts issus de constats **validés**. Arrondi au centime, demi supérieur. |
| Contrôle continu — Essentiel | 99 EUR / mois | Jusqu'à 20 dossiers par mois. |
| Contrôle continu — Pro | 199 EUR / mois | Jusqu'à 60 dossiers par mois. |
| Contrôle continu — Intensif | 349 EUR / mois | Jusqu'à 150 dossiers par mois. |

Les trois paliers et leurs quotas sont des **valeurs de départ, à ajuster**. Ce sont des hypothèses
commerciales, pas encore testées sur le marché. `CatalogueOffres.palier_pour(n)` propose le plus petit
palier qui couvre un volume donné.

**Offre de lancement** : le coupon `LANCEMENT-3-DIAGNOSTICS` donne une remise de 100 % sur un diagnostic.

- Quota : 3 utilisations au total, une seule par client.
- Contrepartie : le client signe un accord qui autorise la publication de ses résultats anonymisés.
  L'accord est obligatoire. Le fondateur saisit :
  - le drapeau « signé » ;
  - le nom du signataire ;
  - la date ;
  - la référence du document signé (conservé hors ligne).
- Contrôles :
  - quota et unicité vérifiés une première fois à la création du brouillon ;
  - revérifiés **sous verrou** à l'émission ;
  - consommation enregistrée dans `coupons_utilisations`, dans la même transaction que la facture.
- La facture porte la ligne à 390 EUR et une remise de document (BG-20) de 390 EUR. Le total est de 0 EUR.

**TVA.**

- Hypothèse par défaut : le fondateur est assujetti à la TVA (taux de 20 %, catégorie `S`).
- Alternative : franchise en base. Pour l'activer, mettre `tva.tva_applicable: false` (ou
  `CONTROLDONE_TVA_APPLICABLE=false`). Effets :
  - catégorie `E`, taux 0 ;
  - motif d'exonération « TVA non applicable, art. 293 B du CGI » imprimé et repris dans le XML (BT-120,
    note `TXD`) ;
  - code `VATEX-FR-FRANCHISE`.
- L'option pour le paiement de la TVA d'après les débits (`tva.option_debits`) est désactivée par défaut.
  Une fois activée :
  - la mention est imprimée ;
  - le XML porte BT-8 = `5` (date de facture).

## 2. Cycle d'une facture (aucun envoi automatique)

```
brouillon facture_emise ──(fondateur : approuver / corriger)──> approuvé
      │                                                            │
      │ refuser (motif)                     émission : numéro, TVA, mentions, XML CII validé (XSD),
      ▼                                     PDF/A-3 Factur-X ; facture IMMUABLE (table append-only)
   refusé                                                          │
                                       dépôt sur la PA partenaire (bouchon) + copie locale ──> envoyé
```

1. **Brouillon.** Plusieurs sources créent un brouillon `facture_emise` :
   - la page « Finances » (diagnostic, abonnement, commission) ;
   - l'agent `facturation` ;
   - le service des litiges (commission) ;
   - un webhook `invoice.paid` (abonnement déjà payé).

   Le brouillon contient les lignes HT, la remise, la TVA estimée et les références. Il n'a pas encore de
   numéro. Les clés d'idempotence sont partagées avec l'agent et les litiges, ce qui évite les doublons :
   - `facture:diagnostic:<client>` ;
   - `facture:abonnement:<client>:<mois>` ;
   - `commission:<client>:<avoir>`.
2. **Approbation** par le fondateur dans la file de validation. Les garde-fous de formulation s'appliquent
   comme pour toute action sortante.
3. **Émission.** Elle est déclenchée par l'approbation (`publication.mettre_a_disposition`) ou par le
   bouton « Émettre et déposer » de la page « Finances ». Étapes :
   - attribution du numéro suivant ;
   - calcul exact en `Decimal` ;
   - génération du XML CII, puis validation contre le XSD Factur-X EN 16931 ;
   - production du PDF lisible (ReportLab) et embarquement du XML (`facturx.generate_from_binary`,
     PDF/A-3, profil `en16931`).

   La facture est stockée dans la table `factures` : XML, PDF, empreinte SHA-256, instantané de l'acheteur
   et des mentions. Cette table est **append-only** :
   - le garde ORM refuse les modifications ;
   - des déclencheurs SQL refusent UPDATE et DELETE.
4. **Dépôt** : `ExpediteurFacture` dépose le PDF Factur-X sur la PA partenaire, puis le statut 200
   « Déposée » est enregistré. Une copie est écrite dans `<data_dir>/outbox_envoyee/facture_emise/`.
5. **Correction** par un **avoir** (type 381, série `AV`), jamais par modification de la facture :
   - l'avoir cite la facture d'origine (BT-25 et BT-26) ;
   - le cumul des avoirs est plafonné au HT de la facture d'origine ;
   - ce plafond est vérifié à la création du brouillon et à l'émission.
6. Après approbation, si l'émission est impossible, le fondateur voit le motif et la facture reste à
   émettre. Exemples : vendeur incomplet en production, coupon épuisé.

**Identité du vendeur.** Elle se règle dans `config/offres.yaml` ou par les variables
`CONTROLDONE_VENDEUR_<CHAMP>`, par exemple `CONTROLDONE_VENDEUR_SIREN`. Champs : raison sociale, forme
juridique, SIREN, RCS, TVA, adresse, courriel, IBAN, BIC. Tant qu'un champ vaut « À COMPLÉTER » :

- le PDF porte un bandeau « DOCUMENT NON VALABLE » ;
- en production (`CONTROLDONE_ENV=prod`), l'émission est **refusée**.

**Identité de l'acheteur** : `reglages["facturation"]` du client. Clés :

- `siren`, `tva_intracom` ;
- `adresse_ligne`, `code_postal`, `ville`, `pays` ;
- `email` ;
- `adresse_electronique` (par défaut, le SIREN) ;
- `livraison_*`, si l'adresse de livraison diffère de celle du client.

## 3. Numérotation

- Une série **continue** par entité légale (`vendeur.identifiant`), par préfixe et par année :
  `F-2026-0001`, `F-2026-0002`… et `AV-2026-0001` pour les avoirs.
- **Atomicité** : allocation et insertion se font dans une seule transaction d'écriture (SQLite
  `BEGIN IMMEDIATE`, PostgreSQL `SELECT … FOR UPDATE` sur le compteur).
- **Pas de trou** : si la construction de la facture échoue (XSD, coupon épuisé…), la transaction est
  annulée et le numéro n'est pas consommé.
- **Concurrence** : un test lance 8 fils × 5 émissions et vérifie la séquence 1..40, sans trou ni doublon.
- **Chronologie** : dans une série, une date d'émission antérieure à la dernière est refusée.
- **Idempotence** : une seule facture par action sortante (`outbox_id` unique).
- **Conservation** : les factures sont des pièces comptables conservées 10 ans (art. L123-22 C. com.).
  Elles survivent à l'effacement d'un client : `client_id` n'est pas une clé étrangère.

## 4. Contenu Factur-X (CII D16B, profil EN 16931)

| Donnée | Où |
|---|---|
| Cadre de facturation / catégorie d'opération : `S1` (prestation de services) | BT-23 `BusinessProcessSpecifiedDocumentContextParameter` + mention imprimée |
| SIREN du vendeur et de l'acheteur | BT-30 / BT-47, `SpecifiedLegalOrganization/ID@schemeID=0002` |
| Adresses électroniques (annuaire) | BT-34 / BT-49, `URIID@schemeID=0225`, par défaut le SIREN |
| N° TVA du vendeur (si assujetti), de l'acheteur s'il est connu | BT-31 / BT-48 |
| Pénalités de retard (BCE + 10 points, L441-10) | note `PMD` + PDF |
| Indemnité forfaitaire de recouvrement de 40 EUR (L441-10, D441-5) | note `PMT` + PDF |
| Absence d'escompte | note `AAB` + PDF |
| Franchise en base ou option sur les débits | note `TXD`, BT-120/121 ou BT-8 = 5 |
| Traitement B2B | note `BAR` = `B2B` |
| Adresse de livraison si différente | BT-75 à BT-80 (`ShipToTradeParty`) |
| Forme juridique, RCS | note `REG` + pied du PDF |
| Échéance, IBAN (virement SEPA, code 58) | BT-9, BT-84 |
| Avoir : facture d'origine | BT-25, BT-26 |

**Validation.**

- Le XSD est vérifié à chaque émission (`facturx.xml_check_xsd`, profil `en16931`).
- `facturx_cii.controles_reforme` vérifie un sous-ensemble des règles françaises BR-FR et inscrit les
  anomalies dans la facture (`contenu.controles_reforme`) :
  - SIREN à 9 chiffres ;
  - adresses électroniques qui commencent par le SIREN ;
  - numéro de 35 caractères au plus.
- Le schématron EN 16931 et le schématron français « Flux 2 » demandent un processeur XSLT 2.0 (Saxon). Ils
  **ne sont pas exécutés** (point ouvert).

**PDF/A.**

- Les polices DejaVu sont embarquées.
- `factur-x` pose les métadonnées XMP PDF/A-3 et le fichier associé (`/AF`).
- La conformité PDF/A-3 complète n'a **pas** été vérifiée avec veraPDF : à faire avant la première facture
  réelle.

## 5. Contrôle avant paiement, côté client

Un client reçoit les factures électroniques de ses transitaires par deux voies :

- par l'API `POST /api/v1/einvoices` (Factur-X, UBL ou CII) ;
- par le connecteur `PlateformeAgreeeEntrante` (D-631), qui lit les factures mises à sa disposition par sa
  PA.

Dans les deux cas :

1. un lot « avant paiement » est créé, avec les jobs `traiter_lot` et `controle_avant_paiement`. Pour
   l'API, `facturation.avant_paiement.mettre_en_file_controle` lit le numéro et l'échéance dans le XML, comme
   des **données**, avec un analyseur sans entités ni réseau ;
2. le lot passe les contrôles ;
3. s'il y a des écarts certains recouvrables non rejetés, un brouillon `statut_litige_pa` **propose au
   client** le statut « en litige », avec le motif chiffré (écarts par composante) ;
4. le fondateur valide le brouillon, puis le client décide et applique lui-même le statut dans **sa** PA.

« Refusée » n'est jamais proposé : il est réservé aux trois motifs prévus par la norme. Le test de bout en
bout est `tests/facturation/test_avant_paiement.py` (route API, file de tâches, worker, brouillon).

## 6. Paiements : Stripe en mode test, ou bouchon

- **Sans clé** : `PaiementBouchon` est utilisé automatiquement. Les pages de paiement sont simulées
  (`/admin/finances/bouchon/<session>`). Les événements ont le format Stripe et sont signés avec
  `STRIPE_WEBHOOK_SECRET` (ou, à défaut, un secret aléatoire propre au processus, jamais écrit dans le code :
  personne ne peut forger un événement accepté par `/webhooks/stripe`), puis vérifiés par le **même**
  `stripe.Webhook.construct_event`. Tout le flux est testable hors ligne.
- **Avec `STRIPE_SECRET_KEY`** : `PaiementStripe` (`stripe.StripeClient`, une clé par instance).
  - Une clé `sk_test_…` (ou `rk_test_…`) est acceptée.
  - Une clé `sk_live_…` est **refusée**, sauf si `CONTROLDONE_ENV=prod` **et** `STRIPE_LIVE_OK=1`.
  - Les tests n'appellent jamais Stripe : le client Stripe est simulé.
- **Paiement unique** (diagnostic, commission) : Checkout Session `mode=payment` du net à payer TTC, avec
  les métadonnées `client_id`, `facture_id` et `numero`. Le webhook `checkout.session.completed` enregistre
  l'encaissement, rattaché à la facture.
- **Abonnement** (contrôle continu) : Checkout Session `mode=subscription`, prix mensuel TTC récurrent.
  - `checkout.session.completed` : abonnement actif (table `comptes_paiement`) ;
  - chaque `invoice.paid` enregistre l'encaissement et crée le brouillon de facture du mois, marqué
    « déjà payé » (BT-113) ;
  - `invoice.payment_failed` déclenche une alerte au fondateur.
- **La facture légale est la facture Factur-X du fondateur.** Stripe ne sert qu'à encaisser. Montants :
  TTC calculé par notre code, sans Stripe Tax.
- **Idempotence** : chaque événement est enregistré une seule fois (`evenements_paiement.id` = identifiant
  de l'événement). Les effets (compte, brouillon, alerte) sont idempotents.
- **Webhook** : `POST /webhooks/stripe`, public. Une signature absente, fausse ou trop ancienne (plus de
  5 minutes) donne une réponse 400. Une métadonnée `client_id` inconnue n'a aucun effet.

### Mise en place de Stripe en mode test (fondateur)

1. Ouvrir un compte Stripe sur stripe.com, en tant qu'entreprise française. Rester en **mode test**
   (sandbox) : aucune activation du compte n'est nécessaire pour tester.
2. Dans le tableau de bord, menu Développeurs, puis Clés API : copier la **clé secrète de test**
   `sk_test_…` dans la variable d'environnement `STRIPE_SECRET_KEY` du serveur. Ne jamais la mettre dans un
   fichier versionné. La clé publiable `pk_…` n'est pas utilisée.
3. Menu Développeurs, puis Webhooks, puis « Ajouter un point de terminaison » :
   - URL : `https://<votre-domaine>/webhooks/stripe` ;
   - événements :
     - `checkout.session.completed` ;
     - `invoice.paid` ;
     - `invoice.payment_failed` ;
     - `customer.subscription.updated` ;
     - `customer.subscription.deleted`.

   Copier le **secret de signature** `whsec_…` dans `STRIPE_WEBHOOK_SECRET`.
4. En local : `stripe listen --forward-to localhost:8000/webhooks/stripe` (CLI Stripe). La commande affiche
   un `whsec_…` à utiliser comme `STRIPE_WEBHOOK_SECRET`. `stripe trigger checkout.session.completed`
   permet de tester l'envoi d'un événement.
5. Carte de test : `4242 4242 4242 4242`, date future, CVC quelconque. Carte refusée : `4000 0000 0000 0002`.
6. Dans Facturation, puis Paramètres, **désactiver l'envoi automatique des factures Stripe** aux clients :
   seule la facture Factur-X du fondateur fait foi. Activer le **portail client** pour la résiliation en
   ligne (voir l'hypothèse 3 de `docs/recherche/legal_market.md`).
7. Les abonnements de test sont annulés par Stripe après 90 jours. Les *test clocks* simulent les
   renouvellements.
8. Production (plus tard) :
   - activer le compte (identité, IBAN) ;
   - utiliser `sk_live_…` **et** `CONTROLDONE_ENV=prod` **et** `STRIPE_LIVE_OK=1` ;
   - créer un nouveau webhook « live » avec son propre `whsec_…`.

## 7. Plateforme agréée partenaire (factures du fondateur)

- Interface `facturation.pa.PlateformeAgreee` :
  - `deposer_facture` (idempotent par numéro) ;
  - `statut` ;
  - `recevoir_statuts` (chaque statut n'est rendu qu'une fois).
- Bouchon : `PlateformeAgreeeBouchon`, qui écrit dans `var/pa_bouchon/` (`deposees/`, `statuts/`).
- Le bouton « Relever les statuts » enregistre les statuts reçus dans `statuts_factures_pa`
  (append-only).
- **Obligations du fondateur**, d'après `docs/recherche/einvoice.md` (sources impots.gouv.fr) :
  - **réception** des factures électroniques par une PA obligatoire pour toutes les entreprises depuis le
    **1er septembre 2026** ;
  - **émission** obligatoire au plus tard le **1er septembre 2027** pour les PME, TPE et
    micro-entreprises. Pour les grandes entreprises et les ETI, elle l'est depuis le 1er septembre 2026.
- Avant le 1er septembre 2027, le fondateur peut émettre ses factures Factur-X par courriel. Il doit
  néanmoins **disposer d'une PA de réception** dès maintenant.

### Liste de contrôle pour choisir la PA partenaire

1. **Immatriculation** : vérifier que la PA figure sur la liste officielle des plateformes agréées
   (impots.gouv.fr). Une « solution compatible » ne suffit pas.
2. **Formats** : la PA accepte le dépôt de Factur-X EN 16931, ainsi que UBL et CII. Elle renvoie les
   **rejets de format** avant transmission.
3. **API** : dépôt de facture et lecture des statuts de cycle de vie par API (norme XP Z12-013). Elle offre
   un environnement de **bac à sable** et une documentation publique.
4. **Statuts** : la PA restitue au moins Déposée, Rejetée, Refusée et Encaissée, horodatés, ainsi que les
   statuts intermédiaires (mise à disposition, en litige…).
5. **E-reporting** : la PA transmet les données de paiement (statut Encaissée pour les prestations de
   services). Elle couvre l'e-reporting si des clients sont hors de France.
6. **Réception** : la PA reçoit les factures des fournisseurs du fondateur (obligation du 1er septembre 2026)
   et inscrit le fondateur dans l'annuaire.
7. **Sécurité et hébergement** : ISO 27001, hébergement dans l'UE (SecNumCloud si le cloud est externalisé),
   authentification forte, contrat de sous-traitance (art. 28 RGPD).
8. **Prix** : offre gratuite ou forfait adapté à un faible volume (une dizaine de factures par mois). Il
   existe plus d'une dizaine d'offres gratuites selon la FAQ officielle.
9. **Réversibilité** : export des factures et des statuts, durée de conservation, conditions de sortie.
10. **Support** : interlocuteur en français, délai de réponse, engagement de disponibilité.

## 8. Suivi financier (page « Finances »)

- **CA HT** du mois = factures émises − avoirs émis, à la date d'émission.
- **Encaissé TTC** = événements de paiement réussis, au mois de l'événement.
- **Coût IA** = registre `ai_usage`, par client, par mois et par dossier. La lecture transversale est
  journalisée (`lire_couts_ia`).
- **Marge brute** = CA HT − coût IA. Hypothèse : l'hébergement et les frais Stripe ne sont pas ventilés par
  client ; ils se suivent en comptabilité.
- Contenu de la page :
  - indicateurs du mois ;
  - tableaux par mois et par client ;
  - factures (PDF, XML, lien de paiement, avoir, statut PA) ;
  - encaissements ;
  - dossiers les plus coûteux en IA ;
  - formulaires de brouillon.
- **Export CSV** : séparateur `;`, virgule décimale, UTF-8 avec BOM. Les cellules qui commencent par `=`,
  `+`, `-` ou `@` sont neutralisées (protection contre l'injection de formules).

---

## 9. Faits vérifiés et hypothèses

### Faits vérifiés (le 2 octobre 2026)

| Fait | Source |
|---|---|
| Réception obligatoire au 1er septembre 2026 pour toutes les entreprises ; émission au plus tard le 1er septembre 2027 pour les PME, TPE et micro-entreprises | `docs/recherche/einvoice.md` : https://www.impots.gouv.fr/actualite/facturation-electronique, FAQ impots.gouv.fr |
| Mentions de la réforme et leur balise : SIREN du vendeur (BT-30) et de l'acheteur (BT-47) au 1/09/2026, catégorie de l'opération (BT-23, codes à racine B/S/M), option TVA sur les débits (BT-8), adresse de livraison (BT-75 à BT-80, au 1/09/2027), escompte en note `AAB`, mention de taxe en note `TXD` | PDF officiel « Données de facture et correspondance des flux » : https://www.impots.gouv.fr/facturation-electronique-donnees-de-facture-et-correspondance-des-flux-de-donnees (lu ce jour) |
| BT-23 `S1` = prestation de services (`B1` biens, `M1` mixte, `S2` facture déjà payée) | Schématron BR-FR « Flux 2 » livré avec `factur-x` 7.1 (règle BR-FR-08, liste des valeurs admises) ; confirmé par des sources secondaires (compta-online.com, cas d'usage AFNOR) |
| Notes obligatoires `PMD`, `PMT`, `AAB`, chacune une seule fois ; `TXD` une seule fois ; `BAR` ∈ {B2B, …} | Schématron BR-FR-05, BR-FR-06, BR-FR-20 (`factur-x` 7.1) |
| SIREN à 9 chiffres (`schemeID 0002`) ; adresse électronique de l'acheteur avec `schemeID 0225`, commençant par son SIREN ; numéro de facture de 35 caractères au plus ; avoir avec référence à la facture antérieure | Schématron BR-FR-10, BR-FR-11, BR-FR-21, BR-FR-32, BR-FR-01, BR-FR-CO-05 |
| Codes de type autorisés (380 facture, 381 avoir…) | Schématron BR-FR-04 |
| Pénalités : au moins BCE + 10 points ; indemnité forfaitaire due de plein droit | `docs/recherche/legal_market.md` (L441-10, Légifrance) |
| Webhooks Stripe signés (`Stripe-Signature`, v1 HMAC-SHA256), mode test `sk_test_`, carte 4242… | `docs/recherche/legal_market.md` §5 (docs.stripe.com) ; vérification hors ligne par `stripe.Webhook.construct_event` (bibliothèque `stripe` 16.0) |
| XML conforme au XSD Factur-X EN 16931 (fichiers « Factur-X 1.09 » de la bibliothèque) | Tests `tests/facturation/test_facturx.py` |

### Hypothèses (à faire confirmer)

1. **Assujettissement à la TVA** du fondateur (taux de 20 %). L'alternative de la franchise en base est
   prévue par la configuration.
2. **Coupon contre droit de publication** : une prestation rendue contre une contrepartie non monétaire peut
   être une opération imposable (échange). La base serait alors la valeur du service, pas 0 EUR. **À faire
   valider par l'expert-comptable** avant le premier diagnostic gratuit.
3. **Montant de 40 EUR** (D441-5) : non relu sur Légifrance (brief juridique, confiance élevée).
4. **Statuts de cycle de vie** : la liste 200 à 213 vient de sources non officielles. Seuls Déposée,
   Rejetée, Refusée et Encaissée seraient obligatoires. À confirmer sur XP Z12-012.
5. **Note `REG`** pour la forme juridique et le RCS : choix d'usage. Aucune règle BR-FR ne la vérifie.
6. **Série séparée pour les avoirs** (`AV`) : admise si chaque série est continue et chronologique. À
   confirmer avec l'expert-comptable.
7. **Paliers 99 / 199 / 349 EUR** et quotas de 20 / 60 / 150 dossiers : valeurs de départ, non testées.
8. **PDF/A-3** : conformité complète non vérifiée (veraPDF non exécuté).
9. **Schématrons** EN 16931 et BR-FR non exécutés (XSLT 2.0). Seul le XSD et quelques règles BR-FR codées
   sont contrôlés.
10. **Frais Stripe** non intégrés à la marge brute.

## 10. Points ouverts

- Branchement d'une vraie PA (API XP Z12-013) derrière `PlateformeAgreee` une fois le partenaire choisi.
- Exécution des schématrons (Saxon en service séparé, ou validation par la PA en bac à sable).
- Mise à disposition des factures dans l'espace client et envoi par courriel (brouillon approuvé), tant que
  l'émission par PA n'est pas obligatoire.
- Rapprochement automatique des virements SEPA (relevé bancaire) avec les factures.
