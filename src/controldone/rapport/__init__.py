"""Rapport de diagnostic (SPEC §18) : HTML (Jinja2), PDF (ReportLab), JSON et tableur XLSX.

    from controldone.rapport import generer_rapport
    sorties = generer_rapport(resultats, profil, "var/rapport")
    # {"html": Path, "pdf": Path, "json": Path, "xlsx": Path, "findings": Path}

Chaque texte produit passe le filtre des formulations interdites (§3.2) : ``generer_rapport`` contrôle le
texte visible du HTML et lève ``FormulationInterdite`` si une expression interdite y figure (un libellé de
constat bloqué est déjà remplacé par une mention neutre dans la vue).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from controldone.guardrails import FormulationInterdite, check_text
from controldone.pipeline import NonLu, ResultatDossier
from controldone.rapport.export import ecrire_xlsx, findings_lot_json, rapport_json
from controldone.rapport.html import rendre_html, texte_visible
from controldone.rapport.images import rogner, vider_cache
from controldone.rapport.pdf import rendre_pdf
from controldone.rapport.vue import RapportVue, construire_vue
from controldone.referentiel_io import ProfilClient

__all__ = [
    "SortiesRapport", "ajouter_images", "construire_vue", "generer_rapport", "rendre_html", "rendre_pdf",
    "verifier_textes",
]


@dataclass
class SortiesRapport:
    html: Path
    pdf: Path
    json: Path
    xlsx: Path
    findings: Path
    vue: RapportVue

    def __getitem__(self, cle: str) -> Path:
        return getattr(self, cle)


def ajouter_images(vue: RapportVue) -> int:
    """Rognages de page des preuves (si le fichier source est disponible). Retourne le nombre d'images."""
    n = 0
    for c in [*vue.constats(), *vue.renvois]:
        for p in c.preuves:
            if p.image is not None or not p.chemin_local or not p.page:
                continue
            p.image = rogner(p.chemin_local, p.page, zone=p.zone, valeur=p.valeur_lue, type_mime=p.type_mime)
            n += p.image is not None
    return n


def verifier_textes(vue: RapportVue, html: str) -> None:
    violations = check_text(texte_visible(html))
    if violations:
        raise FormulationInterdite(violations)


def generer_rapport(
    resultats: Sequence[ResultatDossier],
    profil: ProfilClient,
    dossier_sortie: Path | str,
    *,
    titre: str = "Rapport de diagnostic",
    date_rapport: date | None = None,
    horodatage: datetime | None = None,
    non_lus: Sequence[NonLu] | None = None,
    images: bool = True,
) -> SortiesRapport:
    """Écrit ``report.html``, ``report.pdf``, ``report.json``, ``findings.json`` et ``findings.xlsx``."""
    out = Path(dossier_sortie)
    out.mkdir(parents=True, exist_ok=True)
    vue = construire_vue(resultats, profil, titre=titre, date_rapport=date_rapport, non_lus=non_lus)
    if images:
        try:
            ajouter_images(vue)
        finally:
            vider_cache()  # pages rendues : ~9 Mo chacune, jamais réutilisées par un autre rapport (D-1406)
    html = rendre_html(vue)
    verifier_textes(vue, html)
    (out / "report.html").write_text(html, encoding="utf-8")
    (out / "report.pdf").write_bytes(rendre_pdf(vue, horodatage=horodatage))
    (out / "report.json").write_text(
        json.dumps(rapport_json(vue, resultats), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lot = findings_lot_json(resultats)
    (out / "findings.json").write_text(
        json.dumps(lot[0] if len(lot) == 1 else lot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ecrire_xlsx(vue, resultats, out / "findings.xlsx")
    return SortiesRapport(html=out / "report.html", pdf=out / "report.pdf", json=out / "report.json",
                          xlsx=out / "findings.xlsx", findings=out / "findings.json", vue=vue)
