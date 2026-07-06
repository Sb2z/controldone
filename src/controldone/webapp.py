"""Local web interface for ControlDOne."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import threading
import webbrowser
import zipfile

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from controldone.ocr import configure_tesseract, find_tesseract_executable
from controldone.pipeline import analyze
from controldone.profile import ProfileError, list_profiles, load_profile
from controldone import reporting_json
from controldone.reporting import write_report_v4
from controldone.paths import app_root


ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".zip"}
STATUS_ORDER = ["KO_BLOQUANT", "MANQUE_DOC", "KO", "OK_A_CONTROLER", "A_VERIFIER", "OK"]
BASE_DIR = app_root()
DATA_DIR = BASE_DIR / "data"
APP_JOBS_DIR = DATA_DIR / "app_jobs"
OUTPUT_DIR = DATA_DIR / "output"


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "web" / "templates"),
        static_folder=str(Path(__file__).parent / "web" / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

    @app.get("/")
    def index():
        return render_template("index.html", health=_runtime_health())

    @app.get("/health")
    def health():
        return jsonify(_runtime_health())

    @app.post("/run")
    def run_analysis():
        job_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(4)
        job_dir = APP_JOBS_DIR / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        try:
            uploaded = [f for f in request.files.getlist("files") if f and f.filename]
            local_path = (request.form.get("local_path") or "").strip()
            client = (request.form.get("client") or request.args.get("client") or "").strip()
            input_path = _prepare_input(uploaded, local_path, input_dir)

            def progress(current: int, total: int, path: str) -> None:
                try:
                    rel = os.path.relpath(path, input_path if Path(input_path).is_dir() else Path(input_path).parent)
                except Exception:
                    rel = os.path.basename(path)
                print(f"[{current}/{total}] Analyse: {rel}", flush=True)

            profile = load_profile(client) if client else None
            result = analyze(str(input_path), progress=progress, profile=profile)
            report_name = f"controle_douane_app_{dt.datetime.now():%Y%m%d_%H%M%S}_{job_id}.xlsx"
            report_path = OUTPUT_DIR / report_name
            write_report_v4(result.bundles, str(report_path), result.errors)

            counts = Counter(bundle.status for bundle in result.bundles)
            summary = {
                "documents": len(result.documents),
                "bundles": len(result.bundles),
                "errors": len(result.errors),
                "statuses": [(status, counts[status]) for status in STATUS_ORDER if counts[status]],
            }
            if _wants_json():
                payload = reporting_json.run_to_dict(
                    result.bundles, result.errors, len(result.documents),
                    report_path=str(report_path),
                )
                payload["report_url"] = f"/download/{report_name}"
                return jsonify(payload)
            return render_template(
                "index.html",
                health=_runtime_health(),
                summary=summary,
                report_name=report_name,
                report_url=f"/download/{report_name}",
                errors=result.errors[:20],
            )
        except ProfileError as exc:
            if _wants_json():
                return jsonify({"error": f"profil client : {exc}"}), 400
            return render_template(
                "index.html",
                health=_runtime_health(),
                fatal_error=f"Profil client : {exc}",
            ), 400
        except Exception as exc:
            if _wants_json():
                return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 400
            return render_template(
                "index.html",
                health=_runtime_health(),
                fatal_error=f"{type(exc).__name__}: {exc}",
            ), 400

    @app.get("/clients")
    def clients():
        return jsonify({"clients": list_profiles(), "default": os.environ.get("CONTROLDONE_CLIENT")})

    @app.get("/download/<path:filename>")
    def download(filename: str):
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

    return app


def _wants_json() -> bool:
    if request.args.get("format") == "json":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _prepare_input(uploaded: list[FileStorage], local_path: str, input_dir: Path) -> Path:
    if uploaded:
        saved_paths = []
        for file in uploaded:
            suffix = Path(file.filename).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                continue
            relative = _safe_relative_upload_path(file.filename)
            destination = input_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            file.save(destination)
            saved_paths.append(destination)
            if suffix == ".zip":
                extract_dir = input_dir / destination.stem
                _safe_extract_zip(destination, extract_dir)
        if not saved_paths:
            raise ValueError("Aucun fichier exploitable. Formats acceptes: PDF, XLS, XLSX, ZIP.")
        if len(saved_paths) == 1 and saved_paths[0].suffix.lower() != ".zip":
            return saved_paths[0]
        return input_dir

    if local_path:
        candidate = Path(local_path).expanduser().resolve()
        if not candidate.exists():
            raise ValueError(f"Chemin introuvable: {candidate}")
        if candidate.is_file() and candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("Le chemin fourni doit pointer vers un dossier, PDF, XLS, XLSX ou ZIP.")
        if candidate.suffix.lower() == ".zip":
            extract_dir = input_dir / candidate.stem
            _safe_extract_zip(candidate, extract_dir)
            return extract_dir
        return candidate

    raise ValueError("Ajoute des fichiers ou renseigne un chemin local.")


def _safe_relative_upload_path(filename: str) -> Path:
    parts = []
    for raw in Path(filename).parts:
        clean = secure_filename(raw)
        if clean and clean not in {".", ".."} and not clean.startswith("."):
            parts.append(clean)
    if not parts:
        parts = ["upload"]
    return Path(*parts)


def _safe_extract_zip(zip_path: Path, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or name.startswith("__MACOSX/") or "/._" in name or Path(name).name.startswith("."):
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS - {".zip"}:
                continue
            target = extract_dir / _safe_relative_upload_path(name)
            resolved = target.resolve()
            if not str(resolved).startswith(str(extract_dir.resolve())):
                raise ValueError(f"Archive ZIP non sure: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)


def _runtime_health() -> dict:
    tesseract_path = configure_tesseract() or find_tesseract_executable()
    version = ""
    if tesseract_path:
        try:
            completed = subprocess.run(
                [tesseract_path, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = (completed.stdout or completed.stderr).splitlines()[0]
        except Exception:
            version = "tesseract detecte"
    return {
        "tesseract": bool(tesseract_path),
        "tesseract_version": version,
        "tesseract_path": tesseract_path or "",
        "output_dir": str(OUTPUT_DIR),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ControlDOne local web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="Ouvre automatiquement le navigateur.")
    args = parser.parse_args()

    app = create_app()
    if args.open_browser:
        url = f"http://{args.host}:{args.port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # Werkzeug debugger exposes a console on error pages; developer-only,
    # behind an explicit env var rather than a CLI flag.
    debug = os.environ.get("CONTROLDONE_FLASK_DEBUG") == "1"
    app.run(host=args.host, port=args.port, debug=debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
