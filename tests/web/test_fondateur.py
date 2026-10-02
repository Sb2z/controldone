"""Décisions du fondateur (§7.7), correction de valeur et recontrôle, file des sorties en un clic,
publication du rapport, dossier de réclamation, autonomie, tâches, journal."""

from __future__ import annotations

from aides_web import ADMIN_A, ADMIN_B, connecter_client, connecter_fondateur, executer_jobs, jeton, poster

from controldone.auth.roles import Acteur, Role
from controldone.outbox import FileSortante, StatutAction
from controldone.storage.models import Constat, Dossier, Resultat

A, B = "demo_ateliers", "demo_nord"
FONDATEUR = Acteur("usr_fondateur_demo", Role.fondateur)


def _constat(monde, tenant, cid):
    with monde.pf.db.tenant(tenant, Acteur.systeme("t"), lecture=True) as s:
        c = s.obtenir(Constat, cid)
        return c.statut_validation, c.niveau, c.commentaire_validation


def test_valider_publie_au_client(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    cid = monde.ids[B]["constat_propose"][0]
    r = poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{cid}/valider", {"retour": "/admin/validation"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/validation"
    assert _constat(monde, B, cid)[0] == "valide"
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)
    textes = "".join(c.get(f"/espace/dossiers/{d}").text for d in monde.ids[B]["dossier"])
    assert f"constat-{cid}" in textes


def test_rejet_exige_un_motif(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    cid = monde.ids[B]["constat_propose"][0]
    r = poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{cid}/rejeter", {"motif": "  "})
    assert r.status_code == 303
    assert _constat(monde, B, cid)[0] == "propose"
    r = poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{cid}/rejeter",
               {"motif": "lecture erronée, voir l'original"})
    assert _constat(monde, B, cid)[:1] == ("rejete",)
    assert _constat(monde, B, cid)[2] == "lecture erronée, voir l'original"
    # décision déjà prise : une seconde décision est refusée
    poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{cid}/valider")
    assert _constat(monde, B, cid)[0] == "rejete"


def test_retrograder_un_ecart_certain(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    with monde.pf.db.tenant(B, Acteur.systeme("t"), lecture=True) as s:
        certains = [c.id for c in s.lister(Constat) if c.niveau == "ecart_certain"]
    assert certains
    cid = certains[0]
    poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{cid}/retrograder", {"motif": ""})
    assert _constat(monde, B, cid)[1] == "ecart_certain"  # motif obligatoire
    poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{cid}/retrograder",
           {"motif": "montant à confirmer sur l'original"})
    statut, niveau, _ = _constat(monde, B, cid)
    assert niveau == "a_verifier" and statut == "propose"
    with monde.pf.db.tenant(B, Acteur.systeme("t"), lecture=True) as s:
        assert "retrograde_par_fondateur" in s.obtenir(Constat, cid).contenu["raisons"]


def test_aucune_promotion_directe(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    # constat « à vérifier » proposé : celui de la démonstration, à défaut un écart certain rétrogradé
    with monde.pf.db.tenant(B, Acteur.systeme("t"), lecture=True) as s:
        proposes = [c for c in s.lister(Constat) if c.statut_validation == "propose"]
    a_verifier = [c.id for c in proposes if c.niveau == "a_verifier"]
    cid = a_verifier[0] if a_verifier else proposes[0].id
    if not a_verifier:
        poster(f, "/admin/validation", f"/admin/clients/{B}/constats/{cid}/retrograder",
               {"motif": "montant à confirmer sur l'original"})
    t = jeton(f.get("/admin/validation").text)
    for chemin in ("promouvoir", "certain", "ecart_certain"):
        r = f.post(f"/admin/clients/{B}/constats/{cid}/{chemin}", data={"csrf": t}, follow_redirects=False)
        assert r.status_code in (404, 405)
    assert _constat(monde, B, cid)[1] == "a_verifier"


def test_correction_de_valeur_relance_les_controles(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    dossier = monde.ids[A]["dossier"][0]
    page = f.get(f"/admin/clients/{A}/dossiers/{dossier}").text
    import re

    m = re.search(r'name="document_id" value="([^"]+)"><input type="hidden" name="valeur_id" value="([^"]+)">', page)
    assert m
    doc_id, vs_id = m.groups()
    r = poster(f, f"/admin/clients/{A}/dossiers/{dossier}", f"/admin/clients/{A}/dossiers/{dossier}/corriger",
               {"document_id": doc_id, "valeur_id": vs_id, "valeur": "", "motif": "x"})
    assert r.status_code == 303  # valeur vide : refus (message)
    with monde.pf.db.tenant(A, Acteur.systeme("t"), lecture=True) as s:
        v0 = s.obtenir(Dossier, dossier).version
    # confirmation de la même valeur (saisie humaine)
    from controldone.model.documents import Document as DocumentModele
    from controldone.storage.models import Document

    with monde.pf.db.tenant(A, Acteur.systeme("t"), lecture=True) as s:
        doc = DocumentModele.model_validate(s.obtenir(Document, doc_id).contenu)
    ancienne = next(v for v in doc.valeurs() if v.id == vs_id)
    r = poster(f, f"/admin/clients/{A}/dossiers/{dossier}", f"/admin/clients/{A}/dossiers/{dossier}/corriger",
               {"document_id": doc_id, "valeur_id": vs_id, "valeur": ancienne.valeur_brute or ancienne.valeur,
                "motif": "confirmé sur l'original (test FICTIF)"})
    assert r.status_code == 303
    with monde.pf.db.tenant(A, Acteur.systeme("t"), lecture=True) as s:
        assert s.obtenir(Dossier, dossier).version == v0 + 1
        doc = DocumentModele.model_validate(s.obtenir(Document, doc_id).contenu)
        nouvelle = next(v for v in doc.valeurs() if v.remplace == vs_id)
        assert nouvelle.methode.value == "saisie_humaine" and nouvelle.confiance == 1.0
        assert len(s.corrections(dossier)) == 1
    assert executer_jobs(monde) >= 1
    with monde.pf.db.tenant(A, Acteur.systeme("t"), lecture=True) as s:
        versions = {r.dossier_version for r in s.lister(Resultat, dossier_id=dossier)}
        assert v0 + 1 in versions
    # la page affiche la correction et les contrôles de la nouvelle version
    page = f.get(f"/admin/clients/{A}/dossiers/{dossier}").text
    assert "confirmé sur l&#39;original" in page or "confirmé sur l'original" in page


def test_correction_d_un_document_hors_dossier_refusee(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    d0, d1 = monde.ids[A]["dossier"][:2]
    page = f.get(f"/admin/clients/{A}/dossiers/{d1}").text
    import re

    doc_id, vs_id = re.search(r'name="document_id" value="([^"]+)"><input type="hidden" name="valeur_id" '
                              r'value="([^"]+)">', page).groups()
    r = poster(f, f"/admin/clients/{A}/dossiers/{d0}", f"/admin/clients/{A}/dossiers/{d0}/corriger",
               {"document_id": doc_id, "valeur_id": vs_id, "valeur": "1", "motif": "x"})
    assert r.status_code == 404


def test_file_des_sorties_approuver_en_un_clic(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    fs = FileSortante(monde.pf.db)
    brouillons = fs.lister(FONDATEUR, statuts=["brouillon"])
    assert brouillons, "un dossier de réclamation attend l'approbation"
    action = brouillons[0]
    r = poster(f, "/admin/validation", f"/admin/sorties/{action.id}/approuver")
    assert r.status_code == 303
    a = fs.obtenir(action.id, FONDATEUR)
    assert a.statut is StatutAction.envoye  # approuvé puis mis à disposition du client
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    assert action.id in c.get("/espace/rapports").text
    r = c.get(f"/espace/rapports/{action.id}/pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    texte = c.get(f"/espace/rapports/{action.id}/txt").text
    assert "avoir" in texte and "ControlDOne" not in texte.split("Ce document est")[0]


def test_file_des_sorties_refus_exige_un_motif(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    fs = FileSortante(monde.pf.db)
    action = fs.lister(FONDATEUR, statuts=["brouillon"])[0]
    poster(f, "/admin/validation", f"/admin/sorties/{action.id}/refuser", {"motif": ""})
    assert fs.obtenir(action.id, FONDATEUR).statut is StatutAction.brouillon
    poster(f, "/admin/validation", f"/admin/sorties/{action.id}/refuser", {"motif": "montants à revoir"})
    assert fs.obtenir(action.id, FONDATEUR).statut is StatutAction.refuse
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    assert c.get(f"/espace/rapports/{action.id}/pdf").status_code == 404


def test_correction_d_une_sortie_bloquee_par_les_garde_fous(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    fs = FileSortante(monde.pf.db)
    action = fs.lister(FONDATEUR, statuts=["brouillon"])[0]
    poster(f, "/admin/validation", f"/admin/sorties/{action.id}/corriger",
           {"objet": "Demande", "corps": "Nous réclamons le remboursement des droits."})
    a = fs.obtenir(action.id, FONDATEUR)
    assert a.statut is StatutAction.brouillon and a.motif_blocage


def test_publication_d_un_rapport(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    r = poster(f, f"/admin/clients/{B}", f"/admin/clients/{B}/publier")
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/validation")
    fs = FileSortante(monde.pf.db)
    nouveaux = [a for a in fs.lister(FONDATEUR, statuts=["brouillon"], tenant_id=B) if a.kind.value == "rapport_publication"]
    assert len(nouveaux) == 1
    c = monde.client()
    connecter_client(c, monde, ADMIN_B)
    assert c.get(f"/espace/rapports/{nouveaux[0].id}/pdf").status_code == 404  # pas encore approuvé
    poster(f, "/admin/validation", f"/admin/sorties/{nouveaux[0].id}/approuver")
    r = c.get(f"/espace/rapports/{nouveaux[0].id}/html?afficher=1")
    assert r.status_code == 200 and "script-src" not in r.headers["content-security-policy"]
    assert "default-src 'none'" in r.headers["content-security-policy"]
    # rapport figé sur les constats validés : aucun constat de B n'est validé
    j = c.get(f"/espace/rapports/{nouveaux[0].id}/json").json()
    assert all(not d["constats"] for d in j["dossiers"])


def test_client_rapport_publie_ne_contient_que_les_valides(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    rid = monde.ids[A]["sortie_envoyee"][0]
    j = c.get(f"/espace/rapports/{rid}/json").json()
    ids = {k["finding_id"] for d in j["dossiers"] for k in d["constats"]}
    assert ids == set(monde.ids[A]["constat_valide"])


def test_autonomie_par_type(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    fs = FileSortante(monde.pf.db)
    assert all(fs.autonomie(k).value == "manuel" for k in ("rapport_publication", "reclamation_dossier"))
    poster(f, "/admin/autonomie", "/admin/autonomie", {"kind": "email_client", "mode": "auto"})
    assert fs.autonomie("email_client").value == "auto"


def test_relancer_une_tache_morte(monde):
    from controldone.storage.file_jobs import JobStore

    store = JobStore(monde.pf.db)
    job, _ = store.enqueue("inconnu_test", {}, "inconnu_test:1", A)
    executer_jobs(monde)
    assert store.obtenir(job.id).statut == "dead"
    f = monde.client()
    connecter_fondateur(f, monde)
    assert "inconnu_test" in f.get("/admin/jobs").text
    assert "Tâche morte" in f.get("/admin/alertes").text
    poster(f, "/admin/jobs", f"/admin/jobs/{job.id}/relancer")
    assert store.obtenir(job.id).statut == "pending"


def test_journal_et_chaine(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    page = f.get("/admin/journal").text
    assert "Chaîne intacte" in page and "acces_admin" in page


def test_creation_client_utilisateur_entite_transitaire_grille(monde):
    f = monde.client()
    connecter_fondateur(f, monde)
    r = poster(f, "/admin/clients", "/admin/clients", {"raison_sociale": "NÉGOCE TEST FICTIF", "offre": "continu"})
    tid = r.headers["location"].rsplit("/", 1)[1]
    base = f"/admin/clients/{tid}"
    r = poster(f, base, f"{base}/utilisateurs", {"email": "compta@negoce-fictif.test", "role": "client_admin"})
    assert r.status_code == 200 and "Mot de passe provisoire" in r.text
    poster(f, base, f"{base}/entites", {"raison_sociale": "NÉGOCE TEST FICTIF", "tva": "FR00999999999"})
    poster(f, base, f"{base}/transitaires", {"nom": "TRANSIT TEST FICTIF"})
    page = f.get(base).text
    assert "NÉGOCE TEST FICTIF" in page and "TRANSIT TEST FICTIF" in page
    import re

    tr = re.search(r'<select id="g-tr" name="transitaire_id" required><option value="([^"]+)"', page).group(1)
    csv = ("code_poste;nature;mode;prix;devise;libelles_reconnus\n"
           "DEDOUANEMENT;frais_dedouanement;forfait;55,00;EUR;dédouanement|frais de dédouanement\n")
    t = jeton(page)
    r = f.post(f"{base}/grilles", data={"csrf": t, "transitaire_id": tr, "reference": "DEVIS FICTIF 1"},
               files={"fichier": ("grille.csv", csv.encode(), "text/csv")}, follow_redirects=False)
    assert r.status_code == 303
    page = f.get(base).text
    assert "Brouillon" in page
    gid = re.search(r'name="grille_id" value="([^"]+)"', page).group(1)
    poster(f, base, f"{base}/grilles/valider", {"grille_id": gid, "version": "1"})
    assert "Validée" in f.get(base).text
    r = poster(f, base, f"{base}/cles-api", {"nom": "ERP", "role": "client_lecteur"})
    assert "cdk_" in r.text
