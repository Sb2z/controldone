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
