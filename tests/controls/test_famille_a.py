"""Famille A — facture commerciale contre déclaration (SPEC §10). Données fictives."""

from datetime import date
from decimal import Decimal as D

import pytest

from controldone.controls import famille_a as fa
from controldone.controls.context import ControlContext
from controldone.controls.framework import run_controls
from controldone.guardrails import PHRASE_RENVOI, check_text
from controldone.model import (
    Allocation,
    ArticleDeclaration,
    ChampsDeclaration,
    ChampsFactureCommerciale,
    ChampsSupport,
    DocumentReference,
    Entite,
    ForceLien,
    LigneFactureCommerciale,
    MethodeAllocation,
    NatureMontant,
    Outcome,
    Partie,
    ProfilTolerances,
    QualiteTexte,
    RaisonCode,
    RolePreuve,
    SousTotal,
    TotalOrigine,
    TypeDocument,
    TypeSousTotal,
)
from controldone.normalize.fiscal import tva_fr_depuis_siren
from controldone.taux_reference import TableTauxReference
from controldone.testing import document, dossier_pour, vs

FC, DEC = "doc_fc1", "doc_dec1"
SIREN_A, SIREN_B = "123456782", "987654324"
TVA_A, TVA_B = tva_fr_depuis_siren(SIREN_A), tva_fr_depuis_siren(SIREN_B)
TVA_TIERS = "DE123456789"
TVA_HORS = tva_fr_depuis_siren("999000001")  # entité fictive hors client
ENT_A = Entite(id="ent_a", raison_sociale="ALPHA IMPORT FICTIF", tva=TVA_A, siren=SIREN_A, alias=["Alpha Import"])
ENT_B = Entite(id="ent_b", raison_sociale="BETA LOGISTIQUE FICTIF", tva=TVA_B, siren=SIREN_B)
ENTITES = [ENT_A, ENT_B]
JOUR = "2026-08-14"


# --- fabriques -----------------------------------------------------------------------------------------


def fv(chemin, valeur, doc=FC, **kw):
    return None if valeur is None else vs(f"facture_commerciale.{chemin}", valeur, document_id=doc, **kw)


def dv(chemin, valeur, doc=DEC, **kw):
    return None if valeur is None else vs(f"declaration.{chemin}", valeur, document_id=doc, **kw)


def facture(id=FC, *, numero="INV-2026-00042", total="12540.00", devise="USD", tva=TVA_A, qualite=QualiteTexte.natif,
            sous_type=None, kw_total=None, kw_devise=None, **champs):
    c = ChampsFactureCommerciale(
        numero=fv("numero", numero, id),
        total_facture=fv("total_facture", total, id, **(kw_total or {})),
        devise=fv("devise", devise, id, **(kw_devise or {})),
        acheteur=champs.pop("acheteur", None) or Partie(tva=fv("acheteur.tva", tva, id)),
        **champs,
    )
    return document(TypeDocument.facture_commerciale, c, id=id, qualite=qualite, sous_type=sous_type)


def declaration(id=DEC, *, mrn="26FR00000000000001", montant="12540.00", devise="USD", tva=TVA_A, taux=None,
                sens="eur_par_devise", qualite=QualiteTexte.natif, kw_montant=None, version=None, **champs):
    c = ChampsDeclaration(
        mrn=dv("mrn", mrn, id),
        version=dv("version", version, id),
        montant_total_facture=dv("montant_total_facture", montant, id, **(kw_montant or {})),
        devise_facture=dv("devise_facture", devise, id),
        taux_change=dv("taux_change", taux, id),
        taux_change_sens=dv("taux_change_sens", sens if taux else None, id),
        importateur=champs.pop("importateur", None) or Partie(tva=dv("importateur.tva", tva, id)),
        date_acceptation=dv("date_acceptation", champs.pop("date_acceptation", JOUR), id),
        **champs,
    )
    return document(TypeDocument.declaration, c, id=id, qualite=qualite)


def ctx_de(docs, *, force=ForceLien.forte, allocations=(), entites=ENTITES, taux_ref=None, profil=None):
    dossier = dossier_pour(docs, force=force)
    dossier.allocations.extend(allocations)
    return ControlContext.construire(
        dossier, docs, profil or ProfilTolerances(id="tol_test"), entites=entites, execution_id="exe_test",
        taux_reference=TableTauxReference(taux_ref) if taux_ref else None,
    )


def un(fn, ctx):
    rs = fn(ctx)
    assert len(rs) == 1, [(r.sous_controle, r.outcome) for r in rs]
    return rs[0]


def texte_propre(r):
    c = r.constat
    assert c is not None
    assert check_text(c.libelle) == [] and check_text(c.prochaine_action) == []
    assert c.preuves and all(p.role in RolePreuve for p in c.preuves)
    return c


REF_USD = {"USD": {date(2026, 8, 14): D("1.0870")}}


# --- couples ---------------------------------------------------------------------------------------------


def test_couple_unique_sans_allocation():
    ctx = ctx_de([facture(), declaration()])
    cs = fa.couples(ctx)
    assert len(cs) == 1 and cs[0].unite == "dec:doc_dec1|fc:doc_fc1"


def test_couples_par_allocation():
    docs = [facture("doc_fc1"), facture("doc_fc2"), declaration("doc_dec1"),
            declaration("doc_dec2", mrn="26FR99999999999001")]
    allocs = [Allocation(source_document_id="doc_fc1", cible_document_id="doc_dec1", methode=MethodeAllocation.totalite),
              Allocation(source_document_id="doc_fc2", cible_document_id="doc_dec2", methode=MethodeAllocation.totalite)]
    cs = fa.couples(ctx_de(docs, allocations=allocs))
    assert sorted(c.unite for c in cs) == ["dec:doc_dec1|fc:doc_fc1", "dec:doc_dec2|fc:doc_fc2"]


def test_document_manquant_non_verifiable():
    for fn in (fa.a1_entite_importatrice, fa.a4_valeur_facturee, fa.a13_codes_marchandise):
        r = un(fn, ctx_de([facture()]))
        assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.document_manquant


# --- A1 --------------------------------------------------------------------------------------------------


def test_a1_conforme():
    assert un(fa.a1_entite_importatrice, ctx_de([facture(), declaration()])).outcome is Outcome.conforme


def test_a1_entite_du_groupe_differente_certain():
    r = un(fa.a1_entite_importatrice, ctx_de([facture(tva=TVA_A), declaration(tva=TVA_B)]))
    assert r.outcome is Outcome.ecart_certain
    c = texte_propre(r)
    assert c.montant_en_jeu is None and c.nature_montant is NatureMontant.aucun
    assert "ALPHA IMPORT FICTIF" in c.libelle and "BETA LOGISTIQUE FICTIF" in c.libelle
    assert "aurait dû" not in c.libelle


def test_a1_importateur_hors_client():
    r = un(fa.a1_entite_importatrice, ctx_de([facture(), declaration(tva=TVA_HORS)]))
    assert r.outcome is Outcome.ecart_certain and "aucune entité du client" in r.constat.libelle
    d = declaration(importateur=Partie(tva=dv("importateur.tva", TVA_HORS, confiance=0.8)))
    r = un(fa.a1_entite_importatrice, ctx_de([facture(), d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.confiance_insuffisante in r.constat.raisons


def test_a1_identification_par_alias_jamais_certaine():
    f = facture(acheteur=Partie(nom=fv("acheteur.nom", "Alpha Import SAS")))
    r = un(fa.a1_entite_importatrice, ctx_de([f, declaration(tva=TVA_B)]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.confiance_insuffisante in r.constat.raisons


def test_a1_siren_avec_cle_tva_abimee():
    f = facture(tva="FR00" + SIREN_A)
    assert un(fa.a1_entite_importatrice, ctx_de([f, declaration()])).outcome is Outcome.conforme


def test_a1_plusieurs_entites():
    d = declaration(destinataire=Partie(tva=dv("destinataire.tva", TVA_B)))
    r = un(fa.a1_entite_importatrice, ctx_de([facture(), d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.plusieurs_entites in r.constat.raisons


def test_a1_facture_illisible_et_tva_tiers():
    f = facture(tva=None)
    r = un(fa.a1_entite_importatrice, ctx_de([f, declaration()]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.confiance_insuffisante in r.constat.raisons
    r = un(fa.a1_entite_importatrice, ctx_de([facture(tva=TVA_TIERS), declaration()]))
    assert r.outcome is Outcome.a_verifier and TVA_TIERS in r.constat.libelle
    texte_propre(r)


def test_a1_non_verifiable():
    r = un(fa.a1_entite_importatrice, ctx_de([facture(), declaration(tva=None)]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.valeur_absente
    r = un(fa.a1_entite_importatrice, ctx_de([facture(), declaration()], entites=[]))
    assert r.outcome is Outcome.non_verifiable


def test_a1_rattachement_faible():
    r = un(fa.a1_entite_importatrice, ctx_de([facture(), declaration(tva=TVA_B)], force=ForceLien.faible))
    assert r.outcome is Outcome.a_verifier and RaisonCode.rattachement_faible in r.constat.raisons


# --- A2 --------------------------------------------------------------------------------------------------


def _refs(*refs, code="N380"):
    return [DocumentReference(type_code=dv("documents_references[].type_code", code),
                              reference=dv("documents_references[].reference", r)) for r in refs]


def test_a2_conforme_et_reference_tronquee():
    for ref in ("INV-2026-00042", "2026-00042"):
        d = declaration(documents_references=_refs(ref))
        assert un(fa.a2_reference_facture, ctx_de([facture(), d])).outcome is Outcome.conforme


def test_a2_constat_signal():
    d = declaration(documents_references=_refs("INV-2026-00077"))
    r = un(fa.a2_reference_facture, ctx_de([facture(), d]))
    assert r.outcome is Outcome.a_verifier
    c = texte_propre(r)
    assert RaisonCode.controle_signal_seulement in c.raisons and c.montant_en_jeu is None
    assert "INV-2026-00042" in c.libelle and "INV-2026-00077" in c.libelle


def test_a2_aucune_reference_facture():
    """D-803 : liste des documents produits lue (ici une LTA) sans référence de facture -> constat (§10 A2)."""
    d = declaration(documents_references=_refs("99911112222", code="N740"))
    r = un(fa.a2_reference_facture, ctx_de([facture(), d]))
    assert r.outcome is Outcome.a_verifier
    c = texte_propre(r)
    assert "INV-2026-00042" in c.libelle and "N740 99911112222" in c.libelle and c.montant_en_jeu is None
    assert set(c.documents_concernes) == {FC, DEC}


def test_a2_aucune_reference_lue():
    """Aucune référence lue sur une déclaration imprimée : la section a pu échapper à la lecture."""
    r = un(fa.a2_reference_facture, ctx_de([facture(), declaration()]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.valeur_absente


def test_a2_export_structure_sans_reference():
    """Export structuré (XML/CSV) sans référence de facture : l'absence est fiable -> constat."""
    d = declaration(mrn=None, documents_references=[])
    d.dec.mrn = dv("mrn", "26FR00000000000001", methode="xml_structure")
    r = un(fa.a2_reference_facture, ctx_de([facture(), d]))
    assert r.outcome is Outcome.a_verifier and "aucune référence de facture" in texte_propre(r).libelle


# --- A3 --------------------------------------------------------------------------------------------------


def test_a3_meme_devise():
    assert un(fa.a3_devise, ctx_de([facture(), declaration()])).outcome is Outcome.conforme


def test_a3_devises_differentes_certain():
    r = un(fa.a3_devise, ctx_de([facture(devise="USD"), declaration(devise="GBP")]))
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu is None
    assert "USD" in texte_propre(r).libelle and "GBP" in r.constat.libelle


def test_a3_symbole_ambigu():
    f = facture(kw_devise={"brut": "$"})
    r = un(fa.a3_devise, ctx_de([f, declaration(devise="CAD")]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.devise_incertaine in r.constat.raisons


def test_a3_delegue_a_a5():
    ok = declaration(devise="EUR", montant="11536.80", taux="0.92000")
    r = un(fa.a3_devise, ctx_de([facture(), ok]))
    assert r.outcome is Outcome.conforme and r.raison_code is RaisonCode.montant_converti
    ko = declaration(devise="EUR", montant="10950.00", taux="0.92000")
    r = un(fa.a3_devise, ctx_de([facture(), ko]))
    assert r.outcome is Outcome.non_applicable and r.raison_code is RaisonCode.montant_converti


def test_a3_illisible_et_multiples():
    r = un(fa.a3_devise, ctx_de([facture(kw_devise={"confiance": 0.3}), declaration()]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.confiance_insuffisante
    docs = [facture("doc_fc1"), facture("doc_fc2", devise="EUR"), declaration()]
    r = un(fa.a3_devise, ctx_de(docs))
    assert r.outcome is Outcome.a_verifier and RaisonCode.devise_incertaine in r.constat.raisons


# --- A4 --------------------------------------------------------------------------------------------------


def test_a4_conforme_dans_t_valeur():
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(montant="12541.00")]))
    assert r.outcome is Outcome.conforme and r.tolerance_appliquee == D("12.54100")  # 0,1 % du plus grand


def test_a4_ecart_certain_eur_signe():
    r = un(fa.a4_valeur_facturee, ctx_de([facture(devise="EUR"), declaration(devise="EUR", montant="12640.00")]))
    assert r.outcome is Outcome.ecart_certain
    c = texte_propre(r)
    assert c.montant_en_jeu == D("100.00") and c.nature_montant is NatureMontant.ecart_documentaire
    assert c.sens is None and c.renvoi is False
    assert "12\u00a0640,00\u00a0EUR" in c.libelle and "valeur en douane" not in c.libelle
    r = un(fa.a4_valeur_facturee, ctx_de([facture(devise="EUR"), declaration(devise="EUR", montant="12440.00")]))
    assert r.constat.montant_en_jeu == D("-100.00")


def test_a4_montant_converti_au_taux_imprime():
    d = declaration(montant="12640.00", taux="0.921235")
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), d]))
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("92.12")  # 92,1235 arrondi
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(montant="12640.00")]))
    assert r.constat.montant_en_jeu is None  # devise non EUR et taux absent


def test_a4_sous_seuil():
    r = un(fa.a4_valeur_facturee, ctx_de([facture(devise="EUR", total="1000.00"),
                                          declaration(devise="EUR", montant="1003.00")]))
    assert r.outcome is Outcome.a_verifier and r.constat.raisons == [RaisonCode.ecart_sous_seuil]


def test_a4_ligne_de_pied():
    f = facture(sous_totaux=[SousTotal(type=TypeSousTotal.fret, montant=fv("sous_totaux[].montant", "350.00"))])
    r = un(fa.a4_valeur_facturee, ctx_de([f, declaration(montant="12190.00")]))
    assert r.outcome is Outcome.a_verifier
    c = texte_propre(r)
    assert RaisonCode.ecart_explique_par_ligne_de_pied in c.raisons
    assert PHRASE_RENVOI in c.prochaine_action and c.renvoi is False
    assert c.nature_montant is NatureMontant.ecart_documentaire


def test_a4_total_reconstruit():
    f = facture(kw_total={"total_origine": TotalOrigine.reconstruit, "confiance": 0.6})
    r = un(fa.a4_valeur_facturee, ctx_de([f, declaration(montant="13540.00")]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.total_reconstruit in r.constat.raisons


def test_a4_confiance_et_ancrage():
    r = un(fa.a4_valeur_facturee, ctx_de([facture(kw_total={"confiance": 0.8}), declaration(montant="13540.00")]))
    assert RaisonCode.confiance_insuffisante in r.constat.raisons
    f = facture(kw_total={"methode": "llm", "ancree": False, "confiance": 0.85})
    r = un(fa.a4_valeur_facturee, ctx_de([f, declaration(montant="13540.00")]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.valeur_non_ancree in r.constat.raisons


def test_a4_lecture_ocr_douteuse_et_transposition():
    d = declaration(montant="12840.00", qualite=QualiteTexte.ocr, kw_montant={"methode": "ocr"})
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.lecture_douteuse in r.constat.raisons
    d = declaration(montant="12450.00", qualite=QualiteTexte.ocr, kw_montant={"methode": "ocr"})
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), d]))
    assert r.outcome is Outcome.ecart_certain  # permutation adjacente : vrai écart


def test_a4_allocation_prorata_et_rattachement_faible():
    alloc = Allocation(source_document_id=FC, cible_document_id=DEC, methode=MethodeAllocation.prorata)
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(montant="13540.00")], allocations=[alloc]))
    assert RaisonCode.allocation_prorata in r.constat.raisons
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(montant="13540.00")], force=ForceLien.moyenne))
    assert r.outcome is Outcome.a_verifier and RaisonCode.rattachement_faible in r.constat.raisons


def test_a4_plusieurs_factures_additionnees():
    docs = [facture("doc_fc1", total="1000.00"), facture("doc_fc2", total="2500.50"), declaration(montant="3500.50")]
    r = un(fa.a4_valeur_facturee, ctx_de(docs))
    assert r.outcome is Outcome.conforme and r.attendu == "3500.50"


def test_a4_facture_repartie_sur_deux_declarations():
    docs = [facture(total="3000.00"), declaration("doc_dec1", montant="1000.00"),
            declaration("doc_dec2", mrn="26FR99999999999001", montant="2000.00")]
    allocs = [Allocation(source_document_id=FC, cible_document_id="doc_dec1", montant_alloue=D("1000.00"),
                         methode=MethodeAllocation.reference_explicite),
              Allocation(source_document_id=FC, cible_document_id="doc_dec2", montant_alloue=D("1500.00"),
                         methode=MethodeAllocation.reference_explicite)]
    rs = fa.a4_valeur_facturee(ctx_de(docs, allocations=allocs))
    principal = [r for r in rs if r.sous_controle is None]
    alloc = {r.unite: r for r in rs if r.sous_controle == "allocation"}
    assert len(principal) == 1 and principal[0].outcome is Outcome.conforme
    assert alloc["dec:doc_dec1|fc:doc_fc1"].outcome is Outcome.conforme
    r2 = alloc["dec:doc_dec2|fc:doc_fc1"]
    assert r2.outcome is Outcome.ecart_certain and r2.constat.montant_en_jeu is None  # USD sans taux
    assert len({r.id for r in rs}) == len(rs)


def test_a4_version_rectificative():
    v1 = declaration("doc_dec0", mrn="26FR00000000000001", montant="12540.00", version="1")
    v2 = declaration("doc_dec1", mrn="26FR00000000000002", montant="13540.00", version="2")
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), v1, v2]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.version_rectificative in r.constat.raisons
    assert r.unite == "dec:doc_dec1|fc:doc_fc1"


def test_a4_devise_incertaine():
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(devise=None)]))
    assert r.outcome is Outcome.conforme and r.details["hypothese"] == "meme_devise"
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(devise=None, montant="13540.00")]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.devise_incertaine in r.constat.raisons
    assert r.constat.montant_en_jeu is None


def test_a4_non_verifiable_et_non_applicable():
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(montant=None)]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.valeur_absente
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(montant="1", kw_montant={"confiance": 0.4})]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.confiance_insuffisante
    r = un(fa.a4_valeur_facturee, ctx_de([facture(), declaration(devise="EUR", taux="0.92")]))
    assert r.outcome is Outcome.non_applicable and r.raison_code is RaisonCode.montant_converti


# --- A5 --------------------------------------------------------------------------------------------------


def _eur(montant, taux="0.92000", **kw):
    return declaration(devise="EUR", montant=montant, taux=taux, **kw)


def test_a5_conforme_et_arrondi():
    assert un(fa.a5_montant_converti, ctx_de([facture(), _eur("11537.80")])).outcome is Outcome.conforme
    r = un(fa.a5_montant_converti, ctx_de([facture(total="100.05"), _eur("92.05", taux="0.92")]))
    assert r.attendu == "92.05"  # 92,046 arrondi demi vers le haut


def test_a5_ecart_certain_sens_lu():
    r = un(fa.a5_montant_converti, ctx_de([facture(), _eur("10950.00")]))
    assert r.outcome is Outcome.ecart_certain
    c = texte_propre(r)
    assert c.montant_en_jeu == D("-586.80") and c.nature_montant is NatureMontant.ecart_documentaire
    assert "1 USD = 0,92000 EUR" in c.libelle and r.attendu == "11536.80"
    assert "taux erroné" not in c.libelle


def test_a5_sens_devise_par_eur():
    r = un(fa.a5_montant_converti, ctx_de([facture(), _eur("11536.34", taux="1.0870", sens="devise_par_eur")]))
    assert r.outcome is Outcome.conforme


def test_a5_sens_derive():
    sens_derive = {"taux_change_sens": dv("taux_change_sens", "eur_par_devise", methode="derive", confiance=0.85,
                                          regle_derivation="taux_bce")}
    # écart au-delà du seuil dans les deux sens : certain possible
    d = _eur("9000.00", sens=None)
    d.dec.taux_change_sens = sens_derive["taux_change_sens"]
    r = un(fa.a5_montant_converti, ctx_de([facture(), d]))
    assert r.outcome is Outcome.ecart_certain
    # dans l'autre sens l'écart reste sous le seuil : à vérifier
    d = _eur("11566.00", taux="1.0870")  # autre sens : 11 536,34, écart 29,66 entre T et S
    d.dec.taux_change_sens = sens_derive["taux_change_sens"]
    r = un(fa.a5_montant_converti, ctx_de([facture(), d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.sens_taux_derive in r.constat.raisons


def test_a5_sens_par_taux_de_reference_et_inconnu():
    d = _eur("11536.34", taux="1.0870")
    d.dec.taux_change_sens = None
    r = un(fa.a5_montant_converti, ctx_de([facture(), d], taux_ref=REF_USD))
    assert r.outcome is Outcome.conforme and r.details["sens"] == "devise_par_eur"
    r = un(fa.a5_montant_converti, ctx_de([facture(), d]))  # sens inconnu, un sens concorde
    assert r.outcome is Outcome.conforme


def test_a5_taux_absent_ou_illisible():
    r = un(fa.a5_montant_converti, ctx_de([facture(), declaration(devise="EUR", montant="9000.00")]))
    assert r.outcome is Outcome.non_applicable and r.details["couvert_par"] == "A7"
    d = _eur("9000.00")
    d.dec.taux_change = dv("taux_change", "0.92", confiance=0.3)
    r = un(fa.a5_montant_converti, ctx_de([facture(), d]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.confiance_insuffisante


def test_a5_sous_seuil_et_confusion_taux():
    r = un(fa.a5_montant_converti, ctx_de([facture(), _eur("11570.00")]))
    assert r.outcome is Outcome.a_verifier and r.constat.raisons == [RaisonCode.ecart_sous_seuil]
    d = _eur("11662.20", taux="0.98000", qualite=QualiteTexte.ocr)  # 12 540 × 0,93 = 11 662,20
    d.dec.taux_change = dv("taux_change", "0.98000", methode="ocr")
    r = un(fa.a5_montant_converti, ctx_de([facture(), d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.lecture_douteuse in r.constat.raisons  # 3 lu 8


def test_a5_non_applicable_quand_a6_ou_meme_devise():
    r = un(fa.a5_montant_converti, ctx_de([facture(), _eur("12540.00")]))
    assert r.outcome is Outcome.non_applicable and r.details["couvert_par"] == "A6"
    r = un(fa.a5_montant_converti, ctx_de([facture(), declaration()]))
    assert r.outcome is Outcome.non_applicable


# --- A6 --------------------------------------------------------------------------------------------------


def test_a6_montant_repris_sans_conversion_certain():
    r = un(fa.a6_montant_sans_conversion, ctx_de([facture(), _eur("12540.00")]))
    assert r.outcome is Outcome.ecart_certain
    c = texte_propre(r)
    assert c.montant_en_jeu == D("1003.20")  # 12 540 − 12 540 × 0,92
    assert "même nombre" in c.libelle


def test_a6_devise_incertaine():
    f = facture(kw_devise={"confiance": 0.92})
    r = un(fa.a6_montant_sans_conversion, ctx_de([f, _eur("12540.00")]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.devise_incertaine in r.constat.raisons
    ref = {"GBP": {date(2026, 8, 14): D("0.85")}}  # s'écarte de 1 de plus de 10 %
    d = declaration(devise="EUR", montant="12540.00")
    r = un(fa.a6_montant_sans_conversion, ctx_de([facture(devise="GBP"), d], taux_ref=ref))
    assert r.outcome is Outcome.a_verifier and r.constat.montant_en_jeu is None


def test_a6_conforme_non_verifiable_non_applicable():
    assert un(fa.a6_montant_sans_conversion, ctx_de([facture(), _eur("11536.80")])).outcome is Outcome.conforme
    r = un(fa.a6_montant_sans_conversion, ctx_de([facture(), declaration(devise="EUR", montant="12540.00")]))
    assert r.outcome is Outcome.non_verifiable
    r = un(fa.a6_montant_sans_conversion, ctx_de([facture(), declaration()]))
    assert r.outcome is Outcome.non_applicable


def test_a6_moteur_neutralise_a5():
    rs = run_controls(ctx_de([facture(), _eur("12540.00")]), controles=["A3", "A4", "A5", "A6", "A7"])
    par = {r.controle_id: r for r in rs}
    assert par["A6"].outcome is Outcome.ecart_certain
    assert par["A5"].outcome is Outcome.non_applicable and par["A7"].outcome is Outcome.non_applicable
    assert par["A3"].outcome is Outcome.non_applicable and par["A4"].outcome is Outcome.non_applicable


def test_a6_petit_montant_non_discriminant():
    """D-807 : 2,28 USD déclarés 2,04 EUR : la conversion (≈ 2,10) reste à moins d'une unité, « même nombre »
    ne permet pas de conclure à une absence de conversion."""
    d = declaration(devise="EUR", montant="2.04")
    r = un(fa.a6_montant_sans_conversion, ctx_de([facture(total="2.28"), d], taux_ref=REF_USD))
    assert r.outcome is Outcome.conforme
    r = un(fa.a6_montant_sans_conversion, ctx_de([facture(total="2.28"), _eur("2.28")]))
    assert r.outcome is Outcome.conforme


# --- A7 --------------------------------------------------------------------------------------------------


def test_a7_ordre_de_grandeur():
    d = declaration(devise="EUR", montant="1153.68")
    r = un(fa.a7_ordre_de_grandeur, ctx_de([facture(), d], taux_ref=REF_USD))
    assert r.outcome is Outcome.a_verifier
    c = texte_propre(r)
    assert c.montant_en_jeu is None and c.nature_montant is NatureMontant.aucun
    assert RaisonCode.controle_signal_seulement in c.raisons
    d = declaration(devise="EUR", montant="11000.00")
    assert un(fa.a7_ordre_de_grandeur, ctx_de([facture(), d], taux_ref=REF_USD)).outcome is Outcome.conforme


def test_a7_devise_volatile():
    ref = {"TRY": {date(2026, 8, 14): D("40")}}
    f = facture(devise="TRY", total="400000.00")
    d = declaration(devise="EUR", montant="6500.00")  # ratio 0,65 : hors ± 25 %, dans ± 40 %
    assert un(fa.a7_ordre_de_grandeur, ctx_de([f, d], taux_ref=ref)).outcome is Outcome.conforme


def test_a7_non_applicable_et_non_verifiable():
    r = un(fa.a7_ordre_de_grandeur, ctx_de([facture(), _eur("1000.00")], taux_ref=REF_USD))
    assert r.outcome is Outcome.non_applicable and r.details["couvert_par"] == "A5"
    r = un(fa.a7_ordre_de_grandeur, ctx_de([facture(), declaration(devise="EUR", montant="1000.00")]))
    assert r.outcome is Outcome.non_verifiable


# --- A8 --------------------------------------------------------------------------------------------------


def test_a8_incoterm():
    f = facture(incoterm=fv("incoterm", "FOB Shanghai"))
    r = un(fa.a8_incoterm, ctx_de([f, declaration(incoterm=dv("incoterm", "FOB"))]))
    assert r.outcome is Outcome.conforme
    r = un(fa.a8_incoterm, ctx_de([f, declaration(incoterm=dv("incoterm", "CIF"))]))
    assert r.outcome is Outcome.a_verifier
    c = texte_propre(r)
    assert PHRASE_RENVOI in c.prochaine_action and c.renvoi is False and c.montant_en_jeu is None
    r = un(fa.a8_incoterm, ctx_de([f, declaration()]))
    assert r.outcome is Outcome.non_verifiable


# --- A9 --------------------------------------------------------------------------------------------------


def _ligne(code=None, qte=None, unite="C62", origine=None, ref=None):
    return LigneFactureCommerciale(
        code_marchandise_imprime=fv("lignes[].code_marchandise_imprime", code),
        quantite=fv("lignes[].quantite", qte, unite=unite),
        pays_origine=fv("lignes[].pays_origine", origine),
        reference_article=fv("lignes[].reference_article", ref),
    )


def _article(num="1", code=None, qte=None, unite="C62", origine=None, desc=None, colis=None, doc=DEC, **kw):
    return ArticleDeclaration(
        numero_article=dv("articles[].numero_article", num, doc),
        code_marchandise=dv("articles[].code_marchandise", code, doc),
        quantite_unite_supplementaire=dv("articles[].quantite_unite_supplementaire", qte, doc, unite=unite),
        pays_origine=dv("articles[].pays_origine", origine, doc),
        description=dv("articles[].description", desc, doc),
        nombre_colis=dv("articles[].nombre_colis", colis, doc),
        **kw,
    )


def test_a9_par_sh6():
    f = facture(lignes=[_ligne("8471.30.00", "120"), _ligne("8517.62", "10")])
    d = declaration(articles=[_article("1", "8471300000", "120"), _article("2", "8517620000", "12")])
    rs = {r.unite: r for r in fa.a9_quantites(ctx_de([f, d]))}
    assert rs["dec:doc_dec1|fc:doc_fc1|sh6:847130"].outcome is Outcome.conforme
    r = rs["dec:doc_dec1|fc:doc_fc1|sh6:851762"]
    assert r.outcome is Outcome.a_verifier and "pièces" in texte_propre(r).libelle


def test_a9_unites_differentes_et_total():
    f = facture(lignes=[_ligne("847130", "120", unite="C62")])
    d = declaration(articles=[_article("1", "847130", "50", unite="KGM")])
    r = un(fa.a9_quantites, ctx_de([f, d]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.unites_differentes
    f = facture(lignes=[_ligne(None, "100.0", unite="KGM")])
    d = declaration(articles=[_article("1", None, "100.4", unite="KGM")])
    r = un(fa.a9_quantites, ctx_de([f, d]))
    assert r.sous_controle == "total" and r.outcome is Outcome.conforme  # 0,5 % pour une unité non entière


# --- A10, A11 --------------------------------------------------------------------------------------------


def test_a10_masses():
    f = facture(masse_nette_totale=fv("masse_nette_totale", "100.000"), masse_brute_totale=fv("masse_brute_totale", "120.000"))
    d = declaration(masse_brute_totale=dv("masse_brute_totale", "150.000"),
                    articles=[_article("1", masse_nette=dv("articles[].masse_nette", "100.300"))])
    rs = {r.sous_controle: r for r in fa.a10_masses(ctx_de([f, d]))}
    assert rs["nette"].outcome is Outcome.conforme
    assert rs["brute"].outcome is Outcome.a_verifier and rs["brute"].constat.montant_en_jeu is None
    texte_propre(rs["brute"])


def test_a10_liste_de_colisage_et_non_verifiable():
    sup = document(TypeDocument.document_support, ChampsSupport(
        masse_brute=vs("document_support.masse_brute", "150.000", document_id="doc_sup")), id="doc_sup",
        sous_type="liste_colisage")
    d = declaration(masse_brute_totale=dv("masse_brute_totale", "150.000"))
    rs = {r.sous_controle: r for r in fa.a10_masses(ctx_de([facture(), d, sup]))}
    assert rs["brute"].outcome is Outcome.conforme and "doc_sup" in rs["brute"].documents_concernes
    assert rs["nette"].outcome is Outcome.non_verifiable


def test_a11_colis():
    f = facture(nombre_colis=fv("nombre_colis", "12"))
    assert un(fa.a11_colis, ctx_de([f, declaration(nombre_colis_total=dv("nombre_colis_total", "12"))])).outcome \
        is Outcome.conforme
    d = declaration(articles=[_article("1", colis="5"), _article("2", colis="6")])
    r = un(fa.a11_colis, ctx_de([f, d]))
    assert r.outcome is Outcome.a_verifier and r.constate == "11"
    texte_propre(r)
    assert un(fa.a11_colis, ctx_de([facture(), d])).outcome is Outcome.non_verifiable


def test_a11_deux_declarations_colis_par_article_sans_exception():
    # Total de colis non lu sur deux déclarations du même couple : les valeurs par article (plus nombreuses
    # que les déclarations) ne doivent pas faire échouer la rédaction du libellé (ValueError de zip strict).
    f = facture(nombre_colis=fv("nombre_colis", "20"))
    d1 = declaration(articles=[_article("1", colis="5", doc="doc_dec1"), _article("2", colis="6", doc="doc_dec1")])
    d2 = declaration("doc_dec2", mrn="26FR22222222222222",
                     articles=[_article("1", colis="4", doc="doc_dec2"), _article("2", colis="3", doc="doc_dec2")])
    rs = fa.a11_colis(ctx_de([f, d1, d2]))
    assert rs and all(r.outcome is not None for r in rs)
    for r in rs:
        if r.outcome is Outcome.a_verifier:
            assert "MRN" in texte_propre(r).libelle
    assert fa._refs_dec([d1.model_copy(), d2], [dv("x", "1"), dv("x", "2"), dv("x", "3", doc="doc_dec2")]) \
        .startswith("les déclarations (")


# --- A12, A13 (renvoi) -------------------------------------------------------------------------------------


def test_a12_origines():
    f = facture(lignes=[_ligne("847130", origine="CN")])
    d = declaration(articles=[_article("2", "847130", origine="CN")])
    assert un(fa.a12_pays_origine, ctx_de([f, d])).outcome is Outcome.conforme
    d = declaration(articles=[_article("2", "847130", origine="VN",
                                       code_preference=dv("articles[].code_preference", "300"))])
    r = un(fa.a12_pays_origine, ctx_de([f, d]))
    assert r.outcome is Outcome.a_verifier
    c = texte_propre(r)
    assert c.renvoi is True and c.montant_en_jeu is None and c.nature_montant is NatureMontant.renvoi
    assert PHRASE_RENVOI in c.libelle and RaisonCode.renvoi_reglementaire in c.raisons
    assert "(CN, page 1)" in c.libelle and "article 2" in c.libelle and "(VN, page 1)" in c.libelle
    assert r.details["preferentiel_affiche"] == ["300"]


def test_a12_ensemble_et_non_verifiable():
    f = facture(lignes=[_ligne(None, origine="China")])
    d = declaration(articles=[_article("1", None, origine="CN")])
    r = un(fa.a12_pays_origine, ctx_de([f, d]))
    assert r.sous_controle == "ensemble" and r.outcome is Outcome.conforme
    r = un(fa.a12_pays_origine, ctx_de([facture(), d]))
    assert r.outcome is Outcome.non_verifiable


def test_a13_codes():
    f = facture(lignes=[_ligne("8471.30.00")])
    assert un(fa.a13_codes_marchandise, ctx_de([f, declaration(articles=[_article("1", "8471300000")])])).outcome \
        is Outcome.conforme
    r = un(fa.a13_codes_marchandise, ctx_de([f, declaration(articles=[_article("1", "8517620000")])]))
    assert r.outcome is Outcome.a_verifier
    c = texte_propre(r)
    assert c.renvoi and c.montant_en_jeu is None and PHRASE_RENVOI in c.libelle
    assert RaisonCode.lecture_douteuse not in c.raisons
    assert "8471.30.00" in c.libelle and "8517620000" in c.libelle
    r = un(fa.a13_codes_marchandise, ctx_de([f, declaration(articles=[_article("1", "8471800000")])]))
    assert RaisonCode.lecture_douteuse in r.constat.raisons  # 3 et 8 de la même classe


def test_a13_facture_sans_code():
    r = un(fa.a13_codes_marchandise, ctx_de([facture(lignes=[_ligne(None, "1")]),
                                             declaration(articles=[_article("1", "8471300000")])]))
    assert r.outcome is Outcome.non_verifiable and r.details["motif"] == "la facture ne porte pas de code"


# --- A14, A15 ---------------------------------------------------------------------------------------------


def test_a14_chronologie():
    f = facture(date=fv("date", "2026-08-15"))
    assert un(fa.a14_chronologie, ctx_de([f, declaration()])).outcome is Outcome.conforme  # 1 jour admis
    f = facture(date=fv("date", "2026-08-17"))
    r = un(fa.a14_chronologie, ctx_de([f, declaration()]))
    assert r.outcome is Outcome.a_verifier and "3 jours" in texte_propre(r).libelle
    pf = facture(date=fv("date", "2026-08-17"), sous_type="pro_forma")
    assert un(fa.a14_chronologie, ctx_de([pf, declaration()])).outcome is Outcome.non_applicable
    assert un(fa.a14_chronologie, ctx_de([facture(), declaration()])).outcome is Outcome.non_verifiable


def test_a15_references():
    f = facture(lignes=[_ligne(ref="AB-1234"), _ligne(ref="CD-5678")])
    d = declaration(articles=[_article("1", desc="Pompe réf. AB-1234"), _article("2", desc="Vanne CD5678")])
    assert un(fa.a15_references_produit, ctx_de([f, d])).outcome is Outcome.conforme
    d = declaration(articles=[_article("1", desc="Pompe AB-1234")])
    r = un(fa.a15_references_produit, ctx_de([f, d]))
    assert r.outcome is Outcome.a_verifier and "CD-5678" in texte_propre(r).libelle
    d = declaration(articles=[_article("1", desc="Pompe AB-1234"), _article("2", desc="Vannes diverses")])
    r = un(fa.a15_references_produit, ctx_de([f, d]))
    assert r.outcome is Outcome.non_applicable
    r = un(fa.a15_references_produit, ctx_de([facture(), d]))
    assert r.outcome is Outcome.non_applicable


def test_a15_reference_remplacee_par_une_autre():
    """D-810 : une désignation citant une référence de même forme (« LA-1012-Z ») reprend bien une référence
    d'article ; celle de la facture (« LA-1012-M ») est introuvable -> constat."""
    f = facture(lignes=[_ligne(ref="LA-1012-M"), _ligne(ref="LA-5118-X")])
    d = declaration(articles=[_article("1", desc="MONITEUR REF LA-1012-Z"), _article("2", desc="CASSEROLE REF LA-5118-X")])
    r = un(fa.a15_references_produit, ctx_de([f, d]))
    assert r.outcome is Outcome.a_verifier and "LA-1012-M" in texte_propre(r).libelle
    assert "LA-5118-X" not in r.details["absentes"][0]


def test_a15_reference_tronquee_et_designation_illisible():
    f = facture(lignes=[_ligne(ref="OS-2191-B"), _ligne(ref="OS-4240-BK")])
    d = declaration(articles=[_article("1", desc="COUTEAU REF OS-2191-"), _article("2", desc="VIS REF OS-4240-BK")])
    assert un(fa.a15_references_produit, ctx_de([f, d])).outcome is Outcome.conforme  # troncature (§8.4)
    d = declaration(articles=[_article("1", desc="COUTEAU REF OS-2191-B"), _article("2", desc=None)])
    assert un(fa.a15_references_produit, ctx_de([f, d])).outcome is Outcome.non_verifiable


# --- garde-fous sur l'ensemble de la famille ----------------------------------------------------------------


@pytest.fixture
def dossier_en_ecart():
    f = facture(total="12540.00", tva=TVA_A, incoterm=fv("incoterm", "FOB"), date=fv("date", "2026-08-20"),
                nombre_colis=fv("nombre_colis", "4"), masse_brute_totale=fv("masse_brute_totale", "80"),
                lignes=[_ligne("8471.30.00", "10", origine="CN", ref="AB-1234")])
    d = declaration(devise="EUR", montant="12540.00", taux="0.92000", tva=TVA_B, incoterm=dv("incoterm", "DAP"),
                    nombre_colis_total=dv("nombre_colis_total", "5"), masse_brute_totale=dv("masse_brute_totale", "95"),
                    documents_references=_refs("XYZ-999"),
                    articles=[_article("1", "8471800000", "12", origine="VN", desc="Article AB-9999 FICTIF")])
    return ctx_de([f, d])


def test_garde_fous_textes_et_renvois(dossier_en_ecart):
    rs = run_controls(dossier_en_ecart, controles=[f"A{i}" for i in range(1, 16)])
    constats = [r.constat for r in rs if r.constat is not None]
    assert {c.controle_id for c in constats} >= {"A1", "A2", "A6", "A8", "A9", "A10", "A11", "A12", "A13", "A14"}
    for c in constats:
        assert check_text(c.libelle) == [] and check_text(c.prochaine_action) == [], c.controle_id
        assert c.motif_blocage is None
        assert c.preuves and all(p.document_id for p in c.preuves if p.valeur_sourcee_id)
        if c.controle_id in ("A12", "A13"):
            assert c.renvoi and c.montant_en_jeu is None and PHRASE_RENVOI in c.libelle
        if c.controle_id not in ("A4", "A5", "A6"):
            assert c.montant_en_jeu is None
        if c.controle_id in ("A2", "A7", "A8", "A9", "A10", "A11", "A12", "A13", "A14", "A15"):
            assert c.niveau.value == "a_verifier"
    for r in rs:
        assert r.outcome is not Outcome.non_verifiable or r.raison_code is not None


def test_gabarits_sans_formulation_interdite():
    for nom in fa.__all__:
        if nom.startswith("ACTION"):
            assert check_text(getattr(fa, nom)) == [], nom
