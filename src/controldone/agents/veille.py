"""Agent ``veille`` (plateforme) : veille réglementaire sur le droit forfaitaire des petits envois, le
MACF/CBAM, la réforme du code des douanes de l'Union (et la facturation électronique).

Avec réseau (``CONTROLDONE_VEILLE_RESEAU=1`` ou option ``reseau``) : télécharge chaque source officielle
(liste blanche de domaines), compare l'empreinte du texte visible à l'instantané précédent et rédige une
**note interne** pour le fondateur (brouillon ``note_veille``, jamais publié). Sans réseau : chaque
source est rapportée « non vérifié ». La note signale des changements à relire ; elle n'analyse pas le
contenu et ne donne aucun avis.
"""

from __future__ import annotations

from controldone.agents.veille_sources import THEMES

from .base import Agent, ContexteAgent, RapportAgent

__all__ = ["LIBELLES_STATUT", "AgentVeille"]

LIBELLES_STATUT = {
    "nouveau": "première lecture (empreinte enregistrée)",
    "inchange": "inchangé depuis la dernière lecture",
    "modifie": "MODIFIÉ depuis la dernière lecture — à relire",
    "non_verifie": "non vérifié",
}


class AgentVeille(Agent):
    nom = "veille"
    role = ("Surveille les sources officielles (petits envois, MACF/CBAM, réforme du CDU, facturation "
            "électronique) et rédige pour le fondateur une note des pages modifiées, à relire.")
    outils = ("lire_sources", "telecharger_source", "lire_instantanes", "enregistrer_instantanes",
              "proposer_note_veille")
    plateforme = True
    periode = "semaine"

    def _executer(self, ctx: ContexteAgent, rapport: RapportAgent) -> None:
        now = ctx.maintenant()
        sources = self.appeler(ctx, "lire_sources")
        instantanes = dict(self.appeler(ctx, "lire_instantanes"))
        resultats = []
        for s in sources:
            r = self.appeler(ctx, "telecharger_source", url=s["url"])
            precedent = instantanes.get(s["url"])
            if r.get("statut") != "ok":
                statut = "non_verifie"
            elif precedent is None:
                statut = "nouveau"
            elif precedent.get("sha256") == r["sha256"]:
                statut = "inchange"
            else:
                statut = "modifie"
            if r.get("statut") == "ok":
                instantanes[s["url"]] = {"sha256": r["sha256"], "taille": str(r["taille"]), "vu_le": now.isoformat()}
            resultats.append({"theme": s["theme"], "url": s["url"], "statut": statut,
                              "motif": r.get("motif") or "", "titre": r.get("titre") or "",
                              "precedent": (precedent or {}).get("vu_le", "")})
        if any(x["statut"] != "non_verifie" for x in resultats):
            self.appeler(ctx, "enregistrer_instantanes", instantanes=instantanes)
        rapport.notes += [f"{x['statut']}:{x['theme']}" for x in resultats]
        lignes = [f"Note de veille réglementaire du {now.strftime('%d/%m/%Y')} — brouillon interne, jamais publié.",
                  "La note signale les pages officielles modifiées, à relire ; elle n'en analyse pas le contenu.", ""]
        if all(x["statut"] == "non_verifie" for x in resultats):
            lignes += ["Exécution hors ligne ou sources injoignables : aucune source n'a pu être vérifiée "
                       "(statut « non vérifié »).", ""]
        for theme, libelle in THEMES.items():
            du_theme = [x for x in resultats if x["theme"] == theme]
            if not du_theme:
                continue
            lignes.append(f"{libelle} :")
            for x in du_theme:
                detail = f" ({x['motif']})" if x["statut"] == "non_verifie" and x["motif"] else ""
                lignes.append(f"- {x['url']} : {LIBELLES_STATUT[x['statut']]}{detail}")
            lignes.append("")
        modifiees = sum(1 for x in resultats if x["statut"] == "modifie")
        objet = (f"Veille réglementaire : {modifiees} page(s) modifiée(s)" if modifiees
                 else "Veille réglementaire : aucune modification détectée"
                 if any(x["statut"] != "non_verifie" for x in resultats) else "Veille réglementaire : non vérifié")
        out = self.appeler(ctx, "proposer_note_veille", objet=objet, corps="\n".join(lignes),
                           cle=f"veille:{now.strftime('%Y-%m-%d')}",
                           sources=[{k: x[k] for k in ("url", "statut", "titre")} for x in resultats])
        rapport.propositions.append(out)
