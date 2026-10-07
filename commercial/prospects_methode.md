# Méthode de constitution du fichier de prospection

*Collecte du 2 octobre 2026. Fichier associé : `prospects.csv` (UTF-8, séparateur `;`). Script réutilisable : `scripts/prospection_sirene.py`.*

## 1. Ce que contient le fichier, et ce qu'il ne contient pas

- Uniquement des **entreprises réelles** trouvées dans des sources publiques, avec l'URL de chaque preuve.
- Uniquement des **coordonnées professionnelles publiées par l'entreprise elle-même** : adresse générique (contact@, info@, commercial@…) ou page Contact (formulaire) de son propre site, ou mentions légales. Aucune adresse devinée (prenom.nom@…), aucune adresse issue d'un annuaire tiers, d'un outil d'enrichissement ou de LinkedIn.
- Aucune donnée inventée. Quand une information n'a pas pu être vérifiée, la cellule le dit (« à vérifier »).
- Rien n'a été envoyé, publié ni créé (aucun compte).

## 2. Sources utilisées

| Source | Usage | Accès depuis l'environnement de collecte |
|---|---|---|
| API Recherche d'entreprises (https://recherche-entreprises.api.gouv.fr/search) | SIREN, code NAF, tranche d'effectif salarié INSEE (année 2023), commune du siège, état administratif, dirigeants (pour le contrôle d'appartenance à un groupe) | Bloquée depuis le terminal (connexion réinitialisée). Accessible via l'outil de lecture web, avec de nombreux refus 429/503 (limite de débit) : interrogations une par une, avec pauses |
| annuaire-entreprises.data.gouv.fr | Prévu en complément | Pages rendues côté navigateur : contenu illisible par l'outil de lecture web. Non utilisé |
| Recherche web (moteur généraliste) | Repérage de candidats par secteur (importateurs de produits asiatiques, fruits exotiques, fruits secs, café vert, thé, fleurs coupées, produits de la mer, jouets, articles de maison, spiritueux ; cabinets d'expertise comptable spécialisés import-export) | Accessible |
| Site de chaque entreprise | Preuve d'importation hors UE (citation courte), coordonnées publiées, mentions légales (SIREN) | Accessible pour la plupart ; quelques sites en erreur (502, 503, 307), signalés |

Les annuaires commerciaux (Europages, Kompass, Pages Jaunes, societe.com, Pappers) ont servi au **repérage** seulement. Aucune preuve ni aucun contact du fichier n'en provient.

## 3. Requêtes et filtres

**API Recherche d'entreprises** (exemples effectivement lancés) :

- `q=import&section_activite_principale=G&tranche_effectif_salarie=11,12,21,22,31&etat_administratif=A&per_page=25` (81 résultats ; la recherche porte surtout sur la dénomination) ;
- `q=import&activite_principale=46.49Z&tranche_effectif_salarie=11,12,21,22&etat_administratif=A` ;
- puis une interrogation par SIREN (`q=<siren>`) ou par nom + code postal pour chaque candidat repéré sur le web.

**Filtres de qualification appliqués à la main** :

1. Entreprise française active (`etat_administratif = A`).
2. Taille : tranche INSEE 11 (10-19 salariés) à 31 (200-249). Écartées : tranches 01, 02, 03 (moins de 10 salariés), NN (non renseignée), 32 et plus (250 salariés et plus).
3. Preuve d'importation **hors Union européenne** sur le site de l'entreprise : citation courte (« importateur… », « nous importons… », pays d'origine hors UE) avec l'URL.
4. Profil sans service douane interne apparent : grossiste, distributeur ou marque de taille PME. Ce point est une **présomption**, à confirmer lors du premier échange (colonne `raison_ciblage`).
5. Coordonnées publiées par l'entreprise elle-même.

**Requêtes web** (exemples) : « importateur distributeur produits asiatiques », « importateur fruits exotiques Rungis », « importateur fruits secs Turquie Iran », « importateur café vert », « importateur thé en vrac », « importateur fleurs coupées Kenya Colombie Équateur », « importateur crevettes surgelées », « importateur grossiste jouets », « expert-comptable import-export ».

**Tranches d'effectif (codes INSEE)** : 11 = 10-19 ; 12 = 20-49 ; 21 = 50-99 ; 22 = 100-199 ; 31 = 200-249.

## 4. Contrôle d'exclusion (L'Occitane, CHANEL)

Consigne : exclure L'Occitane, CHANEL et toutes leurs filiales et marques.

Pour chaque ligne :

1. La dénomination, l'enseigne et les marques citées sur le site ont été comparées à la liste des marques et sociétés connues des deux groupes : L'Occitane en Provence, Melvita, Erborian, Elemis, Sol de Janeiro, Dr. Vranjes Firenze, LimeLife, Grown Alchemist ; CHANEL, Paraffection et les Maisons d'art (Lesage, Lemarié, Massaro, Goossens, Desrues, Maison Michel, Causse, Montex, Barrie…), Eres, Holland & Holland. Cette liste vient de la connaissance générale des deux groupes et doit être relue par le fondateur.
2. Les dirigeants personnes morales renvoyés par l'API (holding présidente, par exemple) ont été lus : aucun ne porte le nom d'une société des deux groupes.
3. Quand le site mentionne un groupe d'appartenance (ex. Groupe Duval pour Terr'Asia, JMI Group pour Gel-Pêche), ce groupe a été noté et comparé à la liste.

Résultat : aucune des lignes retenues ne relève des groupes L'Occitane ou CHANEL. Le secteur cosmétique a été évité d'emblée pour limiter le risque. Le script `prospection_sirene.py` applique automatiquement la même liste (dénomination, enseignes, dirigeants personnes morales) et marque « NON » toute correspondance.

## 5. Base juridique et règles CNIL (prospection B2B)

Source : CNIL, « La prospection commerciale par courrier électronique », https://www.cnil.fr/fr/la-prospection-commerciale-par-courrier-electronique ; synthèse dans `docs/recherche/legal_market.md` §1.

- **Régime B2B d'opposition (opt-out)** : un professionnel peut être sollicité par e-mail sans consentement préalable si le message concerne sa profession (art. L34-5 CPCE ; intérêt légitime, art. 6.1.f RGPD). Nos messages visent la fonction de dirigeant, de responsable achats/import ou de DAF d'une entreprise qui importe : le lien avec la profession est direct.
- **Adresses génériques** (contact@, info@) : elles désignent une organisation et non une personne ; elles sortent du régime de protection des personnes, mais nous appliquons quand même les mêmes règles (identification, désinscription).
- **Adresses nominatives** publiées par l'entreprise (ex. une adresse prénom.nom@ affichée sur la page Contact) : ce sont des données personnelles. Elles ne sont utilisées que si l'entreprise les publie elle-même pour ce type de demande, et la personne est informée dès le premier message.
- **Information sur l'origine des données** (art. 14 RGPD) : chaque premier message indique où l'adresse a été trouvée (« votre adresse figure sur votre site, page Contact »), qui écrit (nom suivi de « EI », fonction, SIREN) et pourquoi.
- **Désinscription** : chaque message propose « répondez STOP », gratuit et immédiat. Un STOP est inscrit le jour même dans le fichier et l'adresse n'est plus jamais utilisée. L'opposition est possible dès le premier message.
- **LinkedIn** : pas d'extraction de profils (scraping), pas d'automatisation. Mêmes règles que l'e-mail par prudence (`legal_market.md`, hypothèse n° 1).
- **Durée de conservation** : 3 ans à compter de la collecte ou du dernier contact émanant du prospect, puis suppression ; les lignes sans réponse sont supprimées au plus tard 3 ans après la collecte. Confirmé : référentiel CNIL « gestion des activités commerciales » (3 ans à compter de la collecte ou du dernier contact émanant du prospect ; la simple ouverture d'un e-mail ne compte pas, un e-mail que nous envoyons non plus). Voir `docs/recherche/juridique_france_suisse.md` §5.3.
- **Employeur du fondateur** : ne jamais prospecter l'employeur actuel du fondateur, ni ses clients, fournisseurs ou transitaires, pendant toute la durée du contrat de travail (loyauté ; brief juridique §3.1). Vérifier chaque ligne avant envoi.
- **Registre** : ajouter le traitement « prospection commerciale B2B » au registre des activités de traitement (`docs/RGPD_registre.md`) : finalité, catégories de données (dénomination, adresse e-mail professionnelle, page source), base légale (intérêt légitime), durée, droits.

## 5 bis. Suisse et Belgique

Source : `docs/recherche/juridique_france_suisse.md` §5.5 (à faire confirmer par un avocat du pays concerné).

- **Suisse** : consentement préalable (opt-in) pour tout envoi de masse, en B2B comme en B2C (art. 3 al. 1 let. o LCD). Donc uniquement des e-mails individuels et personnalisés, rédigés un par un, en lien avec l'activité du destinataire ; jamais d'outil d'envoi groupé ; relances limitées. Identification de l'expéditeur et désinscription dans chaque message.
- **Belgique** : prospection par e-mail sans consentement seulement vers des adresses impersonnelles de personnes morales (info@, contact@). Adresses nominatives exclues sans consentement préalable.
- **Luxembourg** : aucune prospection avant avis d'un avocat luxembourgeois (monopole de la consultation juridique à vérifier).

## 6. Limites connues de ce fichier

- **Volume** : 26 lignes qualifiées (22 PME importatrices, 4 cabinets d'expertise comptable), pour un objectif de 40. Deux lignes restent à confirmer avant tout envoi (LX FRANCE : preuve et contact ; TERR'ASIA : rattachement du SIREN à l'établissement de Saint-Genis-Laval) et les SIREN de deux cabinets sont « à vérifier ». La limite de débit de l'API (refus 429/503 fréquents) et le temps de vérification d'une preuve d'import sur le site de chaque entreprise ont été les facteurs limitants.
- **Biais sectoriel** : surreprésentation de l'alimentaire importé (produits asiatiques, fruits, fruits secs, café, thé), parce que ces entreprises écrivent explicitement « importateur » sur leur site. Les marques non alimentaires qui font fabriquer en Asie l'écrivent rarement : elles sont sous-représentées.
- **Effectifs** : tranches INSEE de 2023, possiblement datées.
- **Absence de service douane interne** : présumée, non vérifiée. Un grossiste en fruits frais peut avoir un déclarant en interne ; à demander au premier échange.
- **Particularités du secteur** : pour certains produits (fruits et légumes frais, fleurs, produits de la mer), les contrôles sanitaires ou phytosanitaires et la saisonnalité changent la structure des factures du transitaire. Le diagnostic doit en tenir compte.

## 7. Relancer la collecte

> Depuis octobre 2026, ce fichier s'importe dans l'application (menu **Marketing**, ou `controldone prospection importer prospects.csv`), qui tient aussi la liste d'exclusion (`config/prospection.yaml`), les séquences et la liste d'opposition : voir `docs/PROSPECTION.md`.

Depuis un poste qui a accès à l'API :

```bash
python commercial/scripts/prospection_sirene.py --q import --q importateur --q impex --q trading \
    --pages 4 --pause 1.0 --sortie /tmp/squelette.csv
```

Le script produit un squelette (SIREN, NAF, tranche, commune, contrôle d'exclusion automatique). Les colonnes de qualification restent vides : elles se remplissent à la main, en lisant le site de chaque entreprise, selon les règles des sections 1, 3 et 5.

## 8. Candidats examinés puis écartés

Pour transparence, les entreprises vérifiées mais non retenues (aucune n'est dans `prospects.csv`) :

| Entreprise | SIREN | Motif |
|---|---|---|
| Winhonco | 337945968 | Tranche 6-9 salariés |
| SA Angelini (produits de la mer) | 697120764 | Tranche 6-9 salariés |
| LP Divertissements (Linder Partner) | 514274968 | Tranche 6-9 salariés |
| Wiz' Import (OBG.PUB) | 492337449 | Tranche 1-2 salariés |
| Asia Pack | 894824150 | Tranche 1-2 salariés |
| Doumie | 522497510 | Effectif non renseigné ; preuve d'import absente du site |
| France Fruits Secs International | 789647971 | Effectif non renseigné |
| Caminel SAS (importateur LS Tractor) | 846950053 | Tranche 250-499 salariés |
| Lu Shan | 432297448 | 1-2 salariés (source secondaire) |
| Sun 7 Fruits | — | 4 salariés (source secondaire) |
| Vimass | — | Société espagnole |
| Ribimex | 712045863 | Preuve d'import hors UE introuvable sur son propre site |
| AVM Import, Choco Suisse Import, Moore Import, DAG Import (MMKDO), Double D Import, IEV (groupe Rondy), Mastrad, Fartools, Terre Exotique, Moulin Roty, Cabaïa, Sveltus, Mash | — | Preuve d'import hors UE absente des pages lues, site illisible, ou taille hors cible |
| Paget France | — | Liquidée en 2012-2013 (source secondaire) |
| Artis Trading | 844021550 | Aucun site propre trouvé : ni preuve ni contact publiés par l'entreprise |
