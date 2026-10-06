"""Cycle complet d'une facture du fondateur : brouillon -> approbation -> émission Factur-X -> dépôt PA ;
coupon de lancement ; avoir ; garde-fous (production, vendeur incomplet)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import facturx
import pytest
from aides_facturation import FONDATEUR, SYSTEME, approuver

from controldone.facturation import Consentement, CouponRefuse, EmissionRefusee, ServiceFacturation
from controldone.guardrails import check_text
from controldone.outbox import FileSortante, StatutAction
from controldone.storage import facturation as stock

LE = date(2026, 10, 2)
SIGNE = Consentement(signe=True, signe_par="M. FICTIF", signe_le="2026-10-01", reference_document="accord-FICTIF.pdf")


def test_brouillon_puis_emission_et_depot(service, db, pa, tmp_path):
    a = service.proposer_diagnostic("cli_a", FONDATEUR, references={"lot_id": "lot_x"})
    assert a.statut is StatutAction.brouillon and a.kind.value == "facture_emise"
    p = a.payload
    assert p["total_ht"] == "390.00" and p["total_tva"] == "78.00" and p["total_ttc"] == "468.00"
    assert p["destinataires"] == ["compta@client-a-fictif.test"] and check_text(p["corps"]) == []
    assert service.proposer_diagnostic("cli_a", FONDATEUR).id == a.id  # idempotent
    approuver(db, a.id)
    f = service.emettre_et_deposer(a.id, FONDATEUR, le=LE)
    assert f.numero == "F-2026-0001" and f.total_ttc == Decimal("468.00") and f.client_id == "cli_a"
    assert f.contenu["controles_reforme"] == [] and f.contenu["vendeur_complet"] is True
    _nom, xml = facturx.get_xml_from_pdf(f.pdf, check_xsd=True)
    assert b"F-2026-0001" in xml and xml.decode() == f.xml
    envoyee = FileSortante(db).obtenir(a.id, FONDATEUR)
    assert envoyee.statut is StatutAction.envoye and envoyee.reference_envoi.startswith("pa:pa_bouchon:")
    assert (pa.racine / "deposees" / "PA-BOUCHON-F-2026-0001.pdf").read_bytes() == f.pdf
    copie = tmp_path / "sorties" / "facture_emise" / "F-2026-0001.pdf.enc"  # chiffrée au repos (D-4106)
    from controldone.storage.traces_envoi import TracesEnvoi

    assert TracesEnvoi.depuis_env(tmp_path / "sorties").lire(copie) == f.pdf and f.pdf not in copie.read_bytes()
    assert not (tmp_path / "sorties" / "facture_emise" / "F-2026-0001.pdf").exists()
    assert [s.code for s in stock.statuts_pa(db, facture_id=f.id)] == ["200"]
    # relancer ne crée ni nouveau numéro ni nouveau dépôt
    assert service.emettre_et_deposer(a.id, FONDATEUR, le=LE).id == f.id and len(stock.factures(db)) == 1


def test_brouillon_existant_de_l_agent_repris_avec_tva(service, db):
    from controldone.litiges import LigneFacture, payload_facture

    payload = payload_facture("commission", [LigneFacture("Commission de 20 % sur avoir FICTIF", Decimal("48.00"))],
                              destinataires=["compta@client-a-fictif.test"], raison_sociale="CLIENT A FICTIF SAS")
    a = FileSortante(db).proposer("facture_emise", payload, SYSTEME, tenant_id="cli_a", idempotency_key="commission:x")
    approuver(db, a.id)
    f = service.emettre(a.id, FONDATEUR, le=LE)
    assert (f.total_ht, f.total_tva, f.total_ttc) == (Decimal("48.00"), Decimal("9.60"), Decimal("57.60"))


def test_commission_et_abonnement(service, db):
    c = service.proposer_commission("cli_a", FONDATEUR, base=Decimal("300.00"), avoir_id="av_FICTIF_1")
    assert c.payload["total_ht"] == "60.00" and c.idempotency_key == "commission:cli_a:av_FICTIF_1"
    ab = service.proposer_abonnement("cli_b", FONDATEUR, palier="pro", mois="2026-10")
    assert ab.payload["total_ht"] == "199.00" and ab.idempotency_key == "facture:abonnement:cli_b:2026-10"
    approuver(db, ab.id)
    f = service.emettre(ab.id, FONDATEUR, le=LE)
    assert f.contenu["acheteur"]["livraison_ligne"].startswith("Entrepôt FICTIF")
    assert b"ShipToTradeParty" in f.xml.encode()
    with pytest.raises(ValueError):
        service.proposer_abonnement("cli_b", FONDATEUR, palier="pro", mois="octobre")


def test_coupon_de_lancement(service, db):
    emises = []
    # D-1313 : remise sans aucun accord de publication (cli_a) ; l'accord, s'il existe, est seulement cité
    for cid, consentement in (("cli_a", None), ("cli_c0", SIGNE), ("cli_c1", SIGNE)):
        a = service.proposer_diagnostic(cid, FONDATEUR, coupon="LANCEMENT-3-DIAGNOSTICS", consentement=consentement)
        fx = a.payload["facturation"]["coupon"]
        assert a.payload["total_ttc"] == "0.00" and fx["accord_publication_condition"] is False
        assert ("consentement" in fx) is (consentement is not None)
        if consentement is not None:
            assert fx["consentement"]["signe"] and fx["consentement"]["revocable"]
        approuver(db, a.id)
        emises.append(service.emettre(a.id, FONDATEUR, le=LE))
    assert [f.total_ttc for f in emises] == [Decimal("0.00")] * 3
    assert all(b"AllowanceTotalAmount>390.00<" in f.xml.encode() for f in emises)
    us = stock.coupon_utilisations(db, "LANCEMENT-3-DIAGNOSTICS")
    assert len(us) == 3 and us[0].consentement == {} and us[1].consentement["reference_document"] == "accord-FICTIF.pdf"
    with pytest.raises(CouponRefuse, match="épuisé"):  # quatrième diagnostic gratuit
        service.proposer_diagnostic("cli_c2", FONDATEUR, coupon="LANCEMENT-3-DIAGNOSTICS", consentement=SIGNE)
    with pytest.raises(CouponRefuse):  # même client
        service.proposer_diagnostic("cli_a", FONDATEUR, coupon="LANCEMENT-3-DIAGNOSTICS", consentement=SIGNE)


def test_coupon_reverifie_a_l_emission(service, db):
    """Deux brouillons créés avant l'épuisement : le quota est revérifié sous verrou à l'émission."""
    brouillons = [service.proposer_diagnostic(c, FONDATEUR, coupon="LANCEMENT-3-DIAGNOSTICS", consentement=SIGNE)
                  for c in ("cli_a", "cli_b", "cli_c0", "cli_c1")]
    for a in brouillons:
        approuver(db, a.id)
    for a in brouillons[:3]:
        service.emettre(a.id, FONDATEUR, le=LE)
    with pytest.raises(CouponRefuse, match="épuisé"):
        service.emettre(brouillons[3].id, FONDATEUR, le=LE)
    assert len(stock.factures(db)) == 3 and stock.factures(db)[-1].numero == "F-2026-0003"  # pas de trou


def test_avoir(service, db):
    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    f = service.emettre(a.id, FONDATEUR, le=LE)
    with pytest.raises(ValueError):
        service.proposer_avoir(f.id, FONDATEUR, motif="")
    with pytest.raises(EmissionRefusee):
        service.proposer_avoir(f.id, FONDATEUR, motif="trop", montant_ht=Decimal("400"))
    av = service.proposer_avoir(f.id, FONDATEUR, motif="Erreur de quantité FICTIVE", montant_ht=Decimal("90.00"))
    approuver(db, av.id)
    fa = service.emettre(av.id, FONDATEUR, le=LE)
    assert fa.numero == "AV-2026-0001" and fa.type_code == "381" and fa.facture_origine_id == f.id
    assert fa.total_ht == Decimal("-90.00") and fa.total_ttc == Decimal("-108.00")
    assert "<ram:IssuerAssignedID>F-2026-0001</ram:IssuerAssignedID>" in fa.xml
    with pytest.raises(EmissionRefusee):  # 90 + 301 > 390
        service.proposer_avoir(f.id, FONDATEUR, motif="reste", montant_ht=Decimal("301.00"))
    reste = service.proposer_avoir(f.id, FONDATEUR, motif="Annulation du reste FICTIVE")
    assert reste.payload["total_ht"] == "300.00"
    assert stock.facture(db, f.id).total_ht == Decimal("390.00")  # la facture d'origine est inchangée


def test_production_refuse_vendeur_incomplet(db, catalogue, pa, bouchon):
    from controldone.facturation.offres import Vendeur

    prod = ServiceFacturation(db, catalogue=replace(catalogue, vendeur=Vendeur()), pa=pa, paiement=bouchon, prod=True)
    a = prod.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    with pytest.raises(EmissionRefusee, match="incomplète"):
        prod.emettre(a.id, FONDATEUR, le=LE)
    assert stock.factures(db) == []
    dev = ServiceFacturation(db, catalogue=replace(catalogue, vendeur=Vendeur()), pa=pa, paiement=bouchon, prod=False)
    f = dev.emettre(a.id, FONDATEUR, le=LE)
    assert f.contenu["vendeur_complet"] is False and f.numero == "F-2026-0001"


def test_emission_reservee_au_fondateur(service, db):
    from controldone.storage import AccesRefuse

    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    with pytest.raises(AccesRefuse):
        service.emettre(a.id, SYSTEME)


def test_approbation_web_declenche_emission(service, db, monkeypatch):
    """``publication.mettre_a_disposition`` (appelé après l'approbation du fondateur) émet et dépose."""
    from controldone.services import publication

    class _Pf:
        pass

    pf = _Pf()
    pf.db, pf.facturation, pf.dossier_sorties = db, service, None
    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    publication.mettre_a_disposition(pf, a.id, FONDATEUR)  # type: ignore[arg-type]
    assert stock.facture_par_outbox(db, a.id) is not None
    assert FileSortante(db).obtenir(a.id, FONDATEUR).statut is StatutAction.envoye
