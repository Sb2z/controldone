"""Nature d'une ligne de facture transitaire ou d'avoir d'après son libellé (§5.3.3) — table unique (D-1213).

Utilisée par l'extracteur PDF (``extract.deterministe.facture_transitaire.classer_nature``) et par la lecture
des exports structurés UBL, CII et tableurs (``ingest.structure.nature_ligne``) : un même libellé reçoit la
même nature quel que soit le format du document.

Table ordonnée par spécificité : la première expression qui reconnaît le libellé (minuscules, sans accents,
apostrophes droites) donne la nature. Le mot « forfait » seul ne suffit pas pour le droit forfaitaire petits
envois : il faut un contexte (« petits envois », « par article », « low value », « droit forfaitaire »…), sinon
« Forfait dédouanement » serait pris pour un débours.
"""

from __future__ import annotations

import re

from controldone.model.enums import NatureLigne
from controldone.normalize.text import cle_texte

__all__ = ["NATURES_LIBELLES", "nature_libelle"]

NATURES_LIBELLES: tuple[tuple[NatureLigne, re.Pattern[str]], ...] = (
    (NatureLigne.frais_avance_fonds, re.compile(
        r"avance de fonds|av\.? (?:de )?fonds|frais d'avance|advance (?:fee|of funds)|disbursement fee|cash advance|"
        r"commission d'avance|commission (?:sur|de) debours|frais financiers|finance fee|anticipo de fondos|"
        r"frais de debours")),
    (NatureLigne.frais_ligne_supplementaire, re.compile(
        r"lignes? sup|articles? supp|additional (?:lines?|items?|articles?)|add\.? lines?|extra (?:lines?|items?)|"
        r"ligne additionnelle|ligne(?:s)? (?:de )?(?:declaration )?sup|partida adicional")),
    (NatureLigne.debours_forfait_petits_envois, re.compile(
        r"droit forfaitaire|forfait (?:petits? envois|par article)|petits envois|flat[- ]?(?:rate )?dut|"
        r"low[- ]value|droit fixe par article|per item duty|derecho (?:a tanto alzado|fijo)")),
    (NatureLigne.debours_autres_taxes, re.compile(
        r"autres? (?:tx|taxes?|droits)|other (?:taxes|duties)|accises?|excise|anti-?dumping|compensat|octroi|"
        r"taxe (?:speciale|interieure|additionnelle)|impuestos especiales")),
    (NatureLigne.debours_combines, re.compile(
        r"droits? (?:et|&) (?:taxes|tva)|duties (?:and|&) taxes|duty (?:and|&) tax|droits/taxes|taxes et droits|"
        r"derechos e impuestos")),
    (NatureLigne.debours_tva, re.compile(
        r"tva (?:a l'|a l |de l')?import|import vat|vat on import|tva douane|tva sur import|tva debours|"
        r"tva avancee|iva (?:de )?importacion|^tva$")),
    (NatureLigne.debours_droits, re.compile(
        r"droits? de douane|customs dut|\bdut(?:y|ies)\b|^droits?\b|aranceles?|derechos de aduana")),
    (NatureLigne.magasinage, re.compile(
        r"magasinage|storage|entreposage|stockage|warehous|stationnement|demurrage|almacenaje")),
    (NatureLigne.surcharge, re.compile(
        r"surcharge|carburant|\bfuel\b|surete|security|haute saison|peak season|\bbaf\b|\bcaf\b|recargo")),
    (NatureLigne.manutention, re.compile(r"manutention|handling|chargement|dechargement|manipulacion")),
    (NatureLigne.transport, re.compile(
        r"livraison|delivery|enlevement|pick-? ?up|collection|\btransport|acheminement|camionnage|trucking|"
        r"\bfret\b|freight|\bentrega\b|recogida")),
    (NatureLigne.frais_dedouanement, re.compile(
        r"dedouan|clearance|declaration en douane|customs (?:entry|declaration|formalities)|"
        r"formalites? (?:de )?douan|despacho (?:de )?aduan|representation en douane")),
)


def nature_libelle(libelle: str | None) -> NatureLigne | None:
    """Nature reconnue d'après le libellé ; ``None`` si aucun mot-clé n'est reconnu."""
    if not libelle:
        return None
    t = cle_texte(libelle)
    for nature, motif in NATURES_LIBELLES:
        if motif.search(t):
            return nature
    return None
