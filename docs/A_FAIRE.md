# ControlDOne — ce qui reste à faire

Ce fichier consolide les constats notés en cours de route dans `docs/backlog/` : un fichier par bloc, avec le détail
de chaque point (fichiers, mesures). Il est mis à jour le 7 octobre 2026, à la fin du lot 3. Les points sont classés par priorité. **Décision** signale ce qui demande l'accord ou
l'action du fondateur ; tout le reste peut être traité sans lui. Ce qui a été fait est listé en fin de fichier.

## 1. Décisions du fondateur

| Point | Pourquoi | Source |
|---|---|---|
| Activer l'extraction par modèle de langage (clé d'API) | réponse prévue aux mises en page vraiment inconnues | orchestrateur |
| Mesurer sur un premier dossier réel anonymisé, avec l'accord du client | seule mesure qui vaut pour le vrai monde | orchestrateur |
| Lancer la CI à chaque push / PR (avec PostgreSQL, audit d'image, navigateur) | consomme les minutes GitHub | orchestrateur, sécurité, production |
| Nettoyer l'historique Git (609 Mo de corpus ; adresse personnelle comme auteur des anciens enregistrements) | réécriture irréversible de l'historique déjà poussé | orchestrateur |
| HSTS `preload` | engagement difficile à retirer pour le domaine | sécurité |
| A13 (codes marchandise à sens unique) : 65 « à vérifier » de bruit pour 1 vrai | les réduire ferait perdre le vrai cas | moteur |
| Constats, rapports et relevés en anglais | formulations anglaises à valider contre les garde-fous juridiques | interface |
| Prestataire de courriel et adresse des alertes poussées (désactivées par défaut) | envoi vers l'extérieur | production |
| Hébergement, domaine, paiement réel, déploiement | actions extérieures | — |

## 2. Fiabilité et sécurité de la production

| Point | Source | Effort |
|---|---|---|
| Image Docker sans `pg8000` ni `postgresql-client` (sauvegarde PostgreSQL impossible dans l'image) | production | petit |
| Redémarrages en boucle du web et du worker quand une migration attend, pendant une mise à jour | production | petit |
| Suppression RGPD d'un client (`supprimer_client`) sans le verrou de maintenance | production | petit |
| Verrou de maintenance limité à un seul hôte | production | moyen |
| 77 vulnérabilités élevées ou critiques sans correctif Debian dans l'image (libxml2, libtesseract, libtiff, curl…) : suivi | sécurité | suivi |
| Traces d'envoi en clair sur le disque (`outbox_envoyee`) | sauvegardes | moyen |
| RPO de 24 h : deux sauvegardes par jour, ou journal de transactions | sauvegardes | moyen |
| Exercice mensuel sur une vraie archive ; test de la copie séquestrée de la clé | sauvegardes | procédure |
| Historique des notifications envoyées visible dans l'interface | production | petit |
| Reporter D-3601 à D-3605 dans `docs/SECURITY.md` | sécurité | petit |

## 3. Moteur

| Point | Constat | Effort |
|---|---|---|
| D1 : deux faux certains restants sur les jeux `--ext` (un piège, un non apparié) | antérieurs au lot 2 | moyen |
| Bruit encore au-dessus de l'alerte sur deux jeux tenus à l'écart (1,49 et 1,55) | P4 restants, C5 sur relevés et TVA autoliquidée, doublons P1, A2, B2 total | moyen |
| Rappel des erreurs attendues « certain » : 55 à 75 % selon les jeux | F3 rattachement faible, B1 sur scans, A5 taux OCR | moyen |
| Totaux par code non lus sur certaines mises en page dégradées (encore 34 à 133 manquants selon les jeux) | rappel B2 par code | moyen |

## 4. Interface

| Point | Effort |
|---|---|
| Messages d'erreur des services et page de documentation de l'API encore en français seulement | petit |

## 5. Dépôt et outillage

| Point | Effort |
|---|---|
| Réécriture de l'historique Git (corpus `corpus_g3`–`g5`, anciens courriels d'auteur, décision 4A) : corpus régénérables et vérifiés (`make corpus-verifier`, D-4403) ; ensuite retirer leurs exceptions de `.gitignore` | moyen |
| Seuil minimal de couverture (`COUV_MIN`) une fois la base stabilisée ; modules les moins couverts : `storage`, `services`, `web` | moyen |
| Formatage automatique (`ruff format`) : 301 fichiers à reformater, à faire en un seul enregistrement isolé | petit |

## Fait pendant les lots 1 et 2

Sauvegarde et restauration vérifiées de bout en bout, SQLite et PostgreSQL (D-3301 à D-3306, D-3501) · alertes
poussées, désactivées par défaut (D-3502) · migrations de schéma et index (D-3503) · verrou de maintenance (D-3504) ·
limitation de débit en base, révocation des sessions, sessions actives (D-3201, D-3202, D-3604 à D-3610) ·
`make audit`, SBOM, dépendances avec empreintes, audit de l'image (D-3203, D-3609) · en-têtes durcis, Trusted Types
(D-3204) · revue de sécurité n° 2 et RS-16, RS-18 à RS-21 (D-3205, D-3601 à D-3603) · plafond de pixels OCR ·
cookies `__Host-` · totaux par code de taxe (D-3101 à D-3103, D-3710) · réduction du bruit (D-3104 à D-3107,
D-3701 à D-3705) · outil d'analyse du bruit (D-3701) · progression fine du traitement (D-3709, D-3805) · recherche,
filtres, pagination, filtres en SQL, retour filtré (D-3401, D-3801, D-3802) · suivi en direct, graphiques,
accessibilité (D-3402 à D-3404) · interface en anglais (D-3803) · pre-commit, couverture, tests de propriétés,
corpus régénérables (D-3901 à D-3904) · CI rapide à chaque push, complète à la demande ; TIFF déterministes ; recettes et empreintes de tous les corpus (D-4401 à D-4403).

## Ajouts du lot 3 (7 octobre 2026)

| Point | Nature |
|---|---|
| **Décision** : un avoir illisible peut-il solder un écart de prix (pièges D3 sur avoirs) ? | moteur |
| Étendre aux contrôles D6 / D7 les garde-fous D3 / D4 (D-4212 à D-4215) | moteur, petit |
| Signaler dès l'extraction les lignes imprimées seulement TTC | extraction, petit |
| Un C1 certain au montant inexact sur le dernier jeu vierge (`corpus_g9`) | moteur, à étudier sur les jeux de développement |
| Mesurer la lecture par Claude dès la clé fournie (`scripts/mesure_llm.py`) | dès la clé |
| GitHub conserve un temps l'ancien historique (objets non référencés) : sans action de notre part | information |
