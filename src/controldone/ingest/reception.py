"""Réception d'un lot (SPEC §5.1, §7.1, §20.3) : dossiers, fichiers isolés, archives ZIP, courriels.

Sortie : un ``Lot`` et des ``Fichier`` (sha256, type détecté par les octets, chemin relatif d'origine,
motif de refus). Un fichier refusé ne bloque jamais le lot (§20.6). Rien n'est persisté ici : la couche
d'assemblage stocke les objets et les octets (``FichierRecu.contenu``).

Courriels (§7.1, §20.2) : les pièces jointes deviennent des fichiers d'entrée ; le corps devient un
fichier ``<message>.eml`` marqué ``corps_courriel`` (classé ``document_support/courriel`` ; ``contenu`` =
texte décodé du corps, ``sha256`` = celui du message), **jamais interprété**.
L'objet et le corps ne déclenchent aucune action ; seuls l'expéditeur (liste blanche du client) et les
pièces jointes sont utilisés.
"""

from __future__ import annotations

import base64
import binascii
import email
import email.policy
import hashlib
import html
import io
import logging
import lzma
import quopri
import re
import stat
import zipfile
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr
from enum import StrEnum
from pathlib import Path, PurePosixPath

from controldone.ids import IdGenerator, Prefixe
from controldone.model import CanalLot, Fichier, Lot, StatutFichier
from controldone.model.referentiel import Client

from .sniff import (
    MIME_CSV,
    MIME_EML,
    MIME_PDF,
    MIME_TEXTE,
    MIME_XLS,
    MIME_XLSX,
    MIME_ZIP,
    MIMES_SUPPORTES,
    decoder_texte,
    detecter_type,
)

__all__ = [
    "MIME_CORPS_COURRIEL",
    "FichierRecu",
    "Limites",
    "MotifRefus",
    "Reception",
    "cle_idempotence_reception",
    "expediteur_autorise",
    "recevoir",
    "recevoir_chemin",
    "recevoir_courriel",
    "recevoir_octets",
]

#: Type attribué au corps d'un courriel (texte brut, classé ``document_support/courriel``).
MIME_CORPS_COURRIEL = "text/x-corps-courriel"

_MO = 1024 * 1024

#: pypdf journalise ses avertissements avec des extraits bruts du fichier (octets du document) : jamais dans les
#: journaux (§20.8, D-1601). La réception tourne dans le processus web.
logging.getLogger("pypdf").setLevel(logging.CRITICAL)
log = logging.getLogger("controldone.ingest.reception")

#: Erreurs de décompression d'une entrée d'archive (flux tronqué ou altéré) : entrée « corrompue », jamais une
#: exception qui ferait perdre tout le lot (D-1600).
_ERREURS_ENTREE = (
    zipfile.BadZipFile,
    OSError,
    RuntimeError,
    ValueError,
    EOFError,
    NotImplementedError,
    zlib.error,
    lzma.LZMAError,
    KeyError,
    TypeError,
    OverflowError,
)
#: Profondeur d'imbrication MIME lue dans un courriel (au-delà : courriel refusé « corrompu »).
_PROFONDEUR_MIME = 40


@dataclass(frozen=True)
class Limites:
    """Limites de §20.3."""

    taille_fichier: int = 50 * _MO
    taille_lot: int = 500 * _MO
    pages_fichier: int = 300
    zip_profondeur: int = 5
    zip_entrees: int = 2000
    zip_ratio: float = 100.0
    zip_taille_totale: int = 1024 * _MO


class MotifRefus(StrEnum):
    """Motifs de refus d'un fichier (§5.1)."""

    protege = "protege"
    corrompu = "corrompu"
    vide = "vide"
    non_supporte = "non_supporte"
    trop_gros = "trop_gros"
    archive_dangereuse = "archive_dangereuse"


@dataclass
class FichierRecu:
    fichier: Fichier
    #: Octets du fichier (``None`` si refusé pour taille ou archive dangereuse).
    contenu: bytes | None
    #: Clé d'idempotence de la réception (§7) : ``sha256(fichier) + client_id`` (+ ``Message-ID``).
    cle_idempotence: str
    #: Provenance lisible : ``envoi.zip!dossier/facture.pdf``, ``courriel:<id>``…
    origine: str | None = None
    #: Corps d'un courriel (``document_support/courriel``, jamais interprété).
    corps_courriel: bool = False

    @property
    def a_traiter(self) -> bool:
        """Faux pour un fichier refusé ou un doublon déjà reçu (§7.1 : pas de retraitement)."""
        return (
            self.fichier.statut is StatutFichier.ok
            and self.fichier.doublon_de is None
            and self.contenu is not None
        )


@dataclass
class Reception:
    lot: Lot
    fichiers: list[FichierRecu] = field(default_factory=list)
    #: Courriel d'un expéditeur non autorisé : rien n'est traité (§7.1), signalement au fondateur.
    quarantaine: bool = False
    motif_quarantaine: str | None = None
    message_id: str | None = None
    #: Archives reçues (audit) : ``(chemin, sha256, nombre d'entrées)``.
    archives: list[tuple[str, str, int]] = field(default_factory=list)
    taille_totale: int = 0

    def acceptes(self) -> list[FichierRecu]:
        return [f for f in self.fichiers if f.fichier.statut is StatutFichier.ok]

    def refuses(self) -> list[FichierRecu]:
        return [f for f in self.fichiers if f.fichier.statut is StatutFichier.refuse]

    def a_traiter(self) -> list[FichierRecu]:
        return [f for f in self.fichiers if f.a_traiter]


def cle_idempotence_reception(sha256: str, client_id: str | None, message_id: str | None = None) -> str:
    """Clé de l'étape 1 (§7) : ``sha256(fichier) + client_id`` (et ``Message-ID`` pour un courriel)."""
    brut = "\x1f".join(["reception", sha256, client_id or "", message_id or ""])
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def expediteur_autorise(adresse: str | None, autorises: Iterable[str]) -> bool:
    """Liste blanche : adresse exacte (insensible à la casse) ou domaine (``@domaine.fr`` / ``domaine.fr``)."""
    if not adresse:
        return False
    _, addr = parseaddr(adresse)
    addr = (addr or adresse).strip().lower()
    if "@" not in addr:
        return False
    domaine = addr.rsplit("@", 1)[1]
    for a in autorises:
        a = a.strip().lower()
        if not a:
            continue
        if a.startswith("@"):
            if domaine == a[1:]:
                return True
        elif "@" in a:
            if addr == a:
                return True
        elif domaine == a:
            return True
    return False


# --- moteur interne -----------------------------------------------------------------------------------


class _ArchiveDangereuse(Exception):
    pass


@dataclass
class _Etat:
    client_id: str | None
    lot: Lot
    limites: Limites
    ids: IdGenerator | None
    deja_recus: Mapping[str, str]
    message_id: str | None = None
    vus: dict[str, str] = field(default_factory=dict)
    sortie: list[FichierRecu] = field(default_factory=list)
    archives: list[tuple[str, str, int]] = field(default_factory=list)
    taille_totale: int = 0

    def nouvel_id(self) -> str | None:
        return self.ids.nouveau(Prefixe.fichier) if self.ids is not None else None


def _sha(contenu: bytes) -> str:
    return hashlib.sha256(contenu).hexdigest()


def _nom_sur(chemin: str) -> str:
    return PurePosixPath(chemin.replace("\\", "/")).name or "fichier"


def _compter_pages_pdf(contenu: bytes) -> tuple[int | None, MotifRefus | None]:
    """Nombre de pages ; motif ``protege`` (mot de passe) ou ``corrompu`` si illisible."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        lecteur = PdfReader(io.BytesIO(contenu), strict=False)
        if lecteur.is_encrypted:
            try:
                ok = lecteur.decrypt("")
            except Exception:  # algorithme non pris en charge -> traité comme protégé
                ok = 0
            if not ok:
                return None, MotifRefus.protege
        n = len(lecteur.pages)
    except (PdfReadError, ValueError, KeyError, TypeError, OSError, AssertionError, RecursionError):
        return None, MotifRefus.corrompu
    except Exception:
        return None, MotifRefus.corrompu
    if n == 0:
        return 0, MotifRefus.vide
    return n, None


def _verifier_image(contenu: bytes) -> tuple[int | None, MotifRefus | None]:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(contenu)) as im:
            n = getattr(im, "n_frames", 1)
            im.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return None, MotifRefus.corrompu
    return n, None


def _motif_conteneur(infos: list[zipfile.ZipInfo], lim: Limites) -> str | None:
    """Contrôles de §20.3 sur les tailles **annoncées** d'une archive (la lecture en flux de ``zipfile`` ne
    décompresse jamais au-delà de la taille annoncée d'une entrée)."""
    if len(infos) > lim.zip_entrees:
        return "nombre d'entrées au-delà de la limite"
    total = sum(i.file_size for i in infos)
    if total > lim.zip_taille_totale:
        return "taille décompressée au-delà de la limite"
    compresse = sum(i.compress_size for i in infos)
    if (compresse and total / max(1, compresse) > lim.zip_ratio) or any(
        i.compress_size and i.file_size / i.compress_size > lim.zip_ratio and i.file_size > _MO for i in infos
    ):
        return "taux de compression au-delà de la limite"
    return None


def _verifier_tableur(
    contenu: bytes, mime: str, lim: Limites | None = None
) -> tuple[int | None, MotifRefus | None]:
    """Classeur XLSX/ODS : une archive ZIP soumise aux mêmes limites qu'un ZIP déposé (bombe de décompression,
    D-1602) avant tout contrôle d'intégrité."""
    try:
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            infos = z.infolist()
            if _motif_conteneur(infos, lim or Limites()) is not None:
                return None, MotifRefus.archive_dangereuse
            if any(i.flag_bits & 0x1 for i in infos):
                return None, MotifRefus.protege
            if z.testzip() is not None:
                return None, MotifRefus.corrompu
            noms = z.namelist()
    except _ERREURS_ENTREE:
        return None, MotifRefus.corrompu
    if mime == MIME_XLSX:
        n = sum(1 for x in noms if re.match(r"xl/worksheets/sheet\d+\.xml$", x))
        return n or None, (MotifRefus.vide if n == 0 else None)
    return None, None


def _ajouter(
    etat: _Etat,
    chemin_relatif: str,
    contenu: bytes | None,
    *,
    mime: str | None = None,
    motif: MotifRefus | None = None,
    origine: str | None = None,
    corps_courriel: bool = False,
    taille: int | None = None,
    sha_source: str | None = None,
) -> FichierRecu:
    sha = sha_source or (_sha(contenu) if contenu is not None else _sha(f"refuse:{chemin_relatif}".encode()))
    taille = len(contenu) if contenu is not None else (taille or 0)
    if mime is None:
        mime = detecter_type(contenu, chemin_relatif) if contenu else "application/octet-stream"
    nombre_pages: int | None = None
    if motif is None and contenu is not None:
        if taille == 0:
            motif = MotifRefus.vide
        elif taille > etat.limites.taille_fichier or etat.taille_totale + taille > etat.limites.taille_lot:
            motif = MotifRefus.trop_gros
        elif corps_courriel:
            pass
        elif mime == MIME_TEXTE:
            motif = MotifRefus.non_supporte  # texte brut déposé : format non prévu (§5.1)
        elif mime == MIME_XLS or mime not in MIMES_SUPPORTES:
            motif = MotifRefus.non_supporte
        elif mime == MIME_PDF:
            nombre_pages, motif = _compter_pages_pdf(contenu)
        elif mime.startswith("image/"):
            nombre_pages, motif = _verifier_image(contenu)
        elif mime.startswith("application/vnd."):
            nombre_pages, motif = _verifier_tableur(contenu, mime, etat.limites)
        elif mime in (MIME_CSV,) and not (decoder_texte(contenu) or "").strip():
            motif = MotifRefus.vide
        if motif is None and nombre_pages is not None and nombre_pages > etat.limites.pages_fichier:
            motif = MotifRefus.trop_gros
    if motif is None and contenu is not None:
        etat.taille_totale += taille
    kwargs = {}
    fid = etat.nouvel_id()
    if fid:
        kwargs["id"] = fid
    doublon = None
    if motif is None and contenu is not None:
        doublon = etat.deja_recus.get(sha) or etat.vus.get(sha)
    fichier = Fichier(
        **kwargs,
        client_id=etat.client_id,
        lot_id=etat.lot.id,
        nom_original=_nom_sur(chemin_relatif),
        chemin_relatif=chemin_relatif,
        sha256=sha,
        taille=taille,
        type_mime=MIME_CORPS_COURRIEL if corps_courriel else mime,
        statut=StatutFichier.refuse if motif else StatutFichier.ok,
        motif_refus=motif.value if motif else None,
        nombre_pages=nombre_pages,
        doublon_de=doublon,
    )
    if motif is None and contenu is not None and doublon is None:
        etat.vus[sha] = fichier.id
    recu = FichierRecu(
        fichier=fichier,
        contenu=contenu if motif not in (MotifRefus.trop_gros, MotifRefus.archive_dangereuse) else None,
        cle_idempotence=cle_idempotence_reception(sha, etat.client_id, etat.message_id),
        origine=origine,
        corps_courriel=corps_courriel,
    )
    etat.sortie.append(recu)
    return recu


def _normaliser_chemin(*parties: str) -> str:
    morceaux: list[str] = []
    for p in parties:
        for seg in p.replace("\\", "/").split("/"):
            if seg and seg != ".":
                morceaux.append(seg)
    return "/".join(morceaux)


def _traiter_octets(
    etat: _Etat, chemin_relatif: str, contenu: bytes, *, profondeur_zip: int, origine: str | None
):
    if not contenu:
        _ajouter(etat, chemin_relatif, contenu, motif=MotifRefus.vide, origine=origine)
        return
    if len(contenu) > etat.limites.taille_fichier:
        _ajouter(
            etat,
            chemin_relatif,
            None,
            mime="application/octet-stream",
            motif=MotifRefus.trop_gros,
            origine=origine,
            taille=len(contenu),
        )
        return
    mime = detecter_type(contenu, chemin_relatif)
    if mime == MIME_ZIP:
        _traiter_zip(etat, chemin_relatif, contenu, profondeur_zip=profondeur_zip + 1, origine=origine)
        return
    if mime == MIME_EML:
        # un courriel joint compte comme un niveau d'imbrication, comme une archive (D-1603)
        if profondeur_zip + 1 > etat.limites.zip_profondeur:
            _ajouter(
                etat,
                chemin_relatif,
                None,
                mime=MIME_EML,
                motif=MotifRefus.archive_dangereuse,
                origine=origine,
                taille=len(contenu),
            )
            return
        _traiter_eml_interne(etat, chemin_relatif, contenu, origine=origine, profondeur=profondeur_zip + 1)
        return
    _ajouter(etat, chemin_relatif, contenu, mime=mime, origine=origine)


def _est_lien_symbolique(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return info.create_system == 3 and stat.S_ISLNK(mode)


def _chemin_entree_dangereux(nom: str) -> bool:
    n = nom.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return True
    return any(seg == ".." for seg in n.split("/"))


def _lire_entree_bornee(z: zipfile.ZipFile, info: zipfile.ZipInfo, borne: int) -> bytes:
    """Lit une entrée en flux sans faire confiance à la taille annoncée (bombes de décompression)."""
    morceaux = []
    lu = 0
    with z.open(info) as f:
        while True:
            bloc = f.read(1024 * 1024)
            if not bloc:
                break
            lu += len(bloc)
            if lu > borne:
                raise _ArchiveDangereuse("taille décompressée au-delà de la limite")
            if info.compress_size and lu / max(info.compress_size, 1) > 100 * 4 and lu > 10 * _MO:
                raise _ArchiveDangereuse("taux de compression")
            morceaux.append(bloc)
    return b"".join(morceaux)


def _traiter_zip(
    etat: _Etat, chemin_relatif: str, contenu: bytes, *, profondeur_zip: int, origine: str | None
):
    lim = etat.limites
    base = str(PurePosixPath(chemin_relatif).with_suffix(""))
    prefixe_origine = f"{origine}!" if origine else ""
    try:
        z = zipfile.ZipFile(io.BytesIO(contenu))
    except _ERREURS_ENTREE:
        _ajouter(etat, chemin_relatif, contenu, mime=MIME_ZIP, motif=MotifRefus.corrompu, origine=origine)
        return
    with z:
        infos = z.infolist()
        motif_global: str | None = None
        if profondeur_zip > lim.zip_profondeur:
            motif_global = "archives imbriquées au-delà de la profondeur maximale"
        else:
            motif_global = _motif_conteneur(infos, lim)
        if motif_global is not None:
            _ajouter(
                etat,
                chemin_relatif,
                None,
                mime=MIME_ZIP,
                motif=MotifRefus.archive_dangereuse,
                origine=origine,
                taille=len(contenu),
            )
            return
        if not any(not i.is_dir() for i in infos):
            # archive sans aucun fichier : refusée « vide » (jamais un dépôt qui disparaît en silence, D-1600)
            _ajouter(
                etat,
                chemin_relatif,
                None,
                mime=MIME_ZIP,
                motif=MotifRefus.vide,
                origine=origine,
                taille=len(contenu),
            )
            return
        etat.archives.append((chemin_relatif, _sha(contenu), len(infos)))
        decompresse = 0
        for info in infos:
            if info.is_dir():
                continue
            nom = info.filename
            chemin_entree = _normaliser_chemin(base, nom)
            orig = f"{prefixe_origine}{chemin_relatif}!{nom}"
            if _chemin_entree_dangereux(nom) or _est_lien_symbolique(info):
                _ajouter(
                    etat,
                    _normaliser_chemin(base, _nom_sur(nom)),
                    None,
                    mime="application/octet-stream",
                    motif=MotifRefus.archive_dangereuse,
                    origine=orig,
                )
                continue
            if len([s for s in nom.split("/") if s]) > lim.zip_profondeur + 1:
                _ajouter(
                    etat,
                    chemin_entree,
                    None,
                    mime="application/octet-stream",
                    motif=MotifRefus.archive_dangereuse,
                    origine=orig,
                )
                continue
            if info.flag_bits & 0x1:
                _ajouter(
                    etat,
                    chemin_entree,
                    None,
                    mime="application/octet-stream",
                    motif=MotifRefus.protege,
                    origine=orig,
                )
                continue
            if info.file_size > lim.taille_fichier:
                _ajouter(
                    etat,
                    chemin_entree,
                    None,
                    mime="application/octet-stream",
                    motif=MotifRefus.trop_gros,
                    origine=orig,
                    taille=info.file_size,
                )
                continue
            try:
                donnees = _lire_entree_bornee(
                    z, info, min(lim.taille_fichier, lim.zip_taille_totale - decompresse)
                )
            except _ArchiveDangereuse:
                _ajouter(
                    etat,
                    chemin_entree,
                    None,
                    mime="application/octet-stream",
                    motif=MotifRefus.archive_dangereuse,
                    origine=orig,
                )
                return
            except _ERREURS_ENTREE:
                _ajouter(
                    etat,
                    chemin_entree,
                    None,
                    mime="application/octet-stream",
                    motif=MotifRefus.corrompu,
                    origine=orig,
                )
                continue
            decompresse += len(donnees)
            _traiter_octets(etat, chemin_entree, donnees, profondeur_zip=profondeur_zip, origine=orig)


# --- courriels ---------------------------------------------------------------------------------------


def _texte_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    return "\n".join(re.sub(r"[ \t]+", " ", ligne).strip() for ligne in h.splitlines()).strip()


class _CourrielTropImbrique(Exception):
    pass


def _octets_message_joint(partie: EmailMessage) -> bytes:
    """Octets d'un ``message/rfc822`` joint. Encodé en base64 ou quoted-printable (non conforme, mais courant),
    le parseur en fait un sous-message dont le corps est le texte encodé : on le décode ici."""
    interne = partie.get_payload()
    sous = interne[0] if isinstance(interne, list) and interne else None
    if sous is None:
        return partie.get_payload(decode=True) or b""
    cte = str(partie.get("Content-Transfer-Encoding", "")).strip().lower()
    if cte in ("base64", "quoted-printable"):
        brut = sous.as_bytes().lstrip(b"\r\n")
        try:
            return base64.b64decode(brut) if cte == "base64" else quopri.decodestring(brut)
        except (binascii.Error, ValueError):
            return b""
    return sous.as_bytes()


def _parties(msg: EmailMessage):
    """Parcours en profondeur **itératif** et borné (``msg.walk`` est récursif). Un ``message/rfc822`` nommé
    ou en pièce jointe est une pièce (sous-arbre non parcouru) ; un message transféré en ligne est parcouru."""
    pile: list[tuple[EmailMessage, int]] = [(msg, 0)]
    while pile:
        partie, prof = pile.pop()
        if prof > _PROFONDEUR_MIME:
            raise _CourrielTropImbrique
        yield partie
        if not partie.is_multipart() or _est_piece(partie):
            continue
        enfants = partie.get_payload()
        if isinstance(enfants, list):
            pile.extend((e, prof + 1) for e in reversed(enfants) if isinstance(e, email.message.Message))


def _est_piece(partie: EmailMessage) -> bool:
    if partie.get_content_type() != "message/rfc822":
        return False
    return bool(partie.get_filename()) or (partie.get_content_disposition() or "").lower() == "attachment"


def _corps_et_pieces(msg: EmailMessage) -> tuple[str, list[tuple[str, bytes]]]:
    pieces: list[tuple[str, bytes]] = []
    texte_brut: list[str] = []
    texte_html: list[str] = []
    for partie in _parties(msg):
        if _est_piece(partie):
            pieces.append(
                (
                    partie.get_filename() or f"piece_jointe_{len(pieces) + 1}.eml",
                    _octets_message_joint(partie),
                )
            )
            continue
        if partie.is_multipart():
            continue
        nom = partie.get_filename()
        dispo = (partie.get_content_disposition() or "").lower()
        ctype = partie.get_content_type()
        if nom or dispo == "attachment" or ctype == "message/rfc822":
            try:
                donnees = partie.get_payload(decode=True)
            except Exception:
                donnees = None
            if donnees is None and ctype == "message/rfc822":
                inner = partie.get_payload()
                if isinstance(inner, list) and inner:
                    donnees = inner[0].as_bytes()
            pieces.append((nom or f"piece_jointe_{len(pieces) + 1}", donnees or b""))
            continue
        if ctype in ("text/plain", "text/html"):
            try:
                contenu = partie.get_content()
            except Exception:
                brut = partie.get_payload(decode=True) or b""
                contenu = brut.decode("utf-8", "replace")
            (texte_brut if ctype == "text/plain" else texte_html).append(str(contenu))
    corps = "\n".join(texte_brut).strip() or _texte_html("\n".join(texte_html))
    return corps, pieces


def _ajouter_courriel(
    etat: _Etat,
    base: str,
    msg: EmailMessage,
    *,
    origine: str | None,
    brut: bytes,
    profondeur: int = 0,
    lu: tuple[str, list[tuple[str, bytes]]] | None = None,
):
    """Le message lui-même devient le fichier ``<base>.eml`` (sha256 du message ; contenu remis aux pages :
    le texte du corps, décodé) ; les pièces jointes sont rangées sous ``<base>/``."""
    corps, pieces = lu if lu is not None else _corps_et_pieces(msg)
    origine_c = origine or f"courriel:{etat.message_id or ''}"
    # Le corps est une donnée (document_support/courriel) : en-têtes utiles conservés comme texte.
    entete = []
    for h in ("From", "To", "Date", "Subject"):
        v = msg.get(h)
        if v:
            entete.append(f"{h}: {v}")
    texte = "\n".join(entete) + ("\n\n" if entete else "") + corps
    _ajouter(
        etat,
        f"{base}.eml",
        texte.encode("utf-8"),
        mime=MIME_TEXTE,
        origine=origine_c,
        corps_courriel=True,
        sha_source=_sha(brut),
    )
    vus: dict[str, int] = {}
    for nom, donnees in pieces:
        nom_sur = _nom_sur(nom)
        if nom_sur in vus:  # deux pièces de même nom : suffixe stable
            vus[nom_sur] += 1
            p = PurePosixPath(nom_sur)
            nom_sur = f"{p.stem}_{vus[nom_sur]}{p.suffix}"
        else:
            vus[nom_sur] = 1
        _traiter_octets(
            etat,
            _normaliser_chemin(base, nom_sur),
            donnees,
            profondeur_zip=profondeur,
            origine=f"{origine_c}!{nom_sur}",
        )


def _parser_eml(contenu: bytes) -> EmailMessage:
    return email.message_from_bytes(contenu, policy=email.policy.default)  # type: ignore[return-value]


def _traiter_eml_interne(
    etat: _Etat,
    chemin_relatif: str,
    contenu: bytes,
    *,
    origine: str | None,
    profondeur: int = 0,
    lu: tuple[str, list[tuple[str, bytes]]] | None = None,
):
    """Courriel trouvé dans un dépôt ou une archive : pas de liste blanche (canal de dépôt)."""
    try:
        msg = _parser_eml(contenu)
        lu = _corps_et_pieces(msg)  # structure lisible et imbrication bornée (avant tout ajout)
    except Exception:
        _ajouter(etat, chemin_relatif, contenu, mime=MIME_EML, motif=MotifRefus.corrompu, origine=origine)
        return
    base = str(PurePosixPath(chemin_relatif).with_suffix(""))
    _ajouter_courriel(
        etat, base, msg, origine=origine or chemin_relatif, brut=contenu, profondeur=profondeur, lu=lu
    )


# --- API publique ------------------------------------------------------------------------------------


def _nouveau_lot(
    client_id: str | None, canal: CanalLot, ids: IdGenerator | None, expediteur: str | None
) -> Lot:
    kwargs = {"id": ids.nouveau(Prefixe.lot)} if ids is not None else {}
    return Lot(**kwargs, client_id=client_id, canal=canal, expediteur=expediteur)


def _fin(etat: _Etat, **kw) -> Reception:
    return Reception(
        lot=etat.lot,
        fichiers=etat.sortie,
        archives=etat.archives,
        taille_totale=etat.taille_totale,
        message_id=etat.message_id,
        **kw,
    )


def recevoir_octets(
    elements: Iterable[tuple[str, bytes]],
    *,
    client_id: str | None = None,
    canal: CanalLot = CanalLot.depot,
    deja_recus: Mapping[str, str] | None = None,
    limites: Limites | None = None,
    ids: IdGenerator | None = None,
    lot: Lot | None = None,
) -> Reception:
    """Réception de fichiers en mémoire ``(chemin_relatif, octets)`` (dépôt ou API).

    ``deja_recus`` : ``{sha256: fichier_id}`` des fichiers déjà reçus pour ce client (§7.1).
    """
    lot = lot or _nouveau_lot(client_id, canal, ids, None)
    etat = _Etat(client_id, lot, limites or Limites(), ids, deja_recus or {})
    for chemin, contenu in elements:
        _traiter_sur(etat, _normaliser_chemin(chemin), contenu)
    return _fin(etat)


def _traiter_sur(etat: _Etat, chemin_relatif: str, contenu: bytes) -> None:
    """Filet de sécurité (§20.6, D-1600) : une erreur imprévue sur un fichier déposé le refuse « corrompu » ;
    elle n'interrompt jamais la réception des autres fichiers du lot."""
    try:
        _traiter_octets(etat, chemin_relatif, contenu, profondeur_zip=0, origine=None)
    except Exception as e:  # analyseurs tiers sur contenu hostile
        log.warning("reception_fichier_en_erreur exception=%s", type(e).__name__)
        _ajouter(
            etat,
            chemin_relatif,
            None,
            mime="application/octet-stream",
            motif=MotifRefus.corrompu,
            taille=len(contenu),
        )


def recevoir_chemin(
    chemin: str | Path,
    *,
    client_id: str | None = None,
    racine: str | Path | None = None,
    deja_recus: Mapping[str, str] | None = None,
    limites: Limites | None = None,
    ids: IdGenerator | None = None,
) -> Reception:
    """Réception d'un dossier (arborescence conservée, relative à ``racine`` ou au dossier) ou d'un fichier.

    Les liens symboliques ne sont pas suivis. Ordre de parcours trié (reproductible).
    """
    p = Path(chemin)
    lim = limites or Limites()
    lot = _nouveau_lot(client_id, CanalLot.depot, ids, None)
    etat = _Etat(client_id, lot, lim, ids, deja_recus or {})
    if p.is_dir():
        base = Path(racine) if racine is not None else p
        fichiers = sorted(x for x in p.rglob("*") if not x.is_symlink() and x.is_file())
        for f in fichiers:
            rel = f.relative_to(base).as_posix()
            _lire_et_traiter(etat, f, rel)
    else:
        base = Path(racine) if racine is not None else p.parent
        rel = p.relative_to(base).as_posix() if racine is not None else p.name
        if p.is_symlink():
            _ajouter(etat, rel, None, mime="application/octet-stream", motif=MotifRefus.non_supporte)
        else:
            _lire_et_traiter(etat, p, rel)
    return _fin(etat)


def _lire_et_traiter(etat: _Etat, f: Path, rel: str) -> None:
    try:
        taille = f.stat().st_size
        if taille > etat.limites.taille_fichier:
            _ajouter(
                etat, rel, None, mime="application/octet-stream", motif=MotifRefus.trop_gros, taille=taille
            )
            return
        contenu = f.read_bytes()
    except OSError as e:  # fichier illisible (droits, disparu) : refusé, le lot continue
        log.warning("reception_lecture_impossible exception=%s", type(e).__name__)
        _ajouter(etat, rel, None, mime="application/octet-stream", motif=MotifRefus.corrompu)
        return
    _traiter_sur(etat, rel, contenu)


def recevoir_courriel(
    contenu: bytes,
    *,
    client: Client | None = None,
    expediteurs_autorises: Iterable[str] | None = None,
    deja_recus: Mapping[str, str] | None = None,
    limites: Limites | None = None,
    ids: IdGenerator | None = None,
    dossier: str = "courriel",
) -> Reception:
    """Réception d'un message de la boîte dédiée (§7.1).

    Expéditeur hors liste blanche (``client.expediteurs_autorises`` ou ``expediteurs_autorises``) :
    lot en quarantaine, **aucun** fichier traité. Sinon : pièces jointes = fichiers d'entrée ; corps =
    ``corps_courriel.txt`` (``document_support/courriel``). Les fichiers sont rangés sous
    ``<dossier>/<message>/`` : chaque courriel forme sa propre frontière de regroupement (§7.5).
    """
    client_id = client.id if client is not None else None
    autorises = list(
        expediteurs_autorises
        if expediteurs_autorises is not None
        else (client.expediteurs_autorises if client is not None else [])
    )
    try:
        msg = _parser_eml(contenu)
        expediteur = parseaddr(str(msg.get("From", "")))[1] or None
        message_id = str(msg.get("Message-ID", "")).strip() or None
        lu = _corps_et_pieces(msg)  # structure lisible et imbrication bornée (D-1603)
    except Exception:
        lot = _nouveau_lot(client_id, CanalLot.courriel, ids, None)
        etat = _Etat(client_id, lot, limites or Limites(), ids, deja_recus or {})
        _ajouter(etat, f"{dossier}/message.eml", contenu, mime=MIME_EML, motif=MotifRefus.corrompu)
        return _fin(etat)
    lot = _nouveau_lot(client_id, CanalLot.courriel, ids, expediteur)
    etat = _Etat(client_id, lot, limites or Limites(), ids, deja_recus or {}, message_id=message_id)
    if not expediteur_autorise(expediteur, autorises):
        return _fin(etat, quarantaine=True, motif_quarantaine="expediteur_non_autorise")
    ident = hashlib.sha256((message_id or _sha(contenu)).encode()).hexdigest()[:12]
    _ajouter_courriel(
        etat, f"{dossier}/{ident}", msg, origine=f"courriel:{message_id or ident}", brut=contenu, lu=lu
    )
    return _fin(etat)


def recevoir(
    source: str | Path | bytes,
    *,
    nom: str | None = None,
    client: Client | None = None,
    client_id: str | None = None,
    **kw,
) -> Reception:
    """Point d'entrée commode : chemin (dossier ou fichier) ou octets (``nom`` requis).

    Des octets reconnus comme courriel passent par ``recevoir_courriel`` (liste blanche du client).
    """
    cid = client.id if client is not None else client_id
    if isinstance(source, bytes):
        if detecter_type(source, nom or "") == MIME_EML and client is not None:
            return recevoir_courriel(source, client=client, **kw)
        return recevoir_octets([(nom or "fichier", source)], client_id=cid, **kw)
    return recevoir_chemin(source, client_id=cid, **kw)
