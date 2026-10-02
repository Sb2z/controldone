"""Table de l'Annexe A utile au correcteur : équivalences banc et éligibilité au niveau certain."""

from __future__ import annotations

# ID -> (éligible ecart_certain, équivalents banc)
ANNEXE_A: dict[str, tuple[bool, tuple[str, ...]]] = {
    "P1": (False, ("P1",)),
    "P2": (False, ("P2", "P1")),
    "P4": (False, ("P4",)),
    "A1": (True, ("A1",)),
    "A2": (False, ("A2",)),
    "A3": (True, ("A3", "A6")),
    "A4": (True, ("A4", "A5")),
    "A5": (True, ("A5", "A4")),
    "A6": (True, ("A6", "A3", "A5")),
    "A7": (False, ("A7", "A6")),
    "A8": (False, ("A8",)),
    "A9": (False, ("A9",)),
    "A10": (False, ("A10",)),
    "A11": (False, ("A11", "B5")),
    "A12": (False, ("A12",)),
    "A13": (False, ("A13",)),
    "A14": (False, ("A14",)),
    "A15": (False, ("A15",)),
    "B1": (True, ("B1", "B2")),
    "B2": (True, ("B2", "B1")),
    "B3": (True, ("B3",)),
    "B4": (True, ("B4", "A10")),
    "B5": (False, ("B5", "A11")),
    "C1": (True, ("C1", "C5")),
    "C2": (True, ("C2", "C5")),
    "C3": (True, ("C3", "C5")),
    "C4": (True, ("C4", "C5")),
    "C5": (True, ("C5", "C1", "C2", "C3", "C4")),
    "C6": (True, ("C6", "D4")),
    "C7": (False, ("C7",)),
    "C8": (True, ("C8",)),
    "D1": (True, ("D1",)),
    "D2": (True, ("D2", "D7")),
    "D3": (True, ("D3",)),
    "D4": (True, ("D4", "C6")),
    "D5": (True, ("D5",)),
    "D6": (True, ("D6", "D3")),
    "D7": (True, ("D7", "D2", "D3")),
    "D8": (False, ("D8",)),
    "D9": (True, ("D9", "D3")),
    "E1": (False, ("E1",)),
    "E2": (False, ("E2",)),
    "E3": (False, ("E3", "F1")),
    "E4": (False, ("E4",)),
    "E5": (False, ("E5",)),
    "E6": (False, ("E6",)),
    "F1": (False, ("F1", "E3")),
    "F2": (False, ("F2",)),
    "F3": (True, ("F3", "C5")),
    "F4": (False, ("F4", "D5")),
    "F5": (False, ("F5", "A4")),
    "G1": (True, ("G1", "B1")),
    "G2": (True, ("G2",)),
    "G3": (False, ("G3", "G2")),
    "G4": (True, ("G4", "G5", "C1", "C5")),
    "G5": (True, ("G5", "G4")),
    "G6": (False, ("G6",)),
}

# Contrôles pour lesquels un constat peut être apparié depuis un autre dossier (§19.4, point 2).
CONTROLES_INTER_DOSSIERS = frozenset({"F3", "F4", "F5"})


def equivalents(control_id: str) -> tuple[str, ...]:
    """Équivalents banc d'un contrôle (lui-même inclus) ; inconnu -> lui seul."""
    entry = ANNEXE_A.get(control_id)
    return entry[1] if entry else (control_id,)


def ordre_cle(control_id: str) -> tuple[int, int, str]:
    """Clé de tri lisible : P, A..G puis numéro."""
    familles = "PABCDEFG"
    if control_id and control_id[0] in familles and control_id[1:].isdigit():
        return (familles.index(control_id[0]), int(control_id[1:]), "")
    return (99, 0, control_id)
