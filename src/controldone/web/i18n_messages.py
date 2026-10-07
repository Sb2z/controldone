"""Messages d'erreur des services affichés par l'interface (bloc I4, D-4801).

Les services lèvent leurs erreurs **en français** (``RequeteInvalide("aucun fichier transmis")``) : ce texte reste
celui des journaux et du journal d'audit. L'interface le traduit à l'affichage par ce catalogue, dont les **clés
sont le texte français de référence**, paramètres compris (``"{nom} : valeur obligatoire"``) ; un message
paramétré est reconnu par motif (``traduire_message``) et ses paramètres connus (nom d'un champ) sont traduits à
leur tour. Un message inconnu reste en français (jamais d'erreur). Un test relève les messages levés par les
services affichés et exige leur entrée, dans les deux langues, avec les mêmes paramètres.

Ne contient ni les textes des constats ni les rapports et relevés (décision 7B : français seulement)."""

from __future__ import annotations

import re
from functools import lru_cache

__all__ = ["MESSAGES_EN", "PARAMETRES_EN", "traduire_message"]

#: Message français de référence (tel que levé par le service) -> anglais.
MESSAGES_EN: dict[str, str] = {
    # --- saisie des montants (services/saisie.py) ---
    "{nom} : valeur obligatoire": "{nom}: value required",
    "{nom} : valeur trop longue": "{nom}: value too long",
    "{nom} : nombre attendu (ex. 1 234,56)": "{nom}: number expected (e.g. 1 234,56 or 1234.56)",
    "{nom} : {decimales} décimales au plus": "{nom}: {decimales} decimal places at most",
    "{nom} : nombre attendu": "{nom}: number expected",
    "{nom} : valeur positive attendue": "{nom}: positive value expected",
    "{nom} : valeur non nulle attendue": "{nom}: non-zero value expected",
    "{nom} : valeur trop élevée": "{nom}: value too high",
    # --- administration des clients (services/admin.py) ---
    "réservé au fondateur": "reserved for the founder",
    "raison sociale obligatoire (300 caractères au plus)": "company name required (300 characters at most)",
    "raison sociale obligatoire": "company name required",
    "offre inconnue": "unknown offer",
    "adresse électronique invalide": "invalid email address",
    "rôle inconnu": "unknown role",
    "rôle client attendu": "client role expected",
    "ce compte ne peut pas être rattaché à un client": "this account cannot be attached to a client",
    "SIREN : 9 chiffres": "SIREN: 9 digits",
    "nom obligatoire": "name required",
    "fichier CSV illisible": "unreadable CSV file",
    "grille trop longue (500 postes au plus)": "rate card too long (500 items at most)",
    "ligne {n}, {k} : entier attendu": "line {n}, {k}: integer expected",
    "fichier de grille trop volumineux (2 Mo au plus)": "rate card file too large (2 MB at most)",
    "fichier texte UTF-8 attendu": "UTF-8 text file expected",
    "JSON illisible": "unreadable JSON",
    "objet JSON attendu": "JSON object expected",
    "grille invalide : vérifier les colonnes et les valeurs": "invalid rate card: check the columns and values",
    "aucun poste reconnu dans la grille": "no item recognised in the rate card",
    # --- droits (services/plateforme.py, publication, réclamations) ---
    "action « {action} » non autorisée pour ce compte": "action “{action}” not allowed for this account",
    "reconstitution réservée au fondateur": "reconstruction reserved for the founder",
    "publication réservée au fondateur": "publication reserved for the founder",
    "préparation réservée au fondateur": "preparation reserved for the founder",
    "aucun dossier à publier pour ce client": "no file to publish for this client",
    # --- suivi des avoirs (services/reclamations.py, model/recouvrement.py, litiges/etats.py) ---
    "montant de l'avoir invalide": "invalid credit note amount",
    "le montant de l'avoir doit être positif": "the credit note amount must be positive",
    "origine : transitaire ou administration": "origin: forwarder or administration",
    "aucun écart validé à présenter pour ce transitaire": "no validated discrepancy to present for this forwarder",
    "transition interdite : {de} -> {vers}": "transition not allowed: {de} -> {vers}",
    "l'abandon exige un motif": "abandoning requires a reason",
    "{de} -> {vers} exige un motif": "{de} -> {vers} requires a reason",
    # --- validation des constats (services/validation.py, storage/scope.py) ---
    "ce constat a déjà fait l'objet d'une décision": "a decision has already been made on this finding",
    "le rejet exige un motif": "rejecting requires a reason",
    "la rétrogradation exige un motif": "downgrading requires a reason",
    "seul un écart certain peut être rétrogradé": "only a certain discrepancy can be downgraded",
    "statut de validation inconnu": "unknown validation status",
    "la correction exige un motif": "a correction requires a reason",
    "valeur vide ou trop longue": "value empty or too long",
    "valeur illisible pour ce type de champ": "value unreadable for this type of field",
    "version de dossier antérieure à la version enregistrée": "file version older than the recorded version",
    # --- dépôt (services/depot.py) : refus et motifs de refus d'un fichier ---
    "dépôt réservé aux comptes client": "upload reserved for client accounts",
    "aucun fichier transmis": "no file sent",
    "dépôt trop volumineux : 500 Mo au plus par dépôt": "upload too large: 500 MB at most per upload",
    "un contenu a été retiré du coffre pendant le dépôt : déposer à nouveau": (
        "a content was removed from the vault during the upload: upload again"
    ),
    "fichier protégé par mot de passe": "password-protected file",
    "fichier corrompu ou illisible": "corrupted or unreadable file",
    "fichier vide": "empty file",
    "type de fichier non pris en charge": "file type not supported",
    "fichier trop volumineux (50 Mo par fichier, 500 Mo par dépôt, 300 pages)": (
        "file too large (50 MB per file, 500 MB per upload, 300 pages)"
    ),
    "archive refusée (structure dangereuse : chemins, liens, profondeur, compression)": (
        "archive refused (dangerous structure: paths, links, depth, compression)"
    ),
    "refusé": "refused",
    # --- facturation (facturation/*.py, storage/facturation.py) ---
    "facture et action ne correspondent pas": "invoice and action do not match",
    "mois au format AAAA-MM attendu": "month in YYYY-MM format expected",
    "pas de commission sur un remboursement accordé par une administration": (
        "no commission on a refund granted by an administration"
    ),
    "base de commission négative": "negative commission base",
    "un avoir exige un motif": "a credit note requires a reason",
    "montant de l'avoir supérieur au reste de la facture": "credit note amount higher than the invoice balance",
    "un avoir non émis existe déjà pour cette facture : l'émettre ou le refuser avant d'en proposer un autre": (
        "an unissued credit note already exists for this invoice: issue or refuse it before proposing another"
    ),
    "facture d'origine introuvable": "original invoice not found",
    "action sans facture": "action without an invoice",
    "le brouillon doit être approuvé par le fondateur avant l'émission": (
        "the draft must be approved by the founder before issue"
    ),
    "identité du vendeur incomplète ({champs})": "seller identity incomplete ({champs})",
    "cumul des avoirs supérieur à la facture d'origine": "total credit notes higher than the original invoice",
    "accord de publication non signé": "publication consent not signed",
    "facture non émise : émettre avant de déposer": "invoice not issued: issue it before filing",
    "rien à payer sur cette facture": "nothing to pay on this invoice",
    "palier inconnu : {code}": "unknown tier: {code}",
    "volume négatif": "negative volume",
    "coupon inconnu": "unknown coupon",
    "coupon réservé à l'offre « {offre} »": "coupon reserved for the “{offre}” offer",
    "accord de publication des résultats anonymisés non signé": "consent to publish anonymised results not signed",
    "coupon épuisé": "coupon used up",
    "coupon déjà utilisé par ce client": "coupon already used by this client",
    "montant au centime attendu": "amount to the cent expected",
    "session inconnue": "unknown session",
    "dépôt refusé : PDF Factur-X attendu": "filing refused: Factur-X PDF expected",
    "code de statut inconnu : {code}": "unknown status code: {code}",
    "facture inconnue de la plateforme": "invoice unknown to the platform",
    "une facture comporte au moins une ligne": "an invoice has at least one line",
    "ligne invalide : prix négatif ou quantité nulle": "invalid line: negative price or zero quantity",
    "remise supérieure au total des lignes": "discount higher than the total of the lines",
    "échéance antérieure à la date de facture": "due date earlier than the invoice date",
    "un avoir cite la facture d'origine": "a credit note cites the original invoice",
    "date d'émission {date} antérieure à la dernière facture de la série ({derniere})": (
        "issue date {date} earlier than the last invoice of the series ({derniere})"
    ),
    "offre « continu » : au moins un palier attendu": "“continu” offer: at least one tier expected",
    "taux de commission hors de [0, 1]": "commission rate outside [0, 1]",
    "champs inconnus : {champs}": "unknown fields: {champs}",
    # --- actions sortantes (outbox/service.py) ---
    "le refus exige un motif": "refusing requires a reason",
    "envoi interdit depuis le statut {statut}": "sending not allowed from status {statut}",
    "envoi déjà en cours pour cette action": "sending already in progress for this action",
    "seul un brouillon peut être remplacé": "only a draft can be replaced",
    "formulation interdite « {expression} » ({categorie})": "forbidden wording “{expression}” ({categorie})",
    "formulation_interdite": "forbidden wording",
    # --- limites et verrous (rate limiting, maintenance, plafond IA) ---
    "trop de requêtes": "too many requests",
    "Requête trop volumineuse.": "Request too large.",
}

#: Paramètres connus des messages (noms de champs passés par le web aux services) -> anglais.
PARAMETRES_EN: dict[str, str] = {
    "montant HT de l'avoir": "credit note amount excl. VAT",
    "TVA de l'avoir": "credit note VAT",
    "plafond": "cap",
    "base HT": "base excl. VAT",
    "montant HT": "amount excl. VAT",
    "montant": "amount",
}

_PARAM = re.compile(r"\{(\w+)\}")


@lru_cache(maxsize=1)
def _motifs() -> tuple[tuple[re.Pattern[str], str], ...]:
    """Messages paramétrés compilés en motifs ancrés, les plus longs (les plus précis) d'abord."""
    out = []
    for fr, en in MESSAGES_EN.items():
        if not _PARAM.search(fr):
            continue
        morceaux = _PARAM.split(fr)  # texte, nom, texte, nom, …
        motif = "".join(re.escape(m) if i % 2 == 0 else f"(?P<{m}>.+?)" for i, m in enumerate(morceaux))
        out.append((len(_PARAM.sub("", fr)), re.compile(rf"\A{motif}\Z", re.S), en))
    out.sort(key=lambda x: -x[0])
    return tuple((m, en) for _n, m, en in out)


def _parametre(valeur: str) -> str:
    return PARAMETRES_EN.get(valeur) or MESSAGES_EN.get(valeur) or valeur


def traduire_message(texte: str, langue: str) -> str | None:
    """Traduction anglaise d'un message de service (texte exact ou message paramétré reconnu) ; ``None`` si le
    message est inconnu ou la langue française. Les ``; `` séparent plusieurs motifs (garde-fous)."""
    if langue != "en" or not texte:
        return None
    if texte in MESSAGES_EN:
        return MESSAGES_EN[texte]
    for motif, en in _motifs():
        m = motif.match(texte)
        if m:
            return en.format(**{k: _parametre(v) for k, v in m.groupdict().items()})
    if "; " in texte:
        parties = [traduire_message(p, langue) for p in texte.split("; ")]
        if all(parties):
            return "; ".join(p for p in parties if p)
    return None
