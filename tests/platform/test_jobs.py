"""File de tâches en base : idempotence, bail, battement de cœur, attente exponentielle, mort, arrêt propre,
plafonds de coût IA, handler ``traiter_lot``, journaux sans contenu, métriques."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from aides_plateforme import FONDATEUR, SYSTEME

from controldone.jobs import (
    JobStore,
    RegistreCoutsDB,
    cout_mensuel,
    delai_backoff,
    enqueue,
    enregistrer_cout,
    etat_plafond,
    metriques,
    texte_prometheus,
)
from controldone.jobs import handlers as handlers_mod
from controldone.jobs.journal import FormateurJSON, evenement
from controldone.jobs.registre import ErreurDefinitive
from controldone.jobs.worker import Worker
from controldone.storage import AccesRefuse
from controldone.storage.coltypes import maintenant
from controldone.storage.models import AuditLog, Dossier, Lot, PageTexte


class Horloge:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def avancer(self, **kw: Any) -> None:
        self.t += timedelta(**kw)


@pytest.fixture
def horloge():
    return Horloge(maintenant() + timedelta(seconds=1))  # jobs mis en file « maintenant » : déjà prêts


def _worker(monde, horloge, handlers, **kw):
    return Worker(monde.db, worker_id="w1", handlers=handlers, horloge=horloge, poll_s=0.01, **kw)


# --- file -----------------------------------------------------------------------------------------------


def test_enqueue_idempotent(monde):
    j1 = enqueue("traiter_lot", {"lot_id": "lot_a"}, "cle-1", "cli_a", db=monde.db)
    j2 = enqueue("traiter_lot", {"lot_id": "AUTRE"}, "cle-1", "cli_a", db=monde.db)
    assert j1.id == j2.id and j2.payload == {"lot_id": "lot_a"}
    assert len(JobStore(monde.db).lister()) == 1
    with pytest.raises(ValueError):
        enqueue("x", {}, "", db=monde.db)


def test_succes(monde, horloge):
    vus = []
    enqueue("t", {"n": 1}, "k", "cli_a", db=monde.db)
    w = _worker(monde, horloge, {"t": lambda ctx: vus.append(ctx.payload) or {"ok": True}})
    assert w.executer_un() == "done"
    assert w.executer_un() is None
    job = JobStore(monde.db).lister()[0]
    assert (job.statut, job.attempts, job.resultat) == ("done", 1, {"ok": True})
    assert vus == [{"n": 1}]
    assert metriques()["compteurs"]["jobs_ok"] == 1


def test_attente_exponentielle_puis_mort_apres_5_essais(monde, horloge):
    assert [delai_backoff(n).total_seconds() for n in (1, 2, 3, 4, 8, 20)] == [30, 60, 120, 240, 3600, 3600]

    def echoue(ctx):
        raise RuntimeError("texte de document confidentiel FICTIF")

    store = JobStore(monde.db)
    job = enqueue("t", {}, "k", "cli_a", db=monde.db)
    w = _worker(monde, horloge, {"t": echoue})
    for essai, attente in enumerate([30, 60, 120, 240], start=1):
        assert w.executer_un() == "pending"
        info = store.obtenir(job.id)
        assert info.attempts == essai and info.run_after == horloge.t + timedelta(seconds=attente)
        assert info.last_error == "RuntimeError"  # jamais le message (contenu possible)
        horloge.avancer(seconds=attente - 1)
        assert w.executer_un() is None  # pas encore
        horloge.avancer(seconds=1)
    assert w.executer_un() == "dead"
    assert store.obtenir(job.id).statut == "dead"
    with monde.db.operateur(FONDATEUR) as op:
        alertes = op.alertes()
    assert [a.kind for a in alertes] == ["job_mort"] and alertes[0].tenant_id == "cli_a"
    assert "confidentiel" not in alertes[0].message
    with monde.db.transaction_systeme() as s:
        assert s.query(AuditLog).filter_by(action="job_mort").count() == 1
    m = metriques()
    assert m["compteurs"]["jobs_echec"] == 4 and m["compteurs"]["jobs_mort"] == 1
    assert m["par_kind"]["jobs_mort"] == {"t": 1}
    horloge.avancer(days=1)
    assert w.executer_un() is None  # un job mort n'est plus repris
    assert store.relancer(job.id, acteur_id=FONDATEUR.id) and store.obtenir(job.id).statut == "pending"


def test_erreur_definitive_et_handler_inconnu(monde, horloge):
    def defin(ctx):
        raise ErreurDefinitive("lot introuvable")

    a = enqueue("defin", {}, "k1", db=monde.db)
    b = enqueue("inconnu", {}, "k2", db=monde.db)
    w = _worker(monde, horloge, {"defin": defin})
    assert {w.executer_un(), w.executer_un()} == {"dead"}
    store = JobStore(monde.db)
    assert store.obtenir(a.id).attempts == 1 and "lot introuvable" in store.obtenir(a.id).last_error
    assert store.obtenir(b.id).last_error == "handler_inconnu"


def test_bail_expire_reprise_par_un_autre_worker(monde, horloge):
    store = JobStore(monde.db)
    job = enqueue("t", {}, "k", db=monde.db)
    pris = store.reserver("w_mort", lease_s=60, now=horloge())
    assert pris.id == job.id and pris.attempts == 1
    assert store.reserver("w2", lease_s=60, now=horloge() + timedelta(seconds=59)) is None
    repris = store.reserver("w2", lease_s=60, now=horloge() + timedelta(seconds=61))
    assert repris.id == job.id and repris.attempts == 2 and repris.locked_by == "w2"
    # l'ancien worker ne peut plus rien écrire
    assert not store.terminer(job.id, "w_mort", {}, now=horloge())
    assert store.echouer(job.id, "w_mort", "x", now=horloge()) is None
    assert store.terminer(job.id, "w2", {"ok": 1}, now=horloge())


def test_bail_expire_apres_dernier_essai_donne_mort(monde, horloge):
    store = JobStore(monde.db)
    job = enqueue("t", {}, "k", db=monde.db, max_attempts=1)
    store.reserver("w_mort", lease_s=10, now=horloge())
    assert store.reserver("w2", lease_s=10, now=horloge() + timedelta(seconds=11)) is None
    assert store.obtenir(job.id).statut == "dead"


def test_battement_de_coeur_prolonge_le_bail(monde):
    store = JobStore(monde.db)
    job = enqueue("lent", {}, "k", db=monde.db)

    def lent(ctx):
        time.sleep(1.5)
        return {}

    w = Worker(monde.db, worker_id="w1", handlers={"lent": lent}, lease_s=1, heartbeat_s=0.2, poll_s=0.01)
    debut = maintenant()
    assert w.executer_un() == "done"
    info = store.obtenir(job.id)
    assert info.statut == "done" and info.attempts == 1
    with monde.db.transaction_systeme() as s:
        from controldone.storage.models import Job

        assert s.get(Job, job.id).heartbeat_at > debut + timedelta(seconds=0.5)


def test_arret_propre(monde):
    demarre, liberer = threading.Event(), threading.Event()

    def bloque(ctx):
        demarre.set()
        liberer.wait(5)
        return {"fini": True}

    for i in range(3):
        enqueue("b", {}, f"k{i}", db=monde.db)
    w = Worker(monde.db, worker_id="w1", handlers={"b": bloque}, poll_s=0.01)
    resultat = {}
    fil = threading.Thread(target=lambda: resultat.setdefault("n", w.boucle()))
    fil.start()
    assert demarre.wait(5)
    w.arreter()  # SIGTERM : on termine le job en cours, on n'en prend pas d'autre
    liberer.set()
    fil.join(5)
    assert resultat["n"] == 1
    statuts = sorted(j.statut for j in JobStore(monde.db).lister())
    assert statuts == ["done", "pending", "pending"]


def test_journaux_json_sans_contenu(monde, horloge):
    enregistrements: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            enregistrements.append(FormateurJSON().format(record))

    log = logging.getLogger("controldone.jobs.worker")
    h = Capture()
    etat = (log.disabled, log.level)
    log.disabled = False
    desactive = logging.root.manager.disable
    logging.disable(logging.NOTSET)  # bench_run appelle logging.disable(WARNING) au niveau global
    log.addHandler(h)
    log.setLevel(logging.INFO)
    try:
        enqueue("t", {"texte": "SECRET-DOCUMENT"}, "k", "cli_a", db=monde.db)

        def echoue(ctx):
            raise ValueError("TOTAL AMOUNT DUE USD 12,540.00 SECRET-DOCUMENT")

        _worker(monde, horloge, {"t": echoue}).executer_un()
        evenement(log, "test", contenu="SECRET-DOCUMENT", job_id="j1")
    finally:
        log.removeHandler(h)
        log.disabled, log.level = etat
        logging.disable(desactive)
    assert enregistrements
    for ligne in enregistrements:
        assert "SECRET" not in ligne and "12,540" not in ligne
        json.loads(ligne)
    fin = next(json.loads(x) for x in enregistrements if json.loads(x).get("event") == "job_fin")
    assert fin["erreur"] == "ValueError" and fin["kind"] == "t" and "duree_ms" in fin


def test_metriques_prometheus(monde, horloge):
    enqueue("t", {}, "k", db=monde.db)
    _worker(monde, horloge, {"t": lambda ctx: {}}).executer_un()
    texte = texte_prometheus()
    assert "controldone_jobs_ok_total 1" in texte
    assert 'controldone_job_duree_secondes_count{kind="t"} 1' in texte


# --- coûts IA ------------------------------------------------------------------------------------------


def test_cout_mensuel_et_plafonds(monde):
    db = monde.db
    with db.operateur(FONDATEUR) as op:
        op.modifier_client("cli_a", plafond_cout_ia_mensuel_eur=Decimal("10.00"))
    mois = datetime.now(UTC).strftime("%Y-%m")
    assert cout_mensuel("cli_a", db=db) == Decimal("0")  # l'usage de la fixture est d'un autre mois
    with db.tenant("cli_a", SYSTEME) as sc:
        e = enregistrer_cout(sc, cout_eur=Decimal("7.99"), jetons_entree=1000, jetons_sortie=100, modele="m")
    assert not e.alerte and e.llm_autorise
    with db.operateur(FONDATEUR) as op:
        assert op.alertes() == []
    with db.tenant("cli_a", SYSTEME) as sc:
        e = enregistrer_cout(sc, cout_eur=Decimal("0.01"))
    assert e.alerte and e.llm_autorise and e.cout == Decimal("8.00")
    with db.tenant("cli_a", SYSTEME) as sc:
        enregistrer_cout(sc, cout_eur=Decimal("0.50"))  # pas de seconde alerte 80 %
        e = enregistrer_cout(sc, cout_eur=Decimal("1.50"))
    assert e.arret and not e.llm_autorise
    assert etat_plafond("cli_a", db=db).arret
    assert cout_mensuel("cli_a", db=db, mois=mois) == Decimal("10.00")
    assert cout_mensuel("cli_b", db=db) == Decimal("0")  # aucun mélange entre clients
    with db.operateur(FONDATEUR) as op:
        kinds = sorted(a.kind for a in op.alertes())
        assert kinds == ["cout_ia_alerte", "cout_ia_plafond"]
        assert op.couts_ia(mois) == {"cli_a": Decimal("10.00")}
        # décision du fondateur : relèvement du plafond par les réglages du client
        op.modifier_client("cli_a", reglages={"plafond_cout_ia_mensuel_eur": "20"})
    assert etat_plafond("cli_a", db=db).llm_autorise


def test_registre_couts_db_cloisonne(monde):
    from controldone.extract.llm import CostGuard, EntreeCout

    reg = RegistreCoutsDB(monde.db, "cli_a")
    garde = CostGuard(reg, plafond_dossier=Decimal("0.50"), plafond_client_mensuel=Decimal("1.00"))
    assert garde.verifier("cli_a", "dos_a", Decimal("0.40")).autorise
    mois = datetime.now(UTC).strftime("%Y-%m")
    reg.enregistrer(EntreeCout("cli_a", "dos_a", None, mois, Decimal("0.45"), 10, 10, "m"))
    assert reg.total_dossier("dos_a") == Decimal("0.45")
    assert not garde.verifier("cli_a", "dos_a", Decimal("0.10")).autorise
    with pytest.raises(AccesRefuse):
        reg.total_client_mois("cli_b", mois)
    with pytest.raises(AccesRefuse):
        reg.enregistrer(EntreeCout("cli_b", None, None, mois, Decimal("1"), 0, 0, None))


# --- handler traiter_lot ------------------------------------------------------------------------------


@dataclass
class _Rd:
    dossier: Any
    documents: dict
    fichiers: dict
    pages: dict
    resultats: list
    execution: Any
    non_lus: list = field(default_factory=list)


def _faux_pipeline(appels: list):
    from controldone.model import Dossier as DossierM
    from controldone.model.documents import Fichier as FichierM
    from controldone.model.documents import Page
    from controldone.model.enums import Outcome
    from controldone.model.resultats import Execution, ResultatControle

    def traiter(source, profil, grilles, *, options):
        fichiers = sorted(p for p in source.rglob("*") if p.is_file())
        appels.append({"source": source, "fichiers": [p.relative_to(source).as_posix() for p in fichiers],
                       "contenus": [p.read_bytes() for p in fichiers], "client": profil.client_id,
                       "llm": options.llm, "grilles": len(grilles)})
        import hashlib

        f = FichierM(id="fic_pipeline", nom_original="facture.pdf", chemin_relatif="envoi_a/facture.pdf",
                     sha256=hashlib.sha256(fichiers[0].read_bytes()).hexdigest(), taille=1,
                     type_mime="application/pdf")
        d = DossierM(id="dos_pipeline", reference="D-2026-00042")
        ex = Execution.nouvelle(id="exe_1", cout_ia_eur=Decimal("0.12"), jetons_entree=100, jetons_sortie=10,
                                modele_llm="m")
        r = ResultatControle(id="res_p", controle_id="B1", dossier_id=d.id, dossier_version=1,
                             execution_id=ex.id, outcome=Outcome.conforme)
        page = Page(fichier_id=f.id, numero=1, texte="TEXTE DE PAGE FICTIF", sha256_texte="d" * 64)
        return [_Rd(dossier=d, documents={}, fichiers={f.id: f}, pages={f.id: [page]}, resultats=[r], execution=ex)]

    return traiter


def test_handler_traiter_lot(monde, horloge, monkeypatch):
    from controldone.pipeline import OptionsPipeline

    appels: list = []
    monkeypatch.setattr(handlers_mod, "charger_pipeline", lambda: (_faux_pipeline(appels), OptionsPipeline))
    job = enqueue("traiter_lot", {"lot_id": "lot_a"}, "traiter_lot:cli_a:lot_a", "cli_a", db=monde.db)
    w = _worker(monde, horloge, {"traiter_lot": handlers_mod.traiter_lot}, services={"vault": monde.vault})
    assert w.executer_un() == "done"
    assert appels[0]["fichiers"] == ["envoi_a/facture.pdf"] and appels[0]["contenus"] == [b"PDF FICTIF cli_a"]
    assert appels[0]["client"] == "cli_a" and appels[0]["llm"] is True
    assert JobStore(monde.db).obtenir(job.id).resultat["dossiers"] == 1
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.obtenir(Lot, "lot_a").statut == "traite"
        assert sc.lire_dossier("dos_pipeline").reference == "D-2026-00042"
        assert sc.cout_ia() == Decimal("0.22")  # 0.10 (fixture) + 0.12
        pages = [p for p in sc.lister(PageTexte) if p.fichier_id == "fic_a" and p.id != "pag_a"]
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.obtenir(Dossier, "dos_pipeline")
    # rejouer le même job (clé identique) ou un nouveau job sur le même lot : aucun doublon
    enqueue("traiter_lot", {"lot_id": "lot_a"}, "traiter_lot:cli_a:lot_a:bis", "cli_a", db=monde.db)
    assert w.executer_un() == "done" and len(appels) == 1
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.cout_ia() == Decimal("0.22")
    assert pages == []  # la page 1 de fic_a existait déjà (fixture) : pas de doublon


def test_handler_llm_coupe_au_plafond(monde, horloge, monkeypatch):
    from controldone.pipeline import OptionsPipeline

    appels: list = []
    monkeypatch.setattr(handlers_mod, "charger_pipeline", lambda: (_faux_pipeline(appels), OptionsPipeline))
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        enregistrer_cout(sc, cout_eur=Decimal("8.00"))
    enqueue("traiter_lot", {"lot_id": "lot_a"}, "k", "cli_a", db=monde.db)
    _worker(monde, horloge, {"traiter_lot": handlers_mod.traiter_lot}, services={"vault": monde.vault}).executer_un()
    assert appels[0]["llm"] is False


def test_handler_pipeline_absent_reessaie(monde, horloge, monkeypatch):
    import builtins

    vrai_import = builtins.__import__

    def import_sans_pipeline(nom, *a, **k):
        if nom == "controldone.pipeline":
            raise ImportError("absent")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", import_sans_pipeline)
    job = enqueue("traiter_lot", {"lot_id": "lot_a"}, "k", "cli_a", db=monde.db)
    w = _worker(monde, horloge, {"traiter_lot": handlers_mod.traiter_lot}, services={"vault": monde.vault})
    assert w.executer_un() == "pending"
    assert "pipeline indisponible" in JobStore(monde.db).obtenir(job.id).last_error


def test_handler_lot_d_un_autre_client_refuse(monde, horloge, monkeypatch):
    from controldone.pipeline import OptionsPipeline

    monkeypatch.setattr(handlers_mod, "charger_pipeline", lambda: (_faux_pipeline([]), OptionsPipeline))
    job = enqueue("traiter_lot", {"lot_id": "lot_b"}, "k", "cli_a", db=monde.db)  # lot de B, job de A
    w = _worker(monde, horloge, {"traiter_lot": handlers_mod.traiter_lot}, services={"vault": monde.vault})
    assert w.executer_un() == "pending"
    assert JobStore(monde.db).obtenir(job.id).last_error == "AccesRefuse"
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        assert sc.obtenir(Lot, "lot_b").statut == "recu"


@pytest.mark.parametrize("chemin,attendu", [
    ("envoi/facture.pdf", "envoi/facture.pdf"),
    ("../../etc/passwd", "etc/passwd"),
    ("/etc/passwd", "etc/passwd"),
    ("a\\..\\..\\b.pdf", "a/b.pdf"),
    ("", "defaut"),
    ("..", "defaut"),
])
def test_chemin_sur(tmp_path, chemin, attendu):
    cible = handlers_mod.chemin_sur(tmp_path, chemin, "defaut")
    assert cible == (tmp_path / attendu).resolve()


def test_handler_purge(monde, horloge):
    enqueue("purger_retention", {}, "purge:2026-10-01", db=monde.db)
    w = _worker(monde, horloge, {"purger_retention": handlers_mod.purger_retention}, services={"vault": monde.vault})
    assert w.executer_un() == "done"


def test_worker_main_once(monde, monkeypatch):
    from controldone.jobs.worker import main

    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", monde.db.url)
    enqueue("purger_retention", {}, "purge:main", db=monde.db)
    assert main(["--once", "--worker-id", "w-main"]) == 0
    assert JobStore(monde.db).lister()[0].statut == "done"


def test_handler_avec_le_vrai_pipeline(monde, horloge):
    """Intégration avec ``controldone.pipeline`` (si importable) : un lot illisible ne fait pas échouer le job."""
    pytest.importorskip("controldone.pipeline")
    job = enqueue("traiter_lot", {"lot_id": "lot_a"}, "reel", "cli_a", db=monde.db)
    w = _worker(monde, horloge, {"traiter_lot": handlers_mod.traiter_lot}, services={"vault": monde.vault})
    assert w.executer_un() == "done"
    assert JobStore(monde.db).obtenir(job.id).resultat["llm"] is True
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.obtenir(Lot, "lot_a").statut == "traite"
