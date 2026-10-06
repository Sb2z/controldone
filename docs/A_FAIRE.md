# ControlDOne — ce qui reste à faire

Ce fichier consolide les constats notés en cours de route dans `docs/backlog/` : un fichier par bloc, avec le détail
de chaque point (fichiers, mesures). Il est mis à jour le 6 octobre 2026, à la fin du lot moteur, sécurité,
sauvegardes et interface. Les points sont classés par priorité. **Décision** signale ce qui demande l'accord ou
l'action du fondateur ; tout le reste peut être traité sans lui.

## 1. Décisions du fondateur

| Point | Pourquoi | Source |
|---|---|---|
| Activer l'extraction par modèle de langage (clé d'API) | réponse prévue aux mises en page vraiment inconnues | orchestrateur |
| Mesurer sur un premier dossier réel anonymisé, avec l'accord du client | seule mesure qui vaut pour le vrai monde | orchestrateur |
| Lancer la CI à chaque push / PR | consomme les minutes GitHub du fondateur | orchestrateur |
| Nettoyer l'historique Git des corpus (609 Mo) | réécriture irréversible de l'historique | orchestrateur |
| HSTS `preload` | engagement difficile à retirer pour le domaine | sécurité |
| A13 (codes marchandise à sens unique) : 65 constats « à vérifier » de bruit pour 1 vrai | les réduire ferait perdre le vrai cas (GX0005) | moteur |
| Hébergement, domaine, paiement réel, déploiement | actions extérieures | — |

## 2. Fiabilité et sécurité de la production

| Point | Bloc | Effort |
|---|---|---|
| Sauvegarde automatique pour PostgreSQL (aujourd'hui seulement SQLite) | sauvegardes | moyen |
| Alertes poussées (courriel ou ping) et non seulement visibles dans l'interface | sauvegardes | moyen |
| Tester sur PostgreSQL la limitation de débit et les révocations de session | sécurité | moyen |
| Mécanisme de migration de schéma (index, nouvelles colonnes sur une base existante) | interface | moyen |
| Plafond de pixels pour le rendu OCR des PDF | sécurité | petit |
| Empreintes dans `requirements.lock` ; paquets installés hors du fichier figé | sécurité | petit |
| Audit des paquets de l'image Docker (Debian, Tesseract) | sécurité | petit |
| Taille du corps de `/csp-rapport` bornée aussi côté Caddy | sécurité | petit |
| Cookies `cd_2fa` / `cd_flash` avec préfixe `__Host-` | sécurité | petit |
| Révocations en mémoire bornées | sécurité | petit |
| Points restants de la première revue (RS-16, RS-18 à RS-21) | sécurité | petit à moyen |
| Traces d'envoi en clair sur le disque (`outbox_envoyee`) | sauvegardes / sécurité | moyen |
| Purge lancée à la main pendant une sauvegarde : verrou | sauvegardes | petit |
| RPO de 24 h : deux sauvegardes par jour, ou journal de transactions | sauvegardes | moyen |
| Exercice mensuel sur une vraie archive de production ; test de la copie séquestrée de la clé | sauvegardes | procédure |
| Contrôle Trusted Types / CSP dans un navigateur en CI | sécurité | petit |

## 3. Moteur

| Point | Constat | Effort |
|---|---|---|
| Bruit P4 « rattachement faible » | 62 constats sans erreur réelle : à traiter au regroupement | moyen |
| D1 sur scans (totaux HT / débours) | environ 23 constats de bruit ; un vrai cas apparié avec un montant faux | moyen |
| C4 / C5 répétés par déclaration sur un relevé réparti au prorata | doublons | petit |
| B1 : base lue tronquée sur scan, confirmée à tort par les identités | 2 cas | petit |
| Totaux par code non lus sur certaines mises en page dégradées | rappel B2 par code | moyen |
| Progression fine du pipeline (étapes réelles pour le suivi en direct) | interface | petit |
| Outil d'analyse du bruit (ventilation par contrôle et raison) intégré au banc | outillage | petit |

## 4. Interface

| Point | Effort |
|---|---|
| Filtres calculés en SQL plutôt qu'en Python pour les gros clients | moyen |
| Retour après action dans une liste filtrée : garder les filtres | petit |
| Colonne « Créée » des tâches qui affiche le prochain essai | petit |
| Libellés des nouvelles alertes de sauvegarde dans l'écran Alertes | petit |
| Liste des sessions actives et « fermer mes autres sessions » | moyen |
| Interface en anglais | moyen |

## 5. Dépôt et outillage

| Point | Effort |
|---|---|
| Ne plus versionner les nouveaux corpus : régénération par commande et empreinte (fait pour `corpus_g6`) | petit |
| Couverture de tests mesurée ; tests de propriétés sur les montants | moyen |
| Vérifications avant enregistrement (style, secrets, fichiers lourds) | petit |
