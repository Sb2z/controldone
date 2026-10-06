"""Audit final, corrections de la plateforme (D-1301 à D-1320) : chaque test reproduit un constat de l'audit B
ou D (il échouait avant la correction)."""

from __future__ import annotations

import io
import os
import sqlite3
import threading
import time
import tracemalloc
from datetime import timedelta
from decimal import Decimal

import pytest
from aides_plateforme import FONDATEUR, SYSTEME
from sqlalchemy.exc import OperationalError

from controldone.jobs import JobStore, enqueue
from controldone.jobs.registre import BailPerdu, JobContext, charger_handlers
from controldone.jobs.worker import Worker
from controldone.storage import ErreurIntegrite, purger_expires
from controldone.storage.coltypes import maintenant
from controldone.storage.models import Constat, Dossier, DossierFichier, Fichier, Lot, PageTexte

# --- F-01 : clôture automatique puis purge (voyage dans le temps) ---------------------------------------------


def _dossier_sans_suite(monde, tenant="cli_a", p="x"):
    with monde.db.tenant(tenant, SYSTEME) as sc:
        sha = monde.vault.deposer(tenant, f"PDF FICTIF {p}".encode())
        txt = monde.vault.deposer_texte(tenant, f"texte FICTIF {p}")
        for o in (
            Lot(id=f"lot_{p}", statut="traite"),
            Fichier(
                id=f"fic_{p}",
                lot_id=f"lot_{p}",
                nom_original="f.pdf",
                chemin_relatif="f.pdf",
                sha256=sha,
                taille=1,
                coffre_ref=sha,
            ),
            PageTexte(id=f"pag_{p}", fichier_id=f"fic_{p}", numero=1, texte_ref=txt),
            Dossier(id=f"dos_{p}", lot_id=f"lot_{p}", reference="D-X", version=1),
            DossierFichier(dossier_id=f"dos_{p}", fichier_id=f"fic_{p}"),
        ):
            sc._ajouter_interne(o)
    return sha, txt


def test_f01_cloture_automatique_puis_purge(monde):
    from controldone.storage.retention import cloturer_inactifs

    sha, txt = _dossier_sans_suite(monde)
    t = maintenant()
    # avant la correction : aucun chemin ne clôturait, la purge ne supprimait jamais rien
    assert purger_expires(monde.db, monde.vault, t + timedelta(days=3650)).total == 0
    assert cloturer_inactifs(monde.db, t + timedelta(days=59), jours=60) == {"dossiers": 0, "lots": 0}
    clos = cloturer_inactifs(monde.db, t + timedelta(days=61), jours=60)
    assert clos["dossiers"] >= 1 and clos["lots"] >= 1
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.obtenir(Dossier, "dos_x").cloture_le is not None
        # dos_a : écart encore ouvert et constat en attente de décision -> jamais clos
        assert sc.obtenir(Dossier, "dos_a").cloture_le is None
    assert purger_expires(monde.db, monde.vault, t + timedelta(days=61 + 179)).total == 0
    rapport = purger_expires(monde.db, monde.vault, t + timedelta(days=61 + 181))
    assert rapport.fichiers.get("cli_a") == 1 and rapport.textes.get("cli_a") == 1
    assert not monde.vault.existe("cli_a", sha) and not monde.vault.existe("cli_a", txt, espace="textes")


def test_f01_handler_purger_retention_cloture_et_purge_les_jobs(monde):
    from controldone.jobs import handlers

    enqueue("purger_retention", {}, "purge:test", db=monde.db)
    w = Worker(
        monde.db,
        worker_id="w1",
        handlers={"purger_retention": handlers.purger_retention},
        services={"vault": monde.vault},
        poll_s=0.01,
    )
    assert w.executer_un() == "done"
    res = JobStore(monde.db).par_cle("purge:test").resultat
    assert {"dossiers_clos", "lots_clos", "jobs_purges", "fichiers"} <= set(res)


# --- F-05 : battement de cœur robuste et jeton de clôture -------------------------------------------------------


def test_f05_erreur_de_battement_retentee_sans_double_execution(monde, monkeypatch):
    store = JobStore(monde.db)
    job = enqueue("lent", {}, "k-lent", db=monde.db)
    original = JobStore.prolonger
    appels = {"n": 0}

    def prolonger_instable(self, *a, **kw):
        appels["n"] += 1
        if appels["n"] == 1:
            raise OperationalError("UPDATE jobs", {}, Exception("database is locked"))
        return original(self, *a, **kw)

    monkeypatch.setattr(JobStore, "prolonger", prolonger_instable)
    executions = []
    vu_par_w2 = []

    def lent(ctx):
        executions.append(ctx.worker_id)
        fin = time.monotonic() + 1.6
        while time.monotonic() < fin:  # un autre worker tente de reprendre pendant le traitement
            vu_par_w2.append(store.reserver("w2", lease_s=1, kinds=["lent"]))
            time.sleep(0.2)
        return {}

    w = Worker(monde.db, worker_id="w1", handlers={"lent": lent}, lease_s=1, heartbeat_s=0.2, poll_s=0.01)
    assert w.executer_un() == "done"
    assert executions == ["w1"] and not any(vu_par_w2) and appels["n"] >= 3
    assert store.obtenir(job.id).statut == "done"


def test_f05_jeton_de_cloture_meme_identifiant_de_worker(monde):
    store = JobStore(monde.db)
    job = enqueue("t", {}, "k-jeton", db=monde.db)
    t = maintenant() + timedelta(seconds=1)
    premier = store.reserver("web-integre", lease_s=10, now=t)
    second = store.reserver("web-integre", lease_s=10, now=t + timedelta(seconds=11))  # bail expiré, même id
    assert premier.attempts == 1 and second.attempts == 2
    assert not store.terminer(job.id, "web-integre", {}, now=t, tentative=premier.attempts)
    ctx = JobContext(job=premier, db=monde.db, worker_id="web-integre")
    with monde.db.tenant("cli_a", SYSTEME) as sc, pytest.raises(BailPerdu):
        ctx.exiger_bail(sc.session)  # dans la transaction qui validerait les résultats
    assert store.terminer(job.id, "web-integre", {}, now=t, tentative=second.attempts)


# --- F-07 : registre unique des handlers -------------------------------------------------------------------------


def test_f07_registre_unique_et_worker_integre(monde):
    from controldone.services.plateforme import Plateforme
    from controldone.web.app import _worker

    kinds = set(charger_handlers())
    assert {
        "traiter_lot",
        "purger_retention",
        "recontroler_dossier",
        "controle_avant_paiement",
        "agent",
        "preparer_reclamation",
        "referentiel_recalculer",
    } <= kinds
    w = _worker(Plateforme(db=monde.db, vault=monde.vault, cles_maitresses=[]))
    assert set(w.kinds) == kinds and w.worker_id.startswith("web-integre:")
    inconnu = enqueue("kind_inconnu", {}, "k-inconnu", db=monde.db)
    assert w.store.reserver(w.worker_id, kinds=w.kinds) is None  # jamais tué : reste pour un autre worker
    assert JobStore(monde.db).obtenir(inconnu.id).statut == "pending"


# --- F-20 : ordonnancement équitable entre clients ---------------------------------------------------------------


def test_f20_tourniquet_entre_clients(monde):
    ordre = []
    for i in range(3):
        enqueue("t", {"n": i}, f"a{i}", "cli_a", db=monde.db)
    enqueue("t", {"n": 9}, "b0", "cli_b", db=monde.db)
    w = Worker(monde.db, worker_id="w1", handlers={"t": lambda ctx: ordre.append(ctx.tenant_id)}, poll_s=0.01)
    while w.executer_un() is not None:
        pass
    assert ordre == ["cli_a", "cli_b", "cli_a", "cli_a"]  # avant : cli_b passait après tous les lots de cli_a


def test_f20_duree_maximale_d_un_lot():
    from controldone.jobs.handlers import executer_avec_delai
    from controldone.jobs.registre import ErreurDefinitive

    with pytest.raises(ErreurDefinitive, match="durée maximale"):
        executer_avec_delai(time.sleep, (30,), {}, 1.0)
    assert executer_avec_delai(sorted, ([3, 1, 2],), {}, 30.0) == [1, 2, 3]


# --- F-11 : job d'un lot retrouvé par sa clé ; listes bornées dans le bon ordre -----------------------------------


def test_f11_job_du_lot_apres_2000_jobs(monde):
    from controldone.services.lecture import job_du_lot, lire_lot

    with monde.db.transaction_systeme() as s:
        for i in range(2100):
            JobStore.enqueue_dans(s, "agent", {}, f"agent:cli_a:{i}", "cli_a")
    JobStore(monde.db).enqueue("traiter_lot", {"lot_id": "lot_a"}, "traiter_lot:cli_a:lot_a", "cli_a")
    job = job_du_lot(monde.db, "cli_a", "lot_a")
    with monde.db.tenant("cli_a", SYSTEME, lecture=True) as sc:
        assert lire_lot(sc, "lot_a", job=job)["job"]["statut"] == "pending"
    recents = JobStore(monde.db).lister(tenant_id="cli_a", limite=5, recents=True)
    assert recents[-1].idempotency_key == "traiter_lot:cli_a:lot_a"


def test_f11_purge_des_jobs_termines(monde):
    store = JobStore(monde.db)
    job = enqueue("t", {}, "vieux", db=monde.db)
    t = maintenant() + timedelta(seconds=1)
    pris = store.reserver("w", now=t)
    assert store.terminer(job.id, "w", {}, now=t - timedelta(days=40), tentative=pris.attempts)
    assert store.purger_termines(jours=30) == 1 and store.obtenir(job.id) is None


# --- F-12 : mise en file dans la même transaction ---------------------------------------------------------------


def test_f12_job_annule_avec_la_transaction(monde):
    with pytest.raises(RuntimeError), monde.db.operateur(FONDATEUR) as op:
        sc = op.client("cli_a", "correction (test)")
        sc.mettre_en_file("recontroler_dossier", {"dossier_id": "dos_a", "version": 2}, "recontroler:test")
        raise RuntimeError("échec après la correction")
    assert JobStore(monde.db).par_cle("recontroler:test") is None
    with monde.db.operateur(FONDATEUR) as op:
        op.client("cli_a", "correction (test)").mettre_en_file(
            "recontroler_dossier", {"dossier_id": "dos_a"}, "recontroler:test"
        )
    assert JobStore(monde.db).par_cle("recontroler:test").tenant_id == "cli_a"


# --- F-04, F-14 : dépôt hors verrou d'écriture, fichier par fichier, nettoyage du coffre ---------------------------


def _plateforme(monde):
    from controldone.services.plateforme import Plateforme

    return Plateforme(db=monde.db, vault=monde.vault, cles_maitresses=[])


def _ecrivain_libre(monde) -> bool:
    con = sqlite3.connect(str(monde.db.chemin_sqlite()), timeout=0.3)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def test_f04_f14_depot_sans_verrou_et_flux_lus_un_a_un(monde, monkeypatch):
    from controldone.services import depot

    pf = _plateforme(monde)
    flux = [io.BytesIO(b"<?xml version='1.0'?><Invoice>FICTIF %d</Invoice>" % i) for i in range(2)]
    observations = []
    original = type(pf.vault).deposer

    def deposer_observe(self, tenant, contenu, **kw):
        observations.append((_ecrivain_libre(monde), flux[1].tell()))
        return original(self, tenant, contenu, **kw)

    monkeypatch.setattr(type(pf.vault), "deposer", deposer_observe)
    transmis = [depot.FichierTransmis.depuis_flux(f"f{i}.xml", f) for i, f in enumerate(flux)]
    r = depot.deposer(pf, monde.acteurs["admin_a"], transmis)
    assert r.acceptes == 2 and r.job_id
    # chiffrement sans verrou d'écriture tenu ; le second fichier n'est pas encore lu quand le premier est déposé
    assert observations[0] == (True, 0) and all(libre for libre, _ in observations)


def test_f04_contenus_retires_si_l_enregistrement_echoue(monde, monkeypatch):
    from controldone.services import depot

    pf = _plateforme(monde)

    def echec(*a, **kw):
        raise RuntimeError("panne pendant l'enregistrement")

    monkeypatch.setattr(depot, "enregistrer_prepare", echec)
    contenu = b"<?xml version='1.0'?><Invoice>ORPHELIN FICTIF</Invoice>"
    with pytest.raises(RuntimeError):
        depot.deposer(pf, monde.acteurs["admin_a"], [depot.FichierTransmis("o.xml", contenu, len(contenu))])
    import hashlib

    assert not monde.vault.existe("cli_a", hashlib.sha256(contenu).hexdigest())


# --- F-06 : lecture du fondateur sans verrou d'écriture ------------------------------------------------------------


def test_f06_lecture_operateur_sans_begin_immediate(monde):
    with monde.db.operateur(FONDATEUR) as op:
        sc = op.client("cli_a", "consultation d'un dossier", lecture=True)
        assert sc.obtenir(Dossier, "dos_a")
        assert _ecrivain_libre(monde)  # avant : le worker attendait la fin de la consultation
        sc2 = op.client("cli_b", "écriture", lecture=False)
        sc2.obtenir(Dossier, "dos_b")
        assert not _ecrivain_libre(monde)


# --- F-15 : tri SQL avant la limite, comptage SQL ------------------------------------------------------------------


def test_f15_file_validation_triee_avant_la_limite(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        for i in range(30):
            sc._ajouter_interne(
                Constat(
                    id=f"p_{i:02d}",
                    dossier_id="dos_a",
                    dossier_version=1,
                    controle_id="C9",
                    niveau="a_verifier",
                    statut_validation="propose",
                    montant_en_jeu=Decimal(i),
                )
            )
        sc._ajouter_interne(
            Constat(
                id="p_zz",
                dossier_id="dos_a",
                dossier_version=1,
                controle_id="C1",
                niveau="ecart_certain",
                statut_validation="propose",
                montant_en_jeu=Decimal("5000.00"),
            )
        )
        assert sc.compter(Constat, statut_validation="propose") == 33  # + fv_a
    with monde.db.operateur(FONDATEUR) as op:
        premiers = op.file_validation(limite=5)  # avant : LIMIT puis tri -> p_zz (inséré en dernier) absent
        assert [c.id for c in premiers] == ["p_zz", "f_a", "f_b", "p_29", "p_28"]
        assert op.compter_proposes() == 35  # + f_b et fv_b (cli_b)


# --- F-02 : sauvegarde en flux, segments authentifiés --------------------------------------------------------------


def test_f02_sauvegarde_en_flux_memoire_bornee(monde, tmp_path, cles):
    from controldone.storage.sauvegarde import restaurer, sauvegarder

    for _ in range(6):  # 30 Mo incompressibles dans le coffre
        monde.vault.deposer("cli_a", os.urandom(5 * 1024 * 1024))
    tracemalloc.start()
    archive = sauvegarder(
        monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "sauv", cles, tmp_dir=tmp_path / "tmp_sauv"
    )
    _, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert pic < 12 * 1024 * 1024, pic  # avant : > 3 × la taille du coffre (tar en mémoire + jeton Fernet)
    assert archive.read_bytes()[:7] == b"CDSAV2\n"
    tracemalloc.start()
    cible = restaurer(archive, tmp_path / "r", cles)
    _, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert pic < 12 * 1024 * 1024, pic
    assert len(list((cible / "coffre" / "cli_a" / "fichiers").rglob("*"))) >= 6


def test_f02_archive_tronquee_ou_reordonnee_refusee(monde, tmp_path, cles):
    import struct

    from controldone.storage.sauvegarde import MAGIE, restaurer, sauvegarder

    monde.vault.deposer("cli_a", os.urandom(3 * 1024 * 1024))
    archive = sauvegarder(monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "s", cles)
    brut = archive.read_bytes()
    segments, pos = [], len(MAGIE)
    while pos < len(brut):
        (n,) = struct.unpack(">I", brut[pos : pos + 4])
        segments.append(brut[pos : pos + 4 + n])
        pos += 4 + n
    assert len(segments) >= 3
    tronquee = tmp_path / "t.tar.gz.enc"
    tronquee.write_bytes(MAGIE + b"".join(segments[:-1]))
    with pytest.raises(ErreurIntegrite):
        restaurer(tronquee, tmp_path / "r1", cles)
    melangee = tmp_path / "m.tar.gz.enc"
    melangee.write_bytes(MAGIE + segments[1] + segments[0] + b"".join(segments[2:]))
    with pytest.raises(ErreurIntegrite):
        restaurer(melangee, tmp_path / "r2", cles)


def test_f02_echec_de_sauvegarde_alerte(monde, tmp_path, monkeypatch):
    from controldone.storage import sauvegarde

    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", f"sqlite:///{monde.db.chemin_sqlite()}")
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "var"))
    from controldone.config import reset_settings

    reset_settings()

    def panne(*a, **kw):
        raise OSError("disque plein")

    monkeypatch.setattr(sauvegarde, "sauvegarder", panne)
    try:
        assert sauvegarde.main(["sauvegarder", "--sans-rotation"]) == 1
    finally:
        reset_settings()
    with monde.db.operateur(FONDATEUR) as op:
        assert "sauvegarde_echec" in [a.kind for a in op.alertes()]


# --- F-13 : .env lu par toutes les lectures de réglages --------------------------------------------------------------


def test_f13_env_prod_dans_le_fichier_env(tmp_path, monkeypatch):
    from controldone.config import charger_fichier_env, reset_settings
    from controldone.storage.cles import mode_execution

    fichier = tmp_path / ".env"
    fichier.write_text(
        "CONTROLDONE_ENV=prod\nexport CONTROLDONE_JOB_LEASE_S=300\n# commentaire\n", encoding="utf-8"
    )
    monkeypatch.delenv("CONTROLDONE_ENV", raising=False)
    monkeypatch.delenv("CONTROLDONE_JOB_LEASE_S", raising=False)
    monkeypatch.setenv("CONTROLDONE_ENV_FILE", str(fichier))
    charger_fichier_env(fichier, forcer=True)
    try:
        assert mode_execution() == "prod"  # avant : « dev » (clé de développement, cookie sans Secure)
        reset_settings()
        from controldone.config import get_settings

        assert get_settings().job_lease_s == 300 and get_settings().env == "prod"
    finally:
        reset_settings()


def test_f13_l_environnement_reel_l_emporte(tmp_path, monkeypatch):
    from controldone.config import charger_fichier_env

    fichier = tmp_path / ".env"
    fichier.write_text("CONTROLDONE_ENV=prod\n", encoding="utf-8")
    monkeypatch.setenv("CONTROLDONE_ENV", "test")
    charger_fichier_env(fichier, forcer=True)
    assert os.environ["CONTROLDONE_ENV"] == "test"


def test_f18_plafonds_ia_par_defaut_lus_dans_les_reglages(monde, monkeypatch):
    from controldone.config import reset_settings
    from controldone.storage.models import Tenant

    monkeypatch.setenv("CONTROLDONE_LLM_PLAFOND_CLIENT_MENSUEL_EUR", "12.50")
    reset_settings()
    try:
        with monde.db.operateur(FONDATEUR) as op:
            t = op.creer_client("cli_plafond", "CLIENT PLAFOND FICTIF")
        assert t.plafond_cout_ia_mensuel_eur == Decimal("12.50")
        with monde.db.operateur(FONDATEUR) as op:
            assert any(x.id == "cli_plafond" for x in op.lister_clients())
        assert isinstance(t, Tenant)
    finally:
        reset_settings()


# --- suspicion 1 : insertion idempotente sûre en cas de course (PostgreSQL) -----------------------------------------


def test_insertion_sortante_course_rattrapee(monde):
    from controldone.storage import sorties

    with monde.db.transaction_systeme() as s:
        _a, cree_a = sorties.inserer_ou_lire(
            s,
            id="out_course1",
            kind="email_client",
            statut="brouillon",
            payload={},
            idempotency_key="cle-course",
            cree_par="t",
            cree_le=maintenant(),
        )
    with monde.db.transaction_systeme() as s:
        # simule la transaction concurrente qui n'a pas vu la ligne avant d'insérer
        b, cree_b = sorties.inserer_ou_lire(
            s,
            id="out_course2",
            kind="email_client",
            statut="brouillon",
            payload={},
            idempotency_key="cle-course",
            cree_par="t",
            cree_le=maintenant(),
        )
    assert cree_a and not cree_b and b.id == "out_course1"


# --- suspicion 5 : identifiant du worker intégré unique ------------------------------------------------------------


def test_identifiant_worker_integre_unique(monde):
    from controldone.web.app import _worker

    w = _worker(_plateforme(monde))
    assert str(os.getpid()) in w.worker_id


def test_battement_dans_un_fil_ne_meurt_pas(monde, monkeypatch):
    """Le fil de battement survit à une exception (avant : « Exception in thread heartbeat-… »)."""
    erreurs = []
    monkeypatch.setattr(threading, "excepthook", lambda args: erreurs.append(args))

    def toujours_en_panne(self, *a, **kw):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    monkeypatch.setattr(JobStore, "prolonger", toujours_en_panne)
    enqueue("court", {}, "k-court", db=monde.db)
    w = Worker(
        monde.db,
        worker_id="w1",
        handlers={"court": lambda ctx: time.sleep(0.5) or {}},
        lease_s=60,
        heartbeat_s=0.1,
        poll_s=0.01,
    )
    assert w.executer_un() == "done" and erreurs == []


# --- F-14 : coffre chiffré par segments pour les gros contenus ---------------------------------------------------


def test_f14_coffre_par_segments_memoire_et_integrite(tmp_path, cles):
    from cryptography.fernet import Fernet

    from controldone.storage import FileVault
    from controldone.storage.vault import MAGIE_V2

    v = FileVault(tmp_path / "coffre", cles)
    contenu = os.urandom(20 * 1024 * 1024 + 123)
    tracemalloc.start()
    sha = v.deposer("cli_a", contenu)
    _, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert pic < 8 * 1024 * 1024, pic  # avant (Fernet d'un bloc) : environ 6 × 20 Mo
    chemin = v._chemin("cli_a", sha, "fichiers")
    assert chemin.read_bytes()[:4] == MAGIE_V2 and v.lire("cli_a", sha) == contenu
    brut = chemin.read_bytes()
    chemin.write_bytes(brut[: len(brut) - 1024 * 1024])  # segment final retiré
    with pytest.raises(ErreurIntegrite):
        v.lire("cli_a", sha)
    chemin.unlink()
    sha = v.deposer("cli_a", contenu)
    nouvelle = Fernet.generate_key()
    assert v.tourner_cles([nouvelle, *cles]) == 1
    assert FileVault(tmp_path / "coffre", [nouvelle]).lire("cli_a", sha) == contenu
    with pytest.raises(ErreurIntegrite):
        FileVault(tmp_path / "coffre", cles).lire("cli_a", sha)


# --- suspicion 6 : un lot reçu par l'API n'est jamais traité deux fois en parallèle (D-1321) -------------------------


def test_controle_avant_paiement_reporte_pendant_traiter_lot(monde, monkeypatch):
    from controldone.connecteurs import jobs as cjobs
    from controldone.jobs import handlers

    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc._ajouter_interne(Lot(id="lot_pa", statut="recu"))
    appels = []
    monkeypatch.setattr(handlers, "traiter_lot", lambda ctx: appels.append(ctx.job.kind) or {})
    monkeypatch.setattr(cjobs, "proposer_statut_litige", lambda *a, **kw: None)
    store = JobStore(monde.db)
    enqueue("traiter_lot", {"lot_id": "lot_pa"}, "traiter_lot:cli_a:lot_pa", "cli_a", db=monde.db)
    controle = enqueue(
        "controle_avant_paiement",
        {"lot_id": "lot_pa", "facture_pa_id": "api:lot_pa"},
        "controle_avant_paiement:cli_a:api:lot_pa",
        "cli_a",
        db=monde.db,
    )
    decalage = {"s": 0}
    w2 = Worker(
        monde.db,
        worker_id="w2",
        kinds=["controle_avant_paiement"],
        poll_s=0.01,
        handlers={"controle_avant_paiement": cjobs.controle_avant_paiement},
        horloge=lambda: maintenant() + timedelta(seconds=decalage["s"]),
    )
    # traiter_lot encore en file : le contrôle attend (avant : pipeline lancé ici, puis une seconde fois)
    assert w2.executer_un() == "reporte" and appels == []
    j = store.obtenir(controle.id)
    assert j.statut == "pending" and j.attempts == 0 and j.last_error.startswith("reporte")
    # traiter_lot pris par un autre worker (bail valide) : toujours reporté, sans consommer d'essai
    assert store.reserver("w1", lease_s=600, kinds=["traiter_lot"]).kind == "traiter_lot"
    decalage["s"] = 20
    assert w2.executer_un() == "reporte" and appels == [] and store.obtenir(controle.id).attempts == 0
    # lot traité par w1 : le contrôle s'exécute, sans relancer le pipeline
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.obtenir(Lot, "lot_pa").statut = "traite"
    decalage["s"] = 60
    assert w2.executer_un() == "done" and appels == []


# --- suspicion 8 : schéma périmé détecté au démarrage (D-1322) ------------------------------------------------------


def test_schema_perime_refuse_au_demarrage(tmp_path, monkeypatch):
    import tempfile

    from controldone.config import reset_settings
    from controldone.jobs import worker
    from controldone.storage import Database, SchemaPerime

    url = f"sqlite:///{tmp_path}/ancienne.db"
    db = Database(url)
    db.creer_schema()
    db.exiger_schema_a_jour()  # base neuve : rien à signaler
    db.fermer()
    with sqlite3.connect(tmp_path / "ancienne.db") as cx:  # base d'une version antérieure : colonne absente
        cx.execute("ALTER TABLE jobs DROP COLUMN resultat")
    db = Database(url)
    db.creer_schema()  # create_all n'ajoute pas la colonne
    with pytest.raises(SchemaPerime, match=r"jobs\.resultat"):
        db.exiger_schema_a_jour()  # avant : erreur « no such column » au premier job seulement
    db.fermer()
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", url)
    monkeypatch.setenv("CONTROLDONE_TMP_DIR", str(tmp_path / "tmp"))
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    reset_settings()
    try:
        assert worker.main(["--once"]) == 3
    finally:
        reset_settings()


# --- suspicion 3 : l'expéditeur (appel réseau) est appelé hors du verrou d'écriture (D-1323) ----------------------


def test_envoi_sortant_hors_verrou_d_ecriture(monde):
    from controldone.outbox import FileSortante, TransitionInterdite, TypeAction

    fs = FileSortante(monde.db)
    a = fs.approuver(
        fs.proposer(
            TypeAction.rapport_publication,
            {"objet": "Rapport FICTIF", "corps": "Disponible."},
            SYSTEME,
            tenant_id="cli_a",
        ).id,
        FONDATEUR,
    )
    vu = {}

    class PALente:
        nom = "pa_lente"

        def envoyer(self, action):
            cx = sqlite3.connect(monde.db.chemin_sqlite(), timeout=0.3)
            try:
                cx.execute("BEGIN IMMEDIATE")  # un autre écrivain (worker, dépôt) pendant l'appel réseau
                cx.rollback()
                vu["autre_ecrivain"] = True
            except sqlite3.OperationalError:
                vu["autre_ecrivain"] = False  # avant : « database is locked » pendant tout l'envoi
            finally:
                cx.close()
            with pytest.raises(TransitionInterdite, match="déjà en cours"):
                fs.envoyer(action.id, self, FONDATEUR)  # second envoi concurrent : refusé
            return "pa:FICTIF-1"

    assert fs.envoyer(a.id, PALente(), FONDATEUR).reference_envoi == "pa:FICTIF-1"
    assert vu == {"autre_ecrivain": True}

    b = fs.approuver(
        fs.proposer(
            TypeAction.rapport_publication,
            {"objet": "Rapport FICTIF 2", "corps": "Ok."},
            SYSTEME,
            tenant_id="cli_a",
        ).id,
        FONDATEUR,
    )

    class PAEnPanne:
        nom = "pa_en_panne"

        def envoyer(self, action):
            raise ConnectionError("PA injoignable")

    with pytest.raises(ConnectionError):
        fs.envoyer(b.id, PAEnPanne(), FONDATEUR)
    assert fs.obtenir(b.id, FONDATEUR).reference_envoi is None  # réservation levée : nouvel essai possible
    assert fs.envoyer(b.id, PALente(), FONDATEUR).statut.value == "envoye"


# --- suspicion 2 : purge et redépôt du même contenu (D-1324) --------------------------------------------------------


def test_purge_epargne_un_contenu_redepose_et_depot_reverifie(monde):
    from controldone.services import depot
    from controldone.services.plateforme import Plateforme, RequeteInvalide

    t = maintenant()
    blobs = {p: _dossier_sans_suite(monde, p=p) for p in ("x", "y")}
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        for p in ("x", "y"):
            sc.obtenir(Dossier, f"dos_{p}").cloture_le = t - timedelta(days=400)
            sc.obtenir(Lot, f"lot_{p}").cloture_le = t - timedelta(days=400)
    vieux = (t - timedelta(days=2)).timestamp()
    for sha, txt in blobs.values():
        os.utime(monde.vault._chemin("cli_a", sha, "fichiers"), (vieux, vieux))
        os.utime(monde.vault._chemin("cli_a", txt, "textes"), (vieux, vieux))
    # un dépôt en cours redépose le contenu de x (pas encore enregistré en base) pendant la purge
    assert monde.vault.deposer("cli_a", b"PDF FICTIF x") == blobs["x"][0]
    rapport = purger_expires(monde.db, monde.vault, t)
    assert rapport.fichiers["cli_a"] == 2 and rapport.epargnes == 1
    assert monde.vault.existe(
        "cli_a", blobs["x"][0]
    )  # avant : supprimé, le dépôt référençait un contenu absent
    assert not monde.vault.existe("cli_a", blobs["y"][0])
    # filet : contenu retiré entre la réception et l'enregistrement -> dépôt refusé proprement, rien d'enregistré
    pf = Plateforme(db=monde.db, vault=monde.vault, cles_maitresses=[])
    prep = depot.preparer_depot(pf, "cli_a", [("f.xml", b"<facture>FICTIF z</facture>")], {})
    ref = next(r for _f, r in prep.fichiers if r)
    monde.vault.supprimer("cli_a", ref)
    with pytest.raises(RequeteInvalide, match="retiré du coffre"), monde.db.tenant("cli_a", SYSTEME) as sc:
        depot.enregistrer_prepare(sc, prep, vault=monde.vault)
    with monde.db.tenant("cli_a", SYSTEME, lecture=True) as sc:
        assert sc.lister(Lot, id=prep.lot_id) == []
