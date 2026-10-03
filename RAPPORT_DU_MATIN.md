# Rapport du matin — ControlDOne v2

*Nuit du 1er au 2 octobre 2026. Branche `v2` du dépôt `Sb2z/controldone` (orpheline, sans historique commun avec l'ancien code ; miroir sur `claude/modest-allen-yyjsg9`). Rien n'a été envoyé, publié, déployé ni payé. Aucun compte n'a été créé.*

**En une phrase.** Le moteur de contrôle tourne de bout en bout sur des dossiers synthétiques, passe le seuil bloquant sur un corpus tenu à l'écart (précision des écarts certains 100 %, 46 sur 46), mais il n'a jamais vu un document réel : ce sont les trois diagnostics gratuits qui diront s'il tient et si le marché existe.

> **Mise à jour du 3 octobre 2026 :** audit final complet (bugs, robustesse, performance, cohérence, juridique France-Suisse) et corrections vérifiées au banc. Voir `docs/AUDIT_FINAL.md`. Les « dossiers de demande d'avoir » sont devenus un relevé d'écarts et un modèle neutre que le client adapte ; l'offre gratuite est une remise de lancement avec un accord de publication séparé.

---

## 1. Ce qui fonctionne, et comment le vérifier vous-même

Prérequis : Python 3.11, `uv`, Tesseract avec la langue française (`apt install tesseract-ocr tesseract-ocr-fra`).

| Quoi | Commande | Ce que vous devez voir |
|---|---|---|
| **Tout, en une commande** | `make demo-complete` | Rapport de démonstration, base web neuve, interface sur http://127.0.0.1:8000/connexion. Identifiants affichés et écrits dans `var/demo_web/identifiants.txt`. Code TOTP du fondateur : `scripts/demo_complete.sh totp`. |
| Rapport de diagnostic seul (6 s) | `controldone demo` | `var/demo/report.pdf` (16 pages) et `report.html`. Dossier 1 : TVA refacturée malgré l'autoliquidation (C3, 2 356,28 EUR) et prix au-dessus de la grille (D3). Dossier 2 : erreur de calcul base × taux sur la déclaration (B1) et renvoi sur l'origine (A12, sans montant). Dossier 3 : conforme. |
| Diagnostic d'un dossier réel | `make diagnostic DOSSIER=chemin/du/dossier SANS_LLM=1` | Rapport PDF, HTML, JSON et XLSX dans `var/diagnostic/`. |
| Tests | `make test` | **1 542 tests verts** (≈ 2 min). `make lint` : aucune erreur. |
| Banc d'évaluation (développement) | `python -m bench.generator --out bench/corpus --split dev --count 250 --seed 20261002` puis `make bench-dev` | 202 dossiers ; seuil bloquant **PASSE**. |
| Banc sur le corpus tenu à l'écart | `python -m bench.generator --out bench/corpus_h2 --split holdout --count 250 --seed 20261003` puis `python -m controldone.bench_run --corpus bench/corpus_h2 --split holdout --out bench/out/h2 --workers 4` | 48 dossiers ; seuil bloquant **PASSE** (code de sortie 0 avec `--gate`). |
| API REST | `http://127.0.0.1:8000/api/v1/openapi.json` | Déposer un dossier, lire les écarts, suivre un litige. Doc : `docs/API.md`. |
| Serveur MCP | `CONTROLDONE_MCP_API_KEY=cdk_… python -m controldone.mcp_server` | Mêmes fonctions que l'API. Configuration Claude : `docs/MCP.md`. |
| Site public | `python -m http.server -d site 8080` | Offre, tarifs, démonstration sur données fictives, méthode, pages juridiques en brouillon ; version anglaise dans `site/en/`. |

**Ce qui est construit** (détails dans `docs/ARCHITECTURE.md` et `docs/DECISIONS.md`, 143 décisions tracées) :

- **Niveau 1, moteur.** Réception sûre (ZIP, e-mail, limites de taille), texte natif et OCR, découpage des PDF fusionnés, Factur-X / UBL / CII, exports de déclarations XML et CSV, extracteurs déterministes pour les quatre types de documents, regroupement en dossiers, 59 contrôles (familles P, A à G), deux niveaux « écart certain » / « à vérifier », chaque écart avec sa preuve (document, page, valeur lue, extrait de page dans le rapport), rapport web et PDF. Aucune comparaison ni aucun montant n'est calculé par un modèle.
- **Niveau 2, exploitation.** Multi-clients avec cloisonnement en trois barrières testé (un identifiant d'un autre client donne la même erreur qu'un identifiant inexistant), rôles, journal d'audit chaîné infalsifiable, coffre de fichiers chiffré par client, file de tâches idempotente avec reprise, interface en français (tableau de bord, vue dossier, file de validation en un clic, autonomie réglable par type d'action, tout manuel par défaut), agents d'exploitation qui ne peuvent que proposer, suivi des litiges et commissions, référentiel anonymisé (seuil de 5 clients et 10 dossiers par case), API, MCP, connecteurs (dossier surveillé, réellement fonctionnel et testé de bout en bout ; IMAP ; plateforme agréée en bouchon).
- **Niveau 3, encaisser.** Offres paramétrables (390 EUR, 20 %, 99 / 199 / 349 EUR par mois), coupon « 3 diagnostics gratuits », factures Factur-X EN 16931 numérotées sans trou et immuables, Stripe en mode test avec bouchon local, connecteur de plateforme agréée en bouchon, contrôle avant paiement des factures électroniques reçues par les clients, page Finances (revenu, coût d'IA, marge), modèle sur 12 mois (`finance/modele_12_mois.xlsx`).
- **Niveau 4, clients.** Site, brouillons juridiques, 26 prospects réels sourcés, séquence de 3 e-mails et 2 messages LinkedIn, 20 brouillons personnalisés (dont **13 déposés comme brouillons dans votre Gmail**, objet « [À VALIDER] »), 5 posts et un article sur cas fictifs.
- **Niveau 5.** Préparation des données MACF pour le déclarant autorisé (jamais de dépôt), site en anglais, présentation investisseur d'une page (`investisseurs/one_pager.pdf`), trois noms alternatifs (`investisseurs/noms.md`) : **Probant**, **Apuro**, **Ecarto** (recherche web rapide, pas de recherche de marque).
- **Sécurité.** Revue par un agent qui n'a pas écrit le code : 15 problèmes corrigés (dont un élevé : la signature des webhooks Stripe était vérifiable avec un secret écrit dans le code), 6 ouverts. Aucune vulnérabilité connue dans les 80 dépendances (`pip-audit`). Licences permissives uniquement. Détail : `docs/REVUE_SECURITE.md`.
- **Déploiement préparé, pas lancé.** Image Docker construite et vérifiée, `docker-compose` avec Caddy (HTTPS), sauvegardes chiffrées hors site, procédure Scaleway Paris (≈ 6,55 EUR/mois, source dans `docs/recherche/legal_market.md`) : `docs/DEPLOIEMENT.md`.

## 2. Résultats du banc d'évaluation sur le corpus tenu à l'écart

Le générateur a été écrit par un agent qui n'a jamais vu le code d'extraction ni de contrôle. Le corpus est fictif : 4 clients, 8 gabarits de transitaires, 6 mises en page de déclaration, 4 niveaux de dégradation de scan, 30 % de PDF fusionnés.

**Seuil bloquant retenu : précision des « écarts certains » ≥ 0,97**, et ≥ 0,95 par contrôle dès 10 constats. Un diagnostic contient environ 20 à 40 écarts certains ; à 0,97, on attend moins d'une fausse accusation par diagnostic, que votre validation doit intercepter. À 0,90, on en attendrait 2 à 4, de quoi ruiner la crédibilité du client face à son transitaire. S'y ajoutent : rappel de 100 % sur les documents manquants, aucune formulation interdite et aucun montant sur une note de renvoi (`docs/SPEC.md` §19.7).

**Mesure finale : second corpus tenu à l'écart** (48 dossiers, graine 20261003, jamais vu par personne avant la mesure, code définitif) :

| Indicateur | Valeur |
|---|---|
| Erreurs injectées (dont attendues « certain ») | 148 (55) |
| Écarts certains produits : vrais / faux | **46 / 0** |
| Précision des écarts certains | **100 %** (borne basse de Wilson à 95 % : **92,3 %**) |
| Rappel (toutes erreurs) | 74,3 % |
| Rappel des erreurs attendues « certain » | 74,6 % |
| Exactitude des montants | 90,7 % |
| Bruit : constats « à vérifier » sans erreur derrière | **1,67 par dossier** (au-dessus de l'alerte fixée à 1,5) |
| Coût d'IA par dossier | 0,00 EUR (pas de clé d'API : extraction sans modèle) |
| Durée par dossier, OCR compris | moyenne 16,7 s, médiane 13,3 s, p95 66,6 s, max 74,1 s |
| Seuil bloquant | **PASSE** |

Par contrôle : `docs/banc/holdout2_final.md`. Plus faibles en rappel sur cet échantillon : D6 (magasinage, 0 sur 2), F3 (même déclaration refacturée deux fois, 0 sur 2, scans dégradés), B2 (0 sur 2), C5 (58 %).

**Ce qu'il faut savoir sur la façon dont ce chiffre a été obtenu :**

1. **Le premier corpus tenu à l'écart a échoué au seuil.** Précision 95,65 % (44 vrais, 2 faux). L'un des deux faux était un vrai faux positif : une ligne de taxe spécifique non lue sur un scan, alors que le total imprimé aurait dû empêcher la certitude. L'autre venait d'un défaut du correcteur, qui avait apparié l'erreur à un constat « à vérifier » au lieu du bon constat certain.
2. J'ai corrigé les causes de façon générale : garde de complétude sur la famille C, lecture des taxes spécifiques, départage du correcteur. Ce premier corpus étant alors « brûlé », j'ai remesuré sur un **corpus neuf généré avec une autre graine**. Le changement de règle du correcteur est documenté (`docs/DECISIONS.md` D-905, `docs/SPEC.md` §19.4) : il s'applique à tous les corpus, mais il a été décidé après avoir vu le premier résultat.
3. **L'échantillon reste petit.** 46 écarts certains, d'où la borne basse à 92,3 %. Un seul faux positif de plus ferait passer la précision à 97,9 %.
4. Sur le corpus de développement (202 dossiers, utilisé pour la mise au point, donc optimiste) : 114 vrais, 0 faux, rappel 81,3 %.

## 3. Ce qui n'est pas fait ou pas fiable

- **Aucun document réel n'a été traité.** Tout est synthétique. Les mises en page sont inventées et moins variées que la réalité. La démonstration l'a montré : sur une mise en page que l'extracteur n'avait jamais vue, la famille A était entièrement « non vérifiable » jusqu'à une correction faite cette nuit. **Attendez-vous à un rappel nettement plus bas sur de vrais documents**, sans fausse certitude en principe, puisque le doute classe « à vérifier ».
- **Pas de modèle de langage cette nuit.** Aucune clé d'API n'était disponible. L'extracteur par modèle est écrit et testé avec un faux client (ancrage obligatoire des valeurs, plafonds de coût, cache), mais il n'a jamais tourné en réel. Son coût et sa qualité ne sont pas mesurés.
- **Scans très dégradés** (type télécopie) : l'extraction y est faible. Les valeurs restent sous le seuil de confiance, donc les constats sortent en « à vérifier » ou « non vérifiable ».
- **Le bruit « à vérifier » (1,67 par dossier) dépasse l'alerte.** C'est du temps de validation pour vous.
- **La salle blanche repose sur des consignes données aux agents**, pas sur une séparation physique. Un audit de contamination de la spécification a conclu « propre ». Le code n'a pas fait l'objet d'un audit de similarité avec l'ancien code.
- **Rien n'a tourné en conditions de production.** La pile Docker n'a jamais été démarrée en entier (bloquée volontairement). Il n'y a ni migrations Alembic, ni test de charge.
- **Points de sécurité ouverts** (`docs/REVUE_SECURITE.md`) :
  - RS-16 : si `CONTROLDONE_ENV=prod` est oublié, le service tourne en mode développement ;
  - RS-17 : les sessions sont révoquées en mémoire d'un seul processus ;
  - RS-18 : URL de retour Stripe construite depuis l'en-tête `Host` ;
  - RS-19 : la veille ne limite pas la taille des téléchargements ;
  - RS-20 : rendu des vignettes dans le processus web ;
  - RS-21 : la base SQLite n'est pas chiffrée (volume chiffré recommandé).
- **Factur-X** : seul le schéma XSD a été vérifié. Le schematron EN 16931 et la conformité PDF/A-3 (veraPDF) ne l'ont pas été.
- **Non vérifiés à la source officielle :**
  - la liste des codes NC du MACF (EUR-Lex illisible depuis l'environnement, liste marquée « à vérifier ») ;
  - la liste exacte des statuts de cycle de vie des factures, dont « en litige » ;
  - la date du 21 septembre 2027 pour le nouveau code des douanes (source KPMG seulement, affichée « date annoncée ») ;
  - la durée de conservation de 3 ans pour la prospection (CNIL).
- **Prospects : 26 au lieu de 40.** L'API officielle était limitée en débit. Deux lignes sont à confirmer (Terr'Asia : correspondance du SIREN ; LX France : site illisible). 7 des 20 brouillons visent un formulaire de contact.
- **Chiffres retirés.** J'ai retiré du site et des contenus le chiffre « 2 à 30 % d'erreurs » (aucune référence précise) et deux chiffres d'éditeurs qu'un agent avait ajoutés hors de la conversation.
- **Le modèle financier alerte lui-même.** Dans le scénario central, les avoirs obtenus par client (≈ 1 800 EUR/an) restent sous le seuil de 3 000 à 4 000 EUR qui rend l'activité viable en solo. Ce sont des hypothèses, pas des prévisions : seuls les trois diagnostics trancheront.
- **Pas de pull request vers `main`.** La branche est orpheline à votre demande, donc GitHub ne peut pas la comparer à `main`. Le travail se consulte sur la branche `v2`.

## 4. Votre liste de validations, dans l'ordre

| # | Action | Temps estimé |
|---|---|---|
| 1 | Lire ce rapport, lancer `make demo-complete`, ouvrir le rapport PDF et l'interface | 45 min |
| 2 | **Relire votre contrat de travail** : activité accessoire, exclusivité, non-concurrence, propriété des créations. Si une clause bloque, tout s'arrête là. | 30 min (+ avis RH ou avocat si doute) |
| 3 | **Avocat** : périmètre du droit (arrêt Alma Consulting 2010) et formulation de l'offre ; commission au résultat ; CGV, accord de sous-traitance, mentions légales, confidentialité (`site/*.html`, bandeau « À RELIRE PAR UN AVOCAT ») ; accord de diagnostic (remise de lancement) et accord de publication anonymisée séparé et facultatif ; relevé d'écarts et modèle de courrier neutre (voir `docs/recherche/juridique_france_suisse.md` §10) | 2 h de préparation + rendez-vous |
| 4 | **Statut juridique** (micro-entreprise ou société), puis immatriculation → **SIREN** | 1 h en ligne + 1 à 4 semaines de délai |
| 5 | **Expert-comptable** : régime de TVA (franchise en base par défaut, paramètre `tva_applicable: false`) ; traitement fiscal de la remise de lancement de 100 % avec accord de publication séparé | 1 h |
| 6 | **Compte bancaire professionnel → IBAN** | 30 à 60 min |
| 7 | **Assurance responsabilité civile professionnelle** (dès 13 EUR/mois selon Hiscox) avant le premier client | 30 min |
| 8 | **Nom** : choisir entre ControlDOne, Probant, Apuro et Ecarto ; recherche de marque INPI / EUIPO ; **nom de domaine** | 1 h 15 |
| 9 | Renseigner votre identité de vendeur (`config/offres.yaml` ou variables `CONTROLDONE_VENDEUR_*`) : SIREN, forme, adresse, IBAN, TVA | 15 min |
| 10 | **Clé d'API du modèle** (Anthropic) ; décider si ce sous-traitant (hors UE) est acceptable ou si l'extraction par modèle reste désactivée ; régler les plafonds de coût | 30 min |
| 11 | **Compte Stripe** en mode test, clés dans `.env`, URL du webhook (`docs/FACTURATION.md`) | 30 min |
| 12 | **Hébergement européen** (Scaleway Paris recommandé) en suivant `docs/DEPLOIEMENT.md`, avec `CONTROLDONE_ENV=prod` | 2 à 3 h |
| 13 | **Plateforme agréée partenaire** pour vos propres factures, à choisir avec la grille de `docs/FACTURATION.md` §7 | 2 à 4 h |
| 14 | Adresse e-mail professionnelle et boîte de dépôt dédiée aux clients | 30 min |
| 15 | **Brouillons à approuver** : 13 brouillons Gmail et 7 messages pour formulaires (`commercial/brouillons/`, signature à compléter, préfixe à retirer) ; séquence de relances ; 5 posts et l'article LinkedIn ; textes du site | 2 h 30 |
| 16 | Vérifications techniques : liste NC du MACF contre EUR-Lex ; une facture Factur-X passée dans veraPDF ; mise à jour des taux BCE (`scripts/importer_taux_bce.py`) | 1 h 30 |

## 5. Les trois premières actions commerciales

Détail : `commercial/plan_actions_commerciales.md`.

1. **Obtenir et réaliser 3 diagnostics gratuits** (remise de lancement ; publication de résultats anonymisés seulement si le client l'accepte, par un accord séparé) : 25 à 35 h sur 8 semaines. Envoyez à la main les brouillons validés, 5 par jour au plus, avec relances à J+5 et J+12. Visez 6 à 8 rendez-vous pour obtenir 3 accords, chacun sur au moins 15 dossiers. **Critère d'arrêt fixé à l'avance** : moins de 3 000 à 4 000 EUR d'écarts par client et par an en moyenne (formule d'extrapolation écrite avant l'analyse). Dans ce cas on arrête, après six semaines perdues et non un an.
2. **Ouvrir le canal experts-comptables** : 6 à 8 h. Contactez les 4 cabinets de la liste et montrez le rapport sur cas fictif. Aucune commission d'apport à un cabinet : c'est interdit (art. 24 de l'ordonnance du 19 septembre 1945).
3. **Publier la série LinkedIn** : 5 à 6 h. Un post par semaine pendant 5 semaines, l'article en semaine 3. Tous les cas sont fictifs et étiquetés comme tels, et la phrase de renvoi figure dès qu'un sujet réglementaire apparaît.
