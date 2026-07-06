# Profil client ControlDOne

Un **profil client** regroupe toutes les données propres à une entité contrôlée.
Le moteur n'en contient aucune en dur : il lit le profil actif au lancement.

## Créer un profil

1. Copier ce dossier `_template/` en `config/clients/<nom>/`
   (ex. `config/clients/macompagnie/`).
2. Remplir :
   - `entities.yaml` : vos entités, TVA/SIREN, alias de noms et d'adresses, scope ;
   - `hs_scope.txt` : vos codes HS6 (un par ligne) ;
   - `fx_rates.yaml` : *optionnel*, surcharge de taux de change.
3. Sélectionner le client au lancement :
   - `CONTROLDONE_CLIENT=<nom>` (variable d'environnement), **ou**
   - automatiquement si `config/clients/` ne contient qu'un seul dossier client.

## Important

- Votre dossier `config/clients/<nom>/` **n'est jamais committé** (cf. `.gitignore`) :
  il contient vos données réelles et vous appartient.
- Seul ce `_template/` (vierge) est suivi par git.
- Plusieurs profils peuvent coexister : le moteur les charge par injection
  (`pipeline.analyze(..., profile=...)`), sans état partagé entre clients.
