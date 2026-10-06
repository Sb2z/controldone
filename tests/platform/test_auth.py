"""Primitives d'authentification : Argon2, TOTP (RFC 6238), sessions, CSRF, clés d'API, débit, rôles."""

from __future__ import annotations

import pytest
from aides_plateforme import FONDATEUR, MDP

from controldone.auth import (
    Acteur,
    Action,
    EchecAuthentification,
    GestionnaireSessions,
    LimiteurDebit,
    MotDePasseFaible,
    Ressource,
    Role,
    SessionInvalide,
    authentifier,
    code_totp,
    creer_cle_api,
    generer_secret,
    hacher_mot_de_passe,
    jeton_csrf,
    parametres_cookie,
    peut,
    revoquer_cle_api,
    secrets_session_depuis_env,
    uri_provisioning,
    verifier_cle_api,
    verifier_csrf,
    verifier_mot_de_passe,
    verifier_totp,
)
from controldone.auth.totp import code_hotp
from controldone.storage import AccesRefuse, CleManquante
from controldone.storage.cles import chiffrer_secret
from controldone.storage.comptes import creer_utilisateur, enregistrer_totp

# --- mots de passe -------------------------------------------------------------------------------------


def test_argon2():
    h = hacher_mot_de_passe(MDP)
    assert h.startswith("$argon2id$") and MDP not in h
    assert verifier_mot_de_passe(h, MDP) and not verifier_mot_de_passe(h, MDP + "x")
    assert not verifier_mot_de_passe("pas-un-hash", MDP)
    with pytest.raises(MotDePasseFaible):
        hacher_mot_de_passe("court")


# --- TOTP ----------------------------------------------------------------------------------------------

_SECRET_RFC = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32("12345678901234567890")


@pytest.mark.parametrize(
    "t,attendu",
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_vecteurs_rfc6238(t, attendu):
    assert code_totp(_SECRET_RFC, t, chiffres=8) == attendu


def test_hotp_vecteurs_rfc4226():
    attendus = [
        "755224",
        "287082",
        "359152",
        "969429",
        "338314",
        "254676",
        "287922",
        "162583",
        "399871",
        "520489",
    ]
    assert [code_hotp(b"12345678901234567890", i) for i in range(10)] == attendus


def test_totp_fenetre_et_formats():
    s = generer_secret()
    t = 1_800_000_000
    assert verifier_totp(s, code_totp(s, t), t) == t // 30
    assert verifier_totp(s, code_totp(s, t - 30), t) == t // 30 - 1  # dérive d'un pas
    assert verifier_totp(s, code_totp(s, t - 90), t) is None
    assert verifier_totp(s, "12345", t) is None and verifier_totp(s, "abcdef", t) is None
    assert verifier_totp(s, "", t) is None
    assert uri_provisioning(s, "fondateur@exemple-fictif.test").startswith("otpauth://totp/ControlDOne:")


# --- ouverture de session ----------------------------------------------------------------------------


@pytest.fixture
def fondateur_totp(monde, cles):
    secret = generer_secret()
    creer_utilisateur(
        monde.db,
        user_id=FONDATEUR.id,
        email="fondateur@exemple-fictif.test",
        mot_de_passe_hash=hacher_mot_de_passe(MDP),
        role=Role.fondateur,
        acteur=FONDATEUR,
    )
    enregistrer_totp(monde.db, FONDATEUR.id, chiffrer_secret(cles, secret), acteur=FONDATEUR)
    return secret


def test_fondateur_exige_le_second_facteur(monde, cles, fondateur_totp):
    t = 1_800_000_000
    email = "fondateur@exemple-fictif.test"
    for kwargs in ({}, {"code_totp": "000000"}):
        with pytest.raises(EchecAuthentification):
            authentifier(monde.db, email, MDP, cles_maitresses=cles, t=t, **kwargs)
    a = authentifier(
        monde.db,
        email,
        MDP,
        cles_maitresses=cles,
        code_totp=code_totp(fondateur_totp, t),
        t=t,
        ip="198.51.100.1",
    )
    assert a.role is Role.fondateur and a.ip == "198.51.100.1"
    with pytest.raises(EchecAuthentification):  # rejeu du même code refusé
        authentifier(monde.db, email, MDP, cles_maitresses=cles, code_totp=code_totp(fondateur_totp, t), t=t)
    with pytest.raises(EchecAuthentification):  # code plus ancien que le dernier utilisé
        authentifier(
            monde.db, email, MDP, cles_maitresses=cles, code_totp=code_totp(fondateur_totp, t - 30), t=t
        )
    assert (
        authentifier(
            monde.db, email, MDP, cles_maitresses=cles, code_totp=code_totp(fondateur_totp, t + 30), t=t + 30
        ).role
        is Role.fondateur
    )


def test_utilisateur_client(monde, cles):
    a = authentifier(monde.db, "ADMIN_A@exemple-fictif.test ", MDP, cles_maitresses=cles)
    assert (a.role, a.tenant_id) == (Role.client_admin, "cli_a")
    with pytest.raises(EchecAuthentification):
        authentifier(monde.db, "admin_a@exemple-fictif.test", MDP, cles_maitresses=cles, tenant_id="cli_b")
    for email, mdp in (("admin_a@exemple-fictif.test", "mauvais-mot-de-passe"), ("inconnu@x.test", MDP)):
        with pytest.raises(EchecAuthentification) as exc:
            authentifier(monde.db, email, mdp, cles_maitresses=cles)
        assert str(exc.value) == "identifiants invalides"


def test_creation_de_compte_droits(monde):
    with pytest.raises(AccesRefuse):
        creer_utilisateur(
            monde.db,
            user_id="u_x",
            email="x@x.test",
            mot_de_passe_hash="h",
            role=Role.fondateur,
            acteur=monde.acteurs["admin_a"],
        )
    with pytest.raises(AccesRefuse):
        creer_utilisateur(
            monde.db,
            user_id="u_y",
            email="y@x.test",
            mot_de_passe_hash="h",
            role=Role.client_lecteur,
            acteur=monde.acteurs["lecteur_a"],
        )


# --- jetons de session -------------------------------------------------------------------------------


class Horloge:
    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t


SECRET = "s" * 40


def test_session_aller_retour_et_falsification():
    h = Horloge()
    g = GestionnaireSessions(SECRET, horloge=h)
    jeton = g.emettre(Acteur("usr_admin_a", Role.client_admin, "cli_a"))
    d = g.lire(jeton)
    assert (d.user_id, d.role, d.tenant_id) == ("usr_admin_a", Role.client_admin, "cli_a")
    assert d.acteur().tenant_id == "cli_a"
    with pytest.raises(SessionInvalide):
        g.lire(jeton[:-2] + ("A" if jeton[-2] != "A" else "B") + jeton[-1])
    with pytest.raises(SessionInvalide):
        GestionnaireSessions("t" * 40, horloge=h).lire(jeton)
    with pytest.raises(SessionInvalide):
        g.lire("n'importe quoi")


def test_session_expirations_rotation_revocation():
    h = Horloge()
    g = GestionnaireSessions(SECRET, inactivite_s=1800, duree_absolue_s=8 * 3600, rotation_s=900, horloge=h)
    jeton = g.emettre(Acteur("u", Role.client_lecteur, "cli_a"))
    h.t += 600
    assert g.rafraichir(jeton)[1] is None
    h.t += 400
    d, nouveau = g.rafraichir(jeton)
    assert nouveau and g.lire(nouveau).sid == d.sid and g.lire(nouveau).debut == d.debut
    h.t += 1801
    with pytest.raises(SessionInvalide, match="inactivité"):
        g.lire(nouveau)
    # durée absolue malgré les rotations
    j = g.emettre(Acteur("u", Role.client_lecteur, "cli_a"))
    for _ in range(40):
        h.t += 1000
        try:
            _, n = g.rafraichir(j)
        except SessionInvalide as exc:
            assert "durée maximale" in str(exc)
            break
        j = n or j
    else:
        pytest.fail("la durée absolue n'a pas été appliquée")
    j = g.emettre(Acteur("u", Role.client_lecteur, "cli_a"))
    g.revoquer(g.lire(j).sid)
    with pytest.raises(SessionInvalide, match="révoquée"):
        g.lire(j)


def test_session_fondateur_sans_second_facteur_refusee():
    g = GestionnaireSessions(SECRET, horloge=Horloge())
    with pytest.raises(SessionInvalide):
        g.lire(g.emettre(FONDATEUR))
    assert g.lire(g.emettre(FONDATEUR, deux_facteurs=True)).role is Role.fondateur
    with pytest.raises(ValueError):
        g.emettre(Acteur.systeme())
    with pytest.raises(ValueError):
        GestionnaireSessions("court")


def test_rotation_du_secret_de_signature():
    h = Horloge()
    ancien = GestionnaireSessions(["a" * 40], horloge=h)
    jeton = ancien.emettre(Acteur("u", Role.client_admin, "cli_a"))
    nouveau = GestionnaireSessions(["a" * 40, "b" * 40], horloge=h)
    assert nouveau.lire(jeton).user_id == "u"
    jeton2 = nouveau.emettre(Acteur("u", Role.client_admin, "cli_a"))
    with pytest.raises(SessionInvalide):
        ancien.lire(jeton2)


def test_cookie_et_csrf():
    p = parametres_cookie(prod=True)
    assert p["httponly"] and p["secure"] and p["samesite"] == "strict" and p["key"].startswith("__Host-")
    assert parametres_cookie(prod=False)["secure"] is False
    j = jeton_csrf(SECRET, "sid1")
    assert verifier_csrf(SECRET, "sid1", j)
    assert not verifier_csrf(SECRET, "sid2", j) and not verifier_csrf("x" * 40, "sid1", j)
    assert not verifier_csrf(SECRET, "sid1", None) and not verifier_csrf(SECRET, "sid1", "abc")
    assert jeton_csrf(SECRET, "sid1") != j


def test_secret_de_session_depuis_env(monkeypatch):
    monkeypatch.setenv("CONTROLDONE_SECRET_KEY", "x" * 40 + "," + "y" * 40)
    assert secrets_session_depuis_env() == ["x" * 40, "y" * 40]
    monkeypatch.delenv("CONTROLDONE_SECRET_KEY")
    assert len(secrets_session_depuis_env(mode="test")[0]) == 64
    with pytest.raises(CleManquante):
        secrets_session_depuis_env(mode="prod")


# --- clés d'API -------------------------------------------------------------------------------------------


def test_cles_api(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        cree = creer_cle_api(sc, "ERP FICTIF")
        from controldone.storage.models import CleApi

        stockee = sc.obtenir(CleApi, cree.id)
        assert cree.cle.split("_", 2)[2] not in stockee.hash and stockee.prefixe == cree.prefixe
    acteur = verifier_cle_api(monde.db, cree.cle)
    assert acteur.role is Role.client_admin and acteur.tenant_id == "cli_a"
    for mauvaise in (
        cree.cle + "x",
        cree.cle.replace(cree.prefixe, "000000000000"),
        "cdk_",
        "",
        "abc",
        f"cdk_{cree.prefixe}_",
    ):
        assert verifier_cle_api(monde.db, mauvaise) is None
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        revoquer_cle_api(sc, cree.id)
    assert verifier_cle_api(monde.db, cree.cle) is None
    with monde.db.tenant("cli_a", monde.acteurs["lecteur_a"]) as sc, pytest.raises(AccesRefuse):
        creer_cle_api(sc, "interdit")


# --- débit ----------------------------------------------------------------------------------------------


def test_limiteur_de_debit():
    t = [0.0]
    lim = LimiteurDebit(3, 1.0, horloge=lambda: t[0], max_cles=2)
    assert [lim.autoriser("ip1") for _ in range(4)] == [True, True, True, False]
    assert lim.autoriser("ip2")  # indépendant
    assert lim.attente("ip1") == pytest.approx(1.0)
    t[0] += 1.0
    assert lim.autoriser("ip1") and not lim.autoriser("ip1")
    lim.autoriser("ip3")
    assert len(lim._seaux) == 2  # borné (LRU)
    with pytest.raises(ValueError):
        LimiteurDebit(0, 1)


# --- matrice des permissions --------------------------------------------------------------------------------

A, B = Ressource("dossier", "cli_a"), Ressource("dossier", "cli_b")
PLATEFORME = Ressource("outbox", None)
ADMIN_A = Acteur("u1", Role.client_admin, "cli_a")
LECTEUR_A = Acteur("u2", Role.client_lecteur, "cli_a")


@pytest.mark.parametrize(
    "acteur,action,ressource,attendu",
    [
        (FONDATEUR, Action.valider_constat, A, True),
        (FONDATEUR, Action.changer_autonomie, PLATEFORME, True),
        (FONDATEUR, Action.supprimer_client, B, True),
        (ADMIN_A, Action.lire, A, True),
        (ADMIN_A, Action.deposer, A, True),
        (ADMIN_A, Action.declarer_recouvrement, A, True),
        (ADMIN_A, Action.gerer_cles_api, A, True),
        (ADMIN_A, Action.lire, B, False),
        (ADMIN_A, Action.deposer, B, False),
        (ADMIN_A, Action.valider_constat, A, False),
        (ADMIN_A, Action.publier_rapport, A, False),
        (ADMIN_A, Action.valider_grille, A, False),
        (ADMIN_A, Action.approuver_sortie, A, False),
        (ADMIN_A, Action.supprimer_client, A, False),
        (ADMIN_A, Action.lire_constats_proposes, A, False),
        (ADMIN_A, Action.lire, PLATEFORME, False),
        (ADMIN_A, Action.lire, None, False),
        (LECTEUR_A, Action.lire, A, True),
        (LECTEUR_A, Action.ecrire, A, False),
        (LECTEUR_A, Action.deposer, A, False),
        (LECTEUR_A, Action.exporter, A, False),
        (Acteur.systeme(), Action.ecrire, A, True),
        (Acteur.systeme(), Action.valider_constat, A, False),
        (Acteur.systeme(), Action.approuver_sortie, A, False),
        (Acteur.systeme(), Action.changer_autonomie, PLATEFORME, False),
        (None, Action.lire, A, False),
        (Acteur("u", Role.client_admin, None), Action.lire, A, False),
        (ADMIN_A, "action_inconnue", A, False),
    ],
)
def test_matrice_des_permissions(acteur, action, ressource, attendu):
    assert peut(acteur, action, ressource) is attendu


def test_ressource_objet_avec_tenant_id(monde):
    class Obj:
        tenant_id = "cli_a"

    assert peut(ADMIN_A, Action.lire, Obj()) and not peut(
        Acteur("u", Role.client_admin, "cli_b"), Action.lire, Obj()
    )
