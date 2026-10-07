"""Module de prospection du fondateur (D-5001 à D-5012) : exclusion, opposition, score, modèles, import CSV,
recherche (double, aucun réseau), séquences (horloge simulée), envoi, désinscription, purge, droits.
Sociétés FICTIVES, sauf l'analyse en lecture seule du fichier réel ``commercial/prospects.csv``."""

from __future__ import annotations

import ast
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from controldone.auth.roles import Acteur, Role
from controldone.outbox import FileSortante, StatutAction
from controldone.prospection import contacts as adr
from controldone.prospection import gabarits, jetons
from controldone.prospection.config import charger_config
from controldone.prospection.envoi import (
    ExpediteurDeclaration,
    ExpediteurSmtp,
    construire_message,
    expediteur_configure,
)
from controldone.prospection.exclusion import chercher_exclusion, normaliser_nom, textes_a_verifier
from controldone.prospection.import_csv import analyser_csv, siren_valide
from controldone.prospection.recherche import (
    CandidatEntreprise,
    ClientRechercheEntreprises,
    CriteresRecherche,
    RechercheIndisponible,
    ResultatRecherche,
)
from controldone.prospection.scoring import FaitsScore, calculer_score
from controldone.prospection.service import RefusProspection, ServiceProspection
from controldone.prospection.statuts import tranche_depuis_libelle
from controldone.storage.erreurs import AccesRefuse

RACINE = Path(__file__).resolve().parents[2]
F = Acteur("usr_fondateur_tests", Role.fondateur)
CLIENT = Acteur("usr_client", Role.client_admin, "cli_a")
T0 = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)  # lundi
SECRETS = [b"s" * 32]
IDENTITE = gabarits.IdentiteExpediteur(
    nom="Prénom Nom FICTIF",
    fonction="fondateur de ControlDOne",
    entreprise="Prénom Nom FICTIF (EI)",
    siren="123456782",
    adresse="1 rue Fictive, 75001 Paris",
)
SIREN_A = "732829320"  # clé de Luhn valide (numéro fabriqué pour les tests)


class Horloge:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture
def config():
    return charger_config()


@pytest.fixture
def horloge(monkeypatch):
    """Horloge simulée, partagée avec la file de validation (dates d'envoi des actions)."""
    h = Horloge(T0)
    monkeypatch.setattr("controldone.outbox.service.maintenant", h)
    return h


@pytest.fixture
def svc(db, config, horloge):
    return ServiceProspection(
        db,
        config=config,
        horloge=horloge,
        identite=IDENTITE,
        secrets_jetons=SECRETS,
        url_publique="https://controldone.test",
    )


def _prospect(svc, **k):
    champs = {
        "raison_sociale": "IMPORT ASIE FICTIF SAS",
        "source_url": "https://import-asie-fictif.test/mentions",
        "naf": "46.49Z",
        "tranche_effectif": "21",
        "departement": "69",
        "preuve_import": "« Nous importons directement de Chine » (FICTIF)",
        "preuve_url": "https://import-asie-fictif.test/qui",
        "sans_service_douane": "oui",
        **k,
    }
    domaine = (
        "import-asie-fictif"
        if "raison_sociale" not in k
        else re.sub(r"[^a-z]+", "-", k["raison_sociale"].lower())
    )
    contact = {
        "adresse": f"contact@{domaine.strip('-')}.test",
        "source_url": f"https://{domaine.strip('-')}.test/c",
    }
    return svc.creer(F, champs, contact)


def _contact(svc, pid):
    return svc.fiche(F, pid)["contacts"][0].id


def _qualifie(svc, **k):
    pid = _prospect(svc, **k)
    svc.changer_statut(F, pid, "qualifie")
    return pid, _contact(svc, pid)


# --- exclusion ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texte",
    [
        "L'OCCITANE EN PROVENCE",
        "loccitane.com",
        "Chanel SAS",
        "ERES PARIS",
        "Maison Michel",
        "HOLLAND & HOLLAND",
        "https://www.soldejaneiro.com",
        "chanel-beaute.fr",
    ],
)
def test_exclusion_detecte_les_groupes(config, texte):
    assert chercher_exclusion(textes_a_verifier(raison_sociale=texte), config) is not None


@pytest.mark.parametrize(
    "texte", ["FERESTIERE IMPORT", "BARRIERE LOGISTIQUE", "LES ATELIERS DU SUD", "Massarotti"]
)
def test_exclusion_mot_entier_pour_les_motifs_courts(config, texte):
    # mots entiers : « eres », « barrie », « massaro » ne bloquent pas un nom qui les contient
    assert chercher_exclusion(textes_a_verifier(raison_sociale=texte), config) is None


def test_exclusion_par_domaine_d_adresse_et_dirigeant(config):
    assert chercher_exclusion(textes_a_verifier(adresses=["achats@chanel.com"]), config) is not None
    assert (
        chercher_exclusion(textes_a_verifier(site_web="https://www.melvita.fr/contact"), config) is not None
    )
    assert chercher_exclusion(textes_a_verifier(dirigeants=["PARAFFECTION SAS"]), config) is not None
    # une note libre qui cite la consigne ne bloque rien (seuls noms, enseignes, groupes et domaines comptent)
    assert textes_a_verifier(raison_sociale="X") == ["X"]


def test_configuration_sans_liste_d_exclusion_refusee(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("plafonds: {}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        charger_config(p)


def test_creer_un_prospect_exclu_refuse(svc):
    with pytest.raises(RefusProspection):
        svc.creer(F, {"raison_sociale": "ERBORIAN FRANCE", "source_url": "https://x-fictif.test"})
    with pytest.raises(RefusProspection):
        svc.creer(
            F,
            {"raison_sociale": "NEUTRE FICTIF", "source_url": "https://x-fictif.test"},
            {"adresse": "a@chanel.com", "source_url": "https://x-fictif.test/c"},
        )
    assert svc.liste(F) == []


# --- adresses ----------------------------------------------------------------------------------------------------


def test_nature_des_adresses():
    assert adr.nature_adresse("contact@x.fr") == "generique"
    assert adr.nature_adresse("Info-2@x.fr") == "generique"
    assert adr.nature_adresse("jean.dupont@x.fr") == "nominative"
    assert adr.nature_adresse("jd@x.fr") == "nominative"  # boîte inconnue : supposée nominative
    assert adr.empreinte("Contact@X.fr ") == adr.empreinte("contact@x.fr")
    assert adr.extraire_adresses("écrire à contact@x.fr ou info@x.fr.") == ["contact@x.fr", "info@x.fr"]
    assert not adr.url_valide("https://user:mdp@x.fr") and not adr.url_valide("ftp://x.fr")


def test_contact_sans_source_refuse(svc):
    pid = _prospect(svc)
    with pytest.raises(RefusProspection):
        svc.ajouter_contact(F, pid, adresse="info@import-asie-fictif.test", source_url="")
    with pytest.raises(RefusProspection):
        svc.ajouter_contact(F, pid, adresse="pas-une-adresse", source_url="https://x-fictif.test")
    with pytest.raises(RefusProspection):
        svc.ajouter_contact(F, pid, source_url="https://x-fictif.test")  # ni adresse ni formulaire


# --- score -------------------------------------------------------------------------------------------------------


def test_score_deterministe_et_explique(config):
    f = FaitsScore(
        naf="46.49Z",
        tranche_effectif="21",
        preuve_import="« importateur »",
        preuve_url="https://x-fictif.test/p",
        sans_service_douane="oui",
        natures_contacts=("generique",),
        departement="13",
    )
    s = calculer_score(f, config)
    assert s.total == 100 and [x.points for x in s.lignes] == [25, 20, 25, 10, 15, 5]
    assert calculer_score(f, config) == s  # même entrée, même score
    vide = calculer_score(FaitsScore(), config)
    assert vide.total == 0 and {x.code for x in vide.lignes} >= {"naf_inconnu", "taille_inconnue"}
    interne = calculer_score(
        FaitsScore(naf="47.11B", tranche_effectif="32", sans_service_douane="non"), config
    )
    assert [x.points for x in interne.lignes][:4] == [8, 5, 0, -10] and interne.total == 3
    sans_url = calculer_score(FaitsScore(preuve_import="« x »", natures_contacts=("formulaire",)), config)
    assert sans_url.lignes[2].code == "preuve_sans_source" and sans_url.lignes[4].points == 5
    assert calculer_score(FaitsScore(naf="46.11Z", natures_contacts=("nominative",)), config).total == 25


def test_score_recalcule_quand_les_faits_changent(svc):
    pid = _prospect(svc, preuve_import=None, preuve_url=None)
    avant = svc.fiche(F, pid)["p"].score
    svc.modifier(F, pid, {"preuve_import": "« Nous importons »", "preuve_url": "https://x-fictif.test/p"})
    assert svc.fiche(F, pid)["p"].score == avant + 25


def test_tranches_depuis_libelles():
    assert tranche_depuis_libelle("10-19 (2023)") == "11"
    assert tranche_depuis_libelle("50-99") == "21"
    assert tranche_depuis_libelle("22") == "22"
    assert tranche_depuis_libelle("beaucoup") is None


# --- modèles et faits manquants ----------------------------------------------------------------------------------


def test_rendu_sans_fait_ne_fabrique_rien():
    etape = {"objet": "Pour {raison_sociale}", "corps": "Bonjour,\n{accroche}\n{ville}\n{expediteur}"}
    vide = gabarits.IdentiteExpediteur(nom=None, fonction="f", entreprise=None, siren=None, adresse=None)
    r = gabarits.rendre(
        etape, {"raison_sociale": "X FICTIF"}, vide, source_adresse=None, lien_desinscription=None
    )
    assert not r.complet
    assert set(r.manquants) >= {"accroche", "ville", "expediteur", "expediteur_siren", "source_adresse"}
    assert "[à compléter : accroche]" in r.corps and "[à compléter : ville]" in r.corps
    r2 = gabarits.rendre(
        etape,
        {"raison_sociale": "X", "accroche": "Sur votre site…", "ville": "Lyon"},
        IDENTITE,
        source_adresse="la page x.test/contact",
        lien_desinscription="https://c.test/desinscription/j",
    )
    assert (
        r2.complet
        and "STOP" in r2.corps
        and "SIREN 123456782" in r2.corps
        and "https://c.test/desinscription/j" in r2.corps
    )


def test_accroche_seulement_citation_avec_source():
    assert gabarits.accroche_depuis_preuve("« Nous importons de Chine »", "https://x.test/p") == (
        "Sur votre site, j'ai lu : « Nous importons de Chine »."
    )
    assert gabarits.accroche_depuis_preuve("« Nous importons »", None) is None  # pas de page source
    assert gabarits.accroche_depuis_preuve("Se présente comme importateur", "https://x.test/p") is None
    long = gabarits.accroche_depuis_preuve("« " + "mot " * 200 + "»", "https://x.test/p")
    assert long is not None and long.endswith("[…] ».") and len(long) < 400


def test_sequence_par_defaut_valide_et_sans_tiret_long():
    erreurs = gabarits.valider_etapes(gabarits.SEQUENCE_DEFAUT["etapes"])
    assert erreurs == []
    for e in gabarits.SEQUENCE_DEFAUT["etapes"]:
        assert "—" not in e["corps"] and "–" not in e["corps"]
    assert [e["delai_jours"] for e in gabarits.SEQUENCE_DEFAUT["etapes"]] == [0, 4, 10, 20]


def test_validation_des_etapes():
    base = {"rang": 1, "delai_jours": 0, "objet": "o", "corps": "c"}
    assert gabarits.valider_etapes([]) != []
    assert gabarits.valider_etapes([{**base, "corps": "{inconnue}"}])[0][0].startswith(
        "Étape {rang} : variable"
    )
    deux_liens = {**base, "corps": "https://a.test et https://b.test"}
    assert any("lien" in e[0] for e in gabarits.valider_etapes([deux_liens]))
    assert gabarits.valider_etapes([{**base, "delai_jours": 3}]) != []
    assert gabarits.valider_etapes([base, {**base, "rang": 2, "delai_jours": 0}]) != []
    assert any(
        "garde-fous" in e[0] for e in gabarits.valider_etapes([{**base, "corps": "nous garantissons"}])
    )


def test_modifier_sequence(svc):
    q = svc.sequences(F)[0]
    with pytest.raises(RefusProspection):
        svc.modifier_sequence(F, q.id, "Nom", [{"rang": 1, "delai_jours": 0, "objet": "", "corps": ""}])
    svc.modifier_sequence(
        F, q.id, "Courte", [{"rang": 1, "delai_jours": 0, "objet": "O", "corps": "Bonjour"}]
    )
    assert svc.sequences(F)[0].nom == "Courte" and len(svc.sequences(F)[0].etapes) == 1


# --- import CSV --------------------------------------------------------------------------------------------------


def test_siren_luhn():
    assert siren_valide(SIREN_A) and not siren_valide("732829321") and not siren_valide("12345678")


def test_import_du_fichier_reel_en_lecture_seule(config):
    contenu = (RACINE / "commercial" / "prospects.csv").read_bytes()
    lignes = analyser_csv(contenu, config, existant=lambda s, n: None, aujourdhui=date(2026, 10, 7))
    assert len(lignes) == 26 and all(x.statut == "nouveau" for x in lignes)
    # la colonne exclusion_verifiee cite la consigne : elle n'est pas comparée à la liste
    sealyos = next(x for x in lignes if "SEALYOS" in x.raison_sociale)
    assert sealyos.champs["tranche_effectif"] == "11" and sealyos.champs["departement"] == "17"
    assert [c.adresse for c in sealyos.contacts] == ["contact@sealyos.fr"]
    assert sealyos.contacts[0].source_url == "https://sealyos.fr/contact/"
    assert sealyos.champs["collecte_le"] == date(2026, 10, 2)
    sandy = next(x for x in lignes if x.raison_sociale == "SANDY")
    assert sandy.contacts and sandy.contacts[0].genre == "formulaire"


CSV = (
    "raison_sociale;siren;naf;effectif_tranche;ville;site_web;preuve_import;contact_publie;source_contact;"
    "exclusion_verifiee;date_collecte\n"
    f"ALPHA FICTIF;{SIREN_A};46.49Z;10-19 (2023);Lyon (69);https://alpha-fictif.test;"
    "« importateur » — https://alpha-fictif.test/a;contact@alpha-fictif.test;https://alpha-fictif.test/c;oui;2026-09-01\n"
    "ALPHA FICTIF SAS;;46.49Z;;;https://alpha2-fictif.test;;;;;\n"
    "MELVITA DISTRIBUTION;;46.45Z;;;https://m-fictif.test;;;;;\n"
    "BETA FICTIF;12345;46.49Z;;;https://beta-fictif.test;;;;;\n"
    "GAMMA FICTIF;;46.49Z;;;;;info@gamma-fictif.test;;;\n"
    "DELTA FICTIF;;46.49Z;;;https://delta-fictif.test;;;;NON — groupe exclu;\n"
    ";;;;;;;;;;\n"
)


def test_import_apercu_puis_import(svc):
    lignes = svc.analyser_import(F, CSV.encode())
    statuts = {x.raison_sociale: (x.statut, x.motif) for x in lignes}
    assert statuts["ALPHA FICTIF"] == ("nouveau", None)
    assert statuts["ALPHA FICTIF SAS"] == ("doublon", "fichier")  # même nom normalisé
    assert statuts["MELVITA DISTRIBUTION"] == ("exclu", "liste_exclusion")
    assert statuts["BETA FICTIF"] == ("invalide", "siren")
    assert statuts["GAMMA FICTIF"] == ("invalide", "source")  # aucune page source
    assert statuts["DELTA FICTIF"] == ("exclu", "verification_non")
    assert statuts[""] == ("invalide", "raison_sociale")
    assert svc.liste(F) == []  # l'aperçu n'écrit rien
    r = svc.importer(F, CSV.encode(), "essai.csv")
    assert (r.crees, r.doublons, r.exclus, r.invalides, r.contacts) == (1, 1, 2, 3, 1)
    p = svc.liste(F)[0]["p"]
    assert p.source == "import_csv" and p.collecte_le == date(2026, 9, 1) and "essai.csv" in p.source_detail
    assert p.preuve_url == "https://alpha-fictif.test/a"
    # réimport : doublon par la base
    assert svc.importer(F, CSV.encode(), "essai.csv").crees == 0
    with pytest.raises(RefusProspection):
        svc.analyser_import(F, b"\xff\xfe")
    with pytest.raises(RefusProspection):
        svc.analyser_import(F, b"nom;ville\nx;y\n")


def test_import_journalise(svc, db):
    svc.importer(F, CSV.encode(), "essai.csv")
    with db.operateur(F) as op:
        actions = [e.action for e in op.journal()]
    assert "prospection_importer" in actions and "prospection_creer" not in actions


# --- recherche (double, aucun réseau) ----------------------------------------------------------------------------


class SourceFictive:
    def __init__(self, candidats):
        self.candidats = candidats
        self.appels: list[CriteresRecherche] = []

    def rechercher(self, criteres):
        self.appels.append(criteres)
        if criteres.mots and criteres.mots.isdigit():
            return ResultatRecherche([c for c in self.candidats if c.siren == criteres.mots], 1, 1)
        return ResultatRecherche(list(self.candidats), len(self.candidats), 1)


def _cand(siren, nom, **k):
    return CandidatEntreprise(
        siren,
        nom,
        k.get("naf", "46.49Z"),
        k.get("tranche", "21"),
        "2023",
        "Lyon",
        "69",
        **{x: k[x] for x in ("enseignes", "dirigeants_personnes_morales") if x in k},
    )


def test_recherche_retire_les_exclus_et_n_ajoute_rien(svc):
    source = SourceFictive(
        [
            _cand(SIREN_A, "OMEGA FICTIF"),
            _cand("552100554", "LESAGE INTERIEURS"),
            _cand("443061841", "NEUTRE FICTIF", dirigeants_personnes_morales=("CHANEL SAS",)),
            _cand("130025265", "ENSEIGNE FICTIF", enseignes=("MELVITA",)),
        ]
    )
    candidats, exclus, _res = svc.rechercher(F, source, CriteresRecherche(mots="import"))
    assert [c.entreprise.raison_sociale for c in candidats] == ["OMEGA FICTIF"] and exclus == 3
    assert svc.liste(F) == []  # jamais ajouté d'office
    pid = svc.ajouter_candidat(F, source, SIREN_A)
    p = svc.fiche(F, pid)["p"]
    assert p.source == "recherche" and p.source_url.endswith(SIREN_A) and p.statut == "a_qualifier"
    assert source.appels[-1].mots == SIREN_A  # données relues dans la source, pas prises du formulaire
    with pytest.raises(RefusProspection):
        svc.ajouter_candidat(F, source, "552100554")  # exclu
    with pytest.raises(RefusProspection):
        svc.ajouter_candidat(F, source, "123")
    with pytest.raises(RefusProspection):
        svc.ajouter_candidat(F, source, SIREN_A)  # déjà présent
    candidats, _e, _r = svc.rechercher(F, source, CriteresRecherche(mots="import"))
    assert candidats[0].deja == pid


def test_client_http_reessaie_sur_429_puis_echoue_proprement():
    reponses = [
        (429, {"Retry-After": "3"}, b""),
        (
            200,
            {},
            b'{"results": [{"siren": "732829320", "nom_complet": "X FICTIF", "siege": {}}], "total_results": 1}',
        ),
    ]
    attentes: list[float] = []
    urls: list[str] = []

    def transport(url, delai):
        urls.append(url)
        return reponses.pop(0)

    c = ClientRechercheEntreprises(transport=transport, dormir=attentes.append, pause_s=0)
    res = c.rechercher(CriteresRecherche(naf=("46.49Z",), tranches=("21",), departement="69"))
    assert [x.siren for x in res.candidats] == ["732829320"] and attentes and attentes[0] >= 3
    assert "activite_principale=46.49Z" in urls[0] and "etat_administratif=A" in urls[0]
    toujours = ClientRechercheEntreprises(
        transport=lambda u, d: (429, {}, b""), dormir=lambda s: None, pause_s=0, essais=2
    )
    with pytest.raises(RechercheIndisponible):
        toujours.rechercher(CriteresRecherche(mots="x"))
    illisible = ClientRechercheEntreprises(transport=lambda u, d: (200, {}, b"<html>"), dormir=lambda s: None)
    with pytest.raises(RechercheIndisponible):
        illisible.rechercher(CriteresRecherche(mots="x"))

    def panne(u, d):
        raise OSError("réseau")

    with pytest.raises(RechercheIndisponible):
        ClientRechercheEntreprises(transport=panne, dormir=lambda s: None).rechercher(
            CriteresRecherche(mots="x")
        )


# --- séquences, plafonds, arrêt (horloge simulée) ----------------------------------------------------------------


def _approuver_envoyer(svc, db, action_id, quand):
    fs = FileSortante(db)
    fs.approuver(action_id, F)
    svc.horloge.t = quand
    return svc.envoyer(F, action_id, ExpediteurDeclaration(F.id), declaration=True)


def test_preparer_sequence_exige_qualification_et_faits(svc):
    pid = _prospect(svc)
    cid = _contact(svc, pid)
    q = svc.sequences(F)[0]
    with pytest.raises(RefusProspection, match="Qualifiez"):
        svc.preparer_sequence(F, pid, cid, q.id)
    svc.changer_statut(F, pid, "qualifie")
    sans_nom = ServiceProspection(
        svc.db,
        config=svc.config,
        horloge=svc.horloge,
        identite=gabarits.IdentiteExpediteur(None, "f", None, None, None),
        secrets_jetons=SECRETS,
    )
    with pytest.raises(RefusProspection, match="Faits manquants"):
        sans_nom.preparer_sequence(F, pid, cid, q.id)
    assert FileSortante(svc.db).lister(F, kind="email_prospection") == []


def test_sequence_complete_avec_horloge_simulee(svc, db, horloge):
    pid, cid = _qualifie(svc)
    q = svc.sequences(F)[0]
    a1 = svc.preparer_sequence(F, pid, cid, q.id)
    action = FileSortante(db).obtenir(a1, F)
    assert action.statut is StatutAction.brouillon  # rien ne part sans validation
    p = action.payload
    assert p["destinataires"] == ["contact@import-asie-fictif.test"] and p["rang"] == 1
    assert "STOP" in p["corps"] and "https://controldone.test/desinscription/" in p["corps"]
    assert "Sur votre site, j'ai lu : « Nous importons directement de Chine »" in p["corps"]
    with pytest.raises(RefusProspection):
        svc.preparer_sequence(F, pid, cid, q.id)  # déjà en cours
    # aucune étape suivante tant que l'étape 1 n'est pas envoyée
    horloge.t = T0 + timedelta(days=30)
    assert svc.preparer_etapes_dues(Acteur.systeme("agent:prospection")) == []
    _approuver_envoyer(svc, db, a1, T0 + timedelta(hours=2))
    assert svc.fiche(F, pid)["p"].statut == "contacte"
    horloge.t = T0 + timedelta(days=3)
    assert svc.preparer_etapes_dues(F) == []  # J+4 pas encore échu
    horloge.t = T0 + timedelta(days=4, hours=3)
    ids = svc.preparer_etapes_dues(Acteur.systeme("agent:prospection"))
    assert len(ids) == 1 and FileSortante(db).obtenir(ids[0], F).payload["rang"] == 2
    assert svc.preparer_etapes_dues(F) == []  # idempotent : étape 2 en attente de validation
    _approuver_envoyer(svc, db, ids[0], T0 + timedelta(days=4, hours=4))
    horloge.t = T0 + timedelta(days=10, hours=3)
    (a3,) = svc.preparer_etapes_dues(F)
    # une réponse arrête la séquence : plus aucune étape préparée
    svc.enregistrer_reponse(F, pid, "Merci, rappelez-moi. <script>alert(1)</script>")
    d = svc.fiche(F, pid)
    assert d["p"].statut == "a_repondu" and d["active"] is None
    assert d["inscriptions"][0].motif_arret == "reponse"
    assert any(e.texte and "<script>" in e.texte for e in d["evenements"])  # conservé tel quel (donnée)
    horloge.t = T0 + timedelta(days=40)
    assert svc.preparer_etapes_dues(F) == []
    stats = svc.statistiques(F)["sequences"][0]
    assert stats["inscrits"] == 1
    assert stats["etapes"][1]["envoyes"] == 1 and stats["etapes"][2]["envoyes"] == 1
    assert stats["etapes"][3]["prepares"] == 1 and stats["etapes"][3]["envoyes"] == 0
    assert stats["etapes"][2]["reponses"] == 1  # réponse rattachée à la dernière étape envoyée
    t = svc.tableau(F)
    assert dict(t["par_statut"])["a_repondu"] == 1 and t["segments"][0]["taux"] == 100
    assert len(t["a_valider"]) == 1 and FileSortante(db).obtenir(a3, F).statut is StatutAction.brouillon


def test_sequence_arretee_si_brouillon_refuse_ou_changement_de_statut(svc, db, horloge):
    pid, cid = _qualifie(svc)
    q = svc.sequences(F)[0]
    a1 = svc.preparer_sequence(F, pid, cid, q.id)
    FileSortante(db).refuser(a1, F, "pas maintenant")
    assert svc.preparer_etapes_dues(F) == []
    assert svc.fiche(F, pid)["inscriptions"][0].motif_arret == "refus"
    pid2, cid2 = _qualifie(svc, raison_sociale="AUTRE FICTIF", siren=None)
    svc.preparer_sequence(F, pid2, cid2, q.id)
    svc.changer_statut(F, pid2, "perdu")
    assert svc.fiche(F, pid2)["inscriptions"][0].motif_arret == "statut"


def test_sequence_terminee_apres_la_derniere_etape(svc, db, horloge):
    q = svc.sequences(F)[0]
    svc.modifier_sequence(
        F, q.id, "Une étape", [{"rang": 1, "delai_jours": 0, "objet": "O", "corps": "Bonjour"}]
    )
    pid, cid = _qualifie(svc)
    a1 = svc.preparer_sequence(F, pid, cid, q.id)
    _approuver_envoyer(svc, db, a1, T0 + timedelta(hours=1))
    assert svc.preparer_etapes_dues(F) == []
    assert svc.fiche(F, pid)["inscriptions"][0].statut == "terminee"


def test_plafond_quotidien_de_preparation(svc, config, db):
    from dataclasses import replace

    svc._config = replace(config, preparations_par_jour=1)
    q = svc.sequences(F)[0]
    pid, cid = _qualifie(svc)
    svc.preparer_sequence(F, pid, cid, q.id)
    pid2, cid2 = _qualifie(svc, raison_sociale="SECOND FICTIF", siren=None)
    with pytest.raises(RefusProspection, match="Plafond"):
        svc.preparer_sequence(F, pid2, cid2, q.id)
    assert svc.fiche(F, pid2)["active"] is None  # aucune inscription fantôme
    svc.horloge.t = T0 + timedelta(days=1)
    svc.preparer_sequence(F, pid2, cid2, q.id)


def test_plafond_quotidien_d_envoi(svc, config, db):
    from dataclasses import replace

    q = svc.sequences(F)[0]
    pid, cid = _qualifie(svc)
    pid2, cid2 = _qualifie(svc, raison_sociale="SECOND FICTIF", siren=None)
    a1 = svc.preparer_sequence(F, pid, cid, q.id)
    a2 = svc.preparer_sequence(F, pid2, cid2, q.id)
    svc._config = replace(config, envois_par_jour=1)
    _approuver_envoyer(svc, db, a1, T0 + timedelta(hours=1))
    FileSortante(db).approuver(a2, F)
    with pytest.raises(RefusProspection, match="Plafond"):
        svc.envoyer(F, a2, ExpediteurDeclaration(F.id), declaration=True)
    assert FileSortante(db).obtenir(a2, F).statut is StatutAction.approuve


# --- opposition (suppression) ------------------------------------------------------------------------------------


def test_opposition_bloque_la_mise_en_file_et_l_envoi(svc, db):
    pid, cid = _qualifie(svc)
    q = svc.sequences(F)[0]
    a1 = svc.preparer_sequence(F, pid, cid, q.id)
    FileSortante(db).approuver(a1, F)
    assert svc.ajouter_opposition(F, "CONTACT@import-asie-fictif.test", "plainte") is True
    assert svc.ajouter_opposition(F, "contact@import-asie-fictif.test", "plainte") is False  # idempotent
    assert "opposition" in svc.blocages_envoi(FileSortante(db).obtenir(a1, F))
    with pytest.raises(RefusProspection, match="opposition"):
        svc.envoyer(F, a1, ExpediteurDeclaration(F.id), declaration=True)
    assert FileSortante(db).obtenir(a1, F).statut is StatutAction.approuve  # rien ne part
    pid2, _cid2 = _qualifie(svc, raison_sociale="AUTRE FICTIF", siren=None)
    svc.ajouter_contact(
        F, pid2, adresse="contact@import-asie-fictif.test", source_url="https://x-fictif.test/c"
    )
    contact_oppose = next(c for c in svc.fiche(F, pid2)["contacts"] if c.oppose)
    with pytest.raises(RefusProspection, match="opposition"):
        svc.preparer_sequence(F, pid2, contact_oppose.id, q.id)
    # la liste ne garde que l'empreinte, jamais l'adresse en clair
    liste = svc.suppressions(F)
    assert len(liste) == 1 and liste[0]["s"].empreinte == adr.empreinte("contact@import-asie-fictif.test")
    assert not hasattr(liste[0]["s"], "adresse")


def test_stop_recu_et_rebond(svc, db):
    pid, cid = _qualifie(svc)
    svc.opposer_contact(F, cid)
    d = svc.fiche(F, pid)
    assert d["p"].statut == "ne_plus_contacter" and d["contacts"][0].oppose
    pid2, cid2 = _qualifie(svc, raison_sociale="REBOND FICTIF", siren=None)
    svc.ajouter_contact(F, pid2, adresse="ventes@rebond-fictif.test", source_url="https://x-fictif.test/c")
    q = svc.sequences(F)[0]
    svc.preparer_sequence(F, pid2, cid2, q.id)
    svc.enregistrer_rebond(F, cid2)
    assert svc.fiche(F, pid2)["inscriptions"][0].motif_arret == "rebond"
    with pytest.raises(AccesRefuse):
        svc.enregistrer_rebond(F, "inexistant")
    with pytest.raises(RefusProspection):
        svc.opposer_contact(F, cid2, "nimporte")


def test_ne_plus_contacter_ajoute_les_adresses(svc):
    pid, _cid = _qualifie(svc)
    svc.changer_statut(F, pid, "ne_plus_contacter")
    assert len(svc.suppressions(F)) == 1


# --- consentement (Suisse, Belgique), pays bloqués ---------------------------------------------------------------


def test_adresse_nominative_suisse_exige_une_base_legale(svc):
    pid = svc.creer(
        F,
        {
            "raison_sociale": "HORLOGES FICTIF SA",
            "source_url": "https://horloges-fictif.test",
            "pays": "CH",
            "preuve_import": "« importateur »",
            "preuve_url": "https://horloges-fictif.test/p",
        },
        {"adresse": "anne.martin@horloges-fictif.test", "source_url": "https://horloges-fictif.test/equipe"},
    )
    svc.changer_statut(F, pid, "qualifie")
    cid = _contact(svc, pid)
    q = svc.sequences(F)[0]
    assert "consentement" in svc.fiche(F, pid)["contacts"][0].blocages
    with pytest.raises(RefusProspection, match="consentement"):
        svc.preparer_sequence(F, pid, cid, q.id)
    svc.modifier(F, pid, {"base_legale": "Consentement écrit reçu le 2026-10-01 (FICTIF)"})
    assert svc.preparer_sequence(F, pid, cid, q.id)
    # une adresse générique suisse n'exige pas de base légale
    pid2 = svc.creer(
        F,
        {"raison_sociale": "MONTRES FICTIF SA", "source_url": "https://montres-fictif.test", "pays": "CH"},
        {"adresse": "info@montres-fictif.test", "source_url": "https://montres-fictif.test/c"},
    )
    svc.changer_statut(F, pid2, "qualifie")
    assert "consentement" not in svc.fiche(F, pid2)["contacts"][0].blocages


def test_pays_bloque_refuse(svc):
    with pytest.raises(RefusProspection):
        svc.creer(F, {"raison_sociale": "LUX FICTIF", "source_url": "https://lux-fictif.test", "pays": "LU"})


def test_prospect_devenu_exclu_par_modification(svc):
    pid, _cid = _qualifie(svc)
    svc.modifier(F, pid, {"groupe": "Groupe Chanel"})
    d = svc.fiche(F, pid)
    assert d["exclu"] and d["p"].statut == "ne_plus_contacter"
    with pytest.raises(RefusProspection):
        svc.changer_statut(F, pid, "qualifie")


# --- envoi : jamais de faux envoi ---------------------------------------------------------------------------------


def test_aucun_expediteur_hors_production_ou_sans_configuration():
    env = {
        "CONTROLDONE_PROSPECTION_SMTP_HOTE": "smtp.fictif.test",
        "CONTROLDONE_PROSPECTION_COURRIEL_DE": "moi@fictif.test",
    }
    assert expediteur_configure(env, mode="dev") is None
    assert expediteur_configure({}, mode="prod") is None
    assert (
        expediteur_configure({**env, "CONTROLDONE_PROSPECTION_SMTP_SECURITE": "aucune"}, mode="prod") is None
    )
    assert expediteur_configure({**env, "CONTROLDONE_PROSPECTION_SMTP_PORT": "x"}, mode="prod") is None
    exp = expediteur_configure(env, mode="prod")
    assert isinstance(exp, ExpediteurSmtp) and exp.port == 587


def test_envoi_smtp_par_l_interface_expediteur(svc, db):
    pid, cid = _qualifie(svc)
    a1 = svc.preparer_sequence(F, pid, cid, svc.sequences(F)[0].id)
    FileSortante(db).approuver(a1, F)
    envoyes = []

    class ServeurFictif:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, u, m):
            pass

        def send_message(self, msg):
            envoyes.append(msg)

    exp = ExpediteurSmtp("smtp.fictif.test", 587, "moi@fictif.test", utilisateur="u", fabrique=ServeurFictif)
    a = svc.envoyer(F, a1, exp)
    assert a.statut is StatutAction.envoye and a.reference_envoi.startswith("smtp:")
    msg = envoyes[0]
    assert msg["To"] == "contact@import-asie-fictif.test" and msg["List-Unsubscribe-Post"]
    assert msg["List-Unsubscribe"].startswith("<https://controldone.test/desinscription/")
    assert msg.get_content_type() == "text/plain" and "<img" not in msg.get_content()
    with pytest.raises(RefusProspection):
        svc.envoyer(F, a1, exp)  # déjà envoyé


def test_envoi_refuse_si_pied_retire_ou_fait_manquant(svc, db):
    pid, cid = _qualifie(svc)
    a1 = svc.preparer_sequence(F, pid, cid, svc.sequences(F)[0].id)
    fs = FileSortante(db)
    a = fs.obtenir(a1, F)
    fs.corriger(a1, F, {**a.payload, "corps": "Bonjour, texte sans pied [à compléter : ville]"})
    blocages = svc.blocages_envoi(fs.obtenir(a1, F))
    assert "pied_absent" in blocages and "faits_manquants" in blocages
    with pytest.raises(RefusProspection):
        svc.envoyer(F, a1, ExpediteurDeclaration(F.id), declaration=True)


def test_message_construit_en_texte_brut():
    from controldone.outbox.modele import ActionSortante, StatutAction, TypeAction

    a = ActionSortante(
        id="out_x",
        tenant_id=None,
        kind=TypeAction.email_prospection,
        statut=StatutAction.approuve,
        payload={"objet": "O", "corps": "C", "destinataires": ["a@x.test"]},
        cree_par="t",
        cree_le=T0,
    )
    msg = construire_message(a, "moi@x.test")
    assert msg["List-Unsubscribe"] is None and msg.get_content().strip() == "C"


# --- désinscription ----------------------------------------------------------------------------------------------


def test_jeton_de_desinscription():
    emp = adr.empreinte("contact@x.test")
    j = jetons.emettre(emp, SECRETS)
    assert jetons.verifier(j, SECRETS) == emp and "contact" not in j and len(j) < 80
    assert jetons.verifier(j, [b"autre" * 8, *SECRETS]) == emp  # rotation : ancien secret encore accepté
    for faux in ("", "a.b", j[:-2] + "AA", j.replace(".", ""), "x" * 200, j + ".x"):
        with pytest.raises(jetons.JetonInvalide):
            jetons.verifier(faux, SECRETS)
    with pytest.raises(jetons.JetonInvalide):
        jetons.verifier(j, [b"autre" * 8])
    with pytest.raises(ValueError):
        jetons.emettre("pas-une-empreinte", SECRETS)


def test_secret_de_l_environnement(monkeypatch):
    monkeypatch.setenv("CONTROLDONE_PROSPECTION_SECRET", "court")
    with pytest.raises(ValueError):
        jetons.secrets_depuis_env()
    monkeypatch.setenv("CONTROLDONE_PROSPECTION_SECRET", "x" * 40 + "," + "y" * 40)
    assert jetons.secrets_depuis_env() == [b"x" * 40, b"y" * 40]
    monkeypatch.delenv("CONTROLDONE_PROSPECTION_SECRET")
    assert len(jetons.secrets_depuis_env()[0]) == 32  # dérivé de la clé maîtresse


def test_desinscription_par_jeton(svc, db):
    pid, cid = _qualifie(svc)
    svc.preparer_sequence(F, pid, cid, svc.sequences(F)[0].id)
    j = jetons.emettre(adr.empreinte("contact@import-asie-fictif.test"), SECRETS)
    assert svc.desinscrire_par_jeton(j) is True
    assert svc.desinscrire_par_jeton(j) is False  # idempotent
    d = svc.fiche(F, pid)
    assert d["p"].statut == "ne_plus_contacter" and d["inscriptions"][0].motif_arret == "desinscription"
    with pytest.raises(jetons.JetonInvalide):
        svc.desinscrire_par_jeton("faux.jeton")
    with db.operateur(F) as op:
        e = [x for x in op.journal() if x.action == "prospection_opposition"]
    assert e and "contact@" not in str(e[0].details)  # aucune adresse en clair dans le journal


# --- conservation ------------------------------------------------------------------------------------------------


def test_purge_apres_trois_ans(svc, horloge):
    vieux = _prospect(svc, collecte_le=date(2023, 1, 1))
    recent = _prospect(svc, raison_sociale="RECENT FICTIF", siren=None)
    repondu = _prospect(svc, raison_sociale="REPONDU FICTIF", siren=None, collecte_le=date(2022, 1, 1))
    client = _prospect(svc, raison_sociale="CLIENT FICTIF", siren=None, collecte_le=date(2022, 1, 1))
    svc.changer_statut(F, client, "client")
    svc.enregistrer_reponse(F, repondu, None)  # contact émanant du prospect : le délai repart
    svc.opposer_contact(F, _contact(svc, vieux))
    assert [p.id for p in svc.a_purger(F)] == [vieux]
    assert svc.tableau(F)["a_purger"] == 1
    assert svc.purger(F) == 1
    ids = {x["p"].id for x in svc.liste(F)}
    assert vieux not in ids and {recent, repondu, client} <= ids
    assert len(svc.suppressions(F)) == 1  # la liste d'opposition survit à la purge


# --- droits ------------------------------------------------------------------------------------------------------


def test_reserve_au_fondateur(svc):
    pid = _prospect(svc)
    for appel in (
        lambda a: svc.liste(a),
        lambda a: svc.fiche(a, pid),
        lambda a: svc.changer_statut(a, pid, "qualifie"),
        lambda a: svc.tableau(a),
        lambda a: svc.importer(a, CSV.encode(), "x.csv"),
        lambda a: svc.creer(a, {"raison_sociale": "X", "source_url": "https://x.test"}),
        lambda a: svc.suppressions(a),
        lambda a: svc.purger(a),
        lambda a: svc.sequences(a),
        lambda a: svc.preparer_etapes_dues(a),
    ):
        with pytest.raises(AccesRefuse):
            appel(CLIENT)
    with pytest.raises(AccesRefuse):
        svc.liste(Acteur.systeme("agent:prospection"))  # l'agent ne lit pas les fiches
    with pytest.raises(AccesRefuse):
        svc.fiche(F, "prs_inexistant")


def test_tables_de_niveau_plateforme():
    from controldone.storage import models_prospection as mp
    from controldone.storage.models import TenantMixin

    for m in (mp.Prospect, mp.ContactProspect, mp.EvenementProspect, mp.SequenceProspection, mp.Suppression):
        assert not issubclass(m, TenantMixin)


def test_agent_de_prospection(db, monkeypatch):
    from controldone.agents import ContexteAgent, obtenir_agent

    r = obtenir_agent("prospection").executer(ContexteAgent(db=db, tenant_id=None))
    assert r.propositions == [] and r.notes == ["etapes_preparees:0"]
    with pytest.raises(ValueError):
        obtenir_agent("prospection").executer(ContexteAgent(db=db, tenant_id="cli_a"))


def test_messages_de_refus_traduits():
    from controldone.prospection import service as module_service
    from controldone.prospection.scoring import LIBELLES_SCORE
    from controldone.prospection.service import BLOCAGES, REFUS_CSV
    from controldone.prospection.statuts import (
        LIBELLES_ARRET,
        LIBELLES_EVENEMENT,
        LIBELLES_MOTIF_SUPPRESSION,
        LIBELLES_SOURCE,
        LIBELLES_STATUT,
    )
    from controldone.web.i18n_en import CATALOGUE_EN

    textes = set()
    for d in (
        LIBELLES_STATUT,
        LIBELLES_SOURCE,
        LIBELLES_EVENEMENT,
        LIBELLES_ARRET,
        LIBELLES_MOTIF_SUPPRESSION,
        LIBELLES_SCORE,
        BLOCAGES,
        REFUS_CSV,
    ):
        textes |= set(d.values())
    for f in (Path(module_service.__file__), Path(gabarits.__file__)):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            refus = isinstance(n, ast.Call) and getattr(n.func, "id", None) == "RefusProspection"
            if refus and n.args and isinstance(n.args[0], ast.Constant):
                textes.add(n.args[0].value)
            erreur_etape = isinstance(n, ast.Tuple) and len(n.elts) == 2 and isinstance(n.elts[1], ast.Dict)
            if erreur_etape and isinstance(n.elts[0], ast.Constant) and isinstance(n.elts[0].value, str):
                textes.add(n.elts[0].value)
    assert len(textes) > 80
    assert sorted(textes - set(CATALOGUE_EN)) == []


def test_normalisation_des_noms():
    assert normaliser_nom("Équip'Loisirs SAS") == normaliser_nom("EQUIP LOISIRS")
