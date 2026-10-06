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

- **Choix** : comparaison sur le texte en minuscules, sans accents, tirets ramenés à des espaces, avec variantes de pluriel et de féminin générées par mot (mots grammaticaux invariables). Conséquence assumée : « droit dû » bloque aussi « droit du » sans accent ; les gabarits évitent la tournure « droit du … ». *(Conséquence remplacée par D-1215 : seul le participe « dû » est variable ; « droit du tarif » n'est plus bloqué.)* Un constat dont le libellé ou la prochaine action contient une expression interdite reçoit `motif_blocage = formulation_interdite` (il part en file de validation, il n'est pas supprimé).

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

## D-907 — Correcteur : constats neutres évalués avant les pièges

- **Constat** (revue du banc `corpus_g2` dev) : dans `bench/score/core.py` `classer`, un constat non apparié était
  confronté aux pièges **avant** le test « neutre ». Un C5 sans montant, raison `doublon_composantes`, redondant
  d'un C1 apparié qui porte le montant (§8.6), était compté FP sur un piège C3 « TVA autoliquidée non refacturée »
  (C5 est équivalent de C3 dans l'Annexe A) ; idem pour l'occurrence miroir F3–F5.
- **Choix** : `_neutre` est évalué avant `_piege_pour`, pour tous les corpus et splits. Un constat neutre est par
  construction candidat d'une erreur réelle déjà appariée ; il n'accuse rien de plus et ne peut donc pas violer
  un piège. Un constat certain avec montant reste soumis aux pièges.
- **Vérification** : re-notation à l'identique (métriques inchangées octet pour octet hors identifiants de run) de
  `corpus` dev (`dev_ctl`), `corpus` holdout (`holdout_final_1`), `corpus_h2` holdout (`holdout2_final`) ;
  `corpus_g2` dev (`g2_dev_ctl`, vérité d'avant régénération) : 6 FP certains et 2 FP à vérifier deviennent
  neutres (C5 redondants ; un miroir F3), `precision_certain` 0,857 → 0,906.

# Généralisation à une mise en page inconnue

Constat : le jeu de démonstration (`src/controldone/demo`, famille de mise en page jamais vue des extracteurs)
traité par le moteur réel laissait toute la famille A `non_verifiable` (montant total, TVA importateur et articles
de la déclaration non lus ; noms de parties lus sur un bandeau ou un libellé voisin à 0,80–0,90) et DEMO-3 finissait
`a_verifier` sans constat. Ce statut était conforme à §18.2 (A4/A5 `non_verifiable` -> `a_verifier`, « contrôle
non réalisable ») : la fonction de statut n'est pas modifiée, ce sont les lectures qui sont corrigées. Règles
générales, sans référence aux chaînes du jeu de démonstration ; tests sur des PDF rendus par reportlab dans
plusieurs variantes (`tests/extract/test_mise_en_page_inconnue.py`), plus le jeu de démonstration traité par le
moteur réel (`tests/assembly/test_demo_moteur_reel.py`).

## D-950 — Déclaration : libellés génériques, codes marchandise par groupes, mode de paiement en lettres

- **Montant total facturé** : libellés ajoutés (« Montant facturé total », « Montant total de la facture »,
  « Total invoiced amount », « Total facturé »…). Le libellé générique « Montant facturé » / « Invoice amount » /
  « Amount invoiced » reste un libellé d'article ; imprimé dans l'**en-tête** (hors blocs et tableaux d'articles),
  **une seule fois** et **avant le premier article**, il donne `montant_total_facture`. Si les montants facturés
  par article sont tous lus et que leur somme ne lui est pas égale (au centime), il est plafonné à 0,80 (jamais
  valeur clé d'un écart certain). Sans article reconnu, il n'est pas retenu (ce pourrait être le montant d'un
  article dont le bloc n'a pas été lu).
- **Code marchandise imprimé par groupes** (« 8207 70 37 00 », « 7318 15 88 ») : 4 + 2 + 2 (+ 2) chiffres en
  mots rapprochés forment un code (lu tel quel, sans correction lettre/chiffre) ; reconnu dans les cellules des
  tableaux d'articles (attribution à la colonne « code », détection d'une ligne d'article) et après un libellé.
- **Mode de paiement en toutes lettres** (« Comptant », « Autoliquidation », « Deferred »…) dans la colonne MP :
  mot rattaché à la colonne, `paiement_normalise` d'après le libellé (mêmes motifs que la légende) ;
  « autoliquidation » ne s'applique qu'à une ligne de TVA.
- **Facture commerciale** : libellé de colis nu, seul dans son segment (« Packages   12 »), lu à droite seulement.

## D-951 — En-tête à deux colonnes : pavé borné par la colonne voisine

- **Constat** : pavé de partie à gauche, couples « libellé … valeur » à droite, interlignes différents : les lignes
  s'intercalent. Le pavé de l'importateur était fermé par le premier libellé de la colonne de droite (« Montant
  facturé ») ; le pavé acheteur prenait ce libellé (« Place ») comme nom, à 0,90.
- **Choix** : (a) facture commerciale (`pave`) : quand la ligne du libellé n'a rien à sa droite, une colonne de
  droite est reconnue si au moins deux lignes voisines (± 8 lignes) commencent toutes deux nettement à droite du
  pavé (au-delà du libellé + 0,05 et de son bord gauche + 0,15), alignées à ± 0,02 ; le pavé est borné à ce bord
  (positions x des mots), les lignes de cette colonne sont ignorées sans fermer le pavé. (b) Déclaration
  (`_dessous`, pavé de partie) : un libellé imprimé nettement à droite du pavé et séparé de son texte par un grand
  blanc borne le pavé au lieu de le fermer. (c) Le nom d'une partie lu dans un pavé ainsi borné (structure
  ambiguë) est plafonné à 0,80 au lieu de 0,90 ; un nom doit avoir trois lettres et ne pas être un bandeau ni un
  libellé « … : ».

## D-952 — Numéro de TVA collé à son libellé

« N° TVAFR15000100008 », « VATDE123456789 » (mise en page ou OCR) : le libellé collé (TVA, VAT, IVA, USt-IdNr, NIF,
précédé ou non de « N° ») est retiré seulement si le reste a la forme nationale **et**, pour une TVA française à
clé numérique, une clé juste ; sinon rien n'est lu. Commun aux lectures de TVA des extracteurs (`lire_tva_mots`)
et à la déclaration (`_tva`, pavé de partie).

## D-953 — Bandeaux, filigranes, en-têtes et pieds répétés : jamais un nom de partie

- **Constat** : `vendeur.nom` (facture commerciale, sans libellé « vendeur ») et `emetteur.nom` (facture du
  transitaire) étaient pris sur la première ligne de la page : le bandeau « DONNÉES FICTIVES — … », à 0,80–0,85.
- **Règle générale** (`lignes_bandeau`) : est un bandeau une ligne (i) dont le texte relève du vocabulaire des
  bandeaux et filigranes (« données fictives », « fictitious data », « document de démonstration / de test »,
  « specimen », « draft », « aucune valeur réelle »…) — un nom suivi de « (FICTIF) » n'en relève pas ; (ii) qui
  tient entièrement dans la marge haute ou basse de la page (3 %) ; (iii) sur un document de plusieurs pages,
  répétée sur **toutes** les pages (chiffres neutralisés) dans leur quart haut ou bas. Pour le nom de
  l'**émetteur** (vendeur sans libellé, transitaire), les lignes répétées du haut de page restent admises : c'est
  le papier à en-tête, où se lit précisément son nom ; les pieds répétés restent exclus.
- Ces lignes ne sont jamais lues comme nom de partie ni n'ouvrent un pavé ; sans autre candidat, le nom reste
  absent (mieux vaut absent que faux à haute confiance).

**Mesures** (avant -> après) : démonstration (moteur réel) : DEMO-1 C3 + D3 certains (inchangé), DEMO-2 B1 certain
+ A12 `a_verifier` sans montant (A12 était `non_verifiable`), DEMO-3 `a_verifier` sans constat -> `conforme` ;
contrôles `non_verifiable` par dossier : A1, A4, A9, A10, A11, A12, A13, A15 et P3 -> A9 seul (quantités non imprimées sur ces déclarations). Banc dev
(`dev_r4`) : identique à `dev_r3` (précision certain 100 %, rappel 81,3 %), `declaration.importateur.tva`
288 -> 290 exactes. Calibration (`scripts/mesure_extraction.py`, dev) : déclaration 22 882 valeurs ≥ 0,90, 100 %
exactes (22 880 avant) ; facture commerciale 9 111, 100 % (inchangé).

# Audit final : corrections du moteur

Corrections issues des audits A (moteur, constats F1–F14) et D (architecture, volet moteur). Chaque correction a un
test unitaire sur données fictives qui échoue avant et passe après. Banc dev mesuré après chaque groupe
(`bench/out/dev_fix_1` à `dev_fix_9`) ; référence `dev_r4`. Résultat final (`dev_fix_9`) : seuil bloquant PASSE,
précision certain 100 % (0 FP certain, 114 VP), rappel 81,3 % (inchangé), exactitude des montants 95,8 % -> 96,5 %,
bruit `a_verifier` 1,411 -> 1,381 par dossier, violations de pièges 40 -> 38 ; aucune formulation interdite.

## D-1201 — Contexte des contrôles en erreur : jamais « conforme » (audit A, F4)

- **Constat** : une exception dans `ControlContext.construire` donnait `resultats = []`, puis `conforme`.
- **Choix** : le pipeline produit un résultat `P1` `non_verifiable` (raison `erreur_interne`, unité `erreur`) ;
  `statut_global_depuis_resultats` rend `a_verifier` pour une liste vide et dès qu'un résultat porte la raison
  `erreur_interne` (P8 : « impossible de conclure » n'est jamais « conforme »).

## D-1202 — Exclusions des totaux : règle unique `constats_hors_totaux` (F1, F8)

- **E6** (§14) : le constat d'origine désigné par `details.remplace_constat_id` est exclu des totaux « recouvrable »
  (le reste porté par E6 le remplace). Le lien est publié dans `findings.json` (`constats[].remplace_constat_id`,
  champ optionnel : schéma `controldone.findings/1.1.0`, mineure).
- **F5** : un F5 qui porte le même écart (valeur absolue égale, document commun) qu'un A4/A5/A6 du dossier n'est
  compté qu'une fois dans « Écarts de valeur entre documents ».
- Les montants par constat sont inchangés (banc inchangé) ; seuls les agrégats du rapport (`rapport/vue.py`) changent.
  `findings_io.constats_hors_totaux(resultats)` est la règle à réutiliser par tout autre agrégateur (tableaux de bord
  de la plateforme, à brancher par l'équipe plateforme).

## D-1203 — Clé d'idempotence de l'étape 7 (F10)

- La clé `cle_controles` inclut désormais une empreinte du contexte : grilles (contenu), sous-ensemble
  `options.controles` (`*` = tous), table de taux de référence (contenu), entités, transitaires, paramètres petits
  envois. Un résultat mémorisé n'est jamais rejoué dans un autre contexte.

## D-1204 — Rejeu octet pour octet (F12)

- `execution.duree_s` reste dans `findings.json` (Annexe C) mais est **assimilé aux horodatages** exclus de la
  comparaison de rejeu (§6.2.12) : `findings_io.findings_json_rejeu` donne la forme comparable.
- L'année des références lisibles `D-AAAA-NNNNN` vient de la date de réception du lot (`Lot.recu_le`), plus de
  l'horloge au moment du traitement.

## D-1205 — Libellés bloqués : jamais publiés en JSON (F5) ; tableur sans `float` (F14)

- `report.json` et le `findings.json` du rapport remplacent le libellé et la prochaine action d'un constat
  `motif_blocage` par la même mention neutre que la vue HTML (`LIBELLE_RETENU`), puis vérifient tous les textes de
  constats (`FormulationInterdite` sinon), comme `verifier_textes` pour le HTML.
- Tableur : les montants sont passés en `Decimal` (openpyxl les écrit en nombre) ; plus de conversion `float`
  dans notre code.

## D-1206 — C5 avec une composante non évaluable : résidu seulement (F2)

- **Constat** : R2 ne neutralisait C5 que si C1, C2 et C3/C4 étaient tous évaluables ; sinon C5 gardait l'écart
  total, alors que les constats C2/C4 de la même unité portaient déjà une partie de cet écart (somme comptée deux
  fois).
- **Choix** : C5 ne porte que le **résidu** `écart_C5 − Σ montants des constats C1–C4 de l'unité` (« seul porteur
  du montant » non porté par les composantes, §12 C5 ; part TVA de C3 retirée de fait, §8.6). Résidu dans
  `T_DEBOURS` ou de signe opposé : `montant_en_jeu = None`. Dans les deux cas `montant_brut` = écart total et
  raison `doublon_composantes`.
- **Banc** : BX0055 C5 50 000,00 -> sans montant (composantes C2/C4 déjà portées).

## D-1207 — Ligne non ventilée d'une facture multi-MRN : comparaison sur la somme (F3)

- **Constat** : une allocation `prorata` du regroupement était prise pour une ventilation par C1–C5 : paire d'écarts
  +X / −X fictifs entre les deux déclarations.
- **Choix** : une allocation `prorata` désigne seulement les déclarations que la ligne couvre ; la ligne est
  comparée à la **somme** de ces déclarations (unité « facture × ensemble des déclarations », §12.2). Les allocations
  `prorata` restent dans le dossier : un constat sur cette unité garde la raison `allocation_prorata` (jamais
  certain, §8.5.1 condition 5). Parts au prorata arrondies demi vers le haut (§8.2) et reliquat d'arrondi affecté à la
  dernière part (`regroupement.repartir_prorata`).
- **Essai écarté** : reconnaître un MRN cité « à une confusion OCR près » pour élargir les déclarations couvertes
  ajoutait deux constats de bruit au banc (lectures de taxation incomplètes) sans gain : retiré.
- **Banc** : BX0130 (piège : Σ refacturé = Σ liquidé) C5 ±172,76 et C6 -> plus aucun constat C ; BX0168 C1 ±90,00
  -> aucun.

## D-1208 — Vote OCR des MRN déterministe (F6)

- À égalité de votes caractère par caractère, le caractère de la lecture la plus fréquente, puis l'ordre
  alphabétique (`consensus_lectures`) — jamais l'ordre d'itération d'un ensemble (aléa `PYTHONHASHSEED`).
  Vérifié : BX0041 identique pour `PYTHONHASHSEED` 0, 1, 2, 3, 7, 11.

## D-1209 — Tiret séparateur dans un montant (F13)

- Un tiret entouré d'espaces après un mot ou un nombre est un séparateur (« Frais de dossier - 45,00 » = 45,00 ;
  « Ligne 3 - 1 234,56 » = 1 234,56), sauf après une devise (« EUR - 12,00 » = −12,00). Le moins en tête, collé, ou
  après une ponctuation (« Remise : - 12,00 ») reste un signe.

## D-1210 — Imputation des avoirs : une règle §17.2 pour C, D et E (F7, audit D P1-1)

- **Constat** : trois rattachements différents (C : facture puis MRN, émetteur non vérifié, doublon par numéro
  seul ; D : idem avec égalité stricte des MRN de ligne même quand l'avoir cite la facture ; E : paliers §17.2 sans
  seuil `C_MIN_UTILE`). D3 et E6 n'imputaient pas les mêmes lignes (BX0026 : MRN lu « O » pour « 0 »).
- **Choix** : une seule source de lignes d'avoir (`_aides_befg.lignes_credit_du_dossier` : avoirs du dossier hors
  seconde réception E3, émetteur reconnu, montants et références `≥ C_MIN_UTILE`) et un seul rattachement par
  paliers (`recouvrement.imputation.choisir_par_paliers` : facture d'origine, à défaut MRN, à défaut transport) avec
  la même règle d'émetteur (`emetteurs_compatibles`, D-304/D-305) pour C (déduction par unité), D (déduction par
  ligne, D-703) et E (imputation sur les écarts). En D, quand plusieurs lignes de même nature existent, le MRN de la
  ligne d'avoir choisit la ligne à une confusion OCR près (`cle_confusion_ocr`) ; sinon la première.
- C et D déduisent toujours avant de calculer l'écart (montant net, §8.6) ; E impute sur les écarts (§17.2). Les
  trois appliquent désormais les mêmes avoirs avec les mêmes rattachements.
- **Banc** : BX0026 D3 29,56 -> 10,63 (net de l'avoir, attendu par la vérité) ; exactitude des montants
  95,8 % -> 96,5 %.

## D-1211 — Reconnaissance d'un transitaire : règle unique (audit D P1-2)

- `normalize.parties.identifier_transitaire(tva, nom, transitaires)` : TVA égale ; sinon nom égal au nom ou à un
  alias ; sinon nom ou alias d'au moins 4 caractères contenu en **mots entiers** ; un seul transitaire doit
  correspondre (sinon ambigu, `None`). Utilisée par le regroupement (`Dossier.transitaire_id`, avant : inclusion en
  sous-chaîne, premier trouvé), `cle_emetteur` (avant : égalité seulement) et le choix de la grille (avant : mots
  entiers, unique). Banc inchangé.

## D-1212 — C6 : FAF corrigé arrondi avant la différence (F11, interprétation de §8.6 / §12 C6)

- **Lecture retenue** : `excedent_faf = min(arrondi(FAF au taux sur l'assiette facturée), FAF facturé) −
  arrondi(FAF au taux sur l'assiette corrigée)`, borné à 0 : on compare centimes à centimes ce que le client a payé
  et ce qui aurait été facturé sans l'excédent. La lettre de §12 C6 (`arrondi(taux × excédent)`) donnait 1,55 là où
  la facture corrigée donne 86,11 − 84,55 = 1,56.
- **Banc** : BX0096 C6 1,55 -> 1,56 ; BX0234 3,68 -> 3,69 (valeurs de la vérité ; déjà dans la tolérance du
  correcteur, métriques inchangées).

## D-1213 — Nature d'une ligne : une table (audit D P0-3)

- `normalize/natures.py` (`NATURES_LIBELLES`, `nature_libelle`) remplace les deux tables divergentes de
  `ingest/structure.py` (UBL, CII, tableurs) et de l'extracteur PDF. Union des motifs, ordonnée par spécificité.
  « forfait » seul n'est plus un débours petits envois (« Forfait dédouanement » -> `frais_dedouanement`) ; « TVA »
  seul -> `debours_tva` ; « Fret », « stockage », « Chargement » reconnus. Restrictions assumées pour les exports
  structurés : « droits » seulement en tête de libellé (« Droits du port » n'est pas un droit de douane), « TVA 20 % »
  n'est plus un débours.
- **Banc** : aucune différence de `findings.json` sur dev.

## D-1214 — Chargement explicite des composants (audit D P1-3)

- `pipeline.composants_par_defaut` importe explicitement le découpeur (`controldone.ingest.Decoupeur`) et les
  extracteurs (`ingest.structure.extracteurs`, `extract.deterministe.extracteurs`) ; plus de liste de modules
  essayés avec exceptions avalées. `extract/deterministe/__init__.py` importe ses cinq extracteurs directement : une
  erreur d'import lève. `controls.registry.charger_controles` importe la liste `MODULES_CONTROLES` et lève si l'un des
  59 contrôles de l'Annexe A n'est pas enregistré. Test : `tests/test_chargement_composants.py`.
- Non traité ici (fichiers hors moteur) : valeur par défaut `--moteur auto` de `cli.py` et repli de `demo/`.

## D-1215 — Participe « dû » : variabilité décidée sur l'expression accentuée (F9, remplace la conséquence de D-014)

- « dû » dans le fichier des formulations est variable à toute position (`dû|dus|due|dues`) : « montants dus à la
  douane » est bloqué (pluriel exigé par §3.2). « du » article reste invariable.
- La seule forme ambiguë « du » sans accent, en fin d'expression (« droit dû »), n'est bloquée que si le texte source
  porte l'accent, si elle termine une proposition (« le droit du. », « droit du ; ») ou si le texte est entièrement en
  capitales. « droit du tarif », « Droit du port », « droits du dossier » ne sont plus bloqués.
- Le trait d'union conditionnel (U+00AD) est retiré et les espaces de largeur nulle (U+200B–U+200D, U+2060, U+FEFF)
  deviennent des espaces avant comparaison ; l'extrait signalé reste celui du texte d'origine.

## D-1216 — Dette : aides dupliquées et code mort (audit D P2)

- `_dec`, `_somme`, `_par`/`_entre_parentheses` de C et D et `_num` de B : une seule définition dans `_aides_befg`
  (`num_utilisable`, `somme`, `entre_parentheses`, `num`). Huit copies de `re.sub("[^A-Z0-9]", "", x.upper())` dans les
  extracteurs : `normalize.refs.norm_alnum`.
- Supprimés après vérification (aucun appelant dans `src`, `tests`, `scripts`) : `UniteC.credit_total`,
  `_mise_en_page.accepte_texte`, `_mise_en_page.est_zero_decimale`, paramètre `texte_ligne` de `_segmenter`,
  `declaration._re_sous`, `Champs.valeurs_par_id`, `rapport.pdf._filet`, `regroupement._refs_transport_groupe`,
  `ControlContext.other_dossiers`. Gardé : `ingest/texte.lignes_haut` (périmètre ingestion/OCR).
- Banc : `findings.json` identiques avant et après (hors `duree_s`).


# Audit final : corrections de la plateforme

Corrections issues de l'audit B (robustesse de la plateforme, constats F-01 à F-20 et suspicions), du volet
plateforme de l'audit D (P0-1, P0-2, P1-4, P1-6, P1-7, P2-8) et de l'analyse juridique France-Suisse
(`docs/recherche/juridique_france_suisse.md` §1, §4.4, §5.4, §9). Chaque correction a un test qui échouait avant
(`tests/platform/test_audit_final_platform.py`, `tests/web/test_audit_final_web.py`,
`tests/ops/test_audit_final_ops.py`, `tests/facturation/test_audit_final_facturation.py`). Mesures de l'audit B
refaites après correction (même scripts, même machine) :

| Mesure | Avant | Après |
|---|---|---|
| `/sante` pendant 4 dépôts API de 45 Mo en parallèle (worker intégré actif) | médiane 2,8 s, max 3,1 s | médiane 0,13 s, max 1,1 s |
| `/sante` pendant un dépôt de 10 × 45 Mo | bloqué 28 s | médiane 0,09 s, max 0,25 s |
| Attente d'un autre écrivain pendant un dépôt de 10 × 45 Mo | 27 s | 0,0 s |
| 3 processus déposant chacun 10 × 40 Mo | « database is locked » après 30,1 s | 3 dépôts réussis (35 à 36 s) |
| Attente d'un autre écrivain pendant `publier_rapport` (70 dossiers) | 12,1 s | 0,0 s |
| Mémoire du processus web, dépôt API de 10 × 45 Mo (VmHWM) | 105 → 885 Mo | 107 → 258 Mo |
| Sauvegarde (RSS max) | 6 266 Mo pour un coffre de 1,1 Go | 77 Mo pour 1,7 Go (restauration : 70 Mo) |
| Battement de cœur en échec une fois (`lease.py`) | double exécution (w1 perdu, w2 refait) | une exécution (w1 `done`, w2 ne prend rien) |

## D-1301 — Clôture automatique, point de départ de la conservation (F-01)

- **Constat** : la purge ne supprimait jamais rien : aucun chemin ne clôturait un dossier ni un lot.
- **Choix** : `storage.retention.cloturer_inactifs`, appelée par le handler `purger_retention` avant la purge.
  Dossier clos s'il est inactif depuis `CONTROLDONE_CLOTURE_AUTO_JOURS` (60) jours, sans écart encore ouvert
  et sans constat en attente de décision dans sa version courante ; lot clos s'il est en erreur depuis le même
  délai, ou traité et dont tous les dossiers sont clos. Une nouvelle activité rouvre le dossier. La conservation
  de 180 jours court ensuite. Une transaction par client, entrée d'audit `cloture_auto`.

## D-1302 — Une seule liste de handlers (F-07, audit D P1-6)

- `jobs.registre.MODULES_HANDLERS` et `charger_handlers()` : utilisés par `python -m controldone.jobs.worker` et
  par le worker intégré de `controldone serve`. Le worker intégré ne réserve que les kinds qu'il connaît
  (`kinds=sorted(handlers)`) : un kind inconnu reste `pending` au lieu de mourir `handler_inconnu`. Identifiant
  unique par processus (`web-integre:<hôte>:<pid>`, suspicion 5).

## D-1303 — Battement de cœur robuste et jeton de clôture (F-05)

- Une erreur de base dans `prolonger` est journalisée (`battement_echec`) et retentée ; le bail n'est perdu que
  si la ligne n'est plus détenue ou si aucun renouvellement n'a réussi pendant `lease_s - heartbeat_s`.
- Jeton de clôture `(locked_by, attempts)` : `prolonger`, `terminer`, `echouer` le vérifient ;
  `JobContext.exiger_bail(session)` relit la ligne **dans la transaction** qui valide les résultats
  (`traiter_lot` : avant le pipeline, après, et dans la transaction finale). Deux workers ne valident jamais le
  même job, même avec le même identifiant. `python -m controldone.jobs.worker` passe par le module importé
  (suspicion 4).

## D-1304 — Routes synchrones ; dépôt reçu hors transaction (F-03, F-04, F-14)

- Toutes les routes web et API sont des `def` (groupe de fils de Starlette) ; le formulaire multipart est lu
  par `web.securite.formulaire_sync` (lecture asynchrone exécutée depuis le fil). Test : aucune route
  `async def`.
- Dépôt (`services.depot.deposer`) : (1) empreintes déjà reçues en transaction de lecture ; (2) réception,
  contrôle et chiffrement **un fichier à la fois** (flux du téléversement, `gc.collect` après un gros PDF), sans
  verrou ; (3) courte transaction d'écriture (lot, fichiers, job). Échec de (3) : les contenus créés par ce
  dépôt sont retirés du coffre. Au plus `CONTROLDONE_DEPOTS_SIMULTANES` (2) dépôts à la fois.

## D-1305 — Fichiers temporaires sur le volume de données ; coffre par segments (F-14, F-16)

- `CONTROLDONE_TMP_DIR` (défaut `<data_dir>/tmp`) devient le répertoire de `tempfile` du web et du worker
  (`Settings.appliquer_repertoire_temporaire`) : téléversements multipart, déchiffrement des lots, sauvegardes
  ne vont plus dans le tmpfs `/tmp` de 1 Go du conteneur.
- Coffre : contenus d'au moins 256 Kio au format `CDV2`, AES-256-GCM par segments d'1 Mio (ordre, fin et
  substitution authentifiés), écrits et lus segment par segment ; les objets Fernet existants restent lisibles.
- Dossier surveillé : `relever()` ne lit plus aucun fichier (`ElementsParesseux`, lecture à l'intégration),
  ignore et signale les fichiers au-delà de `taille_fichier`, découpe en dépôts plafonnés à `taille_lot`.

## D-1306 — Lectures du fondateur sans verrou ; job dans la transaction (F-06, F-12)

- `OperatorScope.client(…, lecture=True)` : transaction différée. Consultation d'un dossier, vignettes,
  téléchargements et `publier_rapport` (rapport généré en lecture, pièces déposées hors transaction, puis
  courte écriture dans la file des sorties) ne bloquent plus les autres écrivains.
- Correction d'une valeur : le job `recontroler_dossier` est inséré dans **la même** transaction que la
  nouvelle version du dossier (`JobStore.enqueue_dans`, `TenantScope.mettre_en_file`) ; idem pour le dépôt
  (lot + job) et les connecteurs.

## D-1307 — Taux de commission : une seule source (F-10)

- `litiges.commission.taux_commission(reglages)` : `reglages["commission_taux"]` du client, sinon le taux du
  catalogue (`config/offres.yaml`). Utilisée par le service des litiges et par la page Finances.

## D-1308 — Une frontière de mois : Europe/Paris (F-19)

- `calendrier.mois_paris` pour l'échéance d'abonnement (agent, page Finances, webhook) et le plafond IA
  (`jobs.couts.mois_courant`) : plus deux clés d'idempotence pour une même échéance la première heure du mois.

## D-1309 — Lectures bornées et triées en SQL (F-11, F-15)

- Job d'un lot cherché par sa clé (`traiter_lot:<client>:<lot>`, index unique) ; `jobs_du_client` retiré des
  lectures de lot. Purge des jobs `done` de plus de `CONTROLDONE_JOBS_CONSERVATION_JOURS` (30) jours.
- `file_validation` triée en SQL avant la limite, comptée par `count()` ; `statistiques` agrège colonne par
  colonne (jamais le JSON `contenu`) sur la version courante ; listes de sorties et d'alertes : les plus récentes
  d'abord en SQL ; `TenantScope.compter` en `COUNT(*)` ; recontrôle : une requête pour tous les documents du
  client ; purge par client et par paquet de 500 fichiers. API `/dossiers` paginée (`limite`, `apres`,
  `X-Page-Suivante`).

## D-1310 — `.env` lu par toutes les lectures de réglages (F-13, audit D P1-4)

- `config.charger_fichier_env` charge `./.env` (ou `CONTROLDONE_ENV_FILE`) dans `os.environ` une fois, sans
  écraser l'environnement réel ; `config.env(nom)` remplace les `os.environ.get` directs (mode d'exécution, clé
  maîtresse, secret de session, Stripe, vendeur, MCP…). Nouveaux champs de `Settings` : `env`, `tmp_dir`,
  `lot_duree_max_s`, `jobs_conservation_jours`, `cloture_auto_jours`, `depots_simultanes`.

## D-1311 — Durée maximale d'un lot et ordonnancement équitable (F-20, F-18)

- `CONTROLDONE_LOT_DUREE_MAX_S` (prod 1800) : le pipeline tourne dans un processus fils (`spawn`), tué au-delà ;
  le job devient `dead` (alerte) et le worker passe au lot suivant.
- `reserver` sert d'abord le client dont l'activité la plus récente est la plus ancienne (tourniquet), FIFO au
  sein d'un client.
- Plafonds IA effectifs (F-18) : `CONTROLDONE_LLM_PLAFOND_DOSSIER_EUR` est passé au pipeline par le worker ;
  `_CLIENT_MENSUEL_EUR` et `_DIAGNOSTIC_EUR` sont les défauts du plafond mensuel à la création d'un client.

## D-1312 — Insertion d'une action sortante sous concurrence (suspicion 1)

- `storage.sorties.inserer` : point de sauvegarde ; si la clé d'idempotence vient d'être prise par une
  transaction concurrente (PostgreSQL), la ligne existante est renvoyée au lieu d'une `IntegrityError`. Le
  cumul des avoirs d'une facture est vérifié dans la transaction de numérotation.

## D-1313 — Coupon de lancement sans accord de publication (brief §4.4)

- `consentement_requis: false` dans `config/offres.yaml` : la remise ne dépend d'aucune contrepartie.
  `proposer_diagnostic` accepte l'absence de consentement (plus d'`AttributeError`) ; un accord signé est cité
  à titre d'information (`revocable: true`), jamais comme condition (`accord_publication_condition: false`).

## D-1314 — Assiette de la commission (brief §1.3)

- Base = montants **hors taxes** des avoirs émis par un **transitaire** ; la TVA d'un avoir est conservée pour
  information ; un remboursement ou une remise accordés par la douane ou une autre autorité
  (`origine: "administration"`) est `hors_assiette` et n'ouvre aucune commission (service des litiges et page
  Finances).

## D-1315 — Relevé d'écarts et modèle à adapter ; vocabulaire ; alias d'API (brief §1.3, §9)

- `litiges.redaction` produit deux parties : un **relevé d'écarts** factuel (documents, pages, valeurs lues,
  différence, tolérance) et un court « **Modèle à adapter par le client** » neutre, qui demande de vérifier et
  d'indiquer si un avoir sera émis. `verifier_modele` refuse « nous réclamons », mise en demeure, délais,
  pénalités, citations de textes (`EXPRESSIONS_INTERDITES`).
- Interface : « relevé d'écarts » au lieu de « dossier de réclamation », « suivi des avoirs reçus » au lieu de
  « suivi du recouvrement » / « registre de recouvrement » (espace client, tableau de bord du fondateur).
- API : `/suivi-avoirs` (alias de `/litiges`, mêmes réponses), événement `releve_envoye` (alias de
  `reclamation_envoyee`), champs `rappel_suggere` (alias `relance_suggeree`), `ecart_id` (= `litige_id`),
  `type_libelle` (`releve_ecarts`) : les anciens noms restent valides.

## D-1316 — Un analyseur strict des montants saisis (audit D P1-7)

- `services.saisie.montant_saisi` : utilisé par l'API, le MCP, l'espace client, la page Finances, la fiche
  client (plafond IA), la création d'un client et l'import CSV d'une grille tarifaire (prix jusqu'à 4
  décimales). Refuse `NaN`, `Infinity`, notation scientifique, `+`, négatif, zéro (sauf demande), groupes de
  milliers mal formés, plus d'un milliard ; accepte espaces (y compris insécables), `1.234,56`, `1,234.56`, `€`.

## D-1317 — Le suivi passe par `ServiceLitiges` ; rappels : une source (audit D P0-1, P0-2)

- `services.reclamations.declarer_envoi_releve` et `enregistrer_avoir_recu` (web, API, MCP) : si l'écart
  appartient à un relevé d'écarts, `ServiceLitiges.declarer_envoi` (tout le relevé `reclame`, rappels planifiés)
  ou `ServiceLitiges.enregistrer_avoir` (imputation déterministe, commission, brouillon `facture_emise`) ;
  sinon la transition directe historique.
- `rappel_suggere` lit `reglages["relances_jours"]` du client, défaut `RELANCES_DEFAUT` = 15, 30, 45 jours
  (D-602) ; la constante 30/60/90 est supprimée.

## D-1318 — Référentiel : prix seulement pour un transitaire nommé (brief §5.4)

- Un transitaire n'est nommé que si son entrée de `config/referentiel_alias_publics.yaml` porte
  `accord_ecrit` (référence et date) ; sinon empreinte salée. Nommé, il n'a que des statistiques de prix :
  `taux_dossiers_avec_ecart` vaut `None` (vide à l'export).

## D-1319 — Totaux de la plateforme = règle du rapport

- `TenantScope.enregistrer_resultats` applique `findings_io.constats_hors_totaux` par dossier et l'inscrit dans
  `contenu.hors_totaux` de chaque constat ; `services.lecture` (espace client, API) et
  `OperatorScope.statistiques` excluent ces constats (E6 remplaçant, doublon F5) comme le rapport. Les constats
  enregistrés avant cette version n'ont pas la marque : ils comptent comme avant jusqu'au prochain traitement.

## D-1320 — Sauvegarde et restauration en flux (F-02)

- Format `CDSAV2` : tar.gz écrit en flux et chiffré par segments d'1 Mio (un jeton Fernet par segment, numéro et
  drapeau final authentifiés) ; copie de la base dans un répertoire temporaire du volume de destination ;
  restauration en flux ; l'ancien format reste restaurable. Échec : alerte `sauvegarde_echec` et code 1.

## D-1321 — Report d'un job sans consommer d'essai (suspicion 6)

- **Constat** : `POST /einvoices` met en file `traiter_lot` et `controle_avant_paiement` pour le même lot ; avec
  deux workers, le pipeline (et le modèle de langage) tournait deux fois.
- **Choix** : exception `jobs.registre.Reporter(motif, delai_s)` ; le worker rend le job `pending` après le
  délai, rend l'essai (`JobStore.reporter`) et journalise `job_fin` statut `reporte`. `controle_avant_paiement`
  se reporte tant que le `traiter_lot` du lot est en file ou en cours (bail valide) ; il ne lance lui-même le
  pipeline que si ce job n'existe pas ou est mort.

## D-1322 — Schéma périmé détecté au démarrage (suspicion 8)

- `Database.colonnes_manquantes()` compare chaque table existante au modèle ; `exiger_schema_a_jour()` lève
  `SchemaPerime`. `controldone serve` (après `--init-schema`) et le worker s'arrêtent avec le code 3 et la liste
  des colonnes, au lieu d'échouer en cours de route sur « no such column ». Les migrations restent manuelles
  (point ouvert de `docs/SECURITY.md`).

## D-1323 — Expéditeur appelé hors transaction (suspicion 3)

- `FileSortante.envoyer` : réservation courte (`reference_envoi = "envoi_en_cours:<jeton>:<horodatage>"`),
  appel de l'expéditeur hors transaction (un dépôt réseau sur la plateforme agréée ne tient plus le verrou
  d'écriture), puis enregistrement court. Second envoi pendant la réservation refusé ; échec de l'expéditeur :
  réservation levée ; réservation abandonnée expirée après 15 minutes (le renvoi suivant doit rester idempotent
  côté expéditeur, comme avant).

## D-1324 — Purge et redépôt du même contenu (suspicion 2)

- Coffre adressé par contenu : un fichier purgé redéposé à l'identique pendant la purge pouvait être effacé.
- `FileVault.deposer` rafraîchit la date d'un contenu déjà présent (et le réécrit s'il vient d'être retiré) ;
  `purger_expires` vérifie et supprime **sous le verrou d'écriture** et épargne un contenu redéposé depuis moins
  d'une heure (`RapportPurge.epargnes`) ; un dépôt (web, API, connecteurs) revérifie la présence de ses
  contenus dans la transaction qui l'enregistre et se refuse proprement sinon. Le nettoyage d'un dépôt échoué
  se fait aussi sous le verrou d'écriture.

## D-1325 — Planificateur : rattrapage sans doublon (suspicion 7)

- `deploy/backup-cron.sh --si-absente` : rien si l'archive du jour (UTC) existe ; le planificateur l'utilise,
  un redémarrage du conteneur ne refait plus la sauvegarde du jour.
- Référentiel : mis en file à partir du 2 du mois (03 h UTC) avec la clé `referentiel:<AAAA-MM>` : rattrapé si le
  conteneur était arrêté le 2, jamais deux fois dans le mois.

## D-1326 — Installation (F-17) et points non corrigés

- `make install` crée `.venv` s'il manque, installe `requirements.lock` puis le paquet éditable avec `[dev]` ;
  `numpy` et `httpx` déclarés ; `alembic`, `mako`, `python-dateutil` retirés du lock.
- Non corrigés : installation **non éditable** (`config/` et `ref/` hors de la roue ; contournement :
  `CONTROLDONE_CONFIG_DIR`, `CONTROLDONE_REF_DIR`, ou installation `-e` comme le Dockerfile) ; dédoublonnage de
  `enregistrer_avoir` par lecture puis écriture, sûr sous SQLite (`BEGIN IMMEDIATE`) mais non éprouvé sous
  PostgreSQL ; registre de coûts IA persistant et cache de pages dans le pipeline (audit D P1-5 : périmètre du
  moteur) ; plafonds par défaut encore codés dans `extract/llm.py`, `pipeline.py` et `model/referentiel.py`
  (fichiers du moteur ; mêmes valeurs que `Settings`).

# Audit final : performance

Mise en œuvre de l'audit C (performance), n° 1 à 7. Règle : **aucune sortie ne change**. Vérification sur le banc dev
complet (202 dossiers, 4 processus, cache de pages vide, `--no-score`) entre la base `dbc2a9d` (worktree) et le
nouveau code :
- **202/202 `findings.json` identiques** hors `execution.duree_s`, mêmes non lus, 0 erreur ;
- les **2 409 fichiers du cache de pages identiques octet pour octet** : texte OCR, boîtes et avertissements compris ;
- `scripts/mesure_extraction.py --degradation d2,d3` : **19 356 comparaisons identiques en JSON** (déclaration
  10 599, facture commerciale 5 261, facture transitaire 3 496).

Temps et mémoire mesurés sur 4 vCPU :

| Mesure | Base `dbc2a9d` | Après | Écart |
|---|---|---|---|
| Banc dev complet, cache vide (mur) | 1 170,7 s | 719,6 s | −39 % |
| 3 dossiers en série (BX0039, BX0024, BX0102), `--workers 1` | 121,1 s | 22,8 s | ÷5,3 |
| `mesure_extraction` déclaration d2+d3 (4 processus) | 254,4 s | 189,4 s | −26 % |
| `mesure_extraction` facture commerciale d2+d3 | 217,8 s | 153,6 s | −29 % |
| `mesure_extraction` facture transitaire d2+d3 | 83,1 s | 61,8 s | −26 % |
| 8 rapports dans un même processus : pic de RSS | 363 Mo | 216 Mo | −147 Mo |
| idem : RSS retenue après les 8 rapports | 363 Mo | 168 Mo | −195 Mo |
| idem : durée | 8,9 s | 5,3 s | −40 % |
| idem : taille des PDF | 2 748 Ko | 2 273 Ko | −17 % |

## D-1400 — Image temporaire de Tesseract en PGM/PPM (audit C n° 1)

- pytesseract enregistrait chaque image en PNG, soit environ 1 s d'encodage par appel pour une page A4 à 300 dpi.
  `_pour_tesseract` fixe `image.format = "PPM"`, ce qui donne un PGM en mode `L`.
- Le format est sans perte : Tesseract reçoit les mêmes pixels et le texte ne change pas (cache de pages identique).

## D-1401 — `_page_texte_brut` linéaire (n° 7)

- `largeur_max` est calculée une seule fois, avant la boucle sur les lignes. La sortie ne change pas.
- 20 000 lignes : environ 13 s → moins de 0,3 s. Un gros XML ou un long courriel n'atteint plus le délai du
  processus de pages.

## D-1402 — Processus de pages issu d'un forkserver préchargé (n° 3)

- **Un processus neuf par fichier**, créé par un forkserver qui précharge pdfplumber, pypdfium2, pytesseract, PIL,
  openpyxl, lxml et `controldone.ingest.pages`. Les modules préchargés ne contiennent que du code, aucune donnée.
- Les garde-fous restent les mêmes :
  - `RLIMIT_AS` ;
  - délai `poll(timeout)`, puis `kill` ;
  - `alarm` de secours ;
  - sorties standard vers `/dev/null` ;
  - repli sans OCR, puis pages illisibles.
- Le surcoût par fichier passe d'environ 0,43 s à environ 0,05 s.
- **RS-14** : le forkserver est lancé avec l'environnement C dont on a retiré tout ce que filtre
  `_environnement_sans_secrets()`, le même filtre que pour le sous-processus. Il est relancé de la même façon s'il
  s'est arrêté.
- L'enfant ne réimporte pas le `__main__` du parent.
- Un processus « daemon » (worker de jobs, pool du banc) peut lancer ce processus, puisqu'il est toujours attendu ou
  tué avant de rendre la main.
- Si la plateforme n'offre pas de forkserver, on revient à `python -m controldone.ingest._worker`.

## D-1403 — Registre des textes positionnés vidé en fin de lot (n° 6)

- `preparer_lot` appelle `Decoupeur.liberer`, puis `liberer_textes`, dans un `finally`, après l'extraction.
- Le registre gardait environ 85 Ko par page, jusqu'à 20 000 entrées (environ 0,85 Go), avec le texte des documents
  en clair, dans le worker.
- La clé `sha:` n'est retirée que si elle désigne encore la page du lot.

## D-1404 — Désinclinaison sans numpy (n° 5)

- Même algorithme, en PIL seul : `ImageStat`, `point`, comptage d'octets par ligne. Le score est un entier exact.
- Angles **identiques sur 220 images sur 220** : les 55 pages OCR de l'audit, chacune à 0°, 90°, 180° et 270°. Le
  cache de pages du banc dev est aussi identique.
- numpy n'est plus importé par le code : sa déclaration est retirée de `pyproject.toml`.
- **Reste à faire, côté plateforme** : retirer `numpy` de `requirements.lock`, soit −57 Mo dans le venv et environ
  −72 Mo dans l'image.

## D-1405 — Étape 2 en parallèle sur les fichiers d'un lot (n° 4)

- `Decoupeur.precharger` lance `textes_pages` (cache disque, puis processus isolé) pour tous les fichiers du lot,
  avec un `ThreadPoolExecutor` et un processus isolé par fichier. Les plus gros fichiers partent en premier.
- Le découpage, l'attribution des identifiants et l'ordre restent séquentiels et inchangés. Le texte préchargé est
  consommé puis libéré, et un échec laisse `decouper` refaire le travail.
- Le parallélisme se règle par `CONTROLDONE_PAGES_PARALLELE` ; par défaut, `min(processeurs disponibles, 4)`. Il
  n'agit qu'en processus isolé.
- Mémoire de pointe : jusqu'à N processus d'OCR d'environ 400 Mo chacun. Sur un DEV1-S de 2 Go, régler N = 2.

## D-1406 — Rapport : PNG sans `optimize`, flux PDF binaires, cache de rendu vidé par rapport (n° 2)

- `rogner` enregistre le PNG sans `optimize=True`. L'image reste la même, sans perte.
- `rl_config.useA85 = 0` : les PDF sont environ 17 % plus petits.
- `generer_rapport` vide le cache `_page_image` à la fin de chaque rapport. Il gardait jusqu'à 64 pages rendues
  d'environ 9 Mo, avec des images de pièces client déchiffrées, dans le processus web.

# Corpus public

Les spécimens publics de factures électroniques (dépôts ZUGFeRD/corpus, CEN eInvoicing-EN16931, OpenPeppol BIS
Billing 3, akretion/factur-x) ont été passés dans le pipeline complet, du sniff au rapport. Les sources, les
licences, les exclusions et les mesures sont dans `docs/CORPUS_PUBLIC.md`.

| Mesure | Avant | Après |
|---|---|---|
| Exceptions non gérées (859 fichiers) | 1 | 0 |
| Facture de 26 813 lignes | plus de 15 min | 45 s |
| Type facture / avoir | 87,4 % | 99,7 % |
| Total BT-112 | 91,5 % | 99,7 % |
| TVA vendeur BT-31 | 86,2 % | 99,7 % |
| ZUGFeRD 1.0 lus | 0/25 | 25/25 |

- Banc dev inchangé : précision 1,000, rappel 0,813, seuil bloquant passé.
- Tests : `tests/ingest/test_ingest_structure_public.py`, sur des XML fictifs écrits à la main.

## D-1500 — Corpus public hors dépôt, vérité de terrain indépendante

- `scripts/corpus_public.py fetch` clone les quatre dépôts dans `var/corpus_public/`, qui est ignoré par git. Aucun
  fichier tiers n'est versionné, ni recopié dans les tests.
- Exclusions :
  - documents d'apparence réelle : `unstructured/`, `incoming/`, et un PDF partiellement pseudonymisé ;
  - tests unitaires `testSet` et extraits : comptés pour la robustesse, pas pour l'exactitude.
- La vérité est lue dans le XML par un lecteur XPath propre au script, en `local-name()`, sans code de
  `controldone`. La pièce jointe d'un PDF est lue par `pypdf`.
- Les montants sont comparés en valeur absolue (§5.2).

## D-1501 — Pièce jointe XML d'un PDF hybride : tous les noms, choix par la racine

- `factur-x` (`get_facturx_xml_from_pdf`) ne cherchait que `factur-x.xml` et `zugferd-invoice.xml`. La variante
  XRechnung embarquée (`xrechnung.xml`) et les noms libres étaient donc ignorés : le PDF passait par la lecture du
  texte.
- `piece_xml_facture` lit toutes les pièces jointes `*.xml` avec pypdf, dans cet ordre de préférence :
  `factur-x.xml`, `zugferd-invoice.xml` (toute casse), `xrechnung.xml`, puis les autres.
- La première pièce dont la racine est une facture CII, UBL ou ZUGFeRD 1.0 est retenue. Une pièce de plus de 20 Mo
  décompressés est ignorée.
- La validité au schéma est jugée ensuite, comme pour un XML seul : 1,0 si le XML est valide, 0,95 sinon.

## D-1502 — ZUGFeRD 1.0 lu (et non refusé)

- Le schéma `urn:ferd:CrossIndustryDocument:invoice:1p0` (2014) reprend les notions du CII avec d'autres chemins
  (`HeaderExchangedDocument`, `ApplicableSupplyChainTrade*`, `SpecifiedSupplyChainTradeSettlement`).
- Avant ce lot, ces PDF passaient par la lecture du texte (allemand), et 21 sur 25 n'étaient pas classés.
- Le lecteur `_lire_zf1` remplit les mêmes champs que le CII. Format `zugferd1` pour un XML seul, `facturx` dans un
  PDF.
- Le XML est validé contre le XSD ZUGFeRD 1.0 de la bibliothèque `factur-x` : confiance 1,0 seulement s'il est
  valide.

## D-1503 — BT-110 dans la devise de facture ; numéro de TVA = schéma VAT

- **Total de TVA.** `TaxTotalAmount` (CII) et `TaxTotal/TaxAmount` (UBL) peuvent être répétés dans la devise de
  comptabilisation (BT-111). Le premier rencontré n'est pas forcément BT-110. On retient celui dont le `currencyID`
  est la devise BT-5.
- **TVA d'une partie en UBL.** Le premier `PartyTaxScheme` peut être une autre immatriculation fiscale (BT-32,
  schéma `FC`…). On retient le `PartyTaxScheme` de schéma `VAT`, puis, à défaut, celui sans schéma.
- En CII, `schemeID="VA"` était déjà exigé.

## D-1504 — Facture à total général négatif : avoir

- §5.3.1 : un avoir présenté comme une facture se reconnaît à son total négatif. Une facture structurée (380, 384…)
  dont BT-112 est négatif est donc classée `avoir`.
- Ses montants sont stockés en valeur absolue avec `signe_imprime = negatif` (§5.2).
- 10 spécimens sont concernés : `Rechnungskorrektur`, `negativ_faktura`, factures 380 de correction.
- Le modèle `avoir` ne portant ni l'acheteur ni les sous-totaux, ces champs deviennent « n/a ». Ce n'est pas une
  régression de lecture.

## D-1505 — Frais logistiques, codes de motif, lignes de texte seul

- **Frais logistiques.** `SpecifiedLogisticsServiceCharge` (CII EXTENDED, ZUGFeRD 1.0) est un frais de transport.
  Il est lu comme sous-total `fret`.
- **Codes de motif.** Les codes UNTDID 7161 d'un frais sans libellé donnent le type de sous-total : `FC` → fret,
  `IN` → assurance, `PC` et `ABL` → emballage. Les libellés allemands courants (Fracht, Versand, Versicherung,
  Verpackung) sont aussi reconnus.
- **Lignes de texte seul.** Une « ligne » qui n'a ni article, ni quantité, ni prix, ni montant (commentaire
  ZUGFeRD 1.0 ou EXTENDED) n'est pas une ligne de facture. Elle laissait une ligne vide dans le modèle ; elle est
  maintenant écartée.

## D-1506 — Lecture linéaire des grandes factures

- `_chemin_xpath`, qui produit le `texte_contexte`, recalculait le rang de chaque nœud parmi tous ses frères. Le
  coût était donc quadratique : plus de 15 minutes pour la facture Qvalia de 26 813 lignes, et des heures pour celle
  de 63 404 lignes, avant même le refus à la réception.
- Les rangs sont maintenant calculés une fois par parent, dans un cache propre à la lecture (`_Lecteur.cache`). Les
  XPath sont compilés une fois par lecture.
- Résultat : 26 813 lignes en environ 20 s. Le `texte_contexte` est identique.

## D-1507 — Bon de commande structuré : document non exploitable

- Order-X (racine `SCRDMCCBDACIOMessageStructure`) et UBL `Order` ne sont jamais des factures. §5.3.1 : un bon de
  commande est classé `document_non_exploitable`, avec le motif P2 `bon_commande`.
- `InfoStructure.motif` est recopié sur le `Document` par `decouper_fichier`.

## D-1508 — Sniff d'un XML à commentaire de tête ; CSV illisible sans exception

- Beaucoup de spécimens (CEN, Order-X) commencent par un commentaire de licence, sans déclaration `<?xml …?>`. Ils
  étaient pris pour du texte, donc refusés en `non_supporte`, ou pour du CSV quand le commentaire contenait des
  virgules.
- `detecter_type` saute maintenant les commentaires, les instructions de traitement et le `DOCTYPE` de tête avant
  de chercher l'élément racine.
- Un CSV dont un champ dépasse la limite du module `csv` (ou qui est illisible) levait `_csv.Error`. Il n'est plus
  reconnu par la fiche de correspondance (`reconnait` → faux), et l'extracteur rend `export_illisible`.

## D-1509 — Arrondi BT-114 : net à payer non transmis s'il est non nul

- EN 16931 : BT-115 = BT-112 − BT-113 + BT-114. Le modèle `facture_transitaire` porte le TTC, les acomptes et le net,
  mais pas l'arrondi. Le contrôle D1 `net_a_payer` vérifie net = TTC − acomptes.
- Avant : une facture de transitaire structurée à arrondi non nul (`ram:RoundingAmount`,
  `cbc:PayableRoundingAmount`) aurait produit un faux écart D1, l'arrondi pouvant atteindre presque une unité.
- Après : l'arrondi est lu. S'il est non nul, `net_a_payer` n'est pas renseigné ; D1 ne vérifie alors que le TTC.
  Un arrondi nul ou absent ne change rien.
- Un acompte écrit `0`, `0.00` ou `-0.00` reste ignoré.
- Corpus public : 14 factures ont un arrondi non nul, aucune de transitaire ; mesures inchangées. Tests :
  codes 261 (avoir) / 389 et 384 positif (facture), acompte et deux taux de TVA, arrondi.
- Banc dev inchangé : précision 1,000, rappel 0,813.

# Robustesse

Campagne d'entrées hostiles, cassées ou inhabituelles (`scripts/fuzz/`, compte rendu : `docs/ROBUSTESSE.md`).
Règle commune : tout fichier déposé finit **traité**, **refusé avec un motif** ou **listé non lu** ; jamais une
exception qui emporte le lot, un dépassement du délai configuré ou de la mémoire autorisée. Aucune limite de
sécurité de §20.3 n'est relâchée ; les bornes ajoutées ne touchent pas les documents réels (banc dev inchangé).

## D-1600 — Archives : entrée illisible, archive vide, filet de sécurité par fichier

- Avant : un flux deflate altéré dans une entrée ZIP levait `zlib.error` (non rattrapé) et faisait perdre toute la
  réception du lot ; une archive sans fichier (vide, répertoires seuls, EOCD seul) disparaissait sans trace.
- Après : toute erreur de décompression d'une entrée (`zlib.error`, `lzma.LZMAError`, `EOFError`, `KeyError`…)
  refuse **cette entrée** « corrompu » ; une archive sans aucun fichier est refusée « vide » ; chaque fichier
  déposé passe par `_traiter_sur` (une erreur imprévue d'analyseur refuse ce fichier « corrompu », journal sans
  contenu) ; un fichier illisible sur disque est refusé, le lot continue.
- Tests : `test_d1600_*`.

## D-1601 — pypdf ne journalise plus d'extraits de document

- pypdf écrit dans ses avertissements des octets bruts du fichier (en-têtes d'objets, flux) ; la réception tourne
  dans le processus web. Journal `pypdf` relevé à `CRITICAL` (§20.8). Test : `test_d1601_*`.

## D-1602 — Classeurs XLSX/ODS soumis aux limites d'archive

- Un `.xlsx` est un ZIP : une feuille de 1 Go de zéros (1 Mo compressé) passait la réception puis occupait le
  processus de pages jusqu'au délai. Les limites des ZIP déposés (§20.3 : entrées, taille décompressée, taux de
  compression) s'appliquent désormais au classeur (`_motif_conteneur`), avant le contrôle d'intégrité :
  refus `archive_dangereuse`. Test : `test_d1602_*`.

## D-1603 — Courriels : imbrication bornée, message joint encodé lu

- Le parcours MIME est itératif et borné (40 niveaux ; au-delà, courriel refusé « corrompu » au lieu d'une
  `RecursionError`) ; un courriel joint compte comme un niveau d'imbrication, comme une archive (profondeur ≤ 5,
  zip → eml → zip → eml… borné) ; un `message/rfc822` joint encodé en base64 ou quoted-printable (non conforme
  mais courant) est décodé au lieu d'être perdu. Tests : `test_d1603_*`.

## D-1604 — Texte positionné et feuilles de tableur bornés

- Un XML ou un CSV de 50 Mo produisait des millions de mots positionnés (plusieurs Go dans le processus de pages
  puis dans le processus principal qui les relit) ; une feuille aux dimensions annoncées aberrantes
  (`A1:XFD1048576`) faisait lire 16 384 colonnes par ligne.
- Le texte de la page reste **complet** ; les mots positionnés s'arrêtent à 50 000 lignes / 500 000 mots
  (avertissement `texte_positionne_tronque`) ; un tableur est lu sur 512 colonnes et 2 000 000 de cellules par
  feuille (`tableur_tronque`). Tests : `test_d1604_*`.

## D-1605 — Rognages du rapport bornés en pixels

- Même défaut que RS-04, côté rapport : une page de 2 × 5 m réclamait un bitmap de plusieurs gigaoctets, gardé dans
  le cache de rendu. Échelle réduite au-delà de `MAX_PIXELS` (≈ A3 à 144 dpi) pour les PDF ; images réduites
  (décodage JPEG réduit puis `resize`). Page A4 : rendu inchangé. Test : `test_d1605_*`.

## D-1606 — Lot sans dossier : ses fichiers sont listés non lus

- Un lot dont aucun document n'était reconnu ne produisait aucun dossier : le résumé du lot indiquait `non_lus: 0`
  et les fichiers acceptés disparaissaient sans trace. `traiter_lot` liste alors chaque fichier accepté avec le
  motif `aucun_dossier` (`non_lus_detail`, chemins et motifs techniques seulement). Test : `test_d1606_*`.

## D-1607 — Étape 3 bornée sur une page démesurée

- Mesure (sous plafond de 3 Go) : un XML de 49 Mo à 1,6 million d'éléments faisait monter le processus principal à
  **2,6 Go** et durait 61 s : arbre lxml de ~1 Go pour l'analyse structurée, puis normalisation caractère par
  caractère de 25 Mo de texte pour le classement (~1 Go de plus). Un texte de 30 Mo sur une seule ligne :
  1 Go (l'en-tête du classement découpait la ligne entière en mots, une fois par motif).
- Après : un XML de plus de 1 000 000 de balises n'est pas soumis à l'analyse structurée (format inconnu,
  avertissement `structure_non_analysee:trop_d_elements`) ; le classement travaille sur un extrait de la page
  (1 000 000 de caractères, 20 000 lignes de 10 000 caractères au plus ; avertissement `classement_sur_extrait`).
  Le texte complet de la page reste celui qui est conservé et extrait. Pic : 2,6 Go → 0,39 Go (7,8 s) ; 30 Mo
  sur une ligne : 1,0 Go → 0,46 Go.
- Les documents réels en sont loin (facture UBL de 10 000 lignes : ~300 000 balises ; pages du corpus : quelques
  Ko) : sans effet sur le banc. Tests : `test_d1607_*`.

## D-1608 — Garde-fous de la campagne elle-même

- Une première campagne (3 cas en parallèle, sans plafond d'espace d'adressage, arbre de processus jusqu'à 3,2 Go
  par cas) a épuisé la mémoire du conteneur. `campagne.py` exécute désormais chaque cas sous `RLIMIT_AS`
  (1 500 000 000 octets, hérité par les processus de pages, qui ne peuvent pas le relever ; leur propre plafond de
  production est 3 Go), avec délai (900 s) et plafond de mémoire résidente de l'arbre (3 Go), au plus 2 cas en
  parallèle ; un `MemoryError` est classé `memoire` (défaut). Le générateur écrit les bombes en flux (jamais
  200 Mo matérialisés).

# Généralisation : déclarations

Constat : sur le corpus de généralisation `bench/corpus_g2` (split dev, 308 déclarations, six présentations M1–M6
jamais vues du moteur), les champs obligatoires de la déclaration n'étaient exacts qu'à 35,5 % (champs clés
49,4 %) et 296 valeurs de confiance ≥ 0,90 étaient fausses (93,8 % d'exactitude). Règles générales, sans
référence aux noms de fichiers, gabarits ou sociétés fictives ; aides sans état dans
`extract/deterministe/_declaration_generique.py` ; tests sur des PDF reportlab et des contenus écrits dans les
tests (`tests/extract/test_declaration_generalisation.py`, `tests/ingest/test_ingest_structure_exports_attributs.py`).

## D-1801 — Fiches de correspondance des exports XML à attributs et CSV dénormalisé

- Deux fiches (`config/mappings/g2_m5_xml.yaml`, `g2_m6_csv.yaml`) décrivent les formats publiés dans
  `bench/generator2/FORMATS.md` ; le mécanisme de §5.3.6 n'est pas réécrit.
- XML : données portées par des attributs (XPath `@…`, texte d'élément `.`), taxations d'article et de niveau
  déclaration lues par une union XPath ; le rattachement est `ancestor::position[1]/@rang` (et non `../../@rang`,
  qui lirait le rang de version du dossier pour une taxation globale).

## D-1802 — Options génériques des fiches (rétrocompatibles)

Ajouts à `ingest/structure.py`, inactifs si la fiche ne les déclare pas :
- `csv.commentaire` : lignes commençant par ce préfixe ignorées partout (y compris avant l'en-tête et en fin
  de fichier) ; le contenu d'un commentaire n'est jamais lu (règle 7) ;
- `listes.<nom>.eclater` : une cellule portant plusieurs éléments (`N380:REF|N705:REF`) est découpée par
  séparateur et motif à groupes nommés ; lue une fois (colonne répétée sur chaque ligne d'un export dénormalisé) ;
- `listes.<nom>.requis` : élément retenu seulement si cette source est renseignée (article sans taxation : ses
  colonnes de taxation sont vides, il ne donne pas de ligne de taxation) ;
- `valeurs: {brut: valeur}` sur un champ : valeur imprimée traduite (sens du taux `1EUR` → `devise_par_eur`) ;
  `valeur_brute` reste celle du fichier ;
- une liste d'un CSV « à plat » (une ligne = un élément) n'a plus besoin de `source`.

## D-1803 — Déclaration imprimée : colonnes, libellés et récapitulatifs en texte

- Colonne « À payer » (DE 14 03 042) distincte du montant : rattachée jusque-là à la colonne « Montant », elle en
  prenait la place (« 0,00 » d'une TVA autoliquidée) ou en tronquait les milliers. Lue en `montant_a_payer`.
- Colonnes des tableaux d'articles (masse nette / brute, valeur statistique, colis, préférence, régime,
  quantité supplémentaire) et des tableaux de taxes (`Tax`, `Basis`, `Payment`, colonne « Art » de
  rattachement) en fr / en / de / it / es ; un en-tête de tableau (« Item | Commodity code | … ») n'ouvre plus de
  bloc d'article ; une ligne « Total A00: … » ferme un tableau de taxes.
- « Impositions au niveau de la déclaration » ferme le bloc du dernier article (la taxation n'y est plus
  rattachée).
- Documents produits : colonne « nature » entre le code et la référence (référence = premier mot qui porte un
  chiffre, préfixe court en capitales collé compris : « FT 4800/2026 ») ; même règle pour 1008 / FR7.
- Libellés : rubrique ouverte par un tiret (« LRN … — version 1 ») ou une parenthèse (« (TVA FR…) ») ; TVA et
  EORI sur la ligne du libellé de la partie ; « masse brute / colis » sous un même libellé ; « 63 colis » écrit en
  clair ; un nombre pris dans une référence (« CMR-FX-554972 ») n'est jamais un nombre de colis ; taux
  « EUR 1 = CHF 0.91106 » ; libellés d'en-tête de/it/es.
- Récapitulatif en texte (courriel « bon à enlever ») : articles en liste ouverts par « [n] code », couples
  « libellé valeur » séparés par « | », taxations en prose « CODE libellé : base B x T % = M (mode) » ; une base
  suivie d'un code de devise est un montant, pas une quantité ; le mode est le premier mot qui le dit.

## D-1804 — Date d'acceptation dans une phrase ; dates en lettres

Sans libellé de date lu, la date de la phrase qui porte un mot d'acceptation (« acceptée … le 18 août 2026 »,
« released … on 11 Mar 2026 », « … am 7. September 2026 angenommen ») est retenue, pénalité 0,02 (jamais au-dessus
d'une date sous libellé). Les dates écrites avec le nom du mois (fr / en / de / it / es) sont lues partout.

## D-1805 — OCR : lignes sans code, « 1 » lu « I », lectures contredites

- Ligne d'un tableau de liquidation (article de bloc ou colonne « article ») dont le code est illisible mais dont
  base × taux = montant : gardée sans code, toutes ses valeurs plafonnées à 0,75.
- Numéro d'article « I », « l », « | » dans la colonne des numéros : lu « 1 » avec pénalité 0,25.
- Code de taxe « AQO » corrigé (Q → 0, pénalité) ; mode de paiement « É » lu « E » (pénalité 0,10).
- Montant et « à payer » d'une même ligne en désaccord (sauf « à payer » nul) : les deux lectures OCR sont
  plafonnées à 0,80, même si une autre relation les confirme (décimales perdues : « 12 » / « 12,12 »).
- Montant à zéro de tête suivi d'un chiffre non nul (« 036,48 » : premier groupe de milliers perdu) : pénalité
  0,25, jamais confirmé.

## D-1806 — Mesures

`scripts/mesure_extraction.py --type declaration`, champs obligatoires (exactitude) :
- `bench/corpus_g2` dev : 35,5 % → 85,9 % (M1 89,1 → 93,0 ; M2 43,4 → 62,9 ; M3 20,2 → 77,1 ; M4 19,1 → 100 ;
  M5 10,0 → 100 ; M6 10,1 → 100 ; d0 : 100 % pour les six présentations). Champs clés 49,4 % → 92,1 %.
  Calibration ≥ 0,90 : 4 741 valeurs à 93,8 % → 16 121 valeurs à 99,98 % (4 fausses, lectures OCR confirmées par
  base × taux = montant mais rattachées à un numéro d'article mal lu ou montant entier arrondi).
  Les scans dégradés (d2, d3) restent limités par l'OCR (tableaux sans nombres, page retournée et inclinée).
- `bench/corpus` dev (non-régression) : champs clés 92,6 % (inchangé) ; calibration ≥ 0,90 : 22 882 valeurs, 100 %
  (inchangé) ; 0,80–0,90 : 4 254 valeurs, 98,0 % (inchangé) ; champs obligatoires 81,1 % → 81,2 %. Les lignes de
  taxes sans code (D-1805, ≤ 0,75) ajoutent quelques valeurs fausses de basse confiance dans L1/d2 et L3/d1-d2
  (appariement par clé article / code).

# Généralisation : factures de transitaire

Constat : sur le corpus indépendant `bench/corpus_g2` (split dev, 12 familles de factures de transitaire G1–G12
jamais vues : tableau en paysage, relevé sur plusieurs pages avec reports, en-tête à deux colonnes intercalées,
« € » avant ou après le montant, TVA par ligne ou récapitulative, débours en annexe, factures allemandes,
italiennes, espagnoles, néerlandaises et anglaises, tampons et filigranes sur les montants, annotations
manuscrites, totaux en tête de page, remise négative, XML UBL et CII seuls), l'extracteur `ft_regles` ne lisait
que 51,0 % des champs obligatoires et D1 produisait 15 « écarts certains » dont 14 faux (lignes manquantes ou
mal attribuées lues à 0,97 alors que les totaux étaient justes). Règles générales, sans code de gabarit, nom de
fichier ni nom fictif ; vocabulaire dans `extract/deterministe/_ft_langues.py`, nettoyage des surimpressions dans
`_ft_nettoyage.py` ; tests sur des PDF reportlab propres aux tests
(`tests/extract/test_facture_transitaire_generalisation.py`).

## D-1901 — Vocabulaire multilingue (fr, en, de, it, es, nl), table des natures unique

- **En-têtes de colonnes** (`VOCABULAIRE_COLONNES`) : Leistung / Menge / Einzelpreis / Betrag, Descrizione /
  Q.tà / Prezzo / Importo / Cod. IVA, Concepto / Cant. / Precio / Importe / Cuota IVA, Omschrijving / Aantal /
  Bedrag… Nouveaux rôles : `pos` (n° de position, jamais le libellé) et `ttc` (« Montant TTC », « Brutto » :
  jamais lu comme montant HT). Deux colonnes « montant » : la première est le HT, les suivantes un TTC. Un
  qualificatif accolé (« P.U. **HT** », « Prix (EUR) ») prolonge la colonne précédente au lieu d'en ouvrir une.
- **Libellés d'en-tête** : numéro (« Nr. », « N. », « N.º », « Rechnungsnummer », « Invoice / Facture … »),
  date (« Datum », « Data », « Fecha », « … del 3 marzo 2026 », « Lyon, le … », date seule sous le numéro),
  client (« Rechnungsempfänger », « Cliente », « Klant », « Importer / Destinataire »), titres de transport
  composés (« LTA / B/L / CMR: », « Air waybill / B/L » en tête de colonne : références alignées dessous),
  facture d'origine et motif d'un avoir (« Ursprungsrechnung », « Grund », « Oorspronkelijke factuur »,
  « Reden »…). Numéro en deux mots (« RG 2026-46020 », « FACTURE MDF 84826 » : préfixe de 2 à 4 capitales puis
  partie chiffrée) ; libellé en tête de colonne (« Nr. | Datum | Btw-nr. ») : valeur juste dessous (0,93).
- **Dates** (`normalize/dates.py`) : mois allemands, italiens et néerlandais ajoutés (« 5. März 2026 »,
  « 1 dicembre 2026 », « 12 maart 2026 »).
- **Natures** (`normalize/natures.py`, table unique D-1213, aussi utilisée par les exports structurés) :
  Zollabgaben, Einfuhrumsatzsteuer, Verzollung, Vorlageprovision, Lagergeld, Umschlag, Zustellung ; dazi
  doganali, IVA all'importazione, sdoganamento, commissione anticipo, magazzinaggio, movimentazione, consegna ;
  aranceles, comisión por anticipo, partidas adicionales ; invoerrechten, btw bij invoer, inklaring,
  voorschotprovisie, opslag, behandeling, bezorging ; « additional entry lines ». Tous les libellés des deux
  corpus dev reçoivent la nature de leur vérité.
- **Totaux** : Summe Auslagen / Nettobetrag gesamt / MwSt. / Rechnungsbetrag, di cui anticipazioni / Totale
  imponibile / Totale documento, Total suplidos / Total sin IVA / TOTAL FACTURA, Totaal voorschotten / Totaal
  excl. btw / Totaal incl. btw, « Total droits et taxes » (= débours). Sous-totaux de prestations seuls (« Summe
  Leistungen netto », « Base imponible », « Total charges (net) ») : ignorés. La TVA **à l'importation**
  (« IVA de importación », « Einfuhrumsatzsteuer ») n'est jamais le total de TVA de la facture.

## D-1902 — Totaux n'importe où sur la page

- Libellé d'un total : d'abord le texte **immédiatement à gauche** du montant (segment voisin, sans « € » ni
  « EUR »), puis, à défaut, toute la ligne (règle antérieure) : un bloc de totaux posé à droite du pavé client,
  en tête de page, se lit (« Optique SARL ‖ Totale documento ‖ € 924,51 »).
- Libellé seul sur sa ligne, montant seul juste en dessous et aligné (« NET À PAYER » / « 1 695,28 € ») : lu à
  0,93.
- Lignes de report (« Carried forward », « Brought forward », « À reporter », « Übertrag », « Riporto »,
  « Suma y sigue », « Over te brengen ») : ni total, ni ligne, ni fin de tableau.

## D-1903 — Tableaux : plusieurs pages, intertitres, annexe, tableaux côte à côte, MRN de ligne

- **Report de page** sauté sans clore le tableau ; l'en-tête répété en page suivante rouvre la lecture.
- **Intertitre** (« DÉBOURS (HORS CHAMP DE TVA) », « PRESTATIONS ») ou suite de libellé entre deux rangées,
  sans chiffre : sauté si la ligne suivante est une rangée du tableau ; une ligne chiffrée sans montant lisible
  (« 2,5 % x 376,64 ») est une rangée illisible et clôt la lecture (sauf bruit OCR) ; une rangée lue mais
  illisible compte comme rangée.
- **Deux tableaux côte à côte** (« Item Qty Amount | Item Qty Amount ») : l'en-tête est scindé à chaque colonne
  de libellé répétée (chaque groupe ayant sa colonne de montant) ; chaque tableau lit sa bande horizontale.
- **Segment à cheval sur deux colonnes** (« 95,00 A 20,00% » serrés) : découpé mot par mot selon la colonne qui
  contient chaque mot.
- **Montants** : « €45.00 », « 60,87€ », « EUR 792.16 », « 478,65 € » lus comme montants et attribués à leur
  colonne (symbole et code de devise font partie de la cellule numérique).
- **Annexe de débours** : une ligne dont le libellé renvoie à une annexe (« Suplidos según anexo », « see
  annex », « siehe Anlage », « vedi allegato », « zie bijlage ») est écartée quand son montant est égal à la somme
  des lignes d'un autre tableau du document (le détail de l'annexe, lu sur sa page) ; sinon elle est gardée.
- **MRN de ligne** : un tableau dont la colonne de référence ne porte **que** des MRN (cellule vide sinon) ne
  rattache pas le MRN unique du document aux lignes sans MRN ; une colonne mixte (« MRN / détail ») garde la
  règle antérieure. Ligne de suite qui ne porte qu'un MRN (« [26FR…] » sous le libellé) : MRN de la rangée
  précédente. Code d'une colonne sans en-tête reconnu (« A », « E ») imprimé avant le libellé : hors libellé.
- `3,00 × 3` dans le libellé ou la base de calcul : prix unitaire × quantité retenus seulement s'ils redonnent
  le montant de la ligne (règle du détail étendue au libellé et à la base de calcul).

## D-1904 — Tampons, filigranes, annotations manuscrites (texte natif)

`_ft_nettoyage.retirer_surimpressions`, avant la lecture : (a) mot court (1–2 lettres, sans chiffre) de hauteur
≥ 2 fois la médiane de la page, ou tout mot ≥ 4 fois la médiane : glyphe de tampon ou de filigrane (« A
C Q U I T T É » glissé entre « Total HT » et « 1 637,25 € », « COPIE » en diagonale) ; (b) suite d'au moins
4 glyphes isolés rapprochés (dont 3 lettres ou chiffres) dont au moins la moitié des boîtes voisines se
chevauchent : écriture manuscrite (« Bon pour accord », « Dossier n° 962 ») ; les signes espacés d'une légende
(« A = TVA 20 % ; E = … ») ne sont pas touchés. Les glyphes sont retirés **avant** la recherche d'écriture
manuscrite (sinon le « 1 » des milliers, jointif au tampon, disparaissait). Lignes reclassées de haut en bas.
Le texte de la page (ancrage) n'est pas modifié. Les pages OCR ne sont pas traitées (boîtes peu fiables : retirer
un tiret y fusionnait deux en-têtes de colonnes).

## D-1905 — OCR : lignes parasites, en-tête sur deux lignes, montant illisible

- Ligne de taches (fragments de 5 caractères au plus, sans chiffre ni montant) entre deux rangées : ignorée.
- En-tête de tableau découpé par l'OCR sur deux lignes très proches qui ne se recouvrent pas : fusionné si la
  fusion reconnaît plus de colonnes.
- Montant de ligne imprimé mais illisible, quantité et prix unitaire lus : montant `derive` = quantité × prix
  (confiance plafonnée à 0,60, jamais une valeur clé d'écart certain).
- Signes isolés en bout de libellé (« Droits de douane : ») retirés (pas au milieu : l'ancrage serait perdu).

## D-1906 — Avoirs : routage et vocabulaire

`avoir.est_avoir_fournisseur` : un avoir qui cite un MRN ou dont un libellé est une prestation ou un débours de
transitaire (table des natures) est lu par le moteur transitaire, même si son tableau a l'allure d'un tableau
d'articles (« Désignation / Qté / P.U. HT / Montant HT » était pris pour un avoir de vendeur : ligne à 0,80 lue
dans la colonne TTC). Facture d'origine et motif multilingues (D-1901).

## D-1907 — CII : titre de transport et MRN en note d'en-tête

`ingest/structure._remplir_ft` : une note d'en-tête « Titre de transport: … » / « AWB / B/L: … » (CII
`ExchangedDocument/IncludedNote`) donne `refs_transport[]` (sans doublon avec les références de document) ;
« MRN: … » en note d'en-tête complète `refs_mrn[]`. Aucun autre changement de lecture des XML ; UBL inchangé.

**Mesures** (`scripts/mesure_extraction.py`, champs obligatoires) :

`corpus_g2` dev, facture de transitaire (255 documents, 16 230 valeurs), par famille — « hors conventions » :
une valeur déduite (confiance < 0,90) là où la vérité vaut `null` est comptée juste (voir plus bas) :

| famille | valeurs | avant | après | après (hors conventions) |
|---|---|---|---|---|
| G1 | 1168 | 39,1 % | 89,7 % | 90,0 % |
| G2 | 3908 | 66,6 % | 69,5 % | 86,6 % |
| G3 | 1612 | 32,4 % | 65,9 % | 90,8 % |
| G4 | 1066 | 12,2 % | 75,0 % | 80,5 % |
| G5 | 1002 | 17,7 % | 72,7 % | 81,5 % |
| G6 | 1360 | 77,9 % | 79,7 % | 89,4 % |
| G7 | 960 | 100,0 % | 100,0 % | 100,0 % |
| G8 | 666 | 96,2 % | 98,2 % | 100,0 % |
| G9 | 598 | 55,2 % | 66,6 % | 72,1 % |
| G10 | 1266 | 52,2 % | 57,7 % | 89,9 % |
| G11 | 1576 | 32,0 % | 86,7 % | 95,4 % |
| G12 | 1048 | 21,7 % | 85,4 % | 97,9 % |
| toutes | 16230 | 51,0 % | 76,7 % | 89,4 % |

Par dégradation (toutes familles) :

| dégradation | valeurs | avant | après |
|---|---|---|---|
| d0 | 8016 | 58,2 % | 86,3 % |
| d1 | 4684 | 48,8 % | 75,5 % |
| d2 | 1348 | 39,3 % | 63,8 % |
| d3 | 2182 | 36,3 % | 51,8 % |

Avoirs `corpus_g2` (39 documents, 234 valeurs) : 33,3 % -> 88,5 % (fausses 15 -> 3). Corpus d'origine (dev) :
facture de transitaire 83,3 % -> 83,4 % (aucune valeur juste perdue : 16 valeurs absentes deviennent justes,
1 MRN OCR à 0,49 devient faux), avoirs 98,0 % -> 98,0 %.

Calibration (valeurs de confiance ≥ 0,90, justes / lues) : `corpus_g2` facture 3 212 / 3 311 (97,0 %) -> 6 263 /
6 266 (99,95 %) ; avoirs 28 / 30 -> 91 / 91 ; corpus d'origine facture 8 092 / 8 094 -> 8 097 / 8 099 (99,98 %),
avoirs 109 / 109 -> 109 / 109.

Banc complet `corpus_g2` dev (`bench/out/g2_dev_ft2`) : D1 15 écarts certains dont 14 faux -> 3 écarts certains,
3 vrais (précision 100 %, rappel 80 %). Banc d'origine dev (`bench/out/dev_ft2`) : seuil bloquant PASSE,
précision certain 1,000, rappel 0,818 ; D1 inchangé (2 certains, 2 vrais).

**Conventions de vérité non suivies** (comptées « fausses » ci-dessus, volontairement inchangées) : sur
`corpus_g2`, une valeur non imprimée vaut `null` (prix unitaire, taux et montant de TVA d'une facture à TVA
récapitulative, MRN d'une ligne sans MRN, total des débours non imprimé, total des débours imprimé « 0,00 »),
alors que la vérité du corpus d'origine porte les valeurs déduites (prix = montant / quantité, taux d'après le code
ou le taux unique, MRN unique rattaché, total reconstruit). L'extracteur garde les valeurs déduites, toutes
`derive` ou plafonnées (≤ 0,85) : elles ne fondent aucun écart certain. Les trois valeurs « fausses » à 0,97
de `corpus_g2` sont des totaux de débours **imprimés** « 0,00 » dont la vérité est `null`.

# Prudence sur mises en page inconnues

Constat : sur un corpus de mises en page jamais vues (`bench/corpus_g2`, générateur indépendant), le moteur
produisait 49 faux « écarts certains » sur le split dev (B1 24, D1 14, B2 5, D3 2, A5, D4, C5, B3 1) pour 3 vrais.
Cause : des extracteurs réglés sur un autre corpus lisent, sur une mise en page inconnue, des valeurs **fausses à
confiance ≥ 0,90** : séparateur de milliers perdu (« 2 450,57 » lu « 450,57 »), colonne « à payer » (0,00) prise
pour le montant d'une TVA autoliquidée, colonne voisine lue comme montant facturé des articles, lignes de
prestations ou de débours non lues, montant TTC d'une ligne lu comme HT, assiette des frais d'avance de fonds
calculée sur des lignes incomplètes. La confiance ne protège pas : il faut une preuve interne.

## D-1700 — Lecture corroborée : condition supplémentaire de l'« écart certain »

- **Règle** (`controls/corroboration.py`, appliquée par `ControlContext.classify` à **tous** les contrôles) : un
  classement qui serait `ecart_certain` devient `a_verifier`, raison `lecture_non_corroboree`, si un montant
  **lu** (type `montant`, méthode `texte_natif`, `ocr` ou `llm`, après remontée des valeurs dérivées à leurs
  sources) n'est confirmé par **aucune autre identité arithmétique imprimée sur son document** qui tient. Valeurs
  XML/CSV valides et saisies humaines : dispensées (§6.3).
- **Réseau d'identités** d'un document, bâti uniquement sur des valeurs lues (jamais `derive` : une valeur
  déduite reproduirait la lecture qu'elle prétend confirmer) : déclaration — base × taux = montant, totaux par
  taxe, Σ lignes = total des droits et taxes / total à payer (TVA autoliquidée incluse ou exclue), Σ montants
  facturés des articles = total facturé, écho montant facturé de l'article = valeur statistique ou base du droit
  (deux zones distinctes de la page) ; facture du transitaire et avoir — quantité × prix (quantité ≠ 1 :
  « 1 × x = x » ne prouve rien), HT × taux = TVA de la ligne, Σ débours, Σ lignes = total HT (deux
  présentations), Σ TVA des lignes ou Σ HT × taux = total TVA, HT + TVA = TTC, TTC − acomptes = net ; facture
  commerciale — quantité × prix, Σ lignes (+ pieds) = total.
- **Identité contestée** : quand toutes les valeurs clés viennent d'un seul document (B1, B2, B3, D1, E4, G1…),
  les identités entièrement formées des valeurs clés sont le calcul contesté et ne comptent pas comme preuve.
  Somme contestée : le total imprimé est la valeur mise en cause (pas de confirmation exigée), chaque ligne
  sommée doit être confirmée (B1 de la ligne, autre total) ; pour une facture du transitaire, la **complétude**
  des lignes lues doit être prouvée par une autre identité de même portée (débours : total des débours ; lignes
  taxables : total de TVA ; total des débours contesté : total HT). Produit contesté (B1, G1, D1 ligne) : le
  montant imprimé doit être confirmé (par une somme qui le contient) ; les facteurs (base, prix unitaire) sont
  admis si une autre identité de même nature tient sur le document (colonnes lues au bon endroit). B3 : un
  article au plus sans confirmation (l'écart vrai porte sur un article ; les autres prouvent la colonne), au
  moins un confirmé.
- **Libellé** : « à vérifier : la lecture d'un montant n'est confirmée par aucun autre calcul imprimé sur le même
  document (total, somme des lignes) ; une erreur de lecture pourrait expliquer l'écart » (`check_text` vide).
- **Écarté** : relever `C_MIN_CERTAIN` (les lectures fausses étaient à 0,97) ; des règles par mise en page ou par
  gabarit (non générales) ; exiger une confirmation de chaque base et de chaque taux (B1 ne serait plus jamais
  certain : aucune autre identité ne contient ces valeurs).
- **Limite assumée** : une base mal lue sur une ligne dont le montant est confirmé par le total, alors qu'une
  autre ligne de la même déclaration tient, reste possible ; aucun cas observé.

## D-1701 — Confirmation par la rangée ; un zéro n'est jamais confirmé par une somme

- Un montant d'une rangée de tableau (ligne de taxation, article, ligne de facture) est aussi confirmé quand un
  **autre** montant de la même rangée figure dans une identité qui tient (hors écho) : la rangée a été lue au bon
  endroit (ex. `montant_a_payer` d'une ligne dont base × taux = montant tient ; HT d'une ligne dont la TVA lue
  entre dans le total de TVA).
- Un opérande nul d'une somme (et un total nul) n'est pas confirmé par cette somme : une valeur lue « 0,00 » dans
  une colonne vide ne change pas la somme (cas de la colonne « à payer » d'une TVA autoliquidée, où le total à
  payer concorde justement sans ces lignes).

## D-1702 — Tests

- `tests/controls/test_corroboration.py` (fictif) reproduit chaque mode de lecture fausse observé et le cas vrai
  correspondant, qui reste certain : séparateur de milliers perdu (B1, B2), colonne « à payer » prise pour le
  montant, B1 sans total imprimé, valeurs structurées dispensées, vrai B2, colonne voisine pour B3 et vrai B3 (un
  article modifié), écho dans la même zone non probant, lignes de prestations / de débours non lues et vrai total
  HT faux (D1), TTC lu comme HT (D1 ligne), déclaration sans ligne de taxation lue (C5), remontée des dérivées.
- Les tests unitaires de logique des familles A à G (`tests/controls/`) bâtissent des documents minimaux sans
  redondance : `conftest.py` y construit le contexte avec `exiger_lecture_corroboree=False` (champ de
  `ControlContext`, toujours vrai en production). Les tests de bout en bout (`test_famille_b1.py`,
  `test_findings_io.py`, `assembly/test_pipeline.py`) l'exigent : leurs déclarations portent désormais un total
  imprimé qui reprend les lignes.

## D-1703 — Mesures

- Corpus d'origine, dev (`dev_calib`) : précision certain 1,000 (inchangée), rappel certain 0,736 (inchangé,
  106 erreurs certaines appariées en certain avant et après). Deux constats certains deviennent `a_verifier`
  (BX0242 A5 et C3, facture commerciale et facture du transitaire scannées dont les totaux ne réconcilient pas les
  lignes lues) ; la vérité les attend `a_verifier` (surclassements 8 -> 6). Aucune perte.
- `corpus_g2`, dev : les extracteurs ont été corrigés en parallèle pendant ce travail ; à code d'extraction égal,
  sans la règle -> avec : faux certains 14 -> 13, vrais certains 44 -> 43, précision 0,759 -> 0,768. Les 13
  restants ne sont pas des lectures fausses (valeurs conformes aux documents) : doublons de composantes (C5 avec
  C1, G5 avec G4), avoirs non imputés (D3, C1), pièges de pied de facture UBL (A5), montant D7 calculé sur le
  forfait, incohérences imprimées non listées par le générateur (B4 masse nette > brute, A1, A5). Perte : GX0078
  D5 (facture du transitaire découpée en deux documents, la première moitié sans aucun total : ses lignes ne
  peuvent pas être confirmées).

# Contrôles : cas révélés par le corpus G2

Constat : sur `bench/corpus_g2` dev (`g2_dev_calib`), 13 faux « écarts certains » restaient après la lecture
corroborée (D-1700) ; ils ne venaient pas de lectures fausses. Analyse cas par cas (documents et `truth.json` lus) :
sept relèvent de la logique des contrôles (corrigés ci-dessous), les autres de conventions de vérité du
générateur G2 ou du correcteur (listés en fin de section, moteur inchangé). Chaque correction a un test unitaire
fictif qui échoue avant et passe après.

## D-2201 — B4 : le dépassement au total qui ne fait que reprendre un article n'est pas un second constat

- **Constat** : un article dont la masse nette dépasse la brute produisait deux constats certains (`nette_brute`
  sur l'article, `nette_total` au total), pour un seul fait (GX0188 : un article ; GX0268 : Σ nettes 7,195 >
  brute totale 4,517, entièrement dû à l'article 1, 3,715 > 0,715).
- **Choix** (`famille_b._b4_declaration`) : `nette_total` est `non_applicable` (raison
  `couvert_par_autre_controle`) quand `Σ nettes − Σ (nette − brute) des articles déjà constatés ≤ brute totale +
  T_MASSE`. Un dépassement au total plus grand que celui des articles reste constaté.

## D-2202 — A5 : condition 7 (lignes de pied) appliquée au montant converti

- **Constat** : A4 vérifiait déjà qu'une ligne de pied (fret, assurance, emballage, remise) explique l'écart ;
  A5 ne le faisait pas. GX0023 (facture UBL en GBP, fret en `AllowanceCharge` lu comme sous-total `fret`) : la
  déclaration reprend les marchandises seules, écart −17,46 EUR = 15,01 GBP de fret au taux imprimé.
- **Choix** : A5 cherche, comme A4, une combinaison de lignes de pied dont la somme **convertie au même taux**
  (arrondie au centime) égale `|écart|` à `T_CONVERSION` près → `a_verifier`, raison
  `ecart_explique_par_ligne_de_pied`, prochaine action avec la phrase de renvoi (comme A4). Sous-totaux structurés
  (UBL/CII) et imprimés traités de la même façon (`_lignes_pied`).

## D-2203 — Grille : une surcharge est rapprochée par son libellé seulement

- **Constat** : « Peak season surcharge » / « Recargo temporada alta » (45,00) étaient comparées au seul poste
  surcharge de la grille (« Security surcharge », 12,00 / 5,00) : D7 = 33,00 / 40,00 au lieu de 45,00 (ligne sans
  poste). Avec deux postes surcharge (corpus d'origine BX0052, « Surcharge haute saison »), la ligne était
  « ambiguë » (plusieurs postes) alors qu'aucun libellé ne correspond.
- **Choix** (`famille_d.rapprocher_poste`) : comme `autre_prestation` (D-704), la nature `surcharge` n'identifie
  pas un poste (carburant, sûreté, haute saison… sont des surcharges distinctes) : poste par libellé reconnu
  seulement ; aucun libellé → sans poste (D7 comme D2) ; plusieurs → ambigu. Un libellé lu sous `C_MIN_CERTAIN`
  reste une valeur clé : la ligne sans poste n'est alors pas certaine.

## D-2204 — E3 : deux copies du même avoir, la mieux lue est imputée

- **Constat** : GX0225, même avoir reçu en PDF natif (ligne ventilée) et en scan (aucune ligne lue) ; même date et
  même numéro : l'identifiant départageait, le scan était « premier » et seul imputé, le natif écarté (E3) ;
  l'avoir sans ventilation ne pouvait rien déduire (D3 15,00 certain au lieu de soldé).
- **Choix** (`_aides_befg.avoirs_doubles`) : ordre de réception = date, numéro, puis copie la mieux lue (lignes
  ventilées utilisables, puis confiance du total), puis identifiant. E3 signale toujours une réception en double.

## D-2205 — Avoir rattaché mais non ventilé : pas d'« écart certain » recouvrable sur cette facture

- **Constat** : GX0136, avoir « Ajustement tarif dédouanement » rattaché par le MRN, dont ni les lignes ni les
  totaux n'ont été lus : D3 20,00 certain alors que l'avoir solde précisément cet écart (piège « écart soldé par
  un avoir rattaché seulement par le MRN »).
- **Choix** (§8.5.1 condition 7, `ControlContext.classify` → `_aides_befg.avoirs_non_ventiles_pour`) : un
  classement `ecart_certain` d'un contrôle à montant `recouvrable` dont un document est une facture du transitaire
  devient `a_verifier`, raison nouvelle `avoir_non_ventile` (« un avoir du même transitaire, rattaché à cette
  facture, n'a pas pu être ventilé par nature ; il peut couvrir tout ou partie de l'écart »), quand le dossier
  contient un avoir imputable (E3 exclu), de même émetteur, rattaché à la facture par les paliers de §17.2
  (facture d'origine, MRN de l'en-tête ou des lignes, référence de transport) et sans aucune ligne ventilée.
  Un avoir ventilé suit l'imputation normale (déduction) ; un avoir sans lien avec la facture est sans effet.

## D-2206 — D : rattachement d'une ligne d'avoir par le MRN de l'en-tête et par le transport

- **Constat** : `_credits_ligne` (D) ne connaissait que le MRN **de la ligne** facturée et ignorait le troisième
  palier : un avoir qui ne cite que le MRN (ou que la référence de transport) n'était pas déduit d'une ligne de
  prestation sans MRN propre, alors que C et E le rattachaient.
- **Choix** : ligne sans MRN → MRN de l'en-tête de la facture (§12.2) ; référence de transport de la facture pour
  le palier « transport » (§17.2) ; même `choisir_par_paliers` qu'en C et E.

## D-2207 — E4 : montants d'avoir comparés en valeur absolue

- Un avoir imprime « -15,00 » sur la ligne et 15,00 en prix unitaire (ou l'inverse) : E4 signalait « −15,00 ≠ 1 ×
  15,00 ». Comme `lignes_credit_depuis_avoir` (montants positifs), E4 compare les valeurs absolues (bruit
  `a_verifier` seulement ; GX0151, GX0225).

## D-2208 — Un avoir déjà déduit par C, D ou G4 n'est pas réimputé par E5/E6

- **Constat** : après D-2204, l'avoir de GX0225 (15,00 dédouanement) soldait D3 (résultat `conforme`) ; E6 ne
  voyait plus cet écart (sans constat) et imputait le même avoir sur l'écart D7 de la même facture (« reste
  30,00 » à relancer) : un avoir compté deux fois.
- **Choix** : C (par catégorie), D (par ligne) et G4 publient `details.ecart_brut_avant_avoirs` quand ils
  déduisent un avoir ; E (`_ecarts_du_dossier`) retient aussi ces écarts soldés (résultats sans constat) comme
  candidats de l'imputation. `EcartImputable.nature` (nature de la ligne facturée, D) : à composante égale, une
  ligne d'avoir est imputée d'abord sur l'écart de même nature (même choix que la déduction ligne à ligne de D) ;
  ordre §17.2 inchangé ensuite.

## D-2209 — Mesures

- `corpus_g2` dev (`g2_dev_ctl`, même code d'extraction que les autres équipes au moment de la mesure ; leurs
  corrections ont été intégrées en parallèle, la référence `g2_dev_calib` est antérieure) : faux certains de la
  liste initiale 13 -> 6 restants, tous hors logique des contrôles (voir ci-dessous) : GX0023 A5, GX0136 D3,
  GX0188 B4, GX0225 D3, GX0225 D7 (montant), GX0263 D7 (montant), GX0268 B4 corrigés. Run complet : précision
  certain 0,768 -> 0,857, 96 VP certains, exactitude des montants 0,977. Les 16 faux certains du run complet :
  7 C5 sans montant (`doublon_composantes`) sur un piège C3, 2 C1 (GX0117, GX0151, convention `avoir_partiel`),
  3 A5 (GX0006, GX0219, GX0269), 1 A1 (GX0001), 3 lectures/découpages (GX0055 B2 : ligne B00 de l'article 4 lue
  comme total de la taxe ; GX0212 B2/B4 : deux versions d'une déclaration fusionnées en un document).
- Corpus d'origine dev (`dev_ctl`) : seuil bloquant PASSE, précision certain 1,000, rappel 0,818, rappel certain
  0,736 -> 0,743 (BX0052 D7 48,00 désormais certain : surcharge sans poste), exactitude des montants 0,959 -> 0,966.

**Conventions de vérité et du correcteur à relayer (moteur inchangé, valeurs vérifiées sur les documents)** :

- **C5 sans montant sur un piège C3** (GX0028, GX0145, GX0159, GX0192, GX0291 ; GX0117, GX0151) : quand C1 (ou
  C4) porte l'écart, C5 garde son classement avec `montant_en_jeu = null`, raison `doublon_composantes` (§8.6). Le
  correcteur le rend « neutre » (`redondant_doublon_composantes`) **sauf** si un piège C3 (« TVA autoliquidée non
  refacturée », équivalents C3 → C5) couvre la même facture : le test des pièges passe avant celui des doublons.
  Le corpus d'origine liste ce C5 comme erreur « Conséquence » ; G2 ne le liste pas.
- **`avoir_partiel` (G2)** : l'excédent de droits sous-jacent (GX0151 : 153,08 refacturés pour 33,08 liquidés,
  avoir 72,00 ; GX0117 : 300,00 d'excédent, avoir 180,00) n'est pas listé, seul E6 l'est ; le corpus d'origine
  liste l'écart (D3/C1 au montant net) **et** E6 (BX0026, BX0105).
- **`ordre_grandeur_incoherent` (A7) sur une déclaration qui imprime un taux** : GX0006 (CSV, `taux_change`
  1,13890, base 1 EUR ; 224 681,50 USD → 197 279,39 EUR, déclaré 78 911,76), GX0219 (XML, 0,91544 CHF ; 1 710,67
  CHF → 1 868,69 EUR, déclaré 747,48), GX0269 (PDF p. 2, 0,92522 CHF ; 3 398,59 CHF → 3 673,28 EUR, déclaré
  7 713,89) ; aussi GX0096 et GX0109 (taux 0,85130 et 0,86374 dans `truth_values`). La description dit « aucun
  taux imprimé » ; l'écart est un A5 (`accepted_control_ids` = A7, A6).
- **GX0001 A1** : la facture IHM2026007998 (page 1) est adressée à Imaginor Distribution SAS (FR57000986893) ; la
  déclaration 26FR7SLOJ4DEOCYHXC (page 2) indique Imaginor Industrie SARL (FR13000149542) ; deux entités du
  client CL11 (cas « entité du groupe différente », certain possible). Non listé (scénario
  `facture_commerciale_sur_deux_dossiers`).

## D-2210 — B2 et B4 : un « écart certain » repose sur une structure de tableau validée

- **Constat** : sur des mises en page inconnues, B2 et B4 produisaient des `ecart_certain` faux alors que chaque
  valeur était lue avec une confiance élevée et que chaque ligne vérifiait base × taux = montant (donc
  « corroborée », D-1700) : c'est l'**assemblage** du tableau qui était faux. Dev `corpus_g2` : GX0055 (ligne
  B00 de l'article 4 dont le numéro n'est pas lu, prise pour le total de la taxe B00), GX0212 (deux versions d'une
  déclaration de même MRN fusionnées en un document : lignes et articles en double, B2 au total et B4 au total).
  Modes décrits sur un autre jeu (non ouvert) : montants de droits rangés sous le code de TVA, lignes d'une seule
  page sommées contre le total de toutes les pages, masses nettes et brutes prises à deux niveaux.
- **Choix** (`controls/structure_declaration.py`, raison nouvelle `structure_non_validee`) : un constat B2 ou B4
  au total qui serait certain devient `a_verifier` quand la forme du tableau lu n'est pas validée ; les règles ne
  regardent que la forme, jamais un taux ni un code ; un `conforme` n'est jamais changé.
  - B2 (catégorie et total) : pas deux lignes du même code pour un même article ni deux articles de même numéro ;
    quand les lignes portent un numéro d'article, chaque article attendu (numéros lus, `1..nombre_articles`) a
    une ligne (total) ou une ligne de ce code (catégorie) ; chaque ligne sommée dont base et taux sont lus vérifie
    base × taux = montant (`T_TAXE_LIGNE`) ; un total de catégorie qui imprime une base reprend Σ bases des lignes
    (`T_SOMME`).
  - Total de catégorie (D-301 précisée, partagée avec le réseau de corroboration) : la ligne sans article n'est
    pas un total de catégorie quand son code n'a pas de ligne pour un article attendu **et** que le total des
    droits et taxes (ou à payer) imprimé n'est retrouvé qu'en la comptant comme ligne ordinaire ; B2 la somme
    alors avec les autres lignes (GX0055, GX0203 : `conforme`).
  - B4 `nette_total` : numéros d'articles uniques ; articles lus = `nombre_articles` s'il est lu ; masse brute
    totale du niveau « total » : Σ masses brutes des articles = masse brute totale quand toutes sont lues
    (`T_MASSE`), sinon les masses brutes lues ne la dépassent pas et elle ne reprend pas celle d'un seul article.
    `nette_brute` (même article) inchangé.
- **Écartés** : seuil de confiance plus haut par ligne (réglage, sans lien avec l'erreur d'assemblage) ; exiger
  la page du total parmi les pages des lignes (un récapitulatif de dernière page est légitime) ; correction de
  l'extracteur (numéro d'article déduit de l'alternance des lignes, dédoublonnage de copies) : non générique à ce
  stade, la segmentation de deux versions de même MRN relève du regroupement.
- **Mesures** (dev seulement) : `corpus_g2` `g2_dev_b2_base` → `g2_dev_b2` : FP certain 4 → 1 (GX0055 B2, GX0212
  B2, GX0212 B4 ; reste un piège C8, GX0078, hors périmètre), VP certain 100 → 100, précision certain 0,962 → 0,990, seuil
  bloquant ÉCHOUE → PASSE ; corpus d'origine `c1_dev_b2_base` → `c1_dev_b2` : identique (113 VP, 0 FP, PASSE),
  aucun constat changé.

## D-2211 — C8 : l'entité facturée attestée par un autre document de l'envoi n'est pas un écart certain

- **Constat** (dev seulement ; sur un jeu non ouvert, 2 C8 certains faux sur des pièges « transitaire facturant
  l'entité importatrice déclarée », comptes agrégés seulement) : `corpus_g2` GX0078 (relevé multi-MRN réparti en
  cinq dossiers ; la facture est adressée à l'acheteur de la facture commerciale, entité du client, importateur de
  quatre des cinq déclarations ; la déclaration du dossier principal désigne une société hors du client),
  GX0230 (même cas sur un envoi, déjà `a_verifier` par la confiance du scan). Le transitaire facture le client ;
  l'écart est celui de la déclaration (A1, déjà certain), et la prochaine action de C8 (« facture au nom de
  l'importateur ») demanderait une facture au nom d'un tiers.
- **Choix** (`famille_c._c8_motifs_non_certain`, raison nouvelle `entite_facturee_attestee`, motifs dans
  `details.entite_facturee_attestee`) : le constat C8 sur numéro de TVA reste émis mais `a_verifier` quand
  1. le numéro facturé est l'importateur d'une **autre déclaration citée par la même facture** (dossier frère qui
     contient la facture) ;
  2. le numéro facturé est l'acheteur d'une facture commerciale du dossier **et** une entité du client, alors
     qu'aucun importateur déclaré n'est une entité du client ;
  3. le numéro facturé est celui de l'émetteur de la facture ou d'un déclarant (bloc d'adresse mal attribué) ;
  4. même SIREN que l'importateur sous un autre identifiant (clé de TVA, EORI lu à la place de la TVA).
  Restent certains : facture adressée à une autre entité du groupe quand l'importateur est une entité du client
  (BX0032, BX0094), facture adressée à une société hors du client (GX0089, BX0136, BX0170).
- **Conflit de conventions assumé** : le corpus d'origine attend `ecart_certain` pour le cas 2 (BX0009, BX0063,
  « Conséquence de A1 », importateur « Société Tierce » hors du client) ; `corpus_g2` en fait un piège plafonné à
  `a_verifier` (GX0078, GX0230). Les deux vérités décrivent la même situation documentaire (vérifié : TVA de
  l'acheteur = TVA facturée, importateur hors des entités du profil) ; aucune règle générale ne les sépare. La
  règle suit le jeu le plus récent et la SPEC §12 C8 (« le transitaire a facturé une autre entité ») : ici il a
  facturé l'entité du client. Coût : 2 C8 certains du corpus d'origine deviennent `a_verifier` (toujours
  détectés). Retirer le motif 2 rétablit l'ancien comportement.

## D-2212 — D5 : la répétition doit être établie

- **Constat** : bruit `a_verifier` non apparié sur dev (`corpus_g2` GX0120, GX0128, GX0152, GX0164 ×2) :
  factures de plusieurs envois dont les lignes de prestation ne portent pas de MRN (ou l'OCR ne l'a pas lu) — une
  ligne « dédouanement » par déclaration, regroupées sous la clé « sans référence ». Sur un jeu non ouvert,
  2 D5 certains faux. Situations légitimes analysées : plusieurs envois, plusieurs contenants ou livraisons,
  ligne et sa correction, ligne reportée d'une page à l'autre, même libellé avec références différentes (clé
  déjà distincte : le libellé normalisé garde les chiffres).
- **Choix** (`famille_d._d5_motifs`, raison nouvelle `doublon_non_etabli`, motifs dans
  `details.doublon_non_etabli`) : un D5 n'est certain que si aucun motif ne s'applique :
  1. lignes sans référence d'envoi alors que la facture cite plusieurs MRN (lectures OCR voisines confondues),
     plusieurs titres de transport ou couvre plusieurs déclarations ;
  2. prestation par contenant (transport, manutention, magasinage, surcharge) sur une facture qui cite au moins
     autant de titres de transport que de lignes répétées ;
  3. deux lignes consécutives sur deux pages (report en haut de page) ;
  4. le total HT imprimé reprend toutes les lignes **sauf** la répétition (artefact de lecture).
  Une ligne de même nature, même libellé et montant opposé annule une copie (correction) : sans copie restante,
  pas de constat. Montant = (copies − 1) × montant.

## D-2213 — D4 : FAF expliqué par une autre assiette, des bornes par envoi, un arrondi ; devise

- **Constat** : bruit `a_verifier` non apparié sur dev (GX0011, GX0018, GX0154 ; BX0099, BX0156, BX0242) : le
  FAF facturé est le pourcentage de la grille appliqué à une autre assiette que celle retenue (ligne « droits et
  taxes » combinée exclue d'une assiette « droits », débours de la facture plutôt que ceux rapprochés…). Sur un
  jeu non ouvert, 1 D4 certain faux.
- **Choix** (`famille_d._assiettes_alternatives`, `_faf_explique`, raison nouvelle `assiette_alternative`) :
  quand le FAF dépasse l'attendu, il est recalculé avec le pourcentage, le minimum et le maximum de la grille
  sur : débours rapprochés de chaque composante (total, hors TVA, droits, droits et autres taxes ; avec et sans
  l'excédent constaté), montants liquidés des déclarations (total, hors TVA, droits), débours imprimés sur la
  facture (total, hors TVA, droits) ; bornes appliquées à la somme ou **par envoi** (Σ bornes) ; égalité à
  `T_TARIF` près, ou à l'arrondi à l'euro (au plus proche ou supérieur). L'attendu arrondi à l'euro est aussi une
  explication. Si l'une tient : `a_verifier` (le montant reste l'écart à la grille).
- Attendu non borné (ni minimum ni maximum atteint) : chaque débours lu de l'assiette devient une valeur clé
  (confiance, lecture corroborée D-1700) : une ligne de débours mal lue change l'attendu.
- `_comparer_tarif` (D3, D4, D6, D7) : facture du transitaire dont la devise lue n'est pas l'euro (grille en
  euros) → raison `devise_incertaine`.

## D-2214 — Mesures (dev seulement)

Tests : `tests/controls/test_precision_c8_d4_d5.py` (17 cas fictifs). Bancs `g2_dev_b2` → `g2_dev_cd`,
`c1_dev_b2` → `c1_dev_cd` :

| | `corpus_g2` avant | après | corpus d'origine avant | après |
|---|---|---|---|---|
| VP / FP certain (global) | 100 / 1 | 100 / 0 | 113 / 0 | 111 / 0 |
| précision certain | 0,990 | 1,000 | 1,000 | 1,000 |
| rappel / rappel certain | 0,823 / 0,676 | 0,823 / 0,676 | 0,818 / 0,743 | 0,818 / 0,729 |
| violations de pièges | 49 | 48 | 36 | 36 |
| C8 VP / FP certain, violations | 1 / 1, 1 | 1 / 0, 0 | 6 / 0, 0 | 4 / 0, 0 |
| D4 VP / FP certain | 4 / 0 | 4 / 0 | 2 / 0 | 2 / 0 |
| D5 VP / FP certain | 3 / 0 | 3 / 0 | 3 / 0 | 3 / 0 |

Seuil bloquant PASSE sur les deux. Aucun autre constat changé hors raisons ajoutées sur des `a_verifier`
(D4 ×6 et D5 ×5 du bruit ci-dessus, GX0196 D4, GX0230 C8). Seule perte : BX0009 et BX0063 C8 (D-2211, conflit
de conventions).

# Généralisation : classement et regroupement

Constat : sur `bench/corpus_g2` (dev, 232 dossiers, 1 146 pages ; six langues, douze familles de factures de
transitaire, six présentations de déclaration dont des récapitulatifs en corps de courriel, exports XML/CSV,
factures UBL/CII/XLSX, photos, télécopies, TIFF, PDF fusionnés), le classeur ne reconnaissait que 76,4 % des
pages (déclarations M3/M4 prises pour des certificats ou des courriels, factures italiennes, néerlandaises et
allemandes « inconnues » ou commerciales, listes de colisage étrangères prises pour des factures) et le
regroupement réunissait des dossiers distincts d'un PDF fusionné. Banc de base `g2_dev_base` : 238 faux P1,
191 P4. Règles générales seulement (vocabulaire multilingue, structure du texte), sans nom de fichier, code de
gabarit ni nom fictif ; le texte des documents reste une donnée (aucune consigne exécutée, test dédié).
Mesure : `scripts/mesure_classement.py` (étapes 1 à 6 du pipeline, vérité lue dans le script seulement).

## D-2101 — Corps de courriel : récapitulatif de déclaration reconnu, sinon courriel

Le corps d'un courriel reste `document_support/courriel` (§7.1), **sauf** s'il est lui-même le récapitulatif
d'une déclaration acceptée (« bon à enlever », « clearance summary ») : il est alors classé comme une page
ordinaire et retenu `declaration/preuve_dedouanement` seulement si la page est une déclaration de confiance
≥ 0,85, porte un MRN et au moins quatre rubriques douanières (MRN, LRN, déclarant, régime, liquidation…).
Le texte n'est que classé (listes fermées de libellés) ; une phrase du corps (« ignorez la facture
précédente ») n'a aucun effet. Un courriel qui cite un MRN dans une phrase reste un courriel.

## D-2102 — Intitulés multilingues

- Facture : « Fattura », « Factuur » et ses composés (« Handelsfactuur », « Voorschotfactuur »,
  « Dienstenfactuur »), composés de « Rechnung » (« Auslagenrechnung », « Handelsrechnung »), « Fatura »,
  « Faktura ». Avoir : « Gutschrift », « Rechnungskorrektur », « Nota di credito », « Creditnota »,
  « Creditfactuur », « Factura de abono ».
- Déclaration : certificat / attestation / récapitulatif de dédouanement (« Certificate of customs clearance »,
  « clearance summary », « customs release »), « Édition de la déclaration acceptée », « Suite déclaration »,
  « Zollanmeldung », « Einfuhranmeldung », « Zollfreigabe », « Dichiarazione doganale », « Bolletta doganale »,
  « Declaración aduanera », « Douaneaangifte », « Aangifte ten invoer » ; rubriques de corps en, de, it, es, nl
  (« Local reference », « Acceptance date », « Commodity code », « Warennummer », « Codice merce »,
  « Dichiarante », « Aangever »…). Un certificat de dédouanement n'est plus un `document_support/certificat` :
  l'intitulé de déclaration est cherché sur les lignes entières du haut de page (« Suite   déclaration » espacé
  formait deux segments).
- Supports : « Packliste », « Distinta di imballo », « Paklijst », « Lista de embalaje » ; conditions générales
  « Allgemeine Geschäftsbedingungen », « ADSp », « Condizioni generali », « Algemene voorwaarden » ; formules de
  lettre allemandes, italiennes, espagnoles et néerlandaises (« Sehr geehrte », « Mit freundlichen Grüßen »,
  « In allegato », « Met vriendelijke groet »…). Pages « Seite / Blatt / pagina n di m », « Übertrag »,
  « Riporto », « Suma y sigue ». Langue détectée : de, it, nl en plus de fr, en, es (information seulement).

## D-2103 — Facture de transitaire ou facture commerciale : vocabulaire, pas mise en page

Débours et prestations de dédouanement multilingues comptés comme signaux forts (« Auslagen »,
« Vorlageprovision », « Verzollung », « anticipazioni », « commissione anticipo », « sdoganamento »,
« despacho de aduanas », « voorschotten », « inklaring »…) ou de corps (« Zollabgaben », « Einfuhrumsatzsteuer »,
« Lagergeld », « dazio », « IVA all'importazione », « aranceles », « invoerrechten », « opslag »…) ; signaux de
facture commerciale en de, it, es, nl (« Warentarifnummer », « Ursprungsland », « voce doganale », « Resa »,
« GN-code », « Oorsprong », « Nettogewicht »…). Le sous-type « sans valeur / valeur en douane » (mentions de corps,
« free of charge ») ne retient plus en facture commerciale une page de débours (seul « pro forma » le fait).

## D-2104 — Intitulé ou rubrique citée

Ne sont plus des intitulés : un libellé de titre précédé d'un mot qui porte un chiffre (« N380 Facture
commerciale » : rangée d'un tableau de documents), d'un mot de citation (« Ref. invoice », « Votre facture »,
« Ihre », « uw »), suivi de « currency / value / amount / total » (« Invoice currency / total » d'une déclaration)
ou d'une barre (« AWB / B/L : » est une étiquette de champ, pas un titre de transport). Les signes isolés (« / »,
« — ») ne comptent plus comme mots avant l'intitulé (« STATEMENT / INVOICE »). Un intitulé que l'OCR a espacé
lettre à lettre (« HAN DE LS FACTU U R ») est relu sans les blancs.

## D-2105 — À niveau égal, l'intitulé le plus haut l'emporte

Un document support titré au même niveau qu'une mention « facture » est support si son intitulé est plus haut sur
la page et qu'aucun débours n'est lu (« BILL OF LADING » en tête, « Invoice IHM… » cité en grand corps plus bas).

## D-2106 — Déclaration malgré une mention « facture »

MRN (ou page de suite) et au moins huit rubriques de déclaration, sans débours, sans intitulé d'avoir et avec
moins de trois signaux de facture commerciale : la mention « facture » est une rubrique citée, la page est une
déclaration (score de corps plafonné à 0,50 au lieu de 0,40) ; une page de suite sans MRN lisible qui
n'atteint pas le seuil est une `continuation` (0,75), jamais une facture de transitaire.

## D-2107 — Avoir par total négatif : pas sur un tiret isolé

Un total « négatif » ne fait plus un avoir quand un montant à payer est imprimé positif (« Total débours   -
975,38 € » d'une télécopie suivi de « Net à payer 1 173,99 € ») : facture de transitaire.

## D-2110 — Plusieurs dossiers candidats : référence explicite, sinon départage

Une référence explicite (facture citée, transport, MRN) peut rattacher un document à plusieurs dossiers (plusieurs
factures pour une déclaration, facture mensuelle) : seuls ces dossiers sont gardés. Sans référence explicite
(PDF fusionné où « même fichier » vaut pour tous les dossiers), le meilleur score l'emporte ; à égalité, une
déclaration va au seul dossier qui n'en a pas encore, puis tout document au dossier du document qui le précède
immédiatement dans le même fichier ; sinon la règle antérieure (tous les candidats). Auparavant, une déclaration
liée à cinq factures par le seul « même fichier » (score 2) réunissait les cinq dossiers.

## D-2111 — Pas de repli « même source » entre déclarations sans facture

Le repli `meme_dossier_source` (dossier unique de la frontière) ne rattache plus une déclaration à un dossier
**sans facture commerciale** qui contient déjà une déclaration d'un autre MRN : chacune forme son dossier
(P1 vrai : facture absente). Avec une facture, le repli reste possible (facture répartie sur plusieurs
déclarations, §7.5 étape 8).

## D-2112 — Référence citée univoque

Une référence citée compatible (§8.4, inclusion) avec les numéros de **plusieurs** documents du lot (référence
tronquée par l'OCR, « ODH 2026 ») ne désigne aucun d'eux : `ref_facture_citee` exige l'égalité ou une
compatibilité univoque (facture commerciale pour les déclarations, supports et factures de transitaire ;
facture de transitaire pour les avoirs et lettres).

## D-2113 — Découpage : relevé sur plusieurs pages, suite de déclaration au MRN abîmé, page de tête illisible

- « Page 2 » seul sur sa ligne (sans total) est lu comme numéro de page (`extraire_refs`) : la page 2 d'un relevé
  de transitaire qui répète l'en-tête sans numéro de facture lisible rejoint la page 1 (règle « page n > 1 »
  existante) au lieu de former une seconde facture.
- `ClassementPage.suite` : le haut de page annonce une suite (« Suite », « page 2/2 », « Fortsetzung »…). Une page
  de déclaration qui l'annonce reste dans la déclaration en cours quand son MRN, abîmé par l'OCR au-delà de deux
  confusions, en est **voisin** (même année et pays, au plus 4 caractères différents sur le préfixe de 15) ; deux
  MRN distincts diffèrent sur presque tous leurs caractères aléatoires, et une page sans « suite » (ou
  « page 1/n ») commence toujours une nouvelle déclaration.
- Confiance d'un document : relevée par une page **intitulée** du même type et de plus haute confiance (première
  page illisible, page 2 « COMMERCIAL INVOICE » lisible) — le document n'est plus `inconnu` à tort.
- Pages retournées (non appliqué) : l'OSD de Tesseract rend parfois un verdict confiant faux (page G2 lue à 180°,
  confiance OCR 0,26 après rotation). Proposition : quand la confiance OCR après rotation OSD est < 0,40, essayer
  aussi les autres orientations (dont 0°). Ce changement de `ingest/pages.py` impose de relever
  `VERSION_PAGES` (clé du cache et de l'étape 2), donc de refaire l'OCR des deux corpus : non « bon marché », laissé
  à l'équipe robustesse. Les pages concernées restent `inconnu` (dégradation prudente, 7 pages G2 dev).

**Mesures** (`scripts/mesure_classement.py`, caches `var/cache/g2_pages` et `var/cache/pages` ; regroupement : paires
de documents de vérité liés par `expected_links`, un document étant dans le groupe des documents qu'il cite) :

| corpus dev | pages : type | type + sous-type | regroupement P / R / F1 | liens faibles | dossiers incomplets |
|---|---|---|---|---|---|
| `corpus_g2` avant | 76,4 % | 74,9 % | 0,877 / 0,817 / 0,846 | 79 | 157 |
| `corpus_g2` après | 99,4 % | 98,3 % | 0,955 / 0,963 / 0,959 | 33 | 33 |
| `corpus` avant | 97,8 % | 96,7 % | 0,768 / 0,951 / 0,850 | 51 | 34 |
| `corpus` après | 97,9 % | 96,8 % | 0,808 / 0,950 / 0,873 | 50 | 34 |

Pages G2 encore mal classées (7) : pages retournées ou illisibles à l'OCR, rendues `inconnu` (0,30–0,65), jamais
un type confiant faux. Banc complet `corpus_g2` dev (`bench/out/g2_dev_grp`, contre `g2_dev_base`) : faux P1
238 -> 29, P1 détectés 2/4 -> 4/4, P4 191 -> 30, regroupement du banc F1 0,912 -> 0,981 ; les 16 « écarts
certains » faux restants (C5 sur pièges 7, A5 3, B2 2, C1 2, A1 1, B4 1) sont tous dans des dossiers aux liens
`forte` par références explicites (extraction et contrôles, hors regroupement). Banc d'origine dev
(`bench/out/dev_grp`) : seuil bloquant PASSE, précision certain 1,000, rappel 0,818, rappel P1 1,0, faux P1 25
(inchangé), P4 48 -> 47, regroupement du banc F1 0,965 -> 0,965.

# Généralisation : factures commerciales

Constat : sur `bench/corpus_g2` (split dev, 288 factures commerciales en 11 présentations : allemande en francs
suisses, italienne, néerlandaise, espagnole, française, quatre anglaises dont une chinoise bilingue et une indienne,
UBL, XLSX ; pro forma ; scans, photos, télécopies), les champs obligatoires de la facture commerciale n'étaient
exacts qu'à 61,9 % (champs clés 61,3 %), 65 valeurs de confiance ≥ 0,90 étaient fausses (98,4 %), et les listes de
colisage n'étaient pas lues du tout (0 %). Règles générales, sans nom de fichier, code de présentation ni nom
fictif ; vocabulaire dans `extract/deterministe/_fc_langues.py`, aides de mise en page sans état dans
`_fc_regles.py` ; `_mise_en_page.py` inchangé. Tests sur des PDF reportlab propres aux tests
(`tests/extract/test_facture_commerciale_generalisation.py`).

## D-2001 — Vocabulaire multilingue (de, it, nl en plus de fr, en, es)

- Numéro (« Rechnung Nr. », « Rechnungsnummer », « Fattura n. », « Factuurnummer », « Invoice number ») ; un
  numéro en deux mots, préfixe de 2 à 4 capitales puis partie chiffrée (« FT 4800/2026 », « ODH 2026.3681 »), est
  lu entier. « n. o… » n'est pas « n° » (le libellé doit finir sur une frontière de mot).
- Date (« Datum », « Data », « Factuurdatum », « Issue date ») ; devise (« Währung », « Valuta ») ; conditions de
  livraison (« Lieferbedingungen », « Resa », « Leveringsvoorwaarden », « Terms: ») ; titre de transport
  (« CMR-Frachtbrief », « Polizza di carico », « Luchtvrachtbrief », « Transport document », « Ref. ROAD: »).
- Pavés : acheteur (« Rechnungsempfänger », « Kunde », « Intestatario », « Factuuradres », « TO (BUYER): »), livré
  à (« Lieferadresse », « Destinatario merce », « Afleveradres »), vendeur (« Verkäufer », « Fornitore »…).
- Masses et colis (« Bruttogewicht », « Peso lordo », « Brutogewicht », « TOTAL G.W.: », « Gross 433.696 kg »,
  « Packstücke », « Colli ») ; totaux (« Rechnungsbetrag CHF », « Totale fattura », « Totaal », « Total due (INR) »,
  « Zollwert ») ; sous-totaux (« Warenwert », « Totale merce », « Subtotaal » ; « Fracht », « Vracht », « Nolo » ;
  « Versicherung » ; « Imballo », « Verpackung » ; « Rabatt », « Sconto », « Korting ») ; un libellé de document
  (« Transport document », « Frachtbrief ») n'est jamais une ligne de fret.
- Colonnes : « Zolltarifnr. », « Voce doganale », « GN-code », « Fracción arancelaria », « N° tarif douanier »,
  « Tariff no. » (code) ; « Ursprung », « Herkunft », « Oorsprong », « C/O », « COO » (origine) ; « Menge »,
  « Q.tà », « Aantal » ; « Einh. », « U.M. », « Eenh. » ; « Einzelpreis », « Prezzo unit. », « Prijs » ;
  « Gesamtpreis », « Importo », « Bedrag », « Line total ». La mention « (Incoterms® 2020) » ne fait pas partie du
  lieu de livraison.

## D-2002 — En-tête du tableau des lignes

`_fc_regles.nettoyer_colonnes` et `scinder_mots_colles`, appliqués à la ligne d'en-tête retenue (repérée une fois
par page, `_reperer_entetes`) :
- code de devise accolé au libellé d'une colonne de prix ou de montant (« Amount CNY », « Importo EUR ») : rattaché à
  cette colonne au lieu d'ouvrir une colonne inconnue qui volait les montants alignés à droite (toutes les lignes
  sauf la première étaient perdues) ; en tableur, seule l'étendue du mot du code est rattachée (la cellule voisine
  soudée reste inconnue) ;
- mots soudés par l'extraction du texte (« arancelariaOrigen », « UnidadPrecio ») redécoupés à la frontière
  minuscule → majuscule ;
- deuxième colonne « numéro » (« NO. | ITEM NO. ») lue comme référence d'article ; deuxième colonne « article »
  sans colonne de désignation (« SKU | Item ») lue comme désignation.

## D-2003 — Devise sans libellé « devise »

Indices, dans l'ordre de la règle antérieure (libellé, puis code accolé à la valeur du total) : code ISO accolé à
une colonne de prix ou de montant ou imprimé sous elle (« (USD) »), code dans le libellé d'un total (« TOTAL CNY »,
« Total due (INR) ») ou sa valeur, symbole à côté du total. Symboles univoques € £ ₩ ₹ ₺ ; « ¥ » (CNY ou JPY) et
« $ » ne sont résolus que si un seul code ISO compatible est imprimé sur le document, sinon devise inconnue
(0,30). Un seul code : 0,90 (0,95 si en-tête de colonne **et** total le donnent ; OCR 0,85 / 0,90) ; plusieurs
codes : celui du total à 0,60. Une devise lue sous libellé que contredisent ces indices est plafonnée à 0,60.

## D-2004 — Nom du vendeur sans libellé

Titre à gauche et émetteur à droite sur la même ligne (« HANDELSFACTUUR   Société X N.V. ») : le segment de droite
est le nom. Un libellé « vendeur » placé après le pavé acheteur (« Expediteur: » d'un transitaire en pied) n'ouvre
pas le pavé de l'émetteur (il donnait 0,90 à une ligne d'adresse). Un couple « Date: … » ou un identifiant
majoritairement chiffré (« CHE-000.000.001 MWST ») n'est jamais un nom (sa TVA reste lue).

## D-2005 — Masses écrites sur une même ligne

« Net weight: 1.0 kg   Gross weight: 1.2 kg » : à défaut de libellé en tête de segment, le libellé est cherché au
milieu du segment (frontière de mot) et la valeur lue dans le reste du segment seulement.

## D-2006 — Normalisation (ajouts)

`normalize/amounts.py` : groupement indien (« 1,23,456.00 », « 12,34,56,789 » : groupes de 2 chiffres puis un
dernier de 3, virgule seulement). `normalize/units.py` : Stück, Stk., pezzi, pz, stuks, Paar, paia, litri, metri ;
correction : les mots d'un libellé de plusieurs mots (« metre cube ») ne remplacent plus l'unité simple
(« metre », « meter » étaient lus MTQ).

## D-2007 — Chiffres de la désignation débordant dans la colonne du code

« Taladro 18 V | 8467.21 », « Martillo 500 g 8205.20.00.00 » : sur la première ligne de la rangée, seul le dernier
groupe de mots contigus de la cellule du code est gardé ; à défaut de code valide, le plus long suffixe qui forme un
code de 6, 8 ou 10 chiffres ; confiance plafonnée à 0,85 quand des mots sont écartés.

## D-2008 — Origine déclarée pour toute la facture

Sans colonne d'origine, « Country of origin: China (CN) » (« Ursprungsland », « Paese d'origine », « Land van
oorsprong »…) est reporté sur chaque ligne, lecture ancrée sur cette mention, confiance ≤ 0,85.

## D-2009 — Rangées lues par OCR

- Une rangée s'ouvre aussi sur une référence d'article et une quantité lues quand le montant est illisible (sinon
  les rangées suivantes étaient décalées, et quantité × prix = montant les portait à 0,92 sous le mauvais rang) ;
  un montant imprimé seul une ligne plus bas lui est rattaché (≤ 0,85).
- Filets du tableau lus comme du texte (« | », « _ ») retirés des cellules (« 1'000 | kg », « TW | »).
- En-tête de quantité illisible mais colonne d'unité reconnue : « 50 kg » lu sous « Eenh. » donne quantité et unité
  (≤ 0,85).
- Prix unitaire OCR sans séparateur (« 485 ») : le prix ÷ 10ᵏ qui redonne exactement le montant est retenu, ≤ 0,60.

## D-2010 — Documents support : listes de colisage

Libellés « Ref. invoice / facture: », « Rechnung Nr. », « Fattura n. » (numéro en deux mots admis ; une date n'est
jamais un numéro de facture), « Transport: », « Frachtbrief », « Packages / colis: », « Packstücke », « Colli ».
Masse brute (et nette) lue sur la ligne de total du tableau des articles (« Total », « Summe », « Totale »,
« Totaal ») dans la colonne de son en-tête (« Gross kg », « Brutto kg », « Lordo kg », « Bruto kg ») ; nombre le plus
proche de l'en-tête quand la cellule en porte plusieurs (colonne voisine illisible). Séparateur décimal tiré de la
colonne : un nombre qui porte les deux signes, ou des milliers groupés par apostrophe ou espace, le donnent ; des
masses toutes écrites « d,ddd » sont présumées au gramme près (§5.2 ; ≤ 0,85 sauf « 0,ddd »). Confiance 0,95
(OCR 0,90) seulement si la somme des lignes redonne le total.

## D-2011 — Avoirs fournisseurs

Libellés allemands, italiens, néerlandais (« Gutschrift Nr. », « Nota di credito n. », « Creditnota nr. »,
« Ursprungsrechnung », « Fattura di riferimento », « Oorspronkelijke factuur », « Grund », « Causale », « Reden »).
Le motif (« Grund: Transportschaden ») n'est plus pris pour un libellé de prestation de transitaire dans le
routage `est_avoir_fournisseur`. Aucun avoir fournisseur dans `corpus_g2` dev (tous de transitaire).

## D-2012 — Mesures

Outil : `scripts/mesure_extraction.py` ; la comparaison des `sous_totaux` (champ facultatif) ignore désormais le
sous-total des marchandises des deux côtés (la vérité de `corpus_g2` le porte, la lecture ne le compare pas ; aucune
vérité du corpus d'origine ne le porte). Champs obligatoires (valeurs justes ou absentes des deux côtés) :

`corpus_g2` dev, facture commerciale (288 documents, 7 527 valeurs) : 61,9 % → 86,2 % ; champs clés (acheteur.tva,
devise, numéro, total) 61,3 % → 95,8 %.

| langue | valeurs | avant | après |  | présentation | avant | après |  | dégradation | avant | après |
|---|---|---|---|---|---|---|---|---|---|---|---|
| de | 698 | 46,0 % | 83,4 % | | CA (en) | 56,4 % | 79,8 % | | d0 | 78,1 % | 100,0 % |
| en | 4 298 | 72,8 % | 86,8 % | | CB (de) | 46,0 % | 83,4 % | | d1 | 49,9 % | 81,5 % |
| es | 868 | 38,8 % | 77,1 % | | CC (it) | 54,5 % | 97,0 % | | d2 | 44,8 % | 70,7 % |
| fr | 710 | 57,6 % | 90,0 % | | CD (nl) | 32,2 % | 71,8 % | | d3 | 26,9 % | 46,2 % |
| it | 708 | 54,5 % | 97,0 % | | CE (es) | 38,8 % | 77,1 % | | | | |
| nl | 245 | 32,2 % | 71,8 % | | CE2 (en) | 67,7 % | 72,8 % | | | | |
| | | | | | CF (en/zh) | 77,3 % | 95,9 % | | | | |
| | | | | | CG (en, INR) | 72,6 % | 89,5 % | | | | |
| | | | | | CH (fr) | 57,6 % | 90,0 % | | | | |
| | | | | | CK (XLSX), CU (UBL) | 100 % | 100 % | | | | |

Pro forma 61,9 % → 82,0 %. Les pertes restantes sont surtout des scans : l'OCR mis en cache ne restitue pas les
colonnes de droite de tableaux à filets (quantité, prix, montant absents du texte) ou les brouille (télécopie,
photo) ; non corrigeables à l'extraction.

Calibration (justes / lues) `corpus_g2` : ≥ 0,90 3 888 / 3 953 (98,4 %) → 6 560 / 6 560 (100 %) ; 0,80–0,90
1 113 / 1 251 → 2 006 / 2 057 ; 0,50–0,80 1 150 / 1 344 → 317 / 411.

Documents support `corpus_g2` (105 documents, 375 valeurs) : 31,5 % → 88,0 % (listes de colisage 0 % → 88,3 % ;
d0 37,7 % → 100 %) ; ≥ 0,90 49 / 49 → 148 / 148. Avoirs `corpus_g2` : 88,5 % → 88,5 % (91 / 91 ≥ 0,90).

Corpus d'origine (dev, non-régression) : facture commerciale 84,0 % → 84,1 % (17 valeurs gagnées, aucune perdue),
champs clés 93,2 % → 93,2 %, ≥ 0,90 9 111 / 9 111 → 9 128 / 9 128, 0,80–0,90 2 633 / 2 739 → 2 633 / 2 736 ;
documents support 74,3 % → 74,3 % (282 / 282 ≥ 0,90) ; avoirs 98,0 % → 98,0 % (109 / 109 ≥ 0,90).

## D-2013 — UBL : lieu de l'Incoterm écrit en clair

`ingest/structure._lire_ubl` : sans `DeliveryTerms/DeliveryLocation`, le lieu est tiré de
`DeliveryTerms/SpecialTerms` quand ce texte commence par le code Incoterm de `cbc:ID` (« DAP Le Havre Incoterms
2020 » -> « Le Havre » ; la mention de version et une parenthèse coupent le lieu) ; confiance 0,90 (texte libre,
pas une donnée structurée). `DeliveryLocation` reste prioritaire ; un texte qui ne commence pas par le code ne donne
rien. `corpus_g2` dev : `incoterm_lieu` UBL 0 % -> 100 % (23 valeurs, toutes justes à 0,90) ; aucun autre
changement sur les deux corpus.

**Mesures D-2113** (`scripts/mesure_classement.py`, avant -> après D-2113) : `corpus_g2` dev pages 99,39 % ->
99,39 %, regroupement F1 0,959 -> 0,959, liens faibles 33 -> 29, dossiers incomplets 33 -> 28 ; `corpus` dev pages
97,91 % -> 97,98 % (+2 pages, aucune perdue), F1 0,873 -> 0,873, liens faibles 50 -> 49. Bancs complets
(`bench/out/g2_dev_grp2`, `bench/out/dev_grp2`, code des autres équipes à date) : G2 faux P1 29 -> 23, P4 30 -> 27 ;
banc d'origine : seuil PASSE, précision certain 1,000, rappel 0,818, rappel P1 1,0, P4 47 -> 46.

### D-2114 — « / » après un intitulé n'en fait pas une étiquette de champ

Constat (mesure finale, second jeu tenu à l'écart `corpus_h2`) : un bon de commande intitulé
« PURCHASE ORDER / FACTURE » était classé facture commerciale, si bien que l'absence de la vraie facture
n'était plus signalée (P1). Cause : « / » ajouté aux suites qui font d'un libellé une étiquette de champ
(pour « AWB / B/L: ») excluait aussi l'intitulé « purchase order ». Règle : « / » ne compte comme suite
d'étiquette que s'il annonce un libellé court suivi de « : ». Mesure sans régression (dev corpus_g2 :
classement 0,9939, F1 regroupement 0,959 ; dev corpus : 0,9798, F1 0,873, identiques). Test :
`test_bon_de_commande_intitule_avec_facture_reste_non_exploitable`. Le défaut a été repéré sur un jeu tenu
à l'écart : la correction est générale (une règle de syntaxe), et ce jeu n'est plus vierge pour P1.

# Rappel des écarts certains et bruit « à vérifier » (dev seulement)

Constat (bancs `g2_dev_cd`, `c1_dev_cd`) : précision certaine 1,000 sur les deux jeux, mais rappel certain 0,676
(`corpus_g2`) et 0,729 (corpus d'origine) — 30 et 26 vraies erreurs « certaines » classées `a_verifier`, 15 et 13
manquées — et bruit `a_verifier` non apparié de 2,09 par dossier sur `corpus_g2` (seuil d'alerte 1,5). Analyse :
raison de déclassement de chaque erreur sous-classée (valeurs clés et confiances relevées en instrumentant
`ControlContext.classify`), cause de chaque FN, familles de constats `a_verifier` jamais appariées à une erreur.
Règles générales seulement ; aucune ne lit un nom de gabarit, de fichier ou de société. Tests :
`tests/controls/test_rappel_bruit_d23.py`, `tests/extract/test_lectures_corroborees_d23.py`,
`tests/ingest/test_periode_ligne_d2301.py` (données fictives).

## D-2301 — Période d'une ligne de magasinage : structurée (CII/UBL) ou écrite dans le libellé

- **Constat** : 5 erreurs D6 « franchise facturée » (certaines) manquées sur `corpus_g2` : sans dates lues, D6
  compare quantité × prix (= montant facturé) et conclut `conforme`. Causes : `BillingSpecifiedPeriod` (CII) et
  `InvoicePeriod` (UBL) non lus ; période imprimée dans le libellé (« Lagergeld (07/03/2026 – 15/03/2026) »).
- **Choix** : `ingest/structure` lit BT-134/135 de la ligne (prioritaire sur une note) ; l'extracteur PDF lit la
  période dans le libellé quand aucune colonne de dates n'est lue : **exactement deux** dates reliées par un
  séparateur d'intervalle (–, —, -, au, to, bis, al, a, tot, t/m, hasta).
- Restent manquées : deux factures dont la date d'émission n'est pas lue (OCR) — aucune grille applicable.

## D-2302 — Numéro de TVA lu par OCR dont la clé est juste

La clé française (modulo 97) détecte toute substitution d'un chiffre et toute permutation de deux chiffres
voisins : elle confirme la lecture des caractères. Pour `client_facture.tva` lu par OCR, clé juste, numéro non
corrigé, mots OCR ≥ 0,6 : confiance = celle de l'attribution du pavé (0,97 libellé, 0,80 sans libellé),
plafonnée à `C_OCR_RECOUPEE` (0,92) au lieu du plafond 0,88 d'une lecture OCR isolée. C8 certains : GX0028,
GX0064, BX0055, BX0235 (sous-classés pour `confiance_insuffisante`). Les motifs de D-2211 restent appliqués.

## D-2303 — Le test de confusion ne vise pas une lecture confirmée par l'arithmétique imprimée

`ControlContext.lecture_douteuse` ignore un candidat **membre direct** (non inerte) d'une identité imprimée de
son document qui tient (somme, produit, écho ; D-1700) : une autre lecture de ses caractères romprait cette
identité. La confirmation « par la rangée » (D-1701) ne suffit pas (elle prouve l'emplacement, pas les
caractères). D3 BX0026, BX0138, D7 BX0028, D4 BX0201, GX0088 deviennent certains.

## D-2304 — Allocations dont dépend la comparaison

Condition 5 de §8.5.1 (« l'allocation éventuelle n'est pas `prorata` ») : `ControlContext.classify` ne retient
plus toutes les allocations touchant un document, mais celles qui relient **deux documents comparés** (source et
cible parmi les documents du constat ; un contrôle interne à un document ne dépend d'aucune répartition) ; si
des lignes de **débours** d'une facture du transitaire sont valeurs clés, seulement les allocations de ces lignes ;
une ligne répartie au prorata entre déclarations **toutes** comparées ensemble (parts connues, facture ne citant
aucun MRN hors du dossier) ne dépend pas de la clé de répartition. Une ligne sans MRN d'un relevé multi-MRN (part
inconnue) reste `prorata`. Une ligne de prestation (C6 : FAF) garde toutes les allocations (sa base en dépend
indirectement). A4 BX0168, C5 GX0152, GX0164 deviennent certains.

## D-2305 — Nature d'une ligne lue par OCR ; ligne qui renvoie à une annexe

- `nature_libelle(..., tolerant=True)` (nature d'une ligne déjà lue, jamais le repérage des rangées) : si rien
  n'est reconnu, un mot d'au moins 6 caractères est remplacé par l'**unique** mot (ou radical) du vocabulaire à
  une édition (« Comisi6n » -> « comision », « dédauanement » -> « dedouanement ») ; deux candidats : rien.
- Écarté : classer « Suplidos según anexo » en `debours_combines` (essayé) — quand l'annexe est découpée en un
  second document, ses lignes de détail sont aussi lues : débours comptés deux fois (5 C5 nouveaux, dont 3 sur
  pièges). Voir D-2306.

## D-2306 — D2 : pas de constat sans libellé, ni pour une ligne qui renvoie à une annexe

`_hors_grille` : ligne sans libellé lu -> `non_verifiable` (`valeur_absente`, motif `libelle_absent`) : le
poste se reconnaît au libellé, « aucun poste ne correspond » n'est pas établi ; ligne qui reprend le total d'une
annexe (`renvoie_a_une_annexe` : annexe, anexo, Anlage, allegato, bijlage, appendix…) -> `non_verifiable`
(motif `renvoi_annexe`). Bruit D2 `corpus_g2` 31 -> 5 (avec D-2305). Les D2 vrais (libellés lus) sont inchangés.

## D-2307 — Somme lue incomplète : B2, B3, B4 (masse brute)

Le nombre d'articles imprimé est lu et des articles n'ont pas été lus, **et** le total imprimé dépasse la somme
lue (B2, B3) ou la somme des masses brutes lue est inférieure à la masse brute totale (B4 `somme_brute`) : les
lignes manquantes expliquent l'écart dans le sens observé -> `non_verifiable` (motif `articles_non_lus`) au lieu
d'un constat. Écart de sens contraire (une ligne manquante ne peut pas l'expliquer) : constat inchangé. Sur les
deux jeux, aucun constat ainsi retiré n'était apparié à une erreur (B3 GX0005, vrai, a une somme supérieure au
total : conservé).

## D-2308 — Devise d'une facture commerciale relue à deux endroits (OCR)

D-2003 annonçait 0,90 quand le code ISO est lu en deux endroits distincts (en-tête de colonne et total) ; le
plafond d'une lecture OCR (0,88) l'empêchait. Retenu : 0,90 si les deux lectures concordent et que les mots OCR
sont sûrs (`confiance_mots` ≥ 0,65) ; idem pour le code du libellé « devise » relu ailleurs, ou seul code ISO du
document imprimé sur deux lignes. A3 GX0195, BX0214 deviennent certains.

## D-2309 — A4/A5 : lignes de pied signées

`_explique_par_pied` essaie aussi la somme **signée** (fret, assurance, emballage +, remise −) : « fret +
assurance − remise » explique l'écart (GX0123 : 485,04 + 23,06 − 112,80 = 395,30). Révélé par D-2308 : la
devise lue à 0,90 faisait de cet écart expliqué un A4 certain faux.

## D-2310 — Écart expliqué par une confusion de lecture sur des valeurs peu sûres : pas de constat

`ControlContext.constat` : un classement qui porte à la fois `lecture_douteuse` (§8.5.4) et
`confiance_insuffisante` donne un résultat `non_verifiable` (raison `lecture_douteuse`, motif
`ecart_explique_par_une_lecture_douteuse`, raisons conservées dans `details`), sans constat. Familles P
exclues. Sur les deux jeux, aucune erreur réelle parmi ces constats (un seul C5 neutre `doublon_composantes`) ;
bruit `corpus_g2` 444 -> 388, corpus d'origine 274 -> 245 à cette étape. Une lecture douteuse sur des valeurs
sûres reste `a_verifier`.

## D-2311 — D1 : confusion sur un facteur de produit ; facteur non imprimé

Le test de confusion d'un opérande de produit (quantité × prix, HT × taux) remplaçait le facteur comme dans une
somme (`c − d + x`) : il est désormais recalculé `c × x / d`. Une quantité implicite ou un prix déduit (méthode
`derive`) n'est pas imprimé : pas d'identité à vérifier sur la ligne -> `non_verifiable` (motif
`facteur_non_imprime`). Bruit D1 `corpus_g2` 39 -> 25 (avec D-2310).

## D-2312 — P4 : un constat par dossier

Plusieurs documents faiblement rattachés au même dossier relèvent d'une même vérification : un seul constat
P4 les énumère (documents, signaux de chacun dans `details.documents_faibles`) ; les autres liens faibles
donnent `non_applicable` (`couvert_par_autre_controle`, `regroupe_dans`). Un seul lien faible : libellé
inchangé. P4 `corpus_g2` 28 -> 21, corpus d'origine 46 -> 34. P1/P2 inchangés.

## D-2313 — C1–C5 : aucune ligne de la composante sur la facture

Aucune ligne de la composante refacturée (ni avoir), écart en faveur du client : le transitaire ne refacture
pas cette taxe (ou sa ligne n'est pas lue) ; rien n'est refacturé au-delà du liquidé -> `non_verifiable`
(motif `aucune_ligne_de_la_composante`). Aucune erreur réelle concernée sur les deux jeux.

## D-2314 — Condition de confiance remplie par une identité arithmétique imprimée

`ControlContext._confiance_par_identite` : une valeur clé lue (texte natif, OCR, modèle) sous `C_MIN_CERTAIN`
mais au moins à `C_LECTURE_CONFIRMABLE` (0,70), membre direct d'une identité imprimée de son document qui tient
et **qui n'est pas formée des seules valeurs clés** (le calcul contesté ne se prouve pas lui-même), satisfait la
condition 3 de §8.5.1. Ancrage, rattachement, lecture corroborée (D-1700), structure (D-2210) restent exigés.
C6 GX0192 devient certain. Effet de bord révélé et corrigé : D-2315.

## D-2315 — Versions d'une déclaration : préfixes MRN égaux aux confusions OCR près

`ControlContext.declarations`, `versions_anterieures`, `version_retenue` comparent les préfixes de 15 caractères
par `cle_confusion_ocr` (5/S, 0/O, 1/I…) : deux lectures d'un même MRN (version rectificative scannée) ne sont
plus additionnées. GX0041 : « 26FREMPO5ICM40E… » et « 26FREMPOSICM40E… » sommées par A4 (piège « version
rectifiée ») devenaient un A4 certain faux avec D-2314. Deux MRN réellement distincts diffèrent sur presque tous
leurs caractères aléatoires.

## D-2316 — D5 : deux lectures identiques du libellé se confirment

Libellés des lignes répétées identiques caractère pour caractère (texte brut ≥ 8 caractères), lus à deux
endroits distincts, chacun ≥ 0,80 : la condition de confiance est remplie pour ces libellés (une erreur d'OCR
ne produit pas deux fois le même libellé). Les motifs de D-2212 restent appliqués. D5 GX0101 devient certain.

## D-2317 — Mesures (dev seulement)

Bancs `g2_dev_cd` -> `g2_dev_rec`, `c1_dev_cd` -> `c1_dev_rec` (même cache de pages) :

| | `corpus_g2` avant | après | corpus d'origine avant | après |
|---|---|---|---|---|
| VP / FP certain | 100 / 0 | 110 / 0 | 111 / 0 | 119 / 0 |
| précision certain | 1,000 | 1,000 | 1,000 | 1,000 |
| rappel | 0,823 | 0,837 | 0,818 | 0,818 |
| rappel certain | 0,676 | 0,741 | 0,729 | 0,778 |
| sous-classements | 30 | 24 | 26 | 19 |
| FN | 53 | 49 | 67 | 67 |
| `a_verifier` non appariés (pièges compris) | 485 | 342 | 275 | 226 |
| bruit par dossier | 2,09 | **1,47** | 1,36 | 1,12 |
| violations de pièges | 48 | 35 | 36 | 27 |
| exactitude des montants | 0,963 | 0,964 | 0,966 | 0,966 |

Seuil bloquant PASSE sur les deux ; aucune erreur auparavant détectée n'est perdue ; aucun FP certain. Lecture
(`scripts/mesure_extraction.py`, factures de transitaire et commerciales, deux corpus) : aucune valeur perdue ;
`lignes[].nature` `corpus_g2` 85,3 % -> 86,0 % ; bande ≥ 0,90 : 6 334 / 6 331 justes (les 3 fausses préexistent),
8 142 / 8 140, 6 677 / 6 677, 9 152 / 9 152.

**Restent (relevés, non corrigés)** : B2 « Total A00 EUR … » (totaux par code imprimés sous le tableau des
taxes) non lus par l'extracteur de déclaration — 3 B2 certains manqués (GX0087, GX0108, GX0246) ; les ajouter
impose que C (`reference_declaration`) exclue les lignes sans article, sinon double comptage ; date d'émission
illisible (OCR) sur deux factures de transitaire (aucune grille, D6 manqué) ; F3 `rattachement_faible` (lien du
dossier frère) ; A6 `devise_incertaine` (taux imprimé lu sous 0,90).

# Généralisation : déclarations, classement et regroupement sur `corpus_g4` (dev seulement)

Constat : sur `bench/corpus_g4` (générateur 2.1, split `dev`, 175 dossiers), trois présentations de déclaration
étaient illisibles (M7 feuillet d'en-tête + annexes à deux tableaux de taxes côte à côte, 24 % des champs
obligatoires ; M8 « état de liquidation » en un seul tableau, 31 % ; M9 export XML anglais à taxes hors des
articles, 10 %, classé `inconnu`), les annexes et pages de suite étaient prises pour des factures (« Montant
facturé »), les factures et avoirs de transitaire polonais pour des factures commerciales, et le regroupement
produisait 150 dossiers incomplets (147 faux P1) et 91 liens faibles. Règles générales seulement : vocabulaire,
structure du texte, recoupements ; aucun nom de fichier, code de gabarit ni nom fictif. Le texte des documents
reste une donnée.

## D-2401 — Export XML de déclaration de format inconnu : fiche déduite des noms d'éléments

`ingest/structure_deduite.py` : quand aucune fiche `config/mappings` ne reconnaît un XML, une fiche **en mémoire**
est déduite des noms d'éléments et d'attributs, comparés à des listes fermées de synonymes (fr/en/de/it/es) :
articles = éléments répétés portant un code marchandise ; taxations = éléments portant un code de taxe et un
montant (article par attribut « item/article/position » ou par l'article ancêtre) ; documents = code « N380 » +
référence ; en-tête = feuilles hors de ces groupes ; parties (importateur, déclarant, représentant fiscal) par
l'élément parent. Catégorie d'une taxe d'après le libellé imprimé dans le fichier (« Flat-rate duty (low value) »
-> forfait), modes de paiement de la nomenclature de l'Union. Pas de MRN, ou ni article ni taxation : pas de fiche
(un XML quelconque reste inconnu). Le fichier est alors classé `declaration/export_xml` (confiance 0,90) et lu par
le chemin habituel des fiches. **Confiance** : une correspondance déduite n'a pas la certitude d'une fiche écrite
— 0,95 si les recoupements internes tiennent (somme des taxes = total, base × taux = montant au centime ou à
l'euro, nombre d'articles), 0,85 sinon ; « tiennent » tolère une anomalie isolée (≤ 1 échec, ou ≤ ¼ des
recoupements) : une erreur de la déclaration elle-même doit rester un écart que les contrôles relèvent, une
correspondance fausse fait échouer la plupart des recoupements.

## D-2402 — Rubriques composées « A / B / C »

« Colis / articles … 7 / 12 », « LRN / rang … LRN… / 1 », « Masse brute / colis / articles 3 649,3 kg — 60 colis —
4 article(s) » : libellés enchaînés par « / » suivis d'autant de valeurs séparées par « / » ou « — » (à défaut,
OCR, par un blanc net) ; chaque valeur passe le validateur de son libellé, sinon rien n'est retenu. Ces lectures
priment sur la lecture libellé par libellé, qui prenait « articles » pour la valeur du nombre de colis. Un libellé
après un « / » isolé est crédible (seconde partie de la rubrique). Vocabulaire ajouté : « Rang » (version),
« Livraison » (Incoterm), « Facturation » (monnaie et montant facturé), « Préf. », « Quantité » (unités
supplémentaires d'un bloc d'article).

## D-2403 — Blocs d'article sans libellé de code ; taux de change sans libellé ; récapitulatif « type / libellé »

- « Article 1 — 2102109000 — origine CN — … » : un bloc d'article est ouvert quand le mot qui suit le numéro est un
  code de 8 ou 10 chiffres imprimés tels quels (ou par groupes) ; le code est lu là. OCR : le code pays ISO en
  capitales qui suit le code sur cette ligne est l'origine (pénalité 0,10) quand le libellé « origine » est
  imprimé ailleurs.
- « 1 EUR = 0,92905 CHF » imprimé seul dans l'en-tête : taux et sens, si l'expression est unique et que l'euro est
  l'une des devises (pénalité 0,02).
- Tableau « Type | Libellé | Montant » : « FPE Droit forfaitaire petits envois 6,00 » donne le libellé du code
  (catégorie forfait). Le récapitulatif « Total A00 : 54,62 Total B00 : 513,53 TOTAL DROITS ET TAXES … » ne
  donne plus « 513,53 TOTAL DROITS ET TAXES » pour libellé de B00 (B00 était classé « droit »).

## D-2404 — Deux tableaux de taxes côte à côte ; intitulé de colonne d'un seul tenant

« Taxe Base Taux Montant MP | Taxe Base Taux Montant MP » (droits à gauche, TVA à droite) : un en-tête dont la
première colonne se répète est coupé en groupes de colonnes ; chaque moitié de ligne est lue avec ses colonnes,
de gauche à droite. Un intitulé de colonne en plusieurs mots est d'un seul tenant : « Taxe   Base » séparés par
un blanc de colonne ne sont plus lus « Tax base ».

## D-2405 — Tableau mixte article + taxation (« état de liquidation »)

Un tableau d'articles dont l'en-tête porte aussi les colonnes de taxation (type, base, montant) est lu comme
tableau d'articles : la taxation de la ligne de l'article, puis les sous-lignes « B00 222,94 20,0 % 44,59 … »
rattachées à l'article courant ; une ligne de suite de la désignation (mots tous dans la colonne de la
désignation, sans montant décimal) ne ferme pas le tableau.

## D-2406 — Classement : rubriques citées, polonais et portugais, avoir cité dans le corps

- « Montant facturé », « Mt facturé », « Total facturé » : rubrique, pas un intitulé de facture (les annexes de
  déclaration et pages de suite d'un état de liquidation étaient des « factures commerciales »). Rubriques d'article
  d'annexe ajoutées au vocabulaire de déclaration (« masse nette / brute », « préf. 100 », « TVA à
  l'importation », « droits et autres taxes »).
- Vocabulaire pl/pt : débours refacturés (« należności celne », « refaktura », « odprawa celna », « prowizja za
  kredytowanie », « desalfandegamento »…), prestations (« cło », « składowanie », « usługi »), avoirs (« faktura
  korygująca »), totaux négatifs (« razem », « do zapłaty »), lettres (« Exmos. Senhores », « Junto enviamos »…).
- Facture citant des MRN et des frais douaniers sans aucune rubrique de marchandise (≥ 3 indices de transitaire)
  : facture de transitaire.
- Un intitulé de facture imprimé plus haut, à niveau égal ou supérieur, l'emporte sur un avoir cité dans le corps
  (« Gutschrift zu Rechnung … ») sauf total négatif.
- Texte natif : un changement de corps sépare deux segments (nom de société en grand corps collé à l'intitulé) ;
  un intitulé précédé d'une forme sociale (« … Sp. z o.o. FAKTURA ») reste un intitulé. OCR : pas de coupure sur
  la hauteur des mots (variable selon les lettres).

## D-2407 — Regroupement : lien de déclaration corroboré par un document du dossier

Une déclaration rattachée sans référence explicite (même dossier source, TVA et codes) reçoit `mrn_cite`
(forte pour une déclaration) quand une facture de transitaire du **même dossier**, elle-même rattachée à la
facture commerciale par une référence explicite, cite son MRN ; `ref_transport` quand un document support ainsi
rattaché porte un titre de transport qu'elle cite. Rien n'est déplacé : seuls les signaux d'un lien existant sont
complétés (moins de P4 sur des liens réellement établis).

## D-2408 — Sous-dossiers frères réunis par une référence explicite commune

Les pièces d'un même envoi rangées dans des sous-dossiers mixtes ne se rejoignaient jamais (frontière dure).
Comme pour deux courriels, deux sous-dossiers frères se rejoignent sur une référence explicite commune : MRN,
titre de transport, ou numéro de facture cité tel quel (forme normalisée égale). Un dossier de la même frontière
qui porte la même référence l'emporte (deux envois au même numéro restent séparés, test
`test_frontiere_dure_entre_sous_dossiers`) ; une référence propre au dossier rejoint (MRN d'une facture mensuelle)
garde le rattachement multiple.

## D-2409 — Découpage : numéros de facture multilingues, versions rectificatives, intitulés entrelacés

- Numéro lu après « faktura / fattura / fatura / rechnung / factuur » (avec « VAT », « korygująca »,
  « uzupełniająca », « complémentaire »), et après « note de débit / debit note / nota obciążeniowa » (intitulés
  de facture) : les deux pages d'une facture (page de récapitulatif « PODSUMOWANIE ») forment un document.
- Une page intitulée qui porte un autre MRN complet (même préfixe de 15 : version rectificative) commence une
  nouvelle déclaration (deux versions dans un même PDF étaient fusionnées, sommes doublées en B3).
- Texte natif où le nom de société et l'intitulé, de corps différents, se chevauchent (mots entrelacés) : chaque
  suite est relue dans son ordre (intitulé et numéro reconnus).

Non fait (relevé) : totaux par code (« Total A00 : … ») sous le tableau des taxes — le modèle n'a pas de champ de
totaux de catégorie ; les poser en lignes sans article impose que C (`reference_declaration`) les exclue
(`structure_declaration.totaux_par_categorie` sait les reconnaître) ; laissé à l'équipe des contrôles. Scans
« deux pages par feuille » (3 documents) : à traiter à l'ingestion des pages (découpe de l'image).

## D-2410 — Mesures (dev seulement)

`scripts/mesure_extraction.py --type declaration`, `scripts/mesure_classement.py`, bancs complets (même cache) :

| `corpus_g4` dev | avant | après |
|---|---|---|
| déclarations : champs obligatoires / champs clés | 61,5 % / 73,7 % | 90,5 % / 92,3 % |
| M7 d0 / M8 d0 / M9 (champs obligatoires) | 24,2 % / 31,2 % / 10,2 % | 100 % / 100 % / 100 % |
| valeurs de confiance ≥ 0,90 fausses | 14 / 9 170 | 1 / 13 965 (préexistante, M1 scan) |
| classement des pages | 0,840 | 0,991 |
| regroupement F1 (paires) ; dossiers incomplets ; liens faibles | 0,874 ; 150 ; 91 | 0,952 ; 15 ; 46 |
| banc : rappel / rappel certain | 0,487 / 0,242 | 0,801 / 0,600 |
| banc : bruit `a_verifier` par dossier ; FP P1 ; P1 manqués | 3,42 ; 147 ; 1 | 1,65 ; — ; 0 |

Les 5 FP certains restants du banc g4 ne viennent pas de la lecture des déclarations : C2 GZ0145 (lignes d'autres
taxes d'une facture mensuelle multi-MRN additionnées), C6 GZ0189 (piège FAF au minimum), D2/D4 sur des lignes
polonaises de factures de transitaire. Non-régression : `corpus_g2` et corpus d'origine, lecture des
déclarations (0 comparaison perdue, +3 / +2 justes, bande ≥ 0,90 inchangée), classement inchangé, regroupement
`corpus_g2` F1 0,959 -> 0,965 (incomplets 27 -> 21), corpus d'origine identique (P4 49 -> 47) ; banc corpus
d'origine : seuil PASSE, 119 VP / 0 FP certain (identique). Tests : `tests/extract/test_declaration_d24.py`,
`tests/ingest/test_classement_d24.py`, `tests/assembly/test_regroupement_d24.py`.

## D-2501 — Factures de transitaire et commerciales : vocabulaire portugais, polonais et suisse alémanique

- **Constat** (`corpus_g4` dev) : familles G13 (pt), G14 (pl), G15 (de-CH) sans aucune ligne lue (en-têtes de
  colonnes, totaux et titres inconnus) ; factures commerciales CP (pt) et CL (pl) sans numéro, TVA acheteur, masses
  ni colis.
- **Choix** (données seulement, `_ft_langues`, `_fc_langues`, `normalize/natures`, `normalize/units`) : en-têtes
  « Descrição / Qtd / Preço unit. / Taxa », « Lp. / Nazwa / Ilość / J.m. / Cena jedn. / Wartość netto / Stawka »,
  « Sendung / MRN … Soll / Haben » ; totaux « Total despesas (suplidos) / Total sem IVA / Total com IVA », « Razem
  należności / Razem netto / Razem brutto / Do zapłaty », « Total Auslagen / Total netto / Total EUR » (sous-totaux
  « Razem usługi netto », « Sous-total de l'envoi » ignorés) ; titres « fatura », « nota de crédito », « faktura
  (VAT, korygująca, eksportowa) », « nota obciążeniowa », « Kontoauszug / Sammelrechnung » (relevé) ; libellés de
  facture d'origine et de motif (« Fatura de origem », « Faktura pierwotna », « Przyczyna korekty ») ; parties
  « Nabywca / Odbiorca / Faturar a / Entregar a » ; natures pt/pl (« Desalfandegamento », « Odprawa celna »,
  « Cło », « Prowizja za kredytowanie », « Obsługa ładunku »…) ; unités « szt., sztuk, kpl, unidades ».
- `normalize.text.sans_accents` : lettres barrées sans décomposition Unicode (« ł », « ø », « đ ») ramenées à la
  lettre simple (« usługi » → « uslugi »). Un numéro de ligne collé au libellé (« 1   Cło ») est retiré avant
  la recherche de nature.

## D-2502 — Lignes « TVA comprise » : on expose ce qui est imprimé ; le HT dérivé est marqué et plafonné

- **Constat** : G13 imprime prix unitaire et total **TVA comprise** par ligne (« Preço unit. c/ IVA », « Total
  c/ IVA ») ; le HT n'apparaît que dans le tableau récapitulatif de TVA. Avant : le TTC était lu comme HT (faux à
  0,97) et la TVA de ligne recalculée sur ce faux HT.
- **Choix** : colonnes `pu_ttc` et `ttc` reconnues ; une ligne sans colonne HT expose `montant_ttc` (imprimé) et
  son taux. Ligne exonérée (« isento », « exempt », « zw. », taux 0) : `montant_ht` = montant imprimé (confiance
  ≤ 0,93), taux 0 dérivé de la mention (≤ 0,90). Ligne taxée : `montant_ht` = TTC / (1 + taux) **dérivé**
  (`methode = derive`, règle `montant_ttc / (1 + taux_tva)`, sources TTC et taux, confiance ≤ 0,60) ; ni prix
  unitaire HT ni TVA de ligne fabriqués. Les totaux du document restent ceux imprimés.
- Mesure : avec le HT dérivé, banc g4 rappel 79,8 % / montants justes 95,6 % / bruit 1,99 ; sans, 79,1 % / 93,2 %
  / 2,37 (les contrôles retombaient sur le TTC comme montant de prestation). La vérité du banc n'ayant pas de HT
  pour ces lignes, la mesure d'extraction compte ces dérivés « faux » : c'est voulu.
- Taux lu > 100 (« 2000 », virgule perdue par l'OCR) : écarté.

## D-2503 — MRN d'une ligne : intertitre de section

- Tableau groupé par envoi (« Envoi — MRN 26FR… » juste au-dessus de l'en-tête, G16) : les lignes sans MRN
  propre reçoivent ce MRN (confiance de rattachement 0,85) ; le tableau est marqué « MRN par ligne », donc ses
  lignes sans MRN n'en reçoivent pas d'autre. L'intertitre doit porter un seul MRN, des mots et aucun autre
  nombre, ne pas appartenir à un tableau déjà lu (une rangée « transport / MRN / date » n'en est pas un) ; il
  n'est pas pris non plus comme « ligne de suite » de la rangée précédente.
- Une règle plus large (aucun rattachement du MRN unique dès qu'un autre tableau porte une colonne MRN) a été
  essayée puis retirée : elle suit la convention de vérité de g4 mais contredit celle du corpus d'origine
  (−131 MRN justes) ; rattacher le MRN unique reste utile aux contrôles.

## D-2504 — Numéro de TVA d'un représentant fiscal

- **Constat** : importateur suisse représenté (« TVA rep. fiscal : FR… » puis le numéro propre du client) : le
  premier numéro du pavé était pris, faux à 0,97 sur 6 factures de transitaire et 10 factures commerciales.
- **Choix** (`_mise_en_page.REP_FISCAL`) : un numéro précédé d'un libellé de représentant fiscal n'est retenu
  pour le client / l'acheteur que s'il n'y en a pas d'autre dans le pavé (FT : aussi juste en dessous, même
  colonne) ; il est alors plafonné à 0,60. Il n'est jamais pris pour l'émetteur.

## D-2505 — Rangées perdues, avoirs dans un relevé, quantités groupées

- Rangée OCR dont les montants sont illisibles entre deux rangées lisibles : la lecture du tableau continue
  (avant : arrêt, toutes les rangées suivantes perdues) ; document `partielle`, avertissement
  `rangee_illisible`, montants de ligne plafonnés à 0,85 (une somme de lignes est alors incomplète).
- OCR : si la somme des lignes de débours contredit le total des débours imprimé, chaque montant de débours est
  plafonné à 0,85 (aucune base de commission ou somme par nature ne peut être certaine).
- Lignes négatives (« Gutschrift zu Rechnung … -25.00 ») : signe imprimé conservé ; les recoupements (somme des
  lignes = total) se font en valeur signée.
- Quantité entière à séparateur de milliers (« 3 988 kg ») lue comme quantité (prestations au kg).

## D-2506 — Date de facture de transitaire

- Date seule dans le segment voisin du numéro (« No. PFL/26/60695 | 26 Jun 2026 », texte OCR découpé) : ≤ 0,90.
- Libellé de date en tête de colonne (« Nr. | Datum | Btw-nr. ») : valeur cherchée jusqu'à trois lignes plus bas
  (bruit OCR intercalé), même écart vertical maximal.
- Repli : la seule date distincte du haut de la première page (hors échéance, période, livraison, horodatage de
  télécopie, tableaux) ; confiance 0,70 (jamais une base d'écart certain). g2 dev : dates 88,2 % → 95,7 %.

## D-2507 — Factures commerciales portugaises et polonaises

- Numéro « Fatura n.º FT PIC2026/6990 », « FAKTURA EKSPORTOWA Faktura nr … » ; date « Data wystawienia » ;
  devise « Moeda / Waluta » ; « Condições de entrega / Warunki dostawy » ; titres de transport « Carta de porte
  aéreo / Konosament / Lotniczy list przewozowy » ; masses « Peso líquido / Masa netto / Masa brutto » ; colis
  « Volumes: / Liczba opakowań » ; sous-totaux « Total mercadorias / Frete / Seguro / Embalagem / Desconto »,
  « Wartość towarów / Fracht / Ubezpieczenie / Opakowanie / Rabat » ; total « RAZEM DO ZAPŁATY ».
- Contre-valeur indicative (« Contravalor indicativo », « Równowartość informacyjna ») exclue des totaux.

## D-2508 — Facture commerciale sur plusieurs pages : report jamais compté

- **Constat** (CM, 22 à 45 lignes) : « Brought forward 625.02 » en tête de page 2 lu comme une ligne de
  marchandise et « INVOICE TOTAL EUR » comme une ligne : total des lignes doublé du report.
- **Choix** : `lire_tableau(..., est_ignoree=...)` saute les lignes de report (« brought / carried forward »,
  « report », « Übertrag », « riporto », « z przeniesienia »…) sans finir le tableau ni s'ajouter à une rangée ;
  « invoice / grand total », « delivery terms », « Page n/m » finissent le tableau. « Page total … carried
  forward » reste un total de page (jamais le total de la facture). Colis lus aussi au milieu d'une ligne
  (« … Gross weight: 1,673.406 kg Packages: 41 »).

## D-2509 — Date de facture commerciale à côté du numéro

- « Invoice No. SPT-INV-00608 — 8 Aug 2026 — Page 1/2 » : sans libellé de date, la date qui suit immédiatement le
  numéro (séparateurs seuls intercalés ; segment voisin en OCR) est retenue, confiance ≤ 0,90 (≤ 0,70 si jour et
  mois sont inversables).

## D-2510 — Référence de facture d'un document support à préfixe lettré

- « Ref. invoice / facture: FT PIC2026/8089 » : la seconde partie peut commencer par des lettres.

## D-2511 — Numéro de facture après un titre imprimé au milieu de l'en-tête

- « Spedycja … FAKTURA — USŁUGI DODATKOWE Nr FV/04948/05/2026 », « FACTURE | COMPLÉMENT DE PRESTATIONS
  HTD2026-61136 » : à défaut de libellé, la première référence alphanumérique qui suit un mot-titre dans le même
  segment (ou le segment voisin si le titre est seul) en haut de la première page ; valeur de position (0,88).

## D-2512 — Mesures (dev seulement)

`scripts/mesure_extraction.py`, `corpus_g4` dev (175 dossiers), avant → après :

| Document | Champs | Avant | Après |
|---|---|---|---|
| Facture de transitaire | lignes : libellé / nature / quantité / HT | 46,1 / 47,4 / 50,0 / 58,9 % | 82,0 / 84,2 / 83,7 / 77,2 % |
| | numéro / TVA client / total débours / HT / TTC | 82,7 / 88,8 / 52,6 / 64,3 / 64,3 % | 96,9 / 95,9 / 83,7 / 92,9 / 95,9 % |
| | valeurs ≥ 0,90 justes | 99,4 % (17 faux / 2 811) | 99,93 % (3 / 4 369) |
| Facture commerciale | numéro / date / TVA acheteur / total | 66,4 / 61,6 / 55,9 / 77,7 % | 94,8 / 89,1 / 90,0 / 93,4 % |
| | masse brute / colis / unité | 77,7 / 45,0 / 67,5 % | 95,3 / 95,7 / 79,3 % |
| | valeurs ≥ 0,90 justes | 99,4 % (40 faux) | 99,90 % (8 / 8 282) |
| Avoir | numéro / réf. facture d'origine / nature / total crédité | 71,4 / 73,8 / 42,9 / 40,5 % | 88,1 / 97,6 / 81,0 / 81,0 % |
| Document support | réf. facture | 82,2 % | 93,3 % |

- Les 3 faux ≥ 0,90 restants des factures de transitaire sont des « 0,00 » de débours **imprimés** que la vérité
  laisse vides ; les 8 des factures commerciales viennent d'un scan dont la page 1 manque (numéro de ligne
  illisible, appariement de la mesure décalé), les valeurs lues étant justes pour leur rangée.
- Les lignes `montant_tva` / `taux_tva` / `prix_unitaire` de G14/G15 sont dérivées (≤ 0,60) alors que la vérité
  les laisse vides (non imprimés) : baisse de ces champs dans la mesure, sans effet sur les contrôles.
- Non-régression `corpus_g2` et corpus d'origine (4 types) : aucune valeur juste perdue hors appariement de
  lignes nouvellement lues ; bande ≥ 0,90 inchangée (g2 FT 3 faux, c1 FT 2 faux, autres 0).
- Banc complet (code de tous les chantiers en cours) : `corpus_g4` dev rappel 48,7 % → 80,1 %, rappel certain
  24,2 % → 60,0 %, montants justes 89,9 % → 95,6 %, VP/FP certains 36/3 → 84/5 ; `corpus_g2` dev 112 VP / 1 FP
  (seuil PASSE) ; corpus d'origine 119 VP / 0 FP, seuil PASSE (identique).
- Tests : `tests/extract/test_extraction_pt_pl_ch.py` (36 tests, mises en page propres aux tests).

# Contrôles : écarts certains sur `corpus_g4` (dev seulement)

Constat (banc `g4_dev_ctl_base`, même cache de pages) : 84 VP / 5 FP certains (précision 0,944, seuil bloquant
ÉCHOUE) : C2 GZ0145 ×2, C6 GZ0189 (piège), D2 GZ0048, D4 GZ0144 ; `corpus_g2` : 112 / 1 (D4 GX0173). Règles
générales seulement ; aucune ne lit un nom de gabarit, de fichier, de client ou de transitaire. Extracteurs non
modifiés. Tests : `tests/controls/test_precision_d27.py` (19 cas fictifs).

## D-2701 — Ligne TVA comprise : jamais la base d'un écart certain

- **Constat** : les contrôles C, D, E, F, G et l'imputation des avoirs prenaient `montant_ttc` quand `montant_ht`
  manquait (`_aides_befg.montant_ht`, `famille_d._montant`, `famille_c._montant_ligne`, `lignes_credit_depuis_avoir`) :
  un brut (G13, « Total c/ IVA ») comparé à un tarif ou à un liquidé net. Le HT déduit du TTC (D-2502) n'était pas
  distingué d'un HT lu.
- **Choix** (`recouvrement.imputation.montant_net_ligne`, source unique) : HT lu → tel quel ; HT déduit du TTC
  (`montant_ttc / (1 + taux_tva)` ou TTC parmi ses sources) → marqué ; pas de HT (ou HT inutilisable) → TTC tel quel
  seulement si la ligne ne porte pas de TVA (taux ou TVA de ligne lus nuls), sinon TTC marqué. « Marqué » : raison
  nouvelle `montant_tva_comprise` portée par la valeur (reprise par `classify`, condition 3) et confiance plafonnée
  à 0,60 (sous `C_LECTURE_CONFIRMABLE` : D-2314 ne la relève pas). Un HT déduit reste préféré au TTC (sinon un
  `non_verifiable` deviendrait un constat sur le brut).

## D-2702 — Rattachement d'une ligne de débours à une déclaration (C1–C6)

- **Constat** : GZ0145 (relevé mensuel de quatre envois, scan) : la ligne d'autres taxes de l'envoi D, au MRN lu à
  0,49 (sous `C_MIN_UTILE`), était traitée comme une ligne sans MRN et rattachée à la seule déclaration de chaque
  dossier du relevé ; C2 certain 413,02 dans deux dossiers. Une ligne au MRN lu « 26FRIM2… » (confusion 1/I) n'était
  rattachée à rien (l'écart réel de 2,20 était manqué).
- **Choix** (`famille_c.unites_c`, `LigneDebours.attribution_incertaine`, `UniteC.lignes_non_rattachees`, raison
  nouvelle `attribution_non_univoque`) : « facture de plusieurs envois » (`facture_multi_envois`) = relevé, ou
  plusieurs MRN utilisables distincts aux confusions OCR près, ou un MRN cité qui est celui d'une déclaration d'un
  autre dossier. Pour une ligne qui porte un MRN lu (toute confiance) :
  1. préfixe identique à une déclaration du dossier → rattachée (15 caractères aléatoires lus à l'identique
     confirment la lecture, même sous 0,90) ;
  2. préfixe d'une déclaration d'un autre dossier (identique, ou même clé de confusion sans déclaration du dossier
     de même clé) → ligne de cet autre dossier, écartée ;
  3. même clé de confusion qu'une seule déclaration du dossier → rattachée, non certaine sur une facture de
     plusieurs envois ;
  4. MRN utilisable inconnu : règle antérieure (seule déclaration, hors relevé) mais non certaine sur une facture de
     plusieurs envois ; sur une telle facture, s'il est lu sous `C_MIN_CERTAIN`, les unités de la facture sont
     marquées (la ligne peut être un MRN du dossier mal lu) ;
  5. MRN illisible, ou pas de MRN : règle antérieure ; rattachement à la seule déclaration du dossier non certain sur
     une facture de plusieurs envois.
  C1–C4 : raison ajoutée si une ligne de la composante (ou combinée) est marquée, ou si l'unité a des lignes non
  rattachées ; C5, C6 : si l'unité est marquée. Le constat reste émis (`a_verifier`, `details.attribution_non_univoque`).

## D-2703 — D4 : assiette complète et rattachée

- **Constat** : GZ0144 (télécopie) : la ligne « Cło » (droits) est lue « Cto » sans nature de débours ; l'assiette
  ne retient que la TVA (8 708,58) et D4 est certain (85,60) alors que le FAF facturé est 2 % du total des débours
  imprimé (12 988,58). GX0173 (relevé de cinq envois) : la ligne FAF et la ligne de droits du même envoi portent deux
  lectures différentes du MRN ; aucune déclaration rapprochée, l'assiette de repli (« même MRN que la ligne ») ne
  garde que la TVA : D4 certain 59,64.
- **Choix** (`famille_d._pourcentage`, `_debours_complets`, `_assiette`) : D4 n'est certain que si
  1. les lignes de débours sont complètes : leur somme redonne le total des débours **imprimé** (`T_SOMME`), à défaut
     de ce total la somme de toutes les lignes redonne le total HT imprimé ; sinon raison `valeur_absente`, motif
     `details.assiette_non_confirmee` — sauf attendu au maximum de la grille (une ligne perdue ne peut que
     l'augmenter) ;
  2. les débours de l'assiette sont rattachés sans doute : unités C marquées (D-2702), ou assiette de repli sur une
     facture de plusieurs envois → `attribution_non_univoque`.
  Explication D-2213 complétée : le total des débours imprimé (avec et sans les lignes de TVA) est une assiette
  alternative.

## D-2704 — C6 : ligne « droits et taxes » combinée

- **Constat** : GZ0189 (piège « FAF au plafond ») : ligne combinée 10 217,61 (droits **et** TVA) ; l'assiette du FAF
  est « débours hors TVA » ; l'excédent était calculé contre les seuls droits et autres taxes liquidés, soit
  8 619,61 (toute la TVA), d'où C6 certain 202,06 alors que l'excédent réel (C5) est 18,75 et que le FAF, au
  maximum de la grille avant comme après correction, n'en dépend pas.
- **Choix** (`famille_c.excedent_debours`) : une ligne combinée ne se ventile pas par composante ; quand l'assiette
  ne couvre pas toutes les composantes et que l'unité porte une ligne combinée, l'excédent retenu est l'excédent
  total (Σ refacturé − Σ liquidé total). Le minimum et le maximum de la grille restent appliqués aux deux FAF
  (avant et après correction) : GZ0189 devient `conforme`.

## D-2705 — D2 (et D7 sans poste) : une prestation imprimée deux fois n'est relevée qu'une fois

- **Constat** : GZ0048 : « Kontrola dokumentów » hors grille imprimée deux fois (aussi un D5) : deux D2 certains de
  25,00 pour une prestation (un FP certain).
- **Choix** (`famille_d._hors_grille_une_fois`) : lignes de même facture, nature, libellé normalisé, montant et
  référence d'envoi (clé de D5) : la première porte le constat ; les suivantes sont `non_applicable`
  (`couvert_par_autre_controle`, `details.couvert_par = D5`, `copie_de_la_ligne`). La répétition reste l'objet de D5.

## D-2706 — D5 : rétablir D-2212 quand le MRN de ligne n'est pas sûr

- **Constat** : GX0120 / GX0128 (`corpus_g2`, relevés de cinq envois) : selon la lecture, le MRN d'un envoi est
  recopié sur les lignes « Customs clearance » des autres envois (lu 0,75) ; les lignes portent alors « la même
  référence » et le motif 1 de D-2212 (« lignes sans référence ») ne s'applique plus ; avec D-2316 (libellés
  identiques qui se confirment), D5 devenait certain (110,00) dans un run antérieur.
- **Choix** (`famille_d._d5_motifs`) : sur une facture de plusieurs envois, motif 5 `reference_d_envoi_non_etablie`
  quand la référence commune (MRN ou transport) d'une des lignes répétées est lue sous `C_MIN_CERTAIN` ; motif 6
  `une_ligne_par_envoi` (en plus de 1 ou 5 seulement) quand les lignes identiques, toutes références confondues,
  ne dépassent pas le nombre d'envois cités. Deux lignes qui portent le même MRN lu sûrement restent un doublon
  certain (GX0026, GX0078 inchangés).

## D-2707 — C8 : la facture doit appartenir à l'envoi du dossier

- **Constat** : GZ0197 (piège « facture de débours d'un autre envoi rangée dans ce dossier », PDF fusionné) : la
  facture de l'autre envoi est adressée à une autre entité du client ; C8 pouvait être certain (seul un lien faible
  l'en empêchait dans ce run).
- **Choix** (`famille_c._c8_motifs_non_certain`, motif 5 `facture_non_rattachee_a_l_envoi`,
  `facture_rattachee_a_l_envoi`) : C8 certain seulement si la facture cite le MRN d'une déclaration du dossier (aux
  confusions OCR près) ou un titre de transport cité par une déclaration, une facture commerciale ou un document
  support du dossier (égalité, inclusion ou confusion de lecture). Les C8 certains vrais des trois jeux sont
  inchangés.

## D-2708 — C6 : un FAF par envoi sur des débours non ventilés

- **Constat** : GX0152 : deux envois, lignes « droits et taxes » sans MRN (unité commune de deux déclarations), un
  FAF par envoi : chaque FAF était comparé à l'excédent de l'unité entière (10,43 et 153,26, montants faux ; avec
  D-2704 : `conforme` à tort).
- **Choix** (`famille_c.c6_faf_sur_excedent`) : les lignes FAF rapportées à une même unité de plusieurs déclarations
  sont additionnées et évaluées une fois (première ligne ; les autres `non_applicable`, motif
  `faf_additionnes_par_unite`) ; raison `attribution_non_univoque` (le FAF de chaque envoi n'est pas ventilé).
  GX0152 : 1,65 `a_verifier`, montant juste.

## D-2709 — Mesures (dev seulement)

Bancs `*_dev_ctl_base` → `*_dev_ctl27` (même cache de pages, code d'extraction du moment) :

| | `corpus_g4` avant | après | `corpus_g2` avant | après | corpus d'origine avant | après |
|---|---|---|---|---|---|---|
| VP / FP certain | 84 / 5 | 84 / 0 | 112 / 1 | 112 / 0 | 119 / 0 | 119 / 0 |
| précision certain | 0,944 | 1,000 | 0,991 | 1,000 | 1,000 | 1,000 |
| seuil bloquant | ÉCHOUE | PASSE | PASSE | PASSE | PASSE | PASSE |
| rappel | 0,801 | 0,808 | 0,850 | 0,853 | 0,818 | 0,818 |
| rappel certain | 0,600 | 0,600 | 0,755 | 0,755 | 0,778 | 0,778 |
| bruit `a_verifier` par dossier | 1,651 | 1,651 | 1,466 | 1,457 | 1,109 | 1,124 |
| violations de pièges | 45 | 44 | 33 | 33 | 27 | 28 |

Aucun VP certain perdu. Gains : GZ0145 C2 2,20 et GZ0034 C2 2,20 détectés (`a_verifier`, montant juste), GX0152 C6
1,65 (montant juste). Coût : corpus d'origine, trois `a_verifier` nouveaux (BX0084 C5, BX0149 C4/C5) : lignes
désormais rattachées à leur déclaration par la clé de confusion OCR, dont la lecture des taxes est incomplète
(BX0084 : violation du piège « montant droits et taxes combiné », niveau `a_verifier`).

**Relevé pour l'extraction (non corrigé ici)** : A1 « pavé acheteur ne permet pas d'identifier une entité » sur
`corpus_g4` (GZ0008, GZ0010, GZ0030, GZ0031, GZ0069, GZ0115 ×3 ; pièges GZ0096, GZ0133 CL15 et GZ0117 CL17) : pavé
acheteur de la facture commerciale non lu ou réduit à un fragment (« SARL », une ligne d'adresse) sur des scans ;
comportement conforme à SPEC §A1 (« E_f illisible → `a_verifier` »). GZ0144 : « Cło » lu « Cto », nature non
reconnue (la tolérance D-2305 exige 6 caractères). GZ0145 : MRN des lignes lus 0,49–0,85 et MRN d'en-tête
« 26FRQOMEJMUA 811764 » (0,20). GX0173 : deux lectures différentes du même MRN sur deux lignes du même envoi.

## D-2513 — Pavés de partie sur un scan : ligne découpée, bruit, colonne de droite

- **Constat** (factures commerciales scannées, g4) : nom de l'acheteur réduit à « SARL » (ligne imprimée lue en
  deux lignes OCR de même hauteur, « SARL » avant « Utopia Outillage ») ; pavé mêlant les deux colonnes (un « 7 »
  ou un « . » isolé fixait la largeur de colonne) ; colonne de droite non vue quand l'OCR lit les deux colonnes
  sur une même ligne.
- **Choix** (`_mise_en_page.pave`, `colonne_droite`, texte OCR seulement) : deux lignes du pavé qui se recouvrent
  verticalement d'au moins la moitié de leur hauteur sont réunies dans l'ordre horizontal ; une ligne faite
  uniquement de bruit (ponctuation, chiffre isolé) est sautée sans clore le pavé ; le bruit ne borne pas la
  colonne ; un segment séparé du pavé par un blanc de plus de 0,08 ouvre la colonne de droite.

## D-2514 — Pavé acheteur : libellé déformé, nom illisible, suite de libellé

- Libellé OCR déformé (« Facuré à », « Recimungsempfanger », « Billto/Buyer . ») : quand aucun libellé n'est
  reconnu sur la première page d'un scan, un segment dont le texte (lettres seules) est à une édition (deux au-delà
  de dix lettres) d'un libellé d'acheteur usuel, et plus loin de tout libellé de livraison, de vendeur ou de titre
  (« FACTURE » n'est pas « Facturé à »), ouvre le pavé. Valeurs plafonnées : nom et adresse 0,80, TVA 0,85
  (aucune ne fonde seule un écart certain).
- « Bill to] Buyer » : la fin déformée du libellé n'est pas prise pour le nom ; une ligne d'adresse (« 21 boulevard
  du Mirage », nom illisible) n'est jamais un nom ; ponctuation de fin retirée (« … SA - »).
- Correctif : le test « ligne de TVA » du nom de l'acheteur cherchait « iva » sans frontière de mot à gauche :
  « Helvetia Fic**tiva** AG » était écarté comme ligne de TVA (16 factures g4, 11 g2) ; désormais `\b(vat|tva|iva)\b`.

## D-2515 — Natures : mot court lu par l'OCR

- « Cło » lu « Cto » : pour un libellé OCR (`tolerant`), un mot de 3 à 5 lettres inconnu est remplacé par
  l'**unique** mot court du vocabulaire dont il ne diffère que d'un caractère appartenant à une même classe de
  glyphes confondus (l/t/i/1/|/f, o/0, s/5, b/8, z/2, g/9/q, e/3). Aucun remplacement en texte natif, ni avec
  deux candidats, ni avec deux différences.

## D-2516 — Variantes d'un même MRN sur une facture de transitaire

- Deux groupes de lectures d'un MRN (après la table de confusion O/0, I/1…) dont les formes ne diffèrent que d'un
  caractère hors table (« 7 » / « Z », « J » / « I »), l'un au moins lu par OCR, chacun n'ayant que l'autre pour
  voisin, sont réunis : chaque ligne porte la lecture retenue (la plus fréquente), confiance ≤ 0,70. Deux MRN lus
  en texte natif ne sont jamais réunis.
- Limite : quand les deux lectures sont aussi fréquentes, la retenue peut être la mauvaise (g2 GX0196, c1 BX0192 :
  « J » / « I ») ; elle reste à 0,70 et cohérente sur toute la facture.

## D-2517 — Mesures (dev seulement)

- Factures commerciales, nom / TVA de l'acheteur : g4 77,7 / 90,0 % → 95,7 / 95,7 % ; g2 91,0 / 92,4 % →
  95,1 / 98,3 % ; corpus d'origine 90,6 / 92,2 % → 91,2 / 94,2 %. Bande ≥ 0,90 inchangée (g4 8 faux sur 8 303,
  déjà expliqués D-2512 ; g2 et corpus 0).
- Factures de transitaire : natures g4 84,2 → 84,5 % ; MRN de ligne g2 −5, corpus −1, `refs_mrn` corpus +2
  (D-2516) ; bande ≥ 0,90 inchangée.
- Banc dev : g4 84 VP / 0 FP certain (identique à `g4_dev_ctl27`), bruit 289 → 273, violations de pièges
  44 → 40, bruit A1 12 → 4 ; g2 112 → 113 VP / 0 FP ; corpus d'origine 119 / 0, seuil PASSE (identique).

# OCR : pages scannées dégradées (`corpus_g4`, dev seulement)

Nouvelles dégradations de `bench/corpus_g4` (télécopie bruitée, inclinaison + faible contraste, tampons et
écriture manuscrite colorés, JPEG très compressé, deux pages par feuille, pages retournées). Prétraitement en
PIL seul (aucune dépendance ajoutée), fonctions pures dans `ingest/pretraitement.py`, appelées par
`ingest/pages._ocr_image` dans le processus isolé de pages : isolement, plafond mémoire et délais (D-1600+)
inchangés. `VERSION_PAGES` 1.0.1 -> **1.1.0** (texte OCR modifié : caches de pages et clé d'idempotence de
l'étape 2 à refaire). Réglages regroupés dans `pages.REGLAGES_OCR` (mesure de variantes ; le pipeline ne les
modifie jamais). Chaque opération appliquée laisse un avertissement `pretraitement:…` sur la page (traçabilité).

## D-2601 — Gris par maximum des canaux sur un scan couleur sur papier blanc

- Gris = max(R, V, B) au lieu de la luminance : le noir et le gris neutres sont inchangés, un tampon rouge clair
  (≈ 200,120,120 : luminance 147 -> 200) ou une écriture bleue (≈ 90,120,165 : 122 -> 165) passe au-dessus du
  seuil de binarisation de Tesseract ; un texte coloré foncé du document (bleu marine) reste du texte.
- Seulement si le fond (médiane de luminance) est ≥ 215 (papier blanc) : sur une photo de document (fond brun,
  ombre), le maximum des canaux effaçait le bord de page (facture photographiée G2 : 23 -> 12 valeurs).

## D-2602 — Traits de télécopie effacés ; médian 3 × 3 sur télécopie seulement

- Trait parasite = colonne (rangée) encrée sur ≥ 92 % de la hauteur (largeur), ≤ 12 px d'épaisseur ; profil
  calculé par réduction BOX. Chaque pixel du trait prend le plus clair de ses deux voisins hors du trait : un
  caractère traversé garde sa continuité, le reste devient fond. Un filet de tableau ou de cadre s'arrête aux
  marges et n'est pas touché.
- Médian 3 × 3 (points isolés, trous dans les traits) seulement sur une **page de télécopie** : peu de
  demi-teintes parmi les pixels d'encre (< 55 % ; scan en niveaux de gris ≥ 58 %, télécopie rendue 39–50 %) et
  ≥ 2 000 px de côté. Rejeté : médian sur toute page « bruitée » (taux de points isolés) — l'indicateur ne
  séparait pas le grain d'un scan du bruit de télécopie, et le médian rongeait les petits caractères et les
  pointillés de remplissage (scan250j, TIFF fax 200 dpi : -3 à -19 valeurs par document). Évalué avant
  l'étirement de contraste (demi-teintes d'origine).

## D-2603 — Étirement du contraste d'une page pâle

- Encre (centile 0,5 %) -> 0, fond (médiane) -> 255, si l'encre est plus claire que 140 et l'écart < 150.
  Les photos (encre 20–80 sur fond gris) et le JPEG très compressé (encre ~100) ne sont pas étirés : l'étirement
  y amplifiait ombre et artefacts (photo G2 -16 valeurs ; jpegheavy -1,8 point).

## D-2604 — Deux pages par feuille : une page physique, lue moitié par moitié

- Détection (`coupure_deux_pages`) : feuille paysage (largeur ≥ 1,2 × hauteur), gouttière blanche (≥ 1,5 % de la
  largeur, éventuellement avec un filet séparateur) dans la bande 40–60 %, encre des deux côtés, et dans chaque
  moitié un profil des rangées plus net que celui des colonnes (une page portrait tournée de 90° n'est pas
  coupée). Détectée avant l'OSD : seul un retournement de 180° est alors accepté (l'OSD accepte sinon un 90/270
  peu confiant sur une feuille paysage).
- Chaque moitié est désinclinée et lue seule ; les lignes de la moitié gauche précèdent celles de la droite et
  **aucune ligne ne mêle les deux moitiés** (avant : `construire_lignes` fusionnait les lignes de même hauteur des
  deux pages, « Hop pellets … 12,687.78   Amber glass bottle … »).
- **Convention de numérotation** : la feuille reste **une** page (`numero` = n° de page physique du fichier,
  aucun décalage des pages suivantes) ; les boîtes des mots sont normalisées sur la feuille entière (moitié
  droite : x ≥ abscisse de coupe). Une citation « page n » et son rognage (`rapport/images.py` rend
  `pdf[numero - 1]` puis découpe la zone) pointent donc au bon endroit de la feuille, et la vérité du banc
  (pages physiques) reste comparable. Avertissement `deux_pages_par_feuille:<coupe relative>` sur la page : un
  découpeur qui voudrait traiter les moitiés comme deux pages logiques sait où elles commencent (moitié gauche :
  lignes de x1 ≤ coupe). Feuille portrait à deux pages empilées : non coupée (Tesseract `psm 3` les lit déjà dans
  l'ordre, les lignes ne se mêlent pas).

## D-2605 — Réessai d'orientation quand la lecture est mauvaise (suite de D-2113)

- Les autres orientations sont essayées non seulement sans verdict OSD, mais aussi quand la **qualité de
  lecture** (confiance × `score_texte`) est < 0,40, même après un verdict OSD confiant. Mesure : une page lue
  à l'envers garde une confiance Tesseract de 0,36–0,43 (le seuil de 0,40 sur la confiance seule, proposé en
  D-2113, la manquait) mais une qualité de 0,28–0,33 ; une page droite dépasse 0,8. Ordre d'essai 0, 180, 90,
  270 : Tesseract `psm 3` relit seul une page tournée de 90°, si bien qu'un essai à 90° rendrait la même lecture
  sous une étiquette fausse. Coût : seulement sur les pages mal lues.

## D-2606 — Mesures (`scripts/mesure_ocr.py`, dev seulement)

Part des valeurs de vérité (montants ≥ 3 chiffres, références ≥ 5 caractères, noms) retrouvées dans le texte des
pages des documents scannés, après normalisation (séparateurs de milliers, zéros décimaux, casse, accents,
ponctuation). Avant = code 1.0.1, après = 1.1.0, même machine.

| corpus (pages scannées) | avant | après | modes en hausse |
|---|---|---|---|
| `corpus_g4` (384) | 75,0 % | 76,6 % | jpegheavy +6,7, faxtiff +6,8, faxnoise +4,6, fax +3,9, lowcontrast +3,6, twoup +3,6, skewlow +3,0, overlay +2,6 |
| `corpus_g2` (523) | 78,9 % | 80,4 % | lowcontrast +8,2, fax +5,1, faxtiff +3,0 |
| `corpus` (652) | 60,0 % | 62,2 % | d3 (télécopie) 17,8 -> 29,7 % |

Scans propres (scan300, scan250j, d1, d2, rotated, skew200, jpeg150, photo) : identiques (±0,1 point) ;
tiff200 G2 -0,6 (1 valeur). Confiance OCR moyenne 0,838 -> 0,845 (G4), 0,834 -> 0,861 (corpus). Pages
retournées : aucune page du dev n'a changé d'orientation (les cas G4 « rotated » étaient déjà bien lus) ; le
réessai est couvert par un test (OSD forcé à 180° sur une page droite). Temps (A/B alterné sur 42 pages des
trois corpus, un processus) : p50 2,53 -> 2,84 s, p95 4,39 -> 4,52 s, moyenne 2,85 -> 3,02 s par page
(+6 %). Tests : `tests/ingest/test_ingest_pretraitement.py` (images synthétiques générées dans les tests).

### D-2710 — C8 : importateur déclaré illisible

Constat (dev `corpus_g4`, après le passage à l'OCR 1.1.0) : piège GZ0220-T3. Le transitaire facture l'entité
importatrice déclarée, mais le numéro de TVA de l'importateur est illisible sur la déclaration (confiance 0,02),
si bien que C8 comparait le client facturé à l'acheteur de la facture commerciale et concluait avec certitude.
Règle : quand le dossier contient une déclaration et qu'aucune ne porte un numéro d'importateur lu à 0,90 au
moins, C8 reste « à vérifier » (motif `importateur_declare_non_lu`). Coût sur les dev : un vrai C8 certain du
`corpus_g2` (GX0200, même situation de lecture) passe « à vérifier », toujours détecté ; deux faux certains en
moins (GZ0220, et BX0038 avec D-2711). Test : `test_c8_importateur_declare_illisible_reste_a_verifier`.

### D-2711 — B2 : total de droits et taxes imprimé négatif

Constat (dev `corpus`, OCR 1.1.0) : BX0038, total « -83,69 » lu au lieu de « 83,69 ». Sur une déclaration
d'import, un total de droits et taxes négatif est presque toujours un signe mal lu (tiret, trait de tableau) :
il ne fonde pas un écart certain (motif de structure). Test :
`test_total_negatif_imprime_ne_fonde_pas_un_ecart_certain`.

Mesures après D-2710/D-2711 (dev, OCR 1.1.0) : `corpus_g4` 84 vrais / 0 faux certains (rappel 0,805),
`corpus_g2` 111 / 0 (0,840), `corpus` 120 / 0 (0,827) ; les trois seuils passent.

# Contrôles : écarts certains sur des documents jamais vus — D4, A4/A5, preuves imprimées (dev seulement)

Constat : sur les jeux tenus à l'écart (OCR 1.1.0), il restait un faux écart certain D4 (jeu de type `corpus_g4`) et un
A4 (jeu de type `corpus_h2`). Ces dossiers n'ont pas été ouverts. Étude, sur les seuls jeux de développement des trois
corpus, de tous les constats D4 et A2–A5 (vrais, faux, « à vérifier », pièges déclenchés) et des chemins de code, à la
recherche des façons dont un constat peut être certain et faux — montant compris : un écart certain au montant faux
compte comme un faux certain. Un cas réel a été trouvé, sauvé par chance : GZ0179 (factures de débours et de
prestations séparées, facture de débours scannée dont la ligne de TVA n'est pas lue) — la complétude de D-2703 était
prouvée sur la facture de prestations (Σ lignes = total HT), pas sur celle des débours ; D4 aurait été certain
(38,14) si le total liquidé de la déclaration n'avait pas expliqué le FAF. Règles générales seulement : aucune ne lit
un nom de gabarit, de fichier, de client ou de transitaire. Tests : `tests/controls/test_precision_d28.py` (24 cas
fictifs).

## D-2801 — D4 : assiette établie sans ambiguïté

- **Complétude prouvée sur chaque facture dont viennent les débours** (`famille_d._Assiette.factures`) et non plus
  seulement sur la facture qui porte le FAF : facture de débours séparée de la facture de prestations, débours d'un
  relevé. Motif `details.factures_de_debours_non_confirmees`. Les totaux des débours imprimés de ces factures
  (avec et sans TVA) s'ajoutent aux assiettes alternatives de D-2213.
- **Complétude par le total HT** (aucun total des débours imprimé) : Σ lignes = total HT prouve que toutes les lignes
  sont lues, pas qu'une ligne de débours au libellé illisible (« Cło » lu « Cto ») n'a pas été prise pour une
  prestation. Exigé en plus : Σ (HT × taux de la ligne, lu ou déduit selon la nature) = total de TVA imprimé
  (`_tva_concorde`) ; une ligne de débours (sans TVA) comptée comme prestation au taux normal romprait l'égalité.
- **Conventions que les documents ne fixent pas** → raison nouvelle `assiette_non_etablie`
  (`details.assiette_non_etablie`) :
  1. `faf_par_envoi_non_ventile` : l'assiette couvre plusieurs déclarations, la ligne de FAF ne cite pas de MRN et
     la facture porte plusieurs lignes de FAF (une par envoi, laquelle ?) — GZ0048, GX0152, GX0164 ;
  2. `bornes_par_envoi_ou_par_facture` : une ligne de FAF pour plusieurs déclarations et le minimum/maximum
     appliqué par envoi donne un autre attendu qu'appliqué à la somme (ou la ventilation par envoi n'est pas
     connue alors que la grille a des bornes) — huit relevés du corpus d'origine, tous `conforme` ;
  3. `avoirs_dans_les_debours` : montants négatifs (lignes d'avoir mêlées au relevé) ou avoirs de débours déjà
     reçus, et l'attendu sur les débours bruts ou nets diffère.
  Une ligne de débours « TVA comprise » de l'assiette (D-2701) devient valeur clé même quand l'attendu est borné.
- **Écartés** : exiger que le FAF dépasse l'attendu de *toutes* les assiettes (droits, débours avec/sans TVA) :
  la TVA pèse lourd, les vrais D4 non bornés (GX0098, BX0201) seraient perdus ; FAF égal au prix forfaitaire d'un
  autre poste de la grille (ligne mal rapprochée) : 17 coïncidences de montants ronds sur les `conforme` du dev g4,
  les libellés reconnus des grilles sont en français et ne départagent pas les lignes étrangères.

## D-2802 — D4 : grille du transitaire qui émet la facture ; devise illisible

- `famille_c.grille_pour_facture` : transitaire désigné par l'émetteur de la facture elle-même (TVA, puis nom ou
  alias), à défaut celui du dossier (qui est celui de sa *première* facture identifiée) : une facture d'un autre
  transitaire rangée dans le dossier se compare à la grille de son propre émetteur (C6 et D en profitent).
- D4 certain seulement si l'émetteur lu sur la facture désigne le transitaire de la grille ; sinon raison nouvelle
  `grille_non_attestee` (motif `emetteur_non_identifie`). Émetteur non identifié sur le dev : 3 factures sur 253
  (g4), 6 sur 314 (g2), 3 sur 319 (origine), aucune avec un D4 certain.
- Devise de la facture lue mais inutilisable (sous `C_MIN_UTILE`) → `devise_incertaine` (la grille est en euros).
  Une devise absente reste « EUR supposé » (les factures sans devise du banc sont en euros ; écarté : exiger une
  devise lue, qui casse les factures natives sans mention de devise).

## D-2803 — A4 / A5 : périmètre des montants comparés, échelle et signe

`famille_a._perimetre_non_etabli`, raison nouvelle `perimetre_non_etabli` (`details.perimetre_non_etabli`), sur le
constat principal de A4 et sur A5 (même montant déclaré, référence convertie) :
- `facture_citee_absente` (déclaré > facture) : la déclaration cite avec un code de facture (N380, 380, 325, 935…)
  une référence qu'aucune facture commerciale du couple ne porte — « deux factures pour une déclaration » dont une
  manque ou a été rangée ailleurs ;
- `declaration_citee_absente` (déclaré < facture) : une facture du transitaire qui cite le MRN d'une déclaration
  du couple cite aussi un MRN qu'aucune déclaration lue (ce dossier ou un autre) ne porte ; ou une déclaration
  d'un autre dossier cite une facture du couple — facture répartie sur plusieurs déclarations. BX0244 (deux
  déclarations d'un même PDF lues comme une seule) passait à un niveau de confiance près du certain faux ;
- `facteur_puissance_de_dix` : déclaré = référence × 10^k (k = ±1 à ±3, à 0,05 % près) : séparateur décimal ou de
  milliers lu autrement (devise sans décimales) ;
- `montant_negatif_lu` : total de facture commerciale ou montant déclaré négatif (GZ0144 : −161 827,40 contre
  +161 827,40) ;
- `total_lu_avant_des_lignes` : le total retenu est imprimé sur une page qui précède des lignes de la même facture
  (total de page, report ; mise en page multipage). Écarté : étendre à « total imprimé au-dessus de lignes de la
  même page » — un seul cas sur le dev des trois jeux, un vrai total en tête de page (GZ0082).
Aucun constat certain du dev n'est touché ; les motifs ne s'appliquent qu'aux écarts hors tolérance.

## D-2804 — Lecture corroborée : identités imprimées des factures « TVA comprise » et des taux non imprimés

Dans l'esprit de D-1700 (la confirmation vient toujours de l'arithmétique imprimée du même document, jamais d'une
valeur dérivée) :
- Σ débours = total des débours : seules les lignes de **débours** doivent être lues (avant : toutes les lignes ;
  une ligne de prestation qui n'imprime que son TTC empêchait l'identité) ;
- Σ TTC des lignes = total TTC (`ttc_lignes`, portée « tout ») quand chaque ligne imprime son TTC ;
- Σ HT lus × taux déduits (taux normal selon la nature, quand les taux de ligne ne sont pas imprimés) = total de
  TVA lu (`tva_base_taux_deduits`, portée « taxable ») : membres confirmés le total de TVA et les HT lus, **jamais**
  les taux déduits. Un taux mal attribué (débours compté au taux normal) rompt l'identité.
Effet (dev g4, extraction figée) : sept erreurs attendues ou non « certain » deviennent certaines, montants justes
(C1 ×2, C3, C4, D1 ×3 ; factures portugaises TVA comprise, natives et scannées, D1 « total TTC »), aucune fausse.

## D-2805 — B2 : article au nombre de lignes de taxe inégal et ligne sans code de taxe

Constat (banc final, extraction du moment) : GX0026, déclaration scannée de deux articles ; l'article 1 a ses
droits et sa TVA, l'article 2 une seule ligne au code illisible ; une ligne de 1,59 n'est pas lue. Le total des
droits et taxes (53,17) passe de 0,80 à 0,93 avec la nouvelle extraction : B2 certain faux (1,59), aussi avec les
contrôles d'avant. `structure_declaration.motifs_structure_taxes` : articles au nombre de lignes de taxe inégal
**et** ligne sans code de taxe lisible → `structure_non_validee` (D-2210). Touche 4 B2 du dev, tous déjà
« à vérifier » sauf GX0026.

## D-2806 — Mesures (dev seulement)

**Effet des seuls contrôles** (extraction figée : mêmes documents préparés, contrôles du dépôt contre contrôles
modifiés) :

| | `corpus_g4` avant | après | `corpus_g2` avant | après | corpus d'origine avant | après |
|---|---|---|---|---|---|---|
| VP / FP certain | 84 / 0 | 91 / 0 | 111 / 0 | 111 / 0 | 120 / 0 | 120 / 0 |
| rappel certain | 0,600 | 0,642 | 0,755 | 0,755 | 0,785 | 0,785 |
| sous-classements | 32 | 27 | 23 | 23 | 18 | 18 |
| violations de pièges | 44 | 44 | 34 | 34 | 29 | 29 |

**Bancs complets** `*_dev_d27b` → `*_dev_c5` (code du moment, y compris l'extraction D-2901 à D-2905 menée en
parallèle et `VERSION_PAGES` 1.1.1) :

| | `corpus_g4` avant | après | `corpus_g2` avant | après | corpus d'origine avant | après |
|---|---|---|---|---|---|---|
| VP / FP certain | 84 / 0 | 98 / 0 | 111 / 0 | 113 / 0 | 120 / 0 | 120 / 0 |
| rappel | 0,805 | 0,821 | 0,840 | 0,860 | 0,827 | 0,827 |
| rappel certain | 0,600 | 0,692 | 0,755 | 0,763 | 0,785 | 0,785 |
| sous-classements | 32 | 24 | 23 | 25 | 18 | 18 |
| bruit « à vérifier » par dossier | 1,57 | 1,46 | 1,42 | 1,39 | 1,19 | 1,18 |
| violations de pièges | 44 | 51 | 34 | 35 | 29 | 29 |

Seuils bloquants : PASSE sur les trois. Aucun vrai certain perdu. Les violations de pièges nouvelles (toutes
« à vérifier ») viennent de l'extraction (inchangées à extraction figée). Sans D-2805, `corpus_g2` aurait un faux
certain (GX0026 B2), dû à la nouvelle extraction.

**Sous-classements restants sur le dev `corpus_g4`** (24) : F3 ×5 (MRN de ligne lu 0,85 et rattachement faible de
l'autre facture, propre à l'erreur elle-même : non modifié), B1 ×4 (base et taux lus 0,55–0,80 sur scan, sans autre
identité), C5 ×3 (total liquidé non confirmé), A5 ×2 (taux de change OCR 0,86–0,88 : aucune seconde lecture ;
écarté : le confirmer par le taux de référence, une erreur de lecture de 0,3 % fausserait le montant), puis un cas
chacun (C8, C4, D1, D2, D5, D7, D9, A1). Aucun ne repose sur une preuve robuste au sens de la consigne.

**Relevé pour l'extraction** : GX0026 (total des droits et taxes relevé à 0,93 alors qu'une ligne de taxe manque) ;
lignes d'avoir d'un relevé lues positives et comme prestations (« Gutschrift zu Rechnung … », GZ0041, GZ0107) ;
deux déclarations d'un même PDF lues comme une seule (BX0244) ; ligne de TVA perdue d'une facture de débours scannée
(GZ0179) ; total de facture commerciale lu négatif (GZ0144) ; totaux par code de taxe absents du modèle (D-2903).

# Extraction : valeurs décisives manquantes ou peu sûres sur `corpus_g4` (dev seulement)

Constat (banc `g4_dev_d27b`, 120 erreurs attendues « certain », 84 trouvées certaines) : sur les 36 manquées, la
cause côté lecture est surtout (a) des documents de deux pages coupés en deux documents (facture de transitaire et
avoir paysage « par MRN » dont la page 2 porte le récapitulatif, annexe de débours espagnole, page 2 d'une facture
rangée sous l'autre type), si bien que les lignes et les totaux ne se recoupent plus ; (b) des feuilles paysage
prises à tort pour des feuilles « deux pages » (D-2604) : chaque rangée du tableau était lue en deux lignes et les
lignes de la facture n'étaient pas lues (G16 scannée : 48 montants de ligne absents sur 56) ; (c) des valeurs
lues par OCR justes mais sous 0,90 faute d'identité imprimée exploitée (totaux par code de taxe, TTC = HT + TVA +
débours, Σ TVA des lignes, taux « 20,00 » sous « TVA % »). Règles générales seulement : aucune ne lit un nom de
gabarit, de fichier, de client ou de transitaire.

## D-2901 — Découpage : numéro sans libellé, numéro imprimé sur la page précédente, « page 2 »

- `classement.extraire_refs` : dans les 8 premières lignes, numéro imprimé juste après l'intitulé, sans « N° »
  (« FACTURE HTD2026-47293 », « AVOIR HTD-AV-09866 », « FACTURA COMPLEMENT FT26-97327 », « FAKTURA … Nr
  FV/03342/07/2026 ») : au moins 6 caractères utiles et un chiffre, ni date, ni année, ni montant ; un intitulé
  cité (« avoir sur facture X », « credit note for invoice X ») n'en donne pas. Numéro de page « … — page 2 »,
  « — str. 2 » en fin de ligne, « 2/2 » en fin d'une des 4 premières lignes. `RefsPage.jetons` : références
  imprimées de la page (alphanumériques ≥ 6 caractères avec un chiffre).
- `decoupage._meme_document` : (1) facture dont la page 1 n'a pas donné de numéro, page suivante qui en donne un :
  même document si ce numéro est imprimé (à deux confusions OCR près) sur les pages en cours ; (2) page rangée
  sous l'autre type de facture (commerciale / transitaire, confiance < 0,90), qui n'est pas une page 1 et porte le
  numéro de la facture en cours : suite de celle-ci ; (3) « page 2/2 » dont le numéro lu ne diffère de celui de
  la page 1 que d'un caractère : pas de changement de document ; (4) page de suite d'une déclaration dont le MRN
  de la page de tête n'a pas été lu : même déclaration.
- Mesure (dev, documents attendus retrouvés à l'identique, fichier × pages × type) : `corpus_g4` 61 → 9
  manquants, `corpus_g2` 71 → 22, corpus d'origine 89 → 29 (restent surtout des classeurs dont la vérité ne
  compte qu'une feuille) ; aucun dossier dégradé. Tests : `tests/ingest/test_decoupage_d29.py`.

## D-2902 — Feuille « deux pages » écartée quand du texte touche la coupure (`VERSION_PAGES` 1.1.1)

- **Défaut** (prétraitement OCR, D-2604) : sur une facture paysage dont deux colonnes du tableau encadrent la bande
  centrale (« Unité » | « P.U. HT ») et dont le pied centré a un blanc entre deux mots au même endroit,
  `coupure_deux_pages` trouvait une gouttière : 15 pages du dev `corpus_g4` coupées pour 2 vraies feuilles
  « deux pages », 12 sur `corpus_g2`. Les rangées étaient lues en deux moitiés et le tableau perdu.
- **Règle** (`pages.moities_separees`) : après la lecture des deux moitiés, si une ligne de texte (mots d'au moins
  deux caractères alphanumériques) finit ou commence à moins de 1,2 % de la largeur de la coupure, la feuille est
  une seule page, relue entière (avertissement `deux_pages_ecarte`). Sur le dev, le texte des vraies feuilles
  « deux pages » reste à 3,2 % au moins de la coupure (marges des deux pages réduites) ; celui des pages coupées
  à tort la touche (0 à 0,9 %), sauf une facture G1 (5,8 %), toujours coupée.
- **Coût** : la clé de cache des pages change (`VERSION_PAGES` 1.1.0 → 1.1.1) : toutes les pages OCR sont relues
  une fois (dev des trois jeux relus ici ; les caches des jeux tenus à l'écart devront l'être). Le prétraitement
  lui-même (D-2601 à D-2605) n'est pas modifié. Tests : `tests/ingest/test_decoupage_d29.py`.

## D-2903 — Déclaration : totaux imprimés par code de taxe ; séparateur décimal lu « : »

- `_totaux_categories` lit « Total A00 : 323,00 Total B00 : 2 553,90 », « Total AO0 EUR 477.10 » et les rangées
  d'un récapitulatif « A00 Droits de douane 96,65 » (code, libellé, un seul montant, hors tableaux de taxation),
  pour les seuls codes des lignes de taxation lues (« total TRY 616 558,35 » n'en est pas un). Ils ne sont **pas**
  ajoutés aux taxations : une ligne sans article serait additionnée par les contrôles qui somment les lignes
  (famille C). Ils servent aux recoupements OCR (`_recouper_totaux_categories`), qui ne font que confirmer :
  Σ des totaux par code (≥ 2 codes) = total des droits et taxes imprimé → ce total ; total à payer = cette somme,
  ou cette somme moins les codes dont toutes les lignes sont autoliquidées → le total à payer ; Σ des montants
  des lignes d'un code (≥ 2 non nuls) = total du code → ces montants. Un désaccord n'abaisse rien (le total du
  code peut être la valeur fausse, B2).
- Montant de ligne de taxe lu « 3:46: », « 12:591;51 » (séparateurs lus « : » / « ; ») : relu 3,46 / 12 591,51,
  confiance de relecture (jamais au-dessus de `PLAFOND_REPARE`) ; il complète les sommes.
- **Non fait, pour les contrôles** : B2 par code (« total A00 imprimé faux ») reste invisible tant que ces totaux
  ne sont pas portés par le modèle (3 erreurs attendues certaines du dev g4, 3 de g2, 2 du corpus d'origine) ; il
  faudrait un champ dédié (par ex. `ChampsDeclaration.totaux_par_code`) lu par B2 et par le réseau d'identités.
  Tests : `tests/extract/test_totaux_categories_d29.py`.

## D-2904 — Facture de transitaire OCR : membres d'une somme imprimée qui tient

- Une somme imprimée qui tient avec au moins deux opérandes non nuls (Σ lignes = total HT, Σ débours = total des
  débours, HT + TVA = TTC, Σ TVA des lignes = total TVA) relève ses membres à 0,92 dès que la confiance OCR de leurs
  mots atteint 0,60 (avant : 0,90 exigé comme pour une simple double lecture « 1 × x = x ») : une erreur de lecture
  d'un membre devrait être compensée exactement par une autre. Les montants OCR suspects (milliers sans
  séparateur, D-2505) et les rangées perdues restent exclus ; une contradiction abaisse toujours.
- Identités ajoutées : total HT des seules prestations (Σ prestations = total HT quand les débours ont leur
  total) ; TTC = HT des prestations + TVA + total des débours (récapitulatif sur une page à part, factures polonaise et française « par MRN ») — les
  mêmes que celles du réseau des contrôles (`total_ht_prestations`, `total_ttc_debours`).
  Tests : `tests/extract/test_ft_sommes_ocr_d29.py`.

## D-2905 — Taux de TVA « 20,00 » sous l'intitulé « TVA % » ; HT confirmé par la TVA de sa ligne

- Dans une colonne de taux, un nombre à deux décimales entre 0 et 30 est le taux de la ligne (avant : pris pour un
  montant et ignoré ; le taux était déduit, confiance ≤ 0,60). Effet `corpus_g4` : taux des lignes ≥ 0,90 justes
  120 → 314 (natif), sans valeur fausse.
- Σ TVA des lignes lues = total TVA imprimé confirme ces TVA ; une ligne dont HT × taux imprimé = TVA confirmée
  voit son HT confirmé (chaîne d'identités imprimées, D-2904), même quand le total HT est la valeur contestée (D1).

## D-2906 — Total des droits et taxes confirmé seulement si toutes les lignes attendues sont lues ; déclarations au même titre

- `_lignes_taxes_completes` : chaque article attendu (numéros lus, `1..nombre_articles`) a une ligne pour chaque
  code rattaché à des articles, avec un code et un montant lisibles. Sinon ni Σ des lignes ni Σ des totaux par
  code (D-2903) ne confirme le total des droits et taxes ou le total à payer (GX0026 : ligne A00 de l'article 2
  non lue, total confirmé à 0,93 par les totaux par code).
- Découpage : une page de déclaration intitulée, sans annonce de suite ni numéro de page, au **même titre** que la
  page de tête du document en cours (après au moins une page de suite) ouvre une autre déclaration (BX0244 :
  deux DAU + DAU-bis dans un PDF, MRN de la seconde illisible). Tests : `test_totaux_categories_d29.py`,
  `test_decoupage_d29.py`.

## D-2907 — Signes : ligne de crédit dans une facture ; tiret détaché devant un total

- Facture de transitaire : un montant déduit d'un seul montant imprimé négatif (prix unitaire, TVA d'une ligne
  « Gutschrift zu Rechnung … -18.50 ») porte le même signe imprimé (avant : positif, d'où un prix « +18,50 » lu
  par les contrôles). Le montant HT gardait déjà son signe (D-2505).
- Facture commerciale : total lu par OCR « - 161 827,40 » (tiret détaché, trait de tableau) : pas un signe ; la
  lecture reste sous le seuil (≤ 0,70). Tests : `test_ft_sommes_ocr_d29.py`.
- **Non corrigé** : GZ0179, deuxième ligne de débours « Btw bij invoer € 1.580,20 » lue « ee 8020 » sur un TIFF
  200 dpi : montant illisible ; la reconstruire par différence avec le total des débours ne donnerait qu'une
  valeur déduite (jamais une base d'écart certain).

## D-2908 — Mesures (dev seulement)

`scripts/mesure_extraction.py`, cinq types, valeurs de confiance ≥ 0,90 fausses (avant → après, OCR 1.1.0 →
1.1.1) : `corpus_g4` 1+3+0+0+0 → 1+3+0+0+0 (FT : 4 269 → 4 680 valeurs ≥ 0,90), `corpus_g2` 6+3+0+0+0 → 5+3+0+0+0,
corpus d'origine 0+2+1+0+0 → 0+2+1+0+0 : aucune valeur fausse nouvelle, toutes ≥ 99,9 % justes par type. Gains
`corpus_g4` (scans) : montants HT de ligne justes 343 → 389 dont ≥ 0,90 163 → 235 ; TVA de ligne ≥ 0,90 95 → 148 ;
taux lus ≥ 0,90 (natif) 120 → 314 ; totaux des droits et taxes des déclarations ≥ 0,90 10 → 17 sur 52.

Banc (même code de contrôles, D-2801 à D-2806 compris ; `c5` = contrôles + extraction en cours, `x5` = final) :

| dev | VP / FP certains | rappel certain | rappel | montants justes | bruit / dossier | seuil |
|---|---|---|---|---|---|---|
| `corpus_g4` avant (`d27b`) | 84 / 0 | 0,600 | 0,805 | 0,956 | 1,57 | passe |
| `corpus_g4` après (`x5`) | 98 / 0 | 0,692 | 0,821 | 0,957 | 1,46 | passe |
| `corpus_g2` avant / après | 111 / 0 → 113 / 0 | 0,755 → 0,763 | 0,840 → 0,860 | 0,971 → 0,965 | 1,42 → 1,39 | passe |
| corpus d'origine avant / après | 120 / 0 → 120 / 0 | 0,785 → 0,785 | 0,827 → 0,827 | 0,953 → 0,953 | 1,19 → 1,15 | passe |

Les gains `corpus_g4` viennent de l'extraction (découpage D-2901, OCR D-2902, recoupements D-2903 à D-2905 : C1,
C3, D1 G13/G16 et G5) et des contrôles D-2801 à D-2806, mesurés ensemble.

# Interface

### D-3001 — Refonte visuelle de l'interface web (octobre 2026)

Demande : une interface « fluide et très moderne », avec effets et animations. Choix :
- **Rien d'externe** : la CSP reste `default-src 'self'` sans script en ligne. La bibliothèque d'animation Motion
  14.0.0 (licence MIT, `static/vendor/motion.min.js`, licence jointe) et les polices Geist et Geist Mono (SIL OFL 1.1,
  `static/vendor/fonts/`, licence jointe) sont servies par l'application. Aucun CDN, aucune police distante.
- **Thème** sombre par défaut, thème clair au choix (bouton, palette) ou selon le système. Le choix est mémorisé
  dans le navigateur (`localStorage`, clé `cd-theme`, aucune donnée personnelle). Il est appliqué avant le premier
  affichage par `static/theme.js`, chargé de façon synchrone dans `<head>`.
- **Effets** :
  - entrées en cascade (fondu, flou, glissement) ; les éléments sous la ligne de flottaison s'animent à leur entrée
    dans la vue ;
  - compteurs qui défilent jusqu'au texte exact rendu par le serveur, remis tel quel à la fin, de sorte que
    l'affichage final est toujours celui du serveur ;
  - barres de proportion animées ;
  - halo qui suit le pointeur sur les cartes ;
  - pastille de navigation à ressort ;
  - barre de progression de lecture ;
  - boutons principaux légèrement « magnétiques » ;
  - transitions entre pages (View Transitions entre documents, navigateurs compatibles) ;
  - bascule de thème par dévoilement circulaire ;
  - palette de commandes Ctrl+K / ⌘K, construite à partir des liens de la page ;
  - zone de dépôt par glisser-déposer avec liste des fichiers ;
  - écran de connexion avec présentation du service. Les textes sont factuels : aucun chiffre, aucun témoignage,
    aucune promesse d'hébergement.
- **Garde-fous** :
  - l'interface fonctionne sans JavaScript : contenu visible, champ de fichier natif ;
  - si le script échoue, une animation CSS de secours rend tout visible après 2,2 s ;
  - « réduire les animations » est respecté ;
  - la mise en page d'impression est inchangée et toujours sur fond clair ;
  - le rapport HTML (CSP fermée, sans script) n'est pas touché.
- **Contrôles** : 2 075 tests passent. Le parcours fondateur, le parcours client et le mobile ont été vérifiés par
  captures (Playwright), dans les deux thèmes, sans erreur dans la console. Vidéo de démonstration (données
  fictives) : `docs/interface/demo_interface.mp4`.

## D-3301 — Sauvegarde : manifeste, traces d'envoi, empreinte externe (octobre 2026)

- **Constat** : l'archive ne contenait que la base et le coffre ; `var/outbox_envoyee/` (copies des rapports et
  factures mis à disposition) n'était pas sauvegardé, et rien ne permettait de vérifier une archive fichier par
  fichier sans la restaurer.
- **Choix** : même conteneur chiffré `CDSAV2` (D-1320) ; le tar contient `base/controldone.db`, `coffre/`,
  `outbox_envoyee/` puis, en dernier, `MANIFESTE.json` : taille et SHA-256 de chaque fichier (calculés pendant la
  copie, sur le descripteur ouvert), nombre de lignes par table, intégrité et tête de la chaîne d'audit de
  l'instantané. À côté : `….tar.gz.enc.sha256` au format `sha256sum`, empreinte de l'archive **chiffrée** (contrôle
  d'une copie hors site sans la clé ; ne révèle rien du contenu). Les archives sans manifeste restent restaurables.
- **Écarté** : un manifeste en clair à côté de l'archive (les noms des objets du coffre sont les SHA-256 des
  documents des clients : ils restent dans la partie chiffrée).

## D-3302 — Clés hors des sauvegardes

- Seules les entrées `base/`, `coffre/`, `outbox_envoyee/` et le manifeste sont écrites et admises à la restauration ;
  `dev_master.key`, `.env*`, `identifiants.txt` restent hors de l'archive (test). La clé maîtresse et le secret de
  session se conservent à part (gestionnaire de secrets + copie papier). Les secrets TOTP sont dans la base, chiffrés
  par une clé dérivée distincte (`secrets`) : ils voyagent chiffrés deux fois.
- Rotation de la clé maîtresse : garder l'ancienne clé dans `CONTROLDONE_MASTER_KEY` au moins 35 jours (durée de
  conservation hors site), sinon les archives antérieures deviennent illisibles.

## D-3303 — Vérification systématique, codes de retour, alertes

- `sauvegarder` relit toujours l'archive créée (déchiffrement de chaque segment jusqu'au segment final, SHA-256 de
  chaque fichier comparé au manifeste, empreinte externe) ; une archive non conforme est renommée `.invalide` (elle
  ne bloque pas le rattrapage `--si-absente` et n'entre pas dans la rotation). La lecture vide désormais le flux
  jusqu'au segment final : une archive dont seule la fin manque est refusée même si le tar se lit.
- Codes : 0 succès, 1 création, 2 configuration, 3 vérification, 4 fraîcheur ; `--hors-site` : 5 copie, 6 contrôle
  (`rclone check --one-way`). Alertes fondateur dédoublonnées par jour : `sauvegarde_echec`,
  `sauvegarde_verification_echec`, `sauvegarde_absente`, `sauvegarde_hors_site_echec` (l'hôte passe par
  `docker compose exec scheduler … alerter`). Sonde externe facultative `BACKUP_PING_URL` (`/0` succès,
  `/<code>` échec) : seule façon d'être prévenu quand plus rien ne tourne.
- `restaurer` n'écrit que dans un répertoire absent ou vide.

## D-3304 — Contrôle approfondi d'une restauration

- `controldone.storage.controle_restauration.controler` : intégrité SQLite, lignes par table égales au manifeste,
  chaîne d'audit (`verifier_chaine`) et tête identiques, chaque objet du coffre déchiffré avec les clés fournies et
  conforme à sa référence, chaque fichier et texte de page non purgé référencé par la base présent. Exposé par
  `restaurer --controler`, `controler`, `verifier --profond` et `sauvegarder --verification-profonde` (restauration
  d'essai dans un répertoire temporaire **du même volume** que les archives, effacé ensuite). Le planificateur Docker
  la fait le dimanche (`BACKUP_VERIFICATION_PROFONDE_JOUR`).

## D-3305 — Exercice de restauration de bout en bout (`make restauration-test`)

- `controldone sauvegarde exercice` (`services/exercice_restauration.py`) : base fictive neuve (`init-demo`) dans un
  répertoire temporaire avec une clé neuve tenue seulement dans l'environnement des sous-processus, sauvegarde par
  la ligne de commande, contrôles négatifs (autre clé, octet altéré, aucune clé dans l'archive), effacement de la
  source, restauration ailleurs, comparaison avec la source, puis `controldone serve` sur les données restaurées :
  connexion du fondateur avec TOTP, `/admin`, connexion d'un client, rapport publié rendu en HTML et PDF. Hors ligne
  (aucune clé d'API transmise, aucun `.env` lu), refuse `var/demo_web` et tout répertoire non vide. Durée ≈ 11 s ;
  aussi exécuté par `pytest` (marque `lent`, déclarée dans `pyproject.toml`).
- RPO/RTO documentés dans `deploy/README.md` : RPO 24 h (≈ 24 h 30 hors site), RTO objectif 4 h ouvrées non
  mesuré en conditions réelles, dominé par les gestes humains.

## D-3306 — Sauvegarde avant purge

- `deploy/scheduler.sh` lance la sauvegarde du jour **avant** de mettre en file `purger_retention` : la purge
  (worker) ne retire plus du coffre, pendant la copie, un contenu que l'instantané de la base référence encore. Un
  fichier purgé entre le parcours et la lecture n'est simplement pas copié ; le contrôle approfondi le signalerait
  comme « contenu référencé absent ».

# Sécurité : débit partagé, sessions, en-têtes, dépendances (bloc C, octobre 2026)

Revue complète : `docs/REVUE_SECURITE_2.md`. Tests : `tests/security/test_revue_securite_2.py`.

### D-3201 — Limitation de débit en base, partagée et persistante

- **Constat** : `auth.LimiteurDebit` était en mémoire de chaque processus. Un redémarrage remettait les compteurs
  à zéro (un attaquant n'avait qu'à attendre un redéploiement), plusieurs processus web ne partageaient rien, et
  chaque connexion **réussie** consommait aussi un jeton : le fondateur s'est retrouvé bloqué après une vingtaine de
  connexions de test, débloqué seulement en relançant le serveur.
- **Choix** : `auth.LimiteurDebitPartage`, seaux à jetons dans la table `debit_compteurs`
  (`storage/securite.py`), même interface et **mêmes seuils** (connexion : 10 par adresse et 5 par compte sur
  5 minutes ; second facteur et changement de mot de passe : seau du compte ; API : 120 en rafale puis 2/s, par
  préfixe de clé et par adresse).
  - Mise à jour atomique : `BEGIN IMMEDIATE` sous SQLite ; `SELECT … FOR UPDATE` et nouvel essai sur conflit de
    clé sous PostgreSQL. Testé sous concurrence (6 connexions × 10 essais → exactement 20 autorisés).
  - Clé stockée : `portée:HMAC-SHA256(sel, identifiant)`, sel dérivé de la clé maîtresse : ni adresse IP ni
    courriel en clair, pas de force brute sur l'espace IPv4.
  - Table bornée : une ligne expire quand son seau est de nouveau plein (elle ne porte plus d'information) ; purge
    au plus une fois par minute et par processus, plafond de 100 000 lignes (les plus proches de l'expiration
    partent d'abord) — des préfixes de clé d'API inventés ne font pas grossir la base.
  - Seuls les **échecs** épuisent la limite : une connexion réussie remet le compteur du compte à zéro et rend
    son jeton à l'adresse.
  - Base indisponible : bascule sur un seau en mémoire aux mêmes seuils, avertissement journalisé (nom
    d'exception seulement) ; jamais d'erreur 500 à cause du limiteur.
  - Déblocage : `controldone debit lister` et `controldone debit effacer --email … | --ip … | --cle-api … | --tout
    [--motif …]` (journal d'audit `debit_effacer`).
- **Écarté** : Redis (un service de plus à exploiter pour un seul processus web) ; compter seulement les échecs
  sans seau pour l'adresse (laisserait le bourrage d'identifiants sur de nombreux comptes).
- Le limiteur en mémoire reste pour les tests unitaires, le secours, et le suivi en direct des dépôts (D-3402).

### D-3202 — Révocation des sessions en base ; changement de mot de passe

- **Constat (RS-17)** : la déconnexion n'était connue que du processus qui la servait, et perdue au redémarrage ;
  un changement de mot de passe laissait ouvertes les autres sessions (cookie volé compris).
- **Choix** : table `sessions_revoquees` (`sid:<id>` à la déconnexion ; `user:<id>` avec un instant de coupure au
  changement ou à la réinitialisation du mot de passe : toute session **commencée** avant est refusée). Lue à chaque
  requête (lecture différée, sans verrou d'écriture). Lignes purgées après la durée absolue de session (8 h).
  Le changement de mot de passe remplace la session courante par une session neuve et ferme toutes les autres ; il
  est limité (seau du compte : 5 essais du mot de passe actuel sur 5 minutes).
- Réinitialisation : seulement en ligne de commande sur la machine du service (`controldone
  reinitialiser-mot-de-passe --email …`) ; pas de « mot de passe oublié » par courriel (aucun jeton de
  réinitialisation à voler ni à deviner). Sessions révoquées, compteurs remis à zéro, journalisé.
- Base indisponible à la lecture : la révocation locale du processus s'applique, la requête continue (les pages
  authentifiées relisent de toute façon le compte en base, RS-09).

### D-3203 — Audit des dépendances : `make audit`

- `scripts/audit_dependances.py` (outils dans `.venv-audit`, jamais dans l'image) : `pip-audit` sur
  `requirements.lock` (PyPI puis OSV ; sans réseau, échec sauf `HORS_LIGNE=1`, l'audit n'est jamais déclaré propre
  sans base consultée), SBOM CycloneDX 1.6 (`var/audit/sbom.cdx.json`) enrichi des licences et des composants servis
  par l'application (Motion 14.0.0 MIT, polices Geist OFL-1.1, avec empreinte SHA-256), liste des licences
  (`var/audit/licences.md`). Toute licence non permissive fait échouer l'audit sauf exception justifiée dans
  `config/audit_dependances.json` (`python-stdnum` LGPL, `certifi` MPL-2.0). Un fichier de `static/vendor` non
  déclaré fait échouer l'audit et le test permanent.
- Ajouté à l'intégration continue (déclenchement manuel), SBOM conservé comme artefact 30 jours.
- Résultat du 6 octobre 2026 : 68 paquets figés, **0 vulnérabilité connue** (PyPI et OSV), aucune licence non
  permissive hors exceptions. Aucune version à relever.

### D-3204 — En-têtes HTTP et rapports de violation CSP

- CSP inchangée dans son principe (`default-src 'self'`, aucun script ni style en ligne, `/static/theme.js`
  synchrone, Motion servi localement), complétée de `connect-src 'self'` explicite et de `report-uri /csp-rapport`
  + `report-to csp` (`Reporting-Endpoints`). Le rapport HTML (CSP fermée) envoie aussi ses violations.
- `POST /csp-rapport` : sans jeton CSRF (le navigateur n'en envoie pas), 20 rapports par minute et par adresse,
  8 Ko au plus (lus en flux), types `application/csp-report` et `application/reports+json` seulement. Journal :
  directive, origine de la ressource bloquée (`schéma://hôte`, jamais l'URL), chemin de la page sans requête ;
  ni adresse IP, ni extrait de script.
- `Permissions-Policy` : 18 fonctions refusées (caméra, micro, géolocalisation, paiement, USB, série, HID,
  capture d'écran, capteurs, `browsing-topics`…), noms reconnus par les navigateurs seulement (un nom inconnu
  produit un avertissement dans la console). COOP et CORP `same-origin` (déjà posés), aussi en secours dans Caddy.
- HSTS : même valeur dans l'application et dans Caddy (`max-age=63072000; includeSubDomains`, auparavant
  31536000 dans Caddy) ; `preload` laissé à la décision du fondateur (difficilement réversible).
- **Trusted Types imposés** : `require-trusted-types-for 'script'; trusted-types 'none'` — aucune politique, donc
  aucun puits HTML du DOM (`innerHTML`, `insertAdjacentHTML`, `document.write`, `DOMParser`…) dans les navigateurs
  qui les appliquent. Possible depuis que le filtrage en direct (D-3401) reçoit la page filtrée par
  `XMLHttpRequest` (`responseType = "document"`) au lieu de `DOMParser` ; essai réel du bloc interface sous cette
  CSP : 0 erreur dans la console (palette, zone de dépôt, suivi d'un dépôt, graphiques). Garde-fou permanent : le
  test refuse ces puits, `createPolicy` et toute création de `<script>` dans le JavaScript servi (Motion compris).
- Le limiteur des points JSON de suivi en direct (D-3402, 30 en rafale puis 1/s par compte) reste **en mémoire** :
  il ne protège que la charge du processus qui répond (aucun enjeu d'authentification), et le passer en base
  ajouterait une écriture par interrogation et par onglet ouvert.

### D-3205 — Entrées hostiles : corrections de la seconde revue

- **XML de déclaration à fiche déduite** (D-2401) : le test d'appartenance aux groupes reconstruisait un ensemble à
  chaque élément, d'où une déduction **quadratique** (4 000 articles, 0,5 Mo : 3,5 s ; 1 million de balises :
  ≈ 1 h 30 dans le worker). Ensembles construits une fois : 64 000 articles (8 Mo) en 9 s. Sorties identiques.
- **Images** : cadres d'un TIFF/GIF décodés un par un (au lieu de tous copiés avant de couper à 300) ; agrandissement
  des images basse résolution plafonné à 40 Mpx (une image de 80 Mpx à 72 dpi en demandait 720). Sans effet sur les
  pages ordinaires.
- **CSV de grille tarifaire** : un CSV dont le dialecte n'était pas reconnu modifiait `csv.excel` **pour tout le
  processus** (séparateur « ; » ensuite pour les exports CSV et la lecture des taux BCE) ; un champ démesuré donnait
  une erreur 500. Dialecte dérivé, erreur lisible.
- **Listes** (D-3401) : `?page=²` donnait une erreur 500 (`isdigit` accepte les exposants, `int` non).

### D-3401 — Listes : recherche, filtres, tri et pagination côté serveur

- **Où** : dossiers du client (`/espace/dossiers`), suivi des avoirs (`/espace/recouvrement`), file de validation
  (client, contrôle, niveau, fourchette de montant, ordre), dossiers de la fiche client, journal d'audit (acteur,
  action, client, période), tâches (statut, type, client).
- **Comment** : paramètres GET seulement (pages utilisables sans JavaScript, adresses à garder en favori). Module
  `web/listes.py` : noms de paramètres déclarés par liste (les autres sont ignorés et jamais réémis), valeurs
  **validées strictement** — listes fermées pour les choix, 80 caractères sans caractère de contrôle pour le texte,
  `montant_saisi` (Decimal) pour les montants, AAAA-MM-JJ pour les dates, `page` 1–10 000, `taille` 25/50/100,
  `tri` dans une liste fermée. Valeur invalide : page 400 lisible ; page au-delà de la dernière : dernière page.
- **Cloisonnement** : les listes fermées (transitaires, clients, contrôles) sont construites à partir des données
  déjà lues dans le périmètre de l'acteur ; l'identifiant d'un transitaire d'un autre client est donc refusé comme
  une valeur inconnue (400) sans aucune lecture. Dossiers, avoirs et file de validation sont filtrés en Python sur
  des lignes lues par `TenantScope` (volumes par client : centaines à quelques milliers). Journal et tâches
  (tables transverses du fondateur) : filtres passés à l'ORM en paramètres liés, `LIMIT/OFFSET`, compte en SQL
  (`OperatorScope.rechercher_journal`, `JobStore.rechercher`) ; la sous-chaîne « acteur » échappe `%` et `_`.
- **Index** : aucun ajouté. Le journal est parcouru par clé primaire décroissante, les tâches terminées sont purgées
  à 30 jours ; il n'existe pas de mécanisme de migration pour créer un index sur une base existante (backlog).
- **File de validation** : les extraits de preuve (rendus d'image) ne sont plus calculés que pour la page affichée
  (avant : 40 par client à chaque affichage).
- **Amélioration progressive** : saisie dans un champ de recherche ou changement d'une liste → la même adresse est
  demandée (GET, même origine) par `XMLHttpRequest` en `responseType = "document"` (document inerte, aucun script
  exécuté, aucune chaîne HTML passée à un puits : compatible avec Trusted Types `'none'`) ; seule la région
  `[data-resultats]` est remplacée, l'adresse est mise à jour (`history.replaceState`), le nombre de résultats est
  annoncé dans une région `aria-live`. En-têtes de colonnes triables avec `aria-sort`.

### D-3402 — Suivi en direct du traitement d'un dépôt

- **États** : reçu → lecture des documents → contrôles → terminé (ou erreur). Le worker écrit l'étape dans
  `jobs.resultat` (`{"etape": …}`, remplacé par le résultat final à la fin) par `JobContext.etape`, seulement s'il
  détient le bail (`JobStore.marquer_etape`, jeton de clôture). « Lecture » couvre le pipeline (extraction et
  calculs) ; « contrôles », l'enregistrement des résultats. Un découpage plus fin demanderait un rappel de
  progression dans le pipeline (backlog). Aucune colonne ajoutée (pas de migration).
- **Points JSON** (même origine, session, `Cache-Control: no-store`) : `/espace/lots/{id}/etat` (404 identique pour
  un lot d'un autre client et un lot inexistant), `/espace/suivi` (dépôts récents du client), `/admin/jobs/etat`
  (fondateur). Codes d'état, compteurs et libellés fixes seulement : aucune donnée de document. Limite de débit par
  compte (30 d'avance, 1 par seconde ; au-delà 429 + `Retry-After`).
- **Navigateur** : interrogation toutes les 2 s (page du dépôt) ou 4 s (listes), ralentie après 30 tours, en pause
  quand l'onglet est masqué, arrêtée à la fin ; rechargement automatique de la page à la fin pour afficher les
  dossiers. Mises à jour par `textContent` et classes ; animation Motion de l'étape courante (désactivée si
  « réduire les animations »). **Sans JavaScript** : `<meta http-equiv="refresh" content="5">` placé dans
  `<noscript>` (la CSP ne régit pas cette balise ; ignorée quand le script tourne) et lien « Rafraîchir ».
  Pas de SSE ni de WebSocket.

### D-3403 — Graphiques des tableaux de bord

- SVG produit par le serveur (`web/graphes.py` + `graphes.html.j2`), sans bibliothèque ni script : montant
  recouvrable certain par mois (12 derniers mois, mois de traitement du dossier), constats par famille de contrôles,
  montant certain par transitaire (client) ; à valider / validés par famille (fondateur, à partir de
  `OperatorScope.statistiques`, même lecture journalisée). Mêmes règles de totaux que le rapport (constats publiés,
  version courante, hors totaux exclus) ; montants en `Decimal`.
- Accessibilité : `role="img"` avec `<title>` et `<desc>` (résumé chiffré), tableau de données dans un
  `<details>` « Données du graphique », cadre défilant au clavier sur petit écran. Couleurs par classes CSS liées
  aux variables des deux thèmes (aucun attribut `style`), version imprimable. Barres des graphiques visibles au
  chargement animées (Motion), sauf « réduire les animations » ; les autres restent tels que rendus.

### D-3404 — Accessibilité : audit automatique et corrections

- Audit axe-core 4.10 (Playwright, Chromium, outil de développement non livré) sur 15 pages et la palette, thèmes
  sombre et clair, règles WCAG 2.0/2.1 A et AA + bonnes pratiques. Avant : contraste insuffisant du texte discret
  (4,2:1 en sombre, 3,6:1 en clair), bandeau « données fictives » hors repère, zone `pre` défilante non
  atteignable au clavier, options de la palette mal structurées. Après : **0 violation**, 0 erreur de console.
- Corrections : `--encre-3` #828896 (sombre, 5,7:1) et #5f6676 (clair, 5,4:1) ; bandeau en `<aside>` étiqueté ;
  `pre` défilants focalisables et étiquetés ; `li role="none"` dans la liste de la palette, option vide
  `aria-disabled` ; contraste de l'option sélectionnée ; contour de focus visible sur la zone de dépôt (le champ
  fichier transparent ne montrait rien) ; libellés masqués complétant les boutons répétés (« Relancer », « Avoir
  reçu », « J'ai envoyé mon courrier ») ; icône du site (`/static/favicon.svg`, supprime l'erreur 404 de console).

# Moteur (bloc A) : totaux imprimés par code de taxe ; bruit « à vérifier » (dev seulement, octobre 2026)

Constat : depuis D-2903, l'extracteur lisait les totaux par code (« Total A00 : … », « A00 Droits de douane 96,65 »)
pour recouper d'autres valeurs, mais le modèle ne les portait pas : B2 ne pouvait pas relever un total de code faux
(3 erreurs attendues « certain » du dev `corpus_g4`, 3 de `corpus_g2`, 2 du corpus d'origine). Ensuite, le bruit
« à vérifier » non apparié (1,39 à 1,46 par dossier sur le dev, 1,95 sur un jeu neuf) a été ventilé par contrôle et
par raison sur les seuls jeux de développement (`details` de `metrics.json`) : plusieurs familles ne correspondaient
presque jamais à une erreur réelle. Règles générales seulement : aucune ne lit un nom de gabarit, de fichier, de
client ou de transitaire.

## D-3101 — Modèle : `ChampsDeclaration.totaux_par_code`

- `TotalTaxeCode` (`type_taxe`, `montant`, `base_montant` facultatif), liste `totaux_par_code` : **jamais** une ligne
  de taxation (la famille C et B2 au total additionnent les lignes ; un total ajouté aux lignes serait compté deux
  fois).
- Extraction PDF (`extract/deterministe/declaration.py`) : les lectures de D-2903 (« Total A00 : … », récapitulatif
  « A00 Droits de douane 96,65 ») et deux formes nouvelles : « Total droits (A00) 1009,66 » (code entre parenthèses
  après un libellé court) et « A00 : 279,08   B00 : 2 295,68 » (code suivi de « : » et d'un seul montant à décimales,
  case de données comptables). Seuls les codes des lignes de taxation lues ; un code lu deux fois avec deux valeurs
  n'est pas retenu. Un total de code est confirmé (OCR) quand la somme des lignes du code le redonne, ou quand la
  somme des totaux par code redonne le total des droits et taxes ; un désaccord n'abaisse rien (le total du code
  peut être la valeur fausse).
- Exports : fiches `bench_x1_xml` (`TotalParType`), `bench_x2_csv` (`TOTAL`), `g2_m5_xml` (`recapitulatif/total`),
  version 1.1.0 ; fiche déduite (`ingest/structure_deduite.py`) : feuille hors des groupes reconnus, au nom de total
  (« total », « Summe », « recap »…), qui porte en attribut un code des taxations lues et un seul nombre.
- Réseau d'identités (D-1700) : Σ lignes du code = total du code (`dec:code:<code>`) ; Σ totaux par code = total
  des droits et taxes / total à payer (`dec:codes:<total>`).
- Mesure (`scripts/mesure_extraction.py`, champ comparé à `totaux_par_type` de la vérité) : valeurs ≥ 0,90 toutes
  justes (287 sur `corpus_g4`, 297 sur `corpus_g2`, 508 sur le corpus d'origine) ; une à deux valeurs fausses par
  jeu, toutes sous 0,90. Calibration des déclarations inchangée : ≥ 0,90 justes à 99,99 % (1 fausse sur 14 293),
  99,97 % (5 sur 16 499, les mêmes qu'avant), 100 % (23 436).

## D-3102 — B2 par code (`sous_controle="code"`), un seul constat par fait

- Σ des lignes d'un code contre le total imprimé du code ; `conforme` aussi si la somme des montants « à payer »
  concorde (TVA autoliquidée). Un code qui porte déjà une ligne de total sans article (D-301) n'est pas repris.
- Sous-contrôle nouveau, émis seulement quand la lecture peut trancher : s'il y a écart et qu'un motif de structure
  existe (articles non tous lus, ligne sans code lisible, code sans ligne pour un article quand l'écart est positif,
  doublon, ligne incohérente, total général retrouvé par Σ des totaux par code et non par Σ des lignes, total
  négatif), `non_verifiable` (`structure_non_validee`, motifs dans `details.structure`) au lieu d'un constat.
- Un seul constat par fait : quand B2 au total présente un écart et que les écarts des codes en constat,
  additionnés, le redonnent (une ligne mal lue ou mal imprimée fausse les deux), les constats par code deviennent
  `non_applicable` (`couvert_par_autre_controle`, `details.couvert_par = "B2 total"`).
- Certitude inchangée : D-1700 (les lignes sommées doivent être confirmées ; le total du code est la valeur mise en
  cause), D-2210, D-2711, D-2805 ; valeurs XML/CSV valides dispensées de corroboration (§6.3).

## D-3103 — B2 au total : complétude des lignes d'un code

Constat (dev `corpus_g4`, GZ0091) : avec D-3101, le total des droits et taxes d'un scan devenait confirmé par la
somme des totaux par code ; trois lignes A00 n'étaient pas lues et B2 au total serait devenu certain faux (20,37).
Règle (`structure_declaration.motifs_structure_taxes`, paramètre `ecart`) : écart positif (total imprimé > somme
lue) et un code sans ligne lue pour un article qui a d'autres lignes -> motif de structure, **sauf** si le total
imprimé de ce code est retrouvé par la somme de ses lignes lues (elles sont alors complètes). Réciproquement (B2 par
code), quand la somme de **toutes** les lignes lues redonne le total des droits et taxes, une ligne non lue vaut zéro
et n'explique aucun écart de code (GX0246, vrai écart relevé « à vérifier »).

## D-3104 — C7 : MRN cité proche de celui d'une déclaration du dossier

Hors « 26FR » (année, pays), un MRN porte 11 caractères aléatoires parmi 36 ; deux MRN distincts n'en partagent pas
sept par hasard (probabilité de l'ordre de 1e-8). Un MRN cité dont le préfixe de 15 caractères commence de même et ne
diffère de celui d'une déclaration **de ce dossier** (ou d'un dossier qui partage la facture) que de 4 caractères au
plus (substitutions, caractère perdu ou ajouté : `famille_c.mrn_designe`) la désigne : il n'est pas « sans
correspondance ». Mesure (dev, trois jeux) : parmi les 19 C7 appariés à une erreur réelle, ceux qui citent un MRN le
citent à 9 caractères ou plus des MRN du dossier ; les C7 non appariés, à 1 à 4 caractères pour la plupart. Les MRN d'autres dossiers du client restent signalés (pièges
« facture d'un autre envoi rangée ici »). C7 non apparié 52 -> 22.

## D-3105 — Document rattaché à plusieurs dossiers : contrôles E1 à E5, F1, F2, F4 portés une fois

Un relevé ou un avoir rattaché à plusieurs dossiers d'un même lot donnait le même constat dans chacun (même
libellé : E5 jusqu'à 4 fois). Dans l'esprit de D-701 : un avoir partagé est évalué par E1 à E5 dans le premier
dossier (identifiant) dont une déclaration a un MRN cité par l'avoir, à défaut dans le premier de tous
(`famille_e.dossier_evaluation_avoir`) ; F1, F2 et F4 sur un document partagé, dans le premier dossier qui le
contient. Les autres dossiers : `non_applicable` (`couvert_par_autre_controle`, `details.dossier`). E6 (avoir
partiel, par écart du dossier) inchangé. Constats en double (même contrôle, même libellé, même lot) sur le dev des
trois jeux : E 66 et F 20 -> 0 ; restent P1 (19) et P4 (5), signaux de dossier non touchés.

## D-3106 — A10 masse nette : couverte par B4 quand la déclaration se contredit

Une masse nette d'article supérieure à sa masse brute (B4 `nette_brute`) fausse la masse nette déclarée : A10
`nette` donne `non_applicable` (`couvert_par_autre_controle`) au lieu d'un second constat du même fait. Les
générateurs n'injectent aucune erreur A10 sur la masse nette ; 7 des 21 A10 `nette` non appariés venaient de ce cas.

## D-3107 — B4 `somme_brute` : masse lue sous le seuil

Signal interne à un seul document, sans montant, sans aucune autre identité imprimée sur les masses : quand une des
masses comparées n'est lue que sous `C_MIN_CERTAIN`, la lecture ne peut pas trancher -> `non_verifiable`
(`confiance_insuffisante`, motif `masses_lues_sous_le_seuil`). Les 14 B4 `somme_brute` non appariés du dev étaient
tous dans ce cas (masses lues « 184 295 » pour 184,295…), aucun n'était une erreur réelle.

## D-3108 — Mesures (dev seulement)

Bancs `*_dev_blocA_base` (code du dépôt, identique à `*_dev_c3fin`) -> `*_dev_blocA` :

| dev | VP / FP certains | rappel | rappel certain | bruit / dossier | violations de pièges | sous-classements | montants justes |
|---|---|---|---|---|---|---|---|
| `corpus_g4` | 98 / 0 -> 103 / 0 | 0,821 -> 0,831 | 0,692 -> 0,733 | 1,457 -> 1,143 | 50 -> 46 | 24 -> 22 | 0,957 -> 0,958 |
| `corpus_g2` | 113 / 0 -> 115 / 0 | 0,860 -> 0,870 | 0,763 -> 0,777 | 1,392 -> 1,194 | 35 -> 29 | 25 -> 26 | 0,965 -> 0,966 |
| corpus d'origine | 120 / 0 -> 125 / 0 | 0,827 -> 0,832 | 0,785 -> 0,813 | 1,154 -> 0,951 | 28 -> 28 | 18 -> 16 | 0,953 -> 0,953 |

Seuils bloquants : PASSE sur les trois. Aucune erreur détectée avant ne l'est plus. Gagnées : les 8 erreurs B2
« total de code faux » (7 certaines, GX0246 scanné « à vérifier »), et 6 C5/C6 devenus certains à montant juste (le
total liquidé confirmé par la somme des totaux par code). Bruit non apparié par contrôle (trois jeux) : E5 67 -> 24,
C7 52 -> 22, E1 19 -> 4, B4 17 -> 3, A10 28 -> 19, F1 15 -> 7, F2 9 -> 3, F4 9 -> 3, E2 15 -> 9, E3/E4 7 -> 0 ;
B1 29 -> 31 (deux lectures de base tronquées sur scan, montant désormais confirmé par le total de son code : la
confusion de lecture ne s'applique plus au montant, D-2303). Total 811 -> 669. Tests : `tests/controls/test_famille_b.py`,
`test_famille_a.py`, `test_famille_c.py`, `test_famille_e.py`, `test_famille_f.py`, `test_corroboration.py`,
`tests/extract/test_totaux_categories_d29.py`, `tests/ingest/test_ingest_structure_exports_attributs.py`,
`tests/test_model.py` (données fictives).

## D-3901 — Vérifications avant enregistrement, locales et hors ligne

`.pre-commit-config.yaml` ne déclare que des crochets `repo: local` (`scripts/precommit/lancer.sh` puis
`scripts/precommit/verifs.py`, bibliothèque standard + PyYAML) : rien n'est téléchargé, le résultat ne dépend pas
d'un dépôt tiers. Vérifiés : `ruff check` (src, tests, scripts), espaces en fin de ligne (Markdown : deux espaces
de saut de ligne admis), fichiers > 2 Mo (corpus `bench/corpus*/` exclus ; la vidéo de démonstration déjà
versionnée est admise nommément), clés privées et jetons d'API reconnaissables (Anthropic, Stripe réel, webhook
Stripe, AWS, GitHub, Slack ; ligne marquée `pragma: allowlist secret` ignorée), syntaxe JSON/YAML, pas de `print(`
dans les paquets cœur (les commandes gardent les leurs). Pas de `ruff format --check` : le code n'est pas formaté
par ruff (301 fichiers sur 363). Le crochet git n'est jamais installé automatiquement : `make hooks`.
`make pre-commit` et la CI vérifient tout le dépôt. Outils de développement seulement : pre-commit (MIT).

## D-3902 — Couverture mesurée, sans seuil bloquant pour l'instant

coverage.py (Apache-2.0) via pytest-cov (MIT), branches comprises, configuration dans `pyproject.toml`
(`[tool.coverage.*]`, données et HTML sous `var/couverture/`). `make couverture` ajoute un résumé **par paquet** et
la liste des modules critiques les moins couverts (`scripts/couverture_paquets.py`, `var/couverture/paquets.md`).
Base de référence et lecture : `docs/QUALITE.md`. Seuil (`COUV_MIN`) laissé à 0 tant que les blocs sécurité et
stockage modifient `web/securite.py`, `storage/securite.py` et `storage/scope.py`.

## D-3903 — Tests de propriétés (Hypothesis)

Hypothesis (MPL-2.0 : copyleft faible au niveau du fichier, outil de test jamais distribué ni installé dans
l'image) dans les extras `dev`. `tests/proprietes/` (marqueur `proprietes`) : lecture et formatage des montants
(groupements français, anglais, allemand, suisse, indien ; signes, parenthèses, devises), saisie, tolérances
(symétrie, monotonie, seuil ≥ tolérance, `Decimal` partout), TVA FR / SIREN, MRN (préfixe stable, bruit de
lecture) et clés de confusion OCR, dates multilingues et ambiguïté jour/mois, redirection interne, paramètres de
liste et pagination. Profils `dev` (100 exemples), `ci` (150, déterministe, sans base d'exemples) et `intensif`
(2 000) par `HYPOTHESIS_PROFILE` / `make proprietes PROFIL=…`. Aucun défaut trouvé, y compris en `intensif`.

## D-3904 — Corpus de banc non versionnés : régénération et empreinte

À partir de `corpus_g6`, les corpus ne sont plus versionnés : `.gitignore` ignore `bench/corpus_*/` et ré-inclut
`corpus_g3`, `corpus_g4`, `corpus_g5` (déjà suivis, rien n'est désindexé). Recette et empreinte de chaque corpus dans
`bench/corpus_empreintes.json` ; `make corpus-g6` (régénération sautée si le corpus présent est conforme,
`FORCE=1` pour refaire), `make corpus-verifier`, `make corpus GRAINE=… PREFIXE=…` (`scripts/corpus.py`). Empreinte
exacte = celle consignée dans `docs/backlog/orchestrateur.md` (test de cohérence). Constat en la vérifiant : les TIFF
LZW écrits par Pillow ne sont pas déterministes à l'octet (un octet de remplissage) ; une régénération de
`corpus_g6` a donc des pixels identiques mais une empreinte exacte différente. Empreinte de secours `sha256_pixels`
(TIFF comparés par leurs pixels décodés), acceptée et signalée comme telle. Documentation : `bench/README.md`.

# Fiabilité de la production : PostgreSQL, alertes poussées, migrations, verrou (bloc P, octobre 2026)

Tests : `tests/platform/test_sauvegarde_postgresql.py`, `test_migrations.py`, `test_verrou_maintenance.py`,
`tests/ops/test_notifications.py` ; exercices `make restauration-test` et `make restauration-test-pg`.

## D-3501 — Sauvegarde et restauration PostgreSQL dans l'archive `CDSAV2`

- **Constat** : `sauvegarder` refusait une base non SQLite (code 2) ; un passage à PostgreSQL laissait la
  production sans sauvegarde, sans vérification ni exercice.
- **Choix** : `sauvegarder_postgresql` écrit `base/controldone.dump` (`pg_dump --format=custom --no-owner
  --no-privileges`) dans la **même** archive chiffrée `CDSAV2`, avec le coffre, les traces d'envoi et le manifeste.
  Cohérence : une transaction `REPEATABLE READ` en lecture seule exporte son instantané (`pg_export_snapshot`),
  compte les lignes et lit la tête de l'audit, et reste ouverte pendant `pg_dump --snapshot=…` : manifeste et dump
  voient exactement les mêmes données. Paramètres de connexion par l'environnement (`PGPASSWORD`…), jamais en
  argument. `verifier` contrôle l'en-tête `PGDMP` ; `restaurer` relit le dump (`pg_restore --list`) ;
  `restaurer --base-cible <url>` le charge par `pg_restore --single-transaction --exit-on-error` dans une base
  **vide** (refus sinon) ; `controler --base-url` compare lignes, audit et références du coffre comme pour SQLite.
  Vérification profonde : base jetable sur `BACKUP_PG_VERIFICATION_URL`, supprimée ensuite ; sans ce réglage, dump
  relu seulement (remarque, pas d'échec). Exercice : `controldone sauvegarde exercice --postgres <serveur jetable>`
  (`make restauration-test-pg`, grappe `initdb` dans `/tmp` par `scripts/pg_jetable.sh`, jamais un service).
- **Pilote** : `pg8000` (BSD-3-Clause, pur Python ; extra `postgres` de `pyproject.toml`). psycopg écarté
  (LGPL-3.0 : licences permissives seulement). L'application tourne sur PostgreSQL 16 avec pg8000 (init-demo,
  web, worker, exercice complet conforme), à condition que la base soit en UTF-8.
- **Mesure** (poste de développement, base de démonstration) : exercice PostgreSQL complet 24 s, dont
  restauration + contrôle + démarrage du web 4,9 s.
- **Écarté** : sauvegarde physique (`pg_basebackup`) — liée à la version et à l'architecture, ne restaure pas
  dans une base vide d'un autre serveur ; dump SQL en clair (`--format=plain`) — pas de `pg_restore --list`, et
  restauration non transactionnelle.

## D-3502 — Alertes poussées : webhook et courriel, désactivés par défaut

- **Constat** : les alertes n'étaient visibles qu'en se connectant à `/admin` ; une sauvegarde en panne pouvait
  passer inaperçue plusieurs jours.
- **Choix** : `services/notifications.py`, deux canaux : webhook (POST JSON en HTTPS, sans redirection,
  compatible Slack/Mattermost `text`, Healthchecks `/fail`, ntfy en format `texte`) et courriel (SMTP, STARTTLS
  ou TLS, destinataires fixes). Règles : aucun canal sans configuration explicite (`CONTROLDONE_NOTIF_*`) ;
  aucun envoi hors `CONTROLDONE_ENV=prod`, même configuré ; contenu limité au type, à un libellé fixe, au nombre,
  à l'heure et au chemin `/admin/alertes` ; une notification par type et par jour (`notifications_alertes`),
  les suivantes regroupées ; alertes de plus de 24 h ou déjà lues jamais envoyées (activer ne déverse pas
  l'historique) ; 5 essais par jour au plus ; un canal en panne n'empêche pas l'autre. Envoi **hors**
  transaction, puis inscription. Lancé par le planificateur (toutes les 5 min et après la sauvegarde).
- **Pourquoi pas la file sortante** (D-459) : elle sert aux envois approuvés un à un par le fondateur ; une
  alerte doit partir sans attendre, vers une destination fixée par l'exploitant, et ne contient aucune donnée
  client. La file sortante reste sans code d'envoi réel (test inchangé).
- **Limite** : rien ne part si le conteneur `scheduler` est arrêté ; `BACKUP_PING_URL` reste nécessaire.

## D-3503 — Migrations de schéma versionnées, sans Alembic

- **Constat** : `create_all` ne crée ni colonne ni index sur une table existante ; aucun moyen de faire évoluer une
  base en service (index demandés par l'interface, nouvelles colonnes).
- **Choix** : `storage/migrations.py` : table `schema_version`, étapes Python ordonnées et **idempotentes**
  (`CREATE INDEX IF NOT EXISTS`, colonne ajoutée seulement si absente, nullable), une transaction par étape avec
  son inscription, verrou consultatif sous PostgreSQL. Base neuve : `create_all` puis toutes les étapes inscrites
  (chaque évolution est aussi déclarée dans les modèles, testé). Base existante, même antérieure au mécanisme :
  étapes en attente exécutées. `controldone migrer` sauvegarde d'abord (abandon si la sauvegarde échoue) ;
  `serve` / worker migrent seuls en `dev` / `test`, refusent de démarrer en production (code 3) sauf
  `CONTROLDONE_MIGRATION_AUTO=1`. `serve --init-schema` ne crée plus que les tables d'une base neuve.
- **Étapes** : 1 `socle` (tables manquantes : débit, révocations et sessions actives D-3201/D-3202,
  facturation, notifications) ; 2 `index_journal_taches` (`audit_log` : action+id, actor+id, ts ; `jobs` :
  statut+cree_le, kind+statut+run_after, cree_le) ; 3 `alertes_notifiees` (`alertes.notifiee_le` ; alertes
  existantes marquées traitées ; table `notifications_alertes`). Testé sur SQLite et PostgreSQL 16.
- **Alembic écarté** : installé dans `.venv` mais ni figé ni importé ; il ajouterait Mako et une seconde
  description du schéma, son autogénération ne sert pas pour des ajouts de colonnes et d'index, et les `ALTER`
  de SQLite demandent de toute façon des étapes écrites à la main. À reconsidérer si des transformations lourdes
  (renommage, changement de type) deviennent nécessaires.
- **Limite** : l'index `actor` ne sert pas la recherche par sous-chaîne du journal (`LIKE '%…%'`) ; il sert les
  préfixes et l'égalité.

## D-3504 — Verrou de maintenance : sauvegarde, purge, restauration

- **Constat** : une purge mise en file à la main pendant une sauvegarde pouvait retirer un objet que l'instantané
  référence (D-3306 ne couvrait que le cas planifié).
- **Choix** : `storage/verrou.py`, `flock` exclusif sur `<data_dir>/.verrou-maintenance` (libéré avec le
  processus, partagé par les conteneurs du même hôte qui montent `/app/var`). La création d'archive le prend
  (attente `BACKUP_VERROU_ATTENTE_S`, 30 min, puis échec + alerte) ; `purger_expires` le prend sans attendre
  (`VerrouOccupe` -> le job `purger_retention` est reporté de 10 min sans consommer d'essai) ; la restauration
  aussi (attente 60 s, code 2). La vérification de l'archive se fait hors verrou. Le fichier du verrou est le
  seul admis dans une cible de restauration « vide ».
- **Limite** : plusieurs hôtes (PostgreSQL partagé, volumes distincts) ne sont pas couverts : verrou consultatif
  PostgreSQL à ajouter le jour venu (`docs/backlog/production.md`).

## D-3505 — Libellés des alertes de sauvegarde

`admin/alertes.html.j2` traduit `sauvegarde_echec`, `sauvegarde_verification_echec`, `sauvegarde_absente`,
`sauvegarde_hors_site_echec` ; mêmes libellés fixes dans les notifications. Le bandeau sur `/admin` reste à faire
(bloc interface).

# Sécurité : suivi des revues (bloc S, octobre 2026)

Points ouverts de la première revue (RS-16, RS-18 à RS-21) et du backlog `docs/backlog/securite.md`. Tests :
`tests/security/test_suivi_securite.py` (22 tests) et `tests/security/test_postgresql_securite.py` (6 tests,
marqueur `postgresql`).

## D-3601 — Mode `dev` oublié en production : `serve` refuse de démarrer (RS-16)

- **Constat** : `CONTROLDONE_ENV` absent vaut `dev` (clé maîtresse générée sur le disque, cookies sans `Secure`
  ni `__Host-`, pas de HSTS). L'image Docker fixe `prod`, mais une installation à la main pouvait l'oublier.
- **Choix** : le défaut `dev` reste (démonstration, tests, développement en une commande), mais
  `controldone serve` refuse de démarrer (code 2, avant de créer quoi que ce soit) en `dev`/`test` quand la
  configuration est celle d'une production : écoute hors boucle locale (`--host 0.0.0.0`, adresse publique),
  `--https` ou `--proxy`. `CONTROLDONE_DEV_RESEAU=1` lève le refus (démonstration volontaire sur un réseau de
  confiance), avec un avertissement journalisé. `web.securite.verifier_mode_service`.
- **Écarté** : défaut `prod` (casserait `make serve-demo`, les tests et tout essai local sans clés : l'échec
  « fermé » se paierait en confusion pour tous les usages légitimes).

## D-3602 — URL publique configurée et en-tête `Host` filtré (RS-18)

- Liens de paiement et d'abonnement Stripe construits avec `web.securite.url_publique` :
  `CONTROLDONE_URL_PUBLIQUE` (`https://hôte[:port]`, sans chemin ni identifiants), sinon
  `https://CONTROLDONE_DOMAIN` ; **jamais** l'en-tête `Host` en production (erreur lisible si rien n'est
  configuré) ; en développement seulement, l'URL de la requête à défaut de configuration.
- Domaine configuré : `TrustedHostMiddleware` (400 pour un `Host` étranger), hôtes admis = domaine, hôte de
  l'URL publique, `CONTROLDONE_HOTES_AUTORISES` (liste), boucle locale (sonde de santé de l'image). Vérifié dans
  l'image construite (`Host: piege.test` → 400, domaine → 200, sonde « healthy »).

## D-3603 — Sessions actives : table `sessions_actives` et API pour l'interface

- Table de plateforme `sessions_actives` (`storage/securite.py`, `SessionOuverte`) : une ligne par connexion
  réussie (`sid`, `user_id`, début, dernière émission du jeton, expiration, appareil, réseau), mise à jour à
  chaque rotation (au plus toutes les 15 min : pas d'écriture par requête), supprimée à la déconnexion, à la
  révocation, au changement de mot de passe, purgée à l'expiration (`purger_revocations`). Créée par
  `assurer_tables_securite` au démarrage du web et par l'étape **4** des migrations (`sessions_actives`, D-3503 ;
  l'étape 1 la crée aussi sur une base qui ne l'a pas encore passée) ; table nouvelle, aucune colonne ajoutée.
- **Minimisation** : appareil réduit à « navigateur · système » par listes fermées (`reduire_appareil`, jamais
  le `User-Agent`), réseau tronqué (`/24` IPv4, `/48` IPv6, `reduire_reseau`).
- API (`auth.jetons.GestionnaireSessions`) : `sessions_actives(user_id, sid_courant=…)` (liste de
  `storage.securite.SessionActive` : `sid`, `debut`, `vu`, `appareil`, `reseau`, `courante` ; la plus récemment
  active d'abord ; révoquées, inactives et expirées exclues), `fermer_session(user_id, sid)` (`False` si ce n'est
  pas une session ouverte **de ce compte**), `fermer_autres_sessions(user_id, sid_courant)` (nombre fermé). Les
  connexions passent par `EtatSecurite.ouvrir_session(request, reponse, acteur, deux_facteurs=…)`, qui
  enregistre la session. Sans registre (tests unitaires) : liste vide. Mode d'emploi pour l'interface :
  `docs/backlog/securite.md`.

## D-3604 — Cookies secondaires `__Host-` ; copie locale des révocations bornée

- `cd_2fa` (étape du second facteur) et `cd_flash` (messages) deviennent `__Host-cd_2fa` et `__Host-cd_flash`
  en production (comme `__Host-cd_session` et `__Host-cd_pre`) : `Secure`, `Path=/`, sans `Domain`. Effacement
  par un `Set-Cookie` `Secure` (sinon refusé par le navigateur pour un nom `__Host-`). Accès par
  `EtatSecurite.nom_2fa`, `nom_flash`, `poser_2fa`, `lire_2fa_requete`, `effacer_2fa`, `effacer_flash`.
- `GestionnaireSessions` : copie locale des révocations (`sid`, coupures par utilisateur) bornée à 10 000
  entrées chacune (`MAX_REVOCATIONS_LOCALES`) : les entrées expirées partent d'abord, puis les plus anciennes ;
  le registre en base fait foi (une révocation sortie de la copie reste refusée).

## D-3605 — Base vivante sur un volume chiffré : constat au démarrage (RS-21)

- `storage.securite.chiffrement_volume(chemin)` : `chiffre` si le fichier de la base est sur un volume dm-crypt
  (LUKS) ou sur un volume logique construit au-dessus (lecture de `/sys/dev/block/MAJ:MIN`, `dm/uuid` `CRYPT-…`,
  esclaves), `non_chiffre`, ou `inconnu` (superposition sans périphérique, réseau, autre système).
- Au démarrage de `serve` en production (SQLite) : `non_chiffre` → avertissement et alerte `volume_non_chiffre`
  (une par mois) ; `inconnu` → information journalisée ; `CONTROLDONE_VOLUME_CHIFFRE=1` déclare un chiffrement
  invisible d'ici (disque chiffré par l'hébergeur). PostgreSQL : à la charge de l'hôte de la base.
- **Écarté** : chiffrer la base SQLite elle-même (SQLCipher : dépendance native, licence et sauvegardes à
  revoir) ; refuser de démarrer (un volume non détectable n'est pas un volume en clair).

## D-3606 — Rendu OCR des PDF : plafond de pixels

- `ingest.pages.echelle_rendu_ocr` : `dpi / 72` (300 dpi), abaissée seulement si la page dépasserait
  `MAX_PIXELS_RENDU_OCR` = 40 Mpx (même borne que l'agrandissement des images, REV2-03). A4, A3, légal US et A2
  à 300 dpi restent sous le plafond : **sortie inchangée pour les pages ordinaires, `VERSION_PAGES` inchangée**.
  Au-delà (page de plusieurs mètres), avertissement `rendu_ocr_reduit` sur la page.

## D-3607 — Vignettes rendues dans le processus isolé (RS-20)

- `services.vignettes` ne rend plus dans le processus web : `ingest.pages.executer_isole("rendu_page", …)`
  (même forkserver que l'extraction : environnement sans secrets, `RLIMIT_AS` 1,5 Go, délai 30 s, arrêt forcé),
  liste fermée de cibles (`CIBLES_ISOLEES`). Un plantage ou un dépassement donne « pas d'image » (journalisé).
  Coût mesuré : ≈ 50 ms par rendu (même ordre que le rendu local), le cache des PNG est inchangé.
- **Écarté** : rendre les vignettes à l'ingestion et les stocker chiffrées (stockage, purge et effacement à
  revoir pour un gain de quelques dizaines de millisecondes).

## D-3608 — Caddy : tailles de corps alignées sur l'application

- `/csp-rapport` : 16 Kio (l'application en lit 8 Kio) ; dépôts : 520 Mio (application : 500 Mio + 16 Mio
  d'enveloppe) ; tout le reste : 4 Mio (l'application refuse au-delà de 2 Mio ; auparavant 60 Mo). Unités binaires
  comme l'application. Matchers disjoints ; configuration validée par `caddy validate` 2.10.

## D-3609 — Dépendances figées avec empreintes ; audit de l'image

- `requirements.lock` porte les empreintes SHA-256 de toutes les distributions (`make lock` : `uv pip compile
  --generate-hashes`, Linux, Python 3.11, versions inchangées) ; le Dockerfile installe par `pip
  --require-hashes`, et le backend de construction (hatchling, editables) vient de `deploy/requirements-build.lock`
  (empreintes aussi) dans un environnement de l'étape « build » seulement (`--no-build-isolation`) : plus aucun
  téléchargement non vérifié. `make install` (uv) vérifie les empreintes présentes.
- Image : pip, setuptools et wheel retirés (venv et interpréteur de base) — inutiles à l'exécution et porteurs
  de copies vendues de `wheel` / `jaraco.context` signalées HIGH corrigeables.
- `make audit-image` (ou `make audit IMAGE=…`) : Trivy (binaire, sinon image `aquasec/trivy:0.75.0` par Docker ;
  `AUDIT_CA_BUNDLE` pour un mandataire à autorité privée) sur l'image construite, paquets du système et Python.
  Bloque sur une vulnérabilité HIGH/CRITICAL **corrigeable** ; les autres sont listées (`var/audit/image.md`).
  Résultat du 6 octobre 2026 (Debian 13.7) : 0 grave corrigeable ; 77 graves sans correctif publié
  (CRITICAL 1 : libxml2 ; HIGH : util-linux, curl, expat, libtiff, libtesseract…), à suivre.
- Paquets hors du fichier figé : `alembic` et `mako` retirés de `.venv` (Alembic écarté, D-3503). L'extra
  `postgres` (D-3501) est **figé** dans `requirements.lock` avec ses dépendances (`pg8000`, `python-dateutil`, `six`,
  `scramp`, `asn1crypto` : 73 paquets) : `make install` et l'image l'ont, `make audit` le couvre (0 vulnérabilité,
  licences permissives).

## D-3610 — Débit, révocations et sessions testés sous PostgreSQL

- `make test-pg-securite` : serveur jetable (`scripts/pg_jetable.sh`, PostgreSQL 16, 127.0.0.1:55441), base neuve
  par test, tests marqués `postgresql` (sautés sans `CONTROLDONE_TEST_PG_URL`), serveur arrêté et effacé
  ensuite. Couvre le `SELECT … FOR UPDATE`, les conflits de première insertion rejoués (six connexions sur une clé
  absente : exactement 20 jetons sur 60 demandes ; cinq révocations simultanées du même utilisateur : une ligne,
  coupure la plus tardive), la table bornée, les révocations et les sessions actives entre deux « processus ».
  6 tests verts le 6 octobre 2026. À ajouter à la CI (déclenchement manuel) avec le paquet `postgresql`.

# Moteur (lot 2) : bruit « à vérifier » sur jeux neufs, progression du pipeline (dev seulement, octobre 2026)

Constat : sur les jeux jamais vus, le bruit « à vérifier » non apparié restait à 1,8–1,9 constat par dossier (alerte :
1,5), pour 0,95–1,19 sur les jeux de développement. Il a été ventilé sur les seuls jeux de développement par un outil
nouveau, puis réduit famille par famille. Règles générales seulement : aucune ne lit un nom de gabarit, de fichier
(hors un MRN imprimé dans le nom du fichier d'une déclaration, comme référence à recouper), de client ou de
transitaire.

## D-3701 — Outil d'analyse du bruit : `scripts/analyse_bruit.py`

Joint `metrics.json` (classes de `bench.score`), `findings.json` (raisons, sous-contrôle, documents concernés) et la
vérité du split `dev` (type, format, mise en page, gabarit, dégradation des documents ; pièges). Ventile le bruit
(`fp_a_verifier`, non apparié ou piège déclenché) par contrôle × sous-contrôle, contrôle × raison, type / format /
dégradation des documents concernés, mise en page de la déclaration, gabarit du transitaire ; liste les pièges
déclenchés par description et les constats en double dans un même lot ; `--avant` compare deux bancs (compteurs,
différence par contrôle, nouveaux constats). Refuse tout autre split que `dev` (les jeux tenus à l'écart ne sont lus
qu'en totaux, par `bench.score`). `--controle`, `--exemples`, `--json`. Tests : `tests/bench/test_analyse_bruit.py`.

## D-3702 — Regroupement : lien faible renforcé par une référence retrouvée dans le dossier (P4)

Constat (dev, trois jeux) : 62 P4 « rattachement faible » non appariés, aucune erreur réelle ; le signal « même
dossier source » seul ou un MRN cité (avoir, poids « moyenne ») suffisait à « faible ». Le contrôle sert sur les
factures d'un autre envoi rangées dans le dossier (8 pièges tolérés sur g4/g2, 8 factures `ft9` du corpus d'origine).

Règle (`regroupement._corroborer_faibles`, après `_corroborer`) : un membre au lien faible (score ≤ 2, ni graine ni
doublon) dont une référence se retrouve sur un membre **solidement** rattaché au même dossier (graine ou score ≥ 3)
passe à « moyenne » avec le signal nouveau `reference_proche` (« référence retrouvée dans le dossier ») :
- MRN : `normalize.refs.mrn_proches` — préfixes de 15 caractères, clés de confusion OCR, même année, au plus 4
  caractères d'écart (comme D-3104 ; onze caractères aléatoires) ; MRN de la déclaration, à défaut celui imprimé dans
  le nom de son fichier ; MRN cités par une facture du transitaire ou un avoir ;
- titre de transport : `ref_transport_proches` — compatibles, ou clés de confusion d'au moins 10 caractères à au plus
  `max(1, n // 4)` caractères d'écart ; entre deux déclarations, égalité ou inclusion seulement (leurs références
  mêlent numéros de facture et titres : deux factures successives ne doivent pas se confirmer) ;
- numéro de facture : porté par l'un, cité par l'autre (égaux) ;
- document lu **sans aucune** référence, dans le **même fichier** qu'un membre solide (page illisible d'un PDF
  « envoi complet ») : rien ne le contredit.
Répété tant qu'un lien change. Jamais « forte » (plafond explicite, même avec `mrn_cite`) : la condition 5 de
§8.5.1 (lien solide pour un écart certain) est inchangée, seul P4 distingue « faible » de « moyenne ». Un document qui
ne porte que des références étrangères au dossier reste faible.

Mesure (préparations de 56 dossiers du dev à P4, liens comparés à `expected_links` de la vérité) : 41 liens
renforcés, tous de documents du dossier ; aucun document étranger renforcé ; les 16 documents étrangers (8 `ftx`
piégés de g4/g2, 8 `ft9` du corpus d'origine) restent faibles et signalés. Banc : voir D-3707.
Test modifié : `test_facture_repartie_sur_deux_declarations_par_repli_reste_possible` (MRN1 et MRN2 des
fixtures ne diffèrent que d'un caractère : deux lectures d'un même MRN au sens de cette règle ; MRN réaliste).

## D-3703 — D1 total HT / total des débours : lignes possiblement non lues

Comme D-2307 pour B2/B3 : `total_ht` ou `total_debours` imprimé **supérieur** à la somme des lignes lues, classement
`a_verifier` pour cause de lecture (`confiance_insuffisante` ou `lecture_non_corroboree`) : des lignes non lues
expliquent l'écart dans ce sens et aucune identité ne prouve que la lecture est complète (elle aurait rendu le
classement certain) -> `non_verifiable` (`confiance_insuffisante`, motif `lignes_possiblement_non_lues`). Écart de
sens contraire, ou classement certain : inchangés. Coût : BX0168 (corpus d'origine), apparié jusqu'ici à un montant
faux (9 053,88 EUR pour 53,88 attendus : l'écart venait surtout des lignes non lues), n'est plus relevé.

## D-3704 — C1 à C5 : relevé réparti au prorata, un constat par facture

Une facture du transitaire répartie entre plusieurs dossiers du lot (relevé au prorata) était comparée, dans chaque
dossier, à la seule déclaration de ce dossier : le même montant refacturé donnait un constat par déclaration (GZ0030
×3, GX0120 ×5). Quand le classement est `a_verifier` avec `attribution_non_univoque` ou `allocation_prorata`
**et** que la comparaison porte sur une ligne qu'aucun MRN ni aucune allocation ne désigne (`LigneDebours.partagee` :
ligne non ventilée, MRN illisible ou sans correspondance), le constat n'est porté que par le premier dossier
(identifiant) qui contient la facture ; ailleurs `non_applicable` (`couvert_par_autre_controle`, `details.dossier`,
motif `facture_repartie_evaluee_dans_un_autre_dossier`), dans l'esprit de D-3105. Une ligne ventilée par MRN est un
fait propre à chaque dossier : jamais concernée (une première version sans cette condition faisait perdre le vrai
C2 de GZ0145, ventilé par MRN). Un écart certain n'est jamais concerné.

## D-3705 — B1 : base lue tronquée sur un scan

« 30,65 » lu pour 30 651,38 (GZ0154), « 1.224 » pour 122 481 (GX0054) : les décimales perdues empêchent la variante
« séparateur » (× 1 000) du test de confusion de redonner le montant à la tolérance près ; le montant, confirmé par
le total de son code (D-3101), n'était plus sujet à confusion. Règle (`famille_b._base_tronquee`) : base lue sous
`C_MIN_CERTAIN`, et une puissance de dix `k` (1 à 6) telle que `(base − u) × 10^k × taux ≤ montant ≤ (base + u) ×
10^k × taux` (à la tolérance de ligne près), `u` étant l'unité du dernier chiffre lu -> `non_verifiable`
(`confiance_insuffisante`, motif `base_lue_tronquee`, `details.puissance_de_dix`). Les erreurs B1 injectées
(`taxe_base_taux_incoherente`) ne sont pas des facteurs de dix.

## D-3706 — Totaux par code : récapitulatif sans ligne lue ; total de catégorie sans code

Constat (`scripts/mesure_extraction.py`, corpus d'origine) : sur L1/L3 dégradés (d2), ce ne sont pas les totaux par
code qui manquent mais les lignes de taxation (tableau illisible) ; les totaux lus étaient écartés faute de ligne du
même code. L2 imprime « Total autres taxes 1332,32 » sans code.
- Un code sans ligne de taxation lue est retenu quand **tous** les totaux par code lus (au moins deux) redonnent,
  additionnés, le total des droits et taxes ou le total à payer imprimé (0,01 EUR par code) : l'identité confirme
  chacun.
- « Total droits / autres taxes / TVA <montant> » sans code est rattaché au **seul** code des lignes lues de cette
  catégorie, quand ce code n'a pas de total lu et que la catégorie n'a qu'un tel total ; confiance plafonnée (pénalité
  0,15 : jamais ≥ 0,90, le rattachement est déduit). « Total des droits et taxes » n'est pas une catégorie.
Mesure (totaux par code, dev) : corpus d'origine 577 justes / 205 absents / 1 faux -> 649 / 133 / 1 ; g4 -> 335 /
34 / 1 (58 absents avant, D-3101) ; g2 -> 419 / 46 / 2 (82 absents avant). Calibration des déclarations : ≥ 0,90
justes à 100 % (23 499 sur le corpus d'origine), 99,99 % (1 fausse sur 14 312, la même qu'avant, g4), 99,97 % (5 sur
16 551, les mêmes, g2). Tests : `tests/extract/test_totaux_categories_d29.py`.

## D-3707 — Mesures (dev seulement)

Bancs `dev` (bloc A -> lot 2, `scripts/analyse_bruit.py --avant`) :

| jeu | bruit non apparié + pièges | par dossier | pièges déclenchés | VP/FP certains | rappel |
|---|---|---|---|---|---|
| g4 (175) | 200 -> 176 | 1,14 -> 1,01 | 46 -> 40 | 103/0 -> 103/0 | 0,8311 -> 0,8311 |
| g2 (232) | 277 -> 226 | 1,19 -> 0,97 | 29 -> 17 | 115/0 -> 115/0 | 0,8700 -> 0,8700 |
| d'origine (202) | 192 -> 174 | 0,95 -> 0,86 | 28 -> 28 | 125/0 -> 125/0 | 0,8320 -> 0,8293 |

Par contrôle (trois jeux) : P4 62 -> 28, C5 56 -> 41, D1 `total_ht` 15 -> 0, D1 `total_debours` 8 -> 0, C1 24 -> 14,
C4 18 -> 11, B1 31 -> 27 ; E5 24 -> 25 (un reliquat d'avoir devenu visible). Aucun FP certain ; aucune erreur
appariée perdue hors BX0168-E2 (D-3703) ; exactitude des montants inchangée (g4 0,958, g2 0,9658). Les jeux tenus à
l'écart n'ont pas été relancés par ce bloc (lecture en totaux seulement, à faire par le fondateur ou au bloc suivant).
Suite complète : 2 431 tests verts ; 8 échecs dans `tests/web`, `tests/facturation`, `tests/security`,
`tests/platform/test_isolation.py`, tous sur des fichiers modifiés en parallèle par les blocs interface et sécurité
(`web/suivi.py`, `services/reclamations.py`…), aucun sur un fichier du moteur.

## D-3709 — Progression fine du pipeline

`OptionsPipeline.progression` : rappel facultatif `(etape, fait, total)`, étapes `pipeline.ETAPES_PROGRESSION` =
`pages` (fichiers lus : pages, découpage, classement des documents de chaque fichier), `classement` (documents
classés), `extraction` (documents extraits), `regroupement`, `controles` (dossiers contrôlés). Une erreur du rappel
est journalisée et n'interrompt rien. `jobs.handlers.relais_progression(ctx)` écrit `"<etape> <fait>/<total>"`
(`regroupement` sans compteur, 32 caractères au plus) par `JobContext.etape` : à chaque changement d'étape, à la fin
d'une étape, sinon au plus toutes les 2 s (une écriture en base par appel). Le pipeline exécuté dans le processus fils
de `executer_avec_delai` envoie ses étapes par le tube du résultat (`("progression", …)`), relayées dans le parent ;
`options.progression` reste `None` à travers le tube (rien d'impicklable). L'affichage relève du bloc interface
(`web/suivi.py`, D-3805). Tests : `tests/assembly/test_pipeline.py`, `tests/platform/test_relais_progression.py`.

# Interface (bloc I) : listes en SQL, retour filtré, sessions actives, interface en anglais (octobre 2026)

## D-3801 — Listes filtrées en SQL : dossiers, suivi des avoirs, file de validation

- **Où** : `storage/listes_sql.py` (requêtes : `dossiers_page`, `lignes_dossiers`, `ecarts_page`,
  `totaux_ecarts`, `transitaires_ecarts`), `OperatorScope.rechercher_file_validation` et `points_attention`
  (`storage/scope.py`) ; mise en forme de la seule page affichée dans `web/listes_sql.py` et `routes_admin.py`.
  Aucun accès base hors de `controldone.storage` : `TenantScope.lister_parmi` (`IN` par paquets de 500) et
  `executer_lecture` (lecture construite dans `storage` à partir de `TenantScope.requete`).
- **Cloisonnement** : toutes les requêtes partent du `SELECT` cloisonné de `TenantScope` (ce client ; constats
  publiés seuls pour un rôle client) ; filtres validés par `lire_requete` puis passés en paramètres liés
  (sous-chaînes échappées) ; page bornée (25/50/100), page au-delà de la dernière ramenée à la dernière.
- **Mêmes résultats que les filtres Python** (gardés comme référence, `web/listes_vues.py`) : statut « client »
  par `CASE` sur les agrégats des constats de la version courante ; montants en texte exact triés et comparés par
  `CAST … AS NUMERIC` (clé de tri, bornes passées en texte), affichages et totaux recalculés en `Decimal` ;
  écarts : composante et transitaire rapprochés sur leurs listes fermées puis passés comme ensembles de codes.
  Tests d'équivalence sur un client fictif grossi (`tests/web/test_listes_sql.py`, 56 cas) ; seuls les ex aequo
  peuvent changer d'ordre (et le tri par âge des écarts est à l'instant, non au jour).
- **File de validation** : filtrée et triée avant la limite (avant : 500 constats lus puis filtrés) ; libellés de
  documents, références et extraits seulement pour la page ; points d'attention lus en colonnes (liste `liens`
  extraite du JSON), au plus 200 affichés avec le total. `services.reclamations.registre(ecart_ids=…)` : une page
  d'écarts, événements lus en une requête (avant : une par écart).
- **Mesure** (`scripts/mesure_listes.py`, 5 000 dossiers fictifs, médiane de 3, client HTTP de test, SQLite) :
  `/espace/dossiers` 1 180 → 247 ms ; recherche 1 037 → 228 ms ; filtre + tri montant 1 119 → 205 ms ;
  `/espace/recouvrement` 2 350 → 175 ms ; `/admin/validation` 33 700 → 700 ms, filtrée 33 300 → 500 ms.
  Aucun index ajouté (backlog).

## D-3802 — Retour après action dans une liste filtrée

`rendu.retour_sur` accepte une requête encodée, chemin interne seulement : ASCII imprimable sans espace,
2 000 caractères au plus ; ni schéma ni hôte (`//`, `/\`, `https:`) ; chemin `[A-Za-z0-9_-./]` sans `//` ni
segment `..` (donc sans `%2F` déguisé) ; requête en caractères non réservés, `+ = &` et `%XX` hexadécimaux, sans
caractère de contrôle encodé ; ancre `[A-Za-z0-9_-]`. L'adresse de retour des listes est recomposée par le serveur
(`Requete.url`). Validation, rejet et rétrogradation dans la file filtrée, « J'ai envoyé mon courrier » et « Avoir
reçu » dans le suivi des avoirs filtré, « Relancer » dans les tâches filtrées reviennent à la même liste. Tests de
redirection ouverte (`test_interface_bloc_i.py`, propriétés `tests/proprietes/test_prop_web.py`).

## D-3803 — Interface en anglais

- **Catalogue maison** (aucune dépendance) : textes français source marqués `_()` (gabarits, code web) ou `N_()`
  (libellés traduits à l'affichage) ; `web/i18n_en.py` donne l'anglais (786 entrées) ; paramètres `str.format`.
  Langue portée par une `ContextVar` posée par le middleware de session (et par `rendu.page`) ; textes du
  JavaScript transmis dans un bloc `<script type="application/json">` inerte (CSP et Trusted Types inchangés).
- **Choix** : cookie `cd_langue` (`__Host-` en production, `HttpOnly`, un an, aucune donnée personnelle) posé par
  `POST /preferences/langue` (jeton CSRF, retour validé par `retour_sur`) ; sans cookie, `Accept-Language` pour les
  pages sans session (connexion) ; français sinon. Bouton FR/EN dans l'en-tête. Page d'erreur : le bouton renvoie
  à l'accueil, jamais à l'adresse demandée (une 404 reste identique pour un objet d'un autre client).
- **Formats** : dates « 6 Oct 2026, 15:49 », montants « 1,234.56 EUR », tailles en KB/MB (mêmes chiffres exacts).
- **Hors traduction** : `AVERTISSEMENT` et `PHRASE_RENVOI` exacts restent en français dans les deux langues
  (SPEC §3.3–3.4) ; en anglais, l'avertissement est suivi d'une traduction **de courtoisie** signalée « Courtesy
  translation (the French text above prevails) ». Textes des constats, noms des contrôles, rapports, relevés,
  messages d'alerte et du journal : français, marqués `lang="fr"`. Le module de garde-fous ne vise que le
  français ; les traductions sont contrôlées par `check_text` et par une liste d'équivalents anglais interdits.
- **Tests** : chaque texte marqué a sa traduction et les mêmes paramètres ; chaque gabarit est rendu dans les deux
  langues (parcours client et fondateur, 2e facteur et paiement simulé rendus directement), garde-fous propres,
  avertissement exact présent.

## D-3804 — Mes sessions actives

Page `/compte/sessions` (tous les rôles) sur l'API du bloc sécurité (D-3603) : appareil (navigateur · système
réduits), réseau tronqué, ouverture, dernière activité, « Cette session ». « Fermer » une session et « Fermer mes
autres sessions » (POST avec jeton CSRF). Une session est désignée par une référence HMAC tronquée de son
identifiant : ni identifiant ni jeton dans le HTML ; une référence d'un autre compte est sans effet. Lien dans
l'en-tête et la palette de commandes.

## D-3805 — Étapes fines du traitement d'un dépôt

Le suivi (`web/suivi.py`) affiche les étapes du pipeline (D-3709) : reçu, lecture des pages, classement,
extraction, regroupement, contrôles, terminé ; compteur « fait/total » de l'étape courante (page et JSON :
`fait`, `total`, `texte` traduit). « lecture » (worker sans étapes fines) = lecture des pages ; valeur inconnue
idem. Barre de progression au prorata du compteur, par pas de 5 %. Rang, pourcentage et texte viennent du
serveur ; le JavaScript n'a plus de liste d'étapes.

## D-3806 — Libellés des alertes

`web/listes_vues.LIBELLES_ALERTES` : un libellé par type émis dans le code (tâche morte, coûts IA, sauvegardes :
`sauvegarde_echec`, `_verification_echec`, `_absente`, `_hors_site_echec`, volume non chiffré, facturation,
quarantaine, agents) ; repli sur les libellés des notifications puis sur le nom technique. Badge « grave » pour
les alertes qui exigent une action. Un test relève les types émis dans les sources et exige leur libellé.
Tâches : colonnes « Créée » (`JobInfo.cree_le`) et « Prochain essai » séparées.

## D-3710 — Totaux par code déduits (D-3706) : jamais une preuve suffisante d'un écart certain

Signalement (jeux tenus à l'écart, symptômes agrégés seulement) : après le lot 2, un B2 certain non apparié et un C5
certain au montant faux, absents après le bloc A. Chemins recherchés sur le dev seulement :
- **extraction** (`_recouper_totaux_categories`) : un code sans ligne lue, admis parce que Σ des totaux par code =
  total des droits et taxes (D-3706), entrait dans la même somme qui **confirme** ce total (et les totaux de code) :
  confirmation circulaire, qui portait le total des droits et taxes au-dessus de `C_MIN_CERTAIN` alors que les lignes
  n'étaient pas lues — chemin vers un B2 total certain et vers la valeur liquidée comparée par C1–C6 ;
- **réseau d'identités** (`corroboration`) : `dec:code:<code>` (Σ lignes = total du code) et `dec:codes:<total>`
  (Σ totaux = total) acceptaient un total déduit et pouvaient corroborer lignes et total ;
- **structure** (`_code_complet_par_total`) : un total déduit égal à la somme des lignes « prouvait » que les lignes du
  code étaient toutes lues et levait le motif D-3103 ;
- **B2 par code** : un total rattaché (« Total autres taxes ») pouvait être la valeur comparée.
Règle : un total par code déduit porte `regle_derivation` (`REGLE_TOTAL_CODE_SANS_LIGNE` ou
`REGLE_TOTAL_CATEGORIE_RATTACHE`, `TotalTaxeCode.deduit`) et une confiance plafonnée à 0,85. Il ne confirme rien à
l'extraction, n'entre dans aucune identité (le réseau des totaux par code est abandonné dès qu'un total est déduit,
comme avant le lot 2), ne prouve pas la complétude des lignes ; B2 par code contre un total déduit est au plus
`a_verifier` (`structure_non_validee`). Il reste porté (mesure d'extraction, motif « le total reprend la somme des
totaux par code », qui ne fait que retirer de la certitude).
D-3704 : la règle « premier dossier » ne s'applique qu'à un classement `a_verifier` et ne rend que `non_applicable` ;
un écart certain et son montant ne sont jamais touchés (vérifié : aucun montant de constat certain changé entre le
bloc A et le lot 2 sur les trois dev). Tests : `tests/controls/test_famille_b.py`,
`tests/controls/test_corroboration.py`, `tests/extract/test_totaux_categories_d29.py` (D-3710).

Mesure (dev, lot 2 -> D-3710) : constats identiques sur les trois jeux (aucun constat ajouté, retiré ou reclassé ;
montants inchangés) — g4 103/0 certains, rappel 0,8311, bruit 176 ; g2 115/0, 0,8700, 226 ; d'origine 125/0,
0,8293, 174. Les chemins fermés ne sont pas exercés par le dev : l'effet sur les jeux tenus à l'écart reste à
mesurer (en totaux).

# Décisions du fondateur (6 octobre 2026)

### D-4000 — Arbitrages sur les 9 points en attente

1. **Lecture par Claude : activée (A)**, avec un plafond de dépense par client. La clé sera fournie plus tard par le
   fondateur (D-4001 et suivantes).
2. **Dossier réel : accepté (A)**, à quatre conditions : accord écrit du client, contrat de sous-traitance RGPD,
   anonymisation, entreprise non exclue. La règle « aucune donnée réelle » est levée pour ce dossier seulement.
   Une recherche de dossiers d'anciens employeurs (CHANEL), même anonymisés, est refusée : exclusion explicite et
   salle blanche.
3. **CI à chaque push / PR : tests rapides (A)** ; le banc complet reste manuel.
4. **Nettoyage de l'historique Git : oui (A)**, corpus et adresse d'auteur. Il sera fait en dernier, une fois tous les
   corpus régénérables et vérifiés.
5. **HSTS preload : non pour l'instant (B).**
6. **A13 : regroupement (C)**, un seul « à vérifier » par dossier, « codes à rapprocher manuellement ».
7. **Rapports en anglais : non pour l'instant (B).**
8. **Alertes : notification sur téléphone (B)**, de type ntfy.
9. **Mise en ligne : procédure pas à pas (A)**, exécutée par le fondateur (`docs/MISE_EN_LIGNE.md`).

### D-4501 — Procédure de mise en ligne pas à pas (décision 9A)

- `docs/MISE_EN_LIGNE.md` : procédure du fondateur, en français, de la commande de la VM jusqu'à l'ouverture. Rien n'a
  été acheté, créé ni déployé.
  - Comparatif des hébergeurs relevé le 2026-10-06 sur les pages officielles, sources datées en annexe : Scaleway,
    OVHcloud, Hetzner et Infomaniak, comparés sur le lieu des données, le DPA, le chiffrement du disque, PostgreSQL
    géré, les instantanés, le stockage objet et le prix d'une VM 2 vCPU / 4–8 Go. Un chiffre non vérifié est
    marqué comme tel ; aucun n'est estimé.
  - DNS : A/AAAA, CAA (Let's Encrypt et ZeroSSL), domaine sans courriel (null MX, SPF `-all`, DMARC `reject`).
  - Serveur : compte `cdadmin` sans accès root par SSH, pare-feu 22/80/443, `unattended-upgrades` sans redémarrage
    automatique, volume LUKS (RS-21), Docker depuis le dépôt officiel et désactivé au démarrage.
  - Application : chaque variable de `.env.prod` expliquée ; service ponctuel `migrer` ; TLS par Caddy ;
    `creer-fondateur` et TOTP ; contrôles de santé.
  - Sauvegardes et alertes : exercice `controldone sauvegarde exercice` (équivalent conteneur de
    `make restauration-test`) ; copie rclone vers Object Storage `fr-par` ; essai ntfy (`alertes essai`).
  - Stripe en réel, pages juridiques, liste des sous-traitants ultérieurs, liste de contrôle d'ouverture, retour
    arrière et routine mensuelle.
- **Recommandation : Scaleway Paris (PAR-1)**, DEV1-M (≈ 14,74 €/mois HT) + volume bloc chiffré par LUKS + Object
  Storage fr-par, soit de l'ordre de 20 à 25 € HT/mois hors IA.
  - Pourquoi : données en France chez une société française ; transfert vers l'UE admis pour les clients suisses ;
    VM, volume, stockage S3 et PostgreSQL géré dans une seule console et sous un seul DPA ; facturation à l'heure.
  - Alternatives : Infomaniak si la clientèle est surtout suisse ; Hetzner et OVHcloud VPS, moins chers.
- Données au repos : LUKS par nos soins quel que soit l'hébergeur, avec un fichier conteneur si le VPS n'a pas de
  volume séparé, et déverrouillage manuel après redémarrage (D-3605 vérifie le chiffrement au démarrage). ntfy
  ne reçoit aucune donnée client (D-3502) : il figure au registre, pas dans le DPA client.
- **Écarté** :
  - fixer un prix non vérifié (IPv4 Scaleway/Hetzner, stockage objet hors Scaleway, entité Stripe) ;
  - le redémarrage automatique des mises à jour, incompatible avec le déverrouillage manuel du volume ;
  - `make` et un venv sur le serveur : l'exercice tourne dans l'image.

# Lecture par Claude activée (décision du fondateur D-4000 point 1)

### D-4001 — Le modèle n'est appelé que là où l'extraction déterministe est faible, et il complète seulement

- **Déclenchement** (`extract.llm.motif_appel`) : après les extracteurs `structure` et `deterministe`, le pipeline
  passe leurs résultats à l'extracteur `llm` (`ExtractionContext.options["resultats_precedents"]`, une ligne dans
  `pipeline._extraire`). Appel seulement si : aucune extraction (mise en page inconnue), champ requis absent
  (`CHAMPS_REQUIS` : FC numéro, date, devise, total ; déclaration MRN, devise, montant facturé ; FT numéro, date,
  TTC ; avoir numéro, date), ou champ clé (§5.3) lisible de confiance < `CONTROLDONE_LLM_SEUIL_CONFIANCE` (0,70).
  Un export structuré complet fait foi : jamais d'appel.
- **Complément** (`extract.llm.completer`) : le résultat `llm` est une copie de l'extraction déterministe où seuls
  sont ajoutés les champs simples absents ou illisibles, et une liste entière quand le déterministe n'en a lu aucun
  élément et que ses éléments n'ont pas de classification déduite par le code (énumérations, booléens : pas de
  `taxations` lues par le modèle). Une valeur lisible du déterministe n'est **jamais** remplacée ni mise en
  désaccord : la fusion (§7.3) ne voit que des valeurs identiques ou des champs nouveaux. Pas de mélange des listes
  par rang.
- **Jamais de calcul** : le schéma ne demande que du texte imprimé ; normalisation, sommes, comparaisons restent
  dans le code.
- **Écarté** : appeler le modèle sur tous les documents (coût, et désaccords qui plafonnent la confiance de valeurs
  justes) ; laisser le modèle remplacer une valeur déterministe (une lecture fausse du modèle deviendrait la valeur
  du contrôle).

### D-4002 — Modèle et effort

- **Modèle** : `claude-opus-5-5` (défaut recommandé par la documentation Claude API au 25/09/2026 ; 4 $ / 20 $ par
  million de jetons, lecture du cache 0,20 $). Justification : la tâche est courte et vérifiée (ancrage), mais les
  documents visés sont précisément ceux que les règles ne savent pas lire (mise en page inconnue, OCR médiocre) :
  la qualité de lecture prime ; le volume est faible (seuls les documents faibles, plafond par client).
  Remplaçable sans code : `CONTROLDONE_LLM_MODEL` (ex. `claude-sonnet-5-5`, 2 $ / 10 $), avec un tarif dans
  `config/llm_tarifs.yaml` ; un modèle absent de la table est compté au tarif le plus élevé.
- **Effort** : `low` (`CONTROLDONE_LLM_EFFORT`) — recopie de valeurs, pas de raisonnement long ; sur Opus 5.5 la
  réflexion ne peut pas être désactivée, l'effort est le seul réglage (défaut du modèle : `medium`). À confirmer
  par la mesure D-4008 (`--effort medium` pour comparer). Vide = défaut du modèle (obligatoire pour Haiku 4.5,
  sans paramètre d'effort).
- **Sortie structurée** : `messages.parse(output_format=<schéma Pydantic fermé>)`, revalidée par le code ; aucun
  outil (`tools` absent) ; repli serveur en cas de refus (`fallbacks: "default"`, inchangé).

### D-4003 — Ancrage obligatoire et confiance plafonnée : jamais d'écart certain sur le seul modèle

- Chaque valeur renvoyée doit être **retrouvée sur une page du document** (`extract.llm.localiser`) : sous-chaîne
  exacte aux espaces près, ou « proche » (casse, apostrophes, guillemets, tirets typographiques) — les chiffres ne
  sont jamais rapprochés ; un extrait qui coupe un nombre (groupe de milliers, décimales), un mot ou une référence
  est refusé. La valeur enregistrée est le **texte imprimé** (pas la recopie du modèle), normalisé par le code.
  Introuvable ou illisible : **rejetée** (auparavant : gardée à 0,50).
- Confiance d'une valeur du modèle : `min(CONTROLDONE_LLM_CONFIANCE_ANCREE, 0,65)` (0,60 si ancrage proche) —
  `PLAFOND_CONFIANCE_LLM = 0,65` < `C_LECTURE_CONFIRMABLE = 0,70` (une identité imprimée ne peut pas la promouvoir,
  D-2314) < `c_min_certain = 0,90`. Une valeur du seul modèle ne peut donc jamais être une valeur clé d'un
  `ecart_certain` ; au mieux `a_verifier`. La lecture corroborée (D-1700) s'applique en plus, inchangée.
- Test : `tests/test_llm.py::test_valeur_du_seul_modele_ne_fonde_jamais_un_ecart_certain`.

### D-4004 — Coût calculé depuis l'usage, plafond mensuel vérifié avant chaque appel

- Coût = usage renvoyé par l'API (entrée non mise en cache, sortie, écriture et lecture du cache de prompt) × tarifs
  datés de `config/llm_tarifs.yaml` (source : documentation Claude API, 2026-09-25 ; copie intégrée si le fichier
  manque) × `CONTROLDONE_USD_EUR`. Coût du modèle **servi** (repli éventuel). Réponse reçue mais hors schéma :
  l'estimation majorante est comptée.
- **Avant chaque appel**, `CostGuard` compare l'estimation majorante (tout le texte au prix plein, 4 000 jetons de
  sortie) au plafond par lot (0,50 EUR) et au plafond **mensuel du client** : le worker passe au pipeline le
  plafond et le coût déjà engagé ce mois (`OptionsPipeline.plafond_ia_client_mensuel_eur`, `cout_ia_mois_eur`).
  Refus : aucun appel, extraction déterministe seule, « extraction partielle ». Plafond déjà atteint au début du
  lot : le pipeline tourne sans modèle (inchangé).
- Alertes : `cout_ia_alerte` (80 %) et `cout_ia_plafond` (100 %) émises à l'enregistrement du coût réel du lot
  (inchangé) ; coûts visibles par le fondateur sur le tableau de bord et `controldone llm couts`.
- **Cache de prompt** : consignes statiques (règles + champs du type) dans `system`, point de cache sur le second
  bloc ; rien de variable avant (testé). Cache des réponses par empreinte des pages (§20.5, inchangé).
- **Défauts inchangés** : 8 EUR / mois (continu), 20 EUR (diagnostic), 0,50 EUR par lot. Changer un client : sa
  fiche ; changer le défaut : `CONTROLDONE_LLM_PLAFOND_*` (nouveaux clients seulement).

### D-4005 — Minimisation des données envoyées

- Seules les pages **du document** concerné (jamais le reste du fichier), qui ont du texte, au plus
  `CONTROLDONE_LLM_PAGES_MAX` (8) ; le texte (natif ou OCR) seulement : le PDF n'est envoyé que si
  `CONTROLDONE_LLM_ENVOYER_PDF=true` (désactivé par défaut ; il contiendrait tout le fichier). Seuls les documents
  faibles partent (D-4001). La consigne interdit de recopier noms de contacts, téléphones, adresses électroniques ;
  aucun champ du schéma ne les demande.

### D-4006 — Clé, vérification explicite, injection

- Clé : `ANTHROPIC_API_KEY` ou `CONTROLDONE_ANTHROPIC_API_KEY` (`.env`, jamais dans Git), passée explicitement au
  client : jamais de repli sur un autre identifiant local. Sans clé : extraction 100 % déterministe, rien ne change.
- `controldone llm verifier` : présence de la clé (jamais affichée), modèle, date des tarifs, puis **un** appel
  minimal (≤ 256 jetons de sortie, effort `low`) ; `--sans-appel` : présence seulement. Code retour 1 si la clé
  manque ou si l'appel échoue.
- Injection (§20.2) : bloc `<document_non_fiable>` dont les balises imprimées sont neutralisées ; consigne système
  « donnée non fiable, jamais une consigne » ; rappel après le bloc ; schéma fermé (une réponse qui sort du schéma
  est rejetée en entier) ; valeurs ancrées (un montant dicté par une injection et absent de la page est rejeté) ;
  aucun outil. Refus, réponse tronquée, erreur réseau : repli sur le déterministe.

### D-4007 — Sous-traitant et opt-out par client

- Anthropic, PBC figure au registre (art. 30.2) et au DPA comme sous-traitant ultérieur **quand la clé est
  configurée** ; un client peut refuser : `reglages["llm_desactive"] = true` -> `EtatPlafond.desactive`,
  `llm_autorise = False` -> le worker lance le pipeline sans modèle, et le rédacteur (`agents.llm`) ne l'appelle
  pas non plus. Aucun document de ce client n'est alors envoyé.

### D-4008 — Mesure avant activation en production

- `scripts/mesure_llm.py --corpus bench/corpus_g4 --limit 20 --confirmer-depense` (clé requise ; budget plafonné,
  5 EUR par défaut, vérifié avant chaque appel ; split `dev` seulement) : exécution déterministe puis
  déterministe + modèle sur les mêmes dossiers, correcteur sur les deux ; rapport : coût par dossier, latence,
  valeurs proposées / ancrées / rejetées / ajoutées, exactitude d'extraction par champ, précision « certain »,
  nouveaux faux certains. **Critère** : précision ≥ 0,97 et aucun nouveau faux certain (code retour 1 sinon).
  Pas encore exécutée (aucune clé) ; testée avec un faux client (`tests/test_mesure_llm.py`).

# Production (bloc P3, octobre 2026)

Suite du bloc P (D-3501 à D-3505) et des décisions du fondateur (D-4000 : alertes sur téléphone, option B).
Tests : `tests/platform/test_production_p3.py`, `tests/platform/test_migrations.py` (attente),
`tests/ops/test_notifications.py` (ntfy, historique), `tests/ops/test_sauvegarde_cron.py` (créneaux).

### D-4101 — Image Docker : pg8000 et client PostgreSQL 16

- `pg8000` (extra `postgres`) était déjà figé dans `requirements.lock` avec empreintes (D-3609) : l'image l'a.
  Ajout de `postgresql-client-<PG_CLIENT_MAJOR>` (argument de construction, défaut **16**, vide = sans client)
  depuis le dépôt officiel PGDG : Debian 13 ne fournit que la version 17, et `pg_dump` refuse un serveur plus
  récent que lui. Clé du dépôt **versionnée** (`deploy/pgdg.asc`, empreinte
  `B97B 0AFC AA1A 47F0 44F2 44A0 7FCC 7D46 ACCC 4CF8` vérifiée) : aucune clé téléchargée à la construction.
  `CONTROLDONE_PG_DUMP` / `CONTROLDONE_PG_RESTORE` pointent vers `/usr/lib/postgresql/client-bin/` (binaires de
  la version choisie, sans passer par l'enveloppe Perl `pg_wrapper`).
- **Vérifié le 6 octobre 2026** : image construite (`pg_dump (PostgreSQL) 16.15`, pg8000 1.31.5), puis dans le
  conteneur contre une grappe PostgreSQL 16 jetable (`scripts/pg_jetable.sh`) : `controldone migrer` (base
  neuve), `sauvegarde sauvegarder --verification-profonde` (conforme), `verifier --dernier`, `restaurer
  --base-cible … --controler` (conforme). Taille de l'image : 763 Mo.
- Construction derrière un mandataire à autorité privée (environnement de développement seulement) : image de
  base locale qui ajoute l'autorité, passée par `--build-arg PYTHON_IMAGE=…` ; le Dockerfile n'en garde aucune
  trace.

### D-4102 — Migration en attente : service ponctuel `migrer`, attente puis sortie unique

- **Constat** : pendant une mise à jour, `web` et `worker` sortaient en code 3 tant que `controldone migrer`
  n'avait pas tourné, et `restart: unless-stopped` les relançait en boucle.
- **Choix** : service compose **ponctuel** `migrer` (`controldone migrer`, `restart: "no"`, volumes des données
  et des sauvegardes) dont `web`, `worker` et `scheduler` dépendent (`service_completed_successfully`) : à
  chaque `docker compose up -d`, sauvegarde chiffrée s'il y a des étapes, étapes, chiffrement des traces
  (D-4106), puis démarrage du reste. Un échec arrête `docker compose up` avec le message du service.
  En plus, au démarrage en production, une étape en attente fait **attendre** le processus
  (`Database.attendre_schema_a_jour`, `CONTROLDONE_MIGRATION_ATTENTE_S`, défaut 600 s ; message clair puis rappel
  chaque minute ; le web n'écoute pas, sa sonde est « unhealthy ») : il démarre dès la migration faite, sinon
  sort **une fois** (code 3). Colonnes manquantes sans étape en attente : arrêt immédiat (attendre n'y changerait
  rien). Nouvelle exception `MigrationEnAttente` (sous-classe de `SchemaPerime`).
- **Écarté** : migration automatique au démarrage par défaut (pas de sauvegarde préalable, deux processus qui
  migrent) ; conteneur d'initialisation hors compose (pas de notion d'init container dans compose v2 au-delà
  de `depends_on`).

### D-4103 — Effacement RGPD d'un client sous le verrou de maintenance

`supprimer_client` prend le verrou de maintenance (D-3504) avec une attente courte (10 s,
`attente_verrou_s`) puis lève `VerrouOccupe` (« sauvegarde en cours depuis … ») **sans rien avoir effacé** : une
sauvegarde ne copie jamais un client à moitié effacé ; le fondateur relance après la sauvegarde. Les traces
d'envoi du client sont supprimées après déchiffrement de leur champ `tenant_id` ; les factures émises restent
(obligation de conservation).

### D-4104 — Notifications sur téléphone (ntfy) de premier rang ; historique lisible

- Configuration du fondateur : `CONTROLDONE_NOTIF_WEBHOOK_URL=https://ntfy.sh/<sujet-secret>`,
  `CONTROLDONE_NOTIF_WEBHOOK_FORMAT=texte` ; facultatifs `CONTROLDONE_NOTIF_WEBHOOK_JETON` (jeton ntfy, en
  `Authorization: Bearer`) et `CONTROLDONE_NOTIF_NTFY_PRIORITE` (1–5, défaut 4 ; l'essai en 3). URL et jeton
  jamais affichés (`repr` masqué) ni journalisés. Essai : `controldone alertes essai`, lancé par le fondateur
  seulement, inscrit dans l'historique (`essai:<horodatage>`).
- Historique : chaque notification garde ses canaux **et leur résultat** (`webhook:ok,courriel:echec` dans la
  colonne existante `canaux` ; l'ancien format reste lu). Lecture : `storage.alertes.historique_notifications`,
  `etat_canaux` ; `services.notifications.historique(db, limite, jours)` pour l'interface ; `controldone alertes
  historique`. Aucune migration de schéma.

### D-4105 — Deux sauvegardes par jour : RPO 12 h

- `SCHED_BACKUP_HHMM=0215,1415` (liste d'heures UTC) ; créneau courant = plus récente heure passée ; rattrapage
  par `backup-cron.sh --si-absente-depuis HHMM` (une archive du jour datée du créneau ou après suffit).
  Restauration d'essai hebdomadaire : première sauvegarde du jour seulement. Rotation : les 4 plus récentes
  (`BACKUP_RECENTES`), puis 7 jours et 4 semaines (≈ 12 archives). Fraîcheur hors site 14 h
  (`BACKUP_AGE_MAX_H`), crontab hôte `45 2,14 * * *`, sonde « homme mort » période 12 h, grâce 2 h.
- Corrigé en passant dans `deploy/scheduler.sh` : un `SIGTERM` reçu avant la première attente faisait
  `kill 0` (tout le groupe de processus) ; un arrêt demandé pendant une tâche repartait pour une attente
  complète (`SCHED_TICK_S`) avant de sortir.
- RPO 12 h (≈ 12 h 30 hors site). **Écarté pour l'instant** : expédition continue du journal (Litestream) —
  outil et procédure de restauration de plus, pour un gain qui ne se justifie pas au volume actuel.

### D-4106 — Traces d'envoi chiffrées au repos

- `storage/traces_envoi.py` : Fernet, clé dérivée HKDF `outbox_envoyee` de la clé maîtresse (MultiFernet :
  rotation), fichier `<type>/<nom>.enc` préfixé `CDT1`, écriture atomique 0600. Utilisé par `ExpediteurFichier`
  (`<id>.json.enc`) et `ExpediteurFacture` (`<numéro>.pdf.enc`).
- Migration des fichiers existants : étape de données de `controldone migrer` (chiffre, relit, puis supprime le
  clair ; idempotent ; `--etat` les compte). Sauvegarde et restauration inchangées (fichiers copiés tels
  quels) ; le contrôle approfondi déchiffre chaque trace (`traces d'envoi : N déchiffrées`).
- **Écarté** : passer les traces par le coffre (`FileVault`) — adressage par contenu, purge et effacement par
  client à revoir, sans gain de sécurité (même clé maîtresse).

# Outillage (bloc O3) : CI à chaque push, TIFF déterministes, tous les corpus régénérables (octobre 2026)

## D-4401 — CI : job rapide à chaque push et pull request, banc complet à la demande

Décision du fondateur 3A. `.github/workflows/ci.yml` : job `rapide` sur `push` et `pull_request` (ruff,
pre-commit sur tout le dépôt, `pytest -m "not lent and not postgresql and not proprietes"`, tests de propriétés
en profil `ci`, cache pip, Tesseract installé ; environ 1 min 30 de tests en local, cible < 10 min). Jobs
`complet` (audit des dépendances, couverture sur toute la suite, tests PostgreSQL par serveur jetable —
`make test-pg-securite`, `make restauration-test-pg` —, banc et sa porte) et `image` (construction et audit Trivy)
sur `workflow_dispatch` seulement. `concurrency` par workflow, type d'événement et branche, avec annulation de
l'exécution en cours. Syntaxe vérifiée par actionlint 1.7.12. Pas de marqueur `bench` : aucun test ne dépend d'un
corpus généré (les tests du correcteur et de `bench_run` fabriquent leurs mini-corpus).

## D-4402 — TIFF du générateur 2 écrits de façon déterministe

Cause : libtiff (via Pillow, LZW et G4) aligne le répertoire et les valeurs hors ligne sur un mot en sautant un
octet qu'il n'initialise pas ; sa valeur dépend du tas, d'où des TIFF aux mêmes pixels mais aux octets différents
(D-3904). Correction : `bench/generator2/degrade.py`, `tiff_canonique` appliquée à la sortie de `images_to_tiff` :
parcours de la structure TIFF (en-tête, chaîne des répertoires, valeurs hors ligne, bandes et tuiles) et mise à zéro
de tout octet non référencé (remplissage, en-têtes de page résiduels de l'écriture multipage de Pillow) et de la
fin inutilisée des valeurs en ligne. Les pixels et les étiquettes décodés sont identiques (vérifié sur les 149 TIFF
de `corpus_g2` à `corpus_g7`) ; `tiff_canonique(ancien) == régénéré` à l'octet pour chacun d'eux. Pas de changement
de compression (un TIFF non compressé aurait changé la taille et le chemin de lecture des fichiers du banc). Le
générateur 1 n'écrit pas de TIFF. Version du générateur inchangée (les sorties ne changent que sur des octets que
nul lecteur ne lit).

## D-4403 — Recettes et empreintes de tous les corpus ; `make corpus-tous`, `make corpus-verifier`

Préalable à la réécriture de l'historique (décision 4A). `bench/corpus_empreintes.json` contient la recette de
`corpus`, `corpus_h2`, `corpus_g2` … `corpus_g7`, retrouvée dans les manifestes (graine, nombre, version), les
README du banc et le backlog de l'orchestrateur (`corpus_g5` : préfixe `GW`, `--ext --all-holdout`, nombre
d'erreurs par contrôle par défaut, déduit de `stats_generation.json`). Chaque recette a été rejouée le 2026-10-06
avec le générateur actuel, dans un répertoire temporaire, et comparée à la copie présente : **tous les corpus se
régénèrent** — à l'octet près pour `corpus` et `corpus_h2` (générateur 1, arbre complet), aux pixels près pour
`corpus_g2` à `corpus_g7` (seuls les octets de remplissage des TIFF et les empreintes qui les citent diffèrent ;
arbre complet identique aux pixels). Aucun ancien commit du générateur n'est nécessaire : les corrections 2.0.1 et
2.1 (repli F1) ne touchent pas ces graines. Empreintes : `sha256` (truth.json, générateur actuel), `sha256_historique`
(copie antérieure à D-4402), `sha256_pixels`, `sha256_arbre` / `sha256_arbre_historique` / `sha256_arbre_pixels`
(tous les fichiers sauf `stats_generation.json`, qui contient une durée). Une régénération donne désormais les mêmes
octets (deux générations de `corpus_g3` avec un nombre de processus différent : arbres identiques).
Le générateur 1 importe numpy, retiré des dépendances de l'application (audit final) : version figée
`numpy==2.4.6` dans la recette, installée à part par `make corpus-deps` (`var/bench_deps`, jamais dans
l'environnement de l'application) et par la CI juste avant le banc. Le banc de la CI passait par
`python -m bench.generator` sans numpy : il échouait ; il passe désormais par la recette, empreinte vérifiée.

# Interface (bloc I3, octobre 2026) : tableaux de bord en SQL, langue par compte, alertes graves, notifications

## D-4301 — Tableau de bord client et fiche client du fondateur en SQL

- **Avant** : `/espace` relisait tous les dossiers et constats (`lister_dossiers`, `constats_courants`,
  `reclamations.registre` complet, graphiques sur objets ORM) ; `/admin/clients/{id}` relisait tous les dossiers
  (`lister_dossiers`) puis filtrait et paginait en Python.
- **Après** : `storage/listes_sql.py` `compter_dossiers` (`COUNT`) et `constats_indicateurs` (constats visibles de
  la version courante, **lecture en colonnes** jointe au dossier, jamais le JSON `contenu` entier) ;
  `web/listes_sql.indicateurs` additionne en `Decimal` avec les règles de `ligne_dossier` et du rapport (hors
  totaux exclus, certain = validé, à vérifier = non rejeté) ; les mêmes lignes alimentent les graphiques
  (`graphes.donnees_client(scope, lignes)`). Reste à recouvrer / avoirs reçus : `totaux_ecarts` (D-3801). Les
  8 « Derniers dossiers » viennent de `dossiers_page` (tri par date décroissante ; avant : 8 premiers par
  référence, contraire au titre). Fiche : `services.admin.fiche_client(lire_dossiers=…)` lit la page filtrée
  (`page_dossiers`) et les indicateurs **dans le périmètre déjà ouvert** (une seule entrée de journal).
- **Cloisonnement** : tout part de `TenantScope.requete` (rôle client : constats publiés seuls) ; jointure au
  dossier par `TenantScope.requete(Dossier)` en sous-requête. Tests d'équivalence avec l'ancien calcul (client,
  lecteur, fondateur) et d'isolation (`tests/web/test_interface_bloc_i3.py`).
- **Mesure** (`scripts/mesure_listes.py --dossiers 5000`, médiane de 3, SQLite) : `/espace` 3 617 → 246 ms ;
  `/admin/clients/demo_ateliers` 1 376 → 283 ms ; filtrée (`q` + statut) 1 306 → 151 ms. Pages ajoutées au script.

## D-4302 — Langue de l'interface enregistrée sur le compte

- Colonne `users.langue` (`fr` | `en` | nulle), **étape de migration 5** `langue_utilisateur` (idempotente,
  colonne nullable) et déclarée dans le modèle. `storage.comptes.definir_langue` : le compte lui-même seulement
  (le fondateur ne choisit pas pour un autre), valeur fermée, journal `choisir_langue`.
- Page **« Mon compte »** (`/compte`, icône dans l'en-tête, palette) : choix FR/EN enregistré sur le compte ; liens
  vers les sessions et le mot de passe. Le bouton FR/EN de l'en-tête, connecté, enregistre aussi sur le compte.
- **Lue à la connexion** : si le compte a une langue, le cookie `cd_langue` est reposé (donc suivie d'un navigateur
  à l'autre) ; sans préférence de compte, le cookie du navigateur n'est pas touché. Pages sans session : cookie
  puis `Accept-Language` (inchangé, D-3803). Rapports et constats restent en français (décision 7B).

## D-4303 — Bandeau des alertes graves non lues sur `/admin`

Types : `sauvegarde_*`, `volume_non_chiffre`, `cout_ia_plafond`, `job_mort` (`listes_vues.alerte_du_bandeau`).
Une ligne par type (nombre, date de la plus récente ; `OperatorScope.alertes_non_lues_par_type`, `GROUP BY`),
sauvegardes d'abord. « Marquer comme lu » par type ou « Tout marquer comme lu » (`POST /admin/alertes/bandeau/lues`,
CSRF, fondateur) : `OperatorScope.marquer_alertes_lues`, une transaction, une entrée `alerte_lue` par alerte ;
un type hors bandeau n'est jamais marqué par ce formulaire. Le bandeau disparaît quand tout est lu.

## D-4304 — Historique des notifications poussées (`/admin/notifications`)

Lien depuis `/admin/alertes`. Lecture par l'API du bloc production `services.notifications.historique` (D-4104 ;
90 derniers jours, 500 lignes au plus, paginées à l'affichage) via `web/notifications_vues.py` : configuration
(actives / mode hors production / aucun canal ; noms des canaux et erreurs de variables, **jamais** l'URL, le jeton
ni l'adresse), état par canal (dernier succès, dernier échec, « en échec »), historique avec le résultat de chaque
canal. L'interface mince écrite d'abord (lecture directe de `notifications_alertes`) a été retirée quand l'API est
arrivée.

## D-4305 — Coût IA et lecture par modèle sur la fiche client

Le coût IA du mois face au plafond était déjà sur `/admin` (jauge par client) et en indicateur de la fiche.
Ajouts : jauge, pourcentage et état (80 %, plafond atteint = appels arrêtés ; plafond nul = 100 %, comme
`EtatPlafond.arret`) sur la fiche ; **case « Autoriser la lecture par modèle de langage »** (`POST
/admin/clients/{id}/llm`) qui écrit `reglages["llm_desactive"]` (lu par `jobs.couts.llm_desactive`, D-4007),
journalisée par `modifier_client` ; badge « Lecture par modèle désactivée » dans la liste des clients de `/admin`.

## D-4306 — Corrections relevées pendant la vérification navigateur

- Graphiques : `minmax(440px, 1fr)` écrasait la règle mobile (déclarée avant) → débordement horizontal à 375 px ;
  désormais `minmax(min(440px, 100%), 1fr)`.
- Palette de commandes : un lien `.carte-tete` hors `.carte` (bandeau) levait une erreur ; recherche du bloc
  parent tolérante. Entrée « Mon compte » ajoutée.
- Vérification (Chromium, démo, 0 erreur de console, axe-core 0 violation, FR/EN, deux thèmes) : `/admin`,
  fiche client, `/admin/notifications`, `/admin/alertes`, `/compte`, `/espace`.

# Moteur (bloc M3) : A13 regroupé, D1 sans faux certain, bruit « à vérifier », rappel certain (dev seulement, octobre 2026)

Constat : sur les jeux tenus à l'écart, D1 donnait encore deux faux certains (un piège, un non apparié, connus par
leurs seuls totaux), le bruit dépassait l'alerte sur deux jeux (1,49 et 1,55) et le rappel des erreurs attendues
« certain » restait entre 55 et 75 %. Tout a été étudié et mesuré sur les seuls jeux de développement
(`corpus_g4`, `corpus_g2`, `corpus` : split `dev`) ; aucun jeu tenu à l'écart n'a été lu ni relancé. Règles
générales seulement : aucune ne lit un nom de gabarit, de fichier, de client ou de transitaire.

## D-4201 — A13 : un seul « à vérifier » par dossier, codes à rapprocher manuellement (décision 6C du fondateur)

A13 n'émet plus qu'un constat par dossier : les codes sans équivalent de **tous** les couples (facture -> déclaration),
dans les deux sens, sous le libellé « Codes marchandise à rapprocher manuellement : … » suivi de la phrase de renvoi ;
toutes les valeurs en preuves, tous les documents des couples concernés. Toujours `a_verifier` (contrôle de signal,
`renvoi = true`, montant `null`), jamais certain. `details` : `sh6_facture_seuls`, `sh6_declaration_seuls`, et par
couple `croise` (écart des deux côtés, la forme des vrais écarts A13) ; `a_sens_unique` quand aucun couple n'est
croisé. Les couples conformes ou non vérifiables gardent leur résultat. Mesure : le moteur émettait déjà un constat
par couple et presque tous les dossiers n'en ont qu'un : A13 non apparié reste à 72 sur les trois jeux (le vrai cas
à sens unique, GX0005, est conservé). Le gain est de lecture (un seul point à traiter par dossier), pas de compte.

## D-4202 — D1 total HT / total des débours : lignes prouvées complètes

Un total imprimé **supérieur** à la somme des lignes lues n'est un écart certain que si une autre identité
**imprimée** (ni déduite ni reconstruite) prouve que la lecture des lignes est complète ; sinon `a_verifier`
(`structure_non_validee`, `details.structure_non_validee`). Preuves (`famille_d._preuves_lignes_completes`) :
total TTC = somme des lignes + total TVA ; facture structurée (XML, CSV) ; pour le total HT, total des débours imprimé
= somme des débours lus **et** total TVA imprimé = somme des TVA imprimées de chaque ligne qui en porte une (toutes
les prestations en portent) ou taux unique × lignes taxées ; pour le total des débours, TTC ou total HT = somme de
toutes les lignes. D-3703 (lecture sous le seuil -> `non_verifiable`) passe avant. Mesure (trace des écarts positifs
sur le dev) : 8 écarts prouvés, tous de vraies erreurs (un seul écart d'OCR, rattrapé par le test de confusion) ;
24 non prouvés, aucune erreur réelle. Les 9 D1 certains du dev restent certains.

## D-4203 — D1 : lectures alternatives d'une ligne ; ligne de débours

- `ligne` : montant = q × pu × (1 + t) ou prix TVA comprise (colonne « TTC »), ou un nombre imprimé dans le libellé
  redonne le montant avec le prix lu (tarif au kilo, à l'article) -> `non_verifiable` (`montant_tva_comprise` ou
  `lecture_douteuse`, `details.explications`).
- `tva_ligne` : TVA lue = montant × (1 + t) (montant TTC lu dans la colonne TVA, y compris à taux nul) ->
  `non_verifiable` (`montant_tva_comprise`). Sur le dev : D1 `tva_ligne` 10 -> 3 (lignes TVA comprise).
- Une ligne de **débours** (forfait par article, droits) reproduit un montant de la déclaration : son produit est
  celui de la déclaration (G1, B1) et la refacturation est comparée par C et G ; D1 `ligne` -> `non_applicable`
  (`couvert_par_autre_controle`). Cas trouvé : GZ0066, erreur G1 (forfait 15,00 ≠ 2 × 3,00) reprise sur la facture
  du transitaire ; sur un original natif, D1 l'aurait relevée en écart certain hors erreur et hors piège.
- Total des débours dont l'écart égale le montant d'une ligne lue comme prestation (« TVA al'importation » mal lue)
  -> `non_verifiable` (`nature_de_ligne`).

## D-4204 — D1 : autres présentations des totaux, sans effet sur le montant

TTC = HT des prestations + TVA + total des débours imprimé (débours hors HT, lignes de débours non toutes lues) ;
net à payer = TTC − acomptes + total des débours ; total HT avant une remise ou un avoir porté en ligne négative.
Ces présentations n'expliquent qu'un total qui les redonne **à la tolérance près** ; elles ne servent jamais de
référence au montant d'un écart (une première version qui les laissait choisir comme « calcul le plus proche » a
déplacé le montant du vrai D1 de GZ0107, relevé par le banc : corrigé).

## D-4205 — C5 : écart en faveur du client qu'une lecture explique

Écart négatif (refacturé < liquidé), classement `a_verifier` :
- aucune ligne de TVA ni de « droits et taxes » refacturée et l'écart égale la TVA liquidée -> `non_verifiable`
  (`tva_non_refacturee` : TVA autoliquidée dont l'indice n'est pas lu, ou acquittée directement ; relève de C3/C4) ;
- lecture sous le seuil et aucun total des débours imprimé égal à la somme des débours lus -> `non_verifiable`
  (`debours_possiblement_non_lus`, comme D-3703).
Un écart certain ou en défaveur du client n'est jamais concerné. C5 non apparié 41 -> 24. Coût : quatre appariements
« à vérifier » perdus (GZ0016, GZ0130, GZ0199, BX0188) ; tous étaient des constats de signe et de montant faux
(−1 345,31 pour une erreur de +118,60…) appariés par le seul contrôle accepté.

## D-4206 — P1 : manque commun à tout le lot, signalé une fois

Quand **aucun** dossier du lot n'a de document exploitable du type manquant, le manque est un fait du lot : le
premier dossier (identifiant) qui le partage porte le constat, cite les documents restés sans contrepartie dans
chacun de ces dossiers et précise « même manque pour N autres dossiers du lot » ; les autres -> `non_applicable`
(`couvert_par_autre_controle`, `details.dossier`, motif `manque_commun_du_lot`). Le statut du dossier reste
`document_manquant` (`findings_io.statut_global_depuis_resultats`). Un défaut d'appariement (le type existe ailleurs
dans le lot) reste signalé par chaque dossier. P1 non apparié 35 -> 22, aucun manque réel perdu.

## D-4207 — A2 : référence de facture lue par OCR

`normalize.refs.ref_compatibles_ocr` : `ref_compatibles` sur les clés de confusion OCR (« 0MS » / « OMS »,
« G1 » / « GI », troncature « 1C20263215 » de « FT PIC2026/3215 ») -> conforme. `ref_facture_proches` : quand l'une
des deux valeurs est lue par OCR, clés de confusion d'au moins 8 caractères à au plus `max(1, n // 6)` caractères
d'écart -> `non_verifiable` (`lecture_douteuse`, motif `reference_proche`). Texte natif des deux côtés : inchangé.
Toutes les erreurs A2 injectées sont des références absentes (branche inchangée). A2 non apparié 33 -> 15.

## D-4208 — B2 : total supérieur à la somme lue, lignes possiblement non lues

Écart positif, structure qui signale une ligne non lue (article ou code sans ligne de taxe lue, ligne sans code) et
lecture sous le seuil (ou articles non tous lus) -> `non_verifiable` (`structure_non_validee`, motif
`lignes_possiblement_non_lues`), comme D-2307 et D-3703. B2 total non apparié 33 -> 19. Coût : BX0039-E1 n'est plus
apparié (constat de +10 822,49 pour une erreur de −30,95).

## D-4209 — F3 : lien établi par le MRN

La facture qui refacture le MRN d'un autre dossier n'est rattachée à ce dossier que faiblement, à cause de l'écart
lui-même. Quand le MRN est lu sûrement (≥ `C_MIN_CERTAIN`, ancré, même préfixe) sur les deux factures et que la
complémentarité a pu être testée (montant liquidé connu), le lien est établi par le MRN : `ControlContext.classify`
reçoit `liens_etablis` (documents exclus de la condition 5) et `_raisons_ailleurs` n'ajoute plus
`rattachement_faible`. Les autres conditions (confiance des montants, confusion, corroboration D-1700) restent. Gain :
BX0137-E3 et BX0188-E4 deviennent certains (corpus d'origine). Les autres F3 « à vérifier » ont aussi une valeur lue
sous le seuil : inchangés.

## D-4210 — P4 : lien faible d'un document partagé, signalé une fois

Un document rattaché faiblement à plusieurs dossiers du même lot (avoir ou relevé d'une page d'un PDF « envoi
complet ») n'est signalé que par le premier de ces dossiers ; ailleurs `non_applicable` (`lien_faible_partage`).

## D-4211 — Mesures (dev seulement)

Bancs `*_dev_m3base` (code de départ, identique à `*_dev_lot2d`) -> `*_dev_m3g` :

| dev | VP / FP certains | rappel | rappel certain | bruit / dossier | pièges déclenchés | montants justes |
|---|---|---|---|---|---|---|
| `corpus_g4` (175) | 103 / 0 -> 103 / 0 | 0,8311 -> 0,8212 | 0,733 -> 0,733 | 1,006 -> 0,857 | 40 -> 27 | 0,958 -> 0,979 |
| `corpus_g2` (232) | 115 / 0 -> 115 / 0 | 0,8700 -> 0,8700 | 0,777 -> 0,777 | 0,974 -> 0,832 | 17 -> 13 | 0,966 -> 0,966 |
| d'origine (202) | 125 / 0 -> 127 / 0 | 0,8293 -> 0,8238 | 0,813 -> 0,826 | 0,861 -> 0,787 | 28 -> 27 | 0,960 -> 0,973 |

Bruit non apparié + pièges (trois jeux) : 576 -> 501 (0,946 -> 0,823 par dossier). Par contrôle : A2 33 -> 15,
C5 41 -> 24, B2 total 33 -> 19, P1 35 -> 22, D1 `tva_ligne` 10 -> 3, P4 28 -> 25. Seuils bloquants : PASSE sur les
trois. Les six appariements perdus (D-4205, D-4208) étaient des constats de signe ou de montant faux. Totaux par code
(tâche 5) : rien de sûr à gagner sans nouvelle lecture ; L4 n'imprime aucun total par code (36 des 133 absents du
corpus d'origine), les autres absents sont des récapitulatifs OCR que l'identité « somme des codes = total » ne
confirme pas (souvent parce qu'un total est l'erreur injectée). Extraction inchangée : calibration identique.
Tests : `tests/controls/test_bloc_m3.py`, `test_famille_d.py`, `test_precision_d28.py` (données fictives).

### D-4404 — Plus aucun corpus versionné ; nettoyage de l'historique (décision du fondateur 4A)

Les corpus `bench/corpus_g3`, `corpus_g4` et `corpus_g5` ne sont plus suivis par Git. Les 9 corpus sont tous
régénérables par recette et contrôlés par empreinte : `make corpus-verifier` indique 9 conformes sur 9 avant le
nettoyage. L'historique des deux branches de travail (`v2`, `claude/modest-allen-yyjsg9`) est ensuite réécrit pour en
retirer `bench/corpus_g2_new`, `corpus_g3`, `corpus_g4` et `corpus_g5` (environ 690 Mo), et pour attribuer les
enregistrements à « Claude <noreply@anthropic.com> » au lieu de l'adresse personnelle du fondateur. Les autres
branches du dépôt ne sont pas touchées. Une copie complète de l'historique d'avant la réécriture est conservée hors du
dépôt, le temps de vérifier.
