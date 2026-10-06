"""Garde-fous juridiques (SPEC §3.5)."""

import pytest
import yaml

from controldone.config import get_settings
from controldone.guardrails import (
    AVERTISSEMENT,
    PHRASE_RENVOI,
    FormulationInterdite,
    assert_clean,
    charger_formulations,
    check_text,
    contient_phrase_renvoi,
)
from controldone.model import RAISON_LIBELLES


def test_phrases_exactes():
    assert PHRASE_RENVOI == (
        "Ce point relève d'une appréciation réglementaire : il est à faire vérifier par un représentant en "
        "douane enregistré ou un avocat. ControlDOne ne se prononce pas sur ce point."
    )
    assert AVERTISSEMENT == (
        "Ce document est un contrôle technique de cohérence entre documents et de calcul. Il ne constitue ni un "
        "conseil juridique, fiscal ou douanier, ni un avis sur la conformité des opérations. Les montants "
        "indiqués sont des écarts constatés entre documents ; ils ne préjugent pas des sommes légalement dues."
    )


def test_phrases_officielles_propres():
    assert check_text(PHRASE_RENVOI) == []
    assert check_text(AVERTISSEMENT) == []
    assert contient_phrase_renvoi("Note. " + PHRASE_RENVOI)
    assert not contient_phrase_renvoi(PHRASE_RENVOI.lower())


def _toutes_les_expressions():
    data = charger_formulations()
    return [e for c in data["categories"] for e in c["expressions"]]


def test_fichier_versionne():
    data = yaml.safe_load(
        (get_settings().config_dir / "formulations_interdites.yaml").read_text(encoding="utf-8")
    )
    assert data["schema"].startswith("controldone.formulations_interdites/")
    assert data["motif"] == "formulation_interdite"
    assert len(_toutes_les_expressions()) == 37  # tableau §3.2


@pytest.mark.parametrize("expression", _toutes_les_expressions())
def test_chaque_expression_detectee_telle_quelle(expression):
    v = check_text(f"Texte : {expression}.")
    assert any(x.expression == expression for x in v)


@pytest.mark.parametrize(
    "texte",
    [
        "LE BON CODE",
        "le Code Correct",
        "ERREUR DE CLASSEMENT",
        "devrait etre classee",
        "Droits Dus",
        "les taxes dues",
        "montant du a la douane",
        "trop paye en douane",
        "sous evaluation",
        "sousévaluation",
        "Sur-Évaluations",
        "origines incorrectes",
        "préférences injustifiées",
        "droits préférentiels",
        "taux erronés",
        "mauvais taux",
        "le taux applicable est de 4 %",
        "opérations illégales",
        "illégaux",
        "irrégulières",
        "en infraction",
        "des fraudes",
        "pratiques frauduleuses",
        "frauduleuse",
        "nous réclamons",
        "ControlDOne réclame",
        "au nom de notre client",
        "mandatée par",
        "il faut rectifier la déclaration",
        "nous garantissons",
        "certifiée conforme",
        "certifiés conformes",
        "non conformes à la réglementation",
    ],
)
def test_casse_accents_pluriel_feminin(texte):
    assert check_text(texte), texte


@pytest.mark.parametrize(
    "texte",
    [
        "La déclaration (MRN 26FR…, page 2) indique 12 450,00 EUR ; la facture commerciale indique 12 540,00 USD.",
        "Le montant imprimé (418,20 EUR) diffère du produit de la base imprimée par le taux imprimé.",
        "Montant liquidé indiqué sur la déclaration : 812,40 EUR.",
        "Le code imprimé sur la facture diffère du code imprimé sur la déclaration.",
        "Nous avons constaté un écart ; nous vous remercions de bien vouloir émettre un avoir.",
        "Montant refacturé supérieur au montant liquidé sur la déclaration.",
        "Une irrégularité de mise en page.",  # « irrégularité » n'est pas « irrégulier »
        "Les droits liquidés et la taxe imprimée.",
        "Point à faire vérifier par un RDE ou un avocat.",
    ],
)
def test_textes_propres(texte):
    assert check_text(texte) == []


def test_assert_clean_et_extrait():
    assert_clean("Rien à signaler.")
    with pytest.raises(FormulationInterdite) as e:
        assert_clean("Il s'agit d'une fraude manifeste.")
    v = e.value.violations[0]
    assert (
        v.extrait == "fraude"
        and v.categorie == "qualification_juridique"
        and v.motif == "formulation_interdite"
    )


@pytest.mark.parametrize(
    "texte",
    [
        "droit dû",
        "le droit dû par l'importateur",
        "droits dus",
        "taxe due",
        "montant dû à la douane",
        "montants dus à la douane",  # pluriel exigé par §3.2 (« dû » non final)
        "Le montant du droit du.",
        "droit du ; voir",
        "DROIT DU",  # « du » sans accent : fin de proposition
        "droit\u200bdû",
        "taxe\u200bdue",
        "dro\u00adit dû",
        "fr\u00adaude",  # caractères invisibles
    ],
)
def test_participe_du_bloque(texte):
    # D-1215 (remplace la conséquence assumée de D-014)
    assert check_text(texte)


@pytest.mark.parametrize(
    "texte", ["le droit du transitaire", "droit du tarif", "La ligne « Droit du port »", "droits du dossier"]
)
def test_article_du_non_bloque(texte):
    # D-1215 : l'article « du » suivi d'un nom n'est pas le participe « dû »
    assert check_text(texte) == []


def test_extrait_avec_caracteres_invisibles():
    texte = "Le dro\u00adit dû est indiqué."
    v = check_text(texte)[0]
    assert v.extrait == "dro\u00adit dû" and texte[v.debut : v.fin] == v.extrait


def test_libelles_de_raisons_propres():
    for code, texte in RAISON_LIBELLES.items():
        assert check_text(texte) == [], code
