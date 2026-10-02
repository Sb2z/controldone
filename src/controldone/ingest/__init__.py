"""Ingestion (SPEC §5.1, §6.2.5–6.2.6, §7.1–7.3, §20.2–20.3) : fichiers -> pages -> documents logiques.

- ``reception`` : lot, fichiers (type par octets, refus motivés, ZIP sûr, courriels) ;
- ``pages`` : texte natif / OCR par page, qualité, mots positionnés (``PageText``), cache disque ;
- ``classement`` : type de chaque page (mots-clés fr/en/es, déterministe) ;
- ``decoupage`` : documents logiques ; ``Decoupeur`` est le composant découvert par ``controldone.pipeline`` ;
- ``structure`` : extracteurs ``structure`` (Factur-X, CII, UBL, exports de déclaration par fiche).
"""

from .classement import (
    CONTINUATION,
    SEUIL_CONFIANCE,
    VERSION_CLASSIFIEUR,
    ClassementPage,
    RefsPage,
    classer_page,
    detecter_langue,
    extraire_refs,
)
from .decoupage import (
    VERSION_DECOUPAGE,
    Decoupeur,
    ResultatIngestion,
    cle_classement,
    decouper_fichier,
    decouper_pages,
    enregistrer_textes,
    texte_positionne,
)
from .pages import (
    VERSION_PAGES,
    CachePagesDisque,
    OptionsPages,
    PageExtraite,
    extraire_pages,
    extraire_pages_local,
    ocr_disponible,
    version_ocr,
)
from .reception import (
    MIME_CORPS_COURRIEL,
    FichierRecu,
    Limites,
    MotifRefus,
    Reception,
    cle_idempotence_reception,
    expediteur_autorise,
    recevoir,
    recevoir_chemin,
    recevoir_courriel,
    recevoir_octets,
)
from .sniff import detecter_type
from .structure import (
    ExtracteurDeclarationExport,
    ExtracteurFactureXML,
    FicheCorrespondance,
    InfoStructure,
    analyser_contenu_structure,
    categorie_taxe,
    charger_fiches,
    est_facture_transitaire,
    extracteurs,
    nature_ligne,
    paiement_normalise,
    xml_facturx,
)
from .texte import Ligne, Mot, PageText, score_texte

#: Version publiée (clé d'idempotence des étapes 2 et 3).
VERSION = VERSION_DECOUPAGE

__all__ = [
    "CONTINUATION",
    "MIME_CORPS_COURRIEL",
    "SEUIL_CONFIANCE",
    "VERSION",
    "VERSION_CLASSIFIEUR",
    "VERSION_DECOUPAGE",
    "VERSION_PAGES",
    "CachePagesDisque",
    "ClassementPage",
    "Decoupeur",
    "ExtracteurDeclarationExport",
    "ExtracteurFactureXML",
    "FicheCorrespondance",
    "FichierRecu",
    "InfoStructure",
    "Ligne",
    "Limites",
    "MotifRefus",
    "Mot",
    "OptionsPages",
    "PageExtraite",
    "PageText",
    "Reception",
    "RefsPage",
    "ResultatIngestion",
    "analyser_contenu_structure",
    "categorie_taxe",
    "charger_fiches",
    "classer_page",
    "cle_classement",
    "cle_idempotence_reception",
    "decouper_fichier",
    "decouper_pages",
    "detecter_langue",
    "detecter_type",
    "enregistrer_textes",
    "est_facture_transitaire",
    "expediteur_autorise",
    "extracteurs",
    "extraire_pages",
    "extraire_pages_local",
    "extraire_refs",
    "nature_ligne",
    "ocr_disponible",
    "paiement_normalise",
    "recevoir",
    "recevoir_chemin",
    "recevoir_courriel",
    "recevoir_octets",
    "score_texte",
    "texte_positionne",
    "version_ocr",
    "xml_facturx",
]
