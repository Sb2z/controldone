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
  document se retrouve dans le dossier, avant de conclure « faible ». **À faire.**

- **Bruit : A13 codes marchandise à sens unique (65 non appariés, 1 réel).** Constat : les vrais écarts A13
  (code SH6 différent) apparaissent des deux côtés (code de facture sans équivalent **et** code déclaré sans
  équivalent) ; les constats à sens unique (un seul côté) sont presque tous du bruit (lignes sans code lu, code
  mal lu). Impact : ~0,1 par dossier. Proposition : à sens unique, exiger que toutes les lignes de la facture portent
  un code lu ≥ 0,90 et que les nombres de lignes / d'articles concordent, sinon `non_verifiable`. Coût mesuré :
  1 vrai constat du dev perdu (GX0005) ; à arbitrer. **À faire.**

- **Bruit : D1 total HT / total des débours d'une facture scannée (≈ 23 non appariés).** Constat : total imprimé
  supérieur à la somme lue, lecture sous le seuil : des lignes non lues expliquent l'écart. Le seul « vrai » est un
  appariement au montant faux (BX0168). Proposition : comme D-2307, `non_verifiable` quand l'écart est positif et
  que la complétude des lignes n'est prouvée par aucune autre identité. **À faire** (décision sur BX0168).

- **Bruit : C4 / C5 répétés par déclaration sur un relevé réparti au prorata (GZ0030 ×3, GX0120 ×5).** Constat :
  la TVA refacturée de toute la facture est comparée à chaque déclaration (`attribution_non_univoque`). Proposition :
  un constat par facture quand l'attribution n'est pas univoque. **À faire.**

- **B1 : base lue tronquée sur scan, montant confirmé.** Constat : GZ0154 (« 30,65 » pour 30 651,38), GX0054 ;
  la confusion « séparateur » (× 1 000) ne ramène pas l'écart dans la tolérance car les décimales sont perdues.
  Proposition : pour un facteur lu sous le seuil, accepter la variante puissance de dix à 0,05 % près (comme
  D-2803 pour A4/A5). **À faire.**

- **Totaux par code non lus sur certaines mises en page.** Constat : `corpus` L1/L3 dégradés et M2/M7/M8 scannés
  (`totaux_par_code` absents : 205 sur 783 au corpus d'origine, 82/467 g2, 58/370 g4) ; L2 imprime « Total autres
  taxes » sans code (A30). Proposition : rattacher un total sans code au seul code de sa catégorie quand il est
  unique. **À faire.**

- **`docs/DECISIONS.md` : bloc dupliqué.** Constat : la fin de la section D-2908 (« Les gains `corpus_g4` viennent
  de l'extraction… ») et l'en-tête « # Interface / D-3001 » apparaissent deux fois (lignes ~3459–3475). Impact :
  lecture. Proposition : supprimer la copie (fichier partagé avec les autres blocs : à faire par l'orchestrateur).
  **Fait** (vérifié par l'orchestrateur : plus de doublon dans `docs/DECISIONS.md`).

- **Banc : outil d'analyse du bruit.** Constat : la ventilation du bruit par contrôle et raison (classe, motif,
  piège) a demandé des scripts ad hoc joignant `metrics.json` et `findings.json`. Proposition : une option
  `--bruit` de `bench.score` (tableau contrôle × raisons × classe) et la détection des constats en double par lot.
  **À faire.**
