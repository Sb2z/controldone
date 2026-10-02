"""Famille F — doublons entre dossiers d'un même client (SPEC §15). Données fictives."""

from decimal import Decimal as D

from controldone.controls.context import AutreDossier
from controldone.controls.famille_f import (
    f1_document_en_double,
    f2_numero_reutilise,
    f3_declaration_refacturee_deux_fois,
    f4_prestation_facturee_deux_fois,
    f5_facture_sur_plusieurs_declarations,
)
from controldone.controls.framework import run_controls
from controldone.guardrails import check_text
from controldone.model import (
    ChampsAvoir,
    DocumentReference,
    ForceLien,
    LigneFactureTransitaire,
    NatureLigne,
    NatureMontant,
    Outcome,
    Partie,
    RaisonCode,
    TypeDocument,
)
from controldone.testing import (
    contexte,
    declaration,
    document,
    dossier_pour,
    facture_commerciale,
    facture_transitaire,
    taxation,
    vs,
)

MRN = "26FR00000000000001"
MRN2 = "26FR00000000777001"


def esp(s):
    return s.replace("\xa0", " ")


def autre(*docs, id="dos_autre", force=ForceLien.forte):
    return AutreDossier(dossier_pour(docs, id=id, force=force), {d.id: d for d in docs})


def ft(id, numero, date, *lignes, total=None, emetteur="Transit Fictif SA", refs_mrn=()):
    def f(champ, val):
        return vs(f"facture_transitaire.{champ}", val, document_id=id)

    return facture_transitaire(
        id=id, numero=f("numero", numero), date=f("date", date), emetteur=Partie(nom=f("emetteur.nom", emetteur)),
        lignes=[ln(id, *x) if isinstance(x, tuple) else x for x in lignes],
        total_ttc=f("total_ttc", total) if total else None, refs_mrn=[f("refs_mrn[]", m) for m in refs_mrn],
    )


def ln(doc, montant, nature=NatureLigne.debours_droits, mrn=MRN, ref=None):
    def f(champ, val):
        return vs(f"facture_transitaire.{champ}", val, document_id=doc)

    return LigneFactureTransitaire(nature=nature, montant_ht=f("lignes[].montant_ht", montant),
                                   mrn=f("lignes[].mrn", mrn) if mrn else None,
                                   ref_transport=f("lignes[].ref_transport", ref) if ref else None)


def propre(r):
    assert check_text(r.constat.libelle) == [] and check_text(r.constat.prochaine_action) == []


def un(rs):
    assert len(rs) == 1, rs
    return rs[0]


# --- F1 ---------------------------------------------------------------------------------------------------


def test_f1_meme_identite_dans_un_autre_dossier():
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",))
    nouveau = ft("doc_0002", "FT-001", "2026-08-01", ("50.00",))
    ancien.identite = nouveau.identite = "a" * 64
    rs = f1_document_en_double(contexte([nouveau], autres_dossiers=[autre(ancien)]))
    r = un(rs)
    assert r.outcome is Outcome.a_verifier and r.constat.autres_dossiers == ["dos_autre"]
    assert r.constat.montant_en_jeu is None and "dos_autre" in r.constat.libelle
    propre(r)
    # l'occurrence la plus ancienne ne porte pas le constat
    assert un(f1_document_en_double(contexte([ancien], autres_dossiers=[autre(nouveau)]))).outcome is Outcome.conforme


def test_f1_doublon_marque_dans_le_dossier():
    a = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",))
    b = ft("doc_0002", "FT-001", "2026-08-01", ("50.00",))
    b.doublon_de = a.id
    rs = {r.unite: r for r in f1_document_en_double(contexte([a, b]))}
    assert rs["doc:doc_0001"].outcome is Outcome.conforme
    assert rs["doc:doc_0002"].outcome is Outcome.a_verifier


# --- F2 ---------------------------------------------------------------------------------------------------


def test_f2_numero_reutilise():
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",), total="60.00")
    nouveau = ft("doc_0002", "FT 001", "2026-09-01", ("80.00",), total="96.00")
    r = un(f2_numero_reutilise(contexte([nouveau], autres_dossiers=[autre(ancien)])))
    assert r.outcome is Outcome.a_verifier and "96,00 EUR contre 60,00 EUR" in esp(r.constat.libelle)
    propre(r)
    r = un(f2_numero_reutilise(contexte([ancien], autres_dossiers=[autre(nouveau)])))
    assert r.outcome is Outcome.non_applicable and r.raison_code is RaisonCode.couvert_par_autre_controle


def test_f2_meme_total_ou_autre_emetteur():
    a = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",), total="60.00")
    b = ft("doc_0002", "FT-001", "2026-09-01", ("50.00",), total="60.00")
    assert un(f2_numero_reutilise(contexte([b], autres_dossiers=[autre(a)]))).outcome is Outcome.conforme
    c = ft("doc_0003", "FT-001", "2026-09-01", ("80.00",), total="96.00", emetteur="Autre Transit Fictif")
    assert un(f2_numero_reutilise(contexte([c], autres_dossiers=[autre(a)]))).outcome is Outcome.conforme


# --- F3 ---------------------------------------------------------------------------------------------------


def test_f3_meme_mrn_refacture_deux_fois_certain():
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",))
    nouveau = ft("doc_0002", "FT-002", "2026-09-01", ("50.00",))
    r = un(f3_declaration_refacturee_deux_fois(contexte([nouveau], autres_dossiers=[autre(ancien)])))
    c = r.constat
    assert r.outcome is Outcome.ecart_certain and c.raisons == []
    assert c.montant_en_jeu == D("50.00") and c.nature_montant is NatureMontant.recouvrable
    assert c.autres_dossiers == ["dos_autre"] and "doc_0001" in {p.document_id for p in c.preuves}
    assert "FT-002" in c.libelle and "FT-001" in c.libelle and MRN in c.libelle
    assert r.unite == f"ft:doc_0002|mrn:{MRN[:15]}"
    propre(r)
    # le dossier de la facture la plus ancienne ne porte pas le constat
    r = un(f3_declaration_refacturee_deux_fois(contexte([ancien], autres_dossiers=[autre(nouveau)])))
    assert r.outcome is Outcome.non_applicable and r.details["dossier"] == "dos_autre"


def test_f3_facture_complementaire_conforme():
    dec = declaration(id="doc_dec", mrn=MRN, taxations=[taxation("doc_dec", base="1000", taux="10", montant="100.00")])
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("60.00",))
    nouveau = ft("doc_0002", "FT-002", "2026-09-01", ("40.00",))
    r = un(f3_declaration_refacturee_deux_fois(contexte([dec, nouveau], autres_dossiers=[autre(ancien)])))
    assert r.outcome is Outcome.conforme and r.details["complementaire"] is True


def test_f3_annulee_par_avoir():
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",))
    nouveau = ft("doc_0002", "FT-002", "2026-09-01", ("50.00",))
    av = document(TypeDocument.avoir, ChampsAvoir(
        numero=vs("avoir.numero", "AV-1", document_id="doc_av"),
        refs_facture_origine=[vs("avoir.refs_facture_origine[]", "FT-001", document_id="doc_av")],
        lignes=[LigneFactureTransitaire(nature=NatureLigne.debours_droits,
                                        montant_ht=vs("avoir.lignes[].montant_ht", "50.00", document_id="doc_av"))],
    ), id="doc_av")
    r = un(f3_declaration_refacturee_deux_fois(contexte([nouveau], autres_dossiers=[autre(ancien, av)])))
    assert r.outcome is Outcome.conforme and r.details["annulee_par_avoir"] is True


def test_f3_meme_dossier_non_applicable():
    a = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",))
    b = ft("doc_0002", "FT-002", "2026-09-01", ("50.00",))
    rs = f3_declaration_refacturee_deux_fois(contexte([a, b]))
    assert all(r.outcome is Outcome.non_applicable and r.details["couvert_par"] == "C5" for r in rs)


def test_f3_a_verifier_montants_differents_mrn_non_lu_ou_lien_faible():
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("30.00",))
    nouveau = ft("doc_0002", "FT-002", "2026-09-01", ("50.00",))
    r = un(f3_declaration_refacturee_deux_fois(contexte([nouveau], autres_dossiers=[autre(ancien)])))
    assert r.outcome is Outcome.a_verifier and r.constat.montant_en_jeu == D("50.00")
    # MRN lu seulement en en-tête de l'autre facture (affectation §12.2) : toujours certain s'il est lu
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("50.00", NatureLigne.debours_droits, None), refs_mrn=(MRN,))
    r = un(f3_declaration_refacturee_deux_fois(contexte([nouveau], autres_dossiers=[autre(ancien)])))
    assert r.outcome is Outcome.ecart_certain
    # aucun MRN imprimé sur l'autre facture : rattachement impossible -> pas de doublon détecté
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("50.00", NatureLigne.debours_droits, None))
    r = un(f3_declaration_refacturee_deux_fois(contexte([nouveau], autres_dossiers=[autre(ancien)])))
    assert r.outcome is Outcome.conforme
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",))
    r = un(f3_declaration_refacturee_deux_fois(
        contexte([nouveau], autres_dossiers=[autre(ancien, force=ForceLien.faible)])))
    assert r.outcome is Outcome.a_verifier and RaisonCode.rattachement_faible in r.constat.raisons


def test_f3_fenetre_de_recherche():
    ancien = ft("doc_0001", "FT-001", "2024-01-15", ("50.00",))
    nouveau = ft("doc_0002", "FT-002", "2026-09-01", ("50.00",))
    r = un(f3_declaration_refacturee_deux_fois(contexte([nouveau], autres_dossiers=[autre(ancien)])))
    assert r.outcome is Outcome.conforme


def test_f3_sans_facture_transitaire():
    r = un(f3_declaration_refacturee_deux_fois(contexte([declaration(id="doc_dec", mrn=MRN)])))
    assert r.outcome is Outcome.non_applicable and r.raison_code is RaisonCode.facture_transitaire_absente


# --- F4 ---------------------------------------------------------------------------------------------------


def test_f4_meme_prestation():
    presta = ("45.00", NatureLigne.frais_dedouanement, None, "999-11112222")
    ancien = ft("doc_0001", "FT-001", "2026-08-01", presta)
    nouveau = ft("doc_0002", "FT-002", "2026-09-01", ("45.00", NatureLigne.frais_dedouanement, None, "99911112222"))
    r = un(f4_prestation_facturee_deux_fois(contexte([nouveau], autres_dossiers=[autre(ancien)])))
    assert r.outcome is Outcome.a_verifier and r.constat.montant_en_jeu == D("45.00")
    assert r.constat.composante.value == "prestation"
    propre(r)
    autre_montant = ft("doc_0002", "FT-002", "2026-09-01", ("46.00", NatureLigne.frais_dedouanement, None,
                                                            "999-11112222"))
    r = un(f4_prestation_facturee_deux_fois(contexte([autre_montant], autres_dossiers=[autre(ancien)])))
    assert r.outcome is Outcome.conforme


# --- F5 ---------------------------------------------------------------------------------------------------


def fc_doc(id="doc_fc", total="1000.00"):
    def f(champ, val):
        return vs(f"facture_commerciale.{champ}", val, document_id=id)

    return facture_commerciale(id=id, numero=f("numero", "INV-2026-001"), total_facture=f("total_facture", total),
                               devise=f("devise", "EUR"), date=f("date", "2026-07-20"))


def dec_f5(id, mrn, montant, date):
    def d(champ, val):
        return vs(f"declaration.{champ}", val, document_id=id)

    return declaration(
        id=id, mrn=mrn, montant_total_facture=d("montant_total_facture", montant),
        devise_facture=d("devise_facture", "EUR"), date_acceptation=d("date_acceptation", date),
        documents_references=[DocumentReference(type_code=d("documents_references[].type_code", "N380"),
                                                reference=d("documents_references[].reference", "INV 2026 001"))],
    )


def test_f5_facture_sur_plusieurs_declarations():
    ici = dec_f5("doc_dec2", MRN2, "700.00", "2026-09-01")
    ailleurs = dec_f5("doc_dec1", MRN, "600.00", "2026-08-01")
    r = un(f5_facture_sur_plusieurs_declarations(contexte([fc_doc(), ici], autres_dossiers=[autre(ailleurs)])))
    c = r.constat
    assert r.outcome is Outcome.a_verifier and c.montant_en_jeu == D("300.00")
    assert c.nature_montant is NatureMontant.ecart_documentaire and c.autres_dossiers == ["dos_autre"]
    assert "1 300,00 EUR" in esp(c.libelle)
    propre(r)
    # le dossier de la déclaration la plus ancienne ne porte pas le constat
    r = un(f5_facture_sur_plusieurs_declarations(contexte([fc_doc(), ailleurs], autres_dossiers=[autre(ici)])))
    assert r.outcome is Outcome.non_applicable


def test_f5_envois_partiels_conformes():
    ici = dec_f5("doc_dec2", MRN2, "400.00", "2026-09-01")
    ailleurs = dec_f5("doc_dec1", MRN, "600.00", "2026-08-01")
    r = un(f5_facture_sur_plusieurs_declarations(contexte([fc_doc(), ici], autres_dossiers=[autre(ailleurs)])))
    assert r.outcome is Outcome.conforme


def test_f5_versions_du_meme_mrn_ne_comptent_qu_une_fois():
    v1 = dec_f5("doc_dec1", MRN, "700.00", "2026-08-01")
    v2 = dec_f5("doc_dec2", MRN[:15] + "ZZZ", "700.00", "2026-08-03")
    r = un(f5_facture_sur_plusieurs_declarations(contexte([fc_doc(), v1, v2])))
    assert r.outcome is Outcome.conforme


def test_moteur_famille_f():
    ancien = ft("doc_0001", "FT-001", "2026-08-01", ("50.00",))
    nouveau = ft("doc_0002", "FT-002", "2026-09-01", ("50.00",))
    rs = run_controls(contexte([nouveau], autres_dossiers=[autre(ancien)]), controles=["F1", "F2", "F3", "F4", "F5"])
    f3 = [r for r in rs if r.controle_id == "F3"]
    assert f3[0].outcome is Outcome.ecart_certain and f3[0].constat.motif_blocage is None
