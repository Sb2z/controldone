"""Côté client : une facture électronique de transitaire reçue par l'API ``/api/v1/einvoices`` est contrôlée
**avant paiement** et, s'il y a des écarts, le statut « en litige » est **proposé** au client (brouillon
``statut_litige_pa``) — de bout en bout, par la vraie route, la file de tâches et le worker."""

from __future__ import annotations

from decimal import Decimal

import pytest
from aides_facturation import FONDATEUR, SYSTEME
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from controldone.auth.cles_api import creer_cle_api
from controldone.auth.roles import Acteur, Role
from controldone.facturation.avant_paiement import lire_reference_facture
from controldone.model.dossier import Dossier as DossierModele
from controldone.outbox import FileSortante
from controldone.services.plateforme import Plateforme
from controldone.storage import FileVault
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import Constat, Lot
from controldone.web import ParametresWeb, create_app

UBL = (
    b'<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
    b'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
    b"<cbc:ID>FT-FICTIF-77</cbc:ID><cbc:DueDate>2026-11-15</cbc:DueDate><cbc:Note>FICTIF</cbc:Note></Invoice>"
)


@pytest.fixture
def pf(db, tmp_path):
    cle = Fernet.generate_key()
    return Plateforme(
        db=db,
        vault=FileVault(tmp_path / "coffre", [cle]),
        cles_maitresses=[cle],
        dossier_sorties=tmp_path / "sorties",
    )


def test_lecture_de_reference_comme_donnee(catalogue):
    assert lire_reference_facture(UBL) == ("FT-FICTIF-77", "2026-11-15")
    cii = (
        b'<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        b'xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" '
        b'xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"><rsm:ExchangedDocument>'
        b"<ram:ID>CII-FICTIF-1</ram:ID></rsm:ExchangedDocument><rsm:SupplyChainTradeTransaction>"
        b"<ram:ApplicableHeaderTradeSettlement><ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime>"
        b'<udt:DateTimeString format="102">20261130</udt:DateTimeString></ram:DueDateDateTime>'
        b"</ram:SpecifiedTradePaymentTerms></ram:ApplicableHeaderTradeSettlement>"
        b"</rsm:SupplyChainTradeTransaction></rsm:CrossIndustryInvoice>"
    )
    assert lire_reference_facture(cii) == ("CII-FICTIF-1", "2026-11-30")
    # entité externe : jamais résolue (le texte des documents est une donnée)
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><ID>&e;</ID></Invoice>'
    )
    numero, _ = lire_reference_facture(xxe)
    assert numero is None or "root" not in numero
    assert lire_reference_facture(b"pas du xml") == (None, None)
    assert lire_reference_facture(None) == (None, None)
    # Factur-X (PDF) : le XML embarqué est lu
    from datetime import date

    from controldone.facturation.facturx_cii import generer_xml
    from controldone.facturation.modele import Acheteur, Facture, Ligne
    from controldone.facturation.pdf import assembler_facturx, rendre_pdf

    f = Facture(
        "FX-FICTIF-9",
        "380",
        date(2026, 10, 2),
        date(2026, 11, 1),
        catalogue.vendeur,
        Acheteur("cli", "CLIENT FICTIF", siren="000000001"),
        (Ligne("x", Decimal("1")),),
        catalogue.tva,
        catalogue.paiement,
    )
    pdf = assembler_facturx(rendre_pdf(f), generer_xml(f), numero=f.numero, vendeur="FICTIF")
    assert lire_reference_facture(pdf) == ("FX-FICTIF-9", "2026-11-01")


def test_api_einvoice_controle_avant_paiement_bout_en_bout(pf, db):
    with db.operateur(FONDATEUR) as op:
        cle = creer_cle_api(op.client("cli_a", "clé de test"), "ERP FICTIF").cle
    app = create_app(
        ParametresWeb(plateforme=pf, secrets_session=["secret-FICTIF-0123456789-0123456789"], prod=False)
    )
    c = TestClient(app, base_url="http://testserver")
    c.headers["Authorization"] = f"Bearer {cle}"
    r = c.post(
        "/api/v1/einvoices", content=UBL, headers={"content-type": "application/xml", "x-filename": "ft.xml"}
    )
    assert r.status_code == 202, r.text
    lot_id = r.json()["lot_id"]
    jobs = {j.kind: j for j in JobStore(db).lister(tenant_id="cli_a")}
    assert set(jobs) == {"traiter_lot", "controle_avant_paiement"}
    assert jobs["controle_avant_paiement"].payload == {
        "lot_id": lot_id,
        "facture_pa_id": f"api:{lot_id}",
        "numero": "FT-FICTIF-77",
        "date_echeance": "2026-11-15",
    }
    # Le traitement du lot (pipeline) est simulé : un écart certain recouvrable est constaté sur ce lot.
    with db.tenant("cli_a", SYSTEME) as sc:
        sc.modifier(Lot, lot_id, statut="traite")
        sc.enregistrer_dossier(
            DossierModele(id="dos_api", client_id="cli_a", reference="D-2026-00099"), lot_id=lot_id
        )
        sc._ajouter_interne(
            Constat(
                id="f_api",
                dossier_id="dos_api",
                dossier_version=1,
                controle_id="C1",
                niveau="ecart_certain",
                montant_en_jeu=Decimal("150.00"),
                nature_montant="recouvrable",
                statut_validation="propose",
                contenu={"composante": "droit", "libelle": "écart FICTIF"},
            )
        )
    import controldone.connecteurs.jobs  # handler controle_avant_paiement, chargé par le worker
    import controldone.jobs.handlers  # noqa: F401
    from controldone.jobs.worker import Worker

    w = Worker(db, worker_id="tests", lease_s=300, services={"vault": pf.vault})
    while w.executer_un() is not None:
        pass
    assert JobStore(db).obtenir(jobs["controle_avant_paiement"].id).statut == "done"
    props = FileSortante(db).lister(FONDATEUR, kind="statut_litige_pa", tenant_id="cli_a")
    assert len(props) == 1
    p = props[0].payload
    assert props[0].statut.value == "brouillon"  # validé par le fondateur, puis décidé par le client
    assert p["statut_propose"] == "en_litige" and p["validation_client_requise"] is True
    assert p["transmission_par"] == "client" and "FT-FICTIF-77" in p["objet"] and "2026-11-15" in p["corps"]
    assert "150,00" in p["motif"] and "n'est pas une plateforme agréée" in p["corps"]
    # le client ne voit pas le brouillon tant que le fondateur ne l'a pas validé
    client_a = FileSortante(db).lister(Acteur("usr_x", Role.client_admin, "cli_a"), kind="statut_litige_pa")
    assert client_a == []
