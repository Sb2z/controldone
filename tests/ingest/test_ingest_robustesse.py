"""Robustesse (docs/ROBUSTESSE.md, D-1600 à D-1606) : régressions de la campagne d'entrées hostiles.

Chaque test reproduit, avec une fixture minuscule générée ici, un défaut trouvé par ``scripts/fuzz/`` :
le fichier finit refusé avec un motif, traité, ou listé non lu ; jamais une exception qui emporte le lot.
"""

from __future__ import annotations

import base64
import io
import logging
import zipfile

import fabriques as fab
import pytest

from controldone.ingest import Limites, MotifRefus, recevoir_courriel, recevoir_octets
from controldone.model import StatutFichier
from controldone.model.referentiel import Client

PDF = fab.pdf([fab.FACTURE_COMMERCIALE])


def _motifs(rec) -> dict[str, str | None]:
    return {f.fichier.chemin_relatif: f.fichier.motif_refus for f in rec.fichiers}


def _zip(entrees: dict[str, bytes]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, donnees in entrees.items():
            z.writestr(nom, donnees)
    return b.getvalue()


# --- D-1600 : archives -----------------------------------------------------------------------------------


def test_d1600_flux_deflate_altere_refuse_l_entree_sans_perdre_le_lot():
    contenu = bytearray(_zip({"a.pdf": PDF, "b.pdf": fab.pdf([["autre FICTIF"]])}))
    debut = contenu.find(b"PK\x03\x04") + 30 + len("a.pdf")
    contenu[debut + 40:debut + 80] = b"\xff" * 40  # flux compressé de a.pdf altéré : zlib.error à la lecture
    rec = recevoir_octets([("envoi.zip", bytes(contenu)), ("seul.pdf", PDF)])
    m = _motifs(rec)
    assert m["envoi/a.pdf"] == MotifRefus.corrompu
    assert m["envoi/b.pdf"] is None and m["seul.pdf"] is None


@pytest.mark.parametrize("entrees", [{}, {"a/": b"", "a/b/": b""}])
def test_d1600_archive_sans_fichier_refusee_vide(entrees):
    rec = recevoir_octets([("vide.zip", _zip(entrees))])
    assert [(f.fichier.chemin_relatif, f.fichier.motif_refus) for f in rec.fichiers] == [
        ("vide.zip", MotifRefus.vide)]


def test_d1600_erreur_imprevue_d_un_analyseur_refuse_le_fichier_seulement(monkeypatch):
    from controldone.ingest import reception

    def panne(*_a, **_k):
        raise RuntimeError("analyseur en panne")

    monkeypatch.setattr(reception, "_compter_pages_pdf", panne)
    rec = recevoir_octets([("a.pdf", PDF), ("b.csv", b"numero;montant\nINV-1;10,00\nINV-2;12,00\n")])
    m = _motifs(rec)
    assert m["a.pdf"] == MotifRefus.corrompu and m["b.csv"] is None


def test_d1601_pypdf_ne_journalise_pas_d_extraits_de_document(caplog):
    import controldone.ingest.reception  # noqa: F401  (le réglage est fait à l'import)

    assert logging.getLogger("pypdf").getEffectiveLevel() >= logging.CRITICAL
    casse = PDF.replace(b"/Root", b"/Rxxt").replace(b"xref", b"xrxf")
    with caplog.at_level(logging.DEBUG):
        recevoir_octets([("casse.pdf", casse)])
    assert not [r for r in caplog.records if r.name.startswith("pypdf")]


# --- D-1602 : classeurs ----------------------------------------------------------------------------------


def _xlsx_avec_feuille(feuille: bytes) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active["A1"] = "FICTIF"
    b = io.BytesIO()
    wb.save(b)
    src = zipfile.ZipFile(io.BytesIO(b.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for i in src.infolist():
            z.writestr(i.filename, feuille if i.filename == "xl/worksheets/sheet1.xml" else src.read(i.filename))
    return out.getvalue()


def test_d1602_bombe_xlsx_refusee_comme_une_archive():
    feuille = (b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
               + b" " * (3 * 1024 * 1024) + b"</sheetData></worksheet>")  # 3 Mo, taux > 1 000
    rec = recevoir_octets([("bombe.xlsx", _xlsx_avec_feuille(feuille))])
    assert rec.fichiers[0].fichier.motif_refus == MotifRefus.archive_dangereuse
    limite = recevoir_octets([("gros.xlsx", _xlsx_avec_feuille(feuille))],
                             limites=Limites(zip_taille_totale=1024 * 1024, zip_ratio=10_000))
    assert limite.fichiers[0].fichier.motif_refus == MotifRefus.archive_dangereuse
    normal = recevoir_octets([("ok.xlsx", _xlsx_avec_feuille(b'<worksheet xmlns="http://schemas.openxmlformats.org/'
                                                             b'spreadsheetml/2006/main"><sheetData/></worksheet>'))])
    assert normal.fichiers[0].fichier.statut is StatutFichier.ok


# --- D-1603 : courriels ------------------------------------------------------------------------------------


def _eml_multipart(n: str, pieces: list[tuple[str, str, bytes]]) -> bytes:
    corps = b"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nBonjour FICTIF\r\n"
    for nom, ctype, donnees in pieces:
        corps += (f"--B\r\nContent-Type: {ctype}; name=\"{nom}\"\r\nContent-Transfer-Encoding: base64\r\n"
                  f"Content-Disposition: attachment; filename=\"{nom}\"\r\n\r\n").encode()
        corps += base64.encodebytes(donnees) + b"\r\n"
    corps += b"--B--\r\n"
    return (f"From: transitaire@exemple.invalid\r\nMessage-ID: <{n}@exemple.invalid>\r\nMIME-Version: 1.0\r\n"
            "Content-Type: multipart/mixed; boundary=\"B\"\r\n\r\n").encode() + corps


def test_d1603_message_joint_en_base64_n_est_pas_perdu():
    interne = _eml_multipart("in", [("facture.pdf", "application/pdf", PDF)])
    externe = _eml_multipart("out", [("transfert.eml", "message/rfc822", interne)])
    rec = recevoir_octets([("courriel.eml", externe)])
    chemins = {f.fichier.chemin_relatif: f.fichier for f in rec.fichiers}
    assert "courriel/transfert/facture.pdf" in chemins
    assert chemins["courriel/transfert/facture.pdf"].statut is StatutFichier.ok
    # le corps du message externe ne contient pas le message joint encodé
    corps = next(f for f in rec.fichiers if f.fichier.chemin_relatif == "courriel.eml")
    assert len(corps.contenu or b"") < 2000


def test_d1603_imbrication_courriel_archive_bornee():
    contenu = _eml_multipart("p0", [("f.pdf", "application/pdf", PDF)])
    for i in range(4):  # courriel -> zip -> courriel -> zip …
        contenu = _zip({f"c{i}.eml": contenu}) if i % 2 == 0 else _eml_multipart(
            f"p{i}", [(f"z{i}.zip", "application/zip", contenu)])
    rec = recevoir_octets([("envoi.zip", contenu)], limites=Limites(zip_profondeur=2))
    motifs = {f.fichier.motif_refus for f in rec.fichiers}
    assert MotifRefus.archive_dangereuse in motifs
    assert not any(f.fichier.chemin_relatif.endswith("f.pdf") and f.fichier.statut is StatutFichier.ok
                   for f in rec.fichiers)


def _imbrique(n: int) -> bytes:
    corps = b""
    for i in range(n):
        corps += f"--N{i}\r\nContent-Type: multipart/mixed; boundary=\"N{i + 1}\"\r\n\r\n".encode()
    corps += f"--N{n}\r\nContent-Type: text/plain\r\n\r\nfond\r\n--N{n}--\r\n".encode()
    for i in reversed(range(n)):
        corps += f"--N{i}--\r\n".encode()
    return (b"From: transitaire@exemple.invalid\r\nMIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="N0"\r\n\r\n' + corps)


def test_d1603_multipart_trop_imbrique_refuse_sans_exception():
    rec = recevoir_octets([("m.eml", _imbrique(60))])
    assert [f.fichier.motif_refus for f in rec.fichiers] == [MotifRefus.corrompu]
    client = Client(id="cli_x", raison_sociale="FICTIF", expediteurs_autorises=["@exemple.invalid"])
    rec2 = recevoir_courriel(_imbrique(60), client=client)
    assert [f.fichier.motif_refus for f in rec2.fichiers] == [MotifRefus.corrompu]
    assert recevoir_octets([("m.eml", _imbrique(10))]).fichiers[0].fichier.statut is StatutFichier.ok


# --- D-1604 : texte positionné et tableurs bornés ------------------------------------------------------------


def test_d1604_texte_positionne_borne_texte_complet(monkeypatch):
    from controldone.ingest import pages

    monkeypatch.setattr(pages, "MAX_LIGNES_POSITIONNEES", 50)
    contenu = "\n".join(f"<l>FICTIF {i}</l>" for i in range(500)).encode()
    p = pages._page_texte_brut(contenu, "xml")
    assert len(p.lignes) == 50 and p.texte.count("\n") == 499
    assert "texte_positionne_tronque" in p.avertissements
    csv = pages._page_csv("\n".join(f"L{i};{i},00" for i in range(500)).encode())
    assert len(csv.lignes) == 50 and "L499;499,00" in csv.texte
    monkeypatch.setattr(pages, "MAX_MOTS_POSITIONNES", 100)
    une_ligne = pages._page_texte_brut(b"1 250,00 " * 1000, "texte")
    assert sum(len(li.mots) for li in une_ligne.lignes) <= 100
    petit = pages._page_texte_brut(b"Facture FICTIVE\nTotal 10,00", "texte")
    assert len(petit.lignes) == 2 and petit.avertissements == []


def test_d1604_feuille_aux_dimensions_aberrantes_lue_bornee(monkeypatch):
    from controldone.ingest import pages

    feuille = (b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               b'<dimension ref="A1:XFD1048576"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>FICTIF</t>'
               b'</is></c></row><row r="3000"><c r="XFD3000"><v>1</v></c></row></sheetData></worksheet>')
    monkeypatch.setattr(pages, "MAX_CELLULES_FEUILLE", 50_000)
    sortie = pages._pages_xlsx(_xlsx_avec_feuille(feuille))
    assert sortie[0].texte.startswith("FICTIF")
    assert "tableur_tronque" in sortie[0].avertissements
    assert max((len(li.mots) for li in sortie[0].lignes), default=0) <= pages.MAX_COLONNES_TABLEUR


# --- D-1605 : rognages du rapport bornés en pixels -----------------------------------------------------------


def test_d1605_rognage_page_geante_borne_en_pixels(monkeypatch, tmp_path):
    import pypdfium2 as pdfium

    from controldone.rapport import images

    chemin = tmp_path / "geant.pdf"
    chemin.write_bytes(fab.pdf([fab.FACTURE_COMMERCIALE]).replace(b"/MediaBox [ 0 0 595.2756 841.8898 ]",
                                                                    b"/MediaBox [ 0 0 14400 14400 ]"))
    original = pdfium.PdfPage.render
    demandes = []

    def espion(self, *a, scale=1, **kw):
        w, h = self.get_size()
        demandes.append((w, h))
        assert w * h * scale * scale <= images.MAX_PIXELS, "bitmap démesuré demandé à pdfium"
        return original(self, *a, scale=scale, **kw)

    monkeypatch.setattr(pdfium.PdfPage, "render", espion)
    images.vider_cache()
    images.rogner(str(chemin), 1, zone=(0.1, 0.1, 0.3, 0.12))
    images.vider_cache()
    assert demandes and demandes[0][0] > 10_000
    assert images._echelle(595, 842) == images.ECHELLE  # page A4 : rendu inchangé


# --- D-1606 : non-lus d'un lot sans dossier -----------------------------------------------------------------


def test_d1606_lot_sans_dossier_liste_ses_fichiers_non_lus():
    from controldone.jobs.handlers import _non_lus
    from controldone.pipeline import NonLu

    fichiers = [("fic_1", "envoi/a.pdf", "a.pdf", "sha1", "sha1"), ("fic_2", "b.xml", "b.xml", None, "sha2")]
    assert _non_lus([], fichiers) == [{"fichier": "envoi/a.pdf", "motif": "aucun_dossier"}]

    class Rd:
        def __init__(self):
            self.non_lus = [NonLu(fichier="a.pdf", motif="document_non_reconnu"),
                            NonLu(fichier="z", motif="refuse:vide")]

    assert _non_lus([Rd(), Rd()], fichiers) == [{"fichier": "a.pdf", "motif": "document_non_reconnu"}]


# --- D-1607 : étape 3 bornée sur une page démesurée -----------------------------------------------------------


def _decouper(nom: str, contenu: bytes):
    from controldone.ingest.decoupage import decouper_fichier
    from controldone.ingest.pages import OptionsPages

    fichier = recevoir_octets([(nom, contenu)]).fichiers[0].fichier
    return decouper_fichier(fichier, contenu, options=OptionsPages(isoler=False, ocr=False))


def test_d1607_xml_a_millions_d_elements_sans_arbre_structure(monkeypatch):
    from controldone.ingest import decoupage

    appels = []
    monkeypatch.setattr(decoupage, "analyser_contenu_structure", lambda *a, **k: appels.append(1))
    monkeypatch.setattr(decoupage, "MAX_BALISES_STRUCTURE", 100)
    gros = ("<r>" + "".join(f"<l>FICTIF {i}</l>" for i in range(200)) + "</r>").encode()
    res = _decouper("gros.xml", gros)
    assert appels == [] and "structure_non_analysee:trop_d_elements" in res.avertissements
    assert res.documents  # classé comme un XML de format inconnu : listé, jamais perdu
    _decouper("petit.xml", b"<r><l>FICTIF</l></r>")
    assert appels == [1]  # XML ordinaire : analyse structurée inchangée


def test_d1607_classement_sur_extrait_texte_complet_conserve(monkeypatch):
    from controldone.ingest import decoupage

    vus = []
    original = decoupage.classer_page

    def espion(page, **kw):
        vus.append((len(page.texte), max((len(li.texte) for li in page.lignes), default=0), page.avertissements))
        return original(page, **kw)

    monkeypatch.setattr(decoupage, "classer_page", espion)
    monkeypatch.setattr(decoupage, "MAX_CARACTERES_CLASSEMENT", 500)
    monkeypatch.setattr(decoupage, "MAX_CARACTERES_LIGNE_CLASSEMENT", 100)
    texte = ("FACTURE FICTIVE " * 400).encode()  # une seule ligne de 6 400 caractères
    res = _decouper("long.xml", b"<r>" + texte + b"</r>")
    (n_texte, n_ligne, avert), = vus
    assert n_texte <= 500 and n_ligne <= 100 and "classement_sur_extrait" in avert
    assert len(res.textes[1].texte) > 6000  # texte de la page intact
    vus.clear()
    _decouper("court.xml", b"<r>FACTURE FICTIVE</r>")
    assert vus and "classement_sur_extrait" not in vus[0][2]
