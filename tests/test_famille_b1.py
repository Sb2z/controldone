"""B1 — contrôle de référence du cadre (SPEC §11)."""

from decimal import Decimal as D

from controldone.controls.famille_b import ACTION_B, b1_base_taux_montant
from controldone.controls.framework import run_controls
from controldone.guardrails import PHRASE_RENVOI, check_text
from controldone.model import (
    CategorieTaxe,
    ForceLien,
    NatureMontant,
    Niveau,
    Outcome,
    QualiteTexte,
    RaisonCode,
    RolePreuve,
    TauxNature,
)
from controldone.testing import contexte, declaration, taxation, vs


def _dec(*taxations, total=None, **kw):
    """``total`` : total à payer imprimé, qui reprend les lignes (lecture corroborée, D-1700)."""
    if total is not None:
        kw["total_a_payer"] = vs("declaration.total_a_payer", total, document_id="doc_dec1")
    return declaration(id="doc_dec1", taxations=taxations, **kw)


def _un(ctx):
    rs = b1_base_taux_montant(ctx)
    assert len(rs) == 1
    return rs[0]


def test_conforme():
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="52.28"))
    r = _un(contexte([d]))
    assert r.outcome is Outcome.conforme and r.constat is None
    assert r.attendu == "52.28" and r.ecart == D("0.01")  # 52,28 − 52,275 arrondi au centime
    assert r.tolerance_appliquee == D("0.01") and r.seuil_certitude_applique == D("1.00")
    assert set(r.entrees) == {"base", "taux", "montant"}


def test_arrondi_a_l_euro_admis():
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="53"))  # arrondi supérieur
    assert _un(contexte([d])).outcome is Outcome.conforme


def test_ecart_certain_exemple_de_la_spec():
    d = _dec(taxation("doc_dec1", article="3", base="2091.00", taux="2.5", montant="418.20"), total="418.20")
    r = _un(contexte([d]))
    assert r.outcome is Outcome.ecart_certain
    c = r.constat
    assert c.niveau is Niveau.ecart_certain and c.raisons == []
    assert c.montant_en_jeu == D("365.93") and c.nature_montant is NatureMontant.arithmetique_declaration
    assert c.composante.value == "droit" and c.renvoi is False and c.sens is None
    assert "Sur l'article 3" in c.libelle
    assert "418,20 EUR" in c.libelle and "2 091,00 × 2,5 % = 52,28 EUR" in c.libelle
    assert c.prochaine_action == ACTION_B and PHRASE_RENVOI in c.prochaine_action
    assert check_text(c.libelle + c.prochaine_action) == []
    roles = [p.role for p in c.preuves]
    assert roles == [RolePreuve.operande, RolePreuve.operande, RolePreuve.valeur_b, RolePreuve.valeur_a]
    assert c.preuves[2].valeur_brute == "418.20" and c.preuves[2].document_id == "doc_dec1"
    assert c.documents_concernes == ["doc_dec1"]


def test_ecart_sous_le_seuil():
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="52.90"))
    r = _un(contexte([d]))
    assert r.outcome is Outcome.a_verifier
    assert r.constat.raisons == [RaisonCode.ecart_sous_seuil]
    assert r.constat.montant_en_jeu == D("0.63")


def test_taux_specifique():
    d = _dec(taxation("doc_dec1", base_quantite="120", taux="3.50", montant="420.00", nature=TauxNature.specifique))
    assert _un(contexte([d])).outcome is Outcome.conforme
    d = _dec(taxation("doc_dec1", base_quantite="120", taux="3.50", montant="480.00", nature=None), total="480.00")
    r = _un(contexte([d]))  # nature déduite de la seule base présente
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("60.00")


def test_lecture_ocr_douteuse():
    # 52,28 imprimé, lu « 82,28 » par l'OCR (5 et 8 de la même classe) : l'écart s'explique par la lecture
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="82.28", brut_montant="82,28",
                      methode="ocr", confiance=0.95), qualite=QualiteTexte.ocr)
    r = _un(contexte([d]))
    assert r.outcome is Outcome.a_verifier
    assert RaisonCode.lecture_douteuse in r.constat.raisons


def test_ocr_sans_confusion_possible_reste_certain_si_confiance():
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="418.20", methode="ocr", confiance=0.95),
             qualite=QualiteTexte.ocr, total="418.20")
    r = _un(contexte([d]))
    assert r.outcome is Outcome.ecart_certain


def test_confiance_insuffisante_et_non_verifiable():
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="418.20", confiance=0.8))
    r = _un(contexte([d]))
    assert r.outcome is Outcome.a_verifier and RaisonCode.confiance_insuffisante in r.constat.raisons
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="418.20", confiance=0.4))
    r = _un(contexte([d]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.confiance_insuffisante
    d = _dec(taxation("doc_dec1", base="2091.00", taux=None, montant="418.20"))
    r = _un(contexte([d]))
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.valeur_absente


def test_rattachement_faible():
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="418.20"))
    r = _un(contexte([d], force=ForceLien.faible))
    assert r.outcome is Outcome.a_verifier and r.constat.raisons == [RaisonCode.rattachement_faible]


def test_forfait_exclu_et_plusieurs_lignes():
    d = _dec(
        taxation("doc_dec1", article="1", base="1000", taux="2", montant="20.00"),
        taxation("doc_dec1", article=None, type_taxe="FPE", categorie=CategorieTaxe.forfait_petits_envois,
                 base_quantite="3", taux="3", montant="9", nature=TauxNature.specifique),
        taxation("doc_dec1", article="1", type_taxe="B00", categorie=CategorieTaxe.tva, base="1020", taux="20",
                 montant="204.00"),
    )
    rs = b1_base_taux_montant(contexte([d]))
    assert [r.outcome for r in rs] == [Outcome.conforme, Outcome.conforme]
    assert rs[0].unite != rs[1].unite and rs[1].unite.endswith("tax:2")


def test_sans_declaration():
    rs = b1_base_taux_montant(contexte([]))
    assert rs[0].outcome is Outcome.non_verifiable and rs[0].raison_code is RaisonCode.document_manquant


def test_seule_la_derniere_version_est_controlee():
    v1 = declaration(id="doc_v1", mrn="26FR0000000000001A", version="1",
                     taxations=[taxation("doc_v1", base="100", taux="2", montant="99")])
    v2 = declaration(id="doc_v2", mrn="26FR0000000000001B", version="2",
                     taxations=[taxation("doc_v2", base="100", taux="2", montant="2.00")])
    rs = b1_base_taux_montant(contexte([v1, v2]))
    assert len(rs) == 1 and rs[0].documents_concernes == ["doc_v2"] and rs[0].outcome is Outcome.conforme


def test_reproductible_et_via_le_moteur():
    d = _dec(taxation("doc_dec1", base="2091.00", taux="2.5", montant="418.20"))
    a = run_controls(contexte([d]), controles=["B1"])
    b = run_controls(contexte([d]), controles=["B1"])
    assert [r.model_dump() for r in a] == [r.model_dump() for r in b]
    assert a[0].constat.id.startswith("f_") and a[0].empreinte_tolerances
