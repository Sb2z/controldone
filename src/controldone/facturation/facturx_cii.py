"""XML CII D16B (Factur-X 1.0x, profil EN 16931) d'une facture du fondateur, et validation XSD.

Ordre des éléments conforme au XSD Factur-X EN 16931 livré avec la bibliothèque ``factur-x``. Données
françaises de la réforme (vérifiées : impots.gouv.fr, « données de facture et correspondance des flux » ;
règles BR-FR du schématron « Flux 2 » livré avec ``factur-x`` 7.1) :

- BT-23 (cadre de facturation) = ``S1`` : prestation de services (catégorie de l'opération) ;
- BT-30 / BT-47 : SIREN du vendeur et de l'acheteur (``schemeID="0002"``) ;
- BT-34 / BT-49 : adresses électroniques (annuaire, ``schemeID="0225"``, commençant par le SIREN) ;
- notes BT-21/BT-22 : ``PMD`` (pénalités), ``PMT`` (indemnité de 40 EUR), ``AAB`` (escompte), ``TXD``
  (mention de taxe : franchise en base ou option sur les débits), ``BAR`` = ``B2B`` (traitement) ;
- BT-8 = ``5`` (date de facture) si option pour la TVA d'après les débits ;
- BT-75 à BT-80 : adresse de livraison si différente (``ShipToTradeParty``) ;
- avoir (381) : référence à la facture d'origine (BT-25, BT-26).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from lxml import etree

from controldone.facturation.modele import Facture, mentions_obligatoires

__all__ = ["NS", "controles_reforme", "generer_xml", "valider_xsd"]

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
_GUIDELINE = "urn:cen.eu:en16931:2017"


def _q(prefixe: str, nom: str) -> str:
    return f"{{{NS[prefixe]}}}{nom}"


def _el(parent: etree._Element, nom: str, texte: str | None = None, **attrs: str) -> etree._Element:
    p, n = nom.split(":")
    e = etree.SubElement(parent, _q(p, n), **attrs)
    if texte is not None:
        e.text = texte
    return e


def _m(x: Decimal) -> str:
    return f"{Decimal(x).quantize(Decimal('0.01')):f}"


def _d(parent: etree._Element, nom: str, d: date, prefixe: str = "udt") -> None:
    c = _el(parent, nom)
    _el(c, f"{prefixe}:DateTimeString", d.strftime("%Y%m%d"), format="102")


def _siren_valide(s: str) -> bool:
    return len(s) == 9 and s.isdigit()


def _partie(
    parent: etree._Element,
    nom: str,
    *,
    raison: str,
    siren: str,
    ligne: str,
    cp: str,
    ville: str,
    pays: str,
    adresse_elec: str,
    tva: str,
    email: str = "",
) -> None:
    p = _el(parent, nom)
    _el(p, "ram:Name", raison)
    if siren:
        org = _el(p, "ram:SpecifiedLegalOrganization")
        _el(org, "ram:ID", siren, schemeID="0002")
    adr = _el(p, "ram:PostalTradeAddress")
    if cp:
        _el(adr, "ram:PostcodeCode", cp)
    if ligne:
        _el(adr, "ram:LineOne", ligne)
    if ville:
        _el(adr, "ram:CityName", ville)
    _el(adr, "ram:CountryID", (pays or "FR")[:2].upper())
    if adresse_elec:
        u = _el(p, "ram:URIUniversalCommunication")
        _el(u, "ram:URIID", adresse_elec, schemeID="0225")
    elif email:
        u = _el(p, "ram:URIUniversalCommunication")
        _el(u, "ram:URIID", email, schemeID="EM")
    if tva:
        reg = _el(p, "ram:SpecifiedTaxRegistration")
        _el(reg, "ram:ID", tva, schemeID="VA")


def _taxe(
    parent: etree._Element,
    f: Facture,
    *,
    montant: Decimal | None = None,
    base: Decimal | None = None,
    entete: bool = False,
) -> None:
    t = _el(
        parent,
        "ram:ApplicableTradeTax" if not parent.tag.endswith("AllowanceCharge") else "ram:CategoryTradeTax",
    )
    if montant is not None:
        _el(t, "ram:CalculatedAmount", _m(montant))
    _el(t, "ram:TypeCode", "VAT")
    if entete and not f.tva.tva_applicable:
        _el(t, "ram:ExemptionReason", f.tva.mention_franchise)
    if base is not None:
        _el(t, "ram:BasisAmount", _m(base))
    _el(t, "ram:CategoryCode", f.tva.categorie)
    if entete and not f.tva.tva_applicable:
        _el(t, "ram:ExemptionReasonCode", "VATEX-FR-FRANCHISE")
    if entete and f.tva.tva_applicable and f.tva.option_debits:
        _el(t, "ram:DueDateTypeCode", "5")  # BT-8 : TVA exigible à la date de facture (débits)
    _el(t, "ram:RateApplicablePercent", _m(f.taux_tva))


def generer_xml(f: Facture) -> bytes:
    """XML CII (Factur-X EN 16931) de la facture ``f``."""
    racine = etree.Element(_q("rsm", "CrossIndustryInvoice"), nsmap=NS)
    ctx = _el(racine, "rsm:ExchangedDocumentContext")
    _el(_el(ctx, "ram:BusinessProcessSpecifiedDocumentContextParameter"), "ram:ID", f.categorie_operation)
    _el(_el(ctx, "ram:GuidelineSpecifiedDocumentContextParameter"), "ram:ID", _GUIDELINE)

    doc = _el(racine, "rsm:ExchangedDocument")
    _el(doc, "ram:ID", f.numero)
    _el(doc, "ram:TypeCode", f.type_code)
    _d(doc, "ram:IssueDateTime", f.date_emission)
    notes = [("BAR", "B2B"), *mentions_obligatoires(f).items(), *(("", n) for n in f.notes)]
    for code, texte in notes:
        if not texte:
            continue
        n = _el(doc, "ram:IncludedNote")
        _el(n, "ram:Content", texte)
        if code and code != "CAT":
            _el(n, "ram:SubjectCode", code)

    tx = _el(racine, "rsm:SupplyChainTradeTransaction")
    for i, ligne in enumerate(f.lignes, 1):
        it = _el(tx, "ram:IncludedSupplyChainTradeLineItem")
        _el(_el(it, "ram:AssociatedDocumentLineDocument"), "ram:LineID", str(i))
        _el(_el(it, "ram:SpecifiedTradeProduct"), "ram:Name", ligne.libelle[:300])
        acc = _el(it, "ram:SpecifiedLineTradeAgreement")
        _el(_el(acc, "ram:NetPriceProductTradePrice"), "ram:ChargeAmount", _m(ligne.prix_unitaire_ht))
        _el(
            _el(it, "ram:SpecifiedLineTradeDelivery"),
            "ram:BilledQuantity",
            f"{Decimal(ligne.quantite).normalize():f}",
            unitCode="C62",
        )
        st = _el(it, "ram:SpecifiedLineTradeSettlement")
        _taxe(st, f)
        _el(
            _el(st, "ram:SpecifiedTradeSettlementLineMonetarySummation"),
            "ram:LineTotalAmount",
            _m(ligne.montant_ht),
        )

    v, a = f.vendeur, f.acheteur
    accord = _el(tx, "ram:ApplicableHeaderTradeAgreement")
    _partie(
        accord,
        "ram:SellerTradeParty",
        raison=v.raison_sociale,
        siren=v.siren,
        ligne=v.adresse_ligne,
        cp=v.code_postal,
        ville=v.ville,
        pays=v.pays,
        adresse_elec=v.adresse_electronique_effective,
        tva=v.tva_intracom if f.tva.tva_applicable else "",
        email=v.email,
    )
    _partie(
        accord,
        "ram:BuyerTradeParty",
        raison=a.raison_sociale,
        siren=a.siren,
        ligne=a.adresse_ligne,
        cp=a.code_postal,
        ville=a.ville,
        pays=a.pays,
        adresse_elec=a.adresse_electronique_effective,
        tva=a.tva_intracom,
        email=a.email,
    )

    livr = _el(tx, "ram:ApplicableHeaderTradeDelivery")
    if a.adresse_livraison_differente:
        st = _el(livr, "ram:ShipToTradeParty")
        _el(st, "ram:Name", a.raison_sociale)
        adr = _el(st, "ram:PostalTradeAddress")
        if a.livraison_code_postal:
            _el(adr, "ram:PostcodeCode", a.livraison_code_postal)
        _el(adr, "ram:LineOne", a.livraison_ligne)
        if a.livraison_ville:
            _el(adr, "ram:CityName", a.livraison_ville)
        _el(adr, "ram:CountryID", (a.livraison_pays or a.pays or "FR")[:2].upper())
    if f.date_prestation:
        ev = _el(livr, "ram:ActualDeliverySupplyChainEvent")
        _d(ev, "ram:OccurrenceDateTime", f.date_prestation)

    regl = _el(tx, "ram:ApplicableHeaderTradeSettlement")
    if f.reference_paiement:
        _el(regl, "ram:PaymentReference", f.reference_paiement[:140])
    _el(regl, "ram:InvoiceCurrencyCode", f.devise)
    if v.iban and "À COMPLÉTER" not in v.iban and not f.est_avoir:
        moyen = _el(regl, "ram:SpecifiedTradeSettlementPaymentMeans")
        _el(moyen, "ram:TypeCode", "58")  # virement SEPA
        _el(_el(moyen, "ram:PayeePartyCreditorFinancialAccount"), "ram:IBANID", v.iban.replace(" ", ""))
    _taxe(regl, f, montant=f.montant_tva, base=f.base_ht, entete=True)
    for r in f.remises:
        ac = _el(regl, "ram:SpecifiedTradeAllowanceCharge")
        ind = _el(ac, "ram:ChargeIndicator")
        _el(ind, "udt:Indicator", "false")
        _el(ac, "ram:ActualAmount", _m(r.montant))
        _el(ac, "ram:ReasonCode", r.code_raison)
        _el(ac, "ram:Reason", r.libelle[:300])
        _taxe(ac, f)
    termes = _el(regl, "ram:SpecifiedTradePaymentTerms")
    if not f.est_avoir:
        _el(
            termes,
            "ram:Description",
            f"Paiement à {f.paiement.delai_jours} jours. {f.paiement.moyen}".strip(),
        )
        _d(termes, "ram:DueDateDateTime", f.date_echeance)
    else:
        _el(termes, "ram:Description", "Avoir : montant à déduire ou à rembourser.")
    tot = _el(regl, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    _el(tot, "ram:LineTotalAmount", _m(f.total_lignes_ht))
    if f.remises:
        _el(tot, "ram:AllowanceTotalAmount", _m(f.remise_totale))
    _el(tot, "ram:TaxBasisTotalAmount", _m(f.base_ht))
    _el(tot, "ram:TaxTotalAmount", _m(f.montant_tva), currencyID=f.devise)
    _el(tot, "ram:GrandTotalAmount", _m(f.total_ttc))
    if f.deja_paye:
        _el(tot, "ram:TotalPrepaidAmount", _m(f.deja_paye))
    _el(tot, "ram:DuePayableAmount", _m(f.net_a_payer))
    if f.facture_origine:
        ref = _el(regl, "ram:InvoiceReferencedDocument")
        _el(ref, "ram:IssuerAssignedID", f.facture_origine)
        if f.date_facture_origine:
            _d(ref, "ram:FormattedIssueDateTime", f.date_facture_origine, prefixe="qdt")
    return etree.tostring(racine, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def valider_xsd(xml: bytes) -> None:
    """Validation contre le XSD Factur-X EN 16931 (lève une exception si invalide)."""
    import facturx

    facturx.xml_check_xsd(xml, flavor="factur-x", level="en16931")


def controles_reforme(f: Facture) -> list[str]:
    """Contrôles français (sous-ensemble des règles BR-FR) qui ne sont pas dans le XSD : liste des
    anomalies (vide si la facture est prête pour une plateforme agréée)."""
    anomalies = []
    if not _siren_valide(f.vendeur.siren):
        anomalies.append("SIREN du vendeur absent ou invalide (BT-30, 9 chiffres)")
    if not _siren_valide(f.acheteur.siren):
        anomalies.append("SIREN de l'acheteur absent ou invalide (BT-47, 9 chiffres)")
    if not f.vendeur.adresse_electronique_effective.startswith(f.vendeur.siren):
        anomalies.append("adresse électronique du vendeur (BT-34) : elle doit commencer par le SIREN")
    if not f.acheteur.adresse_electronique_effective.startswith(f.acheteur.siren or "?"):
        anomalies.append("adresse électronique de l'acheteur (BT-49) : elle doit commencer par son SIREN")
    if len(f.numero) > 35:
        anomalies.append("numéro de facture de plus de 35 caractères (BR-FR-01)")
    return anomalies
