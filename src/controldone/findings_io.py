"""Sortie ``findings.json`` par dossier (SPEC Annexe C, schéma ``controldone.findings/1.0.0``).

- ``construire_findings(...)`` : assemble la sortie à partir du dossier, des documents, des fichiers,
  des résultats et de l'exécution ;
- ``ecrire_findings(findings, chemin)`` / ``findings_json(findings)`` : sérialisation déterministe ;
- ``lire_findings(source)`` : relecture avec contrôle de version (§6.4 : refus d'une majeure supérieure,
  champs inconnus ignorés) ;
- ``statut_global_depuis_resultats(...)`` : statut global d'un dossier (§18.2).

Les champs de l'Annexe C sont tous présents ; quelques champs optionnels sont ajoutés (changement
mineur, ignoré par un lecteur 1.0) : ``sous_controle``, ``unite``, ``raison_code``, ``seuil_certitude``,
``sens``, ``montant_brut``, ``autres_dossiers``, ``motif_blocage``, ``calcul`` (preuve).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import Field

from controldone.guardrails import AVERTISSEMENT
from controldone.model.base import Modele, verifier_schema
from controldone.model.champs import chemin_relatif
from controldone.model.documents import Document, Fichier
from controldone.model.dossier import Dossier
from controldone.model.enums import NatureMontant, Outcome, RaisonCode, StatutGlobal, StatutValidation
from controldone.model.resultats import Execution, ResultatControle

__all__ = [
    "NOM_SCHEMA_FINDINGS",
    "SCHEMA_FINDINGS",
    "VERSION_FINDINGS",
    "Findings",
    "FindingsConstat",
    "FindingsDocument",
    "FindingsExecution",
    "FindingsLien",
    "FindingsPreuve",
    "FindingsResultat",
    "FindingsValeur",
    "constats_hors_totaux",
    "construire_findings",
    "ecrire_findings",
    "findings_json",
    "findings_json_rejeu",
    "lire_findings",
    "statut_global_depuis_resultats",
]

NOM_SCHEMA_FINDINGS = "controldone.findings"
VERSION_FINDINGS = "1.1.0"
SCHEMA_FINDINGS = f"{NOM_SCHEMA_FINDINGS}/{VERSION_FINDINGS}"


def _dec(x: Decimal | None) -> str | None:
    return None if x is None else str(x)


class FindingsExecution(Modele):
    execution_id: str
    version_moteur: str
    version_regles: str
    empreinte_tolerances: str | None = None
    modele_llm: str | None = None
    cout_ia_eur: str = "0.00"
    duree_s: float | None = None


class FindingsDocument(Modele):
    document_id: str
    type: str
    sous_type: str | None = None
    file: str | None = None
    pages: list[int] = Field(default_factory=list)
    confiance_classement: float = 1.0


class FindingsLien(Modele):
    document_id: str
    role: str
    force: str
    signaux: list[str] = Field(default_factory=list)


class FindingsValeur(Modele):
    valeur: str | None
    page: int | None = None
    confiance: float
    methode: str


class FindingsResultat(Modele):
    controle_id: str
    outcome: str
    attendu: str | None = None
    constate: str | None = None
    ecart: str | None = None
    tolerance: str | None = None
    sous_controle: str | None = None
    unite: str | None = None
    raison_code: str | None = None
    seuil_certitude: str | None = None


class FindingsPreuve(Modele):
    document_id: str | None = None
    page: int | None = None
    valeur_brute: str | None = None
    role: str
    calcul: str | None = None


class FindingsConstat(Modele):
    finding_id: str
    controle_id: str
    niveau: str
    raisons: list[str] = Field(default_factory=list)
    montant_en_jeu: str | None = None
    nature_montant: str
    composante: str | None = None
    renvoi: bool = False
    documents_concernes: list[str] = Field(default_factory=list)
    preuves: list[FindingsPreuve] = Field(default_factory=list)
    libelle: str = ""
    prochaine_action: str = ""
    statut_validation: str = StatutValidation.propose.value
    sous_controle: str | None = None
    sens: str | None = None
    montant_brut: str | None = None
    autres_dossiers: list[str] = Field(default_factory=list)
    motif_blocage: str | None = None
    #: E6 : constat d'origine dont ce constat remplace le montant dans les totaux (§14 E6, D-1202).
    remplace_constat_id: str | None = None


class Findings(Modele):
    schema_: str = Field(default=SCHEMA_FINDINGS, alias="schema")
    dossier_id: str
    dossier_version: int
    execution: FindingsExecution
    statut_global: str
    documents: list[FindingsDocument] = Field(default_factory=list)
    liens: list[FindingsLien] = Field(default_factory=list)
    valeurs: dict[str, dict[str, FindingsValeur]] = Field(default_factory=dict)
    resultats: list[FindingsResultat] = Field(default_factory=list)
    constats: list[FindingsConstat] = Field(default_factory=list)
    avertissement: str = AVERTISSEMENT

    def vers_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def constats_hors_totaux(resultats: Iterable[ResultatControle]) -> dict[str, str]:
    """Constats à exclure des **totaux** (jamais de la liste des constats), avec le motif (D-1202) :

    - ``remplace_par_e6`` : un constat E6 (avoir partiel) porte le reste à recouvrer et **remplace** le
      montant de l'écart d'origine dans les totaux (§14 E6) ;
    - ``doublon_documentaire`` : un F5 (même facture commerciale sur plusieurs déclarations) qui porte le
      même écart de valeur, sur la même facture commerciale, qu'un A4/A5/A6 du dossier : l'écart n'est
      compté qu'une fois dans « Écarts de valeur entre documents » (§18.3).

    Règle unique pour tout agrégateur (rapport, tableau de bord) : les montants par constat sont inchangés.
    """
    rs = [r for r in resultats if r.constat is not None]
    exclus: dict[str, str] = {}
    for r in rs:
        if r.controle_id == "E6" and r.details.get("remplace_constat_id"):
            exclus[str(r.details["remplace_constat_id"])] = "remplace_par_e6"
    documentaires = [
        r for r in rs
        if r.controle_id in ("A4", "A5", "A6") and r.constat is not None and r.constat.montant_en_jeu is not None
        and r.constat.nature_montant is NatureMontant.ecart_documentaire
    ]
    for r in rs:
        c = r.constat
        if r.controle_id != "F5" or c is None or c.montant_en_jeu is None:
            continue
        for a in documentaires:
            ca = a.constat
            assert ca is not None and ca.montant_en_jeu is not None
            if abs(ca.montant_en_jeu) == abs(c.montant_en_jeu) and set(ca.documents_concernes) & set(
                c.documents_concernes
            ):
                exclus.setdefault(c.id, "doublon_documentaire")
                break
    return exclus


def statut_global_depuis_resultats(
    resultats: Iterable[ResultatControle], *, valides_seulement: bool = False
) -> StatutGlobal:
    """Statut global (§18.2), premier qui s'applique : ``non_concerne`` (P5) > ``document_manquant`` (P1)
    > ``ecart_certain`` > ``a_verifier`` > ``conforme``.

    ``valides_seulement=True`` (rapport client) : un ``ecart_certain`` ne compte que s'il est validé par
    le fondateur ; ``False`` (banc, file de validation) : tous les constats proposés comptent.
    Un dossier dont un contrôle C, A4 ou A5 est ``non_verifiable`` ne peut pas être ``conforme``.
    """
    rs = list(resultats)
    # Aucun résultat ou un contrôle en erreur interne : impossible de conclure, jamais « conforme » (P8).
    if not rs:
        return StatutGlobal.a_verifier
    if any(r.controle_id == "P5" and r.details.get("non_concerne") for r in rs):
        return StatutGlobal.non_concerne
    # D-4206 : un manque commun au lot est signalé par un seul dossier ; les autres restent incomplets.
    if any(r.controle_id == "P1" and (r.outcome.est_constat or r.details.get("motif") == "manque_commun_du_lot")
           for r in rs):
        return StatutGlobal.document_manquant

    def compte(r: ResultatControle) -> bool:
        if r.constat is None:
            return False
        if r.constat.statut_validation is StatutValidation.rejete:
            return False
        return not valides_seulement or r.constat.statut_validation in (
            StatutValidation.valide, StatutValidation.modifie
        )

    if any(r.outcome is Outcome.ecart_certain and compte(r) for r in rs):
        return StatutGlobal.ecart_certain
    # Un constat non rejeté (même non encore validé) empêche le statut « conforme ».
    if any(r.constat is not None and r.constat.statut_validation is not StatutValidation.rejete for r in rs):
        return StatutGlobal.a_verifier
    bloquant = any(
        r.outcome is Outcome.non_verifiable
        and (
            r.raison_code is RaisonCode.erreur_interne
            or (
                (r.controle_id.startswith("C") or r.controle_id in ("A4", "A5"))
                and r.raison_code is not RaisonCode.document_manquant
            )
        )
        for r in rs
    )
    if bloquant:
        return StatutGlobal.a_verifier
    return StatutGlobal.conforme


def construire_findings(
    dossier: Dossier,
    documents: Iterable[Document],
    resultats: Iterable[ResultatControle],
    execution: Execution,
    *,
    fichiers: Mapping[str, Fichier] | None = None,
    dossier_id: str | None = None,
    statut_global: StatutGlobal | None = None,
) -> Findings:
    """Assemble ``findings.json`` (Annexe C).

    ``dossier_id`` : identifiant à écrire (le banc passe l'identifiant ``BXnnnn`` du dossier de corpus) ;
    par défaut ``dossier.id``. ``fichiers`` sert à remplir ``documents[].file`` (chemin relatif d'origine,
    ex. ``docs/expedition_77/envoi.pdf``). Seuls les documents liés au dossier sont exportés.
    """
    fichiers = fichiers or {}
    ids_lies = dossier.document_ids()
    docs_par_id = {d.id: d for d in documents}
    docs = [docs_par_id[i] for i in ids_lies if i in docs_par_id]
    rs = list(resultats)

    f_docs = []
    valeurs: dict[str, dict[str, FindingsValeur]] = {}
    for d in docs:
        fic = fichiers.get(d.pages[0].fichier_id) if d.pages else None
        f_docs.append(
            FindingsDocument(
                document_id=d.id,
                type=d.type.value,
                sous_type=d.sous_type,
                file=fic.chemin_relatif if fic else None,
                pages=[p.numero for p in d.pages],
                confiance_classement=d.confiance_classement,
            )
        )
        vals = {}
        for v in d.valeurs():
            vals[chemin_relatif(v.chemin)] = FindingsValeur(
                valeur=v.valeur, page=v.page, confiance=v.confiance, methode=v.methode.value
            )
        if vals:
            valeurs[d.id] = vals

    f_resultats = [
        FindingsResultat(
            controle_id=r.controle_id,
            outcome=r.outcome.value,
            attendu=r.attendu,
            constate=r.constate,
            ecart=_dec(r.ecart),
            tolerance=_dec(r.tolerance_appliquee),
            sous_controle=r.sous_controle,
            unite=r.unite,
            raison_code=r.raison_code.value if r.raison_code else None,
            seuil_certitude=_dec(r.seuil_certitude_applique),
        )
        for r in rs
    ]
    f_constats = []
    for r in rs:
        c = r.constat
        if c is None:
            continue
        f_constats.append(
            FindingsConstat(
                finding_id=c.id,
                controle_id=c.controle_id,
                niveau=c.niveau.value,
                raisons=[x.value for x in c.raisons],
                montant_en_jeu=_dec(c.montant_en_jeu),
                nature_montant=c.nature_montant.value,
                composante=c.composante.value if c.composante else None,
                renvoi=c.renvoi,
                documents_concernes=list(c.documents_concernes),
                preuves=[
                    FindingsPreuve(
                        document_id=p.document_id, page=p.page, valeur_brute=p.valeur_brute,
                        role=p.role.value, calcul=p.calcul,
                    )
                    for p in c.preuves
                ],
                libelle=c.libelle,
                prochaine_action=c.prochaine_action,
                statut_validation=c.statut_validation.value,
                sous_controle=c.sous_controle,
                sens=c.sens.value if c.sens else None,
                montant_brut=_dec(c.montant_brut),
                autres_dossiers=list(c.autres_dossiers),
                motif_blocage=c.motif_blocage,
                remplace_constat_id=r.details.get("remplace_constat_id") if r.controle_id == "E6" else None,
            )
        )
    statut = statut_global or statut_global_depuis_resultats(rs)
    return Findings(
        dossier_id=dossier_id or dossier.id,
        dossier_version=dossier.version,
        execution=FindingsExecution(
            execution_id=execution.id,
            version_moteur=execution.version_moteur,
            version_regles=execution.version_regles,
            empreinte_tolerances=execution.empreinte_tolerances,
            modele_llm=execution.modele_llm,
            cout_ia_eur=str(execution.cout_ia_eur.quantize(Decimal("0.01"))),
            duree_s=execution.duree_s,
        ),
        statut_global=statut.value,
        documents=f_docs,
        liens=[
            FindingsLien(
                document_id=lien.document_id, role=lien.role.value, force=lien.force.value,
                signaux=[s.value for s in lien.signaux],
            )
            for lien in dossier.liens
        ],
        valeurs=valeurs,
        resultats=f_resultats,
        constats=f_constats,
    )


def findings_json(findings: Findings) -> str:
    """JSON déterministe (ordre des champs du modèle, indentation 2, UTF-8)."""
    return json.dumps(findings.vers_dict(), ensure_ascii=False, indent=2) + "\n"


def findings_json_rejeu(findings: Findings) -> str:
    """Forme de comparaison d'un rejeu (§6.2.12 « identiques octet pour octet, hors horodatages ») :
    ``execution.duree_s`` est une mesure d'horloge, assimilée aux horodatages et retirée (D-1204).
    ``findings.json`` garde ``duree_s`` (Annexe C)."""
    d = findings.vers_dict()
    d["execution"].pop("duree_s", None)
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


def ecrire_findings(findings: Findings, chemin: Path | str) -> Path:
    p = Path(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(findings_json(findings), encoding="utf-8")
    return p


def lire_findings(source: Path | str | Mapping[str, Any]) -> Findings:
    """Relit un ``findings.json`` (chemin, texte JSON ou dictionnaire) après vérification du schéma."""
    if isinstance(source, Mapping):
        data = dict(source)
    else:
        texte = str(source)
        if isinstance(source, Path) or not texte.lstrip().startswith("{"):
            texte = Path(source).read_text(encoding="utf-8")
        data = json.loads(texte)
    verifier_schema(data.get("schema", ""), NOM_SCHEMA_FINDINGS, VERSION_FINDINGS)
    return Findings.model_validate(data)
