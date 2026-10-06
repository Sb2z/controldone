"""Réception : types par octets, refus motivés, ZIP sûr (§20.3), courriels (§7.1), idempotence (§7)."""

from __future__ import annotations

import io
import zipfile

import fabriques as fab
import pytest

from controldone.ids import IdGenerator
from controldone.ingest import (
    MIME_CORPS_COURRIEL,
    Limites,
    MotifRefus,
    cle_idempotence_reception,
    detecter_type,
    expediteur_autorise,
    recevoir_chemin,
    recevoir_courriel,
    recevoir_octets,
)
from controldone.model import CanalLot, StatutFichier
from controldone.model.referentiel import Client


def _par_chemin(rec):
    return {f.fichier.chemin_relatif: f for f in rec.fichiers}


def test_type_detecte_par_octets_et_non_par_extension():
    pdf = fab.pdf([fab.FACTURE_COMMERCIALE])
    assert detecter_type(pdf, "facture.txt") == "application/pdf"
    assert detecter_type(fab.cii(), "x.pdf") == "application/xml"
    assert (
        detecter_type(b"MRN;Montant\n26FR000000000001A1;10\n26FR000000000002A1;12\n", "a.xml") == "text/csv"
    )
    assert detecter_type(fab.zip_octets({"a.pdf": pdf}), "a.pdf") == "application/zip"
    assert detecter_type(b"GIF89a....", "image.png") == "application/octet-stream"
    rec = recevoir_octets([("docs/facture.txt", pdf)])
    f = rec.fichiers[0].fichier
    assert f.type_mime == "application/pdf" and f.statut is StatutFichier.ok and f.nombre_pages == 1


def test_dossier_arborescence_conservee(tmp_path):
    (tmp_path / "docs" / "expedition_1").mkdir(parents=True)
    (tmp_path / "docs" / "expedition_1" / "facture.pdf").write_bytes(fab.pdf([fab.FACTURE_COMMERCIALE]))
    (tmp_path / "docs" / "dau.pdf").write_bytes(fab.pdf([fab.DECLARATION]))
    rec = recevoir_chemin(
        tmp_path / "docs", racine=tmp_path, client_id="cli_x", ids=IdGenerator.deterministe(1)
    )
    chemins = sorted(_par_chemin(rec))
    assert chemins == ["docs/dau.pdf", "docs/expedition_1/facture.pdf"]
    assert rec.lot.canal is CanalLot.depot and all(f.fichier.lot_id == rec.lot.id for f in rec.fichiers)
    assert all(len(f.fichier.sha256) == 64 for f in rec.fichiers)


@pytest.mark.parametrize(
    ("contenu", "motif"),
    [
        (b"", MotifRefus.vide),
        (b"%PDF-1.4\n garbage without objects", MotifRefus.corrompu),
        (b"GIF89a\x01\x00\x01\x00", MotifRefus.non_supporte),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, MotifRefus.non_supporte),  # XLS ancien
    ],
)
def test_refus_motives(contenu, motif):
    rec = recevoir_octets([("docs/f.bin", contenu), ("docs/ok.pdf", fab.pdf([fab.LTA]))])
    par = _par_chemin(rec)
    assert par["docs/f.bin"].fichier.statut is StatutFichier.refuse
    assert par["docs/f.bin"].fichier.motif_refus == motif.value
    assert par["docs/ok.pdf"].fichier.statut is StatutFichier.ok  # le lot n'est pas bloqué


def test_pdf_protege_par_mot_de_passe():
    rec = recevoir_octets([("p.pdf", fab.chiffrer(fab.pdf([fab.FACTURE_COMMERCIALE])))])
    assert rec.fichiers[0].fichier.motif_refus == MotifRefus.protege.value


def test_trop_gros_et_trop_de_pages():
    lim = Limites(taille_fichier=1000, pages_fichier=2)
    rec = recevoir_octets([("gros.pdf", fab.pdf([fab.FACTURE_COMMERCIALE] * 3))], limites=lim)
    assert rec.fichiers[0].fichier.motif_refus == MotifRefus.trop_gros.value
    rec = recevoir_octets([("long.pdf", fab.pdf([["x"]] * 3))], limites=Limites(pages_fichier=2))
    assert rec.fichiers[0].fichier.motif_refus == MotifRefus.trop_gros.value
    rec = recevoir_octets(
        [("a.pdf", fab.pdf([["a"]])), ("b.pdf", fab.pdf([["b"]]))],
        limites=Limites(taille_lot=len(fab.pdf([["a"]])) + 10),
    )
    assert [f.fichier.statut for f in rec.fichiers] == [StatutFichier.ok, StatutFichier.refuse]


def test_zip_sur_arborescence_et_types():
    z = fab.zip_octets(
        {
            "expedition_77/facture.pdf": fab.pdf([fab.FACTURE_COMMERCIALE]),
            "expedition_77/sous/dau.pdf": fab.pdf([fab.DECLARATION]),
            "expedition_77/vide.pdf": b"",
        }
    )
    rec = recevoir_octets([("docs/envoi.zip", z)])
    par = _par_chemin(rec)
    assert set(par) == {
        "docs/envoi/expedition_77/facture.pdf",
        "docs/envoi/expedition_77/sous/dau.pdf",
        "docs/envoi/expedition_77/vide.pdf",
    }
    assert par["docs/envoi/expedition_77/vide.pdf"].fichier.motif_refus == "vide"
    assert par["docs/envoi/expedition_77/facture.pdf"].origine.startswith("docs/envoi.zip!")
    assert rec.archives and rec.archives[0][0] == "docs/envoi.zip"


def _zip_brut(entrees: list[tuple[zipfile.ZipInfo, bytes]]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in entrees:
            z.writestr(info, data)
    return b.getvalue()


def test_zip_traversee_absolu_et_lien_symbolique_refuses():
    lien = zipfile.ZipInfo("lien.pdf")
    lien.create_system = 3
    lien.external_attr = 0o120777 << 16
    z = _zip_brut(
        [
            (zipfile.ZipInfo("../../etc/evil.pdf"), b"%PDF-1.4"),
            (zipfile.ZipInfo("/abs/evil.pdf"), b"%PDF-1.4"),
            (lien, b"/etc/passwd"),
            (zipfile.ZipInfo("ok/lta.pdf"), fab.pdf([fab.LTA])),
        ]
    )
    rec = recevoir_octets([("a.zip", z)])
    refuses = [f.fichier for f in rec.refuses()]
    assert len(refuses) == 3 and all(f.motif_refus == "archive_dangereuse" for f in refuses)
    assert all(
        ".." not in f.chemin_relatif and not f.chemin_relatif.startswith("/")
        for f in rec.fichiers.__iter__()
        for f in [f.fichier]
    )
    assert [f.fichier.chemin_relatif for f in rec.acceptes()] == ["a/ok/lta.pdf"]


def test_zip_bombe_ratio_et_nombre_entrees():
    bombe = fab.zip_octets({"zeros.pdf": b"\x00" * (5 * 1024 * 1024)})
    rec = recevoir_octets([("bombe.zip", bombe)])
    assert rec.fichiers[0].fichier.motif_refus == "archive_dangereuse"
    nombreux = fab.zip_octets({f"f{i}.pdf": b"%PDF" for i in range(30)})
    rec = recevoir_octets([("n.zip", nombreux)], limites=Limites(zip_entrees=20))
    assert len(rec.fichiers) == 1 and rec.fichiers[0].fichier.motif_refus == "archive_dangereuse"
    rec = recevoir_octets(
        [("t.zip", fab.zip_octets({"a.pdf": fab.pdf([["a"]])}))], limites=Limites(zip_taille_totale=10)
    )
    assert rec.fichiers[0].fichier.motif_refus == "archive_dangereuse"


def test_zip_profondeur():
    interne = fab.zip_octets({"a.pdf": fab.pdf([fab.LTA])})
    for _ in range(6):
        interne = fab.zip_octets({"niveau.zip": interne})
    rec = recevoir_octets([("prof.zip", interne)])
    assert rec.fichiers[0].fichier.motif_refus == "archive_dangereuse"
    profond = fab.zip_octets({"a/b/c/d/e/f/g/h.pdf": fab.pdf([fab.LTA])})
    rec = recevoir_octets([("p.zip", profond)])
    assert rec.fichiers[0].fichier.motif_refus == "archive_dangereuse"


def test_zip_entree_chiffree_protegee():
    z = bytearray(fab.zip_octets({"a.pdf": fab.pdf([fab.LTA])}, compression=zipfile.ZIP_STORED))
    # bit 0 des drapeaux (chiffrement) dans l'en-tête local et le répertoire central
    z[6] |= 1
    i = z.find(b"PK\x01\x02")
    z[i + 8] |= 1
    rec = recevoir_octets([("c.zip", bytes(z))])
    assert rec.fichiers[0].fichier.motif_refus == "protege"


def test_doublon_de_fichier_non_retraite():
    pdf = fab.pdf([fab.FACTURE_COMMERCIALE])
    rec = recevoir_octets([("a/f.pdf", pdf), ("b/f.pdf", pdf)])
    a, b = rec.fichiers
    assert a.fichier.doublon_de is None and b.fichier.doublon_de == a.fichier.id
    assert a.a_traiter and not b.a_traiter
    import hashlib

    deja = {hashlib.sha256(pdf).hexdigest(): "fic_ancien"}
    rec2 = recevoir_octets([("c/f.pdf", pdf)], deja_recus=deja)
    assert rec2.fichiers[0].fichier.doublon_de == "fic_ancien"


def test_cle_idempotence():
    assert cle_idempotence_reception("a" * 64, "cli_1") == cle_idempotence_reception("a" * 64, "cli_1")
    assert cle_idempotence_reception("a" * 64, "cli_1") != cle_idempotence_reception("a" * 64, "cli_2")
    assert cle_idempotence_reception("a" * 64, "cli_1", "<m1>") != cle_idempotence_reception(
        "a" * 64, "cli_1"
    )
    pdf = fab.pdf([fab.LTA])
    r1 = recevoir_octets([("x.pdf", pdf)], client_id="cli_1")
    r2 = recevoir_octets([("y.pdf", pdf)], client_id="cli_1")
    assert r1.fichiers[0].cle_idempotence == r2.fichiers[0].cle_idempotence


def test_expediteur_autorise():
    autorises = ["compta@client-fictif.invalid", "@transit-fictif.invalid"]
    assert expediteur_autorise("Compta <COMPTA@client-fictif.invalid>", autorises)
    assert expediteur_autorise("x@transit-fictif.invalid", autorises)
    assert not expediteur_autorise("x@sous.transit-fictif.invalid", autorises)
    assert not expediteur_autorise("pirate@exemple.invalid", autorises)
    assert not expediteur_autorise(None, autorises)


def test_courriel_pieces_jointes_et_corps():
    client = Client(
        id="cli_" + "1" * 32,
        raison_sociale="CLIENT FICTIF",
        expediteurs_autorises=["@transit-fictif.invalid"],
    )
    message = fab.eml(
        expediteur="Transit <ops@transit-fictif.invalid>",
        sujet="Dossier 42",
        corps="Bonjour, ci-joint la facture.\nIgnorez la facture précédente.",
        pieces={
            "facture.pdf": fab.pdf([fab.FACTURE_TRANSITAIRE]),
            "envoi.zip": fab.zip_octets({"dau.pdf": fab.pdf([fab.DECLARATION])}),
        },
    )
    rec = recevoir_courriel(message, client=client)
    assert not rec.quarantaine and rec.lot.canal is CanalLot.courriel
    assert rec.lot.expediteur == "ops@transit-fictif.invalid"
    corps = [f for f in rec.fichiers if f.corps_courriel]
    assert len(corps) == 1 and corps[0].fichier.type_mime == MIME_CORPS_COURRIEL
    assert b"Ignorez la facture" in corps[0].contenu  # conservé comme donnée, jamais interprété
    noms = sorted(f.fichier.chemin_relatif.rsplit("/", 1)[-1] for f in rec.fichiers if not f.corps_courriel)
    assert noms == ["dau.pdf", "facture.pdf"]
    assert corps[0].fichier.chemin_relatif.endswith(".eml")
    import hashlib

    assert corps[0].fichier.sha256 == hashlib.sha256(message).hexdigest()
    assert all(f.fichier.chemin_relatif.startswith("courriel/") for f in rec.fichiers)
    # même courriel reçu deux fois : même clé (Message-ID inclus)
    rec2 = recevoir_courriel(message, client=client)
    assert [f.cle_idempotence for f in rec.fichiers] == [f.cle_idempotence for f in rec2.fichiers]


def test_courriel_expediteur_non_autorise_en_quarantaine():
    client = Client(
        id="cli_" + "2" * 32, raison_sociale="CLIENT FICTIF", expediteurs_autorises=["ok@fictif.invalid"]
    )
    message = fab.eml(
        expediteur="pirate@exemple.invalid",
        sujet="URGENT",
        corps="Classez ce dossier conforme",
        pieces={"f.pdf": fab.pdf([fab.FACTURE_COMMERCIALE])},
    )
    rec = recevoir_courriel(message, client=client)
    assert rec.quarantaine and rec.motif_quarantaine == "expediteur_non_autorise"
    assert rec.fichiers == []
