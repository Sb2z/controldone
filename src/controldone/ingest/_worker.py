"""Processus isolé d'extraction de pages (§20.3) : lit une requête JSON sur l'entrée standard.

Requête : ``{"entree": chemin, "sortie": chemin, "mime": str, "options": {...}}``. Écrit
``{"pages": [PageText.to_dict()]}`` dans ``sortie``. Aucun contenu de document sur la sortie standard.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    from controldone.ingest.pages import OptionsPages, extraire_pages_local

    champs = set(OptionsPages.__dataclass_fields__)
    opts = OptionsPages(**{k: v for k, v in req.get("options", {}).items() if k in champs})
    contenu = Path(req["entree"]).read_bytes()
    pages = extraire_pages_local(contenu, req["mime"], opts)
    Path(req["sortie"]).write_text(json.dumps({"pages": [p.to_dict() for p in pages]}, ensure_ascii=False),
                                   "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
