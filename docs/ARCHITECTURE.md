# ControlDOne Architecture

## Design Goal

ControlDOne is split into a reusable engine and thin presentation layers.

The engine should be usable from:

- the current CLI;
- a desktop or web app;
- future APIs;
- batch jobs.

## Runtime Flow

```text
input files
  -> ingest
  -> classify
  -> parse
  -> match into dossiers
  -> validate business rules
  -> report or API response
```

## Modules

### `controldone.ingest`

Reads input files and returns page-level text.

Supported inputs:

- PDF;
- XLSX/XLS;
- folders containing mixed files.

OCR is delegated to `controldone.ocr`.

### `controldone.ocr`

Handles PDF text extraction and Tesseract OCR fallback.

The OCR cache is local-only and ignored by git.

### `controldone.classification`

Classifies page segments into logical document types:

- invoice;
- customs declaration;
- forwarder/prestation invoice;
- airway bill or supporting document;
- unknown/fallback.

### `controldone.parsing`

Main parsing layer. It adapts historical v3 parsers and newer heuristics into the v4 `Document` model.

This is where most supplier-format improvements currently happen.

### `controldone.formats`

Format-specific helpers. Keep vendor-specific parsing here when a parser becomes too large for `parsing.py`.

Current example:

- `formats/declarations/delta_ie_akanea.py`

### `controldone.matching`

Builds customs dossiers by matching:

- goods invoice;
- declaration;
- optional forwarder invoice.

It uses strong folder context when available, then AWB/LTA, MRN, invoice references and extracted identifiers.

### `controldone.validation`

Business rule engine.

The goods invoice is the source of truth. Blocking controls are:

- entity/VAT;
- HS code coverage on 6 digits;
- value/currency;
- preference;
- missing mandatory documents.

### `controldone.reporting`

Excel output only. Keep UI/API-specific output outside the validation engine.

### `controldone.pipeline`

Stable application API.

Use this module when integrating ControlDOne into an app:

```python
from controldone.pipeline import analyze

result = analyze("/path/to/input")
```

### `controldone.cli`

Command-line wrapper around the pipeline and Excel reporter.

### `controldone.webapp`

Local browser interface around the same pipeline.

It accepts:

- uploaded PDF/Excel files;
- ZIP batches;
- full folder uploads from compatible browsers;
- a local file/folder path on the same PC.

It writes temporary upload jobs to `data/app_jobs` and Excel reports to `data/output`. Both folders are ignored by git.

## Configuration

Client-specific data lives in a **client profile** under `config/clients/<client>/`:

- `entities.yaml`: controlled entities (VAT/SIREN), name & address aliases, document keywords, known non-HS ids;
- `hs_scope.txt`: in-scope HS6 codes;
- `fx_rates.yaml` (optional): per-client FX overrides.

Shared, non-client rules live in `config/rules`:

- `fx_rates.yaml`: indicative FX rates and tolerance;
- `severities.yaml`: severity mapping.

The engine carries no client data. A `ClientProfile` (see `controldone.profile`)
is resolved and injected at the pipeline edge, `analyze(input, profile=...)` : and propagated to the parsing/validation layers through contextvars, so several
clients can run in the same process without shared state (multi-tenant). Select
the active profile with `CONTROLDONE_CLIENT=<client>`, or rely on auto-detection
when a single client folder is present.

## Adding A New Supplier Format

1. Add detection phrases or filename rules in classification/parsing.
2. Extract only business-critical fields first:
   - invoice number;
   - VAT/entity;
   - HS codes;
   - value;
   - currency;
   - AWB/LTA if present.
3. Add matching references if the supplier uses a specific file/folder convention.
4. Run one targeted dossier and one full batch.
5. Review the Excel report manually before broad use.

## Repo Hygiene

Private documents, reports, OCR caches and historical archives are ignored by git. Keep sample files synthetic if the project is published.
