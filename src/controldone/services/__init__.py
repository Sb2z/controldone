"""Services de la plateforme : la logique commune à l'interface web, à l'API REST et au serveur MCP.

Chaque fonction reçoit un ``TenantScope`` (ou ouvre elle-même le périmètre du client **de l'acteur
authentifié**) : le client n'est jamais lu dans un paramètre de requête. Aucune requête SQL ici (règle
d'architecture : tout passe par ``controldone.storage``).

- ``plateforme`` : ``Plateforme`` (base, coffre, clés, limites) et erreurs communes ;
- ``depot`` : dépôt de fichiers ou d'archives (limites §20.3), lot, mise en file de ``traiter_lot`` ;
- ``lecture`` : dossiers, constats (publiés seulement pour un rôle client), lots, valeurs extraites ;
- ``validation`` : décisions du fondateur sur les constats (§7.7), corrections de valeurs ;
- ``recontrole`` : handler ``recontroler_dossier`` (contrôles relancés après une correction) ;
- ``publication`` : rapport figé sur les constats validés, publication via la file des sorties ;
- ``reclamations`` : registre de recouvrement (§17), dossier de réclamation rédigé pour le client ;
- ``admin`` : clients, utilisateurs, entités, transitaires, grilles, clés d'API, tableau de bord ;
- ``vignettes`` : rendu des pages (PNG) depuis le coffre ;
- ``demo_init`` : base de démonstration (``controldone init-demo``).
"""
