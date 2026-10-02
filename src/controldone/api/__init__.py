"""API REST ``/api/v1`` (clé d'API par client). Voir ``docs/API.md``.

Authentification : ``Authorization: Bearer cdk_<préfixe>_<secret>`` (ou en-tête ``X-API-Key``). La clé
désigne un client et un rôle client : le client n'est **jamais** lu dans un paramètre. Un objet d'un autre
client et un objet inexistant donnent la même réponse ``404``. Les constats renvoyés sont les seuls constats
**publiés** (validés par le fondateur). Les montants sont des écarts constatés entre documents, pas un avis
juridique.
"""

from controldone.api.routes import creer_api

__all__ = ["creer_api"]
