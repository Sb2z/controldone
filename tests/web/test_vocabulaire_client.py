"""Vocabulaire de l'espace du client (revue du texte, octobre 2026) : un même montant porte le même nom au tableau de
bord, sur la page d'un dossier et au suivi des avoirs ; la légende d'un montant suit la nature du constat ; une
valeur lue est nommée selon son type (un code n'est pas un montant) ; l'envoi du courrier est dit sans changer de
personne ; les titres des rapports s'affichent sans tiret cadratin. Données fictives."""

from __future__ import annotations

import re
from dataclasses import replace

from aides_web import ADMIN_A, ADMIN_B, connecter_client, connecter_fondateur, poster
from test_revue_interface import CALCUL, EXTRAIT, _carte, _constat

from controldone.auth.roles import Acteur
from controldone.storage.models import Constat, Dossier
from controldone.web.i18n import COOKIE_LANGUE
from controldone.web.rendu import texte_visible
from controldone.web.routes_client import titre_affiche

A, B = "demo_ateliers", "demo_nord"
MONTANT = "Montant recouvrable certain"
ANCIENS = (
    "Écarts certains relevés",
    "Écarts suivis",
    "Écarts constatés",
    "Avoirs obtenus",
    "Sans avoir reçu",
)


def _dossier(monde, tenant: str, reference: str) -> str:
    with monde.pf.db.tenant(tenant, Acteur.systeme("t"), lecture=True) as s:
        return next(d.id for d in s.lister(Dossier) if d.reference == reference)


def _get(c, url: str) -> str:
    """Page HTML, espaces insécables des montants ramenées à des espaces simples."""
    return c.get(url).text.replace("\xa0", " ").replace("\u202f", " ")


def _kpi(html: str, libelle: str) -> str | None:
    m = re.search(rf'{re.escape(libelle)}</div><div class="kpi-val num">(?:<a [^>]*>)?([^<]*)<', html)
    return m.group(1) if m else None


# --- 1. un même montant, un même nom -------------------------------------------------------------------------------


def test_meme_nom_pour_le_montant_recouvrable_certain(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    tableau = _get(c, "/espace")
    suivi = _get(c, "/espace/recouvrement")
    dossier = _get(c, f"/espace/dossiers/{_dossier(monde, A, 'D-2026-00001')}")
    assert _kpi(tableau, MONTANT) == _kpi(suivi, MONTANT) == "2 386,28 EUR"
    assert re.search(rf"<dt>{MONTANT}</dt><dd>2 386,28 EUR</dd>", dossier)
    assert f'class="etiquette">{MONTANT}</h2>' in tableau  # bilan du tableau de bord
    assert _kpi(tableau, "Montant recouvrable à vérifier") == "0,00 EUR"
    assert _kpi(tableau, "Reste sans avoir") == _kpi(suivi, "Reste sans avoir") == "2 386,28 EUR"
    assert "Reste sans avoir : 2 386,28 EUR" in texte_visible(tableau)
    for html in (tableau, suivi, dossier):
        texte = texte_visible(html)
        assert not [x for x in ANCIENS if x in texte], [x for x in ANCIENS if x in texte]
    # en anglais : un seul nom aussi
    c.cookies.set(COOKIE_LANGUE, "en")
    en = "Confirmed recoverable amount"
    assert _kpi(_get(c, "/espace"), en) == _kpi(_get(c, "/espace/recouvrement"), en) == "2,386.28 EUR"


def test_part_a_confirmer_nommee_a_part_au_suivi(monde):
    """Un écart du suivi dont le constat publié est « à vérifier » : le total n'est plus « certain » ; il s'appelle
    « Montant recouvrable », avec la part à confirmer, au suivi comme sur la page du dossier. Le tableau de bord
    garde le montant recouvrable certain."""
    with monde.pf.db.tenant(A, Acteur.systeme("t")) as s:
        d3 = next(x for x in s.lister(Constat) if x.controle_id == "D3")
        d3.niveau = "a_verifier"
        dossier_id = d3.dossier_id
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    suivi = _get(c, "/espace/recouvrement")
    assert _kpi(suivi, MONTANT) is None
    assert _kpi(suivi, "Montant recouvrable") == "2 386,28 EUR"
    assert "dont 30,00 EUR à confirmer" in texte_visible(suivi)
    dossier = texte_visible(_get(c, f"/espace/dossiers/{dossier_id}"))
    assert "Montant recouvrable 2 386,28 EUR dont 30,00 EUR à confirmer" in dossier
    assert _kpi(_get(c, "/espace"), MONTANT) == "2 356,28 EUR"
    c.cookies.set(COOKIE_LANGUE, "en")
    assert "including 30.00 EUR to confirm" in texte_visible(_get(c, "/espace/recouvrement"))


def test_ecart_certain_non_recouvrable_dans_la_liste_des_dossiers(monde):
    """Même présentation qu'au tableau de bord : le montant de l'écart certain, marqué « non recouvrable »."""
    with monde.pf.db.tenant(B, Acteur.systeme("t"), lecture=True) as s:
        b1 = next(x for x in s.lister(Constat) if x.controle_id == "B1")
    f = monde.client()
    connecter_fondateur(f, monde)
    assert poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{b1.id}/valider").status_code == 303
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)
    ligne = re.search(
        rf'<a href="/espace/dossiers/{b1.dossier_id}">.*?</tr>', _get(c, "/espace/dossiers"), re.S
    )
    assert ligne is not None
    assert "20,00 EUR non recouvrable" in texte_visible(ligne.group(0))


# --- 2. légende du montant selon la nature du constat --------------------------------------------------------------


def test_legende_du_montant_selon_le_constat():
    def legende(constat, langue="fr"):
        return re.search(r'<span class="nature">(.*?)</span>', _carte(constat, langue), re.S).group(1)

    d3 = _constat([CALCUL, EXTRAIT])
    assert legende(d3) == "Écart avec la grille tarifaire (montant recouvrable)"
    assert "refacturé" not in legende(d3)
    assert (
        legende(replace(d3, controle_id="C3"))
        == "Écart sur les droits et taxes refacturés (montant recouvrable)"
    )
    assert legende(replace(d3, controle_id="D5")) == "Facturation en double (montant recouvrable)"
    assert legende(replace(d3, controle_id="D1")) == (
        "Écart de calcul sur la facture du transitaire (montant recouvrable)"
    )
    assert legende(replace(d3, controle_id="Z9")) == "Écart recouvrable"  # contrôle non listé : neutre
    b1 = replace(
        d3,
        controle_id="B1",
        nature="Écart de calcul sur la déclaration",
        nature_code="arithmetique_declaration",
    )
    assert legende(b1) == "Écart de calcul sur la déclaration"  # autres natures : libellé d'origine
    assert legende(d3, "en") == "Discrepancy with the rate card (recoverable amount)"


# --- 3. valeur lue nommée selon son type ---------------------------------------------------------------------------


def test_valeur_lue_nommee_selon_son_type():
    code = replace(EXTRAIT, valeur_lue="1008")

    def libelle(preuve, types, langue="fr"):
        html = (
            _carte(_constat([preuve]), langue)
            if types is None
            else _carte_types(_constat([preuve]), types, langue)
        )
        return texte_visible(re.search(r'<div class="valeur-lue">.*?</div>', html, re.S).group(0))

    assert libelle(code, {("cst_FICTIF", 1): "code"}) == "Code lu : 1008"
    assert libelle(EXTRAIT, {("cst_FICTIF", 1): "montant"}) == "Montant lu : 95,00"
    assert libelle(replace(EXTRAIT, valeur_lue="2,2"), {("cst_FICTIF", 1): "taux"}) == "Taux lu : 2,2"
    assert libelle(replace(EXTRAIT, valeur_lue="FT-FIC-0501"), {("cst_FICTIF", 1): "reference"}) == (
        "Numéro lu : FT-FIC-0501"
    )
    assert libelle(code, None) == "Lu sur le document : 1008"  # type inconnu : neutre, jamais « montant »
    assert libelle(code, {("cst_FICTIF", 1): "code"}, "en") == "Code read: 1008"


def _carte_types(constat, types, langue):
    from controldone.web.i18n import activer
    from controldone.web.rendu import environnement

    activer(langue)
    try:
        module = environnement().get_template("macros.html.j2").make_module({"langue": langue})
        return str(module.constat_carte(constat, {}, "/espace", "jeton", "/espace", types=types))
    finally:
        activer("fr")


def test_code_document_lu_comme_un_code_sur_la_page_du_dossier(monde):
    """C3 de la démonstration : le code document 1008 (autoliquidation) est un code, la TVA refacturée un montant."""
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    texte = texte_visible(_get(c, f"/espace/dossiers/{_dossier(monde, A, 'D-2026-00001')}"))
    assert "Code lu : 1008" in texte and "Montant lu : 2 356,28" in texte
    assert "Valeur lue : 1008" not in texte


# --- 4. suivi des avoirs : l'envoi du courrier sans changer de personne -------------------------------------------


def test_envoi_du_courrier_dit_sans_changer_de_personne(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    texte = texte_visible(_get(c, "/espace/recouvrement"))
    assert "Relevé envoyé par le client" not in texte and "J'ai envoyé" not in texte
    assert "Noter l'envoi du courrier" in texte
    assert "Courrier envoyé aujourd'hui" in texte  # écart de la démonstration déjà déclaré envoyé
    assert "en montant hors taxes" not in texte and "avec son montant hors taxes" in texte
    c.cookies.set(COOKIE_LANGUE, "en")
    en = texte_visible(_get(c, "/espace/recouvrement"))
    assert "Mark letter as sent" in en and "Letter sent today" in en


# --- 5. titres des rapports sans tiret cadratin --------------------------------------------------------------------


def test_titres_affiches_sans_tiret_cadratin():
    assert titre_affiche("Rapport de diagnostic — ATELIERS DÉMO FICTIF SAS") == (
        "Rapport de diagnostic · ATELIERS DÉMO FICTIF SAS"
    )
    # la raison sociale est une donnée : affichée telle quelle
    assert titre_affiche("Rapport de diagnostic — ATELIERS DÉMO FICTIF — SITE NORD") == (
        "Rapport de diagnostic · ATELIERS DÉMO FICTIF — SITE NORD"
    )
    assert titre_affiche(
        "Votre relevé d'écarts est prêt — Relevé d'écarts entre documents — factures n° FT-FIC-0501"
    ) == ("Votre relevé d'écarts est prêt · Relevé d'écarts entre documents · factures n° FT-FIC-0501")
    assert titre_affiche("Rapport de diagnostic · ATELIERS DÉMO FICTIF SAS") == (
        "Rapport de diagnostic · ATELIERS DÉMO FICTIF SAS"
    )
    assert titre_affiche("Objet modifié — par le fondateur") == "Objet modifié — par le fondateur"
    assert titre_affiche(None) == ""


def test_titre_du_rapport_au_tableau_de_bord_et_dans_la_liste(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    for url in ("/espace", "/espace/rapports"):
        texte = texte_visible(_get(c, url))
        assert "Rapport de diagnostic · ATELIERS DÉMO FICTIF SAS" in texte, url
        assert "Rapport de diagnostic —" not in texte, url
