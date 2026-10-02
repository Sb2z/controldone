"""Interface web (FastAPI, gabarits Jinja2 rendus côté serveur, en français) et montage de l'API REST.

    from controldone.web import ParametresWeb, create_app
    app = create_app(ParametresWeb(...))   # ou create_app() : paramètres lus dans l'environnement

Voir ``docs/DECISIONS.md`` (D-5xx) et ``docs/SECURITY.md``.
"""

from controldone.web.app import ParametresWeb, create_app

__all__ = ["ParametresWeb", "create_app"]
