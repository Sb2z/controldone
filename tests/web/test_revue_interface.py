"""Revue de l'interface (vidéo de contrôle, octobre 2026) : barres pleines sans script et animation à filet de
sécurité, pied de page du client réservé aux pages du client, accords en nombre sans « (s) », preuves comptées
exactement (extraits de page et calculs), libellés des graphiques sans tiret cadratin, sélecteur de statut du
pipeline, écart certain hors recouvrement au tableau de bord du client. Données fictives."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from aides_web import ADMIN_A, ADMIN_B, connecter_client, connecter_fondateur, poster

from controldone.auth.roles import Acteur
from controldone.guardrails import AVERTISSEMENT
from controldone.services.lecture import ConstatLu, PreuveLue
from controldone.storage.models import Constat, Dossier
from controldone.web.graphes import MARGE_LIBELLES, donnees_fondateur, largeur_libelle, libelle_court
from controldone.web.i18n import COOKIE_LANGUE, accord, activer, pluriel
from controldone.web.i18n_en import CATALOGUE_EN
from controldone.web.rendu import environnement, texte_visible

A, B = "demo_ateliers", "demo_nord"
STATIQUE = Path(__file__).resolve().parents[2] / "src" / "controldone" / "web" / "static"
MENTION_CLIENT = "ControlDOne compare vos documents d'import entre eux et chiffre les écarts."
PIED_FONDATEUR = "Espace du fondateur : pages réservées au compte fondateur."


# --- 1. barres : pleines sans script, animation à filet de sécurité ---------------------------------------------------


def _regles(css: str) -> list[tuple[str, str]]:
    """``(sélecteur, corps)`` des règles d'une feuille (blocs @media compris, à plat)."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def test_barres_pleines_dans_l_etat_initial_sans_script():
    """Sans script ou en mouvement réduit, aucune règle ne pose d'échelle nulle sur une barre de proportion, une jauge
    ou une barre de graphique (la barre de suivi d'un dépôt, pilotée par le serveur, n'est pas concernée)."""
    for feuille in ("app.css", "prospection.css"):
        for selecteur, corps in _regles((STATIQUE / feuille).read_text(encoding="utf-8")):
            vise = re.search(r"\.barre\b|\.jauge\b|\.g-barre\b", selecteur)
            if vise and re.search(r"scale[XY]?\(\s*0\s*\)", corps):
                raise AssertionError(f"{feuille} : {selecteur} {{{corps}}}")
    for g in (STATIQUE.parent / "templates").rglob("*.j2"):
        assert "style=" not in g.read_text(encoding="utf-8"), g.name  # CSP : aucun style en ligne


def test_animation_des_barres_observe_le_conteneur_avec_filet_de_securite():
    js = (STATIQUE / "app.js").read_text(encoding="utf-8")
    pousser = js[js.index("function pousser(") : js.index("function barres(")]
    # visible au chargement : animée tout de suite, sans attendre l'observateur
    assert "if (visible(conteneur)) { lancer(); return; }" in pousser
    # l'observateur porte sur le conteneur (tableau, figure, piste), jamais sur la barre à l'échelle 0
    assert "M.inView(conteneur," in pousser and "M.inView(b," not in js
    # l'échelle 0 n'est posée qu'au lancement, et l'état final est rétabli par un minuteur quoi qu'il arrive
    assert pousser.index('axe + "(0)"') > pousser.index("function lancer()")
    assert "window.setTimeout(fin," in pousser and 'e.style.transform = ""' in pousser
    barres = js[js.index("function barres(") : js.index("function pastille(")]
    assert 'b.closest("table") || b.parentElement' in barres and "pousser(" in barres
    graphes = js[js.index("function graphes(") :]
    assert "pousser(fig," in graphes
    # mouvement réduit : rien n'est touché
    assert "if (!bouge() || !conteneur || !elements.length) { return; }" in pousser


# --- 2. pied de page : client seulement --------------------------------------------------------------------------------


def test_pied_du_client_absent_des_pages_du_fondateur(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    for url in ("/admin/prospection/pipeline", "/admin/prospection", "/admin", "/admin/finances"):
        texte = texte_visible(f.get(url).text)
        assert AVERTISSEMENT not in texte and MENTION_CLIENT not in texte, url
        assert PIED_FONDATEUR in texte, url
    # page du fondateur qui montre des constats : l'avertissement exact reste, sans la phrase destinée au client
    dossier = texte_visible(f.get(f"/admin/clients/{A}/dossiers/{monde.ids[A]['dossier'][0]}").text)
    assert AVERTISSEMENT in dossier and MENTION_CLIENT not in dossier
    # page publique de désinscription d'un prospect : ni avertissement ni phrase du client
    public = texte_visible(monde.client().get("/desinscription/jeton-invalide").text)
    assert AVERTISSEMENT not in public and MENTION_CLIENT not in public and PIED_FONDATEUR not in public


def test_pied_du_client_present_sur_les_pages_du_client(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    for url in ("/espace", "/espace/dossiers", f"/espace/dossiers/{monde.ids[A]['dossier'][0]}"):
        texte = texte_visible(c.get(url).text)
        assert AVERTISSEMENT in texte and MENTION_CLIENT in texte and PIED_FONDATEUR not in texte, url
    connexion = texte_visible(monde.client().get("/connexion").text)
    assert AVERTISSEMENT in connexion and MENTION_CLIENT in connexion


# --- 3. accords en nombre ----------------------------------------------------------------------------------------------


def test_accord_en_nombre_francais_et_anglais():
    un, plusieurs = "{n} constat publié", "{n} constats publiés"
    assert [pluriel(un, plusieurs, n, langue="fr") for n in (0, 1, 2, 15)] == [
        "0 constat publié",
        "1 constat publié",
        "2 constats publiés",
        "15 constats publiés",
    ]
    assert [pluriel(un, plusieurs, n, langue="en") for n in (0, 1, 2)] == [
        "0 published findings",
        "1 published finding",
        "2 published findings",
    ]
    assert pluriel(un, plusieurs, 0, aucun="aucun constat publié", langue="fr") == "aucun constat publié"
    assert pluriel(un, plusieurs, 0, aucun="aucun constat publié", langue="en") == "no published findings"
    assert accord(un, plusieurs, Decimal("1.5"), langue="fr") == un  # moins de 2 : singulier en français
    assert accord(un, plusieurs, Decimal("1.5"), langue="en") == plusieurs
    assert accord(un, plusieurs, "?", langue="fr") == plusieurs  # quantité illisible : pluriel
    assert accord(un, plusieurs, float("nan"), langue="fr") == plusieurs  # ni exception ni singulier
    activer("en")
    try:
        assert pluriel("{n} fichier", "{n} fichiers", 1) == "1 file"  # langue courante par défaut
    finally:
        activer("fr")


def test_catalogues_sans_pluriel_machine():
    machine = re.compile(r"\w\((?:e?s|ies|e|x)\)")
    assert not [k for k in CATALOGUE_EN if machine.search(k)]
    assert not [v for v in CATALOGUE_EN.values() if machine.search(v)]
    assert machine.search("3 constat(s) publié(s)") and machine.search("anomaly(ies)")


def test_tableau_marketing_sous_titre_et_plafonds(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    texte = texte_visible(f.get("/admin/prospection").text)
    assert "Chiffres réels seulement" not in texte
    assert "Aucun chiffre estimé : tout vient des événements enregistrés" in texte
    assert (
        "courriels préparés aujourd'hui ; envoyés : 0 sur" in texte and "préparations ; envois" not in texte
    )
    assert "aucun préparé cette semaine" in texte
    f.cookies.set(COOKIE_LANGUE, "en")
    en = texte_visible(f.get("/admin/prospection").text)
    assert "No estimated figures" in en and "none prepared this week" in en


# --- 4. preuves : compte exact, calcul sans tiret cadratin --------------------------------------------------------------


def _constat(preuves: list[PreuveLue]) -> ConstatLu:
    return ConstatLu(
        id="cst_FICTIF",
        dossier_id="dos_FICTIF",
        controle_id="D3",
        controle_libelle="Prix supérieur à la grille",
        niveau="Écart certain",
        niveau_code="ecart_certain",
        libelle="Libellé fictif.",
        prochaine_action="",
        raisons=[],
        montant="30,00 EUR",
        montant_valeur=Decimal("30.00"),
        nature="Écart refacturé (montant recouvrable)",
        nature_code="recouvrable",
        composante=None,
        renvoi=False,
        tolerance="0,01",
        seuil="0,10",
        statut_validation="Validé",
        statut_validation_code="valide",
        commentaire=None,
        bloque=False,
        motif_blocage=None,
        preuves=preuves,
    )


EXTRAIT = PreuveLue(
    role="Valeur comparée",
    role_code="valeur_b",
    document_id="doc_FICTIF",
    document="Facture du transitaire n° FT-FIC-0501",
    page=1,
    valeur_lue="95,00",
    calcul=None,
    index=1,
)
CALCUL = PreuveLue(
    role="Valeur de référence",
    role_code="valeur_a",
    document_id=None,
    document="Calcul",
    page=None,
    valeur_lue=None,
    calcul="forfait de 65,00 EUR",
    index=0,
)


def _carte(constat: ConstatLu, langue: str = "fr") -> str:
    activer(langue)
    try:
        module = environnement().get_template("macros.html.j2").make_module({"langue": langue})
        return str(module.constat_carte(constat, {}, "/espace", "jeton", "/espace"))
    finally:
        activer("fr")


def test_preuves_comptees_extraits_et_calculs():
    html = _carte(_constat([CALCUL, EXTRAIT]))
    resume = re.search(r"<summary>(.*?)</summary>", html, re.S).group(1)
    assert resume == "Preuves : 1 extrait de page, 1 calcul"
    texte = texte_visible(html)
    assert "—" not in texte and "Calcul Calcul" not in texte
    assert "Valeur de référence Calcul forfait de 65,00 EUR" in texte
    assert "Valeur lue : 95,00" in texte
    assert re.search(r"<summary>(.*?)</summary>", _carte(_constat([EXTRAIT, EXTRAIT])), re.S).group(1) == (
        "Preuves : 2 extraits de page"
    )
    en = re.search(r"<summary>(.*?)</summary>", _carte(_constat([CALCUL, EXTRAIT]), "en"), re.S).group(1)
    assert en == "Evidence: 1 page extract, 1 calculation"


# --- 5. graphiques : séparateur et libellés entiers ---------------------------------------------------------------------


def test_libelles_des_familles_sans_tiret_ni_coupure():
    stats = {"t": {"familles_valides": {"A": 2, "B": 1, "C": 3, "D": 1}, "familles_proposes": {"C": 1}}}
    activer("fr")
    graphes = donnees_fondateur(stats)
    barres = [b for g in graphes[1:] for b in g.barres]
    assert barres and all("—" not in b.libelle for b in barres)
    assert "C · Facture du transitaire / déclaration" in {b.libelle for b in barres}
    assert all(b.court == b.libelle for b in barres)  # tiennent dans la marge des libellés
    assert graphes[1].largeur_zone > 0
    # libellé trop long : coupé au dernier mot qui tient, jamais au milieu d'un mot
    long = "TRANSITAIRE FICTIF " * 6
    court = libelle_court(long.strip())
    assert court.endswith(" …") and largeur_libelle(court) <= MARGE_LIBELLES - 16


# --- 6. pipeline : le sélecteur de statut garde son plus long libellé ---------------------------------------------------


def test_selecteur_du_pipeline_ne_coupe_pas_le_libelle():
    css = (STATIQUE / "prospection.css").read_text(encoding="utf-8")
    regles = dict(_regles(css))
    assert "flex-wrap: wrap" in regles[".prosp-carte form"]
    assert re.search(r"flex:\s*1 1 9\.5rem", regles[".prosp-carte select"])


# --- 8. écart certain hors recouvrement -----------------------------------------------------------------------------


def test_ecart_certain_hors_recouvrement_au_tableau_de_bord(monde):
    """Dossier « Écart certain » dont l'écart certain ne se demande pas au transitaire (B1 : écart de calcul sur la
    déclaration, démonstration du site Nord) : le montant s'affiche avec la note « hors recouvrement », et les
    totaux recouvrables ne changent pas."""
    with monde.pf.db.tenant(B, Acteur.systeme("t"), lecture=True) as s:
        versions = {d.id: (d.version, d.reference) for d in s.lister(Dossier)}
        courants = [c for c in s.lister(Constat) if versions[c.dossier_id][0] == c.dossier_version]
    cible = next(
        c
        for c in courants
        if c.niveau == "ecart_certain"
        and c.nature_montant == "arithmetique_declaration"
        and c.montant_en_jeu
        and c.statut_validation == "propose"
    )
    assert not [x for x in courants if x.dossier_id == cible.dossier_id and x.nature_montant == "recouvrable"]
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)
    kpi = re.compile(r"Écarts certains</div><div class=\"kpi-val num\">([^<]*)</div>")
    avant = kpi.search(c.get("/espace").text)
    f = monde.client()
    connecter_fondateur(f, monde)
    r = poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{cible.id}/valider")
    assert r.status_code == 303
    page = c.get("/espace").text
    ligne = re.search(rf'<a href="/espace/dossiers/{cible.dossier_id}">.*?</tr>', page, re.S)
    assert ligne is not None
    texte = texte_visible(ligne.group(0))
    montant = f"{cible.montant_en_jeu:.2f}".replace(".", ",")
    assert "Écart certain" in texte and montant in texte and "hors recouvrement" in texte, texte
    # les totaux recouvrables n'en tiennent pas compte
    apres = kpi.search(page)
    assert avant is not None and apres is not None and apres.group(1) == avant.group(1)
    # en anglais
    c.cookies.set(COOKIE_LANGUE, "en")
    ligne_en = re.search(
        rf'<a href="/espace/dossiers/{cible.dossier_id}">.*?</tr>', c.get("/espace").text, re.S
    )
    assert ligne_en is not None and "not recoverable" in ligne_en.group(0)
