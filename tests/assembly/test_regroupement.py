"""Regroupement en dossiers (SPEC §7.5) — données fictives."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from controldone.model import (
    ArticleDeclaration,
    ChampsAvoir,
    ChampsDeclaration,
    ChampsFactureCommerciale,
    ChampsFactureTransitaire,
    ChampsSupport,
    DocumentReference,
    Fichier,
    ForceLien,
    LigneFactureCommerciale,
    LigneFactureTransitaire,
    MethodeAllocation,
    NatureLigne,
    Partie,
    RoleLien,
    SignalLien,
    TaxationDeclaration,
    Transitaire,
    TypeDocument,
)
from controldone.regroupement import (
    OptionsRegroupement,
    cle_idempotence_regroupement,
    force_depuis_score,
    frontieres,
    regrouper,
)
from controldone.testing import document, vs

MRN1 = "26FR0000000000AAA1"
MRN2 = "26FR0000000000BBB2"
TVA = "FR32000123459"


class Lot:
    """Petit constructeur de lot : fichiers + documents fictifs."""

    def __init__(self) -> None:
        self.fichiers: dict[str, Fichier] = {}
        self.docs = []

    def fichier(self, chemin: str) -> str:
        fid = "fic_" + hashlib.sha256(chemin.encode()).hexdigest()[:32]
        if fid not in self.fichiers:
            self.fichiers[fid] = Fichier(
                id=fid,
                nom_original=chemin.rsplit("/", 1)[-1],
                chemin_relatif=chemin,
                sha256=hashlib.sha256(chemin.encode()).hexdigest(),
                taille=1,
                type_mime="application/pdf",
            )
        return fid

    def ajouter(self, type_doc, champs, chemin, *, id, pages=(1,)):
        d = document(type_doc, champs, id=id, pages=pages, fichier_id=self.fichier(chemin))
        self.docs.append(d)
        return d

    def fc(
        self,
        id,
        chemin,
        *,
        numero="INV-10001",
        total="1000.00",
        devise="USD",
        tva=TVA,
        transport=None,
        codes=("847130",),
    ):
        c = ChampsFactureCommerciale(
            numero=vs("facture_commerciale.numero", numero, document_id=id),
            devise=vs("facture_commerciale.devise", devise, document_id=id),
            total_facture=vs("facture_commerciale.total_facture", total, document_id=id),
            acheteur=Partie(tva=vs("facture_commerciale.acheteur.tva", tva, document_id=id)),
            ref_transport=vs("facture_commerciale.ref_transport", transport, document_id=id)
            if transport
            else None,
            lignes=[
                LigneFactureCommerciale(
                    code_marchandise_imprime=vs(
                        "facture_commerciale.lignes[].code_marchandise_imprime", c, document_id=id
                    )
                )
                for c in codes
            ],
        )
        return self.ajouter(TypeDocument.facture_commerciale, c, chemin, id=id)

    def dec(
        self,
        id,
        chemin,
        *,
        mrn=MRN1,
        refs=(),
        montant="1000.00",
        devise="USD",
        tva=TVA,
        version=None,
        codes=("8471300000",),
        taxes=("50.00",),
        date_acc="2026-08-01",
        articles_refs=None,
    ):
        c = ChampsDeclaration(
            mrn=vs("declaration.mrn", mrn, document_id=id),
            version=vs("declaration.version", version, document_id=id) if version else None,
            date_acceptation=vs("declaration.date_acceptation", date_acc, document_id=id),
            devise_facture=vs("declaration.devise_facture", devise, document_id=id),
            montant_total_facture=vs("declaration.montant_total_facture", montant, document_id=id)
            if montant
            else None,
            importateur=Partie(tva=vs("declaration.importateur.tva", tva, document_id=id)),
            documents_references=[
                DocumentReference(
                    type_code=vs("declaration.documents_references[].type_code", code, document_id=id),
                    reference=vs("declaration.documents_references[].reference", ref, document_id=id),
                )
                for code, ref in refs
            ],
            articles=[
                ArticleDeclaration(
                    code_marchandise=vs("declaration.articles[].code_marchandise", c, document_id=id),
                    references_facture=[
                        vs("declaration.articles[].references_facture[]", r, document_id=id)
                        for r, _m in (articles_refs or {}).get(i, [])
                    ],
                    montant_facture_article=(
                        vs(
                            "declaration.articles[].montant_facture_article",
                            (articles_refs or {})[i][0][1],
                            document_id=id,
                        )
                        if articles_refs and i in articles_refs
                        else None
                    ),
                )
                for i, c in enumerate(codes)
            ],
            taxations=[
                TaxationDeclaration(montant=vs("declaration.taxations[].montant", t, document_id=id))
                for t in taxes
            ],
        )
        return self.ajouter(TypeDocument.declaration, c, chemin, id=id)

    def ft(
        self,
        id,
        chemin,
        *,
        numero="FT-500",
        mrns=(MRN1,),
        lignes=(("debours_droits", "50.00", None),),
        transports=(),
        emetteur_tva=None,
        total_debours=None,
    ):
        c = ChampsFactureTransitaire(
            numero=vs("facture_transitaire.numero", numero, document_id=id),
            refs_mrn=[vs("facture_transitaire.refs_mrn[]", m, document_id=id) for m in mrns],
            refs_transport=[
                vs("facture_transitaire.refs_transport[]", t, document_id=id) for t in transports
            ],
            emetteur=Partie(
                tva=vs("facture_transitaire.emetteur.tva", emetteur_tva, document_id=id)
                if emetteur_tva
                else None
            ),
            lignes=[
                LigneFactureTransitaire(
                    nature=NatureLigne(n),
                    montant_ht=vs("facture_transitaire.lignes[].montant_ht", m, document_id=id),
                    mrn=vs("facture_transitaire.lignes[].mrn", mrn, document_id=id) if mrn else None,
                )
                for n, m, mrn in lignes
            ],
            total_debours=vs("facture_transitaire.total_debours", total_debours, document_id=id)
            if total_debours
            else None,
        )
        return self.ajouter(TypeDocument.facture_transitaire, c, chemin, id=id)

    def avoir(self, id, chemin, *, origine="FT-500", mrns=()):
        c = ChampsAvoir(
            numero=vs("avoir.numero", "AV-1", document_id=id),
            refs_facture_origine=[vs("avoir.refs_facture_origine[]", origine, document_id=id)]
            if origine
            else [],
            refs_mrn=[vs("avoir.refs_mrn[]", m, document_id=id) for m in mrns],
        )
        return self.ajouter(TypeDocument.avoir, c, chemin, id=id)

    def support(self, id, chemin, *, transport=None, refs_facture=()):
        c = ChampsSupport(
            ref_transport_maitre=vs("document_support.ref_transport_maitre", transport, document_id=id)
            if transport
            else None,
            refs_facture=[vs("document_support.refs_facture[]", r, document_id=id) for r in refs_facture],
        )
        return self.ajouter(TypeDocument.document_support, c, chemin, id=id)

    def regrouper(self, **kw):
        kw.setdefault("options", OptionsRegroupement(annee=2026))
        return regrouper(self.docs, self.fichiers, **kw)


def _lien(dossier, doc_id):
    lien = dossier.lien(doc_id)
    assert lien is not None, f"{doc_id} absent du dossier"
    return lien


def _dossier_de(res, doc_id):
    ds = [d for d in res.dossiers if d.lien(doc_id)]
    assert len(ds) == 1, f"{doc_id} dans {len(ds)} dossiers"
    return ds[0]


# --- cas nominaux ----------------------------------------------------------------------------------


def test_dossier_simple_liens_forts_et_graine():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.dec("dec1", "docs/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/ft.pdf")
    res = lot.regrouper()
    assert len(res.dossiers) == 1
    d = res.dossiers[0]
    assert d.reference == "D-2026-00001"
    graine = _lien(d, "fc1")
    assert graine.force is ForceLien.forte and SignalLien.graine in graine.signaux  # D-013
    ldec = _lien(d, "dec1")
    assert ldec.role is RoleLien.declaration and ldec.force is ForceLien.forte
    assert SignalLien.ref_facture_citee in ldec.signaux and SignalLien.montant_egal in ldec.signaux
    lft = _lien(d, "ft1")
    assert lft.force is ForceLien.forte and SignalLien.mrn_cite in lft.signaux
    assert not d.incomplet and d.documents_manquants == []
    assert d.cles.mrn == [MRN1] and d.cles.num_facture_commerciale == ["INV-10001"]
    assert d.cles.num_facture_transitaire == ["FT-500"]
    methodes = {(a.source_document_id, a.methode) for a in d.allocations}
    assert ("fc1", MethodeAllocation.totalite) in methodes and ("ft1", MethodeAllocation.totalite) in methodes


def test_un_lien_par_document():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.dec("dec1", "docs/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/ft.pdf")
    d = lot.regrouper().dossiers[0]
    ids = [lien.document_id for lien in d.liens]
    assert len(ids) == len(set(ids)) == 3


def test_score_2_est_un_rattachement_faible():
    # seul signal : montant égal (moyenne = 2) -> lien faible (P4)
    lot = Lot()
    lot.fc("fc1", "docs/a/fc.pdf")
    lot.dec("dec1", "docs/b/dec.pdf", refs=[], tva="FR00000000000")
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    d = _dossier_de(res, "dec1")
    lien = _lien(d, "dec1")
    assert lien.score == 2 and lien.force is ForceLien.faible and lien.signaux == [SignalLien.montant_egal]


def test_score_moyen_sans_reference_explicite_n_est_pas_fort():
    lot = Lot()
    lot.fc("fc1", "docs/envoi.pdf")
    lot.dec("dec1", "docs/envoi.pdf", refs=[], tva="FR00000000000")  # même fichier (2) + montant égal (2) = 4
    d = lot.regrouper().dossiers[0]
    lien = _lien(d, "dec1")
    assert lien.score == 4 and lien.force is ForceLien.moyenne


def test_force_depuis_score():
    assert force_depuis_score(1, []) is None
    assert force_depuis_score(2, [SignalLien.ref_transport]) is ForceLien.faible
    assert force_depuis_score(3, [SignalLien.ref_transport]) is ForceLien.forte
    assert force_depuis_score(3, [SignalLien.montant_egal, SignalLien.tva]) is ForceLien.moyenne


def test_tva_et_codes_communs_seuls_ne_suffisent_pas():
    lot = Lot()
    lot.fc("fc1", "docs/x/fc.pdf", total="999.00")
    lot.dec("dec1", "docs/y/dec.pdf", montant="5000.00")  # TVA + SH6 communs : faible (1) < 2
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    assert len(res.dossiers) == 2
    orphelin = _dossier_de(res, "dec1")
    assert orphelin.incomplet and orphelin.documents_manquants == ["facture_commerciale"]
    assert _lien(orphelin, "dec1").signaux == [SignalLien.graine]


def test_reference_de_transport_commune():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", transport="AWB 999-11112222", total="1.00")
    lot.dec("dec1", "docs/dec.pdf", refs=[("N741", "99911112222")], montant="777.00")
    d = _dossier_de(lot.regrouper(), "dec1")
    lien = _lien(d, "dec1")
    assert SignalLien.ref_transport in lien.signaux and lien.force is ForceLien.forte


def test_chaine_document_support_vers_transport():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", total="1.00")
    lot.support("bl1", "docs/bl.pdf", transport="MSCU1234567", refs_facture=["INV-10001"])
    lot.dec("dec1", "docs/dec.pdf", refs=[("N705", "MSCU1234567")], montant="9.00")
    d = _dossier_de(lot.regrouper(), "dec1")
    assert SignalLien.ref_transport in _lien(d, "dec1").signaux
    assert _lien(d, "bl1").role is RoleLien.support and _lien(d, "bl1").force is ForceLien.forte


# --- frontières -------------------------------------------------------------------------------------


def test_frontiere_dure_entre_sous_dossiers():
    lot = Lot()
    lot.fc("fc1", "docs/exp1/fc.pdf")
    lot.dec("dec1", "docs/exp1/dec.pdf", refs=[("N380", "INV-10001")])
    lot.fc("fc2", "docs/exp2/fc.pdf")
    # même numéro de facture et même MRN : la frontière l'emporte
    lot.dec("dec2", "docs/exp2/dec.pdf", refs=[("N380", "INV-10001")], mrn=MRN2)
    res = lot.regrouper()
    assert len(res.dossiers) == 2
    d1, d2 = _dossier_de(res, "fc1"), _dossier_de(res, "fc2")
    assert d1.lien("dec1") and not d1.lien("dec2")
    assert d2.lien("dec2") and not d2.lien("dec1")
    assert res.frontiere_document["fc1"] == "docs/exp1"


def test_frontiere_au_parent_contenant_des_types_differents():
    lot = Lot()
    lot.fc("fc1", "docs/factures/fc.pdf")
    lot.dec("dec1", "docs/declarations/dec.pdf", refs=[("N380", "INV-10001")])
    f = frontieres(lot.docs, lot.fichiers)
    assert f["fc1"] == f["dec1"] == ("docs",)
    assert len(lot.regrouper().dossiers) == 1


def test_document_a_la_racine_peut_rejoindre_un_sous_dossier():
    lot = Lot()
    lot.fc("fc1", "docs/exp1/fc.pdf")
    lot.dec("dec1", "docs/exp1/dec.pdf", refs=[("N380", "INV-10001")])
    lot.fc("fc2", "docs/exp2/fc.pdf", numero="INV-20002")
    lot.dec("dec2", "docs/exp2/dec.pdf", refs=[("N380", "INV-20002")], mrn=MRN2)
    # facture mensuelle du transitaire à la racine, qui cite les deux MRN
    lot.ft(
        "ft1",
        "docs/releve.pdf",
        mrns=(MRN1, MRN2),
        lignes=(("debours_droits", "50.00", MRN1), ("debours_droits", "50.00", MRN2)),
    )
    res = lot.regrouper()
    assert len(res.dossiers) == 2
    for dossier, dec_id in ((_dossier_de(res, "fc1"), "dec1"), (_dossier_de(res, "fc2"), "dec2")):
        assert _lien(dossier, "ft1").force is ForceLien.forte
        allocs = [a for a in dossier.allocations if a.source_document_id == "ft1"]
        assert len(allocs) == 1 and allocs[0].methode is MethodeAllocation.ligne_par_mrn
        assert allocs[0].cible_document_id == dec_id and allocs[0].montant_alloue == Decimal("50.00")


def test_courriels_sont_des_frontieres_sauf_reference_explicite():
    lot = Lot()
    lot.fc("fc1", "mail1/fc.pdf")
    lot.dec("dec1", "mail1/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft_sans_ref", "mail2/ft.pdf", mrns=(), lignes=(("debours_droits", "50.00", None),))
    lot.ft("ft_ref", "mail3/ft.pdf", numero="FT-501", mrns=(MRN1,))
    courriels = {
        lot.fichier("mail1/fc.pdf"): "<m1@fictif>",
        lot.fichier("mail1/dec.pdf"): "<m1@fictif>",
        lot.fichier("mail2/ft.pdf"): "<m2@fictif>",
        lot.fichier("mail3/ft.pdf"): "<m3@fictif>",
    }
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, courriels=courriels))
    d = _dossier_de(res, "fc1")
    assert d.lien("ft_ref") is not None  # MRN commun explicite
    assert d.lien("ft_sans_ref") is None  # montant égal seul ne franchit pas la frontière du courriel
    orphelin = _dossier_de(res, "ft_sans_ref")
    assert orphelin.incomplet


# --- graines multiples, allocations --------------------------------------------------------------------


def test_plusieurs_factures_pour_une_declaration():
    lot = Lot()
    lot.fc("fc1", "docs/fc1.pdf", numero="INV-10001", total="600.00")
    lot.fc("fc2", "docs/fc2.pdf", numero="INV-10002", total="400.00")
    lot.dec(
        "dec1",
        "docs/dec.pdf",
        refs=[("N380", "INV-10001"), ("N380", "INV-10002")],
        montant="1000.00",
        codes=("8471300000", "8471300000"),
        articles_refs={0: [("INV-10001", "600.00")], 1: [("INV-10002", "400.00")]},
    )
    res = lot.regrouper()
    assert len(res.dossiers) == 1
    d = res.dossiers[0]
    assert {lien.document_id for lien in d.liens} == {"fc1", "fc2", "dec1"}
    allocs = {a.source_document_id: a for a in d.allocations if a.cible_document_id == "dec1"}
    assert allocs["fc1"].methode is MethodeAllocation.reference_explicite
    assert allocs["fc1"].montant_alloue == Decimal("600.00")
    assert allocs["fc2"].montant_alloue == Decimal("400.00")


def test_facture_repartie_sur_plusieurs_declarations_au_prorata():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", total="1000.00", transport="MSCU7654321")
    lot.dec("dec1", "docs/dec1.pdf", refs=[("N705", "MSCU7654321")], montant="300.00")
    lot.dec("dec2", "docs/dec2.pdf", refs=[("N705", "MSCU7654321")], montant="900.00", mrn=MRN2)
    d = lot.regrouper().dossiers[0]
    allocs = {a.cible_document_id: a for a in d.allocations if a.source_document_id == "fc1"}
    assert allocs["dec1"].methode is MethodeAllocation.prorata
    assert allocs["dec1"].montant_alloue == Decimal("250.00")
    assert allocs["dec2"].montant_alloue == Decimal("750.00")


def test_facture_repartie_avec_references_explicites():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", total="1000.00")
    lot.dec("dec1", "docs/dec1.pdf", refs=[("N380", "INV-10001")], montant="300.00")
    lot.dec("dec2", "docs/dec2.pdf", refs=[("N380", "INV-10001")], montant="700.00", mrn=MRN2)
    d = lot.regrouper().dossiers[0]
    allocs = {a.cible_document_id: a for a in d.allocations if a.source_document_id == "fc1"}
    assert {a.methode for a in allocs.values()} == {MethodeAllocation.reference_explicite}
    assert allocs["dec1"].montant_alloue == Decimal("300.00")


def test_lignes_sans_mrn_sur_facture_multi_mrn_au_prorata():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", total="1000.00")
    lot.dec("dec1", "docs/dec1.pdf", refs=[("N380", "INV-10001")], montant="500.00", taxes=("10.00",))
    lot.dec(
        "dec2", "docs/dec2.pdf", refs=[("N380", "INV-10001")], montant="500.00", mrn=MRN2, taxes=("30.00",)
    )
    lot.ft(
        "ft1",
        "docs/ft.pdf",
        mrns=(MRN1, MRN2),
        lignes=(("debours_droits", "40.00", None), ("frais_dedouanement", "60.00", None)),
    )
    d = lot.regrouper().dossiers[0]
    allocs = {a.cible_document_id: a for a in d.allocations if a.source_document_id == "ft1"}
    assert allocs["dec1"].methode is MethodeAllocation.prorata and allocs["dec1"].source_ligne == 0
    assert allocs["dec1"].montant_alloue == Decimal("10.00") and allocs["dec2"].montant_alloue == Decimal(
        "30.00"
    )


# --- versions rectificatives ---------------------------------------------------------------------------


def test_versions_rectificatives_rattachees_derniere_retenue():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.dec("dec_v1", "docs/dec_v1.pdf", refs=[("N380", "INV-10001")], version="1")
    # version rectifiée : MRN au préfixe stable identique, ne cite plus la facture
    lot.dec(
        "dec_v2",
        "docs/dec_v2.pdf",
        mrn=MRN1[:15] + "ZZZ",
        refs=[],
        version="2",
        montant=None,
        date_acc="2026-08-05",
        tva="FR00000000000",
    )
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    assert len(res.dossiers) == 1
    d = res.dossiers[0]
    assert d.lien("dec_v2") is not None and SignalLien.mrn_cite in d.lien("dec_v2").signaux
    assert d.cles.mrn == [MRN1[:15] + "ZZZ"]  # seule la dernière version figure dans les clés
    allocs = [a for a in d.allocations if a.source_document_id == "fc1"]
    assert [a.cible_document_id for a in allocs] == ["dec_v2"]


# --- avoirs, orphelins, repli ----------------------------------------------------------------------------


def test_avoir_rattache_par_facture_origine():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.dec("dec1", "docs/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/ft.pdf")
    lot.avoir("av1", "docs/av.pdf", origine="FT-500")
    d = lot.regrouper().dossiers[0]
    lien = _lien(d, "av1")
    assert lien.role is RoleLien.avoir and lien.force is ForceLien.forte
    assert SignalLien.ref_facture_citee in lien.signaux


def test_avoir_par_mrn_est_moyen_donc_faible():
    # MRN d'une déclaration rattachée seulement par le même dossier source (aucun appui solide) : faible
    lot = Lot()
    lot.fc("fc1", "docs/a/fc.pdf", tva="FR00000000000")
    lot.dec("dec1", "docs/a/dec.pdf", montant=None)
    lot.avoir("av1", "docs/a/av.pdf", origine=None, mrns=(MRN1,))
    res = lot.regrouper()
    d = _dossier_de(res, "av1")
    assert _lien(d, "dec1").force is ForceLien.faible
    lien = _lien(d, "av1")
    assert lien.score == 2 and lien.force is ForceLien.faible


def test_avoir_par_mrn_d_une_declaration_solide_est_moyen():
    # D-3702 : le MRN cité est celui d'une déclaration solidement rattachée -> « moyenne », jamais « forte »
    lot = Lot()
    lot.fc("fc1", "docs/a/fc.pdf")
    lot.dec("dec1", "docs/a/dec.pdf", refs=[("N380", "INV-10001")])
    lot.avoir("av1", "docs/b/av.pdf", origine=None, mrns=(MRN1,))
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    lien = _lien(_dossier_de(res, "av1"), "av1")
    assert lien.force is ForceLien.moyenne and SignalLien.reference_proche in lien.signaux


def test_facture_transitaire_orpheline_devient_un_dossier_incomplet():
    lot = Lot()
    lot.fc("fc1", "docs/a/fc.pdf")
    lot.dec("dec1", "docs/a/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/b/ft.pdf", mrns=(MRN2,), lignes=(("debours_droits", "999.00", None),))
    lot.support("x1", "docs/b/notes.pdf")
    res = lot.regrouper()
    assert len(res.dossiers) == 2
    orphelin = _dossier_de(res, "ft1")
    assert orphelin.incomplet and set(orphelin.documents_manquants) == {"facture_commerciale", "declaration"}
    assert _lien(orphelin, "ft1").signaux == [SignalLien.graine]
    assert _lien(orphelin, "x1").signaux == [SignalLien.meme_dossier_source]


def test_repli_meme_source_dossier_unique():
    # P1 : pas de déclaration ; la facture transitaire cite un MRN absent -> même dossier source (faible)
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.ft("ft1", "docs/ft.pdf", mrns=(MRN2,))
    res = lot.regrouper()
    assert len(res.dossiers) == 1
    d = res.dossiers[0]
    assert d.incomplet and d.documents_manquants == ["declaration"]
    lien = _lien(d, "ft1")
    assert lien.force is ForceLien.faible and lien.signaux == [SignalLien.meme_dossier_source]


def test_consolidation_facture_sans_declaration_dans_un_dossier_complet():
    lot = Lot()
    lot.fc("fc1", "docs/fc1.pdf", numero="INV-10001")
    lot.fc("fc2", "docs/fc2.pdf", numero="INV-77777", total="5.00")
    lot.dec("dec1", "docs/dec.pdf", refs=[("N380", "INV-10001")])
    res = lot.regrouper()
    assert len(res.dossiers) == 1
    lien = _lien(res.dossiers[0], "fc2")
    assert lien.force is ForceLien.faible and SignalLien.meme_dossier_source in lien.signaux


def test_sans_repli_meme_source():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.ft("ft1", "docs/ft.pdf", mrns=(MRN2,))
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    assert len(res.dossiers) == 2


def test_non_exploitable_et_inconnu():
    lot = Lot()
    lot.fc("fc1", "docs/a/fc.pdf")
    lot.dec("dec1", "docs/a/dec.pdf", refs=[("N380", "INV-10001")])
    lot.fc("fc2", "docs/b/fc.pdf", numero="INV-20002")
    lot.ajouter(TypeDocument.inconnu, None, "docs/scan.pdf", id="inc1")
    lot.ajouter(TypeDocument.document_non_exploitable, None, "docs/c/pre_alerte.pdf", id="ne1")
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    assert "inc1" in res.non_rattaches
    d = _dossier_de(res, "ne1")
    assert _lien(d, "ne1").role is RoleLien.support and d.incomplet


def test_doublon_suit_son_original():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.dec("dec1", "docs/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/ft.pdf")
    dup = lot.ft("ft1bis", "docs/ft_copie.pdf")
    dup.doublon_de = "ft1"
    d = lot.regrouper().dossiers[0]
    assert d.lien("ft1bis") is not None and d.lien("ft1bis").role is RoleLien.facture_transitaire


def test_transitaire_identifie_par_tva():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.dec("dec1", "docs/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/ft.pdf", emetteur_tva="FR11000000017")
    t = Transitaire(id="T3", nom="TRANSIT FICTIF", tva="FR11000000017")
    d = lot.regrouper(transitaires=[t]).dossiers[0]
    assert d.transitaire_id == "T3"


# --- déterminisme ---------------------------------------------------------------------------------------


def _scenario():
    lot = Lot()
    lot.fc("fc1", "docs/exp1/fc.pdf")
    lot.dec("dec1", "docs/exp1/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/exp1/ft.pdf")
    lot.fc("fc2", "docs/exp2/fc.pdf", numero="INV-20002")
    lot.dec("dec2", "docs/exp2/dec.pdf", refs=[("N380", "INV-20002")], mrn=MRN2)
    return lot


def test_deterministe_et_identifiants_stables():
    a = _scenario().regrouper()
    b = _scenario().regrouper()
    assert [d.model_dump(exclude={"cree_le", "modifie_le"}) for d in a.dossiers] == [
        d.model_dump(exclude={"cree_le", "modifie_le"}) for d in b.dossiers
    ]
    assert [d.reference for d in a.dossiers] == ["D-2026-00001", "D-2026-00002"]


def test_ne_modifie_pas_les_documents():
    lot = _scenario()
    avant = [d.model_dump() for d in lot.docs]
    lot.regrouper()
    assert [d.model_dump() for d in lot.docs] == avant


def test_cle_idempotence_independante_de_l_ordre():
    assert cle_idempotence_regroupement(["b", "a"]) == cle_idempotence_regroupement(["a", "b", "a"])
    assert cle_idempotence_regroupement(["a"]) != cle_idempotence_regroupement(["a", "b"])


@pytest.mark.parametrize("vide", [[], None])
def test_lot_vide(vide):
    assert regrouper(vide or []).dossiers == []


# --- D-708 : documents support co-localisés, lettre d'accompagnement de la facture transitaire ----------------


def test_support_co_localise_lien_moyen_sans_alerte_p4():
    lot = Lot()
    lot.fc("fc1", "docs/envoi.pdf")
    lot.dec("dec1", "docs/dec.pdf", refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/envoi.pdf", numero="FAC-7700")
    lot.support("cg1", "docs/envoi.pdf")  # conditions générales dans le même PDF
    lot.support("lettre1", "docs/envoi.pdf", refs_facture=["FAC-7700"])  # lettre d'accompagnement
    lot.support("mail1", "docs/courriel.pdf")  # seul dossier de la frontière
    d = _dossier_de(lot.regrouper(), "cg1")
    assert _lien(d, "cg1").force is ForceLien.moyenne
    assert _lien(d, "mail1").force is ForceLien.moyenne
    lettre = _lien(d, "lettre1")
    assert lettre.force is ForceLien.forte and SignalLien.ref_facture_citee in lettre.signaux


def test_repartition_prorata_demi_vers_le_haut_et_reliquat():
    # §8.2 : ROUND_HALF_UP ; la somme des parts vaut le total (reliquat sur la dernière part), D-1207
    from decimal import Decimal as D

    from controldone.regroupement import repartir_prorata

    assert repartir_prorata(D("20.25"), [D("1"), D("1")]) == [D("10.13"), D("10.12")]
    assert repartir_prorata(D("100.00"), [D("1"), D("1"), D("1")]) == [D("33.33"), D("33.33"), D("33.34")]
    assert repartir_prorata(D("10.00"), [D("1"), None]) == [D("10.00"), None]
    assert repartir_prorata(None, [D("1")]) == [None]


# --- généralisation (D-2110 à D-2112) ------------------------------------------------------------------


def test_pdf_fusionne_sans_reference_ne_reunit_pas_les_dossiers():
    """PDF fusionné « facture, déclaration, facture, déclaration » : « même fichier » vaut pour tous les dossiers ;
    la déclaration sans autre signal va au dossier de la facture qui la précède, sans réunir les dossiers."""
    lot = Lot()

    def page(n):
        d = lot.docs[-1]
        lot.docs[-1] = document(
            d.type, d.champs, id=d.id, pages=(n,), fichier_id=lot.fichier("docs/scan.pdf")
        )

    lot.fc("fc1", "docs/scan.pdf", numero="INV-10001", tva=None)
    page(1)
    lot.dec("dec1", "docs/scan.pdf", mrn=MRN1, montant=None, tva=None)
    page(2)
    lot.fc("fc2", "docs/scan.pdf", numero="INV-20002", total="777.00", tva=None)
    page(3)
    lot.dec("dec2", "docs/scan.pdf", mrn=MRN2, montant=None, tva=None)
    page(4)
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    assert len(res.dossiers) == 2
    assert _dossier_de(res, "dec1") is _dossier_de(res, "fc1")
    assert _dossier_de(res, "dec2") is _dossier_de(res, "fc2")
    assert _lien(_dossier_de(res, "dec2"), "dec2").force is ForceLien.faible  # P4 : rattachement faible


def test_reference_tronquee_commune_a_plusieurs_factures_n_est_pas_citee():
    lot = Lot()
    lot.fc("fc1", "docs/a/fc1.pdf", numero="ODH 2026.4006", total="100.00", tva=None)
    lot.fc("fc2", "docs/a/fc2.pdf", numero="ODH 2026.4007", total="200.00", tva=None)
    lot.dec("dec1", "docs/a/dec1.pdf", refs=[("N380", "ODH 2026")], montant=None, tva=None)
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    for d in res.dossiers:
        lien = d.lien("dec1")
        assert lien is None or SignalLien.ref_facture_citee not in lien.signaux


def test_reference_exacte_reste_citee_meme_si_compatible_avec_une_autre():
    lot = Lot()
    lot.fc("fc1", "docs/fc1.pdf", numero="INV-10001", tva=None)
    lot.fc("fc2", "docs/fc2.pdf", numero="INV-10001-B", tva=None)
    lot.dec("dec1", "docs/dec1.pdf", refs=[("N380", "INV-10001")], montant=None, tva=None)
    res = lot.regrouper(options=OptionsRegroupement(annee=2026, meme_source=False))
    assert SignalLien.ref_facture_citee in _lien(_dossier_de(res, "dec1"), "dec1").signaux
    assert _dossier_de(res, "dec1") is _dossier_de(res, "fc1")


def test_declarations_sans_facture_de_mrn_differents_restent_distinctes():
    lot = Lot()
    lot.dec("dec1", "docs/envoi/dec1.pdf", mrn=MRN1)
    lot.dec("dec2", "docs/envoi/dec2.pdf", mrn=MRN2)
    lot.ft("ft1", "docs/envoi/ft.pdf", mrns=(MRN1, MRN2))
    res = lot.regrouper()
    assert _dossier_de(res, "dec1") is not _dossier_de(res, "dec2")
    assert sum(1 for d in res.dossiers if d.lien("ft1")) == 2  # facture mensuelle : dans les deux dossiers


def test_facture_repartie_sur_deux_declarations_par_repli_reste_possible():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", total="1000.00", tva=None)
    lot.dec("dec1", "docs/dec1.pdf", mrn=MRN1, refs=[("N380", "INV-10001")], montant="600.00")
    # MRN réaliste (11 caractères aléatoires) : MRN1 et MRN2 ne diffèrent que d'un caractère, soit deux lectures
    # d'un même MRN au sens de D-3702.
    lot.dec("dec2", "docs/dec2.pdf", mrn="26FRK7Q2ZP9XW4M1T8", montant="400.00", tva=None)
    res = lot.regrouper()
    assert len(res.dossiers) == 1
    assert _lien(res.dossiers[0], "dec2").force is ForceLien.faible


# --- D-3702 : lien faible renforcé par une référence retrouvée dans le dossier --------------------------------

MRN_A = "26FRG9YL3TE5MNH5W6"
MRN_B = "26FRNQAXEOLD2XTWZ0"  # autre envoi


def test_declaration_au_mrn_mal_lu_retrouve_sur_la_facture_du_transitaire():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", transport="DEMO609137653", tva="FR00000000000")
    lot.ft("ft1", "docs/ft.pdf", mrns=(MRN_A,), transports=("DEMO 6091 / 37653",))
    lot.dec("dec1", "docs/dec.pdf", mrn="26FRG9YL3TESMNHSW6", montant=None)  # 5 -> S : lecture OCR
    res = lot.regrouper()
    assert len(res.dossiers) == 1
    lien = _lien(res.dossiers[0], "dec1")
    assert lien.force is ForceLien.moyenne
    assert lien.signaux == [SignalLien.meme_dossier_source, SignalLien.reference_proche]


def test_facture_d_un_autre_envoi_reste_faible():
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf", transport="DEMO609137653")
    lot.dec("dec1", "docs/dec.pdf", mrn=MRN_A, refs=[("N380", "INV-10001")])
    lot.ft("ft1", "docs/ft1.pdf", mrns=(MRN_A,), transports=("DEMO609137653",))
    lot.ft(
        "ft9",
        "docs/ft9.pdf",
        numero="FT-900",
        mrns=(MRN_B,),
        transports=("DEMO087829269",),
        lignes=(("debours_droits", "999.00", None),),
    )
    res = lot.regrouper()
    d = _dossier_de(res, "ft1")
    assert _lien(d, "ft1").force is ForceLien.forte
    lien = _lien(_dossier_de(res, "ft9"), "ft9")
    assert lien.force is ForceLien.faible and SignalLien.reference_proche not in lien.signaux


def test_document_sans_reference_dans_le_fichier_d_un_document_solide():
    # page illisible d'un PDF « envoi complet » classée facture du transitaire : rien ne la contredit
    lot = Lot()
    lot.fc("fc1", "docs/fc.pdf")
    lot.dec("dec1", "docs/envoi.pdf", refs=[("N380", "INV-10001")])
    lot.ajouter(
        TypeDocument.facture_transitaire, ChampsFactureTransitaire(), "docs/envoi.pdf", id="ft1", pages=(3,)
    )
    res = lot.regrouper()
    lien = _lien(_dossier_de(res, "ft1"), "ft1")
    assert lien.force is ForceLien.moyenne and SignalLien.reference_proche in lien.signaux
