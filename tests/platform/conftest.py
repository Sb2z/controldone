"""Fixtures de la plateforme : base SQLite temporaire, coffre, deux clients fictifs A et B peuplés."""

from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from aides_plateforme import FONDATEUR, MDP, SYSTEME, T0
from cryptography.fernet import Fernet

from controldone.auth.motdepasse import hacher_mot_de_passe
from controldone.auth.roles import Acteur, Role
from controldone.jobs.metriques import METRIQUES
from controldone.storage import Database, FileVault
from controldone.storage.comptes import creer_utilisateur
from controldone.storage.models import (
    AiUsage,
    CleApi,
    Constat,
    CorrectionValeur,
    Document,
    Dossier,
    DossierFichier,
    Ecart,
    Entite,
    EvenementRecouvrement,
    Fichier,
    Grille,
    Lot,
    Membership,
    Outbox,
    PageTexte,
    Reclamation,
    Resultat,
    Transitaire,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLDONE_ENV", "test")
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.delenv("CONTROLDONE_SECRET_KEY", raising=False)
    METRIQUES.reinitialiser()
    yield


@pytest.fixture
def db(tmp_path):
    base = Database(f"sqlite:///{tmp_path}/plateforme.db")
    base.creer_schema()
    yield base
    base.fermer()


@pytest.fixture(scope="session")
def cles_session():
    return [Fernet.generate_key()]


@pytest.fixture
def cles(cles_session):
    return cles_session


@pytest.fixture
def vault(tmp_path, cles):
    return FileVault(tmp_path / "coffre", cles)


@dataclass
class Monde:
    db: Database
    vault: FileVault
    ids: dict[str, dict[str, object]]  # tenant -> {nom_modele: id}
    acteurs: dict[str, Acteur]


def _peupler(db: Database, vault: FileVault, tenant: str) -> dict[str, object]:
    """Une ligne de chaque table client pour ``tenant`` (identifiants préfixés par le client)."""
    p = tenant[-1]
    ids: dict[str, object] = {}
    with db.tenant(tenant, SYSTEME) as sc:
        sha = vault.deposer(tenant, f"PDF FICTIF {tenant}".encode())
        ref_txt = vault.deposer_texte(tenant, f"texte de page FICTIF {tenant}")
        objets = [
            Lot(id=f"lot_{p}", recu_le=T0),
            Fichier(
                id=f"fic_{p}",
                lot_id=f"lot_{p}",
                nom_original="facture.pdf",
                chemin_relatif=f"envoi_{p}/facture.pdf",
                sha256=sha,
                taille=10,
                type_mime="application/pdf",
                coffre_ref=sha,
            ),
            PageTexte(
                id=f"pag_{p}", fichier_id=f"fic_{p}", numero=1, sha256_texte=ref_txt, texte_ref=ref_txt
            ),
            Entite(id=f"ent_{p}", raison_sociale=f"ENTITE {p.upper()} FICTIF"),
            Transitaire(id=f"tra_{p}", nom=f"TRANSITAIRE {p.upper()} FICTIF"),
            Grille(id=f"grl_{p}@v1", grille_id=f"grl_{p}", version=1, statut="brouillon"),
            Dossier(id=f"dos_{p}", lot_id=f"lot_{p}", reference="D-2026-00001", version=1),
            DossierFichier(dossier_id=f"dos_{p}", fichier_id=f"fic_{p}"),
            Document(id=f"doc_{p}", dossier_id=f"dos_{p}", type="facture_commerciale"),
            Resultat(
                id=f"res_{p}",
                dossier_id=f"dos_{p}",
                dossier_version=1,
                controle_id="C1",
                outcome="ecart_certain",
            ),
            Constat(
                id=f"f_{p}",
                resultat_id=f"res_{p}",
                dossier_id=f"dos_{p}",
                dossier_version=1,
                controle_id="C1",
                niveau="ecart_certain",
                montant_en_jeu=Decimal("120.00"),
            ),
            Constat(
                id=f"fv_{p}",
                dossier_id=f"dos_{p}",
                dossier_version=1,
                controle_id="C2",
                niveau="a_verifier",
                statut_validation="propose",
            ),
            CorrectionValeur(
                id=f"cor_{p}",
                dossier_id=f"dos_{p}",
                document_id=f"doc_{p}",
                cible=f"vs_{p}",
                chemin="facture_commerciale.total_facture",
                ancienne_valeur="1",
                nouvelle_valeur="2",
                auteur="tests",
                role_auteur="fondateur",
                motif="test (FICTIF)",
            ),
            Ecart(
                id=f"eca_{p}",
                constat_id=f"f_{p}",
                montant_initial=Decimal("120.00"),
                reste=Decimal("120.00"),
                contenu={},
            ),
            Reclamation(id=f"rec_{p}", transitaire_id=f"tra_{p}"),
            EvenementRecouvrement(
                id=f"evt_{p}", ecart_id=f"eca_{p}", de="ouvert", vers="reclame", auteur="tests"
            ),
            AiUsage(mois="2026-09", cout_eur=Decimal("0.10")),
            Outbox(id=f"out_{p}", kind="email_client", cree_par="tests", payload={"objet": "x"}),
            CleApi(id=f"key_{p}", nom="cle", prefixe=f"pfx{p}", hash="0" * 64, cree_par="tests"),
        ]
        for o in objets:
            sc._ajouter_interne(o)
        sc.flush()
        ids = {type(o).__name__ + ("_v" if str(o.id).startswith("fv_") else ""): o.id for o in objets}
    return ids


def _construire_monde(racine: Path, cles: list[bytes]) -> tuple[dict, dict]:
    db = Database(f"sqlite:///{racine}/plateforme.db")
    db.creer_schema()
    vault = FileVault(racine / "coffre", cles)
    with db.operateur(FONDATEUR) as op:
        op.creer_client("cli_a", "CLIENT A FICTIF")
        op.creer_client("cli_b", "CLIENT B FICTIF")
    acteurs: dict[str, Acteur] = {"fondateur": FONDATEUR, "systeme": SYSTEME}
    h = hacher_mot_de_passe(MDP)
    for tenant, nom, role in (
        ("cli_a", "admin_a", Role.client_admin),
        ("cli_a", "lecteur_a", Role.client_lecteur),
        ("cli_b", "admin_b", Role.client_admin),
    ):
        creer_utilisateur(
            db,
            user_id=f"usr_{nom}",
            email=f"{nom}@exemple-fictif.test",
            mot_de_passe_hash=h,
            role=role,
            acteur=FONDATEUR,
        )
        with db.operateur(FONDATEUR) as op:
            op.client(tenant, "création des comptes de test").ajouter_membre(f"usr_{nom}", role)
        acteurs[nom] = Acteur(f"usr_{nom}", role, tenant)
    ids = {"cli_a": _peupler(db, vault, "cli_a"), "cli_b": _peupler(db, vault, "cli_b")}
    for t in ("cli_a", "cli_b"):
        with db.tenant(t, SYSTEME) as sc:
            ids[t]["Membership"] = sc.lister(Membership)[0].id
    db.fermer()
    return ids, acteurs


@pytest.fixture(scope="session")
def _modele_monde(tmp_path_factory, cles_session):
    racine = tmp_path_factory.mktemp("modele_monde")
    ids, acteurs = _construire_monde(racine, cles_session)
    return racine, ids, acteurs


@pytest.fixture
def monde(_modele_monde, tmp_path, cles) -> Monde:
    """Deux clients A et B peuplés (une ligne de chaque table client), trois comptes client.
    Construit une fois par session puis copié pour chaque test."""
    modele, ids, acteurs = _modele_monde
    racine = tmp_path / "monde"
    shutil.copytree(modele, racine)
    db = Database(f"sqlite:///{racine}/plateforme.db")
    yield Monde(
        db=db, vault=FileVault(racine / "coffre", cles), ids=copy.deepcopy(ids), acteurs=dict(acteurs)
    )
    db.fermer()
