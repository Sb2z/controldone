"""Site public statique (site/) : garde-fous juridiques, liens, bandeaux, ressources locales seulement.

Politique de script (D-5102) : chaque page charge exactement deux scripts locaux, avec `defer`
(`assets/vendor/motion.min.js` puis `assets/site.js`) ; aucun script en ligne, aucune origine externe, aucun
attribut `style` (la CSP de la page n'autorise que `script-src 'self'` et `style-src 'self'`)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml

from controldone.guardrails import PHRASE_RENVOI, check_text

SITE = Path(__file__).resolve().parents[2] / "site"
PAGES = sorted(SITE.glob("*.html"))
DEMO = SITE / "demo" / "report.html"
PAGES_JURIDIQUES = ["mentions-legales.html", "cgv.html", "confidentialite.html", "dpa.html"]
PAGES_ATTENDUES = [
    "index.html",
    "tarifs.html",
    "demonstration.html",
    "methode.html",
    "experts-comptables.html",
    "contact.html",
    *PAGES_JURIDIQUES,
]
BANDEAU_AVOCAT = "BROUILLON : À RELIRE PAR UN AVOCAT"
SCRIPTS_AUTORISES = ["assets/vendor/motion.min.js", "assets/site.js"]
RACINE = SITE.parent

# Seules sources officielles (ou citées comme source d'un chiffre) autorisées en lien sortant.
DOMAINES_AUTORISES = {
    "taxation-customs.ec.europa.eu",
    "commission.europa.eu",
    "eur-lex.europa.eu",
    "www.impots.gouv.fr",
    "www.legifrance.gouv.fr",
    "www.cnil.fr",
    "www.douane.gouv.fr",
    "entreprendre.service-public.gouv.fr",
    "www.dehst.de",
    "kpmg.com",
}


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.texte: list[str] = []
        self.attrs_visibles: list[str] = []
        self.liens: list[tuple[str, str, str]] = []  # (balise, attribut, valeur)
        self.ids: set[str] = set()
        self.balises: list[str] = []
        self.scripts: list[dict[str, str | None]] = []
        self.contenu_scripts: list[str] = []
        self.styles_en_ligne: list[str] = []
        self.metas: list[dict[str, str | None]] = []
        self._cache = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.balises.append(tag)
        if tag in ("script", "style", "template"):
            self._cache += 1
        if tag == "script":
            self.scripts.append(a)
            self.contenu_scripts.append("")
        if tag == "meta":
            self.metas.append(a)
        if "style" in a:
            self.styles_en_ligne.append(f"{tag}[style]")
        if "id" in a:
            self.ids.add(a["id"])
        for attr in ("href", "src", "action", "data", "poster", "srcset"):
            if a.get(attr):
                self.liens.append((tag, attr, a[attr]))
        for attr in ("alt", "title", "aria-label", "content"):
            if a.get(attr):
                self.attrs_visibles.append(a[attr])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template") and self._cache:
            self._cache -= 1

    def handle_data(self, data):
        if not self._cache:
            self.texte.append(data)
        elif self.balises and self.balises[-1] == "script" and self.contenu_scripts:
            self.contenu_scripts[-1] += data

    @property
    def visible(self) -> str:
        return " ".join(" ".join(self.texte).split())


def _lire(p: Path) -> _Page:
    parser = _Page()
    parser.feed(p.read_text(encoding="utf-8"))
    return parser


def test_pages_attendues_presentes():
    noms = {p.name for p in PAGES}
    assert set(PAGES_ATTENDUES) <= noms
    assert (SITE / "assets" / "style.css").exists()
    assert (SITE / "README.md").exists()


@pytest.mark.parametrize("page", [*PAGES, DEMO], ids=lambda p: p.name)
def test_aucune_formulation_interdite(page):
    doc = _lire(page)
    for texte in (doc.visible, " | ".join(doc.attrs_visibles)):
        assert check_text(texte) == [], f"{page.name} : {check_text(texte)}"


def verifier_ressources(page: Path, doc: _Page, prefixe: str) -> None:
    """Règles communes FR/EN : pas de formulaire, scripts locaux différés, CSP, pas de style en ligne."""
    assert "form" not in doc.balises, f"{page.name} : aucun formulaire (le contact passe par mailto)"
    assert [sc.get("src") for sc in doc.scripts] == [prefixe + s for s in SCRIPTS_AUTORISES], page.name
    for sc, contenu in zip(doc.scripts, doc.contenu_scripts, strict=True):
        assert "defer" in sc, f"{page.name} : script sans defer {sc}"
        assert not contenu.strip(), f"{page.name} : script en ligne interdit"
        assert set(sc) <= {"src", "defer"}, f"{page.name} : attribut de script inattendu {sc}"
    assert "style" not in doc.balises and not doc.styles_en_ligne, (
        f"{page.name} : style en ligne {doc.styles_en_ligne}"
    )
    csp = [
        m.get("content") or ""
        for m in doc.metas
        if (m.get("http-equiv") or "").lower() == "content-security-policy"
    ]
    assert len(csp) == 1, f"{page.name} : une CSP en <meta>"
    directives = {d.split()[0]: d.split()[1:] for d in csp[0].split(";") if d.strip()}
    assert directives["default-src"] == ["'none'"]
    assert directives["script-src"] == ["'self'"], "script-src 'self' seulement (ni inline ni eval)"
    assert directives["style-src"] == ["'self'"]
    assert directives["font-src"] == ["'self'"]
    assert directives["connect-src"] == ["'none'"]
    assert directives["form-action"] == ["'none'"]
    for tag, attr, val in doc.liens:
        u = urlsplit(val)
        if u.scheme in ("", "mailto"):
            continue
        assert u.scheme == "https", f"{page.name} : {val}"
        assert attr == "href" and tag == "a", f"{page.name} : ressource externe chargée {tag}[{attr}]={val}"
        assert u.hostname in DOMAINES_AUTORISES, f"{page.name} : lien externe non autorisé {val}"
    feuilles = [v for t, a, v in doc.liens if t == "link" and a == "href" and v.endswith(".css")]
    assert feuilles == [prefixe + "assets/style.css"], "une seule feuille de style partagée"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_pas_de_ressource_externe_ni_formulaire(page):
    verifier_ressources(page, _lire(page), "")


def test_scripts_et_polices_locaux_avec_licences():
    for chemin in (*SCRIPTS_AUTORISES, "assets/vendor/LICENSE-motion.md"):
        assert (SITE / chemin).is_file(), chemin
    assert "MIT" in (SITE / "assets/vendor/LICENSE-motion.md").read_text(encoding="utf-8")
    css = (SITE / "assets/style.css").read_text(encoding="utf-8")
    polices = re.findall(r'url\("(fonts/[^"]+\.woff2)"\)', css)
    assert len(polices) == 4, polices
    for p in polices:
        assert (SITE / "assets" / p).is_file(), p
    assert css.count("font-display: swap") == 4
    licences = {
        "LICENSE-SourceSerif4.md": "Reserved Font Name",
        "LICENSE-Inter.txt": "SIL OPEN FONT LICENSE",
        "OFL-JetBrainsMono.txt": "SIL OPEN FONT LICENSE",
    }
    for nom, attendu in licences.items():
        assert attendu.lower() in (SITE / "assets/fonts" / nom).read_text(encoding="utf-8").lower(), nom
    # Nom réservé « Source » : le fichier officiel est servi sous son nom d'origine, non modifié.
    assert (SITE / "assets/fonts/SourceSerif4Display-Regular.ttf.woff2").is_file()
    site_js = (SITE / "assets/site.js").read_text(encoding="utf-8")
    for interdit in (
        "fetch(",
        "XMLHttpRequest",
        "sendBeacon",
        "document.cookie",
        "localStorage",
        "eval(",
        "new Function",
    ):
        assert interdit not in site_js, interdit


def test_aucun_hebergement_en_france_annonce():
    for page in [*PAGES, *sorted((SITE / "en").glob("*.html"))]:
        texte = _lire(page).visible.lower()
        for faux in ("hébergé en france", "hébergement en france", "hosted in france", "souverain"):
            assert faux not in texte, f"{page.name} : {faux}"


def test_rapport_demo_sans_ressource_externe():
    doc = _lire(DEMO)
    for _tag, attr, val in doc.liens:
        if attr == "src":
            assert val.startswith("data:"), val
        else:
            assert urlsplit(val).scheme in ("", "mailto", "data"), val


@pytest.mark.parametrize("page", [*PAGES, DEMO], ids=lambda p: p.name)
def test_liens_internes_resolus(page):
    doc = _lire(page)
    for _tag, _attr, val in doc.liens:
        u = urlsplit(val)
        if u.scheme or val.startswith("data:"):
            continue
        cible = (page.parent / unquote(u.path)).resolve() if u.path else page
        assert cible.exists(), f"{page.name} : lien cassé {val}"
        assert SITE.resolve() in cible.parents or cible == SITE.resolve(), f"{page.name} : sort du site {val}"
        if u.fragment and cible.suffix == ".html":
            assert u.fragment in _lire(cible).ids, f"{page.name} : ancre absente {val}"


@pytest.mark.parametrize("nom", PAGES_JURIDIQUES)
def test_pages_juridiques_brouillon_et_champs_a_completer(nom):
    doc = _lire(SITE / nom)
    assert BANDEAU_AVOCAT in doc.visible
    brut = (SITE / nom).read_text(encoding="utf-8")
    assert brut.index(BANDEAU_AVOCAT) < brut.index("<h1"), "le bandeau précède le titre"
    assert "[À COMPLÉTER" in doc.visible


def test_mentions_legales_sans_identite_inventee():
    texte = _lire(SITE / "mentions-legales.html").visible
    for champ in ("SIREN", "forme juridique", "adresse", "hébergeur", "directeur de la publication"):
        assert champ in texte, champ
    assert texte.count("[À COMPLÉTER") >= 8


def test_phrase_de_renvoi_exacte():
    for nom in ("index.html", "methode.html"):
        assert PHRASE_RENVOI in _lire(SITE / nom).visible, nom


def test_demonstration_marquee_fictive():
    assert "DONNÉES FICTIVES" in _lire(SITE / "demonstration.html").visible
    rapport = _lire(DEMO).visible
    assert "DONNÉES FICTIVES" in rapport
    for capture in ("rapport-synthese.png", "rapport-constat.png", "rapport-mobile.png"):
        assert (SITE / "demo" / "captures" / capture).exists()


def _offres() -> dict:
    return yaml.safe_load((RACINE / "config" / "offres.yaml").read_text(encoding="utf-8"))["offres"]


def _euros_fr(montant: Decimal) -> str:
    entier, dec = f"{montant:.2f}".split(".")
    groupes = f"{int(entier):,}".replace(",", " ")
    return f"{groupes},{dec} €"


def test_prix_annonces():
    tarifs = _lire(SITE / "tarifs.html").visible.replace("\u00a0", " ")
    offres = _offres()
    assert f"{int(Decimal(offres['diagnostic']['prix_ht']))} €" in tarifs
    assert f"{int(Decimal(offres['commission']['taux']) * 100)} %" in tarifs
    for palier in offres["continu"]["paliers"]:
        assert f"{int(Decimal(palier['prix_mensuel_ht']))} €" in tarifs, palier
        assert f"Jusqu'à {palier['dossiers_par_mois']}" in tarifs, palier
    assert "sur devis" in tarifs
    assert "diagnostics sont offerts" in tarifs


def test_seuils_de_rentabilite_publies():
    """Seuil = prix ÷ (1 − taux de commission) ; recalculé depuis config/offres.yaml (D-5104)."""
    tarifs = _lire(SITE / "tarifs.html").visible.replace("\u00a0", " ")
    offres = _offres()
    garde = 1 - Decimal(offres["commission"]["taux"])
    diag = Decimal(offres["diagnostic"]["prix_ht"])
    assert diag / garde == Decimal("487.5")
    attendus = [diag, diag / garde]
    for palier in offres["continu"]["paliers"]:
        annuel = Decimal(palier["prix_mensuel_ht"]) * 12
        attendus += [annuel, annuel / garde]
    assert Decimal("99") * 12 / garde == Decimal("1485")
    for montant in attendus:
        assert _euros_fr(montant) in tarifs, _euros_fr(montant)


def test_calculateur_seuil_js():
    """La fonction de calcul de site.js donne les mêmes seuils (exécutée par Node si disponible)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js absent")
    script = (
        "global.window={};global.document={documentElement:{lang:'fr'},readyState:'loading',"
        "addEventListener:function(){}};"
        f"require({json.dumps(str(SITE / 'assets' / 'site.js'))});"
        "const s=window.ControlDOneSeuil;"
        "console.log(JSON.stringify([s('diagnostic',60),s('offert',10),s('continu',240),s('continu',241),"
        "s('continu',720),s('continu',1800),s('continu',1801)]));"
    )
    sortie = json.loads(
        subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    )
    diag, offert, c20, c60a, c60b, c150, devis = sortie
    assert diag["cout"] == 390 and diag["seuil"] == 487.5 and diag["parDossier"] == pytest.approx(8.125)
    assert offert["cout"] == 0 and offert["seuil"] == 0
    assert c20["cout"] == 1188 and c20["seuil"] == pytest.approx(1485)
    assert c60a["cout"] == 2388 and c60a["seuil"] == pytest.approx(2985)
    assert c60b["cout"] == 2388
    assert c150["cout"] == 4188 and c150["seuil"] == pytest.approx(5235)
    assert devis == {"devis": True}


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_offert_toujours_avec_commission(page):
    """L121-4 19° : « offert » est suivi, au même endroit, de la commission qui reste due."""
    texte = _lire(page).visible.replace("\u00a0", " ")
    for m in re.finditer(r"offerts?\b", texte):
        voisinage = texte[max(0, m.start() - 250) : m.end() + 250]
        assert "reste due" in voisinage, f"{page.name} : « offert » sans la commission : …{voisinage}…"
    if page.name not in PAGES_JURIDIQUES:  # « moyen gratuit de s'opposer » est une mention légale
        assert not re.search(r"\bgratuite?s?\b", texte, re.IGNORECASE), f"{page.name} : « gratuit »"


def test_cgv_clauses_essentielles():
    cgv = _lire(SITE / "cgv.html").visible.replace(" ", " ")
    for attendu in (
        "audit technique de cohérence",
        "40 EUR",
        "L441-10",
        "opposer",
        "envoie lui-même",
        "droit français",
        "Confidentialité",
    ):
        assert attendu in cgv, attendu


def test_dpa_sous_traitants():
    dpa = _lire(SITE / "dpa.html").visible
    for attendu in (
        "Union européenne",
        "modèle de langage",
        "Désactivable",
        "Stripe",
        "Mesures de sécurité",
        "Sort des données",
        "audit",
    ):
        assert attendu in dpa, attendu
