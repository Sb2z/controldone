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

__all__ = ["NATURES_LIBELLES", "nature_libelle", "renvoie_a_une_annexe"]

NATURES_LIBELLES: tuple[tuple[NatureLigne, re.Pattern[str]], ...] = (
    (
        NatureLigne.frais_avance_fonds,
        re.compile(
            r"avance de fonds|av\.? (?:de )?fonds|frais d'avance|advance (?:fee|of funds)|disbursement fee|cash advance|"
            r"commission d'avance|commission (?:sur|de) debours|frais financiers|finance fee|anticipo de fondos|"
            r"frais de debours|"
            # de / it / es / nl
            r"vorlageprovision|vorlagegebuhr|auslagenprovision|kapitalbereitstellung|"
            r"(?:commissione|diritti?) (?:di |per )?anticip|anticipazione (?:diritti|fondi)|"
            r"comision (?:por|de) anticipo|anticipo de (?:derechos|fondos|suplidos)|"
            r"voorschotprovisie|voorschotkosten|provisie voorschot|"
            # pt / pl (D-2501)
            r"comissao de adiantamento|adiantamento de (?:fundos|despesas)|taxa de adiantamento|"
            r"prowizja (?:za|od) (?:kredytowanie|wylozenie|zaliczk|kredyt)|oplata za kredytowanie"
        ),
    ),
    (
        NatureLigne.frais_ligne_supplementaire,
        re.compile(
            r"lignes? sup|articles? supp|additional (?:lines?|items?|articles?)|add\.? lines?|extra (?:lines?|items?)|"
            r"ligne additionnelle|ligne(?:s)? (?:de )?(?:declaration )?sup|partida adicional|"
            r"additional (?:entry|declaration|customs) (?:lines?|items?)|"
            r"zusatzliche (?:positionen|zollpositionen|tarifpositionen)|zusatzposition|weitere positionen|"
            r"voci (?:doganali )?aggiuntive|voce aggiuntiva|righe aggiuntive|partidas adicionales|lineas adicionales|"
            r"extra aangifteregels|aanvullende (?:regels|posten)|extra (?:regels|posten)|"
            r"adicoes (?:suplementares|adicionais)|linhas adicionais|artigos adicionais|"
            r"dodatkowe (?:pozycje|linie|artykuly)|dodatkowa pozycja"
        ),
    ),
    (
        NatureLigne.debours_forfait_petits_envois,
        re.compile(
            r"droit forfaitaire|forfait (?:petits? envois|par article)|petits envois|flat[- ]?(?:rate )?dut|"
            r"low[- ]value|droit fixe par article|per item duty|derecho (?:a tanto alzado|fijo)|"
            r"pauschalzoll|zollpauschale|kleinsendung|dazio forfettario|piccole spedizioni|"
            r"pequenos envios|forfaitair recht|kleine zendingen|direito fixo|pequenas remessas|"
            r"oplata ryczaltowa|ryczalt (?:za|od) artykul|male przesylki"
        ),
    ),
    (
        NatureLigne.debours_autres_taxes,
        re.compile(
            r"autres? (?:tx|taxes?|droits)|other (?:taxes|duties)|accises?|excise|anti-?dumping|compensat|octroi|"
            r"taxe (?:speciale|interieure|additionnelle)|impuestos especiales|"
            r"verbrauchsteuer|antidumpingzoll|andere abgaben|sonstige abgaben|altri (?:dazi|diritti|tributi)|"
            r"otros (?:impuestos|derechos)|accijns|overige (?:heffingen|rechten)|antydumping|"
            r"outros (?:impostos|direitos)|imposto especial|akcyza"
        ),
    ),
    (
        NatureLigne.debours_combines,
        re.compile(
            r"droits? (?:et|&) (?:taxes|tva)|duties (?:and|&) taxes|duty (?:and|&) tax|droits/taxes|taxes et droits|"
            r"derechos e impuestos|"
            r"zolle und (?:steuern|abgaben)|zoll und einfuhrumsatzsteuer|dazi e (?:iva|imposte|tributi)|"
            r"aranceles e (?:iva|impuestos)|rechten en (?:btw|belastingen)|invoerrechten en btw|"
            r"direitos e (?:impostos|iva)|cla? i podatki"
        ),
    ),
    (
        NatureLigne.debours_tva,
        re.compile(
            r"tva (?:a l'|a l |de l')?import|import vat|vat on import|tva douane|tva sur import|tva debours|"
            r"tva avancee|iva (?:de )?importacion|^tva$|"
            r"einfuhrumsatzsteuer|\beust\b|iva (?:all'|alla |di |sull')?importazion|"
            r"btw (?:bij|op) invoer|invoer-?btw|iva (?:na |de |sobre a )?importacao|"
            r"vat (?:z tytulu|od) importu|vat importowy|podatek vat (?:z tytulu|od) importu"
        ),
    ),
    (
        NatureLigne.debours_droits,
        re.compile(
            r"droits? de douane|customs dut|\bdut(?:y|ies)\b|^droits?\b|aranceles?|derechos de aduana|"
            r"zollabgaben|^zoll\b|einfuhrzoll|^zolle\b|dazi[oe]? (?:doganal|all'importazione)|^dazi[oe]?\b|"
            r"invoerrechten|douanerechten|direitos (?:aduaneiros|de importacao|alfandegarios)|^direitos\b|"
            r"^clo\b|clo (?:importowe|przywozowe)|^cla\b"
        ),
    ),
    (
        NatureLigne.magasinage,
        re.compile(
            r"magasinage|storage|entreposage|stockage|warehous|stationnement|demurrage|almacenaje|"
            r"lagergeld|lagerung|lagerkosten|magazzinaggio|giacenza|deposito|bodegaje|opslag|"
            r"\bstalling|armazenagem|armazenamento|skladowanie|magazynowanie|przechowywanie"
        ),
    ),
    (
        NatureLigne.surcharge,
        re.compile(
            r"surcharge|carburant|\bfuel\b|surete|security|haute saison|peak season|\bbaf\b|\bcaf\b|recargo|"
            r"zuschlag|supplemento|maggiorazione|sobrecargo|toeslag|sobretaxa|doplata"
        ),
    ),
    (
        NatureLigne.manutention,
        re.compile(
            r"manutention|handling|chargement|dechargement|manipulacion|"
            r"^umschlag|umschlaggebuhr|\bumschlag\b|movimentazione|manipolazione|carico e scarico|"
            r"carga y descarga|^behandeling|overslag|laden en lossen|manuseamento|manuseio|movimentacao|"
            r"obsluga (?:ladunku|towaru)|przeladunek"
        ),
    ),
    (
        NatureLigne.transport,
        re.compile(
            r"livraison|delivery|enlevement|pick-? ?up|collection|\btransport|acheminement|camionnage|trucking|"
            r"\bfret\b|freight|\bentrega\b|recogida|"
            r"zustellung|anlieferung|abholung|\bfracht|consegna|ritiro|trasporto|bezorging|levering|"
            r"afhaling|\bvervoer|dostawa|przewoz|odbior"
        ),
    ),
    (
        NatureLigne.frais_dedouanement,
        re.compile(
            r"dedouan|clearance|declaration en douane|customs (?:entry|declaration|formalities)|"
            r"formalites? (?:de )?douan|despacho (?:de )?aduan|representation en douane|"
            r"verzollung|zollabfertigung|zollanmeldung|sdoganamento|dichiarazione doganale|"
            r"inklaring|douaneaangifte|aangifte ten invoer|desalfandegamento|despacho aduaneiro|desembaraco|"
            r"odprawa celna|zgloszenie celne"
        ),
    ),
)


def nature_libelle(libelle: str | None, *, tolerant: bool = False) -> NatureLigne | None:
    """Nature reconnue d'après le libellé ; ``None`` si aucun mot-clé n'est reconnu.

    ``tolerant`` (libellé lu par OCR, D-2305) : si rien n'est reconnu, chaque mot d'au moins 6 caractères qui
    n'est pas un mot du vocabulaire est remplacé par **l'unique** mot du vocabulaire à une seule édition de lui
    (« Comisi6n » -> « comision », « dédauanement » -> « dedouanement ») ; la table est appliquée une seconde
    fois. Aucun remplacement s'il y a deux candidats ou plus."""
    if not libelle:
        return None
    # numéro de ligne collé au libellé (« 1   Cło », « 3. Dostawa ») : hors du libellé (D-2501)
    t = re.sub(r"^\d{1,3}[.)]?\s+(?=[^\W\d_])", "", cle_texte(libelle))
    n = _chercher(t)
    if n is not None or not tolerant:
        return n
    corrige = _corriger_ocr(t)
    return _chercher(corrige) if corrige != t else None


def _chercher(t: str) -> NatureLigne | None:
    for nature, motif in NATURES_LIBELLES:
        if motif.search(t):
            return nature
    return None


#: Mots (et radicaux) du vocabulaire des natures, tirés des expressions de la table.
_VOCABULAIRE: frozenset[str] = frozenset(
    w for _, motif in NATURES_LIBELLES for w in re.findall(r"[a-z]{6,}", motif.pattern)
)
_RX_MOT = re.compile(r"[a-z0-9]+")
#: Mots courts du vocabulaire (3 à 5 lettres : « clo », « zoll », « dazi ») ; corrigés seulement par confusion
#: de glyphes typique de l'OCR (D-2515).
_VOCABULAIRE_COURT: frozenset[str] = frozenset(
    w
    for _, motif in NATURES_LIBELLES
    for w in re.findall(r"(?<![a-z])[a-z]{3,5}(?![a-z])", re.sub(r"\\[a-z]", " ", motif.pattern))
)
#: Classes de glyphes que l'OCR confond (« ł » lu « t », « l » lu « 1 » ou « i »).
_CLASSES_OCR = ("lti1|!f", "o0", "s5", "b8", "z2", "g9q", "e3")


def _meme_classe(a: str, b: str) -> bool:
    return a == b or any(a in c and b in c for c in _CLASSES_OCR)


def _candidat_court(mot: str) -> str | None:
    """Mot court du vocabulaire dont ``mot`` ne diffère que par des glyphes confondus par l'OCR (une seule
    différence) ; ``None`` si aucun ou plusieurs."""
    trouves = {
        v
        for v in _VOCABULAIRE_COURT
        if len(v) == len(mot)
        and v != mot
        and sum(x != y for x, y in zip(v, mot, strict=True)) == 1
        and all(_meme_classe(x, y) for x, y in zip(v, mot, strict=True))
    }
    return trouves.pop() if len(trouves) == 1 else None


def _une_edition(a: str, b: str) -> bool:
    """``a`` et ``b`` diffèrent d'exactement une substitution, insertion ou suppression."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    court, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(court) and court[i] == long_[i]:
        i += 1
    return court[i:] == long_[i + 1 :]


def _candidat(mot: str) -> str | None:
    """Mot du vocabulaire à une édition de ``mot`` (mot entier, ou radical en tête du mot) ; ``None`` si
    aucun ou plusieurs."""
    trouves: set[str] = set()
    for v in _VOCABULAIRE:
        if _une_edition(mot, v):
            trouves.add(v)
        elif len(mot) > len(v) + 1:
            # radical (« dedouan », « warehous ») : tête du mot à une édition du radical, reste conservé
            for k in (len(v) - 1, len(v), len(v) + 1):
                if _une_edition(mot[:k], v):
                    trouves.add(v + mot[k:])
                    break
        if len(trouves) > 1:
            return None
    return trouves.pop() if trouves else None


def _corriger_ocr(t: str) -> str:
    def remplacer(m: re.Match[str]) -> str:
        mot = m.group(0)
        if 3 <= len(mot) <= 5 and mot not in _VOCABULAIRE_COURT:
            return _candidat_court(mot) or mot
        if len(mot) < 6 or mot in _VOCABULAIRE or sum(c.isalpha() for c in mot) < 4:
            return mot
        return _candidat(mot) or mot

    return _RX_MOT.sub(remplacer, t)


#: Libellé d'une ligne qui renvoie au détail d'une annexe (« Suplidos según anexo », « Disbursements as per annex »).
_RX_RENVOI_ANNEXE = re.compile(
    r"\b(annexe|annex|anexo|anlage|allegato|bijlage|appendix|see attached|ci-joint|siehe|vedi|zie)\b"
)


def renvoie_a_une_annexe(libelle: str | None) -> bool:
    """La ligne résume un détail imprimé ailleurs (annexe) : ce n'est pas une prestation (D-2305)."""
    return bool(libelle) and bool(_RX_RENVOI_ANNEXE.search(cle_texte(libelle or "")))
