"""Notifications poussées des alertes (D-3502) : rien n'est envoyé par défaut ni hors production, aucune donnée
client dans ce qui part, une notification par type et par jour, nouvel essai en cas d'échec. Points de
terminaison factices : serveur HTTP local (127.0.0.1) et faux serveur SMTP."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from controldone.services import notifications as nt
from controldone.services.notifications import (
    CanalCourriel,
    CanalWebhook,
    ConfigNotifications,
    notifier_alertes,
)
from controldone.storage.alertes import emettre_alerte
from controldone.storage.models import Alerte, NotificationAlerte

NOW = datetime(2026, 10, 6, 2, 30, tzinfo=UTC)
SECRET_CLIENT = "CLIENT A FICTIF — facture FA-2026-0042 FICTIVE"


class _Recepteur(BaseHTTPRequestHandler):
    recus: list[tuple[str, dict[str, str], bytes]] = []  # noqa: RUF012
    code = 200

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        type(self).recus.append((self.path, dict(self.headers), self.rfile.read(n)))
        self.send_response(type(self).code)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def recepteur():
    class R(_Recepteur):
        recus = []  # noqa: RUF012
        code = 200

    serveur = HTTPServer(("127.0.0.1", 0), R)
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    yield R, f"http://127.0.0.1:{serveur.server_address[1]}/crochet"
    serveur.shutdown()
    serveur.server_close()


class FauxSMTP:
    envois: list = []  # noqa: RUF012

    def __init__(self, hote, port, timeout=None):
        self.hote, self.port, self.etapes = hote, port, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.etapes.append("starttls")

    def login(self, utilisateur, mot_de_passe):
        self.etapes.append(("login", utilisateur))

    def send_message(self, msg):
        type(self).envois.append((self.etapes[:], msg))


def _alerte(db, cle, kind="sauvegarde_echec", quand=NOW, tenant=None):
    with db.transaction_systeme() as s:
        emettre_alerte(
            s,
            cle=cle,
            kind=kind,
            message=f"Échec : {SECRET_CLIENT}",
            tenant_id=tenant,
            details={"archive": "controldone-20261006.tar.gz.enc", "client": SECRET_CLIENT},
        )
        a = s.query(Alerte).filter_by(cle=cle).one()
        a.cree_le = quand


def _cfg(*canaux, types=None) -> ConfigNotifications:
    return ConfigNotifications(mode="prod", canaux=list(canaux), types=types)


def _etats(db):
    with db.transaction_systeme() as s:
        return {n.cle: (n.statut, n.essais, n.nombre) for n in s.query(NotificationAlerte)}


# --- rien par défaut -------------------------------------------------------------------------------------


def test_aucun_canal_par_defaut(monkeypatch):
    for v in list(__import__("os").environ):
        if v.startswith("CONTROLDONE_NOTIF_"):
            monkeypatch.delenv(v)
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    cfg = ConfigNotifications.depuis_env()
    assert cfg.canaux == [] and not cfg.actif and "aucun canal" in cfg.motif_inactif()


@pytest.mark.parametrize("mode", ["dev", "test"])
def test_jamais_hors_production_meme_configure(db, monkeypatch, recepteur, mode):
    R, url = recepteur
    monkeypatch.setenv("CONTROLDONE_ENV", mode)
    monkeypatch.setenv("CONTROLDONE_NOTIF_WEBHOOK_URL", url)
    cfg = ConfigNotifications.depuis_env()
    assert len(cfg.canaux) == 1 and not cfg.actif
    _alerte(db, "k1")
    rapport = notifier_alertes(db, cfg, now=NOW)
    assert not rapport.actif and R.recus == []
    with db.transaction_systeme() as s:  # rien d'écrit : rien de perdu si on active plus tard
        assert s.query(Alerte).one().notifiee_le is None and s.query(NotificationAlerte).count() == 0


def test_configuration_refusee(monkeypatch):
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.setenv("CONTROLDONE_NOTIF_WEBHOOK_URL", "http://hooks.exemple-fictif.test/x")  # pas HTTPS
    monkeypatch.setenv("CONTROLDONE_NOTIF_SMTP_HOTE", "smtp.exemple-fictif.test")
    monkeypatch.setenv("CONTROLDONE_NOTIF_SMTP_SECURITE", "aucune")  # en clair vers un hôte distant
    monkeypatch.setenv("CONTROLDONE_NOTIF_COURRIEL_DE", "alertes@exemple-fictif.test")
    monkeypatch.setenv("CONTROLDONE_NOTIF_COURRIEL_A", "fondateur@exemple-fictif.test")
    cfg = ConfigNotifications.depuis_env()
    assert cfg.canaux == [] and len(cfg.erreurs) == 2


def test_configuration_complete(monkeypatch):
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.setenv("CONTROLDONE_NOTIF_WEBHOOK_URL", "https://hooks.exemple-fictif.test/x")
    monkeypatch.setenv("CONTROLDONE_NOTIF_SMTP_HOTE", "smtp.exemple-fictif.test")
    monkeypatch.setenv("CONTROLDONE_NOTIF_SMTP_MOT_DE_PASSE", "MDP-FICTIF")
    monkeypatch.setenv("CONTROLDONE_NOTIF_COURRIEL_DE", "alertes@exemple-fictif.test")
    monkeypatch.setenv("CONTROLDONE_NOTIF_COURRIEL_A", "a@exemple-fictif.test, b@exemple-fictif.test")
    monkeypatch.setenv("CONTROLDONE_NOTIF_TYPES", "sauvegarde_echec,job_mort")
    cfg = ConfigNotifications.depuis_env()
    assert cfg.actif and [c.nom for c in cfg.canaux] == ["webhook", "courriel"]
    courriel = cfg.canaux[1]
    assert courriel.port == 587 and courriel.destinataires == [
        "a@exemple-fictif.test",
        "b@exemple-fictif.test",
    ]
    assert "MDP-FICTIF" not in repr(courriel)
    assert cfg.types == {"sauvegarde_echec", "job_mort"}


# --- envoi -----------------------------------------------------------------------------------------------


def test_webhook_une_par_type_et_par_jour_sans_donnee_client(db, recepteur):
    R, url = recepteur
    cfg = _cfg(CanalWebhook(url=url))
    _alerte(db, "sauvegarde_echec:2026-10-06")
    _alerte(db, "job_mort:j1", kind="job_mort", tenant="cli_a")
    _alerte(db, "job_mort:j2", kind="job_mort", tenant="cli_b")
    rapport = notifier_alertes(db, cfg, now=NOW)
    assert rapport.envoyees == {"job_mort": 2, "sauvegarde_echec": 1}
    assert len(R.recus) == 2
    for chemin, entetes, corps in R.recus:
        assert chemin == "/crochet" and entetes["Content-Type"] == "application/json"
        charge = json.loads(corps)
        assert set(charge) == {
            "source",
            "evenement",
            "kind",
            "libelle",
            "nombre",
            "horodatage",
            "lien",
            "text",
        }
        assert charge["lien"] == "/admin/alertes"
        texte = corps.decode()
        for interdit in ("FICTIF", "cli_a", "cli_b", "controldone-2026", "Échec"):
            assert interdit not in texte
    job = next(json.loads(c) for _, _, c in R.recus if b"job_mort" in c)
    assert job["nombre"] == 2 and job["libelle"] == "Tâche en échec définitif"

    # même jour : nouvelle alerte du même type regroupée, rien n'est renvoyé
    _alerte(db, "job_mort:j3", kind="job_mort", quand=NOW + timedelta(hours=1))
    rapport = notifier_alertes(db, cfg, now=NOW + timedelta(hours=1))
    assert rapport.envoyees == {} and rapport.regroupees == 1 and len(R.recus) == 2
    # le lendemain : de nouveau une notification pour ce type
    _alerte(db, "job_mort:j4", kind="job_mort", quand=NOW + timedelta(days=1))
    rapport = notifier_alertes(db, cfg, now=NOW + timedelta(days=1))
    assert rapport.envoyees == {"job_mort": 1} and len(R.recus) == 3
    assert notifier_alertes(db, cfg, now=NOW + timedelta(days=1)).envoyees == {}  # plus rien à faire


def test_historique_et_alertes_lues_jamais_envoyes(db, recepteur):
    R, url = recepteur
    _alerte(db, "ancienne", quand=NOW - timedelta(days=3))
    _alerte(db, "lue", kind="job_mort")
    with db.transaction_systeme() as s:
        s.query(Alerte).filter_by(cle="lue").one().lue_le = NOW
    rapport = notifier_alertes(db, _cfg(CanalWebhook(url=url)), now=NOW)
    assert rapport.envoyees == {} and R.recus == []
    with db.transaction_systeme() as s:
        assert all(a.notifiee_le is not None for a in s.query(Alerte))


def test_echec_retente_puis_abandonne(db, recepteur):
    R, url = recepteur
    R.code = 500
    cfg = _cfg(CanalWebhook(url=url))
    _alerte(db, "k1")
    for essai in range(1, nt.ESSAIS_MAX_PAR_JOUR + 1):
        rapport = notifier_alertes(db, cfg, now=NOW + timedelta(minutes=5 * essai))
        assert rapport.echecs == {"sauvegarde_echec": ["webhook"]}
        assert _etats(db)["sauvegarde_echec:2026-10-06"][:2] == ("echec", essai)
    assert len(R.recus) == nt.ESSAIS_MAX_PAR_JOUR
    rapport = notifier_alertes(db, cfg, now=NOW + timedelta(hours=2))
    assert rapport.echecs == {} and len(R.recus) == nt.ESSAIS_MAX_PAR_JOUR  # plus d'essai ce jour-là


def test_echec_puis_reussite(db, recepteur):
    R, url = recepteur
    R.code = 503
    cfg = _cfg(CanalWebhook(url=url))
    _alerte(db, "k1")
    notifier_alertes(db, cfg, now=NOW)
    R.code = 204
    rapport = notifier_alertes(db, cfg, now=NOW + timedelta(minutes=5))
    assert rapport.envoyees == {"sauvegarde_echec": 1}
    assert _etats(db)["sauvegarde_echec:2026-10-06"] == ("envoyee", 2, 1)


def test_format_texte_pour_ntfy(db, recepteur):
    R, url = recepteur
    _alerte(db, "k1")
    notifier_alertes(db, _cfg(CanalWebhook(url=url, format="texte")), now=NOW)
    ((_, entetes, corps),) = R.recus
    assert entetes["Content-Type"].startswith("text/plain")
    assert corps.decode().startswith("ControlDOne — Sauvegarde en échec (1)")


def test_redirection_non_suivie(db, recepteur):
    R, url = recepteur
    R.code = 302
    _alerte(db, "k1")
    rapport = notifier_alertes(db, _cfg(CanalWebhook(url=url)), now=NOW)
    assert rapport.echecs == {"sauvegarde_echec": ["webhook"]}


def test_courriel_sans_donnee_client(db):
    FauxSMTP.envois = []
    canal = CanalCourriel(
        hote="smtp.exemple-fictif.test",
        port=587,
        expediteur="alertes@exemple-fictif.test",
        destinataires=["fondateur@exemple-fictif.test"],
        utilisateur="alertes",
        mot_de_passe="MDP-FICTIF",
        fabrique=FauxSMTP,
    )
    _alerte(db, "k1", kind="sauvegarde_verification_echec")
    rapport = notifier_alertes(db, _cfg(canal), now=NOW)
    assert rapport.envoyees == {"sauvegarde_verification_echec": 1}
    ((etapes, msg),) = FauxSMTP.envois
    assert etapes == ["starttls", ("login", "alertes")]
    assert msg["To"] == "fondateur@exemple-fictif.test"
    assert msg["Subject"] == "[ControlDOne] Sauvegarde non conforme (1)"
    corps = msg.get_content()
    assert "/admin/alertes" in corps and "FICTIF" not in corps and "controldone-2026" not in corps


def test_un_canal_en_echec_n_empeche_pas_l_autre(db, recepteur):
    R, url = recepteur
    FauxSMTP.envois = []

    class SMTPEnPanne(FauxSMTP):
        def send_message(self, msg):
            raise OSError("relais injoignable")

    courriel = CanalCourriel(
        hote="smtp.exemple-fictif.test",
        port=587,
        expediteur="a@exemple-fictif.test",
        destinataires=["b@exemple-fictif.test"],
        fabrique=SMTPEnPanne,
    )
    _alerte(db, "k1")
    rapport = notifier_alertes(db, _cfg(courriel, CanalWebhook(url=url)), now=NOW)
    assert rapport.envoyees == {"sauvegarde_echec": 1} and rapport.echecs == {
        "sauvegarde_echec": ["courriel"]
    }
    assert len(R.recus) == 1 and _etats(db)["sauvegarde_echec:2026-10-06"][0] == "envoyee"


def test_types_filtres(db, recepteur):
    R, url = recepteur
    _alerte(db, "k1", kind="cout_ia_alerte")
    _alerte(db, "k2")
    rapport = notifier_alertes(
        db, _cfg(CanalWebhook(url=url), types=frozenset({"sauvegarde_echec"})), now=NOW
    )
    assert rapport.envoyees == {"sauvegarde_echec": 1} and rapport.ecartees == 1 and len(R.recus) == 1


def test_cli_etat_et_notifier_inactifs_en_test(monkeypatch, capsys, tmp_path):
    from controldone.cli import main

    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", f"sqlite:///{tmp_path}/n.db")
    monkeypatch.setenv("CONTROLDONE_NOTIF_WEBHOOK_URL", "https://hooks.exemple-fictif.test/SECRET-FICTIF")
    from controldone.storage import Database

    d = Database(f"sqlite:///{tmp_path}/n.db")
    d.creer_schema()
    d.fermer()
    assert main(["alertes", "etat"]) == 0
    sortie = capsys.readouterr().out
    assert "inactives" in sortie and "canal : webhook" in sortie and "SECRET-FICTIF" not in sortie
    assert main(["alertes", "notifier"]) == 0
    assert main(["alertes", "essai"]) == 2


# --- ntfy de premier rang, historique (D-4104) -------------------------------------------------------------


def test_ntfy_jeton_priorite_et_url_jamais_affichee(db, recepteur, monkeypatch):
    R, url = recepteur
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.setenv("CONTROLDONE_NOTIF_WEBHOOK_URL", url.replace("/crochet", "/controldone-SUJET-FICTIF"))
    monkeypatch.setenv("CONTROLDONE_NOTIF_WEBHOOK_FORMAT", "texte")
    monkeypatch.setenv("CONTROLDONE_NOTIF_WEBHOOK_JETON", "tk_JETON_FICTIF")
    monkeypatch.setenv("CONTROLDONE_NOTIF_NTFY_PRIORITE", "5")
    cfg = ConfigNotifications.depuis_env()
    assert cfg.actif and cfg.erreurs == []
    assert "SUJET-FICTIF" not in repr(cfg) and "JETON_FICTIF" not in repr(cfg)
    _alerte(db, "k1")
    notifier_alertes(db, cfg, now=NOW)
    ((chemin, entetes, _),) = R.recus
    assert chemin == "/controldone-SUJET-FICTIF"
    assert entetes["Authorization"] == "Bearer tk_JETON_FICTIF" and entetes["Priority"] == "5"
    reussis, rates = nt.envoyer_essai(cfg, now=NOW, db=db)
    assert reussis == ["webhook"] and rates == [] and R.recus[-1][1]["Priority"] == "3"
    monkeypatch.setenv("CONTROLDONE_NOTIF_NTFY_PRIORITE", "9")
    assert any("PRIORITE" in e for e in ConfigNotifications.depuis_env().erreurs)


def test_historique_et_etat_des_canaux(db, recepteur):
    _r, url = recepteur
    FauxSMTP.envois = []

    class SMTPEnPanne(FauxSMTP):
        def send_message(self, msg):
            raise OSError("relais injoignable")

    courriel = CanalCourriel(
        hote="smtp.exemple-fictif.test",
        port=587,
        expediteur="a@exemple-fictif.test",
        destinataires=["b@exemple-fictif.test"],
        fabrique=SMTPEnPanne,
    )
    cfg = _cfg(courriel, CanalWebhook(url=url, format="texte"))
    _alerte(db, "k1")
    _alerte(db, "k2", kind="job_mort")
    notifier_alertes(db, cfg, now=NOW)
    nt.envoyer_essai(cfg, now=NOW + timedelta(minutes=1), db=db)
    h = nt.historique(db, config=cfg, now=NOW + timedelta(hours=1))
    assert h.actif and h.canaux_configures == ("courriel", "webhook")
    assert h.notifications[0].kind == "essai"
    assert {n.kind for n in h.notifications} == {"essai", "sauvegarde_echec", "job_mort"}
    sauv = next(n for n in h.notifications if n.kind == "sauvegarde_echec")
    assert (
        sauv.envoyee and sauv.jour == "2026-10-06" and sauv.canaux == {"webhook": "ok", "courriel": "echec"}
    )
    assert h.libelle("sauvegarde_echec") == "Sauvegarde en échec"
    assert h.canaux["courriel"].en_echec and not h.canaux["webhook"].en_echec
    assert h.canaux["webhook"].dernier_succes is not None
    texte = repr(h)
    assert url not in texte and "exemple-fictif.test" not in texte and SECRET_CLIENT not in texte
    # au-delà de la fenêtre demandée : rien
    assert nt.historique(db, config=cfg, now=NOW + timedelta(days=40)).notifications == []


def test_historique_ancien_format_des_canaux(db):
    from controldone.storage.alertes import historique_notifications

    with db.transaction_systeme() as s:
        s.add(
            NotificationAlerte(
                cle="job_mort:2026-10-01",
                kind="job_mort",
                nombre=2,
                canaux="webhook",
                statut="envoyee",
                essais=1,
                cree_le=NOW,
                envoyee_le=NOW,
            )
        )
    with db.transaction_systeme() as s:
        (n,) = historique_notifications(s)
    assert n.canaux == {"webhook": "ok"} and n.jour == "2026-10-01"


def test_cli_historique(monkeypatch, capsys, tmp_path):
    from controldone.cli import main
    from controldone.storage import Database

    url = f"sqlite:///{tmp_path}/n.db"
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", url)
    d = Database(url)
    d.creer_schema()
    with d.transaction_systeme() as s:
        s.add(
            NotificationAlerte(
                cle=f"sauvegarde_echec:{datetime.now(UTC):%Y-%m-%d}",
                kind="sauvegarde_echec",
                nombre=1,
                canaux="webhook:echec",
                statut="echec",
                essais=2,
                cree_le=datetime.now(UTC),
            )
        )
    d.fermer()
    assert main(["alertes", "historique"]) == 0
    sortie = capsys.readouterr().out
    assert "Sauvegarde en échec" in sortie and "EN ÉCHEC" in sortie and "essais 2" in sortie
