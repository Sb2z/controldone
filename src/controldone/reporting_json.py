"""Machine-readable rendering of a control run.

The Excel report targets humans; this module targets machines. It turns the
result of ``pipeline.analyze`` into plain dicts/JSON so the engine can sit
inside any orchestrator (n8n, Power Automate, cron + webhook...) without
screen-scraping: one stable summary shape, one entry per dossier, one entry
per check.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from typing import List, Tuple

from controldone.models import Bundle

BLOCKING_STATUSES = {"KO_BLOQUANT", "KO", "MANQUE_DOC"}


def bundle_to_dict(bundle: Bundle) -> dict:
    return {
        "ref_prestation_no": bundle.ref_prestation_no,
        "ref_awb_lta": bundle.ref_awb_lta,
        "ref_mrn": bundle.ref_mrn,
        "status": bundle.status,
        "source_files": list(bundle.source_files),
        "invoices": [d.source_file for d in bundle.invoices],
        "declarations": [d.source_file for d in bundle.declarations],
        "prestation": bundle.prestation.source_file if bundle.prestation else None,
        "notes": list(bundle.notes),
        "checks": [
            {
                "code": c.code,
                "section": c.section,
                "label": c.label,
                "status": c.status,
                "severity": c.severity,
                "blocking": c.is_blocking,
                "expected": c.expected,
                "got": c.got,
                "comment": c.comment,
            }
            for c in bundle.checks
        ],
    }


def run_to_dict(bundles: List[Bundle],
                errors: List[Tuple[str, str]],
                documents_count: int,
                report_path: str | None = None) -> dict:
    counts = Counter(b.status for b in bundles)
    anomalies = sum(n for status, n in counts.items() if status in BLOCKING_STATUSES)
    return {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "documents": documents_count,
            "bundles": len(bundles),
            "read_errors": len(errors),
            "anomalies": anomalies,
            "by_status": dict(counts),
        },
        "report_path": report_path,
        "bundles": [bundle_to_dict(b) for b in bundles],
        "errors": [{"path": path, "error": message} for path, message in errors],
    }


def to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def post_webhook(url: str, payload: dict, timeout: int = 15) -> int:
    """POST the run payload to a webhook URL. Returns the HTTP status code.

    Standard library only: automation targets (n8n webhook node, Power
    Automate HTTP trigger, a Slack/Teams relay) just need a JSON body.
    """
    import urllib.request

    body = to_json(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status
