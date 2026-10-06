"""Énumérations du modèle (valeurs ASCII minuscules, sans accent — SPEC, préambule).

Ajouter une valeur à une énumération est un changement **mineur** du schéma ; en retirer une ou en
changer le sens est **majeur** (SPEC §6.4).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "RAISON_LIBELLES",
    "BasePourcentage",
    "CanalLot",
    "CategorieTaxe",
    "Composante",
    "ForceLien",
    "Methode",
    "MethodeAllocation",
    "ModePoste",
    "MotifNonExploitable",
    "NatureLigne",
    "NatureMontant",
    "Niveau",
    "Offre",
    "Outcome",
    "PaiementNormalise",
    "PrestationsHorsGrille",
    "QualiteTexte",
    "RaisonCode",
    "RoleAuteur",
    "RoleLien",
    "RolePreuve",
    "Sens",
    "SignalLien",
    "SigneImprime",
    "SousTypeDeclaration",
    "SousTypeFactureCommerciale",
    "SousTypeSupport",
    "StatutEcart",
    "StatutFichier",
    "StatutGlobal",
    "StatutGrille",
    "StatutLot",
    "StatutValidation",
    "TauxChangeSens",
    "TauxNature",
    "TotalOrigine",
    "TypeDocument",
    "TypeExtracteur",
    "TypeIndiceAutoliquidation",
    "TypeSousTotal",
    "TypeValeur",
]


# --- Résultats de contrôle (SPEC §1.3, §8.5, §8.6) ---------------------------------------------


class Outcome(StrEnum):
    conforme = "conforme"
    ecart_certain = "ecart_certain"
    a_verifier = "a_verifier"
    non_verifiable = "non_verifiable"
    non_applicable = "non_applicable"

    @property
    def est_constat(self) -> bool:
        return self in (Outcome.ecart_certain, Outcome.a_verifier)


class Niveau(StrEnum):
    """Niveau d'un constat : seuls les deux niveaux de constat du rapport client."""

    ecart_certain = "ecart_certain"
    a_verifier = "a_verifier"

    @property
    def outcome(self) -> Outcome:
        return Outcome(self.value)


class RaisonCode(StrEnum):
    """Raisons d'un ``a_verifier`` (§8.5.3) et motifs de ``non_verifiable`` / ``non_applicable``.

    Les 17 premières valeurs sont celles de SPEC §8.5.3, dans l'ordre. Les suivantes sont des ajouts
    (voir ``docs/DECISIONS.md`` D-012) nécessaires aux règles de §8.6, §10 et au moteur.
    L'ordre de déclaration sert d'ordre canonique de tri des raisons (sortie déterministe).
    """

    # §8.5.3
    ecart_sous_seuil = "ecart_sous_seuil"
    confiance_insuffisante = "confiance_insuffisante"
    valeur_non_ancree = "valeur_non_ancree"
    lecture_douteuse = "lecture_douteuse"
    total_reconstruit = "total_reconstruit"
    rattachement_faible = "rattachement_faible"
    allocation_prorata = "allocation_prorata"
    ecart_explique_par_ligne_de_pied = "ecart_explique_par_ligne_de_pied"
    devise_incertaine = "devise_incertaine"
    unites_differentes = "unites_differentes"
    extracteurs_en_desaccord = "extracteurs_en_desaccord"
    renvoi_reglementaire = "renvoi_reglementaire"
    controle_signal_seulement = "controle_signal_seulement"
    document_manquant = "document_manquant"
    document_non_exploitable = "document_non_exploitable"
    plusieurs_entites = "plusieurs_entites"
    point_fiscal = "point_fiscal"
    # Ajouts cités par la spécification (§8.6, A3)
    doublon_composantes = "doublon_composantes"
    montant_converti = "montant_converti"
    # Ajouts moteur (D-012)
    ecart_en_faveur_client = "ecart_en_faveur_client"
    sens_taux_derive = "sens_taux_derive"
    version_rectificative = "version_rectificative"
    avoir_impute = "avoir_impute"
    valeur_absente = "valeur_absente"
    aucune_grille_validee = "aucune_grille_validee"
    facture_transitaire_absente = "facture_transitaire_absente"
    couvert_par_autre_controle = "couvert_par_autre_controle"
    dossier_non_concerne = "dossier_non_concerne"
    erreur_interne = "erreur_interne"
    # Ajout plateforme (D-505) : constat rétrogradé par le fondateur lors de la validation (§7.7)
    retrograde_par_fondateur = "retrograde_par_fondateur"
    # Ajout moteur (D-1700) : lecture non confirmée par l'arithmétique interne du document
    lecture_non_corroboree = "lecture_non_corroboree"
    # Ajout moteur (D-2205) : avoir rattaché à la facture mais non ventilé (non imputable)
    avoir_non_ventile = "avoir_non_ventile"
    # Ajout moteur (D-2210) : structure lue du tableau (taxes, masses) non validée pour un écart certain
    structure_non_validee = "structure_non_validee"
    # Ajouts moteur (D-2211 à D-2213) : preuve insuffisante pour un écart certain C8, D5, D4
    entite_facturee_attestee = "entite_facturee_attestee"
    doublon_non_etabli = "doublon_non_etabli"
    assiette_alternative = "assiette_alternative"
    # Ajouts moteur (D-2701, D-2702) : ligne TVA comprise ; rattachement d'une ligne à une déclaration non établi
    montant_tva_comprise = "montant_tva_comprise"
    attribution_non_univoque = "attribution_non_univoque"
    # Ajouts moteur (D-2801 à D-2803) : assiette ou grille d'un tarif non établie ; écart expliqué par un ensemble
    # de documents incomplet ou par une lecture du séparateur décimal (A4, A5)
    assiette_non_etablie = "assiette_non_etablie"
    grille_non_attestee = "grille_non_attestee"
    perimetre_non_etabli = "perimetre_non_etabli"
    # Ajouts moteur (D-4212, D-4213) : avoir du dossier non imputé ; tarif attendu d'une ligne non établi (D3, D4)
    avoir_non_impute = "avoir_non_impute"
    tarif_non_etabli = "tarif_non_etabli"


#: Libellés en clair des raisons (gabarits ; SPEC §3.1 règle 4, §8.5.3). Aucun ne contient
#: d'expression interdite (testé).
RAISON_LIBELLES: dict[RaisonCode, str] = {
    RaisonCode.ecart_sous_seuil: "à vérifier : l'écart dépasse la tolérance mais reste sous le seuil de certitude",
    RaisonCode.confiance_insuffisante: "à vérifier : une valeur a été lue avec une confiance insuffisante",
    RaisonCode.valeur_non_ancree: "à vérifier : une valeur n'a pas été retrouvée telle quelle dans le texte de la page",
    RaisonCode.lecture_douteuse: (
        "à vérifier : un chiffre probablement mal lu (par exemple 6 et 8, souvent confondus) "
        "expliquerait l'écart"
    ),
    RaisonCode.total_reconstruit: (
        "à vérifier : le total n'est pas imprimé ; il a été reconstitué à partir des lignes lues"
    ),
    RaisonCode.rattachement_faible: "à vérifier : le rattachement de ce document au dossier est faible",
    RaisonCode.allocation_prorata: "à vérifier : la répartition entre déclarations a été faite au prorata",
    RaisonCode.ecart_explique_par_ligne_de_pied: (
        "à vérifier : l'écart correspond à une ligne de pied de la facture (fret, assurance, emballage, remise)"
    ),
    RaisonCode.devise_incertaine: "à vérifier : la devise n'a pas pu être lue avec certitude",
    RaisonCode.unites_differentes: "les unités des deux documents diffèrent : comparaison impossible",
    RaisonCode.extracteurs_en_desaccord: "à vérifier : les méthodes de lecture donnent des valeurs différentes",
    RaisonCode.renvoi_reglementaire: "point relevant d'une appréciation réglementaire",
    RaisonCode.controle_signal_seulement: "contrôle de signal : le résultat est toujours à vérifier",
    RaisonCode.document_manquant: "un document nécessaire est absent du dossier",
    RaisonCode.document_non_exploitable: "un document du dossier n'est pas exploitable",
    RaisonCode.plusieurs_entites: "à vérifier : plusieurs entités du client figurent sur le document",
    RaisonCode.point_fiscal: "point fiscal : à faire confirmer par votre expert-comptable",
    RaisonCode.doublon_composantes: (
        "montant non additionné : il est déjà compté dans les contrôles par composante"
    ),
    RaisonCode.montant_converti: "devises différentes : le montant déclaré est converti en EUR",
    RaisonCode.ecart_en_faveur_client: (
        "à vérifier : le montant refacturé est inférieur au montant de référence (écart en faveur du client)"
    ),
    RaisonCode.sens_taux_derive: "à vérifier : le sens du taux de change n'est pas imprimé ; il a été déduit",
    RaisonCode.version_rectificative: "à vérifier : une version rectificative de la déclaration existe",
    RaisonCode.avoir_impute: "à vérifier : un avoir déjà reçu couvre tout ou partie de l'écart",
    RaisonCode.valeur_absente: "une valeur nécessaire est absente ou illisible",
    RaisonCode.aucune_grille_validee: "aucune grille tarifaire validée pour ce transitaire",
    RaisonCode.facture_transitaire_absente: "aucune facture du transitaire dans le dossier",
    RaisonCode.couvert_par_autre_controle: "sujet déjà traité par un autre contrôle",
    RaisonCode.dossier_non_concerne: "dossier non concerné : l'acheteur n'est pas une entité du client",
    RaisonCode.erreur_interne: "contrôle non réalisé à la suite d'une erreur interne",
    RaisonCode.retrograde_par_fondateur: (
        "à vérifier : classement abaissé lors de la relecture, une valeur reste à confirmer"
    ),
    RaisonCode.avoir_non_ventile: (
        "à vérifier : un avoir du même transitaire, rattaché à cette facture, n'a pas pu être ventilé par nature ; "
        "il peut couvrir tout ou partie de l'écart"
    ),
    RaisonCode.structure_non_validee: (
        "à vérifier : la disposition lue du tableau (lignes de taxe ou masses des articles) n'a pas pu être "
        "validée (ligne en double, article sans ligne, ligne de total ambiguë) ; une erreur de lecture pourrait "
        "expliquer l'écart"
    ),
    RaisonCode.entite_facturee_attestee: (
        "à vérifier : l'entité facturée figure aussi sur un autre document de l'envoi (acheteur de la facture "
        "commerciale, importateur d'une autre déclaration de la même facture) ; la différence peut venir de "
        "la déclaration plutôt que de la facture du transitaire"
    ),
    RaisonCode.doublon_non_etabli: (
        "à vérifier : les lignes identiques peuvent correspondre à des prestations distinctes (plusieurs envois "
        "ou contenants, ligne reportée d'une page à l'autre) ; la répétition n'est pas établie"
    ),
    RaisonCode.assiette_alternative: (
        "à vérifier : le montant facturé correspond au calcul de la grille sur une autre assiette (droits seuls, "
        "débours avec ou sans TVA, montants liquidés) ou avec un autre arrondi ; l'écart dépend de l'assiette "
        "retenue"
    ),
    RaisonCode.montant_tva_comprise: (
        "à vérifier : la ligne n'imprime que son montant TVA comprise ; le montant hors TVA comparé en est déduit "
        "(ou n'a pas pu l'être), il ne peut pas fonder un écart certain"
    ),
    RaisonCode.attribution_non_univoque: (
        "à vérifier : une ligne de la facture du transitaire n'a pas pu être rattachée avec certitude à une "
        "déclaration (référence d'envoi illisible, d'un autre envoi ou absente sur une facture qui couvre plusieurs "
        "envois)"
    ),
    RaisonCode.assiette_non_etablie: (
        "à vérifier : l'assiette du calcul n'est pas établie sans ambiguïté (frais calculés par envoi ou par "
        "facture, débours d'une autre facture dont toutes les lignes ne sont pas confirmées, avoirs ou montants "
        "TVA comprise dans les débours) ; l'écart dépend de l'assiette retenue"
    ),
    RaisonCode.grille_non_attestee: (
        "à vérifier : l'émetteur lu sur la facture ne permet pas de confirmer le transitaire dont la grille "
        "tarifaire a été appliquée"
    ),
    RaisonCode.perimetre_non_etabli: (
        "à vérifier : l'écart peut venir d'un document de l'envoi absent du dossier (autre facture citée par la "
        "déclaration, autre déclaration de l'envoi), d'un total de page pris pour le total de la facture, ou "
        "d'une lecture de l'échelle (séparateur décimal) ou du signe d'un montant ; les montants comparés ne "
        "couvrent peut-être pas le même périmètre"
    ),
    RaisonCode.avoir_non_impute: (
        "à vérifier : un avoir du même transitaire figure dans le dossier sans avoir pu être imputé à cette ligne "
        "(rattachement ou nature non établis) ; il peut couvrir tout ou partie de l'écart"
    ),
    RaisonCode.tarif_non_etabli: (
        "à vérifier : le tarif attendu pour cette ligne n'est pas établi sans ambiguïté (quantité ou prix unitaire "
        "non lus, prestation facturée plusieurs fois sur une ligne, plusieurs grilles possibles, autre version de "
        "la facture) ; l'écart dépend du tarif retenu"
    ),
    RaisonCode.lecture_non_corroboree: (
        "à vérifier : la lecture d'un montant n'est confirmée par aucun autre calcul imprimé sur le même "
        "document (total, somme des lignes) ; une erreur de lecture pourrait expliquer l'écart"
    ),
}


class NatureMontant(StrEnum):
    """Nature du montant en jeu (§8.6)."""

    recouvrable = "recouvrable"
    ecart_documentaire = "ecart_documentaire"
    arithmetique_declaration = "arithmetique_declaration"
    renvoi = "renvoi"
    aucun = "aucun"


class Composante(StrEnum):
    droit = "droit"
    autre_taxe = "autre_taxe"
    tva = "tva"
    forfait_petits_envois = "forfait_petits_envois"
    prestation = "prestation"
    valeur = "valeur"


class Sens(StrEnum):
    defaveur_client = "defaveur_client"
    faveur_client = "faveur_client"


class StatutValidation(StrEnum):
    propose = "propose"
    valide = "valide"
    rejete = "rejete"
    modifie = "modifie"


class RolePreuve(StrEnum):
    valeur_a = "valeur_a"
    valeur_b = "valeur_b"
    operande = "operande"
    contexte = "contexte"


class StatutGlobal(StrEnum):
    """Statut global d'un dossier (§18.2), par ordre de priorité décroissante."""

    non_concerne = "non_concerne"
    document_manquant = "document_manquant"
    ecart_certain = "ecart_certain"
    a_verifier = "a_verifier"
    conforme = "conforme"


# --- Documents (§5, §6.2.6) --------------------------------------------------------------------


class TypeDocument(StrEnum):
    facture_commerciale = "facture_commerciale"
    declaration = "declaration"
    facture_transitaire = "facture_transitaire"
    avoir = "avoir"
    document_support = "document_support"
    document_non_exploitable = "document_non_exploitable"
    inconnu = "inconnu"


class SousTypeFactureCommerciale(StrEnum):
    facture = "facture"
    pro_forma = "pro_forma"
    valeur_douane_seulement = "valeur_douane_seulement"
    sans_valeur_commerciale = "sans_valeur_commerciale"
    facture_integrateur = "facture_integrateur"


class SousTypeDeclaration(StrEnum):
    h1 = "h1"
    h7 = "h7"
    dau_cases = "dau_cases"
    preuve_dedouanement = "preuve_dedouanement"
    export_xml = "export_xml"
    export_csv = "export_csv"


class SousTypeSupport(StrEnum):
    titre_transport = "titre_transport"
    liste_colisage = "liste_colisage"
    pre_alerte = "pre_alerte"
    conditions_generales = "conditions_generales"
    lettre_accompagnement = "lettre_accompagnement"
    courriel = "courriel"
    certificat = "certificat"
    preuve_paiement = "preuve_paiement"
    autre = "autre"


class MotifNonExploitable(StrEnum):
    """Motifs P2 (§9)."""

    pre_alerte = "pre_alerte"
    liste_reparation = "liste_reparation"
    liste_expedition = "liste_expedition"
    bon_livraison_sans_valeur = "bon_livraison_sans_valeur"
    document_export = "document_export"
    perfectionnement_passif = "perfectionnement_passif"
    devis = "devis"
    bon_commande = "bon_commande"
    recu = "recu"
    hors_sujet = "hors_sujet"
    illisible = "illisible"
    protege = "protege"
    corrompu = "corrompu"


class TypeSousTotal(StrEnum):
    marchandises = "marchandises"
    fret = "fret"
    assurance = "assurance"
    emballage = "emballage"
    remise = "remise"
    autre = "autre"


class CategorieTaxe(StrEnum):
    droit = "droit"
    autre_taxe = "autre_taxe"
    tva = "tva"
    forfait_petits_envois = "forfait_petits_envois"
    inconnue = "inconnue"


class TauxNature(StrEnum):
    ad_valorem = "ad_valorem"
    specifique = "specifique"


class PaiementNormalise(StrEnum):
    comptant = "comptant"
    differe = "differe"
    autoliquide = "autoliquide"
    garanti = "garanti"
    inconnu = "inconnu"


class TauxChangeSens(StrEnum):
    eur_par_devise = "eur_par_devise"
    devise_par_eur = "devise_par_eur"


class TypeIndiceAutoliquidation(StrEnum):
    code_1008 = "code_1008"
    reference_fr7 = "reference_fr7"
    mode_paiement_tva = "mode_paiement_tva"


class NatureLigne(StrEnum):
    """Nature d'une ligne de facture transitaire ou d'avoir (§5.3.3)."""

    debours_droits = "debours_droits"
    debours_autres_taxes = "debours_autres_taxes"
    debours_tva = "debours_tva"
    debours_combines = "debours_combines"
    debours_forfait_petits_envois = "debours_forfait_petits_envois"
    frais_dedouanement = "frais_dedouanement"
    frais_avance_fonds = "frais_avance_fonds"
    frais_ligne_supplementaire = "frais_ligne_supplementaire"
    magasinage = "magasinage"
    transport = "transport"
    manutention = "manutention"
    surcharge = "surcharge"
    autre_prestation = "autre_prestation"

    @property
    def est_debours(self) -> bool:
        return self.value.startswith("debours_")

    @property
    def est_prestation(self) -> bool:
        return not self.est_debours

    @property
    def composante(self) -> Composante | None:
        """Composante de recouvrement (§17.2). ``None`` pour ``debours_combines`` (plusieurs)."""
        return {
            NatureLigne.debours_droits: Composante.droit,
            NatureLigne.debours_autres_taxes: Composante.autre_taxe,
            NatureLigne.debours_tva: Composante.tva,
            NatureLigne.debours_forfait_petits_envois: Composante.forfait_petits_envois,
            NatureLigne.debours_combines: None,
        }.get(self, Composante.prestation)


# --- Provenance (§6.3) -------------------------------------------------------------------------


class TypeExtracteur(StrEnum):
    structure = "structure"
    deterministe = "deterministe"
    llm = "llm"
    saisie_humaine = "saisie_humaine"
    derive = "derive"


class Methode(StrEnum):
    xml_structure = "xml_structure"
    csv_structure = "csv_structure"
    texte_natif = "texte_natif"
    ocr = "ocr"
    llm = "llm"
    saisie_humaine = "saisie_humaine"
    derive = "derive"

    @property
    def est_structuree(self) -> bool:
        """Méthodes dispensées d'ancrage pour un ``ecart_certain`` (§8.5.1 condition 3)."""
        return self in (Methode.xml_structure, Methode.csv_structure, Methode.saisie_humaine)


class QualiteTexte(StrEnum):
    natif = "natif"
    natif_faible = "natif_faible"
    ocr = "ocr"
    illisible = "illisible"


class TypeValeur(StrEnum):
    montant = "montant"
    decimal = "decimal"
    entier = "entier"
    taux = "taux"
    masse = "masse"
    quantite = "quantite"
    date = "date"
    texte = "texte"
    reference = "reference"
    code = "code"
    pays = "pays"
    devise = "devise"
    tva = "tva"
    siren = "siren"
    eori = "eori"
    incoterm = "incoterm"
    unite = "unite"
    enumeration = "enumeration"
    booleen = "booleen"


class SigneImprime(StrEnum):
    positif = "positif"
    negatif = "negatif"


class TotalOrigine(StrEnum):
    imprime = "imprime"
    reconstruit = "reconstruit"


# --- Dossier, liens (§6.2.7, §6.2.8) -----------------------------------------------------------


class RoleLien(StrEnum):
    facture_commerciale = "facture_commerciale"
    declaration = "declaration"
    facture_transitaire = "facture_transitaire"
    avoir = "avoir"
    support = "support"


class ForceLien(StrEnum):
    forte = "forte"
    moyenne = "moyenne"
    faible = "faible"
    manuelle = "manuelle"

    @property
    def est_solide(self) -> bool:
        """Condition 5 de §8.5.1."""
        return self in (ForceLien.forte, ForceLien.manuelle)


class SignalLien(StrEnum):
    mrn_cite = "mrn_cite"
    ref_facture_citee = "ref_facture_citee"
    ref_transport = "ref_transport"
    montant_egal = "montant_egal"
    meme_dossier_source = "meme_dossier_source"
    meme_fichier_source = "meme_fichier_source"
    tva = "tva"
    codes_communs = "codes_communs"
    nom_fichier = "nom_fichier"
    # Ajout (D-013) : le document graine du dossier (§7.5 étape 2) porte ce signal.
    graine = "graine"
    # Ajout (D-3702) : MRN, référence de transport ou numéro de facture du document retrouvé, à une lecture
    # imparfaite près, sur un document solidement rattaché au même dossier. Le lien reste au plus « moyenne ».
    reference_proche = "reference_proche"


class MethodeAllocation(StrEnum):
    totalite = "totalite"
    reference_explicite = "reference_explicite"
    ligne_par_mrn = "ligne_par_mrn"
    prorata = "prorata"
    manuelle = "manuelle"


# --- Référentiels client (§6.2.1–6.2.4) --------------------------------------------------------


class Offre(StrEnum):
    diagnostic = "diagnostic"
    continu = "continu"


class StatutGrille(StrEnum):
    brouillon = "brouillon"
    validee = "validee"


class ModePoste(StrEnum):
    forfait = "forfait"
    unitaire = "unitaire"
    pourcentage = "pourcentage"
    par_jour = "par_jour"


class BasePourcentage(StrEnum):
    debours_total = "debours_total"
    debours_hors_tva = "debours_hors_tva"
    droits = "droits"
    droits_et_autres_taxes = "droits_et_autres_taxes"
    tva = "tva"
    valeur_marchandise = "valeur_marchandise"
    autre = "autre"


class PrestationsHorsGrille(StrEnum):
    interdites = "interdites"
    tolerees = "tolerees"


class CanalLot(StrEnum):
    depot = "depot"
    courriel = "courriel"
    api = "api"


class StatutLot(StrEnum):
    recu = "recu"
    en_cours = "en_cours"
    traite = "traite"
    en_erreur = "en_erreur"


class StatutFichier(StrEnum):
    ok = "ok"
    refuse = "refuse"


class RoleAuteur(StrEnum):
    fondateur = "fondateur"
    utilisateur_client = "utilisateur_client"
    systeme = "systeme"


# --- Recouvrement (§17) ------------------------------------------------------------------------


class StatutEcart(StrEnum):
    ouvert = "ouvert"
    reclame = "reclame"
    partiellement_credite = "partiellement_credite"
    credite = "credite"
    conteste = "conteste"
    abandonne = "abandonne"
