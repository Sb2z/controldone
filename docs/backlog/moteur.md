# Bloc moteur : constats en marge (totaux par code, bruit « à vérifier »)

Mesures sur les seuls jeux de développement (`bench/out/*_dev_blocA`), sauf mention.

- **Totaux par code de taxe portés par le modèle.** Constat : D-2903 lisait les totaux par code sans les porter ;
  B2 ne voyait pas un total de code faux (8 erreurs attendues certaines sur le dev des trois jeux). Impact : 7
  deviennent certaines, 1 « à vérifier ». Proposition : `ChampsDeclaration.totaux_par_code`, B2 `code`, identités
  (D-3101 à D-3103). **Fait.**

- **Bruit : constats en double d'un document partagé entre dossiers.** Constat : 86 constats E/F répétés à
  l'identique dans les dossiers d'un même lot (avoir ou relevé rattaché à plusieurs envois). Impact : bruit, et le
  client voit le même sujet plusieurs fois. Proposition : un dossier porteur (D-3105). **Fait.**

- **Bruit : C7 sur un MRN mal lu.** Constat : 30 C7 non appariés citaient un MRN à 1–4 caractères de celui de la
  déclaration du dossier. Proposition : `mrn_designe` (D-3104). **Fait.**

- **Bruit : A10 masse nette, B4 somme des masses brutes.** Constat : A10 `nette` répétait B4 `nette_brute` (7 cas) ;
  B4 `somme_brute` reposait sur des masses OCR sous le seuil (14 cas, aucun réel). Proposition : D-3106, D-3107.
  **Fait.**

- **Bruit : P4 « rattachement faible » (62 non appariés, 0 erreur réelle, 8 pièges tolérés).** Constat : le signal
  « même dossier source » seul domine (33 cas) ; le contrôle est utile sur les pièges « facture d'un autre envoi
  rangée ici ». Impact : 0,10 constat par dossier. Proposition : relève du regroupement (`regroupement.py`, hors
  périmètre de ce bloc) : renforcer le lien quand un MRN, un numéro de facture ou une référence de transport du
  document se retrouve dans le dossier, avant de conclure « faible ». **Fait** (D-3702, lot 2 : P4 non apparié
  62 -> 28, dont 8 vraies factures d'un autre envoi du corpus d'origine, que la vérité n'attend pas de P4 ; les
  8 pièges « facture d'un autre envoi » restent signalés).

- **Bruit : A13 codes marchandise à sens unique (65 non appariés, 1 réel).** Constat : les vrais écarts A13
  (code SH6 différent) apparaissent des deux côtés (code de facture sans équivalent **et** code déclaré sans
  équivalent) ; les constats à sens unique (un seul côté) sont presque tous du bruit (lignes sans code lu, code
  mal lu). Impact : ~0,1 par dossier. Proposition : à sens unique, exiger que toutes les lignes de la facture portent
  un code lu ≥ 0,90 et que les nombres de lignes / d'articles concordent, sinon `non_verifiable`. Coût mesuré :
  1 vrai constat du dev perdu (GX0005) ; à arbitrer. **À faire.**

- **Bruit : D1 total HT / total des débours d'une facture scannée (≈ 23 non appariés).** Constat : total imprimé
  supérieur à la somme lue, lecture sous le seuil : des lignes non lues expliquent l'écart. Le seul « vrai » est un
  appariement au montant faux (BX0168). Proposition : comme D-2307, `non_verifiable` quand l'écart est positif et
  que la complétude des lignes n'est prouvée par aucune autre identité. **Fait** (D-3703 : D1 `total_ht` /
  `total_debours` non appariés 23 -> 0 ; BX0168, apparié à un montant faux, devient `non_verifiable`).

- **Bruit : C4 / C5 répétés par déclaration sur un relevé réparti au prorata (GZ0030 ×3, GX0120 ×5).** Constat :
  la TVA refacturée de toute la facture est comparée à chaque déclaration (`attribution_non_univoque`). Proposition :
  un constat par facture quand l'attribution n'est pas univoque. **Fait** (D-3704, C1 à C5).

- **B1 : base lue tronquée sur scan, montant confirmé.** Constat : GZ0154 (« 30,65 » pour 30 651,38), GX0054 ;
  la confusion « séparateur » (× 1 000) ne ramène pas l'écart dans la tolérance car les décimales sont perdues.
  Proposition : pour un facteur lu sous le seuil, accepter la variante puissance de dix à 0,05 % près (comme
  D-2803 pour A4/A5). **Fait** (D-3705 : puissance de dix à une unité du dernier chiffre lu près, base lue
  sous le seuil -> `non_verifiable`).

- **Totaux par code non lus sur certaines mises en page.** Constat : `corpus` L1/L3 dégradés et M2/M7/M8 scannés
  (`totaux_par_code` absents : 205 sur 783 au corpus d'origine, 82/467 g2, 58/370 g4) ; L2 imprime « Total autres
  taxes » sans code (A30). Proposition : rattacher un total sans code au seul code de sa catégorie quand il est
  unique. **Fait en partie** (D-3706). Constat complémentaire : sur L1/L3 dégradés, ce sont surtout les **lignes
  de taxation** qui ne sont pas lues (tableau illisible) ; le récapitulatif par code l'est souvent. Totaux par
  code absents 205 -> 133 (corpus d'origine), 58 -> 34 (g4), 82 -> 46 (g2). Reste : L4 (aucun total lu,
  mise en page sans récapitulatif lisible) et les lignes de taxation de L1/L3 d2–d3 (OCR).

- **`docs/DECISIONS.md` : bloc dupliqué.** Constat : la fin de la section D-2908 (« Les gains `corpus_g4` viennent
  de l'extraction… ») et l'en-tête « # Interface / D-3001 » apparaissent deux fois (lignes ~3459–3475). Impact :
  lecture. Proposition : supprimer la copie (fichier partagé avec les autres blocs : à faire par l'orchestrateur).
  **Fait** (vérifié par l'orchestrateur : plus de doublon dans `docs/DECISIONS.md`).

- **Banc : outil d'analyse du bruit.** Constat : la ventilation du bruit par contrôle et raison (classe, motif,
  piège) a demandé des scripts ad hoc joignant `metrics.json` et `findings.json`. Proposition : une option
  `--bruit` de `bench.score` (tableau contrôle × raisons × classe) et la détection des constats en double par lot.
  **Fait** : `scripts/analyse_bruit.py` (D-3701).

## Lot 2 (bruit sur jeux neufs, progression du pipeline) — 6 octobre 2026

- **Étapes fines du pipeline pour le suivi en direct.** `OptionsPipeline.progression(etape, fait, total)` ; étapes
  `pages`, `classement`, `extraction`, `regroupement`, `controles` (`pipeline.ETAPES_PROGRESSION`). Le handler
  `traiter_lot` les relaie à `JobContext.etape` sous la forme `"<etape> <fait>/<total>"` (`regroupement` sans
  compteur), une écriture par changement d'étape, sinon au plus toutes les 2 s (`jobs.handlers.relais_progression`,
  y compris depuis le processus fils de `executer_avec_delai`). Affichage : bloc interface (`web/suivi.py`). (D-3709)
  **Fait.**

- **Bruit restant non apparié (dev, trois jeux, après le lot 2) : piste suivante.** Mesuré par
  `scripts/analyse_bruit.py` : A13 (72, décision du fondateur), C5 (41, dont pièges « TVA autoliquidée non
  refacturée » et « écart d'arrondi de 0,03 EUR » : la tolérance de C5 sur un relevé et le retrait de la TVA
  autoliquidée quand C3 ne se déclenche pas sont à revoir), P1 « document manquant » (35, dont 7 en double dans un
  même lot), A2 (33), B2 total (33, `structure_non_validee` / lecture), B1 (27). **À faire.**

- **P4 restant (20 non appariés hors vraies factures d'un autre envoi).** Grappes de documents faibles qui se
  confirment entre eux (déclaration, facture du transitaire et avoir citant le même MRN) sans lien solide à la
  facture commerciale ; facture commerciale au numéro illisible ; déclaration sans référence lue. Proposition :
  traiter la grappe comme un tout quand la facture commerciale est la seule autre pièce du dossier. **À faire.**

- **Libellé du signal `reference_proche`** : ajouté à `rapport/vue.py` (`LIBELLES_SIGNAL`) et à la famille P ;
  l'interface (`services/lecture.py`) le reprend par `LIBELLES_SIGNAL`. Traduction anglaise éventuelle : bloc
  interface. **À vérifier par le bloc interface.**

