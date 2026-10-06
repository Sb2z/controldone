"""Table des taux de référence (§8.7) : conversion du fichier historique de la BCE (D-806). Données fictives."""

import io
import zipfile
from datetime import date
from decimal import Decimal

from controldone.taux_reference import TableTauxReference, convertir_historique_bce

HIST = (
    "Date,USD,JPY,XXX,\n"
    "2026-08-14,1.1000,170.10,N/A,\n"
    "2026-08-13,1.0900,169.00,N/A,\n"
    "2025-12-31,1.0500,160.00,N/A,\n"
)


def test_conversion_format_large_vers_table(tmp_path):
    texte = convertir_historique_bce(HIST.encode(), depuis=date(2026, 1, 1))
    lignes = texte.strip().splitlines()
    assert lignes[0] == "date,devise,devise_par_eur"
    assert lignes[1:] == [
        "2026-08-13,JPY,169.00",
        "2026-08-13,USD,1.0900",
        "2026-08-14,JPY,170.10",
        "2026-08-14,USD,1.1000",
    ]  # N/A et dates anciennes écartés
    chemin = tmp_path / "taux_bce.csv"
    chemin.write_text(texte, encoding="utf-8")
    table = TableTauxReference.depuis_csv(chemin)
    assert table.devise_par_eur("USD", date(2026, 8, 16)) == Decimal(
        "1.1000"
    )  # week-end : dernière publication
    assert table.devise_par_eur("XXX", date(2026, 8, 14)) is None


def test_conversion_depuis_archive_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("eurofxref-hist.csv", HIST)
    assert "2025-12-31,USD,1.0500" in convertir_historique_bce(buf.getvalue())
