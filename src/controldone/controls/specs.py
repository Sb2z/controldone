"""Métadonnées des contrôles : Annexe A de la spécification, exportée comme donnée.

``CONTROL_SPECS`` est ordonné selon l'Annexe A (P, A, B, C, D, E, F, G) : c'est aussi l'ordre
d'exécution du moteur (un contrôle peut lire les résultats des contrôles qui le précèdent, ex. C5
lit C1–C4, C6 lit C1–C5, G5 lit G4).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from controldone.model.enums import NatureMontant

__all__ = ["CONTROL_SPECS", "ORDRE_CONTROLES", "ControlSpec", "get_spec", "specs_as_dicts", "specs_json"]


@dataclass(frozen=True, slots=True)
class ControlSpec:
    """Ligne de l'Annexe A.

    - ``eligible_certain`` : le contrôle peut-il produire ``ecart_certain`` (``None`` pour P3/P5, « — ») ;
    - ``nature_montant`` : ``None`` pour P3/P5 (pas de constat) ;
    - ``equivalents`` : ``accepted_control_ids`` du banc ;
    - ``note`` : précision de l'Annexe (ex. B4 « oui (a), non (b) », D8 « informatif »).
    """

    id: str
    libelle: str
    unite: str
    eligible_certain: bool | None
    nature_montant: NatureMontant | None
    equivalents: tuple[str, ...]
    note: str | None = None

    @property
    def famille(self) -> str:
        return self.id[0]

    @property
    def numero(self) -> int:
        return int(self.id[1:])

    @property
    def produit_constat(self) -> bool:
        """P3 et P5 ne produisent jamais de constat (statut / non vérifiable)."""
        return self.nature_montant is not None

    @property
    def montant_autorise(self) -> bool:
        return self.nature_montant not in (None, NatureMontant.aucun, NatureMontant.renvoi)

    @property
    def est_renvoi(self) -> bool:
        return self.nature_montant is NatureMontant.renvoi


_R = NatureMontant.recouvrable
_E = NatureMontant.ecart_documentaire
_A = NatureMontant.arithmetique_declaration
_V = NatureMontant.renvoi
_0 = NatureMontant.aucun


def _s(id_, libelle, unite, certain, nature, equiv, note=None) -> ControlSpec:
    return ControlSpec(id_, libelle, unite, certain, nature, tuple(equiv.split(", ")) if equiv else (), note)


_LISTE: tuple[ControlSpec, ...] = (
    _s("P1", "Complétude du dossier", "dossier", False, _0, "P1"),
    _s("P2", "Document non exploitable", "document", False, _0, "P2, P1"),
    _s("P3", "Champ clé illisible (pas de constat)", "champ", None, None, ""),
    _s("P4", "Rattachement faible", "lien", False, _0, "P4"),
    _s("P5", "Dossier non concerné (statut)", "dossier", None, None, ""),
    _s("A1", "Entité importatrice", "couple", True, _0, "A1"),
    _s("A2", "Référence de facture citée", "couple", False, _0, "A2"),
    _s("A3", "Devise de facturation", "couple", True, _0, "A3, A6"),
    _s("A4", "Valeur facturée (même devise)", "couple", True, _E, "A4, A5"),
    _s("A5", "Montant converti au taux imprimé", "couple", True, _E, "A5, A4"),
    _s("A6", "Montant repris sans conversion", "couple", True, _E, "A6, A3, A5"),
    _s("A7", "Ordre de grandeur au taux indicatif", "couple", False, _0, "A7, A6"),
    _s("A8", "Incoterm", "couple", False, _0, "A8"),
    _s("A9", "Quantités", "ligne/article", False, _0, "A9"),
    _s("A10", "Masses facture/déclaration", "couple", False, _0, "A10"),
    _s("A11", "Nombre de colis", "couple", False, _0, "A11, B5"),
    _s("A12", "Pays d'origine imprimés (renvoi)", "ligne/article", False, _V, "A12"),
    _s("A13", "Codes marchandise imprimés (renvoi)", "couple", False, _V, "A13"),
    _s("A14", "Chronologie des dates", "couple", False, _0, "A14"),
    _s("A15", "Références produit (signal)", "couple", False, _0, "A15"),
    _s("B1", "Base × taux = montant", "ligne de taxation", True, _A, "B1, B2"),
    _s("B2", "Sommes des taxes", "déclaration", True, _A, "B2, B1"),
    _s("B3", "Somme des montants facturés des articles", "déclaration", True, _A, "B3"),
    _s("B4", "Masses nette/brute", "déclaration", True, _0, "B4, A10", "oui (a), non (b)"),
    _s("B5", "Colis", "déclaration", False, _0, "B5, A11"),
    _s("C1", "Droits refacturés", "facture transitaire × déclaration(s)", True, _R, "C1, C5"),
    _s("C2", "Autres taxes refacturées", "facture transitaire × déclaration(s)", True, _R, "C2, C5"),
    _s(
        "C3",
        "TVA refacturée malgré autoliquidation",
        "facture transitaire × déclaration(s)",
        True,
        _R,
        "C3, C5",
    ),
    _s("C4", "TVA refacturée (payée)", "facture transitaire × déclaration(s)", True, _R, "C4, C5"),
    _s("C5", "Total des débours", "facture transitaire × déclaration(s)", True, _R, "C5, C1, C2, C3, C4"),
    _s("C6", "FAF sur débours en écart", "ligne FAF", True, _R, "C6, D4"),
    _s("C7", "Références de la facture transitaire", "facture transitaire", False, _0, "C7"),
    _s("C8", "Client facturé", "facture transitaire", True, _0, "C8"),
    _s("D1", "Arithmétique interne", "facture transitaire", True, _R, "D1", "recouvrable (totaux)"),
    _s("D2", "Ligne hors grille", "ligne", True, _R, "D2, D7"),
    _s("D3", "Prix supérieur à la grille", "ligne", True, _R, "D3"),
    _s("D4", "FAF contre grille", "ligne FAF", True, _R, "D4, C6"),
    _s("D5", "Ligne en double", "facture", True, _R, "D5"),
    _s("D6", "Magasinage", "ligne", True, _R, "D6, D3"),
    _s("D7", "Surcharges", "ligne", True, _R, "D7, D2, D3"),
    _s("D8", "TVA sur débours", "ligne", False, _R, "D8", "recouvrable (informatif)"),
    _s("D9", "Lignes supplémentaires", "ligne", True, _R, "D9, D3"),
    _s("E1", "Rattachement de l'avoir", "avoir", False, _0, "E1"),
    _s("E2", "Avoir supérieur à l'origine", "avoir", False, _0, "E2"),
    _s("E3", "Avoir reçu deux fois", "avoir", False, _0, "E3, F1"),
    _s("E4", "Arithmétique de l'avoir", "avoir", False, _0, "E4"),
    _s("E5", "Avoir sans écart ouvert", "avoir", False, _0, "E5"),
    _s("E6", "Avoir partiel", "écart", False, _R, "E6", "recouvrable (reste)"),
    _s("F1", "Document en double", "document", False, _0, "F1, E3"),
    _s("F2", "Numéro de facture transitaire réutilisé", "facture", False, _0, "F2"),
    _s("F3", "Même déclaration refacturée deux fois", "MRN", True, _R, "F3, C5"),
    _s("F4", "Même prestation facturée deux fois", "ligne", False, _R, "F4, D5"),
    _s("F5", "Facture commerciale sur plusieurs déclarations", "facture", False, _E, "F5, A4"),
    _s("G1", "Nombre d'articles × montant unitaire", "ligne forfait", True, _A, "G1, B1"),
    _s("G2", "Base du forfait contre nombre d'articles", "déclaration", True, _A, "G2"),
    _s("G3", "Base contre codes distincts (renvoi)", "déclaration", False, _V, "G3, G2"),
    _s(
        "G4",
        "Forfait refacturé contre liquidé",
        "facture transitaire × déclaration",
        True,
        _R,
        "G4, G5, C1, C5",
    ),
    _s("G5", "Base de refacturation du transitaire", "ligne", True, _R, "G5, G4"),
    _s("G6", "Applicabilité du forfait (renvoi)", "déclaration", False, _V, "G6"),
)

#: Identifiant -> spécification, dans l'ordre de l'Annexe A.
CONTROL_SPECS: dict[str, ControlSpec] = {s.id: s for s in _LISTE}
#: Ordre d'exécution déterministe.
ORDRE_CONTROLES: tuple[str, ...] = tuple(CONTROL_SPECS)


def get_spec(controle_id: str) -> ControlSpec:
    try:
        return CONTROL_SPECS[controle_id]
    except KeyError as e:
        raise KeyError(f"contrôle inconnu (absent de l'Annexe A) : {controle_id!r}") from e


def specs_as_dicts() -> list[dict]:
    """Annexe A en liste de dictionnaires JSON-compatibles (pour le banc, le rapport, la doc)."""
    out = []
    for s in _LISTE:
        d = asdict(s)
        d["nature_montant"] = s.nature_montant.value if s.nature_montant else None
        d["equivalents"] = list(s.equivalents)
        out.append(d)
    return out


def specs_json() -> str:
    return json.dumps(specs_as_dicts(), ensure_ascii=False, indent=2)
