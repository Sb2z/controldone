"""Modèles de courriels de prospection : variables tirées de faits vérifiés, pied obligatoire (D-5005).

- Variables admises : ``{raison_sociale}``, ``{accroche}``, ``{ville}``, ``{expediteur}``. Chacune vient d'un fait
  enregistré ; un fait absent n'est **jamais** inventé : le texte porte « [à compléter : …] » et la préparation est
  refusée tant qu'il manque (``Rendu.manquants``).
- ``{accroche}`` : citation **textuelle** (entre « ») de la preuve d'import, seulement si la page source est
  enregistrée. Une paraphrase sans guillemets ne suffit pas.
- Texte brut d'abord ; un lien au plus dans l'objet et le corps (le lien de désinscription du pied est à part).
- Pied ajouté par le code, non modifiable : identité de l'expéditeur (nom, SIREN, adresse), origine de l'adresse,
  opposition « répondez STOP » et lien de désinscription quand l'URL publique est configurée.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from controldone.guardrails import check_text

__all__ = [
    "MARQUE_MANQUANT",
    "SEQUENCE_DEFAUT",
    "VARIABLES",
    "IdentiteExpediteur",
    "Rendu",
    "accroche_depuis_preuve",
    "compter_liens",
    "pied",
    "rendre",
    "valider_etapes",
]

MARQUE_MANQUANT = "[à compléter"
VARIABLES = {
    "raison_sociale": "Raison sociale (source publique)",
    "accroche": "Citation du site de l'entreprise (preuve d'import, page source enregistrée)",
    "ville": "Ville",
    "expediteur": "Nom de l'expéditeur (configuration)",
}
_VARIABLE = re.compile(r"\{([A-Za-z_]+)\}")
_LIEN = re.compile(r"https?://|\bwww\.", re.I)
_CITATION = re.compile(r"«\s*(.+?)\s*»", re.S)
CITATION_MAX = 300


@dataclass(frozen=True)
class IdentiteExpediteur:
    nom: str | None
    fonction: str
    entreprise: str | None
    siren: str | None
    adresse: str | None

    def manquants(self) -> list[str]:
        return [k for k in ("nom", "siren", "adresse") if not getattr(self, k)]


@dataclass
class Rendu:
    objet: str
    corps: str
    manquants: list[str] = field(default_factory=list)

    @property
    def complet(self) -> bool:
        return not self.manquants


def accroche_depuis_preuve(preuve: str | None, preuve_url: str | None) -> str | None:
    """Phrase d'accroche tirée d'une citation textuelle de la preuve d'import (la plus longue), seulement si sa
    page source est enregistrée ; ``None`` sinon."""
    from controldone.prospection.contacts import url_valide

    if not preuve or not url_valide(preuve_url):
        return None
    citations = [c.strip() for c in _CITATION.findall(preuve) if len(c.strip()) >= 3]
    if not citations:
        return None
    c = max(citations, key=len)
    c = " ".join(c.split())
    if len(c) > CITATION_MAX:
        c = c[:CITATION_MAX].rsplit(" ", 1)[0] + " […]"
    return f"Sur votre site, j'ai lu : « {c} »."


def compter_liens(texte: str) -> int:
    return len(_LIEN.findall(texte or ""))


def _remplacer(texte: str, faits: Mapping[str, str | None], manquants: list[str]) -> str:
    def rep(m: re.Match[str]) -> str:
        nom = m.group(1)
        v = faits.get(nom)
        if v is None or not str(v).strip():
            if nom not in manquants:
                manquants.append(nom)
            return f"{MARQUE_MANQUANT} : {nom}]"
        return str(v).strip()

    return _VARIABLE.sub(rep, texte)


def pied(identite: IdentiteExpediteur, source: str | None, lien: str | None, manquants: list[str]) -> str:
    """Pied obligatoire (LCEN, art. 14 RGPD, opposition)."""
    for k in identite.manquants():
        if f"expediteur_{k}" not in manquants:
            manquants.append(f"expediteur_{k}")
    if not source:
        manquants.append("source_adresse")

    def v(x: str | None, nom: str) -> str:
        return x if x else f"{MARQUE_MANQUANT} : {nom}]"

    lignes = [
        "--",
        f"{v(identite.nom, 'expediteur_nom')}, {identite.fonction}",
        ", ".join(
            x
            for x in (
                identite.entreprise,
                f"SIREN {v(identite.siren, 'expediteur_siren')}",
            )
            if x
        ),
        v(identite.adresse, "expediteur_adresse"),
        f"Vous recevez ce message parce que votre adresse professionnelle figure sur {v(source, 'source_adresse')}.",
        "Si vous ne souhaitez plus recevoir de message de ma part, répondez simplement STOP"
        + (f" ou ouvrez ce lien : {lien}" if lien else "")
        + ". Je retirerai votre adresse de mon fichier.",
    ]
    return "\n".join(lignes)


def rendre(
    etape: Mapping[str, Any],
    faits: Mapping[str, str | None],
    identite: IdentiteExpediteur,
    *,
    source_adresse: str | None,
    lien_desinscription: str | None,
) -> Rendu:
    """Objet et corps (pied compris) d'une étape ; ``manquants`` liste les faits absents."""
    manquants: list[str] = []
    valeurs = {**faits, "expediteur": identite.nom}
    objet = _remplacer(str(etape.get("objet") or ""), valeurs, manquants)
    corps = _remplacer(str(etape.get("corps") or ""), valeurs, manquants).rstrip()
    corps = corps + "\n\n" + pied(identite, source_adresse, lien_desinscription, manquants) + "\n"
    return Rendu(objet=" ".join(objet.split()), corps=corps, manquants=manquants)


def valider_etapes(etapes: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Erreurs d'une séquence saisie par le fondateur : ``[(gabarit, paramètres)]`` (vide si valide)."""
    erreurs: list[tuple[str, dict[str, Any]]] = []
    if not 1 <= len(etapes) <= 6:
        erreurs.append(("Une séquence compte de 1 à 6 étapes.", {}))
    precedent = -1
    for e in etapes:
        rang = e["rang"]
        objet, corps, delai = str(e.get("objet") or ""), str(e.get("corps") or ""), e.get("delai_jours")
        if not objet.strip() or not corps.strip():
            erreurs.append(("Étape {rang} : objet et texte obligatoires.", {"rang": rang}))
        if len(objet) > 150 or len(corps) > 5000:
            erreurs.append(("Étape {rang} : texte trop long.", {"rang": rang}))
        if not isinstance(delai, int) or not 0 <= delai <= 120 or delai <= precedent:
            erreurs.append(("Étape {rang} : délai invalide (jours croissants, 120 au plus).", {"rang": rang}))
        else:
            precedent = delai
        if rang == 1 and delai != 0:
            erreurs.append(("La première étape part le jour J (délai 0).", {}))
        inconnues = sorted({m for m in _VARIABLE.findall(objet + corps) if m not in VARIABLES})
        if inconnues:
            erreurs.append(
                (
                    "Étape {rang} : variable inconnue {variables}.",
                    {"rang": rang, "variables": ", ".join(inconnues)},
                )
            )
        if compter_liens(objet + "\n" + corps) > 1:
            erreurs.append(("Étape {rang} : un lien au plus.", {"rang": rang}))
        if check_text(objet + "\n" + corps):
            erreurs.append(("Étape {rang} : formulation interdite par les garde-fous.", {"rang": rang}))
    return erreurs


#: Séquence par défaut, réécrite depuis ``commercial/sequence_emails.md`` : le fondateur écrit, à la première
#: personne, en vouvoyant ; phrases courtes ; aucun chiffre sans source (l'exemple est signalé comme inventé) ;
#: aucun sujet réglementaire (donc pas de phrase de renvoi nécessaire). Modifiable dans l'interface.
SEQUENCE_DEFAUT: dict[str, Any] = {
    "id": "seq_defaut",
    "nom": "Importateurs : diagnostic gratuit",
    "etapes": [
        {
            "rang": 1,
            "delai_jours": 0,
            "objet": "Vos factures de transitaire",
            "corps": (
                "Bonjour,\n\n"
                "Je m'appelle {expediteur} et j'ai créé ControlDOne. Je compare, dossier par dossier, la facture "
                "du fournisseur, la déclaration en douane et la facture du transitaire, pour repérer ce qui ne "
                "concorde pas.\n\n"
                "{accroche} C'est pour cela que je vous écris.\n\n"
                "Concrètement, je relève par exemple un montant refacturé qui ne correspond pas à la déclaration, "
                "un prix différent de la grille tarifaire, ou un avoir annoncé qui n'est jamais arrivé. Pour chaque "
                "point, je donne les deux valeurs et la page où elles figurent. Je ne donne pas d'avis sur les "
                "droits et taxes.\n\n"
                "Je propose un premier diagnostic gratuit sur une vingtaine de dossiers déjà clos. Il peut très "
                "bien conclure que tout est en ordre.\n\n"
                "Auriez-vous vingt minutes la semaine prochaine pour en parler ? Si ce n'est pas vous qui suivez "
                "ces factures, pouvez-vous me dire à qui écrire ?\n\n"
                "Bien cordialement,\n{expediteur}"
            ),
        },
        {
            "rang": 2,
            "delai_jours": 4,
            "objet": "Re : vos factures de transitaire",
            "corps": (
                "Bonjour,\n\n"
                "Je me permets de revenir vers vous avec un exemple, inventé pour l'illustration.\n\n"
                "La grille tarifaire du transitaire prévoit 45 EUR pour l'ouverture d'un dossier. Sur la facture "
                "du mois, la même ligne est facturée 65 EUR pour trois dossiers. L'écart est de 60 EUR, et on ne "
                "le voit qu'en mettant la grille et les factures côte à côte.\n\n"
                "Le diagnostic fait ce travail sur vos propres dossiers, et vous décidez de la suite.\n\n"
                "Si le sujet vous intéresse, une simple réponse à ce message suffit.\n\n"
                "Bien cordialement,\n{expediteur}"
            ),
        },
        {
            "rang": 3,
            "delai_jours": 10,
            "objet": "Le diagnostic, concrètement",
            "corps": (
                "Bonjour,\n\n"
                "Pour que ce soit concret, voici comment se passe le diagnostic.\n\n"
                "Vous déposez les pièces d'une vingtaine de dossiers déjà clos : factures du fournisseur, "
                "déclarations, factures et avoirs du transitaire. Je vous rends un relevé des écarts constatés, "
                "chacun avec ses pièces. Vous décidez seul de ce que vous en faites, sans aucun engagement.\n\n"
                "Est-ce que cela pourrait être utile chez {raison_sociale} ?\n\n"
                "Bien cordialement,\n{expediteur}"
            ),
        },
        {
            "rang": 4,
            "delai_jours": 20,
            "objet": "Dernier message de ma part",
            "corps": (
                "Bonjour,\n\n"
                "C'est mon dernier message sur ce sujet, je ne vous relancerai pas.\n\n"
                "Si la question des factures de transitaire se pose un jour chez {raison_sociale}, il suffit de "
                "répondre « diagnostic » à ce message.\n\n"
                "Merci de m'avoir lu.\n\n"
                "Bien cordialement,\n{expediteur}"
            ),
        },
    ],
}
