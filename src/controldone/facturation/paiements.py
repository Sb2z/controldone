"""Paiements : Stripe en **mode test** (``PaiementStripe``) ou bouchon local (``PaiementBouchon``).

- Clés lues **uniquement** dans l'environnement : ``STRIPE_SECRET_KEY`` (doit commencer par ``sk_test_`` ;
  une clé ``sk_live_`` n'est acceptée que si ``CONTROLDONE_ENV=prod`` **et** ``STRIPE_LIVE_OK=1``),
  ``STRIPE_WEBHOOK_SECRET`` (``whsec_…``) pour vérifier la signature des webhooks.
- Sans clé : ``PaiementBouchon`` (automatique) simule Checkout, l'abonnement et les webhooks, signés comme
  ceux de Stripe et vérifiés par le même ``stripe.Webhook.construct_event`` : tout le flux est testable
  hors ligne. Aucun appel réseau dans les tests.
- La facture légale est **toujours** la facture Factur-X du fondateur (numérotée, validée) ; Stripe ne sert
  qu'à encaisser. Montants envoyés à Stripe : TTC en centimes (calculés par notre code, pas de Stripe Tax).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "SECRET_WEBHOOK_BOUCHON",
    "CleStripeRefusee",
    "FournisseurPaiement",
    "PaiementBouchon",
    "PaiementStripe",
    "SessionPaiement",
    "SignatureInvalide",
    "centimes",
    "fournisseur_depuis_env",
    "signer_charge",
    "verifier_cle_stripe",
]

#: Secret de signature du bouchon quand ``STRIPE_WEBHOOK_SECRET`` est absent (local uniquement).
SECRET_WEBHOOK_BOUCHON = "whsec_bouchon_local_controldone"


class CleStripeRefusee(RuntimeError):
    """Clé Stripe refusée (clé de production hors autorisation explicite, ou format inconnu)."""


class SignatureInvalide(ValueError):
    """Webhook dont la signature est absente, fausse ou trop ancienne."""


@dataclass(frozen=True)
class SessionPaiement:
    id: str
    url: str
    mode: str  # payment | subscription


def centimes(montant: Decimal) -> int:
    c = Decimal(montant) * 100
    if c != c.to_integral_value():
        raise ValueError("montant au centime attendu")
    return int(c)


def verifier_cle_stripe(cle: str, env: dict[str, str] | None = None) -> str:
    """Renvoie la clé si elle est utilisable ; ``CleStripeRefusee`` sinon (jamais de clé dans le message)."""
    env = dict(os.environ) if env is None else env
    if cle.startswith(("sk_test_", "rk_test_")):
        return cle
    if cle.startswith(("sk_live_", "rk_live_")):
        if env.get("CONTROLDONE_ENV") == "prod" and env.get("STRIPE_LIVE_OK") == "1":
            return cle
        raise CleStripeRefusee("clé Stripe de production refusée : CONTROLDONE_ENV=prod et STRIPE_LIVE_OK=1 requis")
    raise CleStripeRefusee("clé Stripe refusée : sk_test_… attendu")


def signer_charge(charge: bytes, secret: str, horodatage: int | None = None) -> str:
    """En-tête ``Stripe-Signature`` (schéma v1 : HMAC-SHA256 de ``"<t>.<charge>"``)."""
    t = int(time.time()) if horodatage is None else horodatage
    sig = hmac.new(secret.encode(), f"{t}.".encode() + charge, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


def _verifier_signature(charge: bytes, signature: str | None, secret: str) -> dict[str, Any]:
    import stripe

    try:
        stripe.Webhook.construct_event(charge, signature, secret)
    except stripe.SignatureVerificationError as exc:
        raise SignatureInvalide("signature de webhook invalide") from exc
    except ValueError as exc:
        raise SignatureInvalide("charge de webhook illisible") from exc
    evt = json.loads(charge)
    if not isinstance(evt, dict) or not evt.get("id") or not evt.get("type"):
        raise SignatureInvalide("événement incomplet")
    return evt


@runtime_checkable
class FournisseurPaiement(Protocol):
    nom: str
    mode_test: bool

    def creer_client(self, *, client_id: str, raison_sociale: str, email: str | None) -> str: ...

    def session_paiement(self, *, client_id: str, customer_id: str | None, facture_id: str, numero: str,
                         montant_ttc: Decimal, libelle: str, url_succes: str, url_annulation: str) -> SessionPaiement: ...

    def session_abonnement(self, *, client_id: str, customer_id: str | None, palier: str, libelle: str,
                           montant_ttc_mensuel: Decimal, url_succes: str, url_annulation: str) -> SessionPaiement: ...

    def verifier_webhook(self, charge: bytes, signature: str | None) -> dict[str, Any]: ...


class PaiementStripe:
    """Stripe (Checkout Session, Billing) par ``stripe.StripeClient`` ; une clé par instance (pas d'état
    global). Idempotence des créations par clé d'idempotence Stripe."""

    nom = "stripe"

    def __init__(self, cle: str, secret_webhook: str | None, *, client: Any = None,
                 env: dict[str, str] | None = None) -> None:
        self.cle = verifier_cle_stripe(cle, env)
        self.mode_test = "_test_" in self.cle
        self.secret_webhook = secret_webhook
        if client is None:
            import stripe

            client = stripe.StripeClient(self.cle)
        self.client = client

    def creer_client(self, *, client_id: str, raison_sociale: str, email: str | None) -> str:
        params: dict[str, Any] = {"name": raison_sociale[:250], "metadata": {"client_id": client_id}}
        if email:
            params["email"] = email
        c = self.client.v1.customers.create(params=params, options={"idempotency_key": f"customer:{client_id}"})
        return str(c.id)

    def session_paiement(self, *, client_id: str, customer_id: str | None, facture_id: str, numero: str,
                         montant_ttc: Decimal, libelle: str, url_succes: str, url_annulation: str) -> SessionPaiement:
        meta = {"client_id": client_id, "facture_id": facture_id, "numero": numero}
        params: dict[str, Any] = {
            "mode": "payment", "success_url": url_succes, "cancel_url": url_annulation,
            "client_reference_id": client_id, "metadata": meta, "payment_intent_data": {"metadata": meta},
            "line_items": [{"quantity": 1, "price_data": {"currency": "eur", "unit_amount": centimes(montant_ttc),
                                                          "product_data": {"name": f"{libelle} — facture {numero}"[:250]}}}],
        }
        if customer_id:
            params["customer"] = customer_id
        s = self.client.v1.checkout.sessions.create(params=params, options={"idempotency_key": f"checkout:{facture_id}"})
        return SessionPaiement(str(s.id), str(s.url), "payment")

    def session_abonnement(self, *, client_id: str, customer_id: str | None, palier: str, libelle: str,
                           montant_ttc_mensuel: Decimal, url_succes: str, url_annulation: str) -> SessionPaiement:
        meta = {"client_id": client_id, "palier": palier}
        params: dict[str, Any] = {
            "mode": "subscription", "success_url": url_succes, "cancel_url": url_annulation,
            "client_reference_id": client_id, "metadata": meta, "subscription_data": {"metadata": meta},
            "line_items": [{"quantity": 1, "price_data": {
                "currency": "eur", "unit_amount": centimes(montant_ttc_mensuel), "recurring": {"interval": "month"},
                "product_data": {"name": libelle[:250]}}}],
        }
        if customer_id:
            params["customer"] = customer_id
        s = self.client.v1.checkout.sessions.create(
            params=params, options={"idempotency_key": f"abonnement:{client_id}:{palier}:{secrets.token_hex(4)}"})
        return SessionPaiement(str(s.id), str(s.url), "subscription")

    def verifier_webhook(self, charge: bytes, signature: str | None) -> dict[str, Any]:
        if not self.secret_webhook:
            raise SignatureInvalide("STRIPE_WEBHOOK_SECRET absent : webhook refusé")
        return _verifier_signature(charge, signature, self.secret_webhook)


class PaiementBouchon:
    """Bouchon local : sessions dans ``<racine>/sessions/``, événements au format Stripe, signés avec le
    secret de webhook (``STRIPE_WEBHOOK_SECRET`` s'il existe, sinon ``SECRET_WEBHOOK_BOUCHON``)."""

    nom = "bouchon"
    mode_test = True

    def __init__(self, racine: Path | str | None = None, secret_webhook: str | None = None) -> None:
        if racine is None:
            from controldone.config import get_settings

            racine = Path(get_settings().data_dir) / "paiement_bouchon"
        self.racine = Path(racine)
        self.secret_webhook = secret_webhook or SECRET_WEBHOOK_BOUCHON

    def _ecrire(self, nom: str, contenu: dict[str, Any]) -> None:
        d = self.racine / "sessions"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        (d / f"{nom}.json").write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")

    def _lire(self, nom: str) -> dict[str, Any]:
        p = self.racine / "sessions" / f"{nom}.json"
        if not p.exists() or not nom.replace("_", "").isalnum():
            raise KeyError("session inconnue")
        return json.loads(p.read_text(encoding="utf-8"))

    def creer_client(self, *, client_id: str, raison_sociale: str, email: str | None) -> str:
        return "cus_bouchon_" + hashlib.sha256(client_id.encode()).hexdigest()[:14]

    def session_paiement(self, *, client_id: str, customer_id: str | None, facture_id: str, numero: str,
                         montant_ttc: Decimal, libelle: str, url_succes: str, url_annulation: str) -> SessionPaiement:
        sid = "cs_bouchon_" + secrets.token_hex(8)
        self._ecrire(sid, {"id": sid, "mode": "payment", "amount_total": centimes(montant_ttc), "currency": "eur",
                           "customer": customer_id, "client_reference_id": client_id,
                           "metadata": {"client_id": client_id, "facture_id": facture_id, "numero": numero},
                           "url_succes": url_succes})
        return SessionPaiement(sid, f"/admin/finances/bouchon/{sid}", "payment")

    def session_abonnement(self, *, client_id: str, customer_id: str | None, palier: str, libelle: str,
                           montant_ttc_mensuel: Decimal, url_succes: str, url_annulation: str) -> SessionPaiement:
        sid = "cs_bouchon_" + secrets.token_hex(8)
        self._ecrire(sid, {"id": sid, "mode": "subscription", "amount_total": centimes(montant_ttc_mensuel),
                           "currency": "eur", "customer": customer_id, "client_reference_id": client_id,
                           "metadata": {"client_id": client_id, "palier": palier}, "url_succes": url_succes})
        return SessionPaiement(sid, f"/admin/finances/bouchon/{sid}", "subscription")

    def session(self, session_id: str) -> dict[str, Any]:
        return self._lire(session_id)

    def _evenement(self, type_: str, objet: dict[str, Any]) -> tuple[bytes, str]:
        evt = {"id": "evt_bouchon_" + secrets.token_hex(10), "object": "event", "type": type_,
               "created": int(time.time()), "livemode": False, "data": {"object": objet}}
        charge = json.dumps(evt, ensure_ascii=False).encode()
        return charge, signer_charge(charge, self.secret_webhook)

    def simuler_paiement(self, session_id: str, *, mois: str | None = None) -> list[tuple[bytes, str]]:
        """Événements signés que Stripe enverrait après un paiement réussi : ``checkout.session.completed``
        (et, pour un abonnement, ``invoice.paid`` du premier mois). À poster sur le webhook."""
        s = self._lire(session_id)
        objet = {"id": s["id"], "object": "checkout.session", "mode": s["mode"], "payment_status": "paid",
                 "status": "complete", "amount_total": s["amount_total"], "currency": s["currency"],
                 "customer": s["customer"], "client_reference_id": s["client_reference_id"],
                 "metadata": s["metadata"]}
        evts = []
        if s["mode"] == "subscription":
            sub = "sub_bouchon_" + hashlib.sha256(s["id"].encode()).hexdigest()[:14]
            objet["subscription"] = sub
            evts.append(self._evenement("checkout.session.completed", objet))
            evts.append(self.simuler_facture_abonnement(sub, s["customer"], s["amount_total"], s["metadata"], mois=mois))
        else:
            objet["payment_intent"] = "pi_bouchon_" + secrets.token_hex(8)
            evts.append(self._evenement("checkout.session.completed", objet))
        return evts

    def simuler_facture_abonnement(self, abonnement_id: str, customer_id: str | None, montant_centimes: int,
                                   metadata: dict[str, Any], *, mois: str | None = None,
                                   payee: bool = True) -> tuple[bytes, str]:
        """``invoice.paid`` (ou ``invoice.payment_failed``) d'une échéance mensuelle d'abonnement."""
        inv = {"id": "in_bouchon_" + secrets.token_hex(8), "object": "invoice", "subscription": abonnement_id,
               "customer": customer_id, "amount_paid": montant_centimes if payee else 0,
               "amount_due": montant_centimes, "currency": "eur", "status": "paid" if payee else "open",
               "billing_reason": "subscription_cycle",
               "subscription_details": {"metadata": metadata}, "metadata": {"mois": mois} if mois else {}}
        return self._evenement("invoice.paid" if payee else "invoice.payment_failed", inv)

    def verifier_webhook(self, charge: bytes, signature: str | None) -> dict[str, Any]:
        return _verifier_signature(charge, signature, self.secret_webhook)


def fournisseur_depuis_env(env: dict[str, str] | None = None, *, racine_bouchon: Path | None = None) -> FournisseurPaiement:
    """``PaiementStripe`` si ``STRIPE_SECRET_KEY`` est défini (clé de test, ou production autorisée),
    sinon ``PaiementBouchon``."""
    env = dict(os.environ) if env is None else env
    cle = (env.get("STRIPE_SECRET_KEY") or "").strip()
    secret = (env.get("STRIPE_WEBHOOK_SECRET") or "").strip() or None
    if cle:
        return PaiementStripe(cle, secret, env=env)
    return PaiementBouchon(racine_bouchon, secret)
