# Rappels pour le fondateur — ce que toi seul peux fournir

Mis à jour le 6 octobre 2026, après tes décisions sur les 9 points. Ce fichier liste ce que j'attends de toi. Rien
ici n'est urgent tant que l'application n'est pas en ligne.

| # | À fournir | Pour | Où le mettre | Comment vérifier |
|---|---|---|---|---|
| 1 | Clé d'API Anthropic | lecture par Claude (décision 1A) | `.env` / `.env.prod`, toi-même ; jamais dans un message ni dans Git | commande donnée dans `docs/EXPLOITATION.md` (bloc LLM) |
| 2 | Plafond mensuel de dépense IA par client | lecture par Claude | fiche client (valeur par défaut sinon) | page Finances |
| 3 | Un vrai dossier, avec l'accord écrit du client, un contrat de sous-traitance RGPD, anonymisé, d'une entreprise non exclue | mesure réelle (décision 2A) | dépôt par toi dans l'application | rapport de mesure dédié |
| 4 | Adresse du sujet de notification sur téléphone (type ntfy) | alertes poussées (décision 8B) | `.env.prod` | `controldone alertes essai` |
| 5 | Choix de l'hébergeur et du nom de domaine | mise en ligne (décision 9A) | suivre `docs/MISE_EN_LIGNE.md` | liste de contrôle de mise en ligne |
| 6 | Compte Stripe vérifié, passage en mode réel | encaissement | tableau de bord Stripe | paiement d'essai |
| 7 | Vérifier ton quota de minutes GitHub Actions | CI à chaque envoi (décision 3A) | paramètres GitHub | onglet Actions |

Décisions mises en attente : préchargement HTTPS (5B, à revoir après le lancement) ; rapports et constats en
anglais (7B, plus tard).

**Ce que je ne ferai pas.** Je ne chercherai pas de dossiers d'employeurs, même anonymisés (CHANEL et ses filiales
sont exclues, règle de la salle blanche). Je n'achète rien, je ne crée aucun compte, je n'envoie rien et je ne
déploie rien à ta place.
