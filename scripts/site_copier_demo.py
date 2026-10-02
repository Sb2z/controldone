"""Copie le rapport de démonstration (données fictives) dans le site public.

Usage :
    source .venv/bin/activate && controldone demo     # régénère var/demo/
    python scripts/site_copier_demo.py                # copie dans site/demo/ avec le bandeau

Le rapport copié reçoit un bandeau fixe « DONNÉES FICTIVES » et un lien de retour vers le site.
Refuse de copier un rapport qui ne se déclare pas fictif.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SOURCE = RACINE / "var" / "demo"
CIBLE = RACINE / "site" / "demo"

BANDEAU = """
<style>
.cd-site-fictif { position: sticky; top: 0; z-index: 1000; background: #b42318; color: #fff;
  font: 700 14px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; letter-spacing: .06em;
  padding: 10px 16px; text-align: center; }
.cd-site-fictif a { color: #fff; font-weight: 600; letter-spacing: 0; margin-left: 12px; }
@media print { .cd-site-fictif { display: none; } }
</style>
<div class="cd-site-fictif" role="note">DONNÉES FICTIVES — exemple de rapport ControlDOne : aucune société, aucun
transitaire, aucun montant n'est réel.<a href="../demonstration.html" target="_top">Retour au site</a></div>
"""


def main() -> int:
    rapport = SOURCE / "report.html"
    if not rapport.exists():
        print("var/demo/report.html absent : lancer d'abord `controldone demo`.", file=sys.stderr)
        return 1
    html = rapport.read_text(encoding="utf-8")
    if "FICTIVES" not in html.upper() and "FICTIF" not in html.upper():
        print("Le rapport ne se déclare pas fictif : copie refusée.", file=sys.stderr)
        return 1
    if "cd-site-fictif" not in html:
        html = html.replace("<body>", "<body>" + BANDEAU, 1)
    CIBLE.mkdir(parents=True, exist_ok=True)
    (CIBLE / "report.html").write_text(html, encoding="utf-8")
    shutil.copyfile(SOURCE / "report.pdf", CIBLE / "report.pdf")
    print(f"copié : {CIBLE / 'report.html'}, {CIBLE / 'report.pdf'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
