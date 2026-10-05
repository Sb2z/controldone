"""Traite UN échantillon comme un lot complet (réception -> pages -> … -> contrôles) et écrit un bilan JSON.

    python scripts/fuzz/executer_un.py <fichier> <bilan.json>

Lancé par ``campagne.py`` (un processus par échantillon : temps et mémoire mesurés de l'extérieur). Code de
sortie 0 si le pipeline a rendu la main (quelle que soit l'issue du fichier), 2 sur exception non rattrapée.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path


def main() -> int:
    source, sortie = Path(sys.argv[1]), Path(sys.argv[2])
    debut = time.monotonic()
    bilan: dict = {"fichier": str(source)}
    try:
        from controldone.pipeline import OptionsPipeline, controler_lot, preparer_lot

        with tempfile.TemporaryDirectory(prefix="cdo-fuzz-") as tmp:
            lot = Path(tmp) / "lot"
            lot.mkdir()
            shutil.copyfile(source, lot / source.name)
            options = OptionsPipeline(llm=False, seed=1)
            prep = preparer_lot(lot, None, [], options=options)
            res = controler_lot(prep, options=options)
        pages = [p for ps in prep.pages.values() for p in ps]
        bilan.update({
            "ok": True,
            "fichiers": [{"chemin": f.chemin_relatif, "statut": str(f.statut), "motif": f.motif_refus,
                          "mime": f.type_mime, "pages": f.nombre_pages} for f in prep.fichiers.values()],
            "non_lus": [{"fichier": n.fichier, "motif": n.motif} for n in prep.non_lus],
            "documents": sorted(str(d.type) for d in prep.documents.values()),
            "dossiers": len(res),
            "pages": len(pages),
            "qualites": sorted({str(p.qualite_texte) for p in pages}),
            "avertissements": sorted(set(prep.avertissements))[:30],
        })
        code = 0
    except BaseException as e:  # précisément ce que la campagne cherche
        bilan.update({"ok": False, "exception": type(e).__name__, "trace": traceback.format_exc()[-4000:]})
        code = 2
    bilan["duree_s"] = round(time.monotonic() - debut, 2)
    sortie.write_text(json.dumps(bilan, ensure_ascii=False, indent=1), "utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
