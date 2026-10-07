# ControlDOne — ce qui reste à faire

Ce fichier consolide les constats notés en cours de route dans `docs/backlog/` : un fichier par bloc, avec le détail
de chaque point (fichiers, mesures). Il est mis à jour le 7 octobre 2026, à la fin du lot 4. Les points sont classés par priorité. **Décision** signale ce qui demande l'accord ou
l'action du fondateur ; tout le reste peut être traité sans lui. Ce qui a été fait est listé en fin de fichier.

## 1. Décisions et actions du fondateur

Les neuf arbitrages d'octobre sont tranchés (D-4000). Reste ce qui ne peut venir que du fondateur
(détail : `docs/RAPPELS_FONDATEUR.md`) :

| Point | Pourquoi | Source |
|---|---|---|
| Fournir la clé d'API Anthropic, puis `controldone llm verifier` et `scripts/mesure_llm.py` (dépense confirmée) | la lecture par Claude est prête mais inactive (D-4001 à D-4008) | orchestrateur |
| Premier dossier réel : accord écrit du client, contrat RGPD, anonymisation, entreprise non exclue | seule mesure qui vaut pour le vrai monde (D-4000 point 2) | orchestrateur |
| **Décision** : un avoir illisible peut-il solder un écart de prix (pièges D3 sur avoirs) ? | règle métier, pas technique | moteur |
| Adresse ntfy secrète et sonde de sauvegarde (`CONTROLDONE_NOTIF_WEBHOOK_URL`, `BACKUP_PING_URL`) | alertes sur téléphone (D-4000 point 8) | production |
| Activer l'exercice mensuel et contrôler la copie papier de la clé (§ 2) | procédure sur le serveur réel | production |
| Hébergement, domaine, Stripe en réel, mise en ligne (`docs/MISE_EN_LIGNE.md`) | actions extérieures et dépenses | — |
| Plus tard : HSTS `preload` (non pour l'instant), rapports en anglais (non pour l'instant), tests PostgreSQL dans la CI (minutes GitHub) | décisions 5B, 7B, 3A | — |

## 2. Fiabilité et sécurité de la production

Reste à faire (détail : `docs/backlog/production.md`, `sauvegardes.md`, `securite.md`) :

| Point | Source | Effort |
|---|---|---|
| **Décision** : activer l'exercice mensuel planifié (`SCHED_EXERCICE_MENSUEL=1`, après avoir vérifié l'espace libre de `/backups`) ; contrôler la copie papier de la clé et noter son empreinte sur l'enveloppe (`docs/EXPLOITATION.md` § 3.4, § 3.5) | production | procédure |
| 77 vulnérabilités élevées ou critiques sans correctif Debian dans l'image (libxml2, libtesseract, libtiff, curl…) : suivi mensuel outillé (`make audit-image` puis `make suivi-cve`), reconstruire dès qu'un correctif paraît | sécurité | suivi |
| Tests PostgreSQL dans la CI (`make test-pg-securite`, `make test-pg-plateforme`, `make restauration-test-pg`) ; marquer `postgresql` les anciens tests PostgreSQL de `tests/platform` | production, outillage | petit (après la décision CI du § 1) |
| Mise en service d'une restauration encore manuelle (`controldone sauvegarde mettre-en-service`, déplacement atomique sous verrou) | sauvegardes | moyen |
| Battement quotidien du scheduler (rien n'est notifié s'il est arrêté ; seule la sonde « homme mort » le voit) | production | petit |
| Répétition générale d'une montée de version réelle (`docker compose up` avec le service `migrer`, Caddy, domaine) | production | procédure |
| Exercice trimestriel sur une machine de test à partir de la copie hors site téléchargée | sauvegardes | procédure |
| Sauvegarde : compression gzip niveau 9 d'un coffre déjà chiffré (création 4 fois plus lente que nécessaire) | sauvegardes | petit |
| Contrôle au démarrage de la version de `pg_dump` contre celle du serveur ; rôles PostgreSQL (`pg_dumpall --globals-only`) à documenter pour une restauration sur un serveur neuf | production | petit |
| Exercice mensuel : contrôle de l'espace libre avant de restaurer ; libellé d'alerte dédié | production, interface | petit |
| ODS : plafond propre de `content.xml` ; vignettes groupées par appel isolé (à mesurer) | sécurité | petit |

Fait (lots P3 et P4) : client PostgreSQL 16 et `pg8000` dans l'image, sauvegarde et restauration PostgreSQL
vérifiées dans le conteneur (D-4101) · service ponctuel `migrer`, plus de redémarrages en boucle pendant une
mise à jour (D-4102) · effacement RGPD d'un client sous le verrou de maintenance (D-4103) · notifications ntfy,
historique en ligne de commande et page `/admin/notifications` (D-4104, D-4304) · deux sauvegardes par jour,
RPO 12 h (D-4105) · traces d'envoi chiffrées au repos (D-4106) · D-3601 à D-3605 reportés dans
`docs/SECURITY.md` § 4.1 · verrou de maintenance entre hôtes, verrou consultatif PostgreSQL (D-4701) · exercice
mensuel sur la dernière vraie archive, compte rendu daté sans donnée client, planification désactivée par défaut
(D-4702) · empreinte publique de la clé et procédure de contrôle de la copie séquestrée (D-4703) · suivi
mensuel des vulnérabilités de l'image, sans réseau (D-4704).

## 3. Moteur

| Point | Constat | Effort |
|---|---|---|
| Un faux certain C1 (montant inexact) sur `corpus_g9`, non expliqué par le correctif D-4603 | à reproduire sur un nouveau jeu de développement, sans ouvrir `corpus_g9` | moyen |
| Rappel des erreurs attendues « certain » : 61 % sur le dernier jeu vierge | A5 (taux lu entre 0,86 et 0,89, sans seconde lecture), B1 et F3 sous 0,70, A6 taux imprimé illisible | moyen |
| Rappel global stable autour de 73 à 88 % : 39 erreurs manquées sur 188 au dernier jeu vierge | analyser les FN par contrôle sur les jeux de développement | moyen |
| Bruit 0,6 à 1,35 par dossier (sous l'alerte de 1,5 partout) ; `corpus_g5` et `corpus_g6` les plus bruités | P4, C5 sur relevés, TVA autoliquidée | moyen |
| Totaux par code non lus sur certaines mises en page dégradées | rappel B2 par code | moyen |
| Lignes de régularisation lues sans signe moins : aujourd'hui le montant C passe « non établi » ; les lire signées | extraction | petit |

Fait (lots M3 et M4) : A13 regroupé (D-4201) · garde-fous D3/D4 (D-4212 à D-4215) étendus à D6/D7 (D-4601) ·
lignes imprimées seulement TTC signalées à l'extraction (D-4602) · montant C1–C5 « non établi » quand un avoir,
une version de déclaration ou un total par code le rend incertain ; avoir d'un autre envoi plus déduit dans chaque
dossier (D-4603) · rappel certain par seconde lecture indépendante F3, A6, B1 (D-4604 à D-4606).

## 4. Interface

Rien d'ouvert de prioritaire (détail et petites pistes : `docs/backlog/interface.md`).

## 5. Dépôt et outillage

| Point | Effort |
|---|---|
| Tests de `storage/verrou.py` (70 %), `services/exercice_restauration.py`, `storage/sauvegarde.py`, `services/exercice_mensuel.py` (≈ 80 %), puis relever les seuils de couverture | petit |
| Codes d'erreur portés par l'exception et champ `code` dans les erreurs de l'API REST (aujourd'hui message français reconnu par motif) | petit |

Fait : historique Git nettoyé, plus aucun corpus versionné (D-4404) · `ruff format` appliqué à tout le dépôt ·
couverture 89,7 %, seuils 88 % global, `controls` 89 %, `auth` 97 % (D-4901 à D-4903) · messages des services et
documentation de l'API en anglais, détection des textes restés en français (D-4801 à D-4803).

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

## Information

GitHub conserve un temps l'ancien historique (objets non référencés) : sans action de notre part.
