"""Suivi financier du fondateur : chiffre d'affaires (factures émises, nettes des avoirs), encaissements
(événements de paiement Stripe ou bouchon), coût IA par dossier et par client (registre ``ai_usage``),
marge brute par client et par mois ; export CSV.

Définitions (fonctions pures sur des lignes déjà lues) :

- **CA HT** du mois = Σ HT des factures émises dans le mois − Σ HT des avoirs émis dans le mois ;
- **Encaissé TTC** = Σ montants des événements de paiement réussis (``checkout.session.completed`` payé,
  ``invoice.paid``), au mois de l'événement ;
- **Coût IA** = Σ ``ai_usage.cout_eur`` (EUR, converti au taux ``CONTROLDONE_USD_EUR``) au mois du registre ;
- **Marge brute** = CA HT − coût IA (hypothèse : les autres coûts directs — hébergement, frais Stripe —
  ne sont pas ventilés par client ; ils sont à suivre en comptabilité).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

from controldone.storage import facturation as stock
from controldone.storage.db import Database
from controldone.storage.facturation import UsageIA

__all__ = ["LigneMarge", "SyntheseFinances", "calculer_marges", "export_csv", "synthese"]

_PARIS = ZoneInfo("Europe/Paris")
_ZERO = Decimal("0.00")


@dataclass
class LigneMarge:
    mois: str
    client_id: str
    raison_sociale: str = ""
    ca_ht: Decimal = _ZERO
    encaisse_ttc: Decimal = _ZERO
    cout_ia: Decimal = _ZERO
    nb_factures: int = 0
    nb_dossiers_ia: int = 0

    @property
    def marge_brute(self) -> Decimal:
        return self.ca_ht - self.cout_ia

    @property
    def taux_marge(self) -> Decimal | None:
        if self.ca_ht <= 0:
            return None
        return (self.marge_brute * 100 / self.ca_ht).quantize(Decimal("0.1"))


@dataclass(frozen=True)
class FactureLue:
    """Vue minimale d'une facture pour les calculs (testable sans base)."""

    mois: str
    client_id: str
    total_ht: Decimal  # négatif pour un avoir


@dataclass(frozen=True)
class EncaissementLu:
    mois: str
    client_id: str | None
    montant: Decimal


def calculer_marges(factures: Iterable[FactureLue], encaissements: Iterable[EncaissementLu],
                    usages: Iterable[UsageIA], noms: dict[str, str] | None = None) -> list[LigneMarge]:
    """Lignes (mois, client) triées par mois puis client. Fonction pure."""
    noms = noms or {}
    lignes: dict[tuple[str, str], LigneMarge] = {}
    dossiers: dict[tuple[str, str], set[str]] = {}

    def ligne(mois: str, client: str) -> LigneMarge:
        return lignes.setdefault((mois, client), LigneMarge(mois, client, noms.get(client, client)))

    for f in factures:
        x = ligne(f.mois, f.client_id)
        x.ca_ht += Decimal(f.total_ht)
        x.nb_factures += 1
    for e in encaissements:
        ligne(e.mois, e.client_id or "(non rattaché)").encaisse_ttc += Decimal(e.montant)
    for u in usages:
        x = ligne(u.mois, u.client_id)
        x.cout_ia += Decimal(u.cout_eur)
        if u.dossier_id:
            dossiers.setdefault((u.mois, u.client_id), set()).add(u.dossier_id)
    for k, ds in dossiers.items():
        lignes[k].nb_dossiers_ia = len(ds)
    return [lignes[k] for k in sorted(lignes)]


@dataclass
class SyntheseFinances:
    lignes: list[LigneMarge]
    par_mois: list[LigneMarge]
    par_client: list[LigneMarge]
    factures: list[dict[str, object]] = field(default_factory=list)
    encaissements: list[dict[str, object]] = field(default_factory=list)
    couts_dossiers: list[UsageIA] = field(default_factory=list)


def _cumul(lignes: list[LigneMarge], cle: str) -> list[LigneMarge]:
    out: dict[str, LigneMarge] = {}
    for x in lignes:
        k = x.mois if cle == "mois" else x.client_id
        t = out.setdefault(k, LigneMarge(x.mois if cle == "mois" else "tous", "tous" if cle == "mois" else x.client_id,
                                         "Tous clients" if cle == "mois" else x.raison_sociale))
        t.ca_ht += x.ca_ht
        t.encaisse_ttc += x.encaisse_ttc
        t.cout_ia += x.cout_ia
        t.nb_factures += x.nb_factures
        t.nb_dossiers_ia += x.nb_dossiers_ia
    return [out[k] for k in sorted(out)]


def _mois(d: object) -> str:
    from datetime import date, datetime

    if isinstance(d, datetime):
        return d.astimezone(_PARIS).strftime("%Y-%m")
    if isinstance(d, date):
        return d.strftime("%Y-%m")
    return str(d)[:7]


def synthese(db: Database, *, acteur_id: str, acteur_role: str) -> SyntheseFinances:
    """Lit factures, événements de paiement et coûts IA (lecture du registre journalisée) et calcule."""
    noms = stock.clients_facturation(db)
    fs = stock.factures(db)
    evts = stock.evenements_paiement(db)
    usages = stock.couts_ia(db, acteur_id=acteur_id, acteur_role=acteur_role)
    statuts: dict[str, str] = {}
    for st in stock.statuts_pa(db):
        if st.facture_id:
            statuts[st.facture_id] = f"{st.libelle} ({st.code})"
    payes: dict[str, Decimal] = {}
    for e in evts:
        if e.facture_id and e.montant:
            payes[e.facture_id] = payes.get(e.facture_id, _ZERO) + e.montant
    lignes = calculer_marges(
        [FactureLue(_mois(f.date_emission), f.client_id, f.total_ht) for f in fs],
        [EncaissementLu(_mois(e.le), e.client_id, e.montant) for e in evts if e.montant],
        usages, noms)
    vues = [{"id": f.id, "numero": f.numero, "type": "Avoir" if f.type_code == "381" else "Facture",
             "type_facture": f.type_facture, "client_id": f.client_id, "client": noms.get(f.client_id, f.client_id),
             "date": f.date_emission, "echeance": f.date_echeance, "total_ht": f.total_ht, "total_ttc": f.total_ttc,
             "net_a_payer": Decimal(str((f.contenu or {}).get("net_a_payer", f.total_ttc))),
             "encaisse": payes.get(f.id, _ZERO), "statut_pa": statuts.get(f.id, "non déposée"),
             "vendeur_complet": bool((f.contenu or {}).get("vendeur_complet"))} for f in reversed(fs)]
    enc = [{"id": e.id, "le": e.le, "type": e.type, "client": noms.get(e.client_id or "", e.client_id or "—"),
            "montant": e.montant, "fournisseur": e.fournisseur, "facture_id": e.facture_id} for e in reversed(evts)]
    couts = sorted([u for u in usages if u.dossier_id], key=lambda u: -u.cout_eur)
    return SyntheseFinances(lignes=lignes, par_mois=_cumul(lignes, "mois"), par_client=_cumul(lignes, "client"),
                            factures=vues, encaissements=enc, couts_dossiers=couts)


def _fr(x: Decimal | None) -> str:
    return "" if x is None else f"{Decimal(x).quantize(Decimal('0.01')):f}".replace(".", ",")


def export_csv(lignes: Iterable[LigneMarge]) -> bytes:
    """CSV (séparateur « ; », virgule décimale, UTF-8 avec BOM : ouverture directe dans un tableur)."""
    tampon = io.StringIO()
    w = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    w.writerow(["mois", "client_id", "client", "factures", "ca_ht_eur", "encaisse_ttc_eur", "cout_ia_eur",
                "dossiers_avec_cout_ia", "marge_brute_eur", "taux_marge_pct"])
    for x in lignes:
        nom = x.raison_sociale
        if nom[:1] in ("=", "+", "-", "@"):  # neutralise une formule de tableur (injection CSV)
            nom = "'" + nom
        w.writerow([x.mois, x.client_id, nom, x.nb_factures, _fr(x.ca_ht), _fr(x.encaisse_ttc), _fr(x.cout_ia),
                    x.nb_dossiers_ia, _fr(x.marge_brute), "" if x.taux_marge is None else str(x.taux_marge).replace(".", ",")])
    return ("﻿" + tampon.getvalue()).encode("utf-8")
