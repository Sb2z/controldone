"""Primitives d'authentification et d'autorisation (SPEC §4, §20.1)."""

from controldone.auth.cles_api import CleApiCreee, creer_cle_api, revoquer_cle_api, verifier_cle_api
from controldone.auth.debit import Limiteur, LimiteurDebit, LimiteurDebitPartage, sel_debit
from controldone.auth.jetons import (
    DonneesSession,
    GestionnaireSessions,
    SessionInvalide,
    jeton_csrf,
    parametres_cookie,
    secrets_session_depuis_env,
    verifier_csrf,
)
from controldone.auth.motdepasse import (
    MotDePasseFaible,
    doit_rehacher,
    hacher_mot_de_passe,
    verifier_mot_de_passe,
)
from controldone.auth.revocation import RegistreRevocations
from controldone.auth.roles import Acteur, Action, Ressource, Role, peut
from controldone.auth.service import EchecAuthentification, authentifier
from controldone.auth.totp import code_totp, generer_secret, uri_provisioning, verifier_totp

__all__ = [
    "Acteur",
    "Action",
    "CleApiCreee",
    "DonneesSession",
    "EchecAuthentification",
    "GestionnaireSessions",
    "Limiteur",
    "LimiteurDebit",
    "LimiteurDebitPartage",
    "MotDePasseFaible",
    "RegistreRevocations",
    "Ressource",
    "Role",
    "SessionInvalide",
    "authentifier",
    "code_totp",
    "creer_cle_api",
    "doit_rehacher",
    "generer_secret",
    "hacher_mot_de_passe",
    "jeton_csrf",
    "parametres_cookie",
    "peut",
    "revoquer_cle_api",
    "secrets_session_depuis_env",
    "sel_debit",
    "uri_provisioning",
    "verifier_cle_api",
    "verifier_csrf",
    "verifier_mot_de_passe",
    "verifier_totp",
]
