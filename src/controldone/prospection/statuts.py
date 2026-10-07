"""Statuts du pipeline de prospection et tranches d'effectif INSEE.

Libellés en français (texte source du catalogue de traduction ``web/i18n_prospection_en.py`` ; un test vérifie
que chacun y figure)."""

from __future__ import annotations

__all__ = [
    "ETAPES_PIPELINE",
    "LIBELLES_ARRET",
    "LIBELLES_EVENEMENT",
    "LIBELLES_MOTIF_SUPPRESSION",
    "LIBELLES_SOURCE",
    "LIBELLES_STATUT",
    "LIBELLES_TRANCHE",
    "STATUTS",
    "STATUTS_ACTIFS_SEQUENCE",
    "STATUTS_FERMES",
    "rang_statut",
    "tranche_depuis_libelle",
]

#: Ordre du pipeline : à qualifier -> qualifié -> contacté -> a répondu -> rendez-vous -> essai -> client ; sorties.
STATUTS: tuple[str, ...] = (
    "a_qualifier",
    "qualifie",
    "contacte",
    "a_repondu",
    "rendez_vous",
    "essai",
    "client",
    "perdu",
    "ne_plus_contacter",
)
ETAPES_PIPELINE: tuple[str, ...] = STATUTS[:7]
#: Statuts où une séquence peut continuer ; tout autre statut l'arrête.
STATUTS_ACTIFS_SEQUENCE = frozenset({"qualifie", "contacte"})
STATUTS_FERMES = frozenset({"client", "perdu", "ne_plus_contacter"})

LIBELLES_STATUT = {
    "a_qualifier": "À qualifier",
    "qualifie": "Qualifié",
    "contacte": "Contacté",
    "a_repondu": "A répondu",
    "rendez_vous": "Rendez-vous",
    "essai": "Essai / diagnostic",
    "client": "Client",
    "perdu": "Perdu",
    "ne_plus_contacter": "Ne plus contacter",
}

LIBELLES_SOURCE = {
    "import_csv": "Import CSV",
    "recherche": "Recherche d'entreprises",
    "saisie": "Saisie du fondateur",
    "demo": "Démonstration (fictif)",
}

LIBELLES_EVENEMENT = {
    "creation": "Prospect ajouté",
    "statut": "Changement de statut",
    "note": "Note",
    "contact": "Contact ajouté",
    "modification": "Fiche modifiée",
    "reponse": "Réponse reçue",
    "rendez_vous": "Rendez-vous",
    "preparation": "Courriel préparé",
    "envoi": "Courriel envoyé",
    "declaration_envoi": "Envoi déclaré par le fondateur",
    "desinscription": "Désinscription",
    "rebond": "Adresse en échec (rebond)",
    "sequence_arret": "Séquence arrêtée",
    "sequence_fin": "Séquence terminée",
}

LIBELLES_ARRET = {
    "reponse": "réponse reçue",
    "desinscription": "désinscription",
    "rebond": "adresse en échec",
    "statut": "changement de statut",
    "exclusion": "liste d'exclusion",
    "refus": "brouillon refusé",
    "fondateur": "arrêt par le fondateur",
    "opposition": "adresse dans la liste d'opposition",
}

LIBELLES_MOTIF_SUPPRESSION = {
    "desinscription": "Désinscription",
    "rebond": "Rebond",
    "ne_plus_contacter": "Ne plus contacter",
    "plainte": "Plainte",
}

#: Tranches d'effectif salarié (codes INSEE).
LIBELLES_TRANCHE = {
    "00": "0",
    "01": "1-2",
    "02": "3-5",
    "03": "6-9",
    "11": "10-19",
    "12": "20-49",
    "21": "50-99",
    "22": "100-199",
    "31": "200-249",
    "32": "250-499",
    "41": "500-999",
    "42": "1000-1999",
    "51": "2000-4999",
    "52": "5000-9999",
    "53": "10000+",
}


def rang_statut(statut: str) -> int:
    return STATUTS.index(statut) if statut in STATUTS else -1


def tranche_depuis_libelle(texte: str | None) -> str | None:
    """Code INSEE d'un libellé « 10-19 (2023) », « 50-99 », « 11 » ; ``None`` si rien n'est reconnu."""
    import re

    t = (texte or "").strip()
    if t[:2] in LIBELLES_TRANCHE and (len(t) == 2 or not t[2].isdigit()):
        return t[:2]
    m = re.search(r"(\d+)\s*-\s*(\d+)", t)
    if m:
        cle = f"{int(m.group(1))}-{int(m.group(2))}"
        for code, lib in LIBELLES_TRANCHE.items():
            if lib == cle:
                return code
    return None
