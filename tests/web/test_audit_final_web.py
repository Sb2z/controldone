"""Audit final, corrections de la plateforme côté web, API et MCP (D-1304, D-1315 à D-1319)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Mount

from controldone.auth.roles import Acteur, Role
from controldone.services.plateforme import RequeteInvalide

A = "demo_ateliers"
FONDATEUR = Acteur("usr_fondateur_demo", Role.fondateur)


def _api(monde, tenant=A):
    c = monde.client()
    c.headers["Authorization"] = f"Bearer {monde.cles[tenant]}"
    return c


def _routes(app):
    for r in app.routes:
        if isinstance(r, APIRoute):
            yield r
        elif isinstance(r, Mount) and hasattr(r.app, "routes"):
            yield from _routes(r.app)


# --- F-03 : aucune route ne fait de travail bloquant sur la boucle d'événements --------------------------------------


def test_f03_routes_synchrones(monde):
    asynchrones = [f"{sorted(r.methods)} {r.path}" for r in _routes(monde.app) if asyncio.iscoroutinefunction(r.endpoint)]
    assert asynchrones == []  # avant : dépôts, connexion (Argon2), finances, fondateur… en « async def »


# --- P0-1 : relevé d'écarts -> envoi déclaré -> avoir -> commission et brouillon de facture -------------------------


def _ecart_releve(monde):
    from controldone.litiges import DossierReclamation
    from controldone.services import reclamations
    from controldone.storage.models import Ecart, Reclamation

    with monde.pf.db.tenant(A, Acteur.systeme("tests"), lecture=True) as sc:
        existants = sc.lister(Reclamation)  # la démonstration prépare déjà un relevé validé
        transitaires = sorted({e.transitaire_id for e in sc.lister(Ecart) if e.transitaire_id and e.statut == "ouvert"})
    if not existants:
        reclamations.preparer_dossier(monde.pf, FONDATEUR, A, transitaires[0])
    with monde.pf.db.tenant(A, Acteur.systeme("tests"), lecture=True) as sc:
        rec = DossierReclamation.model_validate(sc.lister(Reclamation)[-1].contenu)
    return rec


def test_p0_1_suivi_par_l_api_passe_par_le_service_des_litiges(monde):
    from controldone.litiges import DossierReclamation
    from controldone.outbox import FileSortante
    from controldone.storage.models import Reclamation

    rec = _ecart_releve(monde)
    assert rec.statut.value == "valide" and rec.relances == []
    eid = rec.lignes[0].ecart_id
    c = _api(monde)
    r = c.post(f"/api/v1/suivi-avoirs/{eid}/evenements", json={"type": "releve_envoye"})
    assert r.status_code == 200 and r.json()["statut"] == "reclame"
    with monde.pf.db.tenant(A, Acteur.systeme("tests"), lecture=True) as sc:
        d = DossierReclamation.model_validate(sc.obtenir(Reclamation, rec.id).contenu)
    # avant : simple transition de l'écart, aucun rappel planifié (agent litiges sans objet)
    assert d.statut.value == "envoyee" and [x.jours for x in d.relances] == [15, 30, 45]
    montant = min(rec.lignes[0].ecart, Decimal("10.00"))
    r = c.post(f"/api/v1/litiges/{eid}/evenements",
               json={"type": "avoir_recu", "montant": f"{montant}".replace(".", ","), "reference": "AV-FICTIF-77"})
    assert r.status_code == 200 and r.json()["montant_credite_eur"] == f"{montant}"
    with monde.pf.db.tenant(A, Acteur.systeme("tests"), lecture=True) as sc:
        d = DossierReclamation.model_validate(sc.obtenir(Reclamation, rec.id).contenu)
    assert d.avoirs and d.commissions and d.commissions[0].base == montant  # avant : jamais de commission
    factures = [a for a in FileSortante(monde.pf.db).lister(FONDATEUR, kind="facture_emise")
                if a.tenant_id == A and (a.payload.get("references") or {}).get("avoir_id") == d.avoirs[0].avoir_id]
    assert len(factures) == 1


def test_p0_1_suivi_par_l_espace_client_jusqu_a_la_commission(monde):
    from aides_web import connecter_client, poster

    from controldone.litiges import DossierReclamation
    from controldone.storage.models import Reclamation

    rec = _ecart_releve(monde)
    eid = rec.lignes[0].ecart_id
    w = monde.client()
    connecter_client(w, monde)
    assert poster(w, "/espace/recouvrement", f"/espace/recouvrement/{eid}/reclame", {}).status_code == 303
    r = poster(w, "/espace/recouvrement", f"/espace/recouvrement/{eid}/avoir",
               {"montant": "1,00", "reference": "AV-FICTIF-WEB"})
    assert r.status_code == 303 and "Avoir enregistré" in w.get(r.headers["location"]).text
    with monde.pf.db.tenant(A, Acteur.systeme("tests"), lecture=True) as sc:
        d = DossierReclamation.model_validate(sc.obtenir(Reclamation, rec.id).contenu)
    assert d.statut.value != "valide" and d.relances and d.avoirs and d.commissions  # même chemin que l'API


def test_remboursement_d_une_administration_sans_commission(monde):
    from controldone.litiges import DossierReclamation
    from controldone.storage.models import Reclamation

    rec = _ecart_releve(monde)
    eid = rec.lignes[0].ecart_id
    c = _api(monde)
    c.post(f"/api/v1/litiges/{eid}/evenements", json={"type": "reclamation_envoyee"})
    r = c.post(f"/api/v1/litiges/{eid}/evenements",
               json={"type": "avoir_recu", "montant": "1.00", "reference": "REMB-DOUANE-FICTIF",
                     "origine": "administration"})
    assert r.status_code == 200
    with monde.pf.db.tenant(A, Acteur.systeme("tests"), lecture=True) as sc:
        d = DossierReclamation.model_validate(sc.obtenir(Reclamation, rec.id).contenu)
    assert d.avoirs[0].origine == "administration" and d.avoirs[0].hors_assiette and d.commissions == []


# --- P0-2 : une seule source pour les rappels -----------------------------------------------------------------------


def test_p0_2_rappels_lus_dans_les_reglages_du_client(monde):
    from datetime import UTC, datetime, timedelta

    from controldone.services import reclamations
    from controldone.storage.models import Ecart

    c = _api(monde)
    ouvert = next(x for x in c.get("/api/v1/litiges").json() if x["statut"] == "ouvert")
    c.post(f"/api/v1/litiges/{ouvert['litige_id']}/evenements", json={"type": "reclamation_envoyee"})
    il_y_a_20_jours = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    with monde.pf.db.tenant(A, Acteur.systeme("tests")) as sc:
        e = sc.obtenir(Ecart, ouvert["litige_id"])
        e.contenu = {**e.contenu, "reclame_le": il_y_a_20_jours}
    ligne = c.get(f"/api/v1/litiges/{ouvert['litige_id']}").json()
    assert ligne["relance_suggeree"] == "rappel suggéré (15 jours)" == ligne["rappel_suggere"]  # avant : aucune (30)
    with monde.pf.db.operateur(FONDATEUR) as op:
        reglages = next(dict(t.reglages or {}) for t in op.lister_clients() if t.id == A)
        op.modifier_client(A, reglages={**reglages, "relances_jours": [7, 14]})
    assert c.get(f"/api/v1/litiges/{ouvert['litige_id']}").json()["relance_suggeree"] == "rappel suggéré (14 jours)"
    assert reclamations.jours_relance({}) == (15, 30, 45)


# --- P1-7 : un seul analyseur strict des montants saisis ------------------------------------------------------------


@pytest.mark.parametrize("brut", ["NaN", "Infinity", "1e9", "-5", "abc", "1,2,3", "99999999999", ""])
def test_montants_invalides_refuses_par_l_api(monde, brut):
    c = _api(monde)
    ouvert = next(x for x in c.get("/api/v1/litiges").json() if x["statut"] == "ouvert")
    r = c.post(f"/api/v1/litiges/{ouvert['litige_id']}/evenements", json={"type": "avoir_recu", "montant": brut})
    assert r.status_code == 400  # avant : NaN / Infinity / 1e9 acceptés par Decimal() dans plusieurs routes


def test_montant_saisi_formats_admis():
    from controldone.services.saisie import montant_saisi

    for brut, attendu in (("1 234,56", "1234.56"), ("1 234,56", "1234.56"), ("1 234,56", "1234.56"),
                          ("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("12.5", "12.50"), ("40 €", "40.00"),
                          ("EUR 7", "7.00")):
        assert montant_saisi(brut) == Decimal(attendu)
    for brut in ("nan", "inf", "1E3", "+5", "12,345", "1 23,4", "0"):
        with pytest.raises(RequeteInvalide):
            montant_saisi(brut)
    assert montant_saisi("0", zero=True) == Decimal("0.00")


@pytest.mark.parametrize("prix", ["NaN", "Infinity", "1e3", "-5"])
def test_grille_csv_prix_invalide_refuse(prix):
    from controldone.services.admin import _postes_csv

    # avant : Decimal("NaN") / Decimal("1e3") / négatif acceptés dans la grille importée (P1-7)
    with pytest.raises(RequeteInvalide):
        _postes_csv(f"code_poste;prix\nDEDOUANEMENT;{prix}\n")
    assert _postes_csv("code_poste;prix\nDEDOUANEMENT;1 234,5678\n")[0]["prix"] == "1234.5678"


def test_formulaire_avoir_client_refuse_nan(monde):
    from aides_web import connecter_client, poster

    c = monde.client()
    connecter_client(c, monde)
    eid = monde.ids[A]["ecart"][0]
    r = poster(c, "/espace/recouvrement", f"/espace/recouvrement/{eid}/avoir", {"montant": "NaN"})
    assert r.status_code == 303
    assert "nombre attendu" in c.get(r.headers["location"]).text


# --- D-1315 : vocabulaire, alias d'API ------------------------------------------------------------------------------


def test_vocabulaire_et_alias_api(monde):
    from aides_web import connecter_client

    c = _api(monde)
    assert c.get("/api/v1/suivi-avoirs").json() == c.get("/api/v1/litiges").json()
    ligne = c.get("/api/v1/litiges").json()[0]
    assert ligne["ecart_id"] == ligne["litige_id"] and "relance_suggeree" in ligne  # champs historiques conservés
    w = monde.client()
    connecter_client(w, monde)
    page = w.get("/espace/recouvrement").text
    assert "Suivi des avoirs reçus" in page and "Registre de recouvrement" not in page
    assert "dossier de réclamation" not in w.get("/espace/rapports").text.lower()
    from aides_web import connecter_fondateur

    f = monde.client()
    connecter_fondateur(f, monde)
    tableau = f.get("/admin").text.lower()
    assert "relevés d'écarts" in tableau.replace("&#39;", "'") and "dossiers de réclamation" not in tableau


def test_api_dossiers_pagines(monde):
    c = _api(monde)
    tous = c.get("/api/v1/dossiers").json()
    assert len(tous) >= 2
    r = c.get("/api/v1/dossiers?limite=1")
    assert len(r.json()) == 1 and r.headers["X-Page-Suivante"] == r.json()[0]["dossier_id"]
    suite = c.get(f"/api/v1/dossiers?limite=1000&apres={r.json()[0]['dossier_id']}").json()
    assert [d["dossier_id"] for d in suite] == [d["dossier_id"] for d in tous[1:]]


def test_projection_de_lot_unique_api_et_mcp(monde):
    from controldone.services.lecture import resume_lot

    lot_id = monde.ids[A]["lot"][0]
    api = _api(monde).get(f"/api/v1/lots/{lot_id}").json()
    assert api == resume_lot(monde.pf, _acteur_client(monde), lot_id) and api["traitement"] == "done"


def _acteur_client(monde):
    from controldone.auth.cles_api import verifier_cle_api

    return verifier_cle_api(monde.pf.db, monde.cles[A])


# --- D-1319 : totaux = règle unique du rapport (findings_io.constats_hors_totaux) ------------------------------------


def test_totaux_excluent_le_constat_remplace_par_e6(monde):
    from controldone.model.enums import NatureMontant, Niveau, Outcome
    from controldone.model.resultats import Constat as ConstatModele
    from controldone.model.resultats import ResultatControle
    from controldone.services.lecture import lister_dossiers
    from controldone.storage.models import Dossier

    systeme = Acteur.systeme("tests")
    with monde.pf.db.tenant(A, systeme, lecture=True) as sc:
        d = sc.lister(Dossier, ordre=Dossier.reference)[0]
        dossier_id, version = d.id, d.version

    def resultat(cid, controle, montant, **details):
        c = ConstatModele(id=cid, controle_id=controle, niveau=Niveau.ecart_certain, montant_en_jeu=Decimal(montant),
                          nature_montant=NatureMontant.recouvrable, statut_validation="valide")
        return ResultatControle(id=f"res_{cid}", controle_id=controle, dossier_id=dossier_id, dossier_version=version,
                                outcome=Outcome.ecart_certain, constat=c, details=details)

    with monde.pf.db.tenant(A, systeme) as sc:
        sc.enregistrer_resultats([resultat("f_orig", "C3", "100.00"),
                                  resultat("f_e6", "E6", "60.00", remplace_constat_id="f_orig")])
    with monde.pf.db.operateur(FONDATEUR) as op:
        sc = op.client(A, "test des totaux", lecture=True)
        ligne = next(x for x in lister_dossiers(sc) if x.id == dossier_id)
        stats = op.statistiques(auditer=False)[A]
    from controldone.storage.models import Constat

    with monde.pf.db.tenant(A, systeme, lecture=True) as sc:
        assert sc.obtenir(Constat, "f_orig").contenu["hors_totaux"] == "remplace_par_e6"
        assert sc.obtenir(Constat, "f_e6").contenu["hors_totaux"] is None
        autres = sum((c.montant_en_jeu for c in sc.lister(Constat, dossier_id=dossier_id)
                      if c.dossier_version == version and c.niveau == "ecart_certain" and c.statut_validation == "valide"
                      and c.nature_montant == "recouvrable" and c.id not in ("f_orig", "f_e6")
                      and not (c.contenu or {}).get("hors_totaux") and (c.montant_en_jeu or 0) > 0), Decimal(0))
    assert ligne.recouvrable_certain == autres + Decimal("60.00")  # 100 remplacé par 60, pas 160
    assert stats["recouvrable_certain"] >= Decimal("60.00")
