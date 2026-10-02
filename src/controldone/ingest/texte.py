"""Structure ``PageText`` (texte, lignes, mots positionnés) et mesure de la qualité d'un texte (§7.3).

``PageText`` est ce que les extracteurs consomment : texte de la page, lignes, mots avec boîtes
**normalisées 0–1** (origine en haut à gauche) et, pour l'OCR, la confiance de chaque mot. Les fonctions
``zone_de`` / ``mots_dans`` servent à l'ancrage et aux zones (§6.3).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field

from controldone.model.enums import QualiteTexte
from controldone.model.valeur import Zone
from controldone.normalize.text import normaliser_espaces

__all__ = ["Ligne", "Mot", "PageText", "construire_lignes", "score_texte"]


@dataclass(frozen=True, slots=True)
class Mot:
    texte: str
    x0: float
    y0: float
    x1: float
    y1: float
    #: Confiance OCR (0–1) ; ``None`` pour un texte natif.
    confiance: float | None = None
    #: Taille de police (points) pour un texte natif, hauteur relative sinon.
    taille: float | None = None

    @property
    def zone(self) -> Zone:
        return Zone(x0=_b(self.x0), y0=_b(self.y0), x1=_b(self.x1), y1=_b(self.y1))


@dataclass(frozen=True, slots=True)
class Ligne:
    texte: str
    mots: tuple[Mot, ...]

    @property
    def x0(self) -> float:
        return min((m.x0 for m in self.mots), default=0.0)

    @property
    def y0(self) -> float:
        return min((m.y0 for m in self.mots), default=0.0)

    @property
    def x1(self) -> float:
        return max((m.x1 for m in self.mots), default=0.0)

    @property
    def y1(self) -> float:
        return max((m.y1 for m in self.mots), default=0.0)

    @property
    def taille(self) -> float | None:
        tailles = [m.taille for m in self.mots if m.taille]
        return max(tailles) if tailles else None


def _b(v: float) -> float:
    return min(1.0, max(0.0, round(float(v), 5)))


@dataclass
class PageText:
    """Texte d'une page (ou d'une feuille de tableur) avec sa géométrie."""

    numero: int
    texte: str
    lignes: list[Ligne] = field(default_factory=list)
    qualite: QualiteTexte = QualiteTexte.natif
    #: ``natif``, ``ocr``, ``tableur``, ``csv``, ``xml``, ``texte``.
    source: str = "natif"
    score_natif: float | None = None
    score_ocr: float | None = None
    rotation: int = 0
    #: Angle de désinclinaison appliqué (degrés).
    desinclinaison: float = 0.0
    largeur: float | None = None
    hauteur: float | None = None
    feuille: str | None = None
    #: Texte retiré car invisible (blanc sur blanc, mode invisible, micro-police) : audit seulement,
    #: jamais utilisé pour classer ni extraire (§20.2).
    texte_masque: str = ""
    avertissements: list[str] = field(default_factory=list)

    @property
    def mots(self) -> list[Mot]:
        return [m for ligne in self.lignes for m in ligne.mots]

    # --- géométrie ---

    def mots_dans(self, zone: Zone, *, recouvrement: float = 0.5) -> list[Mot]:
        """Mots dont au moins ``recouvrement`` de la surface est dans ``zone``."""
        out = []
        for m in self.mots:
            ix = max(0.0, min(m.x1, zone.x1) - max(m.x0, zone.x0))
            iy = max(0.0, min(m.y1, zone.y1) - max(m.y0, zone.y0))
            aire = max(1e-9, (m.x1 - m.x0) * (m.y1 - m.y0))
            if ix * iy / aire >= recouvrement:
                out.append(m)
        return out

    def zone_de(self, valeur_brute: str, *, apres: Zone | None = None) -> Zone | None:
        """Zone (union des boîtes) de la première occurrence de ``valeur_brute`` (suite de mots
        consécutifs d'une ligne, espaces normalisés). ``apres`` : ne chercher qu'en dessous / à droite."""
        cible = normaliser_espaces(valeur_brute)
        if not cible:
            return None
        for ligne in self.lignes:
            mots = list(ligne.mots)
            if apres is not None and ligne.y1 < apres.y0:
                continue
            for i in range(len(mots)):
                acc = ""
                for j in range(i, len(mots)):
                    acc = f"{acc} {mots[j].texte}" if acc else mots[j].texte
                    if cible in acc:
                        reste = " ".join(m.texte for m in mots[i + 1 : j + 1])
                        if i < j and cible in reste:
                            break  # l'occurrence commence plus loin : essayer le mot suivant
                        sel = mots[i : j + 1]
                        return Zone(
                            x0=_b(min(m.x0 for m in sel)), y0=_b(min(m.y0 for m in sel)),
                            x1=_b(max(m.x1 for m in sel)), y1=_b(max(m.y1 for m in sel)),
                        )
                    if len(acc) > len(cible) + 60:
                        break
        return None

    def lignes_haut(self, fraction: float = 0.3) -> list[Ligne]:
        return [ligne for ligne in self.lignes if ligne.y0 <= fraction]

    # --- sérialisation (cache) ---

    def to_dict(self) -> dict:
        d = asdict(self)
        d["qualite"] = self.qualite.value
        d["lignes"] = [{"texte": li.texte, "mots": [list(_mot_tuple(m)) for m in li.mots]} for li in self.lignes]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PageText:
        d = dict(d)
        d["qualite"] = QualiteTexte(d["qualite"])
        d["lignes"] = [
            Ligne(texte=li["texte"], mots=tuple(Mot(*m) for m in li["mots"])) for li in d.get("lignes", [])
        ]
        champs = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in champs})


def _mot_tuple(m: Mot) -> tuple:
    return (m.texte, m.x0, m.y0, m.x1, m.y1, m.confiance, m.taille)


def construire_lignes(mots: Sequence[Mot], *, ecart_colonne: float = 0.02) -> list[Ligne]:
    """Regroupe des mots en lignes (même bande verticale), triées haut -> bas, gauche -> droite.

    Deux mots séparés de plus de ``ecart_colonne`` (fraction de largeur) sont joints par trois espaces
    (indice de colonne pour les extracteurs ; l'ancrage normalise les espaces).
    """
    restants = sorted(mots, key=lambda m: ((m.y0 + m.y1) / 2, m.x0))
    lignes: list[list[Mot]] = []
    for m in restants:
        cy = (m.y0 + m.y1) / 2
        h = max(m.y1 - m.y0, 1e-4)
        if lignes:
            der = lignes[-1]
            dy0 = sum(x.y0 for x in der) / len(der)
            dy1 = sum(x.y1 for x in der) / len(der)
            dh = max(dy1 - dy0, 1e-4)
            if abs(cy - (dy0 + dy1) / 2) <= 0.5 * min(h, dh) + 1e-4:
                der.append(m)
                continue
        lignes.append([m])
    sortie = []
    for groupe in lignes:
        groupe.sort(key=lambda m: m.x0)
        parties: list[str] = []
        prec: Mot | None = None
        for m in groupe:
            if prec is not None:
                parties.append("   " if m.x0 - prec.x1 > ecart_colonne else " ")
            parties.append(m.texte)
            prec = m
        sortie.append(Ligne(texte="".join(parties), mots=tuple(groupe)))
    return sortie


# --- qualité du texte (§7.3) -------------------------------------------------------------------------

_LEXIQUE = frozenset(
    """
    a à au aux avec ce ces cet cette dans de des du en et il la le les leur lui ma mais me mes mon ne ni
    nous on ou où par pas pour qu que qui sa se ses son sur ta te tes ton tu un une vos votre vous y n° no
    nr nº
    the of and to in for on at by from with as is are be this that an or it its not no all any per our
    your we you via vat tax total date page
    el la los las de del y en por para con un una sin al es
    facture invoice factura avoir credit crédito note nota client cliente customer montant amount importe
    prix price precio quantité quantity cantidad qty unité unit pays country país origine origin origen
    poids weight peso brut gross bruto net neto colis packages bultos tva iva douane customs aduana
    droits duty duties taxes déclaration declaration declaración transport frais fees gastos description
    désignation descripción article item artículo code código référence reference referencia commande
    order pedido livraison delivery entrega adresse address dirección vendeur seller vendedor acheteur buyer
    comprador destinataire consignee expéditeur shipper exportateur exporter importateur importer conditions
    terms paiement payment pago banque bank banco devise currency moneda taux rate tasa échéance due
    sous subtotal valeur value valor marchandises goods mercancías fret freight flete assurance insurance
    seguro emballage packing embalaje remise discount descuento numéro number número tél tel phone fax
    email mail www siret siren eori rcs capital société company sociedad sarl sas sa ltd inc gmbh srl
    mrn lrn régime procédure liquidation base montants payer paid payé mode signature cachet
    """.split()
)

_VOYELLES = set("aeiouyàâäéèêëîïôöùûüœæ")
_NUMERIQUE = re.compile(r"^[\(\-+]?[\d][\d.,:/'’%\-   ]*[\)%]?$|^[€$£¥]?\d")
_CODE = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9./\-_:#]*$")
_MOT_SEUL = re.compile(r"[^\W\d_]+", re.UNICODE)


def _token_valide(tok: str) -> bool:
    t = tok.strip(".,;:!?()[]{}\"'«»“”‘’*|")
    if not t:
        return True  # ponctuation isolée : neutre
    if _NUMERIQUE.match(t) or _CODE.match(t):
        return True
    if t in {"€", "$", "£", "%", "&", "-", "/", "#", "+", "=", "@"}:
        return True
    base = t.lower()
    if base in _LEXIQUE:
        return True
    lettres = "".join(_MOT_SEUL.findall(base))
    if not lettres or len(lettres) < len(base) * 0.7:
        # mélange de lettres et de symboles (ex. « Ã©Ã », « ¤¤a ») : douteux
        return bool(re.fullmatch(r"[\w'’\-./&]+", base)) and len(lettres) >= len(base) * 0.5
    if any(unicodedata.category(c) not in ("Ll", "Lu", "Lo", "Lt") for c in lettres):
        return False
    if len(lettres) <= 2:
        return t.isupper() or base in _LEXIQUE or len(lettres) == 1
    if t.isupper() and len(lettres) <= 6:
        return True  # sigles
    if not t.isupper() and not t.islower() and not t[0].isupper():
        return False  # « aBcDe »
    voy = sum(1 for c in lettres if c in _VOYELLES)
    ratio = voy / len(lettres)
    if ratio < 0.15 or ratio > 0.8:
        return False
    if re.search(r"[^aeiouyàâäéèêëîïôöùûüœæ]{5,}", lettres):
        return False
    return not re.search(r"(.)\1\1", lettres)


def score_texte(texte: str | Iterable[str]) -> float:
    """Part (0–1) des caractères non blancs appartenant à des mots plausibles FR/EN/ES ou à des nombres
    et références, parmi des caractères imprimables (§7.3)."""
    if not isinstance(texte, str):
        texte = " ".join(texte)
    if "(cid:" in texte:
        texte = re.sub(r"\(cid:\d+\)", "\x00", texte)
    total = 0
    bons = 0
    for tok in texte.split():
        n = len(tok)
        total += n
        if any((not c.isprintable()) or c in "\x00�" for c in tok):
            continue
        if _token_valide(tok):
            bons += n
    return 1.0 if total == 0 else bons / total
