"""Bloc I4 — interface : messages d'erreur des services traduits à l'affichage (D-4801), documentation de l'API en
anglais (D-4802), aucun texte français hors des régions ``lang="fr"`` de l'interface anglaise (D-4803).
Données FICTIVES."""

from __future__ import annotations

import ast
import re
from html import escape
from pathlib import Path

import pytest
from aides_web import ADMIN_A, LECTEUR_A, connecter_client, connecter_fondateur, poster
from francais_visible import mots_francais, segments_visibles
from test_interface_bloc_i import INTERDITS_EN, _pages_client, _pages_fondateur

from controldone.guardrails import AVERTISSEMENT, PHRASE_RENVOI, check_text
from controldone.services.depot import LIBELLES_REFUS
from controldone.web.i18n import AVERTISSEMENT_EN, COOKIE_LANGUE, traduire_erreur
from controldone.web.i18n_api import DESCRIPTIONS_EN, RESUMES_EN, description_operation
from controldone.web.i18n_messages import MESSAGES_EN, PARAMETRES_EN, traduire_message
from controldone.web.rendu import texte_visible

A, B = "demo_ateliers", "demo_nord"
SRC = Path(__file__).resolve().parents[2] / "src" / "controldone"
_PARAM = re.compile(r"\{[^{}]*\}")


# --- 1. catalogue des messages des services ---------------------------------------------------------------------------

#: Modules dont les erreurs atteignent l'interface (``str(exc)`` affiché par une route web).
MODULES_AFFICHES = (
    "services/saisie.py",
    "services/admin.py",
    "services/plateforme.py",
    "services/publication.py",
    "services/reclamations.py",
    "services/validation.py",
    "services/depot.py",
    "facturation/service.py",
    "facturation/offres.py",
    "facturation/paiements.py",
    "facturation/pa.py",
    "facturation/modele.py",
    "outbox/service.py",
    "model/recouvrement.py",
    "litiges/etats.py",
    "storage/facturation.py",
    "storage/scope.py",
)
#: Exceptions dont le texte est affiché (les refus d'accès ``AccesRefuse`` donnent une page 404 fixe).
EXCEPTIONS_AFFICHEES = frozenset(
    {
        "RequeteInvalide",
        "Interdit",
        "ValueError",
        "KeyError",
        "CouponRefuse",
        "EmissionRefusee",
        "TransitionInterdite",
        "ErreurTransition",
        "TransitionReclamationInterdite",
        "CouponIndisponible",
        "ChronologieRompue",
    }
)


def _gabarit(v: ast.expr) -> str | None:
    """Texte d'un message levé, paramètres remplacés par ``{}`` (f-chaînes, concaténations)."""
    if isinstance(v, ast.Constant) and isinstance(v.value, str):
        return v.value
    if isinstance(v, ast.JoinedStr):
        return "".join(p.value if isinstance(p, ast.Constant) else "{}" for p in v.values)
    if isinstance(v, ast.BinOp) and isinstance(v.op, ast.Add):
        return (_gabarit(v.left) or "{}") + (_gabarit(v.right) or "{}")
    return None


def _messages_leves() -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in MODULES_AFFICHES:
        for n in ast.walk(ast.parse((SRC / rel).read_text(encoding="utf-8"))):
            if not (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) and n.exc.args):
                continue
            if getattr(n.exc.func, "id", None) not in EXCEPTIONS_AFFICHEES:
                continue
            texte = _gabarit(n.exc.args[0])
            if texte:
                out[re.sub(r"(\{\})+", "{}", texte)] = f"{rel}:{n.lineno}"
    return out


def test_chaque_message_de_service_affiche_a_sa_traduction():
    leves = _messages_leves()
    assert len(leves) > 80  # le relevé fonctionne
    # chaque message, paramètres remplis par une valeur fictive, est reconnu (texte exact ou message paramétré)
    manquants = sorted(
        f"{v} : {k}" for k, v in leves.items() if traduire_message(k.replace("{}", "FICTIF"), "en") is None
    )
    assert manquants == [], manquants
    assert set(LIBELLES_REFUS.values()) <= set(MESSAGES_EN)  # motifs de refus d'un fichier déposé


def test_noms_de_champs_des_montants_saisis_traduits():
    noms = set()
    for f in (SRC / "web").glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "montant_saisi":
                noms |= {
                    k.value.value for k in n.keywords if k.arg == "nom" and isinstance(k.value, ast.Constant)
                }
    assert noms and noms <= set(PARAMETRES_EN), sorted(noms - set(PARAMETRES_EN))


def test_messages_deux_langues_memes_parametres_sans_formulation_interdite():
    for fr, en in {**MESSAGES_EN, **PARAMETRES_EN}.items():
        assert en.strip(), fr
        assert sorted(re.findall(r"\{(\w+)\}", fr)) == sorted(re.findall(r"\{(\w+)\}", en)), fr
        assert len(set(re.findall(r"\{(\w+)\}", fr))) == len(re.findall(r"\{(\w+)\}", fr)), fr
        assert check_text(en) == [], fr
        assert not any(x in en.lower() for x in INTERDITS_EN), en
        assert fr.strip("{}") and _PARAM.sub("", fr).strip(), fr  # jamais un motif fait d'un seul paramètre


def test_traduire_message():
    assert traduire_message("aucun fichier transmis", "en") == "no file sent"
    assert traduire_message("aucun fichier transmis", "fr") is None
    assert traduire_message("message inconnu", "en") is None
    assert (
        traduire_message("montant HT de l'avoir : nombre attendu (ex. 1 234,56)", "en")
        == "credit note amount excl. VAT: number expected (e.g. 1 234,56 or 1234.56)"
    )
    assert traduire_message("plafond : 2 décimales au plus", "en") == "cap: 2 decimal places at most"
    assert traduire_message("transition interdite : credite -> reclame", "en") == (
        "transition not allowed: credite -> reclame"
    )
    assert traduire_message("palier inconnu : {x}", "en") == "unknown tier: {x}"  # accolades : données
    assert traduire_message("coupon épuisé; formulation interdite « x » (y)", "en") == (
        "coupon used up; forbidden wording “x” (y)"
    )
    assert traduire_erreur("aucun fichier transmis", "fr") == "aucun fichier transmis"
    assert traduire_erreur("Action approuvée, suite impossible : {motif}", "en", motif="coupon épuisé") == (
        "Action approved, next step impossible: coupon used up"
    )
    assert traduire_erreur("Action approuvée, suite impossible : {motif}", "fr", motif="coupon épuisé") == (
        "Action approuvée, suite impossible : coupon épuisé"
    )


# --- messages des services dans l'interface -------------------------------------------------------------------------


def _flash(html: str) -> str:
    m = re.search(r'<div class="message (?:erreur|succes)"[^>]*>(.*?)</div>', html, re.S)
    return m.group(1).strip() if m else ""


@pytest.mark.parametrize(("langue", "attendu"), [("en", "no file sent"), ("fr", "aucun fichier transmis")])
def test_depot_vide_message_traduit(monde, langue, attendu):
    c = monde.client()
    c.cookies.set(COOKIE_LANGUE, langue)
    connecter_client(c, monde, ADMIN_A)
    r = poster(c, "/espace/depot", "/espace/depot")
    assert r.status_code == 303
    assert _flash(c.get(r.headers["location"]).text) == attendu


def test_avoir_montant_invalide_message_traduit(monde):
    c = monde.client()
    c.cookies.set(COOKIE_LANGUE, "en")
    connecter_client(c, monde, ADMIN_A)
    page = c.get("/espace/recouvrement").text
    m = re.search(r'action="/espace/recouvrement/([^/"]+)/avoir"', page)
    assert m
    r = poster(c, "/espace/recouvrement", f"/espace/recouvrement/{m.group(1)}/avoir", {"montant": "douze"})
    assert r.status_code == 303
    assert _flash(c.get(r.headers["location"]).text) == (
        "credit note amount excl. VAT: number expected (e.g. 1 234,56 or 1234.56)"
    )


def test_fondateur_messages_traduits_journal_en_francais(monde):
    c = monde.client()
    c.cookies.set(COOKIE_LANGUE, "en")
    connecter_fondateur(c, monde)
    cid = monde.ids[B]["constat_propose"][0]
    r = poster(c, "/admin/validation", f"/admin/clients/{B}/constats/{cid}/rejeter", {"motif": ""})
    assert _flash(c.get(r.headers["location"]).text) == "rejecting requires a reason"
    r = poster(
        c,
        "/admin/finances",
        "/admin/finances/abonnement",
        {"client_id": A, "palier": "zz", "mois": "2026-10"},
    )
    assert _flash(c.get(r.headers["location"]).text) == "unknown tier: zz"  # KeyError : sans guillemets
    r = poster(c, "/admin/clients", "/admin/clients", {"raison_sociale": "", "offre": "diagnostic"})
    assert _flash(c.get(r.headers["location"]).text).startswith("company name required")
    # journal d'audit : en français, quelle que soit la langue de l'interface
    journal = c.get("/admin/journal").text
    assert '<td class="details" lang="fr">' in journal and "décision sur un constat (rejeter)" in journal


def test_corps_trop_gros_dans_la_langue_du_navigateur(monde):
    c = monde.client()
    corps = b"x" * (2 * 1024 * 1024 + 10)
    r = c.post("/connexion", content=corps, headers={"Accept-Language": "en-GB,en;q=0.9"})
    assert r.status_code == 413 and r.text == "Request too large."
    c.cookies.set(COOKIE_LANGUE, "fr")
    r = c.post("/connexion", content=corps, headers={"Accept-Language": "en"})
    assert r.status_code == 413 and r.text == "Requête trop volumineuse."


# --- 2. documentation de l'API ----------------------------------------------------------------------------------------


def test_documentation_api_en_anglais(monde):
    c = monde.client()
    schema = c.get("/api/v1/openapi.json").json()
    for ops in schema["paths"].values():
        for op in ops.values():
            assert op.get("summary", "") in RESUMES_EN, op.get("summary")
            if op.get("description"):
                assert description_operation(op["description"], "en") != op["description"], op["description"][
                    :60
                ]
    for en in (*RESUMES_EN.values(), *DESCRIPTIONS_EN.values()):
        assert check_text(en) == [] and not any(x in en.lower() for x in INTERDITS_EN), en
    c.cookies.set(COOKIE_LANGUE, "en")
    page = c.get("/api/v1/docs")
    assert page.status_code == 200 and '<html lang="en">' in page.text
    texte = texte_visible(page.text)
    assert "List files" in texte and "Lister les dossiers" not in texte and "/api/v1/einvoices" in texte
    assert AVERTISSEMENT in texte and AVERTISSEMENT_EN in texte and check_text(texte) == []
    assert mots_francais(page.text) == []
    fr = c.get("/api/v1/docs?langue=fr")
    assert (
        '<html lang="fr">' in fr.text and "Lister les dossiers" in fr.text and AVERTISSEMENT_EN not in fr.text
    )
    sans = monde.client().get("/api/v1/docs", headers={"Accept-Language": "fr-FR"})
    assert '<html lang="fr">' in sans.text
    assert c.get("/api/v1/openapi.json").json() == schema  # schéma inchangé


# --- 3. aucun texte français hors des régions lang="fr" en anglais ------------------------------------------------------

#: Données de démonstration et textes qui restent en français par décision (7B) ou par nature, retirés des segments
#: avant la recherche. Chaque entrée est justifiée ; ne jamais y ajouter un texte d'interface.
AUTORISES = (
    re.compile(
        r"[A-Z0-9ÀÂÉÈÊÎÔÛÇ' &—-]*FICTIF[A-Z0-9ÀÂÉÈÊÎÔÛÇ' &—-]*"
    ),  # raisons sociales fictives (données)
    # libellés des documents (rendus lang="fr" ailleurs ; repris dans un texte alternatif d'image)
    re.compile(r"(Déclaration en douane|Facture commerciale|Facture du transitaire) n° \S+"),
    # libellés lus dans les documents de démonstration (données des documents, jamais traduites)
    re.compile(
        r"Contrôleurs industriels|Droits de douane \(débours\)|Frais de dédouanement|TVA à l'importation \(débours\)"
    ),
    re.compile(r"Contrôle continu — \w+"),  # libellé des paliers du catalogue (texte des factures émises)
)
TEXTES_JURIDIQUES = (AVERTISSEMENT, PHRASE_RENVOI)


def _francais(html: str) -> list[tuple[str, str]]:
    propres = []
    for seg in segments_visibles(html):
        for t in TEXTES_JURIDIQUES:
            seg = seg.replace(t, " ")
        for motif in AUTORISES:
            seg = motif.sub(" ", seg)
        propres.append(seg)
    return mots_francais("".join(f"<p>{escape(s)}</p>" for s in propres if s.strip()))


def test_aucun_mot_francais_hors_lang_fr_en_anglais(monde):
    trouves: dict[str, set[str]] = {}
    parcours = (
        ("client", ADMIN_A, _pages_client(monde)),
        ("lecteur", LECTEUR_A, ["/espace", "/espace/dossiers", "/espace/recouvrement", "/compte"]),
        ("fondateur", None, [*_pages_fondateur(monde), "/admin/inexistant"]),
    )
    for qui, email, pages in parcours:
        c = monde.client()
        c.cookies.set(COOKIE_LANGUE, "en")
        connecter_fondateur(c, monde) if qui == "fondateur" else connecter_client(c, monde, email)
        for url in pages:
            r = c.get(url)
            assert '<html lang="en">' in r.text, url
            for mot, seg in _francais(r.text):
                trouves.setdefault(f"{mot!r} dans {seg[:120]!r}", set()).add(url)
    anonyme = monde.client()
    anonyme.cookies.set(COOKIE_LANGUE, "en")
    for url in ("/connexion", "/api/v1/docs", "/inexistant"):
        for mot, seg in _francais(anonyme.get(url).text):
            trouves.setdefault(f"{mot!r} dans {seg[:120]!r}", set()).add(url)
    assert trouves == {}, sorted(f"{k} <- {sorted(v)[:2]}" for k, v in trouves.items())[:30]


def test_le_repere_signale_bien_le_francais():
    html = '<p>Files</p><p lang="fr">Écart certain</p><p>Aucun dossier</p><code>valider_constat</code>'
    assert [m for m, _s in mots_francais(html)] == ["Aucun", "dossier"]
    assert mots_francais("<p>field `fichier` (Markdown)</p>") == []
    assert mots_francais('<button title="Télécharger">x</button>') == [("Télécharger", "Télécharger")]
    assert _francais(f"<p>{AVERTISSEMENT}</p><p>ATELIERS DÉMO FICTIF SAS</p>") == []
