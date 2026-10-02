# Décisions structurantes

Chaque choix structurant est noté ici, avec sa raison et l'option écartée. En cas de doute, l'option la plus prudente a été retenue.

## D-001 — Réécriture en salle blanche, branche orpheline

- **Choix** : nouveau dépôt Git initialisé à vide (`git init`), poussé sur la branche `v2` du dépôt `controldone` (et en miroir sur la branche de travail de la session). Aucun historique commun avec l'ancien code.
- **Méthode** : des agents « lecteurs » ont lu les anciens dépôts et n'ont rapporté que le besoin (documents, champs, contrôles, cas limites), sans code, nom de fonction, nom de société, nom de transitaire ni donnée. Un agent distinct a rédigé `docs/SPEC.md` à partir de ces notes seulement, puis un agent auditeur a recherché toute contamination (noms, identifiants, données, phrases recopiées). Les agents qui écrivent le code reçoivent la consigne de ne jamais ouvrir les anciens dépôts.
- **Pourquoi** : article L. 113-9 du code de la propriété intellectuelle (logiciel créé dans le cadre d'un emploi). Le paramètre « code réutilisable tel quel » est vide.
- **Limite** : la salle blanche repose sur des consignes données aux agents, pas sur une séparation physique des machines. C'est noté dans le rapport du matin.

## D-002 — Python, FastAPI, rendu serveur

- **Choix** : Python 3.11, FastAPI, gabarits Jinja2 rendus côté serveur, CSS maison sans chaîne de construction JavaScript.
- **Pourquoi** : une seule langue à maintenir (le fondateur connaît Python), pas de `npm build`, pages lisibles sans JavaScript.
- **Écarté** : application monopage React (deux piles à maintenir, surface d'attaque plus grande).

## D-003 — SQLite par défaut, PostgreSQL possible

- **Choix** : SQLAlchemy 2 ; SQLite en mode WAL pour la démonstration et un premier client ; la même base de code tourne sur PostgreSQL (variable `CONTROLDONE_DATABASE_URL`).
- **Pourquoi** : zéro serveur à administrer au démarrage ; sauvegarde = copie de fichier chiffrée.
- **Cloisonnement** : il n'est pas confié à la base mais à une couche d'accès unique qui impose l'identifiant du client sur chaque requête, avec des tests qui tentent l'accès croisé (voir `docs/SECURITY.md`).

## D-004 — File de tâches en base, sans Redis

- **Choix** : table `jobs` avec clé d'idempotence unique, verrou par bail (lease), reprise avec attente exponentielle, statut mort après N essais.
- **Pourquoi** : un seul processus de plus à surveiller (le worker), pas de service tiers.

## D-005 — Licences des dépendances

- **Choix** : uniquement des licences permissives (MIT, BSD, Apache 2.0). PyMuPDF (AGPL) est écarté : son usage dans un service en ligne imposerait de publier le code. Rendu PDF des pages : `pypdfium2` ; texte : `pdfplumber` ; OCR : Tesseract (Apache 2.0, langue `fra`) ; PDF produits : ReportLab ; Factur-X : bibliothèque `factur-x` (BSD).

## D-006 — Le modèle lit, le code calcule

- **Choix** : l'extraction passe par une interface `Extracteur`. Trois implémentations : structurée (XML Factur-X/UBL/CII, XML et CSV de déclaration : aucune IA), déterministe (texte PDF + OCR + règles de mise en page), et modèle de langage (Anthropic, si une clé est fournie). Les contrôles et tous les montants sont calculés par du code testé, jamais par le modèle.
- **Si aucune clé** : l'extracteur déterministe sert pour tout le corpus. C'est le cas de cette nuit (aucune clé d'API dans l'environnement). La clé figure dans la liste de validations du rapport du matin.

## D-007 — Prudence de classement

- **Choix** : un écart n'est « certain » que si toutes les valeurs comparées ont été lues avec une confiance suffisante, sur des documents identifiés, avec page et valeur citées, et que l'écart dépasse la tolérance. Sinon : « à vérifier ». Tout sujet qui toucherait au bien-fondé d'un droit, d'une taxe, d'un classement, d'une origine ou d'une valeur en douane n'est jamais chiffré comme dû : il est renvoyé vers un représentant en douane enregistré ou un avocat.

## D-008 — Socle du moteur : paquet `controldone`, contrats publiés

- **Choix** : paquet Python `controldone` (disposition `src/`), modèle Pydantic v2 fidèle aux §5 et §6, noms de champs français identiques à la spécification. Les contrats entre équipes (ingestion, extraction, contrôles, assemblage) sont décrits dans `docs/ARCHITECTURE.md` avec les noms exacts des classes et fonctions.
- **Pourquoi** : cinq équipes travaillent en parallèle ; un contrat écrit et testé évite les divergences.

## D-009 — Identifiants

- **Choix** : `<préfixe>_<32 hex>` de type UUID v7 (triables), générés par `IdGenerator` (mode déterministe par graine pour le banc). Les résultats de contrôle et les constats ont un identifiant **stable** dérivé du contenu (`id_stable` : SHA-256 de dossier, version, contrôle, sous-contrôle, unité ; format UUID v8).
- **Pourquoi** : §6.2.12 exige qu'une exécution rejouée donne les mêmes résultats octet pour octet ; un identifiant aléatoire l'empêcherait. La stabilité permet aussi de retrouver la validation du fondateur après une relance.

## D-010 — Représentation des valeurs

- **Choix** : `ValeurSourcee.valeur` est toujours une chaîne (décimal en notation point, date ISO, code) ; lecture typée par `.decimal()`, `.entier()`, `.date_iso()`. Montants en valeur absolue, signe dans `signe_imprime` (§5.2). Chemins relatifs avec index de liste **0-based** (`lignes[2].montant_ht`) ; `ValeurSourcee.chemin` est préfixé du type de document. La quantité porte son unité normalisée dans `quantite.unite` (pas de champ `unite` séparé). Les classifications déduites (`nature` d'une ligne, `categorie`, `paiement_normalise`, `taux_nature` d'une taxe) sont des énumérations simples, non sourcées : leur provenance est celle de la valeur lue dont elles découlent.
- **Écarté** : flottants (interdits) ; `Decimal` dans le JSON (perte de la forme imprimée).

## D-011 — Profil de tolérances : compléments

- **Choix** : ajout au profil de valeurs citées dans la spécification hors du tableau §8.3 : `s_calcul_declaration = 1,00 EUR` (B1, B2, B3, G1 « > 1,00 EUR »), seuils de A6 (`2 %`, `10 %`, confiance devise `0,95`), fenêtre F (24 mois). Liste `devises_volatiles` par défaut : ARS, EGP, GHS, LBP, NGN, PKR, TRY, VES, ZWL (aucune liste n'est donnée par la spécification ; modifiable). Les pourcentages sont stockés en fractions (`0.001` = 0,1 %). Les seuils de certitude (`s_*`, `c_min_certain`, confiance devise A6) ne peuvent qu'augmenter (`ProfilTolerances.appliquer_surcharges` refuse une baisse). L'empreinte SHA-256 porte sur le contenu canonique (sans identifiant, horodatages ni numéro de version).

## D-012 — Raisons ajoutées à l'énumération de §8.5.3

- **Choix** : en plus des 17 raisons de §8.5.3 (inchangées, dans l'ordre), ajout de `doublon_composantes` et `montant_converti` (citées par §8.6 et A3), et de `ecart_en_faveur_client`, `sens_taux_derive`, `version_rectificative`, `avoir_impute`, `valeur_absente`, `aucune_grille_validee`, `facture_transitaire_absente`, `couvert_par_autre_controle`, `dossier_non_concerne`, `erreur_interne` (motifs de `non_verifiable` / `non_applicable` et raisons de doute rencontrées en appliquant §8.6, §8.7, §8.5.1 condition 7). Chaque raison a un libellé en clair (`RAISON_LIBELLES`), testé contre les formulations interdites. `doublon_composantes`, `montant_converti` et `couvert_par_autre_controle` sont **informatives** : elles peuvent accompagner un `ecart_certain` (ex. C5 dont le montant n'est pas additionné).

## D-013 — Lien du document graine

- **Choix** : chaque document d'un dossier a exactement un `LienDocument`. Le document graine (facture commerciale, §7.5 étape 2) ou le document orphelin qui forme son propre dossier porte `force = forte` et le signal ajouté `graine`.
- **Pourquoi** : la condition 5 de §8.5.1 s'applique à tous les documents comparés ; sans lien explicite pour la graine, aucun constat ne pourrait être certain.

## D-014 — Filtre des formulations interdites : insensibilité aux accents

- **Choix** : comparaison sur le texte en minuscules, sans accents, tirets ramenés à des espaces, avec variantes de pluriel et de féminin générées par mot (mots grammaticaux invariables). Conséquence assumée : « droit dû » bloque aussi « droit du » sans accent ; les gabarits évitent la tournure « droit du … ». Un constat dont le libellé ou la prochaine action contient une expression interdite reçoit `motif_blocage = formulation_interdite` (il part en file de validation, il n'est pas supprimé).

## D-015 — Base des tolérances en pourcentage

- **Choix** : une tolérance ou un seuil exprimé en pourcentage (`T_VALEUR`, `S_VALEUR`, `T_CONVERSION`, `S_CONVERSION`, `T_MASSE`, `T_QUANTITE`) s'applique à la **plus grande** des deux valeurs comparées en valeur absolue ; un seuil de certitude n'est jamais inférieur à la tolérance du même contrôle. « 1 unité de devise » vaut 1, quelle que soit la devise.
- **Pourquoi** : lecture la plus large, donc la plus prudente (P-7) ; la spécification ne précise pas la base.

## D-016 — Total reconstruit parmi les valeurs clés

- **Choix** : condition 4 de §8.5.1 — dès qu'une valeur clé est un total `reconstruit`, le constat est `a_verifier` (raison `total_reconstruit`), sans chercher à savoir si la reconstruction « pourrait » expliquer l'écart.
- **Pourquoi** : un total reconstruit est une borne basse (§5.3.1) ; déterminer qu'il n'explique pas l'écart demanderait de savoir quelles lignes manquent. Option la plus prudente.

## D-017 — Fusion de plusieurs extracteurs

- **Choix** : §7.3 appliqué champ par champ (`fusionner_valeurs`). Une `saisie_humaine` l'emporte toujours. En désaccord, la valeur de plus haute confiance est retenue (à égalité : structure > texte natif > llm > OCR) ; sur un champ clé sa confiance est plafonnée à 0,80 et la raison `extracteurs_en_desaccord` est mémorisée ; sur un champ non clé, la raison est mémorisée **sans** plafond (le classement la traite comme un doute).

## D-018 — Extracteur `llm` : paramètres et hypothèses

- **Modèle** : `CONTROLDONE_LLM_MODEL`, défaut `claude-opus-5-5`, appelé par `client.messages.parse(..., output_format=<schéma fermé>)` du SDK officiel `anthropic`. Repli côté serveur en cas de refus activé par défaut (`fallbacks: "default"`, désactivable par `CONTROLDONE_LLM_FALLBACKS=false`).
- **Coûts** : tarifs par million de jetons (USD) opus-5-5 4/20, sonnet-5-5 2/10, haiku-4-5 1/5 ; conversion USD -> EUR au taux `CONTROLDONE_USD_EUR`, **défaut 0,92 : hypothèse** à mettre à jour ; un modèle inconnu est compté au tarif le plus élevé. Le plafond est vérifié **avant** l'appel sur une estimation (texte/3 jetons + 1 600 jetons par page PDF + 2 000 jetons de sortie), puis le coût réel est enregistré.
- **Confiance** : une valeur `llm` ancrée reçoit 0,85 (paramètre `CONTROLDONE_LLM_CONFIANCE_ANCREE`), donc **sous** `C_MIN_CERTAIN` : une valeur lue seulement par le modèle ne fonde jamais seule un `ecart_certain` ; non ancrée : 0,50. La `zone` n'est pas calculée par l'extracteur `llm` (pas de géométrie) : à compléter par l'équipe extraction à partir des mots positionnés de la page si besoin.
- **Schéma fermé** : liste de `{champ, index, valeur_brute, page}` où `champ` est une énumération des feuilles du modèle ; aucune classification ni aucun statut n'est demandé au modèle.
- **Pas de clé** dans cet environnement : l'extracteur est désactivé et testé avec un faux client.

## D-019 — Test de confusion : précisions

- **Choix** : le test porte sur `valeur_brute` (à défaut `valeur`). Pour une comparaison numérique, seule la substitution lettre -> chiffre est utile (un chiffre remplacé par une lettre ne donne pas de nombre). La perte ou l'ajout d'un zéro final ne s'applique qu'aux valeurs sans partie décimale (codes, quantités entières). Si la valeur lue est une transposition adjacente de la valeur attendue, le test est négatif (vrai écart). Qualité de page inconnue : le test s'applique (prudence). Forme générale `confusion_test_fn(brut, accepte)` pour les opérandes (base, taux, ligne d'une somme).

## D-020 — Dossier non concerné (P5)

- **Choix** : P5 ne produit pas de constat ; « non concerné » est exprimé par un résultat `non_applicable`, raison `dossier_non_concerne`, `details.non_concerne = true`. Le moteur arrête alors l'exécution des contrôles suivants et le statut global est `non_concerne`.

## D-021 — Non-double-comptage (§8.6) dans le moteur

- **Choix** : les règles portant sur une même unité de comparaison sont appliquées par le moteur après exécution, d'après la clé `ResultatControle.unite` (convention `cle_unite(ft=…, dec=[…])` pour C1–C5 et G4, `cle_unite(fc=[…], dec=[…])` pour A3–A7) : C3 constaté -> C4 `non_applicable` ; C1, C2 et C3/C4 évaluables -> C5 sans montant (`doublon_composantes`, `montant_brut` conservé) ; A6 constaté -> A5 `non_applicable` ; G4 et G5 de même montant (à `S_DEBOURS` près) sur la même facture -> G5 sans montant. Les règles qui demandent un recalcul (C6/D4 « assiette corrigée », part TVA de C5, F3/C5 dans un même dossier) restent à la charge des contrôles, qui peuvent lire les résultats antérieurs (`ctx.anterieurs`).
- **Filets de sécurité** appliqués à tout résultat : contrôle non éligible jamais certain ; note de renvoi toujours `a_verifier`, sans montant, avec la phrase de renvoi ; montant `aucun` nul ; écart recouvrable négatif jamais certain.

## D-022 — Statut global (§18.2)

- **Choix** : pour le banc et la file de validation, tous les constats proposés comptent ; pour le rapport client (`valides_seulement=True`), un `ecart_certain` ne compte que validé, mais tout constat non rejeté empêche le statut `conforme`. Un `non_verifiable` sur un contrôle C, A4 ou A5 empêche `conforme`, sauf s'il vient d'un document manquant (déjà couvert par P1).

# Contrôles P et A

## D-101 — Couples de la famille A

- **Choix** : l'unité « couple » est formée par les composantes connexes des allocations facture -> déclaration (une allocation visant une version antérieure est reportée sur la dernière version du même préfixe MRN). Sans allocation : un seul couple (toutes les factures exploitables, toutes les dernières versions). Documents sans allocation : couple résiduel ; un côté seul rejoint l'unique composante s'il n'y en a qu'une, sinon le couple incomplet donne `non_verifiable` (`document_manquant`). Clé `cle_unite(fc=[…], dec=[…])` pour tous les contrôles A.
- **A4, allocation explicite** : en plus du couple, chaque allocation chiffrée (`montant_alloue`) d'une facture répartie sur plusieurs déclarations est comparée au montant déclaré de sa déclaration (`sous_controle = "allocation"`, unité `cle_unite(fc=[f], dec=[d])`).

## D-102 — Situation des devises (A3–A7)

- **Choix** : une seule lecture des devises par couple : `meme` (A4), `converti` (facture D ≠ EUR, déclaration EUR : A5, A6, A7), `differente` (A3 constate ; A4 à A7 `non_applicable`, raison `couvert_par_autre_controle`), `incertaine` (une devise illisible : A3 `non_verifiable` ; A4 compare sous deux hypothèses, même devise ou conversion au taux imprimé, et conclut `conforme` si l'une concorde, sinon `a_verifier` raison `devise_incertaine` sans montant ; A5–A7 `non_applicable` couverts par A4), `multiples` (factures ou déclarations du couple en devises différentes entre elles : A3 `a_verifier` `devise_incertaine`, A4–A7 `non_verifiable`).
- **A3 délégué** : en situation `converti`, A3 recalcule A5 (fonction partagée) : `conforme` avec `raison_code = montant_converti` si A5 est conforme, sinon `non_applicable` (`montant_converti`, couvert par A5/A6/A7). « Code ISO lu » = le code figure tel quel dans `valeur_brute` (un « $ » est un symbole ambigu -> `devise_incertaine`).

## D-103 — Sens du taux de change (A5, §8.7)

- **Choix** : sens imprimé (valeur `taux_change_sens` non `derive`) = sens lu. Sinon sens dérivé : valeur `derive` de l'extraction, ou, à défaut, sens le plus proche du taux de référence du jour d'acceptation. Sans référence : sens inconnu, on retient le sens qui donne le plus petit écart.
- Sens non lu : A5 est `conforme` si **l'un** des deux sens concorde dans `T_CONVERSION` (le montant déclaré est cohérent avec une lecture du taux imprimé). Sinon `ecart_certain` possible seulement si l'écart dépasse `S_CONVERSION` dans les deux sens ; sinon raison `sens_taux_derive`. La valeur de sens dérivée n'entre pas dans les valeurs clés (sa confiance 0,85 est traitée par cette règle).
- Taux absent : A5 `non_applicable` (couvert par A7). Taux illisible : `non_verifiable`. Déclarations d'un même couple avec des taux différents : `non_verifiable` (`valeur_absente`, motif `incoherent`).

## D-104 — A6 : seuils et cas indécidable

- **Choix** : « taux imprimé différent de 1 (écart > 2 %) » lu comme `|taux − 1| > 2 %` quel que soit le sens. Même nombre, sans taux imprimé ni taux de référence : `non_verifiable` (`valeur_absente`). `ecart_certain` exige la devise de facture lue en code ISO avec confiance ≥ 0,95 (ou structurée) **et** un taux imprimé exploitable ; sinon `devise_incertaine`. Montant : `déclaré − total × taux` (EUR par unité, sens lu ou dérivé), `null` sans taux ou sans sens. A5 est `non_applicable` dès qu'A6 se déclenche (calculé dans A5 et confirmé par la règle R3 du moteur) ; A7 aussi (pas de double signal).

## D-105 — A4 : explications documentées (§8.5.1 condition 7)

- **Lignes de pied** : fret, assurance, emballage, remise (pas `autre`), au plus 12 lignes ; l'écart est « expliqué » si `|écart|` égale, à `T_VALEUR` près, la somme des valeurs absolues d'un sous-ensemble de ces lignes.
- **Version rectificative** : si une autre version du même MRN porte un montant concordant, raison `version_rectificative` (`a_verifier`). Même règle en A5.
- Montant d'A4 en devise non EUR : converti au taux imprimé (sens lu ou dérivé) ; `null` sans taux ou sans sens, et en situation `incertaine`.

## D-106 — A1 : cas non énumérés

- **Choix** : identification de l'entité de facture par TVA exacte, puis SIREN (imprimé ou tiré d'une TVA FR à clé abîmée, entité unique), puis alias le plus long contenu dans le nom lu (unique). `ecart_certain` seulement si chaque facture est identifiée **par TVA** (sinon raison `confiance_insuffisante`) et via `classify` (confiance ≥ 0,90 des TVA). La TVA d'acheteur lue mais hors client (probablement celle d'un tiers) avec importateur client donne `a_verifier` (raison `controle_signal_seulement`), que A4 soit conforme ou non (A1 s'exécute avant A4). Aucune entité de part et d'autre : `a_verifier` (`confiance_insuffisante`). Plusieurs TVA du client sur la déclaration (toutes les feuilles de type TVA : importateur, destinataire, indices 1008…) ou plusieurs entités entre documents du couple : `plusieurs_entites`. Aucune entité client configurée : `non_verifiable`.

## D-107 — A2 : références citées

- **Choix** : références retenues = `documents_references` dont le code contient 380, 325 ou 935 (ou sans code), plus `references_facture` des articles. Aucune référence de facture citée : `non_verifiable` (`valeur_absente`) plutôt qu'un constat (H7 sans références : pas de signal sans objet). **Remplacé en partie par D-803.**

## D-108 — A7 : texte et seuil

- **Choix** : le libellé donne le **rapport** (en %) entre le montant déclaré et la contre-valeur indicative du total, jamais une contre-valeur en euros ; « Aucun montant n'est calculé au taux indicatif ». Taux imprimé présent mais illisible : A7 s'exécute (A5 est `non_verifiable`). Sans taux de référence ou date d'acceptation : `non_verifiable`.

## D-109 — A9 à A11 : sources et rapprochement

- **A9** : rapprochement par SH6 commun (une unité par SH6, `cle_unite(fc, dec, sh6)`), sinon une unité « total » (`quantite_totale` de la facture, à défaut somme des lignes, contre somme des quantités en unité supplémentaire). Unités normalisées (`normalize_unit`) identiques exigées, sinon `non_verifiable` `unites_differentes` (unité absente comprise).
- **A10** : masse nette déclarée = somme des masses nettes des articles (pas de total net en DE) ; brute = `masse_brute_totale`, à défaut somme des articles. Référence : totaux de la facture, à défaut le premier document support exploitable (liste de colisage, puis titre de transport, puis autre). **A11** : même logique (`nombre_colis_total`, à défaut somme des articles).

## D-110 — A12, A13 : notes de renvoi

- **A12** : par SH6 commun, comparaison des **ensembles** de pays (ISO 2) des lignes et des articles ; à défaut de SH6 commun, ensemble des origines du couple (`sous_controle = "ensemble"`). L'origine préférentielle et le code de préférence sont seulement recopiés dans `details.preferentiel_affiche`.
- **A13** : un seul constat par couple listant les SH6 de la facture absents de la déclaration et réciproquement ; `lecture_douteuse` si un code de l'un et un code de l'autre sont `codes_confondables` (1 ou 2 chiffres d'une même classe). Déclaration sans code lisible : `non_verifiable`.
- La `PHRASE_RENVOI` figure dans le **libellé** (formulation de la fiche) ; la prochaine action oriente vers un RDE ou un avocat. `renvoi = true`, montant `null`.

## D-111 — A14, A15

- **A14** : seules les factures de sous-type autre que `pro_forma` sont comparées ; toutes pro forma : `non_applicable` (`valeur_absente`, motif `pro_forma`). Constat si une date d'acceptation précède une date de facture de plus d'un jour.
- **A15** : références normalisées (`norm_ref`, ≥ 4 caractères) recherchées dans les désignations normalisées. Une désignation sans aucune référence -> `non_applicable` (raison `controle_signal_seulement`, motif `references_non_reprises`) ; facture sans référence -> `non_applicable` (`valeur_absente`).

## D-112 — Famille P

- **P1** : un document non exploitable est rattaché au type manquant selon son rôle de lien (rôle `support` ou inconnu -> « facture », §5.3.1) ; raisons `document_manquant` (+ `document_non_exploitable`) ; `attendu` = types manquants ; `details.facture_transitaire_absente` informatif.
- **P2** : un résultat par document lié (doublons exclus) : constat pour `motif_non_exploitable` renseigné ou type `document_non_exploitable`, `conforme` sinon. **P4** : un résultat par lien ; constat seulement pour `force = faible` (la force `moyenne` est traitée par la condition 5 de `classify`).
- **P3** est enregistré : un `non_verifiable` (jamais de constat) par champ clé (*) absent ou de confiance < `C_MIN_UTILE` d'un document exploitable, pour la section « non vérifiable » du rapport ; `taux_change` n'est pas exigé quand la monnaie de facturation est l'euro. Le mécanisme reste `ctx.utilisable` dans chaque contrôle.
- **P5** (prudence) : non concerné seulement si **chaque** facture porte une TVA acheteur lue avec confiance ≥ 0,90 qui n'est celle d'aucune entité, sans autre identification du client (SIREN, alias, destinataire), **et** si chaque déclaration a une TVA importateur lisible et qu'aucune TVA du client n'y figure. Aucune entité configurée : `non_verifiable`.

# Contrôles C et D

## D-201 — Montants de référence par déclaration (§12.1)

- **Choix** : `liquide[k]` = Σ `montant_a_payer` (à défaut `montant`) des lignes de catégorie `k` non `autoliquide`, sur la **dernière version** de chaque préfixe MRN (`ctx.declarations()`). Autoliquidation : au moins un indice **utilisable** (≥ `C_MIN_UTILE`) — code 1008 (valeur ou numéro de TVA), FR7, ou ligne de TVA au paiement `autoliquide` (sa valeur `mode_paiement`, à défaut son montant). La confiance ≥ 0,90 exigée par §12.1 est appliquée au **classement** de C3 (l'indice le plus sûr est une valeur clé) : un indice peu sûr donne un C3 `a_verifier` plutôt qu'aucun constat.
- **Complétude** : si `total_a_payer` dépasse la somme lue de plus de `T_SOMME(n lignes)`, `liquide_total = total_a_payer` et les composantes **sans aucune ligne lue** (droits, autres taxes, TVA hors autoliquidation) deviennent `non_verifiable` (`valeur_absente`) ; si aucune composante ne manque, toutes le deviennent (une ligne d'une composante a pu échapper à la lecture). Exception : une différence égale (à `T_SOMME` près) à la TVA autoliquidée signifie que le total l'inclut ; la déclaration est alors réputée complète. Ligne de taxation illisible : sa composante est `non_verifiable` et C5 utilise `total_a_payer` s'il est lu, sinon `non_verifiable`. Ligne de catégorie `inconnue` : comptée dans le total seulement, composantes `non_verifiable`.
- **Composante sans ligne et complétude non vérifiable** (pas de `total_a_payer`) : la référence 0 n'est pas prouvée ; un écart sur cette composante est `a_verifier` (raison `valeur_absente`), jamais certain.
- `T_DEBOURS` utilise le nombre d'articles de l'unité : Σ `nombre_articles` imprimés, à défaut nombre de blocs articles, à défaut articles distincts des taxations (au moins 1).

## D-202 — Unités de comparaison C1–C5 (§12.2)

- **Affectation d'une ligne de débours** : allocation explicite du dossier (ligne -> déclaration, `montant_alloue` sinon montant de la ligne ; une allocation `prorata` rend le constat `a_verifier`), sinon MRN cité sur la ligne (préfixe 15), sinon unique déclaration couverte par la facture (MRN cités en en-tête, tableau ou lignes, ou toutes les déclarations du dossier si la facture n'en cite aucun). Une ligne non ventilée d'une facture couvrant plusieurs déclarations fusionne ces déclarations en **une** unité (comparaison sur la somme, le constat cite tous les MRN).
- **Plusieurs factures, même déclaration** : additionnées dans une unité `cle_unite(ft=[…], dec=[…])` (facture initiale + complémentaire ; une même déclaration refacturée deux fois fait apparaître l'excédent en C1–C5). Une facture de prestations sans ligne de débours ne crée pas d'unité ; si aucune facture du dossier ne porte de débours, C1–C6 sont `non_applicable` (`valeur_absente`, motif `aucune_ligne_de_debours`).
- **Relevé** : une ligne citant le MRN d'une déclaration hors du dossier est écartée (elle relève d'un autre dossier) ; une ligne non ventilée d'un relevé qui cite aussi des MRN hors dossier rend l'unité `non_verifiable` (`ventilation_par_mrn_absente`). Hors relevé, si le dossier n'a qu'une déclaration, une ligne citant un MRN inconnu lui reste affectée (la discordance de référence est le sujet de C7).
- **Avoirs déjà reçus** (§8.6, §12.2) : un avoir du dossier qui cite une facture de l'unité (`ref_compatibles`), à défaut un MRN de l'unité, est déduit ligne de débours par composante (ligne sans MRN ambiguë entre unités : non déduite ; même numéro d'avoir reçu deux fois : déduit une fois). `montant_en_jeu` = écart net, `montant_brut` = écart avant avoir ; si l'avoir couvre l'écart (net ≤ `T_DEBOURS`), le résultat est `conforme`. Les `ecarts_recouvrement` ne sont pas relus (pas de double déduction avec la famille E).

## D-203 — C1–C5 : composantes, débours combinés, version rectificative

- Une ligne « droits et taxes » combinée rend C1 et C2 `non_verifiable` (`debours_combines_sans_ventilation`), ainsi que C3/C4 s'il n'y a pas de ligne de TVA distincte ; C5 porte alors seul le montant (le moteur ne le neutralise pas puisque C1/C2 ne sont pas évaluables).
- C3 et C4 sont exclusifs : C3 `non_applicable` (`couvert_par_autre_controle`, C4) sans autoliquidation ; C4 `non_applicable` (C3) si toutes les déclarations de l'unité l'indiquent. Unité mêlant déclarations autoliquidées et non : C3 `non_verifiable`, C4 compare avec une TVA de référence nulle pour les autoliquidées.
- C5 retire la TVA refacturée quand C3 s'est déclenché sur l'unité (lu dans `ctx.anterieurs("C3")`) et retire des deux côtés le forfait petits envois s'il est refacturé sur des lignes distinctes (comparé par G4), pour ne pas compter deux fois le même excédent.
- C1 est `non_applicable` (G4) quand le transitaire refacture en « droits » le seul droit forfaitaire liquidé (aucune ligne de droits, une ligne de forfait sur la déclaration).
- Condition 7 : si l'écart disparaît (dans `T_DEBOURS`) en prenant une version antérieure de la déclaration, le constat est `a_verifier` (raison `version_rectificative`), montant calculé sur la dernière version.
- Écart négatif : `a_verifier`, montant négatif, prochaine action qui précise qu'aucun avoir n'est à demander.
- C3 : le libellé reprend la forme de §12 (« la TVA est indiquée comme autoliquidée (code document 1008 suivi du numéro …, page n) ») ; la prochaine action précise que le constat ne se prononce pas sur l'applicabilité de l'autoliquidation (sans phrase de renvoi : ce n'est pas une note de renvoi).

## D-204 — C6 et D4 : assiette corrigée, pas de double comptage

- **C6** (unité : ligne FAF, `cle_unite(ft=…, ligne=…)`) : taux de la grille validée (poste FAF unique en `pourcentage`), sinon `pourcentage` imprimé sur la ligne, sinon `non_verifiable`. Débours rattachés : unités de la facture, sinon unités des déclarations qu'elle couvre (facture de prestations séparée). `excedent_faf = min(FAF(assiette facturée) − FAF(assiette − excédent) ; FAF facturé − FAF(assiette − excédent))`, chaque FAF borné par minimum/maximum (FAF au minimum : 0). Excédent = Σ des excédents positifs des unités, restreint aux composantes de `base_pourcentage` (total des débours par défaut). Tolérance `T_TARIF`, seuil de certitude `S_DEBOURS` (C6 est un contrôle C) ; `ecart_certain` seulement si chaque unité en excédent porte un constat C1–C5 positif `ecart_certain` (sinon les raisons de ces constats sont reprises).
- **D4** : `attendu = borner(pourcentage × (assiette − excédent C))` ; l'écart est diminué du montant déjà chiffré par C6 sur la même ligne (`details.deduit_c6`). Ainsi C6 + D4 = FAF facturé − FAF attendu sur les débours retenus, sans double comptage. Sans déclaration rapprochée : assiette = débours de la facture, sans correction.

## D-205 — C7, C8

- **C7** : MRN reconnus par préfixe parmi toutes les versions du dossier et les déclarations des autres dossiers du client (relevés) ; références de transport comparées (`ref_transport_compatibles` ou `ref_compatibles`) aux références de la déclaration (DG 12 03), de la facture commerciale et des documents support. Sans aucune référence de comparaison, les références de transport ne sont pas jugées ; facture sans référence : `non_verifiable`.
- **C8** : TVA du client facturé contre la TVA importateur des déclarations (à défaut l'acheteur de la facture commerciale). Écart de TVA : `ecart_certain` possible (deux TVA ≥ 0,90, test de confusion par `codes_confondables` sur une lecture OCR) ; le libellé dit si le numéro est celui d'une autre entité du client. Sans TVA lue : rapprochement par nom/alias, au mieux `a_verifier` (`plusieurs_entites`) quand le nom désigne une autre entité, sinon `non_verifiable`.

## D-206 — Famille D : grille, rapprochement, aiguillage

- **Grille** : transitaire du dossier, sinon émetteur reconnu par sa TVA puis par nom/alias (un seul transitaire) ; grille `validee` applicable à la date de la facture (la plus haute `version`, puis `valide_du`). Sans grille : un `non_applicable` (`aucune_grille_validee`) par facture pour D2–D9 (D8 compris, conformément à §13) ; D1 s'exécute toujours.
- **Rapprochement** : postes de même `nature` ; un seul -> retenu ; plusieurs -> départage par libellé (égalité ou inclusion par mots entiers, ≥ 4 caractères, sans accents ni casse) ; aucun poste de cette nature -> recherche par libellé sur toute la grille (nature mal déduite). Plusieurs postes possibles -> `a_verifier` (`confiance_insuffisante`), sans montant.
- **Aiguillage** d'une ligne de prestation rapprochée : FAF -> D4, magasinage -> D6, surcharge -> D7, ligne supplémentaire (poste `unitaire` par article ou sans unité) -> D9, autres -> D3. Sans poste : D2, sauf surcharge -> D7 (règle « comme D2 »). Les lignes de débours ne relèvent que de D1 et D8.
- **D2** : `interdites` -> `ecart_certain` possible ; `tolerees` -> `a_verifier` (non éligible). Montant = HT, TVA de la ligne en `montant_tva_associee`.
- **D3** : `forfait` = prix ; `unitaire` = quantité × prix, borné par minimum/maximum ; quantité non imprimée -> 1, constat au mieux `a_verifier` (`valeur_absente`). Poste en `pourcentage` hors FAF/surcharge : même calcul que D4.
- **D5** : lignes de **prestation** seulement (un débours en double est déjà un excédent C) ; montant = (occurrences − 1) × montant ; poste `unitaire`/`par_jour` (quantité multiple prévue) -> `a_verifier`. Unité `cle_unite(ft=…, lignes=[…])`, `conforme` par facture sans doublon.
- **D6** : poste `par_jour`/`unitaire` : jours = `date_fin − date_debut + 1` moins `franchise_jours` (≥ 0), × prix, borné ; sans période lisible : quantité imprimée × prix (au mieux `a_verifier` si une franchise existe) ; poste `forfait` : comme D3.
- **D7** : pourcentage de surcharge : assiette = débours selon `base_pourcentage`, ou lignes `transport` de la facture si la base est `autre` ou absente ; sinon `non_verifiable`.
- **D8** : TVA > `T_LIGNE` (imprimée, ou HT × taux imprimé) sur une ligne `debours_*` : toujours `a_verifier`, seule raison `point_fiscal`, montant informatif = TVA, renvoi vers l'expert-comptable.
- **D9** : `inclus` du poste ligne supplémentaire, à défaut celui de l'unique poste de dédouanement, à défaut 0 ; nombre d'articles des déclarations couvertes (`nombre_articles` imprimé ; à défaut nombre de blocs articles -> raison `total_reconstruit`) ; quantité non imprimée -> montant ÷ prix si entier.
- **Seuils** : tolérance `T_TARIF`, certitude `S_TARIF` ; écart négatif -> `conforme` (D3, D4, D6, D7, D9).

## D-207 — D1 : présentations admises

- **Choix** : sous-contrôles `ligne` et `tva_ligne` seulement si les trois valeurs sont lues (pas de résultat sinon) ; `total_debours` ignoré si le total est `reconstruit` ; `total_ht` accepte Σ de toutes les lignes ou Σ des seules prestations (débours présentés hors total HT) ; `total_ttc` accepte HT + TVA, ou HT + TVA + débours quand le total HT ne comprend que les prestations ; `net_a_payer` = TTC − acomptes (0 si non imprimés). L'écart retenu est celui de la présentation la plus proche. Montant `recouvrable` seulement pour un total imprimé supérieur au calcul ; tolérance `T_SOMME(n)` (n = opérandes), certitude `S_ARITH`.

# Contrôles B, E, F, G

## D-301 — B2 : totaux de catégorie, totaux de référence, hypothèses

- **Totaux de catégorie** : le modèle n'a pas de champ « total par catégorie ». Pour un même code de taxe, s'il existe **exactement une** ligne de taxation sans article **et** au moins une ligne par article, la ligne sans article est lue comme le total imprimé de la catégorie (sous-contrôle `categorie`, unité `cle_unite(dec=, taxe=<code>)`) ; elle est exclue de la somme générale. Sinon, aucune ligne n'est prise pour un total.
- **Somme générale** (sous-contrôle `total`, unité `cle_unite(dec=)`) : montant imprimé de chaque ligne (à défaut `montant_a_payer`), TVA autoliquidée incluse puis exclue ; totaux de référence : `total_droits_taxes` puis `total_a_payer`. `conforme` si **une** combinaison (total, hypothèse) concorde dans `T_SOMME(n)`. Sinon l'écart est rapporté contre `total_droits_taxes` s'il est imprimé, avec l'hypothèse la plus proche (`details.hypothese`).
- **Tous les articles lus** : nombre d'articles distincts lus (blocs articles, à défaut numéros d'article des taxations) = `nombre_articles` imprimé ; sinon le constat est `a_verifier`, raison `valeur_absente` (« une ligne non lue peut expliquer l'écart » dans le libellé). Total absent : `non_applicable` ; une ligne illisible : `non_verifiable`.

## D-302 — B3 : devise et montant

- Σ `montant_facture_article` contre `montant_total_facture` dans la devise imprimée ; `T_SOMME(n)` appliqué en unités de cette devise. Montant `arithmetique_declaration` en EUR : direct en EUR, sinon converti au taux imprimé de la déclaration (raison informative `montant_converti`, le taux et son sens deviennent valeurs clés) ; sans taux ou sans sens : montant `null`, `a_verifier` (raison `valeur_absente`). Le seuil de 1,00 EUR s'applique à l'écart converti.
- Un article sans montant alors que d'autres en ont : `non_verifiable` ; aucun montant d'article ou pas de total : `non_applicable`.

## D-303 — B4, B5 : sous-contrôles

- B4 (a) `nette_brute` par article (unité `cle_unite(dec=, art=<index>)`) et `nette_total` (Σ masses nettes des articles contre `masse_brute_totale`, la déclaration n'ayant pas de masse nette totale) : `ecart_certain` possible, **seuil de certitude = tolérance** `T_MASSE` (aucun seuil distinct n'est spécifié). (b) `somme_brute` : `a_verifier` seulement (`eligible=False`). Une sous-vérification sans données n'est pas exécutée ; aucune masse lue : un seul `non_applicable`.
- B5 : exige un nombre de colis sur **chaque** article ; partiel -> `non_verifiable`. La prochaine action de B4/B5 est celle de la famille B (`ACTION_B`).

## D-304 — Imputation des avoirs (§17.2) : fonction pure `imputer_avoirs`

- **Où** : `controldone.recouvrement.imputation` (voir `docs/ARCHITECTURE.md` § 10). Entrées : `LigneCredit` (une par ligne d'avoir, montant **HT**, nature, émetteur, factures d'origine, MRN, références de transport — ceux de la ligne, à défaut ceux de l'en-tête) et `EcartImputable` ; sortie `ResultatImputation` (imputations, état de chaque écart, reliquats).
- **Rattachement par paliers** : facture d'origine (`ref_compatibles`), puis MRN (préfixe), puis référence de transport ; on ne passe au palier suivant que si le précédent ne donne **aucun** candidat (lecture large : imputer plutôt que réclamer un montant déjà crédité, P-7). Même émetteur exigé (clé `cle_emetteur` : identifiant du `Transitaire` reconnu par TVA, nom ou alias, sinon `tva:`/`nom:`), même composante, statut imputable, reste > 0.
- **Ordre** : écarts déjà réclamés (`reclame`, `partiellement_credite`, `conteste`) avant `ouvert`, puis date de constat (absente en dernier), `constat_id`, `id`. Lignes : avoirs par date (absente en dernier), numéro normalisé, id ; dans un avoir, nature (ordre de `NatureLigne`) puis index. Ligne combinée : `droit`, `autre_taxe`, `tva`, `forfait_petits_envois`.
- **Avoir sans ventilation** (aucune ligne lisible) : une ligne sans nature au montant `total_credite_ht` (à défaut TTC), **jamais imputée** (reliquat entier, signalé par E5).
- Arrondi au centime de chaque imputation ; `credite` si `reste ≤ T_DEBOURS` (paramètre `t_debours`).

## D-305 — Famille E : unités, émetteur, E1 à E4

- Unité `cle_unite(av=<id>)` ; E4 par sous-contrôle (`ligne`, `tva_ligne` : `cle_unite(av=, ligne=)` ; `total_ht`, `total_ttc` : `cle_unite(av=)`) ; E6 `cle_unite(ecart=<id>)`. Pas d'avoir : `non_applicable`, raison `document_manquant` (`details.motif`), sans ajout d'énumération.
- **Même émetteur** : un émetteur illisible d'un côté n'empêche pas le rapprochement par référence (E1, E2, F3) ; deux émetteurs lus et différents l'empêchent.
- **E1** : factures d'origine cherchées dans le dossier **et** dans les autres dossiers du client. Rattachement secondaire : MRN (déclarations et factures transitaires du dossier), puis référence de transport (clés du dossier, factures transitaires, facture commerciale) ; raison `rattachement_faible` dans les deux cas « faibles ».
- **E2** : Σ (par nature ; natures de débours regroupées dès qu'une ligne « droits et taxes » combinée figure d'un côté) de tous les avoirs reçus citant la ou les factures d'origine (hors secondes réceptions E3) contre Σ facturé, tolérance `T_SOMME(n lignes des deux côtés)`. Avoirs non ventilés : totaux HT. Facture d'origine introuvable : `non_verifiable` (`document_manquant`).
- **E3** : « même numéro » exige deux émetteurs lus et égaux ; « même montant » = même total crédité (TTC, à défaut HT) au centime, même facture d'origine (`ref_compatibles`) et écart de dates **strictement** inférieur à 7 jours (dates lisibles exigées). La seconde réception est la plus récente (date, numéro, identifiant) ; recherche aussi dans les autres dossiers.
- **E4** : `taux_tva` lu en pour cent ; tolérances `T_LIGNE` / `T_SOMME` ; seuil `S_ARITH` enregistré mais le contrôle reste `a_verifier` (Annexe A) ; montant `aucun`.

## D-306 — E5, E6 : écarts candidats et remplacement du montant

- **Écarts candidats** de l'imputation du dossier : (1) le registre `ctx.ecarts_recouvrement` (statuts imputables), dont le reste est **recalculé depuis `montant_initial`** avec les avoirs du dossier (recalcul idempotent ; un crédit venu d'un avoir d'un autre dossier n'est donc pas vu ici) ; (2) les constats `recouvrable` positifs des contrôles **déjà exécutés** (C, D ; montant brut, composante du constat ou C1 -> droit, C2 -> autre taxe, C3/C4 -> TVA ; un constat sans composante, ex. C5 combiné, est ignoré). Les constats F3, F4, G4, G5 s'exécutent après E (ordre de l'Annexe A) et ne sont pas candidats : un avoir qui les règle apparaît en E5 (information, `a_verifier`).
- **E5** : reliquat > `T_SOMME(n lignes de l'avoir)` ; la seconde réception (E3) est `non_applicable` (`couvert_par_autre_controle`).
- **E6** : seulement pour un écart du **registre** déjà réclamé (`reclame`, `partiellement_credite`, `conteste`) que les avoirs du dossier créditent en partie ; `montant_en_jeu` = reste. « Remplace le montant d'origine dans les totaux » : le moteur ne permet pas à un contrôle de modifier un autre résultat ; E6 porte `details.remplace_constat_id` (le constat d'origine), que le consommateur des totaux doit exclure. Une règle moteur (comme R4 pour G4/G5) serait plus sûre : proposée, non implémentée (hors périmètre de l'équipe).

## D-307 — Famille F : fenêtre, porteur du constat

- Recherche dans `ctx.autres_dossiers` (même client par construction) ; fenêtre `fenetre_doublons_mois` sur les dates des documents (facture, avoir, acceptation) ; une date illisible ne fait pas sortir de la fenêtre. Un document partagé par deux dossiers (même identifiant, ex. relevé mensuel) n'est pas un doublon.
- **Porteur** : l'occurrence la plus récente (date, numéro normalisé, identifiant UUID v7) porte le constat et cite l'autre dossier (`autres_dossiers`) et son document (preuves) ; l'autre dossier produit `non_applicable` (`couvert_par_autre_controle`, `details.porte_par`). Un lien faible du document de l'autre dossier ajoute `rattachement_faible`.
- **F1** : même `identite` (§6.2.6), ou `doublon_de` renseigné ; la seconde occurrence est l'identifiant le plus grand. **F2** : émetteurs lus et égaux exigés ; total comparé = TTC, à défaut net à payer, à défaut HT ; tolérance `T_SOMME(1)` ; deux documents de même `identite` relèvent de F1.

## D-308 — F3 : affectation au MRN, complémentarité, certitude

- Débours de chaque facture pour un préfixe MRN selon §12.2 (lignes citant le MRN ; lignes sans MRN affectées si la facture ne cite qu'un MRN). Unité `cle_unite(ft=, mrn=<préfixe>)`. Les factures de même numéro normalisé relèvent de F1/F2.
- Deux factures du **même** dossier : `non_applicable` (C5 compte déjà l'excédent). Annulation : un avoir (ici ou ailleurs) citant l'une des factures et créditant au moins ses débours (à `T_DEBOURS` près) -> `conforme`. Complémentaire : somme des deux = `liquide_total` de la déclaration (ici, sinon dernière version dans un autre dossier) dans `T_DEBOURS` -> `conforme`.
- **Certitude** : appliquée telle quelle (MRN lu ≥ 0,90 sur chaque facture — une affectation sans MRN imprimé ajoute `confiance_insuffisante` —, débours égaux dans `T_DEBOURS`, `> S_DEBOURS`, règle générale), y compris quand la déclaration est absente du contexte. Débours différents : `a_verifier` (`controle_signal_seulement`). Montant = débours de la facture la plus récente ; composante `null` (débours mêlés).

## D-309 — F4, F5

- **F4** : référence de la ligne (MRN ou transport), à défaut référence d'en-tête si elle est unique ; une ligne sans référence n'est pas comparée. Montant égal au centime ; émetteurs « mêmes » au sens de D-305. Dans le même dossier aussi (deux factures distinctes).
- **F5** : déclarations (dernière version par préfixe MRN, ici et ailleurs) citant le numéro de la facture (`documents_references` hors codes 1008/N7xx, références par article) ; montants dans la devise de la facture exigés (sinon `non_verifiable`) ; tolérance `T_VALEUR` ; porteur = dossier de la déclaration la plus récente ; montant converti au taux imprimé de cette déclaration.

## D-310 — Famille G : détection, nombres imprimés, renvois

- **Détection** d'une ligne de forfait : catégorie normalisée `forfait_petits_envois`, ou code configuré (`codes_forfait_petits_envois`), ou libellé configuré retrouvé dans le texte lu du type de taxe. Le montant unitaire de référence n'est **jamais** utilisé (ni pour reconnaître, ni pour calculer) : B1 ne traite que la catégorie normalisée, une ligne reconnue seulement par code ou libellé peut donc être vue par B1 et G1 (équivalents banc G1/B1). Pas de ligne de forfait : `non_applicable` (raison `valeur_absente`, `details.motif`).
- **G1** : tolérance stricte 0,01 EUR (`T_LIGNE`, pas d'arrondi à l'euro) ; taux imprimé absent -> `non_verifiable`.
- **G2** : base = Σ `base_quantite` des lignes de forfait de la déclaration ; référence = `nombre_articles` imprimé, à défaut nombre de blocs articles lus (jamais certain, raison `valeur_absente`) ; exact (tolérance et seuil 0) ; montant `(base − n) × taux` si un taux imprimé unique, sinon `null`.
- **G3** : codes complets (chiffres du code imprimé) et codes à 6 chiffres ; constat si la base diffère des deux ; un article sans code lisible -> `non_verifiable`. Le texte ne dit jamais ce qu'est un « article ».
- **G4** : unité `cle_unite(ft=, dec=[…])` (ventilation §12.2), liquidé = Σ `montant_a_payer` (à défaut `montant`) des lignes de forfait non autoliquidées ; lignes `debours_droits` retenues seulement si la facture n'a pas de ligne de forfait **et** si la déclaration ne porte aucun autre droit de montant non nul. Montant net des avoirs du dossier imputés selon §17.2 (`montant_brut` = brut) ; si le net est dans `T_DEBOURS`, `conforme` (condition 7).
- **G5** : seulement si la ligne imprime une quantité ; `écart = (quantité − base déclarée) × prix unitaire imprimé`.
- **G6** : hors période si la date d'acceptation est **avant** `date_debut` ou **après** `date_fin` ; valeur = `montant_total_facture` de la déclaration (EUR, ou converti au taux imprimé) **strictement** supérieure au seuil. Aucun signal mais une donnée illisible -> `non_verifiable`. G3 et G6 : `renvoi = true`, montant `null`, `PHRASE_RENVOI` dans la prochaine action.

## D-311 — Module d'aides interne

- `controls/_aides_befg.py` (préfixe `_`, non chargé comme famille) regroupe les lectures communes à E, F et G (références lisibles, émetteurs, fenêtre, ventilation §12.2, avoirs reçus deux fois). Aucune modification du cadre (`framework`, `context`, `runner`, énumérations) n'a été nécessaire.

# Orchestration

## D-900 — Démarrage anticipé du socle du niveau 2

- **Choix** : le socle d'exploitation (base, cloisonnement, rôles, audit, file de tâches) a démarré pendant que le générateur de corpus du niveau 1 tournait, dans des modules séparés (`storage/`, `jobs/`, `auth/`) qui ne modifient aucun fichier du moteur.
- **Pourquoi** : le niveau 1 était bloqué par la génération du corpus, pas par du travail d'ingénierie ; la vérification du niveau 1 (banc sur le corpus tenu à l'écart) reste un préalable à toute déclaration « niveau 1 terminé ».

## D-401 — Regroupement (§7.5) : force des liens et frontières

- **Force** : score = somme des poids des signaux distincts (forte 3, moyenne 2, faible 1) ; pas de lien sous 2 ; score 2 -> `faible` (P4) ; score ≥ 3 -> `forte` **seulement** si au moins un signal explicite (référence de facture citée, référence de transport, MRN cité), sinon `moyenne` (non solide au sens de §8.5.1 condition 5). Pourquoi : un cumul d'indices indirects (même fichier + montant égal) ne vaut pas une référence citée ; cohérent avec la règle du banc « liens explicites » pour `ecart_certain`.
- **Frontière** : dossier parent le plus profond du fichier dont le sous-arbre contient des types de documents différents ; deux documents ne sont regroupés que si leurs frontières sont égales ou emboîtées (un relevé posé à la racine peut rejoindre plusieurs sous-dossiers ; deux sous-dossiers frères jamais). Courriels : une frontière par message, franchie seulement par un MRN ou une référence de transport commune.
- **Repli `meme_dossier_source`** (option, active par défaut) : un document sans lien suffisant rejoint l'**unique** dossier candidat de sa frontière (poids 2, donc `faible`, P4) ; un dossier incomplet (sans facture ou sans déclaration) est fusionné avec l'unique dossier complet de sa frontière. Pourquoi : un dépôt rangé par envoi (et chaque dossier du banc) ne doit pas éclater en dossiers orphelins ; le rattachement reste signalé faible.
- **Allocations** : facture -> déclaration `totalite` (1 pour 1), `reference_explicite` (déclaration citant la facture, montant = articles qui la citent ou montant déclaré si elle est seule citée), sinon `prorata` des montants déclarés ; lignes de débours -> MRN `ligne_par_mrn`, `totalite` (facture mono-MRN), sinon `prorata` des taxes déclarées. Seule la dernière version d'une déclaration (préfixe MRN) sert aux allocations et aux clés.
- **Ajouts de signaux** : une facture transitaire qui cite le numéro de facture commerciale reçoit `ref_facture_citee` (forte) ; un document support est rattaché par référence de transport, référence de facture ou MRN.

## D-402 — Pipeline et banc : assemblage

- `traiter_lot` = `preparer_lot` (réception -> regroupement) + `controler_lot` (contrôles, rédaction, findings), séparables pour la famille F : le banc prépare tous les dossiers en parallèle puis exécute les contrôles de chaque dossier avec tous les dossiers du même client (processus `fork`, état partagé en lecture).
- Composants découverts à l'exécution (`controldone.ingest.Decoupeur`, `controldone.ingest.structure.extracteurs`, `controldone.extract.deterministe.extracteurs`, `LLMExtracteur` si une clé est présente) ; un composant en erreur ne bloque jamais le lot (fichier listé « non lu »).
- Extraction (§7.3) : un export structuré complet fait foi ; sinon tous les extracteurs `deterministe` et `llm` disponibles tournent et sont fusionnés (`fusionner_resultats`).
- Banc : un `findings.json` par dossier du corpus ; si le lot produit plusieurs dossiers (orphelins), leurs sorties sont réunies (statut le plus prioritaire). Le client d'un dossier vient de `manifest.json`, à défaut des identifiants d'entités trouvés dans le texte ; `truth.json` n'est jamais lu.
- Rapport (§18) : montants proposés **avant validation** (mention explicite) ; un constat bloqué pour formulation interdite est affiché avec une mention neutre ; génération refusée si le texte visible contient une formulation interdite.

# Plateforme

Numérotation D-450 et suivantes (D-401 et D-402 sont déjà prises par l'assemblage). Détails :
`docs/SECURITY.md`, `docs/EXPLOITATION.md`.

## D-450 — Cloisonnement : couche d'accès unique et trois barrières

- **Choix** : `TenantScope(session, tenant_id, actor)` est le seul chemin vers les données client ; filtre explicite, plus un critère `with_loader_criteria` ajouté automatiquement à toute requête ORM d'une session liée à un client (écouteur global `do_orm_execute`), plus un contrôle au flush (`before_flush`). Une session non liée qui touche une table client est refusée. Aucune `relationship()` dans les modèles. Un test d'architecture interdit `select(`, `.execute(`, `sqlalchemy`… hors de `controldone.storage`.
- **Pourquoi** : D-003 confie le cloisonnement au code ; une seule barrière (filtre explicite) ne résiste pas à une requête écrite à la main ou à une jointure. Erreur identique pour « autre client » et « inexistant » (pas d'oracle).
- **Écarté** : sécurité au niveau des lignes de PostgreSQL (indisponible en SQLite, D-003) ; clés primaires composites `(tenant_id, id)` (complexité ; l'identifiant UUID v7 aléatoire n'est pas devinable et une collision est refusée sans écrasement).

## D-451 — Accès du fondateur

- **Choix** : le fondateur n'ouvre jamais un `TenantScope` directement ; `OperatorScope.client(tenant, motif)` écrit `acces_admin` **validé immédiatement** (trace conservée même si l'opération échoue) ; ses écritures dans le périmètre sont journalisées ; sa session propre est en lecture seule. Avec SQLite (un seul écrivain), chaque nouvel accès tracé valide d'abord les écritures en cours des périmètres déjà ouverts.

## D-452 — Journal d'audit chaîné

- **Choix** : `prev_hash`/`hash` SHA-256 sur un JSON canonique, `prev_hash` unique (pas de fourche), déclencheurs SQL qui refusent UPDATE/DELETE, `verifier_chaine`. Le journal survit à l'effacement d'un client (identifiants seulement).
- **Limite** : sans ancrage externe, une réécriture complète de la chaîne par un détenteur du fichier de base reste indétectable (point ouvert).

## D-453 — Rôles et publication

- **Choix** : `peut(user, action, ressource)`, refus par défaut. `client_admin` : lecture/écriture de son client sauf validation, publication, grilles validées et actions sortantes ; `client_lecteur` : lecture ; `systeme` : écrit les données produites par le moteur, ne valide rien. Un rôle client ne lit que les constats `valide` et jamais la table des résultats bruts ; l'appartenance au client est revérifiée en base à l'ouverture du périmètre.

## D-454 — SQLite : `BEGIN IMMEDIATE`

- **Choix** : toute transaction d'écriture SQLite commence par `BEGIN IMMEDIATE` (pilotage manuel des transactions de pysqlite), `busy_timeout` 30 s ; `Database.session(lecture=True)` ouvre une transaction différée.
- **Pourquoi** : en WAL, une transaction qui lit puis écrit échoue (`SQLITE_BUSY_SNAPSHOT`) si un autre écrivain est passé entre-temps ; sérialiser les écrivains est sûr pour un premier client et un ou deux workers. PostgreSQL (D-003) lève la limite.

## D-455 — Coffre chiffré, clés dérivées

- **Choix** : Fernet, clé par client dérivée par HKDF-SHA256 de la clé maîtresse (`vault:<client>`), adressage par SHA-256 du clair revérifié à la lecture ; `MultiFernet` pour la rotation (`CONTROLDONE_MASTER_KEY=nouvelle,ancienne` puis `tourner_cles`). Clés dérivées distinctes pour les sauvegardes et les secrets TOTP. Sans clé : refus de démarrer en `prod` ; clé générée dans `var/dev_master.key` avec avertissement en `dev`/`test` ; mode inconnu traité comme `prod`.
- **Écarté** : AES-GCM « fait main » (Fernet authentifie déjà et évite les erreurs de nonce) ; chiffrement de la base vivante (laissé au volume ou à l'hébergeur PostgreSQL, point ouvert).

## D-456 — Conservation : unité de purge

- **Choix** : un fichier brut (et ses textes de page) est purgé quand **tous** les dossiers qui l'utilisent (table `dossier_fichiers`) sont clôturés depuis `retention_jours` ; un fichier rattaché à aucun dossier suit la clôture de son lot. Un contenu encore référencé par une autre ligne du même client (adressage par contenu) n'est pas effacé du coffre. Métadonnées et constats conservés.

## D-457 — Effacement et restitution

- **Choix** : `supprimer_client` efface toutes les tables du client, ses comptes qui n'appartiennent à aucun autre client, ses jobs, ses alertes et son coffre, puis journalise `supprimer_client` (motif obligatoire, fondateur seul). `exporter_client` : ZIP JSON + pièces d'origine + manifeste SHA-256 ; export complet pour le fondateur (accès tracé), constats publiés seulement pour un `client_admin`. Les rapports PDF générés ne sont pas encore stockés : l'export contient les pièces d'origine, pas de rapport PDF (point ouvert).

## D-458 — File de tâches

- **Choix** : table `jobs` (clé d'idempotence unique), prise atomique (UPDATE conditionnel, `SKIP LOCKED` en PostgreSQL), essais comptés à la prise, bail prolongé par un fil de battement de cœur, attente 30 s × 2^(n−1) plafonnée à 1 h, `dead` après 5 essais (ou bail expiré au dernier essai, ou `ErreurDefinitive`, ou handler inconnu) avec alerte et audit. Le message d'une exception n'est jamais stocké ni journalisé (nom de classe seulement), sauf pour nos exceptions `ErreurDefinitive`/`ErreurTemporaire`.
- **`traiter_lot`** : déchiffre le lot dans un répertoire temporaire (chemins assainis), appelle `controldone.pipeline.traiter_lot` (import paresseux, absence = erreur réessayable), enregistre tout dans **une** transaction qui marque le lot `traite` ; un lot déjà traité n'est jamais retraité (effet unique malgré les reprises).

## D-459 — Alertes du fondateur : table `alertes`

- **Choix** : les alertes internes (job mort, 80 % et 100 % du plafond IA) vont dans une table `alertes` dédoublonnée par clé (`cout80:<client>:<mois>`…), lue par le tableau de bord (`OperatorScope.alertes()`), et non dans la file des actions sortantes.
- **Pourquoi** : la file sortante sert aux envois vers l'extérieur soumis à approbation ; une alerte n'a ni destinataire externe ni approbation. Si une notification par courriel au fondateur est voulue plus tard, elle sera une `ActionSortante` de type `email_client`/nouveau type, en mode `auto`.

## D-460 — Plafond mensuel de coût IA

- **Choix** : plafond lu dans `reglages["plafond_cout_ia_mensuel_eur"]` du client, sinon la colonne (8 EUR) ; vérifié avant chaque lot : à 100 % le pipeline tourne avec `llm=False`. « Décision du fondateur » = relèvement du plafond. `RegistreCoutsDB(db, client)` (un registre par client) implémente le protocole `RegistreCouts` de `extract.llm`.
- **Limite** : le pipeline actuel crée son propre registre en mémoire ; le plafond mensuel n'est donc pas réévalué pendant un lot (point ouvert : injection du registre).

## D-461 — Actions sortantes

- **Choix** : `brouillon -> approuve | corrige | refuse`, puis `approuve | corrige -> envoye` ; décisions réservées au fondateur ; `check_text` sur toutes les chaînes rédigées du contenu (hors destinataires, identifiants, références de pièces) avant approbation, correction **et** envoi ; blocage enregistré (motif + audit). Autonomie par type en base, `manuel` par défaut pour tous, `auto` = approbation automatique seulement ; seul `ExpediteurFichier` est livré. Un rôle client ne voit que les actions **envoyées** de son client.

## D-462 — Authentification

- **Choix** : Argon2id (argon2-cffi) ; TOTP RFC 6238 en bibliothèque standard, secret chiffré, anti-rejeu par dernier pas utilisé ; jetons de session itsdangerous (liste de secrets pour la rotation), inactivité 30 min, durée absolue 8 h, rotation 15 min, drapeau « second facteur » obligatoire pour un jeton fondateur ; cookie `__Host-`, `HttpOnly`, `Secure`, `SameSite=Strict` ; CSRF HMAC lié à la session ; clés d'API `cdk_<préfixe>_<secret>` avec SHA-256 du secret (256 bits d'entropie : pas de hachage lent) ; limiteur de débit en mémoire.
- **Limite** : révocation des sessions et limiteur en mémoire du processus (points ouverts).

# Exploitation : agents, litiges, référentiel, connecteurs

Numérotation D-600 et suivantes. Détails : `docs/AGENTS.md`, `docs/REFERENTIEL.md`, `docs/EXPLOITATION.md`.

## D-600 — Litiges : statut du dossier de demande d'avoir

- **Choix** : `litiges.etats.StatutReclamation` — `brouillon -> valide -> envoyee -> partiellement_credite -> credite -> clos`, plus `conteste` (retour `envoyee` par relance du client) et `abandonnee` ; abandon, et clôture d'un dossier non entièrement crédité, avec motif obligatoire (le reste des écarts passe `abandonne`). Le statut du dossier se déduit de celui de ses écarts après chaque avoir (`statut_depuis_ecarts`) ; les écarts gardent la machine d'état de §17.1 et leurs événements append-only (`TenantScope.transitionner_ecart`). Un avoir reçu avant la déclaration d'envoi est admis (`valide -> partiellement_credite | credite`).
- **Rôles** : préparation par le système ou le fondateur ; validation par le fondateur seul ; déclaration d'envoi, d'avoir, de contestation, clôture, abandon par le client (`declarer_recouvrement`) ou le fondateur.
- **Stockage** : contenu complet (lignes, relances, avoirs, commissions, historique) dans `reclamations.contenu` via un modèle `DossierReclamation` qui étend `Reclamation` (aucune table ajoutée). Écart né d'un constat : identifiant stable `eca_<sha256(client, constat)>` ; un écart déjà repris dans un dossier non abandonné n'est jamais redemandé.

## D-601 — Dossier de demande d'avoir rédigé pour le client

- **Choix** : texte et PDF (ReportLab) à la première personne du pluriel du client, objet « Demande d'avoir — factures n° … », tableau facture / MRN / composante / montant refacturé / montant de référence / écart (« écart constaté entre documents »), pièces (document, page, valeur lue, calcul), signature à compléter, avertissement §3.4 en fin de texte et au pied de chaque page. Montants refacturé et de référence lus dans `attendu`/`constate` du résultat de contrôle, à défaut dans les preuves. Toute phrase d'un libellé de constat qui cite le prestataire est retirée. Le texte passe `assert_clean`.
- **Total** : « Total des écarts constatés entre documents » = Σ des écarts certains validés ; les écarts « à vérifier » cochés par le client sont listés à part avec la mention « à confirmer » et un total distinct (lecture prudente du §17.3 point 5).
- **PDF** : déposé dans le coffre chiffré du client (`pdf_sha256`), cité en pièce du brouillon `reclamation_dossier`.

## D-602 — Relances au client, J+15 / J+30 / J+45

- **Choix** : à la déclaration d'envoi, relances planifiées à J+15, J+30, J+45 (`reglages["relances_jours"]`) ; chaque relance échue devient un brouillon `relance` **adressé au client** (contacts du client), qui lui suggère de relancer lui-même son transitaire ou de transmettre l'avoir. Le produit n'écrit jamais au transitaire. Les relances planifiées sont annulées quand le dossier est crédité, clos ou abandonné. Le §17.1 suggère 30/60/90 jours : la consigne d'exploitation (15/30/45) l'emporte, réglable par client.

## D-603 — Journal des agents en JSONL

- **Choix** : un fichier JSONL par jour sous `<data_dir>/journal_agents/` (0600), une ligne par événement, résumé des paramètres (identifiants courts gardés, texte libre remplacé par longueur + empreinte).
- **Pourquoi** : pas de table nouvelle (un concurrent modifie le schéma ; le test d'isolation énumère les tables client) ; journal opérationnel, pas une donnée client ; rotation et purge par fichier. **Écarté** : table `journal_agents` (à reconsidérer si le tableau de bord doit l'interroger).
- **Limite** : le journal n'est pas chaîné comme `audit_log` ; les décisions qui comptent (brouillons, approbations, alertes) restent tracées dans l'audit et la file sortante.

## D-604 — Agents : proposer seulement, liste blanche d'outils, client fixé par le contexte

- **Choix** : `Agent.outils` (liste blanche) + `Agent.appeler` (validation des paramètres par leurs annotations, refus journalisé) ; le client est celui du job et n'est jamais un paramètre d'outil ; acteur `systeme:agent:<nom>`. Écritures possibles : brouillon sortant, alerte, demande de job (`traiter_lot`, `preparer_reclamation`), instantanés de veille. Test d'architecture : les modules d'agents n'accèdent ni à la base, ni à la file, ni à l'envoi directement.
- **Courriels** : destinataires imposés (contacts du client) — un agent ne peut pas exfiltrer vers une adresse de son choix.

## D-605 — Données entrantes citées dans un brouillon

- **Choix** : nouvelle clé `donnees_entrantes` ajoutée aux clés exclues du contrôle de formulation de la file sortante (`outbox.service._CLES_NON_TEXTE`) : une question de client ou un titre de page officielle cités ne sont pas « notre » texte et ne doivent pas bloquer l'approbation ; le corps rédigé, lui, reste contrôlé. Correctif rétrocompatible.

## D-606 — Modèle de langage des agents

- **Choix** : `agents.llm.RedacteurLLM` réutilise réglages, tarifs (`extract.llm.cout_eur`), repli serveur en cas de refus et registre de coûts (`RegistreCoutsDB`) de l'extracteur ; plafond mensuel vérifié avant l'appel (`etat_plafond`). Schéma fermé `{"texte"}`, aucun outil, faits produits par le code séparés du bloc `<donnees_non_fiables>` (balises neutralisées dans la donnée). Sortie retenue seulement si `texte_acceptable` (formulations interdites, conservation des nombres et des références, pas d'affirmation de conformité absente des faits) ; `PHRASE_RENVOI` et l'avertissement sont rajoutés s'ils manquent. Seul `questions_clients` l'utilise ; les autres agents sont déterministes.

## D-607 — Questions des clients

- **Choix** : recherche déterministe (mots et références communs, pluriel simple) dans les constats **publiés** du client ; détection des sujets réglementaires par motifs (tarif, classement, origine, préférence, valeur en douane, taux applicable, légalité, remboursement, rectification, régime, MACF…) -> `PHRASE_RENVOI` ; détection des tentatives de consigne -> alerte `question_client_instruction`, sans autre effet. Réponse toujours en brouillon.

## D-608 — Veille réglementaire

- **Choix** : sources officielles reprises des briefs `docs/recherche`, limitées à la liste blanche (six domaines) ; deux compléments officiels pour le MACF (page de la Commission, règlement 2023/956 sur EUR-Lex) car le brief cite une autorité nationale hors liste. Empreinte du texte visible normalisé (scripts, balises et espaces retirés) ; redirections vérifiées une à une, jamais suivies hors liste ; réseau seulement si `CONTROLDONE_VEILLE_RESEAU=1`. Note `note_veille` (nouveau type d'action sortante, rétrocompatible), plateforme, jamais publiée ; sans réseau : « non vérifié ».
- **Limite** : une page dynamique peut changer d'empreinte sans changement de fond (faux positifs « modifié » : à relire).

## D-609 — Planificateur des agents

- **Choix** : `python -m controldone.agents.planificateur` met en file un job `agent` par agent et par client actif (veille : un seul), clé `agent:<nom>:<client|plateforme>:<période>` (heure pour `accueil`/`controle`, jour pour `litiges`/`facturation`, semaine ISO pour `veille`) ; `questions_clients` n'est pas planifié (sur événement). Le worker charge les handlers d'exploitation (`agent`, `preparer_reclamation`, `controle_avant_paiement`, `referentiel_recalculer`) — ajout de quelques lignes à `jobs.worker.main`. Liste des clients actifs : nouvelle fonction `storage.clients.clients_actifs` (identifiants seulement).

## D-610 — Facturation proposée

- **Choix** : diagnostic une fois par client (390 EUR HT par défaut) dès le premier lot traité ; abonnement mensuel (99 EUR HT par défaut) ; commission par avoir (taux de l'offre, `reglages["commission_taux"]`, 20 % par défaut ; base §17.4 = crédits imputés sur des écarts dont le constat est validé au moment de l'imputation ; `Decimal`, arrondi au centime demi supérieur). Brouillons `facture_emise` (lignes, total HT ; TVA et numérotation laissées à la facturation de niveau 3). Clé de la commission `commission:<client>:<avoir>` partagée entre le service des litiges et l'agent (filet de sécurité).

## D-611 — Préparation des dossiers par job

- **Choix** : l'agent `litiges` ne prépare pas lui-même un dossier (ce serait une écriture métier) : il demande le job `preparer_reclamation` (clé par client, transitaire et jour), exécuté par le worker avec l'acteur système ; le dossier reste un brouillon que le fondateur valide.

## D-612 — Périmètre pour un acteur quelconque

- **Choix** : `controldone.perimetre.perimetre(db, client, acteur, motif=…)` ouvre `OperatorScope.client` (accès tracé avec motif) pour le fondateur et `Database.tenant` pour les autres rôles ; utilisé par les litiges et les outils des agents. Les propositions sortantes (transaction propre) sont toujours faites hors d'un périmètre en écriture (verrou d'écrivain SQLite).

## D-620 — Référentiel : clé de transitaire

- **Choix** : alias public si le transitaire figure dans `config/referentiel_alias_publics.yaml` (tenu par le fondateur), sinon `T-` + HMAC-SHA256 tronqué à 12 hexadécimaux sur la TVA normalisée (à défaut le nom normalisé) avec un sel secret (`CONTROLDONE_REFERENTIEL_SEL`, sinon dérivé de la clé maîtresse). **Écarté** : SHA-256 sans sel (recalculable par quiconque connaît la TVA).

## D-621 — Référentiel : k-anonymat et arrondis

- **Choix** : publication d'un agrégat seulement à ≥ 5 clients distincts et ≥ 10 dossiers, et d'une statistique de prix seulement si elle-même atteint ces seuils ; prix (quartiles, rang le plus proche) arrondis à 5 EUR, taux au pas de 5 points, effectifs en tranches ; agrégats supprimés seulement comptés.

## D-622 — Référentiel : flux

- **Choix** : flux = groupe de pays d'origine × régime de déclaration (H1 `standard` / H7 `petits_envois`) × famille d'Incoterm × mois. Le « mode de transport » n'est pas extrait par le modèle de données actuel : le régime le remplace ; à ajouter quand un champ sourcé existera.

## D-623 — Référentiel : données validées et opt-out

- **Choix** : seuls les dossiers dont aucun constat n'est encore `propose` entrent dans le calcul ; un dossier « avec écart » a au moins un constat `ecart_certain` validé. Opt-out contractuel par `reglages["referentiel_opt_out"]`, appliqué au recalcul suivant (recalcul complet, sans état). Job `referentiel_recalculer` ; export JSON + CSV sous `<data_dir>/referentiel/`.

## D-630 — Connecteurs entrants

- **Choix** : protocole `ConnecteurEntrant` (`relever() -> list[Depot]`, `acquitter(depot, resultat)` facultatif) ; intégration commune `integrer_depot` (réception §7.1/§20.3 de l'ingestion, coffre chiffré, `Lot` + `Fichier`, job `traiter_lot` avec la clé `traiter_lot:<client>:<lot>`). Idempotence : sha256 (§7.1) — un dépôt sans fichier nouveau ne crée pas de lot — et `Message-ID` (conservé dans `lots.resume`). Une erreur d'un connecteur n'arrête pas les autres. Configuration dans `reglages["connecteurs"]`, secrets par nom de variable d'environnement.
- **Dossier surveillé** : interrogation, fichier pris s'il est stable (même taille et même date qu'au relevé précédent, ou inchangé depuis `stabilite_s`), fichiers cachés et temporaires ignorés, archivage dans `_archive/AAAAMMJJ/` sans écrasement.
- **IMAP** : `imaplib.IMAP4_SSL` avec contexte TLS par défaut, `UNSEEN` + `BODY.PEEK[]`, expéditeurs autorisés `reglages["expediteurs_autorises"]` ; sinon quarantaine (copie dans un dossier dédié, marqué lu), alerte au fondateur avec le seul domaine de l'expéditeur.

## D-631 — Plateforme agréée partenaire : contrôle avant paiement

- **Choix** : interface `ClientPA` (lecture des factures mises à disposition du client par **sa** PA) et bouchon `ClientPAFictif` ; chaque facture devient un lot (canal `api`) et un job `controle_avant_paiement` (traitement puis, s'il y a des écarts certains recouvrables non rejetés, brouillon `statut_litige_pa` proposant au **client** le statut « en litige » avec le motif chiffré). **ControlDOne n'est pas une plateforme agréée** (SPEC §21.2) : il ne transmet aucun statut ; le client décide et l'applique dans sa PA. « Refusée » n'est jamais proposé (réservé aux motifs de la norme, `docs/recherche/einvoice.md`).
- **Limite** : la liste des statuts de cycle de vie (dont « en litige ») vient de sources non officielles du brief ; à confirmer sur XP Z12-012 avant tout branchement réel.

# Web, API, MCP

Numérotation D-500 et suivantes. Code : `src/controldone/web/`, `src/controldone/api/`, `src/controldone/services/`,
`src/controldone/mcp_server.py` ; documentation : `docs/API.md`, `docs/MCP.md` ; tests : `tests/web/`.

## D-500 — Couche de services commune

- **Choix** : `controldone.services` porte la logique partagée par l'interface web, l'API REST et le serveur MCP (dépôt, lectures, décisions du fondateur, publication, recouvrement, administration, base de démonstration) ; aucune requête SQL hors de `storage` (test d'architecture inchangé). Les routes ne font que lire le formulaire, ouvrir le bon périmètre et rendre.
- **Client** : toujours celui de l'acteur authentifié (session ou clé d'API), jamais un paramètre. Le fondateur désigne un client dans l'URL (`/admin/clients/<id>/…`), mais chaque ouverture passe par `OperatorScope.client` avec un motif (audit `acces_admin`). Une page de dossier = un accès tracé : vignettes et extraits de preuve y sont intégrés (`data:` PNG) plutôt que servis par des requêtes séparées qui multiplieraient les entrées d'audit.
- **SQLite** : un périmètre ouvert par `op.client` tient le verrou d'écriture ; les appels qui ouvrent leur propre transaction (file des tâches, file des sorties, comptes) sont faits après la sortie du bloc (sinon attente de 30 s).

## D-501 — Rendu serveur, CSS maison, CSP stricte

- **Choix** : Jinja2 (échappement automatique, `StrictUndefined`), une feuille `static/app.css` et un petit `static/app.js` facultatif ; aucune ressource externe, aucun script ni style en ligne (`Content-Security-Policy: default-src 'self'; img-src 'self' data:; …`) : les jauges utilisent des classes de largeur (`w-0` … `w-100`) plutôt qu'un attribut `style`. Pages lisibles sans JavaScript (rafraîchissement d'un lot par `<meta refresh>`), imprimables (`@media print`), adaptées au téléphone.
- **Documentation de l'API** : `/api/v1/docs` est rendue par le serveur à partir du schéma OpenAPI (Swagger UI et ReDoc chargent des scripts depuis un CDN : écartés).
- **Fichiers déposés** : jamais rendus ; téléchargement en pièce jointe, `application/octet-stream` (sauf PDF), `nosniff`. Le rapport HTML (gabarit maison, sans script) peut s'afficher sous `default-src 'none'; style-src 'unsafe-inline'; img-src data:`.

## D-502 — Connexion en deux étapes, session, CSRF

- **Choix** : `auth.service` gagne `verifier_mot_de_passe_compte`, `verifier_second_facteur` et `acteur_client` (ajouts ; `authentifier` inchangée). Après le mot de passe du fondateur, un jeton signé de 5 minutes (cookie `cd_2fa`) porte seulement l'identifiant ; la session n'est émise qu'avec le code TOTP (anti-rejeu existant). Limitation : 10 tentatives / 5 min par IP, 5 par compte (et par compte pour le second facteur).
- **CSRF** : jeton `auth.jetons.jeton_csrf` lié à la session sur chaque formulaire POST ; avant connexion, lié à un identifiant de pré-session (cookie `HttpOnly`). Messages flash dans un cookie signé de 60 s (jamais un secret : mot de passe provisoire et clé d'API sont affichés dans la réponse même, une seule fois).
- **Cookies** : `parametres_cookie` (production : `__Host-`, `Secure`, `SameSite=Strict`) ; HSTS si HTTPS déclaré (`--https`) ou schéma `https`.

## D-503 — Limites de dépôt

- **Choix** : lecture bornée de chaque fichier transmis (au-delà de 50 Mo, le contenu n'est pas conservé : métadonnées et motif `trop_gros` seulement), refus global au-delà de 500 Mo par dépôt, puis `ingest.reception.recevoir_octets` (archives, types, doublons). Un intergiciel ASGI coupe tout corps au-delà de 2 Mo (516 Mo pour les chemins de dépôt), `Content-Length` absent ou mensonger compris (413). Un dépôt sans fichier exploitable donne un lot `en_erreur` sans tâche.

## D-504 — Corrections et recontrôle

- **Choix** : table append-only `corrections` (`CorrectionValeur`, ajout de schéma rétrocompatible) ; `TenantScope.appliquer_correction` remplace la feuille par une `ValeurSourcee` `saisie_humaine` (confiance 1,0, `remplace` = ancienne valeur), conserve l'ancienne valeur complète dans la correction, incrémente `Dossier.version` ; le job `recontroler_dossier` relance les contrôles purs sur l'instantané en base (grilles validées, entités, transitaires, autres dossiers du client), sans relire les fichiers. Confirmer une valeur douteuse = la ressaisir à l'identique.
- **Versions** : les résultats et constats d'une version antérieure restent en base ; les vues ne montrent que ceux de la version courante. Correctif de `enregistrer_resultats` : la version du dossier est mise à jour sur un résultat ou un constat existant ; la validation déjà donnée est conservée **seulement** si le niveau et le montant sont inchangés, sinon le constat est de nouveau proposé.
- **Limite** : un recontrôle déclenché par une autre correction peut faire revenir en « écart certain » un constat rétrogradé (D-505) : il repasse alors en « proposé » et doit être revalidé.

## D-505 — Décisions du fondateur sur un constat (§7.7)

- **Choix** : valider (publie ; un constat `recouvrable` positif ouvre l'écart à recouvrer, identifiant `litiges.id_ecart`), rejeter (motif obligatoire), rétrograder un écart certain en « à vérifier » (motif obligatoire ; nouvelle raison `retrograde_par_fondateur`, ajout d'énumération rétrocompatible ; le constat reste proposé). **Aucune route de promotion** : un « à vérifier » ne devient « écart certain » que par recontrôle après correction ou confirmation de la valeur. `TenantScope.retrograder_constat` exige `valider_constat`.
- **File de validation** : constats proposés de tous les clients (ordre §7.7 : écarts certains par montant décroissant, à vérifier, renvois), avec les deux valeurs, la tolérance et les extraits de page ; actions sortantes en brouillon (approuver, refuser avec motif, corriger puis approuver) ; points d'attention (documents non reconnus, rattachements faibles).

## D-506 — Publication et mise à disposition

- **Choix** : « Publier le rapport » reconstitue depuis la base les `ResultatDossier` du client en retirant tout constat non validé (statut global recalculé sur les seuls constats validés), génère HTML/PDF/JSON par `rapport.generer_rapport` (garde-fous sur le texte visible), range les fichiers chiffrés dans le coffre du client et propose une action `rapport_publication`. Approuver une action `rapport_publication` ou `reclamation_dossier` l'« envoie » aussitôt par `ExpediteurFichier` : c'est la mise à disposition dans l'espace du client (un rôle client ne voit que les actions `envoye` de son client). Rien n'est jamais envoyé à un transitaire. Aucune table ajoutée : les références des pièces sont dans le contenu de l'action.
- **Dossier de réclamation** : délégué à `controldone.litiges.ServiceLitiges` (D-600, D-601) — le bouton du fondateur prépare puis valide le dossier, et le brouillon `reclamation_dossier` attend l'approbation. Le registre du client (`/espace/recouvrement`, API `/litiges`) agit au niveau des écarts (§17.1 : réclamation envoyée, avoir reçu) ; le statut d'un dossier de demande d'avoir se recalcule depuis ses écarts au prochain avoir traité par le service des litiges.

## D-507 — Clés d'API dans le périmètre client

- **Choix** : un acteur issu d'une clé d'API (`api:<clé>`) n'est membre d'aucun client ; `TenantScope` vérifie alors que la clé appartient au client, n'est pas révoquée et porte le même rôle (correctif minimal, la vérification d'appartenance des comptes est inchangée). Erreur d'accès indistincte (`404 {"detail": "introuvable"}`) ; `403` seulement pour une action interdite au rôle de la clé (ex. dépôt avec une clé lecteur).
- **Factures électroniques** (`POST /api/v1/einvoices`) : Factur-X (PDF portant le XML embarqué), UBL ou CII reconnus par signature ; dépôt d'un lot `api` marqué `avant_paiement` puis `traiter_lot`. Le branchement à une plateforme agréée et la proposition de statut « en litige » relèvent de `controldone.connecteurs` (D-631).

## D-508 — Serveur MCP

- **Choix** : SDK installé en version 2 (`mcp.server.mcpserver.MCPServer` ; `mcp.server.fastmcp` n'existe plus), transport stdio ; clé d'API dans `CONTROLDONE_MCP_API_KEY` ; fonctions des outils dans `OutilsControldone` (testables sans transport). Descriptions et réponses : écarts factuels, pas un avis juridique ; textes des documents renvoyés comme données (`donnees_documents`). Dépôt depuis un chemin local : liens symboliques refusés, 500 fichiers au plus, limites de dépôt, répertoire restreint par `CONTROLDONE_MCP_RACINE`.

## D-509 — Démonstration

- **Choix** : `controldone init-demo` crée le compte fondateur (mot de passe et secret TOTP affichés une fois, stockés haché/chiffré), deux clients **fictifs** (`reglages.demo` → bandeau « DONNÉES FICTIVES » sur chaque page), leurs comptes, entités, transitaires et grilles validées, puis dépose les dossiers de `controldone.demo` par le service de dépôt et exécute le vrai worker. Pour illustrer la publication : écarts certains du premier client validés, rapport publié, dossier de réclamation en attente d'approbation, une réclamation déclarée envoyée ; tout reste à valider pour le second. `controldone serve` lance un worker dans un fil d'exécution (démonstration ; en production : `--sans-worker` et `python -m controldone.jobs.worker`). `make serve-demo` utilise `var/demo_web/`.

## D-901 — Niveaux 3 et 4 lancés pendant la mise au point du niveau 1

- **Choix** : le moteur, le banc et l'exploitation tournent de bout en bout ; la mise au point de la précision (seuil 0,97) se fait en parallèle par deux agents dédiés. Les niveaux 3 et 4 (facturation, finance, site, documents juridiques, prospection) ne modifient pas le moteur et ont été répartis entre sous-agents à ce moment.
- **Garde-fou** : le niveau 1 n'est déclaré « vert » qu'après la mesure finale sur le corpus tenu à l'écart (voir rapport du matin).

# Facturation

Numérotation D-1001 et suivantes. Détails : `docs/FACTURATION.md` ; code : `src/controldone/facturation/`.

## D-1001 — Offres configurables en YAML

- **Choix** : `config/offres.yaml` lu par `charger_offres` (diagnostic 390 EUR HT, commission 20 %, paliers 99 / 199 / 349 EUR HT pour 20 / 60 / 150 dossiers par mois — valeurs de départ à ajuster, coupon, TVA, numérotation, conditions de paiement, vendeur). L'identité du vendeur peut être remplacée par `CONTROLDONE_VENDEUR_<CHAMP>`. Les valeurs « À COMPLÉTER » donnent un PDF « NON VALABLE » et un refus d'émission en production.
- **Écarté** : une table d'offres en base. Le fondateur est seul, les offres changent peu, et un fichier versionné est relu en revue.
- **Lien** : les réglages par client existants (`diagnostic_prix_eur`, `abonnement_mensuel_eur`, `commission_taux`) restent ceux de l'agent `facturation` (D-610).

## D-1002 — Tables de facturation de niveau plateforme, immuables

- **Choix** : `factures`, `compteurs_factures`, `evenements_paiement`, `comptes_paiement`, `coupons_utilisations` et `statuts_factures_pa`, sans `TenantMixin`. `client_id` est une colonne simple, sans clé étrangère : les pièces comptables survivent à l'effacement d'un client (conservation de 10 ans, art. L123-22 C. com.), comme le journal d'audit.
- **Immuabilité** : `factures`, `evenements_paiement`, `coupons_utilisations` et `statuts_factures_pa` sont `AppendOnly`. `factures` est en plus protégée par des déclencheurs SQL (UPDATE et DELETE refusés). Les tables sont définies dans `storage/models_facturation.py`, importé par `controldone.storage` : `models.py` n'est pas modifié.

## D-1003 — Numérotation continue sous verrou

- **Choix** : une série par (entité légale, préfixe, année) : `F-AAAA-NNNN` pour les factures, `AV-AAAA-NNNN` pour les avoirs.
- **Mécanisme** : le compteur est lu `FOR UPDATE` dans une transaction d'écriture unique (`BEGIN IMMEDIATE` en SQLite). Dans cette même transaction, la facture est construite (XML validé, PDF), insérée, et le coupon est consommé. Tout échec annule la transaction : pas de trou. Une date d'émission antérieure à la dernière de la série est refusée. L'émission est idempotente par action sortante.
- **Test** : 8 fils × 5 émissions donnent la séquence 1..40.
- **Hypothèse** : une série séparée pour les avoirs (à confirmer avec l'expert-comptable).

## D-1004 — Brouillon d'abord, émission après approbation

- **Choix** : toute facture naît en brouillon `facture_emise`. Les clés d'idempotence sont partagées avec l'agent et les litiges. L'émission (numéro, Factur-X) n'a lieu que sur un brouillon `approuve` ou `corrige`, par le fondateur. Elle est déclenchée après l'approbation (`publication.mettre_a_disposition`, ajout rétrocompatible) ou par le bouton « Émettre et déposer ».
- **Erreurs** : une erreur d'émission après approbation est affichée au fondateur (`routes_admin._sortie` intercepte `ValueError`). La facture reste à émettre.
- **Corrections** : une correction passe par un avoir, dont le cumul est plafonné au HT d'origine et revérifié à l'émission.

## D-1005 — XML CII écrit à la main, validé par le XSD

- **Choix** : le XML CII D16B (profil EN 16931) est construit avec lxml, dans l'ordre du XSD Factur-X. Données françaises :
  - BT-23 `S1` ;
  - SIREN `0002` ;
  - adresses `0225` ;
  - notes `PMD`, `PMT`, `AAB`, `TXD`, `BAR=B2B`, `REG` ;
  - BT-8 = `5` si l'option sur les débits est retenue ;
  - `ShipToTradeParty` si l'adresse de livraison diffère.
- **Validation** : `facturx.xml_check_xsd` à chaque émission. Le PDF est produit par ReportLab (polices DejaVu embarquées), puis `facturx.generate_from_binary` (PDF/A-3, `en16931`).
- **Écarté** : `facturx.generate_xml`, dont l'API par dictionnaire de BT est moins lisible et moins testable ici.
- **Limite** : schématrons EN 16931 et BR-FR non exécutés (XSLT 2.0) ; seul un sous-ensemble de règles BR-FR est codé (`controles_reforme`).

## D-1006 — Coupon de lancement

- **Choix** : la remise de document (BG-20) est de 100 %. Le coupon exige un accord de publication signé (drapeau, signataire, date, référence du document). Quota global (3) et usage unique par client sont vérifiés à la création du brouillon, puis revérifiés sous verrou à l'émission. La consommation est append-only et cite le consentement.
- **Hypothèse fiscale** : un service rendu contre un droit de publication peut être un échange imposable. À faire valider avant le premier usage.

## D-1007 — Stripe en mode test, bouchon par défaut

- **Choix** : `fournisseur_depuis_env` renvoie `PaiementStripe` si `STRIPE_SECRET_KEY` est présent, sinon `PaiementBouchon`.
- **Clés** : une clé `sk_live_` n'est acceptée qu'avec `CONTROLDONE_ENV=prod` et `STRIPE_LIVE_OK=1`. Le message d'erreur ne cite jamais la clé.
- **Bouchon** : il signe ses événements au format Stripe. Ils passent par le même `stripe.Webhook.construct_event` que les vrais.
- **Facture légale** : c'est toujours la facture Factur-X. Stripe encaisse seulement le TTC calculé par notre code, sans Stripe Tax.
- **Webhooks** : `POST /webhooks/stripe`, public, signature obligatoire, idempotence par identifiant d'événement. Les effets (compte, brouillon du mois « déjà payé », alerte d'échec) sont idempotents.
- **Tests** : le client Stripe est simulé, aucun appel réseau.

## D-1008 — Plateforme agréée du fondateur : interface et bouchon

- **Choix** : protocole `PlateformeAgreee` (`deposer_facture`, `statut`, `recevoir_statuts`). Bouchon `PlateformeAgreeeBouchon` dans `var/pa_bouchon/`.
- **Dépôt** : `ExpediteurFacture` dépose la facture comme expéditeur de la file sortante. Il ne fait aucune écriture en base pendant l'envoi : la file tient le verrou d'écrivain SQLite. Le statut 200 est enregistré après l'envoi.
- **Positionnement** : ControlDOne n'est pas une plateforme agréée et ne le prétend pas. La liste complète des statuts reste une hypothèse (D-631).

## D-1009 — Contrôle avant paiement par l'API

- **Choix** : `POST /api/v1/einvoices` met aussi en file `controle_avant_paiement`, avec la clé `controle_avant_paiement:<client>:api:<lot>`. C'est le même chemin que le connecteur PA (D-631). Le numéro et l'échéance sont lus dans le XML comme des données : analyseur sans entités, sans DTD, sans réseau ; Factur-X via `facturx.get_xml_from_pdf`.
- **Worker intégré** : le worker de `controldone serve` charge aussi `connecteurs.jobs`.
- **Test** : un test de bout en bout couvre la route, la file, le worker et le brouillon `statut_litige_pa` adressé au client.

## D-1010 — Suivi financier

- **Définitions** :
  - CA HT = factures − avoirs, à la date d'émission ;
  - encaissé = événements de paiement réussis ;
  - coût IA = `ai_usage`, par client, mois et dossier (lecture transversale journalisée `lire_couts_ia`) ;
  - marge brute = CA HT − coût IA.
- **Implémentation** : fonction pure `calculer_marges`. Export CSV au format tableur français (`;`, virgule décimale, BOM), avec neutralisation des formules.
- **Hypothèse** : hébergement et frais Stripe non ventilés par client.

## D-1011 — Page « Finances »

- **Choix** : routeur `web/routes_finances.py` (`/admin/finances`, fondateur avec second facteur ; un client reçoit 404). Il reprend les gabarits et le CSS existants. Lien « Finances » ajouté au menu du fondateur.
- **Contenu** : formulaires de brouillon (diagnostic avec coupon et consentement, abonnement, commission), émission, avoir, lien de paiement, relevé des statuts PA, paiement simulé du bouchon. Le service est construit par `facturation.service_pour(plateforme)` et peut être injecté pour les tests.

## D-1012 — Données de facturation de l'acheteur

- **Choix** : `reglages["facturation"]` du client : SIREN, TVA, adresse, courriel, adresse électronique (par défaut le SIREN), adresse de livraison si elle diffère. À défaut, la raison sociale du client et le premier contact. Un instantané est figé dans la facture émise.
- **Limite** : les champs manquants (SIREN de l'acheteur…) n'empêchent pas l'émission : ils sont listés dans `contenu.controles_reforme`, à corriger avant le passage par une PA (obligatoire au plus tard le 1er septembre 2027).

# Mise au point : précision

## D-701 — Relevé ou facture partagé entre dossiers : chaque ligne jugée une fois, dans le bon dossier

- **Constat** : un relevé (facture mensuelle, plusieurs MRN) appartient à plusieurs dossiers (D-202). Les contrôles D4, D9 (et C6) comparaient chaque ligne de FAF ou de lignes supplémentaires à la déclaration du dossier courant, quel que soit le MRN cité par la ligne (220 « écarts certains » faux sur le banc de développement).
- **Choix** : une ligne de prestation qui cite le MRN d'une déclaration absente du dossier mais présente dans un autre dossier contenant la même facture relève de cet autre dossier (`ligne_hors_dossier`). Elle n'est évaluée ni par D2–D9, ni par C6. Une ligne sans MRN d'une facture partagée est jugée dans le dossier « principal », c'est-à-dire celui de plus petit identifiant parmi les dossiers qui la contiennent. Les contrôles de niveau facture (D1, C7, C8) ne s'exécutent que dans ce dossier principal. Ailleurs, ils rendent `non_applicable` (`couvert_par_autre_controle`).
- **Assiette et articles par ligne** (§13 D4 et D9, §12.2) : `declarations_de_ligne` renvoie la déclaration dont la ligne cite le MRN. À défaut, elle renvoie les déclarations couvertes par la facture. Elle renvoie une liste vide dans deux cas : le MRN de la ligne est inconnu sur une facture multi-MRN, ou une ligne non ventilée porte sur une facture qui cite aussi des MRN hors du dossier. Le FAF se calcule sur les débours de ce seul MRN, toutes factures du dossier confondues (une facture de débours et une facture de prestations peuvent être séparées). Le nombre d'articles de D9 est celui de cette déclaration. Sans déclaration retenue, D4 calcule l'assiette sur les débours de la facture elle-même (même MRN si la ligne en cite un), sans correction C.
- **Lecture de la grille** retenue (et vérifiée sur les factures correctement établies du banc) : le pourcentage, le minimum et le maximum s'appliquent **par déclaration** ; `inclus` est un nombre d'articles par déclaration.

## D-702 — Assiette « débours hors TVA » quand une taxe de la déclaration n'est pas ventilée

- Quand une ligne de taxation de catégorie inconnue (code non libellé) rend les composantes indisponibles (D-201), l'excédent hors TVA reste calculable si la TVA de chaque déclaration de l'unité est autoliquidée et qu'aucune TVA n'est refacturée. Il est alors égal à l'excédent total. Dans les autres cas, il n'est pas calculable (`None`).

## D-703 — D3, D4, D6, D7 : montant net des avoirs déjà reçus

- §8.6 : le montant recouvrable est net des avoirs déjà imputés. Une ligne d'avoir du dossier, de même nature que la ligne facturée, est déduite de l'écart tarifaire. L'avoir doit citer la facture (`ref_compatibles`), ou à défaut le MRN de la ligne ; si la ligne d'avoir cite un MRN, ce doit être le même. Chaque ligne d'avoir n'est imputée qu'à une seule ligne : la première ligne compatible de la facture. Le constat porte `montant_brut` (écart avant avoir), cite l'avoir et le mentionne dans le libellé. Si l'avoir couvre l'écart, le résultat est `conforme`.

## D-704 — Rapprochement d'une ligne « autre prestation »

- `autre_prestation` est la nature fourre-tout (« tout le reste », §5.3.3) : elle n'identifie pas un poste. Une telle ligne est rapprochée par son libellé seulement. Sans libellé reconnu, elle est « hors grille » (D2) et n'est plus comparée au seul poste de cette nature (D3).

## D-705 — Composante non vérifiable quand le total à payer contient des lignes non lues

- Quand la règle de complétude de §12.1 s'applique, le montant non retrouvé est `manquant = total_a_payer − Σ lignes lues`. C'est le cas si `total_a_payer` dépasse la somme lue, ou si une ligne est illisible. Un excédent de composante (C1, C2, C4) compris entre la tolérance et `manquant + tolérance` est alors `non_verifiable` (`ecart_explicable_par_une_ligne_de_taxation_non_lue`), car une ligne de cette composante non extraite l'explique. C5 compare toujours le total.

## D-706 — D1 : ligne probablement non lue, acomptes

- **Ligne non lue** : les totaux imprimés peuvent se confirmer entre eux. Deux cas : le total des débours et le total HT dépassent la somme lue du même montant, ou bien, avec un taux de TVA unique sur les prestations, le total de TVA imprimé vaut le taux × la base HT imprimée et non le taux × la somme des lignes lues. L'écart positif vient alors d'une ligne non lue, pas d'une erreur d'addition : `non_verifiable` (`ligne_probablement_non_lue`), §8.5.1 conditions 4 et 6. Une erreur d'addition injectée sur un seul total reste détectée.
- **Acomptes** : un acompte est une déduction, qu'il soit imprimé en positif ou précédé d'un signe moins (valeur absolue).

## D-707 — C8 : un constat par numéro de TVA facturé et par dossier

- Une facture de débours et une facture de prestations adressées au même numéro de TVA, différent de celui de l'importateur, constituent un seul fait. Elles donnent un seul constat qui cite les deux factures. Une facture partagée n'est jugée que dans le dossier principal (D-701).

## D-708 — Documents support co-localisés et lettre d'accompagnement

- Un document support n'est jamais comparé avec certitude : A10 et A11 sont `a_verifier`, et les conditions générales et lettres sont écartées (§5.3.3). Pour un support, `meme_fichier_source` et `meme_dossier_source` pèsent 3. Sans référence explicite, D-401 plafonne alors la force à `moyenne` : le lien est conservé, sans alerte P4 de rattachement faible. Les déclarations et factures gardent le poids 2 (P4 inchangé).
- Un support qui cite le numéro de la facture transitaire (lettre d'accompagnement) reçoit `ref_facture_citee` (forte).

## D-709 — C7 : références d'un relevé réparti, lecture OCR, regroupement

- **Correspondances admises** : les MRN et les références de transport des autres dossiers qui contiennent **la même facture** (relevé réparti). Un MRN d'un autre dossier sans lien avec la facture reste « sans correspondance ». C'est l'objet même de C7 (refacturation du MRN d'un autre dossier, F3/F4), ce qui revient sur D-205 pour ce point.
- **Lecture OCR** : une référence qui ne diffère d'une référence connue que par 1 ou 2 caractères n'est pas signalée, si l'une des deux est lue par OCR. Les confusions admises sont celles de §8.5.4 et, pour un identifiant, les lettres I/J/L, O/Q et U/V.
- **Sans déclaration dans le dossier** : les MRN cités ne sont pas jugés (P1 : contrôle dépendant d'un document manquant).
- **Regroupement** : les factures du dossier qui citent les mêmes références sans correspondance donnent un seul constat.

## D-710 — B2 : TVA autoliquidée signalée par la déclaration

- L'hypothèse « TVA autoliquidée exclue » de B2 traite comme autoliquidée une ligne de TVA dont le mode de paiement n'est pas lu, si la déclaration porte un indice d'autoliquidation : code 1008 et TVA, ou FR7 (§12.1). Cela corrige le constat faux de la démonstration, où le total à payer n'incluait pas la TVA autoliquidée.

## D-711 — C5 et forfait petits envois

- Le forfait refacturé sur une ligne distincte n'est retiré des deux côtés (G4 le compare) que si chaque déclaration de l'unité en porte une ligne lue. Sinon, le retirer de la seule facture créerait un écart égal au forfait.

## D-712 — Lectures de déclaration (extracteur déterministe)

- **Formulaire à cases lu par OCR** : quand le libellé de case suivant est reconnu mais que son numéro n'a pas été vu comme tel, un seul nombre de 1 ou 2 chiffres entre deux libellés de case est un numéro de case. Exemple : « 35 Masse brute (kg) 38 Masse nette (kg) ». La valeur est alors lue sous le libellé. `v_masse` refuse aussi « 38 » suivi d'un mot.
- **Tableau condensé** : quand la colonne St est vide, un montant à trois décimales en virgule décimale (« 929,527 ») est un montant suivi du chiffre de statut collé. Un montant dont la virgule a été lue « / » ou « | » (« 31/87 ») est relu avec la virgule. Ces deux réparations appliquent une pénalité de confiance de 0,15.

# Mise au point : rappel

Mesures sur le split `dev` (202 dossiers) : `bench/out/dev_r1` (avant) -> `bench/out/dev_rec_6` (après, avec les
travaux de précision menés en parallèle). Rappel global 68,6 % -> 80,5 % ; précision certain 100 % ; P1 9/9.

## D-801 — P1 : documents concernés ; mention « sans valeur commerciale »

- **Choix** : le constat P1 cite les documents restés sans contrepartie (factures commerciales exploitables, ou
  déclarations) et les documents non exploitables qui tiennent lieu du document manquant. Un constat sans document
  n'était ni vérifiable par le fondateur ni rattachable à une pièce.
- **Classement (§7.2, P2)** : une mention explicite du corps (« document sans valeur commerciale », « ceci n'est pas
  une facture », `P2_CORPS`) l'emporte sur l'intitulé « FACTURE » même quand un motif P2 a été lu à un niveau
  d'intitulé inférieur (« FACTURE - BON DE LIVRAISON ») ; le motif lu est conservé.

## D-802 — Fichier en double (§7.1) : copie rattachée au lot

- **Choix** : le fichier identique (sha256) n'est toujours pas retraité (mention `doublon_de_fichier` dans
  `non_lus`), mais le pipeline crée pour chaque document de l'original une **copie** (mêmes type, champs, identité ;
  pages du fichier en double ; `doublon_de` = document original). Le regroupement la place avec son original ; les
  contrôles l'excluent de leurs sommes (`documents_par_role`) ; F1 la signale (le banc accepte F1 pour E3). P4
  rend `non_applicable` (`couvert_par_autre_controle`) pour la copie (pas de second « rattachement faible »).
- **Limite** : un doublon d'un fichier reçu dans un **autre** lot (`deja_recus`) n'a pas d'original dans le lot :
  seule la mention subsiste.

## D-803 — A2 : aucune référence de facture citée (remplace la fin de D-107)

- **Choix** : §10 A2 dit « sinon constat ». Si la liste des documents produits a bien été lue — export structuré, ou
  au moins une autre référence lue (titre de transport, 1008…) — et qu'aucune référence de facture n'y figure :
  constat `a_verifier` (signal, liste des documents cités). Aucune référence lue sur une déclaration imprimée
  (la section a pu échapper à la lecture, H7 sans références) : `non_verifiable` comme avant.

## D-804 — Déclarations : références « référence + libellé » et séparateurs

- **Choix** : dans la section « Documents produits / références », une ligne dont la colonne des codes est perdue
  (OCR) « FAC/2026/0060-0  Facture commerciale » est lue avec un code déduit du libellé imprimé (facture commerciale
  -> N380, pro forma -> N325, connaissement -> N705, LTA -> N740 ; pénalité 0,10 ; valeur brute = libellé, ancrée).
  Un séparateur de colonne lu entre le code et la référence (« N380 | FAC/… », « 1008 | FR… ») est sauté.
- **Effet** : regroupement par référence citée et A2 sur les H1 scannées (32 déclarations dev sans aucune
  référence lue auparavant).

## D-805 — `ref_compatibles` : inclusion sur la forme `norm_ref` (§8.4)

- **Choix** : l'inclusion est testée sur la forme `norm_ref` (texte de §8.4 : « l'une contient l'autre et la plus
  courte a au moins 5 caractères ») **puis** sur la forme sans zéros de tête (comportement existant). « 0001-0 » (troncature
  de « FAC/2026/0001-0 ») était refusé car sa forme sans zéros (« 10 ») est trop courte.

## D-806 — Taux de référence BCE : alimentation et chargement par défaut

- **Choix** : `ref/taux_bce.csv` est alimenté depuis le fichier historique officiel de la BCE
  (`eurofxref-hist.zip`, données publiques réutilisables avec mention de la source) par
  `scripts/importer_taux_bce.py` (fonction `convertir_historique_bce`, format large -> `date,devise,devise_par_eur`,
  « N/A » ignorés), depuis le 2024-01-01. Le pipeline charge cette table par défaut (`table_par_defaut()`,
  `CONTROLDONE_REF_DIR` sinon `<dépôt>/ref`) quand `OptionsPipeline.taux_reference` n'est pas fourni. Usage
  inchangé (§8.7) : sens d'un taux non libellé et A7 ; jamais un montant.
- **Pourquoi** : la table était vide, A7 ne pouvait jamais s'exécuter (0/5). Écart des taux imprimés du corpus dev
  aux taux BCE : −21 % à +6 %, dans les bandes de A7.
- **À faire (exploitation)** : rafraîchir la table périodiquement (tâche hors ligne).

## D-807 — A6 : « même nombre » discriminant seulement

- **Choix** : A6 ne se déclenche que si la conversion (taux imprimé dans les deux sens, à défaut taux de référence)
  aurait déplacé le montant de plus de `T_VALEUR`. Pour 2,28 USD déclarés 2,04 EUR, conversion et non-conversion
  tombent toutes deux à moins d'une unité : rien ne permet de conclure (A5/A7 jugent).

## D-808 — E6 : écart relevé dans le dossier et crédité en partie

- **Choix** : outre les écarts « réclamés » du registre (D-306), E6 traite les constats `recouvrable` (C, D) du
  dossier que les avoirs du dossier créditent en partie (imputation §17.2) : un avoir reçu sur la facture montre que
  l'écart a été porté au transitaire ; le reste (> `T_DEBOURS`) est à relancer. Montant = reste ;
  `details.remplace_constat_id` = constat d'origine (le montant d'origine, déjà net des avoirs selon §8.6, ne doit
  pas être additionné).

## D-809 — E2 : comparaison par MRN cité ; facture sans ligne ; numéro illisible

- **Par MRN** : quand une ligne d'avoir cite un MRN que la facture d'origine cite aussi pour la même nature, le
  « montant facturé d'origine » du crédit est celui de ce MRN (145,73 de dédouanement crédités sur un MRN facturé
  85, alors que 2 × 85 sont facturés sur la facture). Sans MRN sur la ligne : comparaison par nature (inchangée).
- **Facture d'origine sans ligne lue** : `non_verifiable` (et non « 0,00 facturé », source de faux signaux).
- **Numéro illisible** : l'avoir cite une facture d'origine, l'unique facture du transitaire du dossier (même
  émetteur) a un numéro illisible : comparaison sur elle, raison `rattachement_faible`.

## D-810 — A15 : « contient une référence d'article »

- **Choix** : une désignation contient une référence d'article si elle cite une référence de la facture **ou** un
  mot de même forme (lettres -> A, chiffres -> 9, séparateurs conservés : « LA-1012-Z » ~ « LA-1012-M »). Une
  référence tronquée dans la désignation (« OS-2191- ») est retrouvée par `ref_compatibles` (§8.4). Un article sans
  désignation lisible -> `non_verifiable` (la référence cherchée peut y figurer).

## D-811 — H7 : ligne de forfait lue hors tableau

- **Choix** : en-tête du tableau des taxes illisible (OCR), la ligne « Droit forfaitaire petits envois N article(s)
  T EUR/art. M » est lue hors tableau, seulement si aucune ligne de forfait n'a été lue : présence, base et taux ;
  **pas le montant** (le reste du tableau a pu échapper à la lecture : un montant isolé faussait B2 et G4, mesuré).
  Sert G2, G3 et G6 (G6 4/5).

## D-812 — F3 : autre facture citant le MRN mais illisible

- **Choix** : une autre facture du client (autre dossier, numéro différent, fenêtre) cite le même MRN mais aucune
  de ses lignes n'a été lue. Si la facture du dossier est la plus récente, n'est pas annulée par un avoir et couvre
  seule le liquidé (quand il est connu ; sinon la complémentarité n'est pas exclue mais le signal reste à vérifier) :
  constat `a_verifier` (raisons `valeur_absente`, `controle_signal_seulement`), montant = ses débours. Jamais
  certain.

# Mise au point après le premier holdout

Première mesure sur le corpus tenu à l'écart (`bench/out/holdout_final_1`, holdout désormais « brûlé ») :
précision certain 0,9565 (44 VP / 2 FP). Causes générales corrigées ci-dessous, chacune avec un test sur des données
fictives ; aucun réglage propre à un dossier, un nom de fichier ou un nom fictif. Banc `dev` : `bench/out/dev_r2`
(avant) -> `bench/out/dev_r3` (après) : VP/FP certain 111/0 -> 114/0, rappel 80,5 % -> 81,3 %, rappel certain
71,5 % -> 73,6 %, bruit 1,41 -> 1,41 par dossier ; seuil bloquant passé. Un nouveau holdout sera généré pour la
mesure finale.

## D-902 — Famille C : garde de complétude de la lecture des lignes de taxation

- **Constat (holdout 1)** : une ligne « autre taxe » à taux spécifique (0,12 par LTR sur 623 LTR, code X01) n'a pas
  été extraite d'une déclaration condensée scannée ; une ligne de TVA mal lue rendait la somme lue **supérieure** au
  total à payer imprimé, si bien que la règle de complétude de §12.1 (total > somme) ne s'appliquait pas. C2 comparait
  1 170,71 (transitaire) à 1 095,95 (2 lignes lues) et produisait un écart certain faux de 74,76 EUR, alors que le
  total à payer (6 124,49) était lu à 0,83.
- **Choix** (§12.1, §8.5.1 conditions 3–4) : `reference_declaration` calcule `lecture_incomplete` :
  1. un total imprimé (`total_a_payer` ou `total_droits_taxes`) est lu avec une confiance ≥ `C_MIN_UTILE` et
     **aucun** total lu ne concorde, à `T_SOMME` près, avec la somme des lignes lues, TVA autoliquidée exclue ou
     incluse (mêmes hypothèses que B2, D-710) — dans un sens comme dans l'autre ;
  2. ou les lignes par article semblent incomplètes : un article attendu (articles lus, `nombre_articles`) sans
     aucune ligne, ou un article sans ligne de droits (ou de TVA) alors que d'autres articles en ont une.
  Les constats C1, C2, C4 de la déclaration sont alors au plus `a_verifier` (raison `valeur_absente`,
  `details.lecture_incomplete` = motif) ; C5 aussi quand son total liquidé est la somme des lignes (le total imprimé,
  quand la règle de complétude le retient, fait foi). Les règles existantes (composante `non_verifiable`, D-705)
  sont inchangées. « Différence pleinement expliquée » = concordance sous l'une des deux hypothèses de TVA
  autoliquidée.
- **Limite** : le motif 2 ne voit pas une ligne de droit spécifique manquante sur un article qui porte déjà ses
  lignes de droits et de TVA : c'est le motif 1 (total imprimé) ou l'extracteur (D-903) qui la couvre.

## D-903 — Déclarations condensées : sous-lignes de droit spécifique lues par OCR

- **Constat** : sur les déclarations condensées scannées (dev L2/L3 d1–d3 et holdout), l'OCR lit le code « X01 » en
  minuscule (« x01 ») ou le tronque (« x1 ») ; la sous-ligne était ignorée sans signal. Les codes `X..` sans libellé
  restaient de catégorie `inconnue` (toutes les composantes C indisponibles, même sur PDF natif L3).
- **Choix** : (a) un code de taxe dont la lettre est lue en minuscule est accepté et corrigé (pénalité 0,12) s'il
  contient au moins un chiffre lu tel quel et si la ligne porte un montant décimal (un débris « s00 » sans montant
  n'ouvre pas de ligne) ; (b) dans un tableau condensé, une sous-ligne sans code lisible mais avec un montant décimal
  dans la colonne des droits **et** un libellé de taxe (droit, taxe, accise, dumping, spécifique…) ou une base en
  quantité (« 980 LTR ») donne une ligne de taxation sans code, catégorie d'après le libellé seulement, toutes ses
  valeurs plafonnées à 0,85 (jamais valeur clé d'un écart certain ; avertissement `code_taxe_illisible`) ; (c) un
  code `X` + 2 chiffres sans libellé imprimé est classé `autre_taxe` (accises et taxes nationales).
- **Mesure** (`scripts/mesure_extraction.py --type declaration`, dev) : lignes de taxation absentes 649 -> 643,
  catégories fausses 5 -> 2 ; calibration inchangée (22 880 valeurs ≥ 0,90, 100 % exactes). Effet banc : deux
  écarts C1 certains de plus (codes X01 désormais classés), aucun constat certain nouveau faux.

## D-904 — Facture commerciale : total OCR sans séparateur décimal

- **Constat (holdout 1)** : `total_facture` lu « 4058121 » et « 2853745 » à 0,95 (OCR). Vérification : la devise est
  le JPY (0 décimale) et ces valeurs sont **exactes** (recoupées par la somme des lignes) ; la confiance 0,95 était
  donc légitime et n'a pas causé de faux certain. Sur le banc dev, aucune valeur ≥ 0,90 n'est fausse.
- **Choix (garde-fou explicite)** : pour une devise à décimales (ou inconnue), un total OCR ≥ 1000 lu sans
  séparateur décimal suivi du bon nombre de décimales est plafonné à 0,80, sauf recoupement arithmétique à la même
  échelle (somme des lignes, sous-total + pieds). Les devises sans décimales (JPY, KRW…) ne sont pas concernées.
  Le code existant plafonnait déjà ces cas (0,80 sans recoupement, 0,60 si incohérent) ; la règle est désormais
  écrite et testée. Calibration dev inchangée (9 111 valeurs ≥ 0,90, 100 % exactes).

## D-905 — Correcteur du banc : départage de l'appariement

- **Constat (holdout 1)** : l'erreur BX0037-E2 (contrôle principal B4, acceptés B4/A10, attendue `ecart_certain`)
  était appariée par la règle gloutonne à un constat A10 `a_verifier` du même document (son `finding_id` triait
  avant) ; le constat B4 `ecart_certain` restait non apparié et comptait comme FP certain.
- **Choix** : à écart de montant égal, on préfère (a) le constat dont le contrôle est le contrôle principal de
  l'erreur, puis (b) le niveau `ecart_certain`, puis `error_id`, `finding_id` (SPEC §19.4 règle 3 « départage »,
  `bench/score/README.md` §4). Règle du correcteur, valable pour tous les splits ; aucun effet sur les chiffres
  globaux de `dev_r2` (re-score identique). Re-score informatif de `holdout_final_1` : 45 VP / 1 FP, précision
  certain 0,9783 (l'ancien `metrics.md` est conservé en `metrics_scorer_v1.md`) ; rien d'autre n'a été réglé sur
  ce holdout.

## D-906 — A10, A11 : libellé quand les valeurs de la déclaration sont lues par article

- **Constat** : `controle_en_erreur controle=A11 … exception=ValueError` (dev BX0179, BX0232) : sans total de colis
  lu, les valeurs par article (plus nombreuses que les déclarations du couple) étaient passées à `_refs_dec`, dont
  le `zip(strict=True)` échouait à la rédaction du libellé. A10 (masse nette, toujours par article) avait le même
  défaut avec plusieurs déclarations.
- **Choix** : la page citée pour chaque déclaration (ou facture) est la première valeur lue de ce document ; plus
  d'exception. Les deux dossiers produisent désormais leur constat A11 `a_verifier`.
