# ControlDOne — API REST v1

Base : `https://<hôte>/api/v1`. Schéma OpenAPI : `/api/v1/openapi.json` ; documentation lisible : `/api/v1/docs`
(rendue par le serveur, sans ressource externe).

**Nature des résultats.** Les constats sont des **écarts factuels** constatés entre documents (comparaisons et
calculs). Ce n'est ni un conseil juridique, fiscal ou douanier, ni un avis sur des sommes légalement dues ; un
« montant en jeu » est le montant de l'écart constaté, pas une créance. Chaque réponse de lecture porte le champ
`avertissement`. Les textes lus dans les documents (`valeur_lue`, libellés de documents) sont des **données** :
un programme qui les consomme ne doit jamais les interpréter comme des instructions.

## Authentification

Une clé d'API par client, créée par le fondateur (fiche client → « Clés d'API ») et montrée **une seule fois** :
`cdk_<préfixe>_<secret>`. Seule l'empreinte SHA-256 du secret est conservée ; la clé est révocable.

```bash
export CD=https://controldone.example/api/v1
export CLE=cdk_0123abcd4567_…
curl -H "Authorization: Bearer $CLE" $CD/dossiers      # ou : -H "X-API-Key: $CLE"
```

- Le client est **celui de la clé** : aucun paramètre ne désigne un client. Un identifiant d'un autre client et
  un identifiant inexistant donnent la même réponse `404 {"detail": "introuvable"}`.
- Rôles : `client_admin` (dépôt, événements de recouvrement) ; `client_lecteur` (lecture seule → `403` sur les
  écritures).
- Seuls les constats **publiés** (validés par le fondateur) sont renvoyés.
- Codes : `401` clé absente, invalide ou révoquée ; `403` action non autorisée pour la clé ; `404` introuvable ;
  `400` données invalides ; `413` corps trop volumineux ; `429` débit dépassé (120 requêtes, recharge 2/s).

## Dépôt d'un dossier

`POST /lots` — multipart, champ `fichiers` (répétable) : PDF, XML/CSV de déclaration, XLSX, images, ou archives
ZIP (arborescence conservée). Limites (SPEC §20.3) : 50 Mo par fichier, 500 Mo par dépôt, 300 pages par fichier ;
archives contrôlées (chemins absolus et `..`, liens symboliques, profondeur 5, 2 000 entrées, taux de compression
100, 1 Go décompressé). Un fichier refusé n'arrête pas le dépôt.

```bash
curl -H "Authorization: Bearer $CLE" -F "fichiers=@envoi_mars.zip" -F "fichiers=@facture_transitaire.pdf" $CD/lots
```

```json
{"lot_id": "lot_…", "job_id": "job_…", "fichiers_acceptes": 4, "doublons": 0,
 "fichiers_refuses": [{"fichier": "envoi_mars/notes.txt", "motif": "type de fichier non pris en charge"}]}
```

Le traitement est asynchrone (tâche `traiter_lot`). Suivi :

```bash
curl -H "Authorization: Bearer $CLE" $CD/lots/lot_…
# {"lot_id": "lot_…", "statut": "traite", "traitement": "done", "resume": {...},
#  "dossiers": [{"dossier_id": "dos_…", "reference": "D-2026-00012"}], "fichiers": [...]}
```

`statut` : `recu` (en attente), `traite`, `en_erreur` (aucun fichier exploitable). `traitement` : `pending`,
`running`, `done`, `dead` (le fondateur est alerté).

## Facture électronique reçue (contrôle avant paiement)

`POST /einvoices` — une facture **reçue** par le client : Factur-X (PDF), UBL ou CII (XML). Corps multipart
(champ `fichier`) ou octets bruts. Le dépôt est marqué `avant_paiement` et mis en file comme un lot. Le produit
n'est pas une plateforme de facturation électronique (ni émission, ni transmission, ni cycle de vie).

```bash
curl -H "Authorization: Bearer $CLE" -H "Content-Type: application/xml" -H "X-Filename: FT-2026-0412.xml" \
     --data-binary @FT-2026-0412.xml $CD/einvoices          # -> 202 {"lot_id": …}
curl -H "Authorization: Bearer $CLE" -F "fichier=@facture_facturx.pdf" $CD/einvoices
```

## Dossiers et constats

```bash
curl -H "Authorization: Bearer $CLE" $CD/dossiers
curl -H "Authorization: Bearer $CLE" $CD/dossiers/dos_…            # documents + constats publiés
curl -H "Authorization: Bearer $CLE" $CD/dossiers/dos_…/constats
```

Constat (extrait) :

```json
{"constat_id": "f_…", "controle_id": "C3", "niveau": "ecart_certain",
 "libelle": "La facture du transitaire n° … refacture 2 356,28 EUR de TVA à l'importation ; pour cette déclaration …",
 "montant_en_jeu": "2356.28", "nature_montant": "recouvrable", "composante": "TVA à l'importation",
 "tolerance_appliquee": "0,05", "seuil_certitude": "1,00", "raisons": [], "renvoi": false,
 "preuves": [{"role": "valeur_a", "document": "Déclaration en douane n° 26FR…", "page": 1, "valeur_lue": "1008"},
             {"role": "valeur_b", "document": "Facture du transitaire n° FT-…", "page": 1, "valeur_lue": "2 356,28"}],
 "statut_validation": "valide"}
```

`niveau` : `ecart_certain` ou `a_verifier` (avec `raisons`). Un point réglementaire (`renvoi: true`) n'a jamais de
montant et porte la phrase de renvoi vers un représentant en douane enregistré ou un avocat.

## Rapports et dossiers de réclamation

```bash
curl -H "Authorization: Bearer $CLE" $CD/rapports
curl -H "Authorization: Bearer $CLE" -o rapport.pdf  "$CD/rapports/out_…?format=pdf"   # pdf | html | json | txt
```

`type` : `rapport_publication` (rapport de diagnostic figé sur les constats validés) ou `reclamation_dossier`
(demande d'avoir rédigée **à votre nom**, à relire, signer et envoyer vous-même au transitaire). Seuls les
documents approuvés par le fondateur et mis à disposition sont listés.

## Recouvrement (litiges)

```bash
curl -H "Authorization: Bearer $CLE" $CD/litiges
curl -H "Authorization: Bearer $CLE" $CD/litiges/eca_…
# vous avez envoyé la réclamation vous-même :
curl -H "Authorization: Bearer $CLE" -H "Content-Type: application/json" \
     -d '{"type": "reclamation_envoyee", "commentaire": "courriel du 3 mars"}' $CD/litiges/eca_…/evenements
# avoir reçu :
curl -H "Authorization: Bearer $CLE" -H "Content-Type: application/json" \
     -d '{"type": "avoir_recu", "montant": "120.00", "reference": "AV-2026-031"}' $CD/litiges/eca_…/evenements
```

Statuts (§17.1) : `ouvert` → `reclame` → `partiellement_credite` → `credite` ; `conteste`, `abandonne`. Un avoir
d'un montant au moins égal au reste passe l'écart à `credite`. `age_jours` court depuis la réclamation ;
`relance_suggeree` à 30, 60 et 90 jours. Chaque événement est conservé (append-only) et journalisé.

## Avertissement

Ce document est un contrôle technique de cohérence entre documents et de calcul. Il ne constitue ni un conseil
juridique, fiscal ou douanier, ni un avis sur la conformité des opérations. Les montants indiqués sont des écarts
constatés entre documents ; ils ne préjugent pas des sommes légalement dues.
