# Plan des trois premières actions commerciales — ControlDOne

*Version 1.0 — 2 octobre 2026. Plan pour un fondateur seul, à temps partiel. Les durées sont des estimations de travail effectif, pas des délais de réponse des prospects.*

## Vue d'ensemble

| # | Action | Durée de travail estimée | Échéance cible | Critère de réussite |
|---|---|---|---|---|
| 1 | Obtenir et réaliser 3 diagnostics gratuits | 25 à 35 h | 8 semaines | 3 diagnostics livrés, chacun avec au moins 15 dossiers d'import analysés et un rapport validé |
| 2 | Ouvrir le canal experts-comptables | 6 à 8 h | 6 semaines | 2 rendez-vous tenus avec des cabinets ; au moins 1 cabinet qui accepte de présenter l'offre à un client importateur |
| 3 | Publier la série LinkedIn et l'article | 5 à 6 h | 6 semaines | 5 posts + 1 article publiés ; au moins 3 conversations entrantes avec des personnes en poste dans une PME importatrice ou un cabinet |

**Critère d'arrêt (stratégie)** : si les 3 diagnostics réunis font apparaître, en moyenne, **moins de 3 000 à 4 000 EUR d'écarts par client et par an** (écarts `ecart_certain` en défaveur du client, extrapolés à l'année à partir du lot analysé, hors notes de renvoi), on arrête le développement commercial du produit sous sa forme actuelle. On ne relance pas une seconde vague de prospection pour « trouver de meilleurs clients » : on documente le résultat et on décide (arrêt, ou changement de cible ou d'offre, décidé à froid).

Calcul de l'extrapolation, fixé à l'avance pour ne pas l'ajuster après coup : `écarts constatés sur le lot × (nombre de dossiers par an déclaré par le client / nombre de dossiers du lot)`. Le nombre de dossiers par an est demandé au client avant l'analyse et noté dans la fiche du diagnostic.

---

## Action 1 — Les 3 diagnostics gratuits (priorité absolue)

**But** : mesurer, sur des dossiers réels, si les écarts entre facture fournisseur, déclaration, facture du transitaire et avoirs représentent un montant qui justifie un service payant. C'est le test de la stratégie.

**Offre** : diagnostic gratuit sur un lot de dossiers passés (idéalement les 20 à 30 derniers dossiers, ou 6 mois), au titre d'une remise commerciale de lancement de 100 %. L'autorisation de publier des résultats anonymisés est proposée à part, facultative et révocable jusqu'à la publication, sans effet sur la remise (brief juridique §4.4). Aucun montant promis.

**Étapes**

1. **Préparer les pièces contractuelles (3 h)**
   - accord de diagnostic d'une page (remise de lancement de 100 %) : périmètre, durée de conservation des documents, absence de conseil juridique, fiscal ou douanier (avertissement de la SPEC §3.4) ; signature à distance (devis accepté par e-mail), jamais sur place chez un client de 5 salariés au plus (art. L221-3 C. conso.) ;
   - accord de publication **distinct et facultatif** : résultats anonymisés (pas de nom, pas de montant identifiant), relecture par le client, retrait possible jusqu'à la publication ;
   - accord de sous-traitance art. 28 RGPD (les documents contiennent des données personnelles : noms, signatures) — voir `docs/recherche/legal_market.md` §2 ;
   - liste des pièces demandées : factures fournisseurs, déclarations (ou extractions DELTA fournies par le transitaire), factures du transitaire, avoirs, grille tarifaire ou devis signé.
2. **Prospection (8 à 10 h, semaines 1 à 4)**
   - valider puis envoyer à la main les 20 brouillons de `brouillons/` (après relecture du fondateur), 5 par jour au plus ;
   - relances J+5 et J+12 selon `sequence_emails.md`, uniquement sans réponse ; un STOP est noté le jour même ;
   - en parallèle, demandes de connexion LinkedIn ciblées (message de `sequence_emails.md`), sans automatisation.
   - Objectif intermédiaire : 6 à 8 rendez-vous de 20 minutes pour obtenir 3 accords.
3. **Collecte des documents (2 h par client)** : dépôt sécurisé, contrôle de complétude (famille P de la SPEC), relance des pièces manquantes, en particulier la grille tarifaire.
4. **Analyse et validation (4 à 6 h par client)** : traitement du lot, revue de chaque constat par le fondateur (valider, rejeter, rétrograder), rédaction des notes de renvoi avec la phrase exacte.
5. **Restitution (1 h par client)** : rapport de diagnostic, présentation en visioconférence, relevé d'écarts et modèle de courrier neutre que le client adapte et envoie lui-même s'il le décide.
6. **Bilan (2 h)** : tableau des 3 diagnostics (nombre de dossiers, écarts certains, écarts à vérifier, notes de renvoi, extrapolation annuelle), comparaison au critère d'arrêt, texte anonymisé publiable.

**Critère de réussite** : 3 diagnostics livrés dans les 8 semaines, chacun sur au moins 15 dossiers, avec rapport validé et accord de publication signé.

**Critère d'échec intermédiaire** : moins de 3 accords obtenus après 40 prospects contactés et 4 semaines : revoir le message et la cible (taille, secteur) avant de continuer, et le noter.

---

## Action 2 — Canal experts-comptables

**But** : trouver un prescripteur qui voit passer les factures de transitaires de plusieurs clients importateurs.

**Étapes**

1. Envoyer un e-mail adapté (variante DAF de `sequence_emails.md`, en remplaçant l'offre par : « présenter le diagnostic gratuit à un ou deux de vos clients importateurs ») aux cabinets de `prospects.csv` (canal « expert-comptable »). (2 h)
2. Rendez-vous de 30 minutes : montrer un rapport sur cas fictif, expliquer la limite (pas de conseil juridique, fiscal ou douanier ; renvoi vers RDE ou avocat). (2 à 3 h)
3. Aucune commission d'apport aux cabinets, ni maintenant ni plus tard (art. 24 de l'ordonnance du 19 septembre 1945) : partenariat sans rémunération, le cabinet facture lui-même son temps à son client. (—)
4. Noter pour chaque cabinet : nombre approximatif de clients importateurs annoncé, intérêt, objection principale. (1 h)

**Critère de réussite** : 2 rendez-vous tenus et au moins 1 client importateur présenté par un cabinet.

---

## Action 3 — Présence LinkedIn (soutien des actions 1 et 2)

**But** : que les personnes contactées trouvent un contenu sérieux en regardant le profil du fondateur, et susciter quelques contacts entrants.

**Étapes**

1. Relire et ajuster `linkedin/posts.md` et `linkedin/article.md` (tous les cas sont fictifs et marqués comme tels ; la phrase de renvoi figure dès qu'un sujet réglementaire apparaît). Repasser `check_text` après toute modification. (2 h)
2. Mettre à jour le profil : fonction, offre de lancement, mention « résultats publiés anonymisés avec accord ». (1 h)
3. Publier un post par semaine pendant 5 semaines, l'article en semaine 3. (1 h au total)
4. Répondre aux commentaires et messages dans les 48 h, sans relance automatique. (1 à 2 h)

**Critère de réussite** : 3 conversations entrantes avec des personnes en poste dans une PME importatrice ou un cabinet d'expertise comptable.

---

## Garde-fous communs aux trois actions

- Ne rien envoyer ni publier sans relecture du fondateur.
- Aucun chiffre sans source ; aucun témoignage ou résultat client avant qu'il existe et que sa publication soit autorisée.
- Aucun avis sur un droit, une taxe, un classement, une origine, une valeur en douane ou un régime : phrase de renvoi exacte.
- Le relevé d'écarts et son modèle de courrier neutre sont adaptés et envoyés par le client lui-même ; ControlDOne ne contacte jamais le transitaire, ne relance pas pour le client et n'encaisse rien (SPEC §17.3, brief juridique §6.1).
- Aucune commission d'apport versée à un expert-comptable (art. 24 de l'ordonnance du 19 septembre 1945).
- Données de prospection : uniquement des coordonnées professionnelles publiées par l'entreprise ; information sur l'origine des données et désinscription dans chaque message ; registre des traitements tenu à jour (`docs/RGPD_registre.md`).
