# Site public ControlDOne

Site statique, en français, sans étape de construction : des fichiers HTML, une feuille de style
partagée (`assets/style.css`), un logo SVG. Aucun script, aucune police ni ressource externe, aucun
cookie, aucun traceur, aucun formulaire. Thème clair ou sombre selon le réglage du système.

| Fichier | Contenu |
|---|---|
| `index.html` | Problème, documents comparés, livrables, limites (pas de conseil, renvoi RDE/avocat), 4 étapes, contexte réglementaire sourcé, offre de lancement |
| `tarifs.html` | Diagnostic 390 EUR HT, commission 20 % des avoirs obtenus, contrôle continu dès 99 EUR HT/mois, offre de lancement, FAQ |
| `demonstration.html` | Rapport de démonstration intégré (`demo/report.html`, `demo/report.pdf`) et captures (`demo/captures/`) — **données fictives** |
| `methode.html` | Calcul déterministe, preuve par écart, niveaux « écart certain » / « à vérifier », familles de contrôles, hors périmètre, sécurité et RGPD |
| `experts-comptables.html` | Proposition de partenariat aux cabinets (rémunération : **à valider**) |
| `contact.html` | Lien `mailto:` (adresse à compléter), pas de formulaire |
| `mentions-legales.html`, `cgv.html`, `confidentialite.html`, `dpa.html` | **Brouillons à relire par un avocat** |
| `en/` | Version anglaise de `index`, `tarifs` (`pricing`), `demonstration` (`demo`), `methode` (`method`), `contact` ; pages juridiques en français seulement (note « French version prevails — draft to be reviewed by a lawyer ») ; sélecteur de langue EN/FR dans le menu ; tests : `tests/site/test_site_en.py` |

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

Le test contrôle : aucune formulation interdite (`controldone.guardrails.check_text`) dans le texte
visible et les attributs `alt`/`title` ; aucun script, formulaire ni ressource externe ; liens sortants
limités aux sources officielles citées ; liens internes et ancres résolus ; bandeau
« BROUILLON — À RELIRE PAR UN AVOCAT » avant le titre de chaque page juridique ; phrase de renvoi exacte ;
démonstration marquée « DONNÉES FICTIVES ».

## Déployer plus tard (rien n'est déployé aujourd'hui)

N'importe quel hébergement de fichiers statiques **situé dans l'Union européenne** convient : un
stockage objet avec site statique (par exemple chez un hébergeur français ou allemand) ou un petit
serveur web. Points à respecter :

1. Publier le contenu de `site/` tel quel (pas de `README.md` nécessaire en ligne).
2. HTTPS obligatoire ; redirection HTTP vers HTTPS.
3. En-têtes conseillés : `Content-Security-Policy: default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'`,
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
      date reprise de résumés secondaires, **non confirmée sur EUR-Lex** dans `docs/recherche/customs.md`) ;
      facturation électronique (impots.gouv.fr).
- [ ] Source précise de l'allégation « 2 % à 30 % d'erreurs annoncés par des éditeurs » ajoutée, ou
      paragraphe retiré.
- [ ] Adresse `mailto:` réelle à la place de `adresse@a-completer.invalid` (`contact.html`).
- [ ] Fournisseur du modèle de langage et lieu de traitement confirmés ; si hors UE, garanties de
      transfert indiquées et option de désactivation décrite au client.
- [ ] Démonstration régénérée et toujours marquée « DONNÉES FICTIVES » ; aucune donnée réelle.
- [ ] `pytest tests/site -q` passe.
