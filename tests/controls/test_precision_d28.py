"""Écarts certains sur des documents jamais vus : assiette et grille du FAF (D4), périmètre de A4/A5, identités
imprimées des factures « TVA comprise » (D-2801 à D-2804). Données entièrement fictives construites ici."""

from decimal import Decimal as D

from controldone.controls import corroboration
from controldone.controls import famille_a as fa
from controldone.controls.context import ControlContext
from controldone.controls.framework import run_controls
from controldone.guardrails import check_text
from controldone.model import (
    BasePourcentage,
    CategorieTaxe,
    ChampsDeclaration,
    ChampsFactureCommerciale,
    DocumentReference,
    Entite,
    GrilleTarifaire,
    LigneFactureCommerciale,
    LigneFactureTransitaire,
    ModePoste,
    NatureLigne,
    Outcome,
    Partie,
    PosteGrille,
    PrestationsHorsGrille,
    ProfilTolerances,
    QualiteTexte,
    RaisonCode,
    StatutGrille,
    Transitaire,
    TypeDocument,
)
from controldone.model.enums import RAISON_LIBELLES, Methode
from controldone.testing import declaration, document, dossier_pour, facture_transitaire, taxation, vs

N = NatureLigne
TVA_TRANSITAIRE = "FR11000555550"  # transitaire FICTIF
TVA_TRANSITAIRE_2 = "FR52000666660"  # second transitaire FICTIF
TVA_CLIENT = "FR68000458570"  # entité FICTIVE du client
MRN_A = "26FRAAAAAAAAAAAAA1"
MRN_B = "26FRBBBBBBBBBBBBB2"
MRN_X = "26FRXQXQXQXQXQXQX7"  # MRN FICTIF d'un envoi dont la déclaration n'est pas au dossier
ENTITES = [Entite(id="ent_1", raison_sociale="Maison FICTIVE SAS", tva=TVA_CLIENT)]
TRANSITAIRES = [
    Transitaire(id="tra_1", nom="Transit FICTIF", tva=TVA_TRANSITAIRE),
    Transitaire(id="tra_2", nom="Douane FICTIVE", tva=TVA_TRANSITAIRE_2),
]


def _grille(transitaire="tra_1", pourcentage="2", minimum="15.00", maximum=None):
    return GrilleTarifaire(
        transitaire_id=transitaire,
        reference=f"DEV-FICTIF-{transitaire}",
        statut=StatutGrille.validee,
        prestations_hors_grille=PrestationsHorsGrille.interdites,
        postes=[
            PosteGrille(
                code_poste="DEDOU", nature=N.frais_dedouanement, mode=ModePoste.forfait, prix=D("60.00")
            ),
            PosteGrille(
                code_poste="FAF",
                nature=N.frais_avance_fonds,
                mode=ModePoste.pourcentage,
                pourcentage=D(pourcentage),
                minimum=D(minimum) if minimum else None,
                maximum=D(maximum) if maximum else None,
                base_pourcentage=BasePourcentage.debours_total,
            ),
        ],
    )


GRILLE = _grille()


def _v(fid, nom, val, **kw):
    return None if val is None else vs(f"facture_transitaire.lignes[].{nom}", val, document_id=fid, **kw)


def ligne(nature, montant, *, mrn=None, fid="doc_ft1", **kw):
    return LigneFactureTransitaire(
        libelle=_v(fid, "libelle", nature.value.replace("_", " ")),
        nature=nature,
        montant_ht=_v(fid, "montant_ht", montant),
        mrn=_v(fid, "mrn", mrn),
        **{k: _v(fid, k, x) for k, x in kw.items()},
    )


def ft(*lignes, fid="doc_ft1", mrns=(MRN_A,), emetteur_tva=TVA_TRANSITAIRE, numero="FA-FICTIF-28", **totaux):
    champs = {k: vs(f"facture_transitaire.{k}", x, document_id=fid) for k, x in totaux.items()}
    em = (
        Partie(tva=vs("facture_transitaire.emetteur.tva", emetteur_tva, document_id=fid))
        if emetteur_tva
        else Partie()
    )
    return facture_transitaire(
        id=fid,
        numero=vs("facture_transitaire.numero", numero, document_id=fid),
        date=vs("facture_transitaire.date", "2026-09-15", document_id=fid),
        emetteur=em,
        client_facture=Partie(tva=vs("facture_transitaire.client_facture.tva", TVA_CLIENT, document_id=fid)),
        refs_mrn=[vs("facture_transitaire.refs_mrn[]", m, document_id=fid) for m in mrns],
        lignes=list(lignes),
        **champs,
    )


def dec(did="doc_dec", mrn=MRN_A, *, droits="1000.00", tva=None):
    tx = [taxation(did, categorie=CategorieTaxe.droit, type_taxe="A00", montant=droits)]
    if tva is not None:
        tx.append(taxation(did, categorie=CategorieTaxe.tva, type_taxe="B00", montant=tva))
    d = declaration(id=did, mrn=mrn, taxations=tx)
    d.dec.importateur = Partie(tva=vs("declaration.importateur.tva", TVA_CLIENT, document_id=did))
    return d


def ctx_de(docs, *, grilles=(GRILLE,), transitaire_dossier=None):
    dossier = dossier_pour(docs, id="dos_a")
    if transitaire_dossier is not None:
        dossier = dossier.model_copy(update={"transitaire_id": transitaire_dossier})
    return ControlContext.construire(
        dossier,
        docs,
        ProfilTolerances(id="tol_test"),
        execution_id="exe_test",
        grilles=list(grilles),
        entites=ENTITES,
        transitaires=TRANSITAIRES,
        exiger_lecture_corroboree=False,
    )


def d4(docs, **kw):
    return [r for r in run_controls(ctx_de(docs, **kw), controles=["D4"]) if r.controle_id == "D4"]


def un_d4(docs, **kw):
    xs = [r for r in d4(docs, **kw) if r.constat is not None]
    assert len(xs) == 1, xs
    return xs[0]


def test_libelles_des_raisons_nouvelles():
    for code in (
        RaisonCode.assiette_non_etablie,
        RaisonCode.grille_non_attestee,
        RaisonCode.perimetre_non_etabli,
    ):
        texte = RAISON_LIBELLES[code]
        assert texte.startswith("à vérifier") and check_text(texte) == []


# --- D-2801 : facture de débours séparée -----------------------------------------------------------------------


def test_d4_facture_de_debours_separee_dont_une_ligne_est_perdue():
    """Facture de prestations FICTIVE (FAF 45,00, aucune ligne de débours) et facture de débours séparée, scannée :
    seule la ligne de droits (500,00) est lue alors que son total des débours imprimé est 2 000,00. La facture de
    prestations est complète (Σ lignes = total HT) mais l'assiette ne l'est pas."""
    services = ft(
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A),
        ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A),
        total_ht="105.00",
    )
    debours = ft(
        ligne(N.debours_droits, "500.00", mrn=MRN_A, fid="doc_ft2"),
        fid="doc_ft2",
        numero="FA-FICTIF-29",
        total_debours="2000.00",
    )
    r = un_d4([dec(droits="500.00", tva="1500.00"), services, debours])
    assert r.outcome is Outcome.a_verifier and RaisonCode.valeur_absente in r.constat.raisons
    assert r.details["factures_de_debours_non_confirmees"] == ["doc_ft2"]


def test_d4_facture_de_debours_separee_complete_reste_certain():
    services = ft(
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A, taux_tva="20"),
        ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A, taux_tva="20"),
        total_ht="105.00",
        total_tva="21.00",
    )
    debours = ft(
        ligne(N.debours_droits, "500.00", mrn=MRN_A, fid="doc_ft2"),
        fid="doc_ft2",
        numero="FA-FICTIF-29",
        total_debours="500.00",
    )
    r = un_d4([dec(droits="500.00"), services, debours])
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("30.00")


# --- D-2801 : FAF par envoi ou par facture ----------------------------------------------------------------------


def _deux_envois(*faf, total_debours="2000.00"):
    return ft(
        ligne(N.debours_droits, "1000.00", mrn=MRN_A),
        ligne(N.debours_droits, "1000.00", mrn=MRN_B),
        *faf,
        mrns=(MRN_A, MRN_B),
        total_debours=total_debours,
    )


def test_d4_deux_faf_sans_mrn_sur_une_facture_de_deux_envois():
    """Deux lignes de FAF sans MRN : chacune porte sur un envoi, lequel n'est pas établi."""
    f = _deux_envois(ligne(N.frais_avance_fonds, "20.00"), ligne(N.frais_avance_fonds, "70.00"))
    rs = [r for r in d4([dec("doc_a", MRN_A), dec("doc_b", MRN_B), f]) if r.constat is not None]
    assert rs and all(r.outcome is Outcome.a_verifier for r in rs)
    assert all("faf_par_envoi_non_ventile" in r.details["assiette_non_etablie"] for r in rs)


def test_d4_un_faf_pour_deux_envois_minimum_par_envoi_ou_par_facture():
    """2 % de 2 × 100,00 : minimum 15,00 par facture, 30,00 par envoi ; FAF facturé 60,00. Le montant de l'écart
    dépend de la convention, que les documents ne fixent pas."""
    f = _deux_envois(ligne(N.frais_avance_fonds, "60.00"), total_debours="200.00")
    f.ft.lignes[0].montant_ht = _v("doc_ft1", "montant_ht", "100.00")
    f.ft.lignes[1].montant_ht = _v("doc_ft1", "montant_ht", "100.00")
    r = un_d4([dec("doc_a", MRN_A, droits="100.00"), dec("doc_b", MRN_B, droits="100.00"), f])
    assert r.outcome is Outcome.a_verifier
    assert r.details["assiette_non_etablie"] == ["bornes_par_envoi_ou_par_facture"]


def test_d4_faf_par_mrn_sur_un_releve_reste_certain():
    f = _deux_envois(
        ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A), ligne(N.frais_avance_fonds, "20.00", mrn=MRN_B)
    )
    rs = {
        r.constat.montant_en_jeu: r
        for r in d4([dec("doc_a", MRN_A), dec("doc_b", MRN_B), f])
        if r.constat is not None
    }
    assert set(rs) == {D("25.00")} and rs[D("25.00")].outcome is Outcome.ecart_certain


# --- D-2801 : avoir mêlé au relevé ----------------------------------------------------------------------------


def test_d4_ligne_d_avoir_dans_les_debours():
    """Relevé FICTIF : droits 1 000,00 et une ligne d'avoir de droits −200,00 ; 2 % du net (16,00) ou du brut
    (20,00) : l'attendu dépend de la convention."""
    f = ft(
        ligne(N.debours_droits, "1000.00", mrn=MRN_A),
        ligne(N.debours_droits, "-200.00", mrn=MRN_A),
        ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A),
        total_debours="800.00",
    )
    r = un_d4([dec(droits="800.00"), f])
    assert r.outcome is Outcome.a_verifier
    assert "avoirs_dans_les_debours" in r.details["assiette_non_etablie"]


# --- D-2802 : grille de l'émetteur de la facture ----------------------------------------------------------------


def test_d4_emetteur_non_identifie_grille_non_attestee():
    f = ft(
        ligne(N.debours_droits, "1000.00", mrn=MRN_A),
        ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A),
        emetteur_tva=None,
        total_debours="1000.00",
    )
    r = un_d4([dec(), f], transitaire_dossier="tra_1")
    assert r.outcome is Outcome.a_verifier and RaisonCode.grille_non_attestee in r.constat.raisons
    assert r.details["grille_non_attestee"] == "emetteur_non_identifie"


def test_grille_du_transitaire_qui_emet_la_facture():
    """Dossier rattaché au transitaire 1 (sa première facture) ; une facture du transitaire 2 y est rangée : elle se
    compare à la grille du transitaire 2 (3 %, 30,00 attendus), pas à celle du transitaire 1 (2 %)."""
    g2 = _grille("tra_2", pourcentage="3")
    f = ft(
        ligne(N.debours_droits, "1000.00", mrn=MRN_A),
        ligne(N.frais_avance_fonds, "30.00", mrn=MRN_A),
        emetteur_tva=TVA_TRANSITAIRE_2,
        total_debours="1000.00",
    )
    (r,) = d4([dec(), f], grilles=(GRILLE, g2), transitaire_dossier="tra_1")
    assert r.outcome is Outcome.conforme


# --- D-2803 : périmètre de A4 / A5 --------------------------------------------------------------------------------

FC, DEC = "doc_fc1", "doc_dec1"


def _fc(id=FC, *, numero="INV-FICTIF-001", total="10000.00", lignes=(), page_total=1, pages=(1,)):
    c = ChampsFactureCommerciale(
        numero=vs("facture_commerciale.numero", numero, document_id=id),
        total_facture=vs("facture_commerciale.total_facture", total, document_id=id, page=page_total),
        devise=vs("facture_commerciale.devise", "EUR", document_id=id),
        acheteur=Partie(tva=vs("facture_commerciale.acheteur.tva", TVA_CLIENT, document_id=id)),
        lignes=list(lignes),
    )
    return document(TypeDocument.facture_commerciale, c, id=id, qualite=QualiteTexte.natif, pages=pages)


def _decl(*, montant="10000.00", refs=(), id=DEC, mrn=MRN_A):
    c = ChampsDeclaration(
        mrn=vs("declaration.mrn", mrn, document_id=id),
        montant_total_facture=vs("declaration.montant_total_facture", montant, document_id=id),
        devise_facture=vs("declaration.devise_facture", "EUR", document_id=id),
        importateur=Partie(tva=vs("declaration.importateur.tva", TVA_CLIENT, document_id=id)),
        date_acceptation=vs("declaration.date_acceptation", "2026-08-14", document_id=id),
        documents_references=[
            DocumentReference(
                type_code=vs("declaration.documents_references[].type_code", code, document_id=id),
                reference=vs("declaration.documents_references[].reference", ref, document_id=id),
            )
            for code, ref in refs
        ],
    )
    return document(TypeDocument.declaration, c, id=id, qualite=QualiteTexte.natif)


def _a4(docs):
    dossier = dossier_pour(docs)
    ctx = ControlContext.construire(
        dossier,
        docs,
        ProfilTolerances(id="tol_test"),
        entites=ENTITES,
        execution_id="exe_test",
        transitaires=TRANSITAIRES,
    )
    (r,) = [r for r in fa.a4_valeur_facturee(ctx) if r.sous_controle is None]
    return r


def test_a4_facture_citee_par_la_declaration_absente_du_dossier():
    """La déclaration cite deux factures (N380) ; une seule est au dossier : l'excédent déclaré peut être l'autre."""
    r = _a4([_fc(), _decl(montant="14500.00", refs=[("N380", "INV-FICTIF-001"), ("N380", "INV-FICTIF-002")])])
    assert r.outcome is Outcome.a_verifier and RaisonCode.perimetre_non_etabli in r.constat.raisons
    assert r.details["perimetre_non_etabli"] == ["facture_citee_absente"]


def test_a4_seule_facture_citee_presente_reste_certain():
    r = _a4([_fc(), _decl(montant="14500.00", refs=[("N380", "INV-FICTIF-001"), ("N740", "LTA-FICTIVE-9")])])
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("4500.00")


def test_a4_declaration_de_l_envoi_absente():
    """La facture du transitaire cite le MRN de la déclaration du dossier et un autre MRN qu'aucune déclaration lue
    ne porte : la facture commerciale peut être répartie sur cette autre déclaration (déclaré < facture)."""
    f = ft(ligne(N.debours_droits, "100.00", mrn=MRN_A), mrns=(MRN_A, MRN_X), total_debours="100.00")
    r = _a4([_fc(), _decl(montant="6000.00"), f])
    assert r.outcome is Outcome.a_verifier
    assert r.details["perimetre_non_etabli"] == ["declaration_citee_absente"]


def test_a4_facteur_puissance_de_dix():
    r = _a4([_fc(total="1234567"), _decl(montant="1234.567")])
    assert r.outcome is Outcome.a_verifier and "facteur_puissance_de_dix" in r.details["perimetre_non_etabli"]


def test_a4_total_facture_negatif():
    r = _a4([_fc(total="-10000.00"), _decl(montant="10000.00")])
    assert r.outcome is Outcome.a_verifier and "montant_negatif_lu" in r.details["perimetre_non_etabli"]


def test_a4_total_de_page_lu_avant_des_lignes():
    """Facture FICTIVE de deux pages : le total retenu (page 1) précède une ligne imprimée page 2 (report)."""
    lignes = [
        LigneFactureCommerciale(
            montant_ligne=vs("facture_commerciale.lignes[].montant_ligne", m, document_id=FC, page=p)
        )
        for m, p in (("6000.00", 1), ("4000.00", 2))
    ]
    r = _a4([_fc(total="6000.00", lignes=lignes, pages=(1, 2)), _decl(montant="10000.00")])
    assert (
        r.outcome is Outcome.a_verifier and "total_lu_avant_des_lignes" in r.details["perimetre_non_etabli"]
    )


def test_a4_ecart_ordinaire_reste_certain():
    r = _a4([_fc(), _decl(montant="10900.00")])
    assert r.outcome is Outcome.ecart_certain and "perimetre_non_etabli" not in r.details


# --- D-2804 : identités imprimées d'une facture « TVA comprise » -----------------------------------------------

FT = "doc_ft1"


def _lv(nom, val, **kw):
    return None if val is None else vs(f"facture_transitaire.lignes[].{nom}", val, document_id=FT, **kw)


def _ligne_g(nature, *, ht=None, ttc=None, taux=None, taux_deduit=False):
    return LigneFactureTransitaire(
        libelle=_lv("libelle", nature.value),
        nature=nature,
        montant_ht=_lv("montant_ht", ht),
        montant_ttc=_lv("montant_ttc", ttc),
        taux_tva=(
            _lv(
                "taux_tva",
                taux,
                methode=Methode.derive,
                confiance=0.60,
                regle_derivation="taux_normal_fictif",
            )
            if taux_deduit
            else _lv("taux_tva", taux)
        ),
    )


def _ft_g(*lignes, **totaux):
    champs = {k: vs(f"facture_transitaire.{k}", x, document_id=FT) for k, x in totaux.items()}
    return facture_transitaire(
        id=FT,
        numero=vs("facture_transitaire.numero", "FT-FICTIF-28", document_id=FT),
        lignes=list(lignes),
        **champs,
    )


class _Tol:
    def t_ligne(self):
        return D("0.01")

    def t_somme(self, n):
        return D("0.01") * n

    def taxe_ligne_concorde(self, montant, calcul):
        return abs(montant - calcul) <= D("0.01")


def _identites(f):
    return {i.cle: i for i in corroboration.reseau(f, lambda v: v is not None and v.est_lisible, _Tol())}


def test_somme_des_debours_sans_hors_taxe_des_prestations():
    """Facture FICTIVE à lignes « TVA comprise » : les prestations n'impriment que leur TTC ; les débours (sans
    TVA) impriment leur montant. Σ débours = total des débours imprimé confirme les lignes de débours."""
    f = _ft_g(
        _ligne_g(N.debours_droits, ht="536.18", ttc="536.18"),
        _ligne_g(N.debours_tva, ht="3280.40", ttc="3280.40"),
        _ligne_g(N.frais_dedouanement, ttc="70.80", taux="20"),
        total_debours="3816.58",
        total_ttc="3887.38",
    )
    ids = _identites(f)
    assert ids["ft:total_debours"].tient
    assert corroboration.lecture_confirmee(list(ids.values()), f.ft.lignes[1].montant_ht.id)


def test_somme_des_debours_ligne_perdue_ne_confirme_rien():
    f = _ft_g(
        _ligne_g(N.debours_tva, ht="3280.40", ttc="3280.40"),
        _ligne_g(N.frais_dedouanement, ttc="70.80", taux="20"),
        total_debours="3816.58",
    )
    assert not _identites(f)["ft:total_debours"].tient


def test_somme_des_ttc_des_lignes_egale_au_total_ttc():
    f = _ft_g(
        _ligne_g(N.debours_droits, ht="536.18", ttc="536.18"),
        _ligne_g(N.frais_dedouanement, ttc="70.80", taux="20"),
        _ligne_g(N.frais_avance_fonds, ttc="137.40", taux="20"),
        total_ttc="744.38",
    )
    i = _identites(f)["ft:ttc_lignes"]
    assert i.tient and i.portee == "tout"
    assert not _identites(_ft_g(*f.ft.lignes, total_ttc="844.38"))["ft:ttc_lignes"].tient


def test_total_tva_confirme_par_le_taux_normal_deduit():
    """Taux de ligne non imprimés (déduits) : Σ HT des prestations × 20 % = total de TVA lu (64,19)."""
    f = _ft_g(
        _ligne_g(N.debours_droits, ht="853.59", taux="0", taux_deduit=True),
        _ligne_g(N.frais_dedouanement, ht="85.00", taux="20", taux_deduit=True),
        _ligne_g(N.transport, ht="235.93", taux="20", taux_deduit=True),
        total_tva="64.19",
    )
    i = _identites(f)["ft:tva_base_taux_deduits"]
    assert i.tient and f.ft.total_tva.id in i.confirmes
    assert not any(lg.taux_tva.id in i.membres for lg in f.ft.lignes)
    faux = _ft_g(*f.ft.lignes, total_tva="69.19")
    assert not _identites(faux)["ft:tva_base_taux_deduits"].tient


# --- D-2801 : complétude par le total HT : une ligne de débours prise pour une prestation ------------------------


def test_d4_droits_lus_comme_prestation_sans_total_des_debours():
    """Télécopie FICTIVE sans total des débours : la ligne de droits (1 000,00) a un libellé illisible et passe pour
    une prestation. Σ lignes = total HT tient, mais le total de TVA imprimé (12,00 = 20 % de 60,00) ne correspond
    pas à une ligne de 1 000,00 au taux normal : l'assiette (TVA seule) n'est pas établie."""
    f = ft(
        ligne(N.debours_tva, "2000.00", mrn=MRN_A),
        ligne(N.autre_prestation, "1000.00", mrn=MRN_A, taux_tva="20"),
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A, taux_tva="20"),
        ligne(N.frais_avance_fonds, "60.00", mrn=MRN_A, taux_tva="20"),
        total_ht="3120.00",
        total_tva="24.00",
    )
    r = un_d4([dec(droits="1000.00", tva="2000.00"), f])
    assert r.outcome is Outcome.a_verifier and RaisonCode.valeur_absente in r.constat.raisons


def test_d4_completude_par_total_ht_et_total_tva_reste_certain():
    f = ft(
        ligne(N.debours_droits, "1000.00", mrn=MRN_A, taux_tva="0"),
        ligne(N.frais_dedouanement, "60.00", mrn=MRN_A, taux_tva="20"),
        ligne(N.frais_avance_fonds, "45.00", mrn=MRN_A, taux_tva="20"),
        total_ht="1105.00",
        total_tva="21.00",
    )
    r = un_d4([dec(), f])
    assert r.outcome is Outcome.ecart_certain and r.constat.montant_en_jeu == D("25.00")


# --- D-2805 : B2, ligne de taxe d'un article perdue -----------------------------------------------------------


def _b2(*taxations, total):
    from controldone.controls.famille_b import b2_sommes_taxes
    from controldone.testing import contexte

    d = declaration(
        id="doc_dec",
        taxations=taxations,
        total_droits_taxes=vs("declaration.total_droits_taxes", total, document_id="doc_dec"),
    )
    return [r for r in b2_sommes_taxes(contexte([d])) if r.sous_controle == "total" and r.constat is not None]


def test_b2_article_au_nombre_de_lignes_inegal_et_ligne_sans_code():
    """Scan FICTIF : l'article 1 a ses droits et sa TVA ; l'article 2 n'a qu'une ligne, au code illisible ; le total
    imprimé (53,17) dépasse la somme lue (51,58) du montant d'une ligne perdue."""
    tx = [
        taxation("doc_dec", article="1", type_taxe="A00", montant="5.98"),
        taxation("doc_dec", article="1", type_taxe="B00", categorie=CategorieTaxe.tva, montant="33.52"),
        taxation("doc_dec", article="2", type_taxe="", categorie=CategorieTaxe.tva, montant="12.08"),
    ]
    assert _b2(*tx, total="53.17") == []
    # D-4208 : la ligne perdue explique l'écart dans ce sens (total > somme lue) : impossible de conclure.
    from controldone.controls.famille_b import b2_sommes_taxes
    from controldone.testing import contexte

    d = declaration(
        id="doc_dec",
        taxations=tx,
        total_droits_taxes=vs("declaration.total_droits_taxes", "53.17", document_id="doc_dec"),
    )
    (r,) = [x for x in b2_sommes_taxes(contexte([d])) if x.sous_controle == "total"]
    assert r.outcome is Outcome.non_verifiable and r.details["motif"] == "lignes_possiblement_non_lues"
    # Écart de sens contraire (total < somme lue) : une ligne non lue ne l'explique pas, le constat reste.
    (r,) = _b2(*tx, total="41.58")
    assert r.outcome is Outcome.a_verifier and RaisonCode.structure_non_validee in r.constat.raisons


def test_b2_articles_au_meme_nombre_de_lignes_structure_validee():
    tx = [
        taxation("doc_dec", article="1", type_taxe="A00", montant="5.98"),
        taxation("doc_dec", article="1", type_taxe="B00", categorie=CategorieTaxe.tva, montant="33.52"),
        taxation("doc_dec", article="2", type_taxe="A00", montant="1.59"),
        taxation("doc_dec", article="2", type_taxe="B00", categorie=CategorieTaxe.tva, montant="12.08"),
    ]
    (r,) = _b2(*tx, total="63.17")
    assert RaisonCode.structure_non_validee not in r.constat.raisons and r.constat.montant_en_jeu == D(
        "10.00"
    )
