from decimal import Decimal as D

from controldone.extract import (
    Extracteur,
    ExtractionResult,
    anchor,
    ancrer,
    fusionner_resultats,
    fusionner_valeurs,
    normaliser_valeur,
    valeur_sourcee,
)
from controldone.extract.llm import LLMExtracteur
from controldone.model import (
    ChampsFactureCommerciale,
    ChampsFactureTransitaire,
    ExtracteurInfo,
    LigneFactureTransitaire,
    Methode,
    NatureLigne,
    RaisonCode,
    SigneImprime,
    TypeDocument,
    TypeValeur,
)
from controldone.testing import vs

DET = ExtracteurInfo(type="deterministe", id="pdf_regles", version="1.0.0")
STR = ExtracteurInfo(type="structure", id="cii", version="1.0.0")
LLM = ExtracteurInfo(type="llm", id="llm_anthropic", version="1.0.0")


def test_anchor_normalise_les_espaces():
    page = "TOTAL AMOUNT DUE  USD 12,540.00\nThank you"
    assert anchor("USD 12,540.00", page)
    assert anchor("USD  12,540.00", page)
    assert anchor("DUE USD 12,540.00", page)  # retour à la ligne / insécable = espace
    assert not anchor("USD 12.540,00", page)
    assert not anchor("usd 12,540.00", page)  # littéral : casse respectée
    assert not anchor("", page) and not anchor("x", None)


def test_ancrer():
    textes = {1: "Total 1 234,56 EUR"}
    v = vs("facture_commerciale.total_facture", "1234.56", brut="1 234,56", methode="ocr", confiance=0.85,
           ancree=False)
    assert ancrer(v, textes).ancree is True and ancrer(v, textes).confiance == 0.85
    # une valeur llm construite non ancrée est déjà plafonnée à 0,50 par le modèle (§6.3)
    assert vs("a", "1", methode="llm", confiance=0.85, ancree=False).confiance == 0.5
    w = vs("facture_commerciale.total_facture", "1234.56", brut="1 234,57", methode="llm", confiance=0.85,
           ancree=True)
    a = ancrer(w, textes)
    assert a.ancree is False and a.confiance == 0.5
    x = vs("a", "1", methode="xml_structure", ancree=False)
    assert ancrer(x, textes) is x


def test_fusion_accord():
    a = vs("facture_commerciale.total_facture", "100.00", confiance=0.97, extracteur=DET)
    b = vs("facture_commerciale.total_facture", "100.00", confiance=0.85, methode="llm", extracteur=LLM)
    r = fusionner_valeurs([b, a], champ_cle=True)
    assert r is a and r.raisons == []


def test_fusion_desaccord_champ_cle():
    a = vs("facture_commerciale.total_facture", "100.00", confiance=0.97, extracteur=DET)
    b = vs("facture_commerciale.total_facture", "160.00", confiance=0.85, methode="llm", extracteur=LLM)
    r = fusionner_valeurs([a, b], champ_cle=True)
    assert r.valeur == "100.00" and r.confiance == 0.8 and RaisonCode.extracteurs_en_desaccord in r.raisons
    r2 = fusionner_valeurs([a, b], champ_cle=False)
    assert r2.confiance == 0.97 and RaisonCode.extracteurs_en_desaccord in r2.raisons


def test_fusion_saisie_humaine_prioritaire():
    a = vs("x.total", "100.00", confiance=0.99)
    h = vs("x.total", "90.00", confiance=1.0, methode="saisie_humaine")
    assert fusionner_valeurs([a, h], champ_cle=True) is h


def test_fusion_egalite_de_confiance_departagee_par_methode():
    s = vs("x.total", "1", confiance=0.9, methode="xml_structure", extracteur=STR)
    o = vs("x.total", "2", confiance=0.9, methode="ocr", extracteur=DET)
    assert fusionner_valeurs([o, s], champ_cle=False).methode is Methode.xml_structure


def test_fusionner_resultats():
    c1 = ChampsFactureCommerciale(
        numero=vs("facture_commerciale.numero", "INV-1", confiance=0.95, extracteur=DET),
        total_facture=vs("facture_commerciale.total_facture", "100.00", confiance=0.95, extracteur=DET),
    )
    c2 = ChampsFactureCommerciale(
        total_facture=vs("facture_commerciale.total_facture", "160.00", confiance=0.85, methode="llm",
                         extracteur=LLM),
        incoterm=vs("facture_commerciale.incoterm", "FOB", confiance=0.85, methode="llm", extracteur=LLM),
    )
    r = fusionner_resultats(
        [ExtractionResult(extracteur=LLM, champs=c2), ExtractionResult(extracteur=DET, champs=c1)],
        TypeDocument.facture_commerciale,
    )
    assert r.champs.numero.valeur == "INV-1"
    assert r.champs.incoterm.valeur == "FOB"
    assert r.champs.total_facture.valeur == "100.00" and r.champs.total_facture.confiance == 0.8
    assert r.extracteur.id == "llm_anthropic+pdf_regles"
    assert len(r.valeurs) == 3


def test_fusion_conserve_les_classifications_de_la_base():
    l0 = LigneFactureTransitaire(nature=NatureLigne.debours_tva,
                                 montant_ht=vs("facture_transitaire.lignes[0].montant_ht", "20.00", extracteur=DET))
    base = ChampsFactureTransitaire(lignes=[l0])
    r = fusionner_resultats([ExtractionResult(extracteur=DET, champs=base)], TypeDocument.facture_transitaire)
    assert r.champs.lignes[0].nature is NatureLigne.debours_tva


def test_normaliser_valeur():
    n = normaliser_valeur(TypeValeur.montant, "(1 234,56 EUR)")
    assert n.valeur == "1234.56" and n.signe is SigneImprime.negatif and n.unite == "EUR"
    assert normaliser_valeur(TypeValeur.date, "14 août 2026").valeur == "2026-08-14"
    assert normaliser_valeur(TypeValeur.masse, "1 250,5 kg").valeur == "1250.500"
    assert normaliser_valeur(TypeValeur.pays, "Chine").valeur == "CN"
    assert normaliser_valeur(TypeValeur.tva, "FR 32 000 123 459").valeur == "FR32000123459"
    assert normaliser_valeur(TypeValeur.taux, "2,5 %").valeur == "2.5"
    q = normaliser_valeur(TypeValeur.quantite, "10 pcs")
    assert q.valeur == "10" and q.unite == "C62"
    assert normaliser_valeur(TypeValeur.code, "8471.30.00").valeur == "84713000"
    assert normaliser_valeur(TypeValeur.incoterm, "FOB Shanghai").valeur == "FOB"
    assert normaliser_valeur(TypeValeur.montant, "abc").valeur is None
    assert normaliser_valeur(TypeValeur.montant, "1,234").ambigu


def test_valeur_sourcee():
    v = valeur_sourcee(type_document=TypeDocument.facture_commerciale, chemin="total_facture",
                       brut="USD 12,540.00", document_id="doc_1", page=2, extracteur=DET,
                       methode=Methode.texte_natif, confiance=0.97,
                       textes_pages={2: "TOTAL AMOUNT DUE  USD 12,540.00"})
    assert v.chemin == "facture_commerciale.total_facture" and v.valeur == "12540.00" and v.unite == "USD"
    assert v.ancree and v.type is TypeValeur.montant and v.decimal() == D("12540.00")
    amb = valeur_sourcee(type_document="facture_commerciale", chemin="total_facture", brut="1,234",
                         document_id="d", page=1, extracteur=DET, methode=Methode.ocr, confiance=0.9)
    assert amb.confiance == 0.75 and not amb.ancree


def test_protocole():
    assert isinstance(LLMExtracteur(client=object()), Extracteur)
