"""Cadre commun des contrôles — point d'entrée unique pour les équipes qui écrivent les familles A à G.

    from controldone.controls.framework import (
        control, ControlContext, Confusion, cle_unite, preuve,
        CONTROL_SPECS, get_spec, Tolerances, arrondi_centime,
        montant_recouvrable, montant_ecart_documentaire, montant_arithmetique, eur_par_devise,
    )

Voir ``docs/ARCHITECTURE.md`` § « Comment écrire un contrôle » et l'exemple de référence B1
(``controldone/controls/famille_b.py``).
"""

from controldone.controls.classify import (
    Classement,
    classify,
    eur_par_devise,
    montant_arithmetique,
    montant_ecart_documentaire,
    montant_pour_spec,
    montant_recouvrable,
    sens_pour,
    trier_raisons,
)
from controldone.controls.confusion import (
    CLASSES_CONFUSION,
    LETTRES_CHIFFRES,
    codes_confondables,
    confusion_applicable,
    confusion_test,
    confusion_test_fn,
    est_transposition_adjacente,
    variantes_numeriques,
)
from controldone.controls.context import AutreDossier, Confusion, ControlContext, cle_unite, preuve
from controldone.controls.registry import (
    ControlFn,
    charger_controles,
    control,
    controles_enregistres,
    desenregistrer,
    registre_temporaire,
)
from controldone.controls.runner import (
    EVALUABLES,
    appliquer_regles_dedoublonnage,
    garde_fous_resultat,
    run_controls,
)
from controldone.controls.specs import (
    CONTROL_SPECS,
    ORDRE_CONTROLES,
    ControlSpec,
    get_spec,
    specs_as_dicts,
    specs_json,
)
from controldone.controls.tolerances import (
    CENTIME,
    Tolerances,
    arrondi_centime,
    arrondi_devise,
    arrondi_unite,
    dans_tolerance,
)
from controldone.model.valeur import confiance_derivee, deriver_somme, facteur_derivation

__all__ = [
    "CENTIME",
    "CLASSES_CONFUSION",
    "CONTROL_SPECS",
    "EVALUABLES",
    "LETTRES_CHIFFRES",
    "ORDRE_CONTROLES",
    "AutreDossier",
    "Classement",
    "Confusion",
    "ControlContext",
    "ControlFn",
    "ControlSpec",
    "Tolerances",
    "appliquer_regles_dedoublonnage",
    "arrondi_centime",
    "arrondi_devise",
    "arrondi_unite",
    "charger_controles",
    "classify",
    "cle_unite",
    "codes_confondables",
    "confiance_derivee",
    "confusion_applicable",
    "confusion_test",
    "confusion_test_fn",
    "control",
    "controles_enregistres",
    "dans_tolerance",
    "deriver_somme",
    "desenregistrer",
    "est_transposition_adjacente",
    "eur_par_devise",
    "facteur_derivation",
    "garde_fous_resultat",
    "get_spec",
    "montant_arithmetique",
    "montant_ecart_documentaire",
    "montant_pour_spec",
    "montant_recouvrable",
    "preuve",
    "registre_temporaire",
    "run_controls",
    "sens_pour",
    "specs_as_dicts",
    "specs_json",
    "trier_raisons",
    "variantes_numeriques",
]
