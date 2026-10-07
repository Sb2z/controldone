# Site public ControlDOne

Site statique, en français (racine) et en anglais (`en/`), sans étape de construction : des fichiers HTML, une
feuille de style partagée (`assets/style.css`), un script local (`assets/site.js`) et la bibliothèque d'animation
Motion servie par le site (`assets/vendor/motion.min.js`, licence MIT, copie de celle de l'application). Aucune
ressource externe, aucun cookie, aucun traceur, aucun formulaire. Thème clair ou sombre selon le système.
Décisions : D-5101 à D-5106 (`docs/DECISIONS.md`) ; étude de départ : `docs/marketing/RECHERCHE.md`.

| Fichier | Contenu |
|---|---|
| `index.html` | Titre en deux tons, carte de constat fictive, bandeau de prix, écarts types (codes de contrôle), démonstration du rapprochement ligne à ligne, livrables, mesures du banc d'essai (fichiers fictifs, datées), limites et phrase de renvoi, 4 étapes, fondateur, sécurité, échéances sourcées, FAQ, offre de lancement |
| `tarifs.html` | Deux points d'entrée (diagnostic 390 € HT ; contrôle continu 99 / 199 / 349 € HT par mois pour 20 / 60 / 150 dossiers, au-delà sur devis, valeurs de `config/offres.yaml`), commission commune de 20 %, calculateur de seuil, tableau des seuils, FAQ |
| `methode.html` | Calcul par programme, preuve par écart, relecture, deux niveaux, familles de contrôles, mesures, hors périmètre, sécurité et RGPD |
| `demonstration.html` | Rapport de démonstration intégré (`demo/report.html`, `demo/report.pdf`) et captures : **données fictives** |
| `experts-comptables.html` | Proposition de partenariat aux cabinets (aucune commission d'apport) |
| `contact.html` | Lien `mailto:` avec quatre questions préremplies (adresse à compléter), pas de formulaire |
| `mentions-legales.html`, `cgv.html`, `confidentialite.html`, `dpa.html` | **Brouillons à relire par un avocat** (texte inchangé sur le fond ; bandeau « BROUILLON : À RELIRE PAR UN AVOCAT ») |
| `en/` | `index`, `pricing`, `method`, `demo`, `contact` ; pages juridiques en français seulement |
| `assets/fonts/` | Source Serif 4 Display Regular (titres), Inter Regular et SemiBold (texte), JetBrains Mono Regular (montants, références) : fichiers `woff2` officiels **non modifiés** (Source Serif : nom de police réservé « Source », donc ni découpe ni renommage), licences SIL OFL 1.1 à côté |

## Règles d'écriture (D-5105)

Phrases courtes avec un verbe, première personne du fondateur (vouvoiement), vocabulaire du client (facture du
transitaire, DAU, droits, TVA à l'importation, frais de dossier, avoir), chiffres précis et sourcés, limites dites
dans la même voix. Interdits, vérifiés par `tests/site/test_style_texte.py` : liste de style de
`RECHERCHE.md` §3.2 (FR et EN), tiret cadratin en incise, plus d'un point d'exclamation par page, marques exclues.
Rien d'inventé : pas de témoignage, de logo client ni de promesse d'économies ; les mesures du banc d'essai sont
toujours présentées comme mesurées sur des fichiers de test synthétiques, avec leur date. « Offert » est toujours
suivi, au même endroit, de « la commission de 20 % sur les avoirs obtenus reste due » (test).

## Mouvement (D-5103)

Durées 120 / 200 / 280 / 400 ms, courbe d'entrée `cubic-bezier(0.16, 1, 0.3, 1)`, ressorts sans rebond, seulement
`transform` et `opacity`, pas de parallaxe, rien qui dure plus de cinq secondes. Entrée du haut de page en CSS
(fonctionne sans script) ; avec Motion : compteurs (montant fictif, mesures), révélations au défilement, fil des
étapes, rapprochement « ligne de facture contre ligne de déclaration » piloté par le défilement sur grand écran
(joué une fois à l'entrée dans la vue sur téléphone), en-tête condensé, barre de lecture des pages longues, FAQ
adoucie, appel à l'action collant sur téléphone, calculateur. Sans JavaScript ou avec `prefers-reduced-motion:
reduce`, toutes les valeurs finales sont affichées directement et le calculateur laisse place au tableau des seuils.

Le registre des traitements (art. 30.2 RGPD et prospection) est un document interne :
`docs/RGPD_registre.md`, non publié.

## Prévisualiser

```bash
python -m http.server -d site 8080
# puis ouvrir http://127.0.0.1:8080/
```

## Régénérer la démonstration

```bash
source .venv/bin/activate
controldone demo                     # écrit var/demo/ (jeu entièrement fictif)
python scripts/site_copier_demo.py   # copie dans site/demo/ avec le bandeau « DONNÉES FICTIVES »
```

Les captures de `demo/captures/` ont été prises avec Playwright + Chromium sur `demo/report.html`
(synthèse, un constat, vue téléphone). Les reprendre si le gabarit du rapport change.

## Vérifier

```bash
pytest tests/site -q
```

Les tests contrôlent : aucune formulation interdite (`controldone.guardrails.check_text`) dans le texte
visible et les attributs ; exactement deux scripts locaux avec `defer` (`assets/vendor/motion.min.js` puis
`assets/site.js`), aucun script en ligne, aucun attribut `style`, CSP en `<meta>` (`script-src 'self'`,
`style-src 'self'`, `font-src 'self'`, `connect-src 'none'`, `form-action 'none'`) ; aucun formulaire ni
ressource externe ; polices locales avec leurs licences ; liens sortants limités aux sources officielles citées ;
liens internes et ancres résolus ; bandeau « BROUILLON : À RELIRE PAR UN AVOCAT » avant le titre de chaque page
juridique ; phrase de renvoi exacte ; démonstration marquée « DONNÉES FICTIVES » ; prix et seuils recalculés depuis
`config/offres.yaml` ; fonction de calcul de `site.js` exécutée par Node si disponible ; style des textes
(`test_style_texte.py`).

Mesuré le 7 octobre 2026 (Chromium, 1440 px) : environ 600 Ko au premier chargement sans compression, dont
390 Ko de polices et 140 Ko pour Motion ; environ 460 Ko avec gzip. Activer la compression (gzip ou brotli)
chez l'hébergeur. Contrôle axe-core (WCAG 2.1 AA et bonnes pratiques) : aucune violation sur les 15 pages, thèmes
clair et sombre, 1440 px et 390 px.

## Déployer plus tard (rien n'est déployé aujourd'hui)

N'importe quel hébergement de fichiers statiques **situé dans l'Union européenne** convient : un
stockage objet avec site statique (par exemple chez un hébergeur français ou allemand) ou un petit
serveur web. Points à respecter :

1. Publier le contenu de `site/` tel quel (pas de `README.md` nécessaire en ligne).
2. HTTPS obligatoire ; redirection HTTP vers HTTPS.
3. En-têtes conseillés (la même CSP figure déjà en `<meta>` dans chaque page, sauf `frame-ancestors`, ignoré
   en `<meta>`) : `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; frame-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'`,
   `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Strict-Transport-Security`.
4. Désactiver toute mesure d'audience ajoutée par l'hébergeur ; noter la durée de conservation de ses
   journaux dans `confidentialite.html`.
5. Reporter le nom, l'adresse et le téléphone de l'hébergeur dans `mentions-legales.html`.

## Liste de contrôle avant publication

- [ ] Toutes les mentions `[À COMPLÉTER : …]` remplies (identité de l'éditeur, SIREN, forme juridique,
      adresse, téléphone, TVA, directeur de la publication, hébergeur, adresse e-mail de contact,
      sous-traitants et lieux de traitement).
- [ ] Toutes les mentions `[À VALIDER]` tranchées (assiette HT/TTC de la commission, durée de prise en
      compte des avoirs, résiliation, plafond de responsabilité, délai de notification des violations,
      conditions de l'offre de lancement, rémunération des cabinets d'expertise comptable).
- [ ] CGV, DPA, politique de confidentialité et mentions légales **relues par un avocat**, y compris la
      frontière audit technique / consultation juridique (loi n° 71-1130, art. 54 ; Cass. 1re civ.,
      15 nov. 2010, n° 09-66.319). Retirer ensuite les bandeaux « BROUILLON ».
- [ ] Rémunération éventuelle des experts-comptables vérifiée au regard de leurs règles déontologiques.
- [ ] Chiffres du contexte revérifiés sur la source officielle le jour de la publication :
      règlement (UE) 2026/382 (3 EUR par article) ; règlement (UE) 2025/2083 et calendrier MACF
      (30 septembre 2027) ; date d'application du nouveau code des douanes de l'Union (21 septembre 2027 :
      date reprise de résumés secondaires, **non confirmée** : retirée du site le 7 octobre 2026, D-5106 ; le site
      cite désormais le règlement (UE) 2026/2108 et les dates du 1er juillet 2028 et du 1er mars 2034 publiées par la
      Commission) ; facturation électronique (FAQ impots.gouv.fr « À partir de quand suis-je concerné ? » : émission
      obligatoire pour les PME au 1er septembre 2027).
- [ ] Placeholders du fondateur remplis : photo réelle, poste et durée dans le groupe du luxe (sans nommer
      l'entreprise), programme et année à GEM, raison d'avoir construit ControlDOne (accueil FR et EN).
- [ ] Offre de lancement retirée ou mise à jour dès que les trois diagnostics sont attribués (L121-4, 7°).
- [ ] Bloc « Ce que j'ai mesuré » (accueil, Méthode) recalculé et redaté à chaque nouvelle version du moteur
      (`docs/TESTS_INTENSIFS.md`).
- [ ] Délai de réponse (« deux jours ouvrés ») confirmé, ou retiré de `contact.html`.
- [ ] Adresse `mailto:` réelle à la place de `adresse@a-completer.invalid` (`contact.html`).
- [ ] Fournisseur du modèle de langage et lieu de traitement confirmés ; si hors UE, garanties de
      transfert indiquées et option de désactivation décrite au client.
- [ ] Démonstration régénérée et toujours marquée « DONNÉES FICTIVES » ; aucune donnée réelle.
- [ ] `pytest tests/site -q` passe.
