"""Listes filtrées en SQL (D-3801) : mêmes lignes, même ordre que les filtres Python de référence
(``web.listes_vues``) sur un client fictif grossi (dossiers, constats et écarts recopiés et variés)."""

from __future__ import annotations

import itertools
import uuid
from decimal import Decimal

import pytest
from starlette.datastructures import QueryParams

from controldone.auth.roles import Acteur, Role
from controldone.services.lecture import lister_dossiers, trier_constats, vue_constat
from controldone.services.reclamations import registre
from controldone.storage.models import Constat, Dossier, Ecart, Membership
from controldone.web.listes import lire_requete
from controldone.web.listes_sql import page_dossiers, page_registre, transitaires_registre
from controldone.web.listes_vues import (
    PARAMS_DOSSIERS,
    TRIS_DOSSIERS,
    TRIS_REGISTRE,
    TRIS_VALIDATION,
    filtrer_dossiers,
    filtrer_registre,
    filtrer_validation,
    params_registre,
    params_validation,
)

A, B = "demo_ateliers", "demo_nord"
STATUTS_VAL = ("propose", "valide", "rejete", "valide", "propose")
NIVEAUX = ("ecart_certain", "a_verifier", "ecart_certain", "conforme")
ECARTS = ("ouvert", "reclame", "credite", "conteste", "partiellement_credite")


class _Req:
    def __init__(self, qs: str) -> None:
        self.query_params = QueryParams(qs)


def _grossir(pf, tenant: str, n_dossiers: int) -> None:
    """Recopie les dossiers du client en variant références, clés, niveaux, validations et montants (FICTIF)."""
    with pf.db.transaction_systeme() as s:
        dossiers = list(s.query(Dossier).filter(Dossier.tenant_id == tenant))
        constats = list(s.query(Constat).filter(Constat.tenant_id == tenant))
        ecarts = {e.constat_id: e for e in s.query(Ecart).filter(Ecart.tenant_id == tenant)}
        par_dossier: dict[str, list[Constat]] = {}
        for c in constats:
            par_dossier.setdefault(c.dossier_id, []).append(c)
        k = itertools.count()
        for n in range(n_dossiers):
            m = dossiers[n % len(dossiers)]
            did = f"dos_sql_{tenant}_{n:04d}"
            contenu = dict(m.contenu or {})
            contenu["cles"] = {
                "num_facture_transitaire": [f"FICTIF-{n:04d}"],
                "mrn": [f"26FRSQL{n:011d}"],
                "ref_transport": [f"TR-FICTIF-{n % 7}"],
                "num_facture_commerciale": [f"FC-{n:05d}"],
            }
            s.add(
                Dossier(
                    id=did,
                    tenant_id=tenant,
                    lot_id=m.lot_id,
                    reference=f"GZ{n % 40:05d}" if n % 9 else None,
                    version=m.version,
                    statut_global=(m.statut_global, None, "a_verifier", "conforme")[n % 4],
                    contenu=contenu,
                )
            )
            for c in par_dossier.get(m.id, []):
                i = next(k)
                cid = f"con_sql_{uuid.uuid4().hex[:16]}"
                montant = (
                    None if i % 11 == 0 else (Decimal(i % 13) * Decimal("7.35")).quantize(Decimal("0.01"))
                )
                j = dict(c.contenu or {})
                j["renvoi"] = i % 10 == 3
                if i % 8 == 5:
                    j["hors_totaux"] = "F5"
                s.add(
                    Constat(
                        id=cid,
                        tenant_id=tenant,
                        dossier_id=did,
                        dossier_version=m.version,
                        controle_id=c.controle_id,
                        niveau=NIVEAUX[i % len(NIVEAUX)],
                        montant_en_jeu=montant,
                        nature_montant=("recouvrable", "aucun", "recouvrable", "renvoi")[i % 4],
                        statut_validation=STATUTS_VAL[i % len(STATUTS_VAL)],
                        contenu=j,
                    )
                )
                e = ecarts.get(c.id)
                if e is not None or i % 3 == 0:
                    je = dict((e.contenu if e else {}) or {})
                    je.update(
                        dossier_id=did,
                        mrn=f"26FRSQL{n:011d}",
                        reclame_le=f"2026-0{1 + i % 8}-1{i % 9}T10:00:00+00:00" if i % 4 else None,
                    )
                    s.add(
                        Ecart(
                            id=f"eca_sql_{uuid.uuid4().hex[:16]}",
                            tenant_id=tenant,
                            constat_id=cid,
                            transitaire_id=e.transitaire_id if e and i % 5 else None,
                            statut=ECARTS[i % len(ECARTS)],
                            montant_initial=montant or Decimal("1.00"),
                            reste=(montant or Decimal("1.00")) / 2,
                            contenu=je,
                        )
                    )


@pytest.fixture
def gros(monde):
    _grossir(monde.pf, A, 90)
    _grossir(monde.pf, B, 40)
    return monde


def _acteurs(pf):
    with pf.db.transaction_systeme() as s:
        membres = {m.role: m.user_id for m in s.query(Membership).filter(Membership.tenant_id == A)}
    return [Acteur(membres[r], Role(r), A) for r in ("client_admin", "client_lecteur") if r in membres]


DOSSIERS_QS = [
    "",
    "q=fictif-001",
    "q=GZ0001",
    "q=tr-fictif-3 fc-0",
    "q=26frsql",
    "q=%25",
    "q=_",
    "statut=ecart_certain",
    "statut=a_verifier",
    "statut=en_validation",
    "statut=en_cours",
    "statut=conforme",
    *(f"tri={t}" for t in TRIS_DOSSIERS),
    "statut=ecart_certain&tri=-montant",
    "q=fictif&tri=-constats",
]


@pytest.mark.parametrize("qs", DOSSIERS_QS)
def test_dossiers_sql_identiques_au_filtre_python(gros, qs):
    for acteur in _acteurs(gros.pf):
        with gros.pf.db.tenant(A, acteur, lecture=True) as scope:
            ref = filtrer_dossiers(
                lister_dossiers(scope), lire_requete(_Req(qs), PARAMS_DOSSIERS, TRIS_DOSSIERS, "reference")
            )
            vus = []
            for page in (1, 2, 3, 4, 5, 6):
                req = lire_requete(
                    _Req(f"{qs}&taille=25&page={page}"), PARAMS_DOSSIERS, TRIS_DOSSIERS, "reference"
                )
                p, total_client = page_dossiers(scope, req)
                assert p.total == len(ref)
                if p.page == page:
                    vus.extend(p.elements)
            assert total_client == scope.compter(Dossier)

        def cle(d):
            return (d.id, d.statut_code, d.nb_constats, d.recouvrable_certain, d.recouvrable_a_verifier)

        tri = (
            dict(x.split("=") for x in qs.split("&") if x.startswith("tri="))
            .get("tri", "reference")
            .lstrip("-")
        )
        valeur = {
            "reference": lambda d: d.reference,
            "date": lambda d: d.cree_le,
            "montant": lambda d: d.recouvrable_certain,
            "constats": lambda d: d.nb_constats,
        }[tri]
        # ex aequo (dossiers recopiés) : ordre libre entre eux, même suite de valeurs triées, mêmes lignes
        assert [valeur(d) for d in vus] == [valeur(d) for d in ref], (acteur.role, qs)
        assert sorted(map(cle, vus)) == sorted(map(cle, ref)), (acteur.role, qs)


REGISTRE_QS = [
    "",
    "q=gz0000",
    "q=26frsql0000",
    "q=droits",
    "q=non identifie",
    "q=%",
    "statut=ouvert",
    "statut=reclame",
    *(f"tri={t}" for t in TRIS_REGISTRE),
    "statut=conteste&tri=-age",
]


@pytest.mark.parametrize("qs", REGISTRE_QS)
def test_registre_sql_identique_au_filtre_python(gros, qs):
    for acteur in _acteurs(gros.pf):
        with gros.pf.db.tenant(A, acteur, lecture=True) as scope:
            lignes = registre(scope)
            transitaires = transitaires_registre(scope)
            assert transitaires == {x.transitaire_id: x.transitaire for x in lignes if x.transitaire_id}
            params = params_registre(transitaires)
            ref = filtrer_registre(lignes, lire_requete(_Req(qs), params, TRIS_REGISTRE, "-reste"))
            req = lire_requete(_Req(qs + "&taille=100"), params, TRIS_REGISTRE, "-reste")
            p = page_registre(scope, req, transitaires)
        assert p.total == len(ref)
        attendu = [x.id for x in ref][:100]
        if "age" in qs:  # tri par jour en Python, par instant en SQL : mêmes lignes, ordre par jour identique
            assert sorted(x.id for x in p.elements) == sorted(attendu)
            assert [x.age_jours for x in p.elements] == [x.age_jours for x in ref][:100]
        else:
            assert [x.id for x in p.elements] == attendu, (acteur.role, qs)
        assert [x.evenements for x in p.elements] == [x.evenements for x in ref][:100]


VALIDATION_QS = [
    "",
    f"client={A}",
    f"client={B}",
    "niveau=ecart_certain",
    "niveau=a_verifier",
    "niveau=renvoi",
    "controle=A12",
    "min=10",
    "max=30",
    "min=7.35&max=7.35",
    "min=0",
    *(f"tri={t}" for t in TRIS_VALIDATION),
    f"client={A}&niveau=a_verifier&tri=-montant",
]


@pytest.mark.parametrize("qs", VALIDATION_QS)
def test_file_validation_sql_identique_au_filtre_python(gros, qs):
    fondateur = Acteur("usr_fondateur_demo", Role.fondateur)
    with gros.pf.db.operateur(fondateur) as op:
        noms = {t.id: t.raison_sociale for t in op.lister_clients() if t.actif}
        params = params_validation(noms)
        items = []
        for c in op.file_validation(limite=10_000):
            items.append(
                {
                    "c": vue_constat(c),
                    "tenant_id": c.tenant_id,
                    "client": noms[c.tenant_id],
                    "dossier": c.dossier_id,
                }
            )
        refs: dict[str, str] = {}
        for t in noms:
            scope = op.client(t, "test", lecture=True)
            refs.update({d.id: d.reference or d.id for d in scope.lister(Dossier)})
        for it in items:
            it["dossier"] = refs[it["dossier"]]
        par_c = {id(x["c"]): x for x in items}
        items = [par_c[id(c)] for c in trier_constats([x["c"] for x in items])]
        ref = filtrer_validation(items, lire_requete(_Req(qs), params, TRIS_VALIDATION, "priorite"))
        req = lire_requete(_Req(qs + "&taille=100"), params, TRIS_VALIDATION, "priorite")
        f = req.filtres
        constats, total, total_file = op.rechercher_file_validation(
            clients=sorted(noms),
            client=f.get("client"),
            controle=f.get("controle"),
            niveau=f.get("niveau"),
            mini=f.get("min"),
            maxi=f.get("max"),
            tri=req.tri,
            limite=100,
        )
    assert total_file == len(items) and total == len(ref)
    assert [c.id for c in constats] == [x["c"].id for x in ref][:100], qs


def test_pages_sql_dans_l_interface(gros):
    from aides_web import ADMIN_A, connecter_client, connecter_fondateur

    c = gros.client()
    connecter_client(c, gros, ADMIN_A)
    r = c.get("/espace/dossiers?q=fictif-00&tri=-montant&taille=25&page=2")
    assert r.status_code == 200
    assert c.get("/espace/dossiers?page=10000").status_code == 200  # ramenée à la dernière page
    assert c.get("/espace/recouvrement?q=%25_&tri=-age").status_code == 200
    f = gros.client()
    connecter_fondateur(f, gros)
    r = f.get("/admin/validation?niveau=renvoi&page=9999")
    assert r.status_code == 200 and 'id="attention"' in r.text
