# Prospection : mode d'emploi du module « Marketing »

Module réservé au fondateur : menu **Marketing** (`/admin/prospection`). Aucun client ne le voit. Décisions :
D-5001 à D-5012 (`docs/DECISIONS.md`) ; registre RGPD : § 2.1 bis (`docs/RGPD_registre.md`).

Trois règles ne changent jamais :

1. **Rien ne part sans vous.** Chaque courriel est un brouillon de la file de validation (`/admin/validation`).
2. **Rien d'inventé.** Une entreprise réelle, une page source, une date de collecte ; une adresse publiée par
   l'entreprise (ou que l'on vous a donnée), toujours avec la page où elle figure. Un fait manquant bloque.
3. **Les deux groupes exclus** (liste dans `config/prospection.yaml`) sont refusés partout, sans exception.

## 1. Avant le premier envoi (une fois)

- Identité de l'expéditeur, obligatoire dans chaque message : `CONTROLDONE_PROSPECTION_EXPEDITEUR_NOM` (ou
  `expediteur.nom` dans `config/prospection.yaml`), SIREN et adresse du vendeur (`CONTROLDONE_VENDEUR_SIREN`,
  `…_ADRESSE_LIGNE`, `…_CODE_POSTAL`, `…_VILLE`, ou `config/offres.yaml`). Tant qu'un champ manque, l'aperçu le
  dit et la préparation est refusée.
- URL publique du service (`CONTROLDONE_URL_PUBLIQUE` ou `CONTROLDONE_DOMAIN`) : sans elle, le pied propose
  seulement « répondez STOP », sans lien de désinscription.
- Domaine d'envoi : SPF, DKIM, DMARC (page **Délivrabilité**).
- Envoi par l'application (facultatif) : `CONTROLDONE_PROSPECTION_SMTP_HOTE`, `…_SMTP_PORT`, `…_SMTP_SECURITE`
  (`starttls` ou `ssl`), `…_SMTP_UTILISATEUR`, `…_SMTP_MOT_DE_PASSE`, `CONTROLDONE_PROSPECTION_COURRIEL_DE`, en
  production seulement. Sans cela, vous envoyez vous-même depuis votre messagerie et vous le déclarez (§ 5).

## 2. Constituer le fichier

- **Importer** : le fichier `commercial/prospects.csv` (ou un fichier au même format). L'aperçu montre, ligne par
  ligne, ce qui sera importé, les doublons (même SIREN ou même nom), les exclusions et les lignes sans source ;
  rien n'est écrit avant « Importer N prospect(s) ». En ligne de commande :
  `controldone prospection importer fichier.csv --essai`, puis sans `--essai`.
- **Rechercher** : la base publique « Recherche d'entreprises » par NAF, tranche d'effectif, département ou région.
  La recherche part quand vous cliquez ; les résultats sont des candidats. « Ajouter » relit l'entreprise dans la
  base publique et la crée « à qualifier ».
- **Saisir** : formulaire en bas de la page Prospects.

## 3. Qualifier

Sur la fiche : relevez sur le site de l'entreprise une **phrase exacte** qui montre l'import hors UE (entre « »)
et sa page ; une adresse publiée (contact@, info@…) avec la page où elle figure ; le signal « service douane
interne ». Le score (sur 100) se recalcule et la fiche explique chaque point. Passez ensuite le statut à
« qualifié ». Suisse et Belgique : une adresse nominative exige une base légale enregistrée sur la fiche.

## 4. Préparer et valider

« Préparer la séquence » met le premier courriel en brouillon. Ouvrez la **file de validation** : approuvez,
corrigez puis approuvez, ou refusez (un refus arrête la séquence). Les étapes suivantes (J+4, J+10, J+20 par
défaut) sont préparées chaque jour par l'agent `prospection`, ou tout de suite par « Préparer les étapes échues »
(page Courriels) ; elles arrivent elles aussi en brouillon. Les modèles se modifient dans **Séquences** (texte
brut, un lien au plus, variables de faits enregistrés seulement).

## 5. Envoyer

Page **Courriels** : pour un courriel approuvé, « Envoyer » (messagerie configurée) ou, sans messagerie, copiez le
texte approuvé dans votre messagerie, envoyez-le, puis cliquez « Je l'ai envoyé moi-même ». Juste avant, l'outil
revérifie l'opposition, l'exclusion, le pays, le pied obligatoire et le plafond du jour (15 envois par défaut).

## 6. Suivre les réponses

- Réponse reçue : bouton « A répondu » sur la fiche (texte collé facultatif) ; la séquence s'arrête.
- Rendez-vous : bouton « Rendez-vous ». Puis déplacez le prospect dans le **Pipeline** (essai, client, perdu).
- « STOP », plainte : bouton « STOP reçu » sur le contact ; rebond définitif : bouton « Rebond ». L'adresse entre
  dans la liste d'opposition et n'est plus jamais utilisée.
- Lien de désinscription cliqué par le destinataire : enregistré automatiquement (page **Opposition**).

La **vue d'ensemble** donne le pipeline, la conversion par étape, les courriels à valider, les réponses à traiter
et les segments qui répondent le mieux, à partir des seuls événements réels (aucun suivi d'ouverture ni de clic).

## 7. Conserver, purger

Un prospect sans contact émanant de lui depuis 3 ans est signalé « à purger » (page Opposition, vue d'ensemble).
« Purger » le supprime avec son historique ; la liste d'opposition est conservée. En ligne de commande :
`controldone prospection purger` (compte), puis `--oui`.

## 8. Démonstration

`controldone init-demo` ajoute six sociétés fictives (« … DÉMO FICTIF »), sans courriel préparé.
