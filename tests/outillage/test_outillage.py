"""Outillage du dépôt (D-3901–D-3904) : vérifications avant enregistrement, empreinte des corpus, résumé de
couverture, cohérence des recettes consignées."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[2]


def _module(chemin: str):
    spec = importlib.util.spec_from_file_location(Path(chemin).stem + "_outil", RACINE / chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verifs = _module("scripts/precommit/verifs.py")
corpus = _module("scripts/corpus.py")
couverture = _module("scripts/couverture_paquets.py")


# --- vérifications avant enregistrement ------------------------------------------------------------------------


def test_secrets_detectes(tmp_path):
    f = tmp_path / "conf.py"
    cle_stripe = (
        "sk_" + "live_" + "A1b2C3d4E5f6G7h8I9j0"
    )  # assemblée : ce fichier ne doit pas déclencher le crochet
    cle_pem = "-----BEGIN " + "RSA PRIVATE KEY-----"
    f.write_text(
        f'X = "{cle_stripe}"\nY = 1\n{cle_pem}\nZ = "{cle_stripe}"  # pragma: allowlist secret\n',
        encoding="utf-8",
    )
    constats = verifs.secrets([f])
    assert [c.split(":")[1] for c in constats] == ["1", "3"]


def test_secrets_valeurs_fictives_du_depot_tolerees(tmp_path):
    f = tmp_path / "t.py"
    f.write_text(
        'k = "sk_live_FICTIVE"\nm = "sk-ant-fictif"\nr = r"sk_live_[A-Za-z0-9]{8,}"\n', encoding="utf-8"
    )
    assert verifs.secrets([f]) == []


def test_espaces_fin_de_ligne(tmp_path):
    py, md = tmp_path / "a.py", tmp_path / "a.md"
    py.write_text("x = 1 \ny = 2\n\t\n", encoding="utf-8")
    md.write_text("ligne forcée  \nmauvaise \n  \n", encoding="utf-8")
    assert [c.split(":")[1] for c in verifs.espaces([py])] == ["1", "3"]
    assert [c.split(":")[1] for c in verifs.espaces([md])] == ["2", "3"]


def test_fichiers_lourds(tmp_path):
    gros, petit = tmp_path / "gros.bin", tmp_path / "petit.bin"
    gros.write_bytes(b"\0" * (3 * 1024 + 1))
    petit.write_bytes(b"\0" * 10)
    assert len(verifs.lourds([gros, petit], max_ko=3)) == 1


def test_syntaxe_json_yaml(tmp_path):
    bon, mauvais, y = tmp_path / "a.json", tmp_path / "b.json", tmp_path / "c.yaml"
    bon.write_text('{"a": 1}', encoding="utf-8")
    mauvais.write_text('{"a": 1,}', encoding="utf-8")
    y.write_text("a: [1, 2\n", encoding="utf-8")
    assert len(verifs.syntaxe([bon, mauvais, y])) == 2


def test_print_interdit_dans_le_coeur(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def f():\n    print('x')\n# print( en commentaire\nimprimer = 'print('\n", encoding="utf-8")
    assert [c.split(":")[1] for c in verifs.sans_print([f])] == ["2"]


def test_configuration_pre_commit():
    conf = yaml.safe_load((RACINE / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    crochets = {h["id"]: h for r in conf["repos"] for h in r["hooks"]}
    assert {
        "ruff",
        "espaces-fin-de-ligne",
        "fichiers-lourds",
        "secrets",
        "syntaxe-json-yaml",
        "pas-de-print",
    } <= set(crochets)
    assert all(r["repo"] == "local" for r in conf["repos"])  # hors ligne
    assert re.search(conf["exclude"], "bench/corpus_g6/holdout/GV0001/truth.json")
    for h in crochets.values():
        assert (RACINE / h["entry"].split()[0]).is_file()


def test_main_verifs_code_retour(tmp_path, capsys):
    f = tmp_path / "x.txt"
    f.write_text("ok\n", encoding="utf-8")
    assert verifs.main(["espaces", str(f)]) == 0
    f.write_text("ko \n", encoding="utf-8")
    assert verifs.main(["espaces", str(f)]) == 1
    assert verifs.main(["lourds", "--max-ko", "1", str(f)]) == 0


# --- corpus non versionnés --------------------------------------------------------------------------------------


def _faux_corpus(racine: Path) -> None:
    for i, contenu in enumerate(["a", "b", "c"]):
        d = racine / "holdout" / f"GV000{i}"
        d.mkdir(parents=True)
        (d / "truth.json").write_text(json.dumps({"x": contenu}), encoding="utf-8")


def test_empreinte_identique_au_pipeline_shell(tmp_path):
    _faux_corpus(tmp_path)
    attendu, n = corpus.empreinte(tmp_path)
    assert n == 3
    if shutil.which("sha256sum") and shutil.which("xargs"):
        shell = subprocess.run(
            "find holdout -name truth.json | LC_ALL=C sort | xargs sha256sum | sha256sum",
            shell=True,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[0]
        assert shell == attendu
    lignes = "".join(
        f"{hashlib.sha256((tmp_path / p).read_bytes()).hexdigest()}  {p}\n"
        for p in sorted(f"holdout/GV000{i}/truth.json" for i in range(3))
    )
    assert attendu == hashlib.sha256(lignes.encode()).hexdigest()


def test_verifier_corpus(tmp_path, capsys):
    _faux_corpus(tmp_path)
    bon, _ = corpus.empreinte(tmp_path)
    assert corpus.verifier(tmp_path, bon, 3)
    assert not corpus.verifier(tmp_path, "0" * 64)
    assert not corpus.verifier(tmp_path / "absent", bon)
    assert corpus.main(["verifier", str(tmp_path), "--attendu", bon]) == 0


def test_recette_g6_conforme_au_backlog():
    """L'empreinte et la commande de corpus_g6 consignées par l'orchestrateur sont celles de la recette."""
    r = corpus.recettes()["corpus_g6"]
    backlog = (RACINE / "docs" / "backlog" / "orchestrateur.md").read_text(encoding="utf-8")
    assert r.get("sha256_historique", r["sha256"]) in backlog
    cmd = " ".join(corpus.commande(r, Path("bench/corpus_g6"), 2)[1:])
    for morceau in [
        "-m bench.generator2",
        "--out bench/corpus_g6",
        "--prefix GV",
        "--count 160",
        "--seed 20261008",
        "--split holdout",
        "--per-control 3",
        "--ext",
        "--all-holdout",
    ]:
        assert morceau in cmd
        assert morceau.split()[-1] in re.sub(r"\s+", " ", backlog)


def test_corpus_futurs_ignores_anciens_suivis():
    if not (RACINE / ".git").exists() or not shutil.which("git"):
        pytest.skip("hors dépôt git")

    def ignore(chemin: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", chemin], cwd=RACINE).returncode == 0

    assert ignore("bench/corpus_g9/holdout/GX0001/truth.json")
    assert ignore("bench/corpus_g6/manifest.json")
    for suivi in (
        "bench/corpus_g3/x.json",
        "bench/corpus_g4/x.json",
        "bench/corpus_g5/x.json",
        "bench/corpus_empreintes.json",
        "bench/README.md",
    ):
        assert not ignore(suivi), suivi


# --- résumé de couverture --------------------------------------------------------------------------------------


def test_resume_couverture_par_paquet(tmp_path):
    def f(cl, n, cb=0, nb=0):
        return {
            "summary": {
                "covered_lines": cl,
                "num_statements": n,
                "covered_branches": cb,
                "num_branches": nb,
                "percent_covered": 100 * (cl + cb) / (n + nb),
                "missing_lines": n - cl,
                "num_partial_branches": 0,
            }
        }

    donnees = {
        "files": {
            "src/controldone/controls/famille_a.py": f(50, 100, 10, 20),
            "src/controldone/normalize/amounts.py": f(95, 100),
            "src/controldone/cli.py": f(10, 100),
        },
        "totals": {
            "covered_lines": 155,
            "num_statements": 300,
            "covered_branches": 10,
            "num_branches": 20,
            "percent_covered": 51.5,
        },
    }
    texte, global_ = couverture.resumer(donnees, 2)
    assert global_ == 51.5
    assert "| `controls` | 50.0 % (50/100) | 50.0 % (10/20) | 50.0 % |" in texte
    assert "`(racine)`" in texte
    critiques = texte.split("moins couverts")[1]
    assert critiques.index("famille_a") < critiques.index("amounts") and "cli.py" not in critiques
    j = tmp_path / "c.json"
    j.write_text(json.dumps(donnees), encoding="utf-8")
    assert couverture.main([str(j), "--out", str(tmp_path / "p.md"), "--min", "60"]) == 1
    assert couverture.main([str(j), "--out", str(tmp_path / "p.md")]) == 0


def test_empreinte_pixels_insensible_a_l_encodage_tiff(tmp_path, capsys):
    """Mêmes pixels, octets différents (ici : compression différente, en pratique un octet de remplissage) :
    l'empreinte exacte change, l'empreinte des pixels non ; des pixels différents la changent."""
    from PIL import Image

    def corpus_tiff(racine: Path, compression: str, couleur: int) -> None:
        d = racine / "holdout" / "GV0001"
        (d / "docs").mkdir(parents=True)
        Image.new("L", (16, 8), couleur).save(d / "docs" / "scan.tif", compression=compression)
        sha = hashlib.sha256((d / "docs" / "scan.tif").read_bytes()).hexdigest()
        (d / "truth.json").write_text(
            json.dumps({"files": [{"path": "docs/scan.tif", "sha256": sha}]}), encoding="utf-8"
        )

    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    corpus_tiff(a, "raw", 200)
    corpus_tiff(b, "tiff_lzw", 200)
    corpus_tiff(c, "raw", 10)
    assert corpus.empreinte(a)[0] != corpus.empreinte(b)[0]
    assert corpus.empreinte_pixels(a) == corpus.empreinte_pixels(b)
    assert corpus.empreinte_pixels(a)[0] != corpus.empreinte_pixels(c)[0]
    attendu, pixels = corpus.empreinte(a)[0], corpus.empreinte_pixels(a)[0]
    assert corpus.verifier(b, attendu, 1, pixels)
    assert "remplissage" in capsys.readouterr().out
    assert not corpus.verifier(c, attendu, 1, pixels)
    assert not corpus.verifier(b, attendu, 2, pixels)  # nombre de dossiers différent


# --- TIFF déterministes et recettes de tous les corpus (D-4402, D-4403) ----------------------------------------


def _pixels(data: bytes) -> list:
    import io

    from PIL import Image, ImageSequence

    with Image.open(io.BytesIO(data)) as im:
        return [
            (p.mode, p.size, p.tobytes(), sorted((k, v) for k, v in p.tag_v2.items() if k not in (273, 279)))
            for p in ImageSequence.Iterator(im)
        ]


@pytest.mark.parametrize("encodage", ["png", "png1"])
def test_tiff_canonique_pixels_inchanges_octets_libres_a_zero(encodage):
    """Tout octet que la structure TIFF ne référence pas (remplissage d'alignement laissé non initialisé par
    libtiff, en-têtes de page résiduels) est mis à zéro ; pixels et étiquettes inchangés."""
    from bench.generator2 import degrade
    from PIL import Image, ImageDraw

    pages = []
    for i, (w, h) in enumerate([(37, 21), (19, 33), (25, 25)]):
        im = Image.new("L", (w, h), 255)
        ImageDraw.Draw(im).line((0, i, w, h - i), fill=40 * i, width=3)
        pages.append((im, encodage))
    canon = degrade.images_to_tiff(pages, 200)
    assert degrade.tiff_canonique(canon) == canon
    libres = []
    for p in range(8, len(canon)):  # un octet libre peut valoir n'importe quoi : même TIFF canonique
        x = bytearray(canon)
        x[p] ^= 0xA5
        try:
            if degrade.tiff_canonique(bytes(x)) == canon:
                libres.append(p)
        except (ValueError, KeyError, __import__("struct").error):
            pass
    assert libres and all(canon[p] == 0 for p in libres)
    sale = bytearray(canon)
    for p in libres:
        sale[p] = 0x5C
    assert _pixels(bytes(sale)) == _pixels(canon)
    assert degrade.tiff_canonique(bytes(sale)) == canon
    with pytest.raises(ValueError):
        degrade.tiff_canonique(b"%PDF-1.4")


def _corpus_avec_tiff(racine: Path, compression: str) -> None:
    from PIL import Image

    d = racine / "holdout" / "GV0001"
    (d / "docs").mkdir(parents=True)
    Image.new("L", (16, 8), 200).save(d / "docs" / "scan.tif", compression=compression)
    (d / "docs" / "a.pdf").write_bytes(b"%PDF-1.4 fictif")
    sha = hashlib.sha256((d / "docs" / "scan.tif").read_bytes()).hexdigest()
    verite = json.dumps({"files": [{"path": "docs/scan.tif", "sha256": sha}]}).encode()
    (d / "truth.json").write_bytes(verite)
    manifeste = {
        "dossiers": [
            {
                "truth_sha256": hashlib.sha256(verite).hexdigest(),
                "files": [{"path": "holdout/GV0001/docs/scan.tif", "sha256": sha}],
            }
        ]
    }
    (racine / "manifest.json").write_text(json.dumps(manifeste), encoding="utf-8")
    (racine / "stats_generation.json").write_text(json.dumps({"seconds": len(compression)}), encoding="utf-8")


def test_empreinte_arbre_complete_et_pixels(tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    _corpus_avec_tiff(a, "raw")
    _corpus_avec_tiff(b, "tiff_lzw")
    assert corpus.empreinte_arbre(a) != corpus.empreinte_arbre(b)
    assert corpus.empreinte_arbre(a, pixels=True) == corpus.empreinte_arbre(b, pixels=True)
    assert corpus.empreinte_arbre(a)[1] == 4  # stats_generation.json (durée) exclu
    e = corpus.empreintes(a)
    assert corpus.verifier(b, e["sha256"], 1, e["sha256_pixels"], e["sha256_arbre"], e["sha256_arbre_pixels"])
    assert "pixels" in capsys.readouterr().out
    (b / "holdout" / "GV0001" / "docs" / "a.pdf").write_bytes(b"%PDF-1.4 autre")  # hors truth.json
    assert not corpus.verifier(
        b, e["sha256"], 1, e["sha256_pixels"], e["sha256_arbre"], e["sha256_arbre_pixels"]
    )
    assert corpus.verifier(a, ["0" * 64, e["sha256"]], 1)  # plusieurs empreintes exactes admises


def test_recettes_de_tous_les_corpus():
    """Chaque corpus du banc a sa recette et toutes ses empreintes ; commande du générateur 1 sans options 2."""
    rs = corpus.recettes()
    assert {
        "corpus",
        "corpus_h2",
        "corpus_g2",
        "corpus_g3",
        "corpus_g4",
        "corpus_g5",
        "corpus_g6",
        "corpus_g7",
    } <= set(rs)
    for nom, r in rs.items():
        assert r["sortie"] == f"bench/{nom}"
        for cle in ("dossiers", "sha256", "sha256_pixels", "sha256_arbre", "sha256_arbre_pixels"):
            assert re.fullmatch(r"[0-9a-f]{64}", str(r[cle])) or cle == "dossiers", (nom, cle)
    cmd = corpus.commande(rs["corpus_h2"], Path("x"), 2)
    assert cmd[1:3] == ["-m", "bench.generator"] and "--prefix" not in cmd and "--seed" in cmd
    makefile = (RACINE / "Makefile").read_text(encoding="utf-8")
    assert "corpus-tous:" in makefile and "verifier $(if $(CORPUS),$(CORPUS),--tous)" in makefile
