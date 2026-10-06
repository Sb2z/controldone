"""Petits graphiques des tableaux de bord (D-3403) : SVG produit par le serveur, sans bibliothèque ni script.

La géométrie est calculée ici ; le gabarit ``graphes.html.j2`` écrit le SVG (textes échappés par Jinja), avec
``<title>`` / ``<desc>`` et un tableau de données en repli. Couleurs : classes CSS liées aux variables du thème
(aucun attribut ``style``, compatible avec la CSP). Montants en ``Decimal`` ; seules les coordonnées sont des
nombres à virgule, arrondies au dixième de pixel.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from controldone.calendrier import mois_paris
from controldone.formatage import format_montant
from controldone.web.listes_vues import FAMILLES

__all__ = ["Graphe", "barres", "colonnes", "donnees_client", "donnees_fondateur"]

_MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


@dataclass
class Barre:
    libelle: str
    valeur: Decimal
    texte: str
    x: float = 0
    y: float = 0
    largeur: float = 0
    hauteur: float = 0
    tx: float = 0
    ty: float = 0
    vx: float = 0
    vy: float = 0
    court: str = ""


@dataclass
class Graphe:
    id: str
    titre: str
    description: str
    genre: str  # "colonnes" (verticales) ou "barres" (horizontales)
    largeur: int
    hauteur: int
    barres: list[Barre]
    colonne_libelle: str
    colonne_valeur: str
    graduations: list[tuple[float, str]] = field(default_factory=list)
    vide: bool = False
    note: str = ""


def _texte(v: Decimal, monnaie: bool) -> str:
    return format_montant(v, "EUR") if monnaie else str(int(v))


def _court(v: Decimal, monnaie: bool) -> str:
    """Valeur d'axe abrégée (« 12 k€ »)."""
    if not monnaie:
        return str(int(v))
    if abs(v) >= 1000:
        k = (v / 1000).quantize(Decimal("0.1")).normalize()
        return f"{k:f}".replace(".", ",") + " k€"
    return f"{int(v)} €"


def _pas(maxi: Decimal) -> Decimal:
    """Pas de graduation « rond » (1, 2, 5 × 10^n) pour environ 4 intervalles."""
    if maxi <= 0:
        return Decimal(1)
    brut = maxi / 4
    puissance = Decimal(1)
    while puissance * 10 <= brut:
        puissance *= 10
    while puissance > brut and puissance > Decimal("0.01"):
        puissance /= 10
    for m in (1, 2, 5, 10):
        if puissance * m >= brut:
            return puissance * m
    return puissance * 10


def colonnes(id_: str, titre: str, series: Sequence[tuple[str, Decimal]], *, monnaie: bool = True,
             colonne_libelle: str = "Mois", colonne_valeur: str = "Montant", note: str = "") -> Graphe:
    """Histogramme vertical (série temporelle)."""
    L, H, g, d, h, b = 640, 240, 56, 12, 16, 34
    vals = [v for _l, v in series]
    maxi = max(vals, default=Decimal(0))
    pas = _pas(maxi)
    plafond = pas * max(1, -(-maxi // pas)) if maxi > 0 else pas * 4
    zone_h, zone_l = H - h - b, L - g - d
    n = max(1, len(series))
    larg = zone_l / n
    out = []
    for i, (lib, v) in enumerate(series):
        hh = float(v / plafond) * zone_h if plafond else 0
        x = g + i * larg + larg * 0.18
        out.append(Barre(lib, v, _texte(v, monnaie), x=round(x, 1), y=round(h + zone_h - hh, 1),
                         largeur=round(larg * 0.64, 1), hauteur=round(max(hh, 0), 1),
                         tx=round(g + i * larg + larg / 2, 1), ty=H - b + 18))
    grad = []
    k = Decimal(0)
    while k <= plafond:
        grad.append((round(h + zone_h - float(k / plafond) * zone_h, 1), _court(k, monnaie)))
        k += pas
    total = sum(vals, Decimal(0))
    desc = (f"{len(series)} mois ; total {_texte(total, monnaie)} ; maximum {_texte(maxi, monnaie)}."
            if series else "Aucune donnée.")
    return Graphe(id_, titre, desc, "colonnes", L, H, out, colonne_libelle, colonne_valeur, grad,
                  vide=not any(vals), note=note)


def barres(id_: str, titre: str, series: Sequence[tuple[str, Decimal]], *, monnaie: bool = False,
           colonne_libelle: str = "Catégorie", colonne_valeur: str = "Nombre", note: str = "") -> Graphe:
    """Barres horizontales classées (catégories), valeur écrite au bout de chaque barre."""
    series = sorted(series, key=lambda s: -s[1])[:8]
    L, g, d, ligne = 640, 230, 110, 30
    H = max(60, 12 + ligne * len(series))
    maxi = max((v for _l, v in series), default=Decimal(0))
    zone_l = L - g - d
    out = []
    for i, (lib, v) in enumerate(series):
        w = float(v / maxi) * zone_l if maxi else 0
        y = 8 + i * ligne
        out.append(Barre(lib, v, _texte(v, monnaie), court=lib if len(lib) <= 34 else lib[:33] + "…", x=g, y=y + 5,
                         largeur=round(max(w, 2 if v else 0), 1), hauteur=ligne - 12, tx=g - 10, ty=y + ligne / 2 + 4,
                         vx=round(g + w + 8, 1), vy=y + ligne / 2 + 4))
    total = sum((v for _l, v in series), Decimal(0))
    desc = (f"{len(series)} catégorie(s) ; total {_texte(total, monnaie)} ; la plus élevée : {series[0][0]} "
            f"({_texte(series[0][1], monnaie)})." if series else "Aucune donnée.")
    return Graphe(id_, titre, desc, "barres", L, H, out, colonne_libelle, colonne_valeur, vide=not maxi, note=note)


def _mois_libelle(m: str) -> str:
    a, n = m.split("-")
    return f"{_MOIS[int(n) - 1]} {a[2:]}"


def _serie_mois(par_mois: dict[str, Decimal], *, nb: int = 12, aujourd_hui: date | None = None) -> list[tuple[str, Decimal]]:
    """Les ``nb`` derniers mois jusqu'au mois courant (Paris), mois sans montant compris."""
    courant = mois_paris(aujourd_hui) if aujourd_hui else mois_paris()
    a, m = int(courant[:4]), int(courant[5:7])
    mois = []
    for _ in range(nb):
        mois.append(f"{a:04d}-{m:02d}")
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    mois.reverse()
    # mois plus anciens que la fenêtre : ignorés (tableau de bord récent) ; plus récents : impossibles
    return [(_mois_libelle(x), par_mois.get(x, Decimal(0))) for x in mois]


def donnees_client(scope: Any) -> list[Graphe]:
    """Graphiques du tableau de bord client, à partir des constats **publiés** de la version courante."""
    from controldone.services.lecture import constats_courants, hors_totaux
    from controldone.storage.models import Dossier, Transitaire

    dossiers = {d.id: d for d in scope.lister(Dossier)}
    noms = {t.id: t.nom for t in scope.lister(Transitaire)}
    par_mois: dict[str, Decimal] = {}
    par_famille: dict[str, Decimal] = {}
    par_transitaire: dict[str, Decimal] = {}
    for c in constats_courants(scope):
        if c.statut_validation != "valide":
            continue
        fam = (c.controle_id or "?")[0]
        par_famille[fam] = par_famille.get(fam, Decimal(0)) + 1
        if hors_totaux(c) or c.niveau != "ecart_certain" or c.nature_montant != "recouvrable":
            continue
        if not c.montant_en_jeu or c.montant_en_jeu <= 0:
            continue
        d = dossiers.get(c.dossier_id)
        if d is None:
            continue
        m = mois_paris(d.cree_le)
        par_mois[m] = par_mois.get(m, Decimal(0)) + c.montant_en_jeu
        tid = (d.contenu or {}).get("transitaire_id")
        lib = noms.get(tid or "", "Transitaire non identifié")
        par_transitaire[lib] = par_transitaire.get(lib, Decimal(0)) + c.montant_en_jeu
    return [
        colonnes("g-mois", "Montant recouvrable certain par mois", _serie_mois(par_mois),
                 note="Écarts certains validés, par mois de traitement du dossier (12 derniers mois)."),
        barres("g-familles", "Constats publiés par famille de contrôles",
               [(f"{k} — {FAMILLES.get(k, k)}", v) for k, v in par_famille.items()], colonne_libelle="Famille"),
        barres("g-transitaires", "Montant recouvrable certain par transitaire", list(par_transitaire.items()),
               monnaie=True, colonne_libelle="Transitaire", colonne_valeur="Montant"),
    ]


def donnees_fondateur(stats: dict[str, dict[str, Any]]) -> list[Graphe]:
    """Graphiques du tableau de bord du fondateur, tous clients, à partir de ``OperatorScope.statistiques``."""
    par_mois: dict[str, Decimal] = {}
    proposes: dict[str, Decimal] = {}
    valides: dict[str, Decimal] = {}
    for b in stats.values():
        for m, v in (b.get("certain_par_mois") or {}).items():
            par_mois[m] = par_mois.get(m, Decimal(0)) + v
        for fam, n in (b.get("familles_proposes") or {}).items():
            proposes[fam] = proposes.get(fam, Decimal(0)) + n
        for fam, n in (b.get("familles_valides") or {}).items():
            valides[fam] = valides.get(fam, Decimal(0)) + n
    return [
        colonnes("g-mois", "Montant recouvrable certain validé par mois (tous clients)", _serie_mois(par_mois),
                 note="Par mois de traitement du dossier (12 derniers mois)."),
        barres("g-proposes", "Constats à valider par famille de contrôles",
               [(f"{k} — {FAMILLES.get(k, k)}", v) for k, v in proposes.items()], colonne_libelle="Famille"),
        barres("g-valides", "Constats validés par famille de contrôles",
               [(f"{k} — {FAMILLES.get(k, k)}", v) for k, v in valides.items()], colonne_libelle="Famille"),
    ]
