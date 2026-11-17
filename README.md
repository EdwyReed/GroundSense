# GroundSense

GroundSense is a research prototype for assessing environmental conditions around unpaved and forest roads serving civilian industrial sites. It combines maps, weather, soil and terrain sources with an experimental scientific assessment model. The frontend is Ukrainian; specifications are mainly Russian.

The model is not field-validated and does not authorize vehicle passage or guarantee road safety. External data providers have their own usage and licensing terms.

## Source layout

- `apps/api`: Python/FastAPI backend and source adapters.
- `apps/web`: Vue/TypeScript frontend.
- `packages`: domain fixtures, ingestion and scientific model.
- `contracts`: assessment schema and synthetic examples.
- `tests`: backend and contract tests; frontend tests live alongside components.
- `docs` and `GROUNDSENSE-SPEC.md`: product and scientific specifications.
- `infra`: database Compose definition and PostGIS initialization.

## Local checks

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-runtime.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
.venv/bin/python -m pytest -q
npm --prefix apps/web test
npm --prefix apps/web run typecheck
```

These are project check commands, not a claim that this publication was deployed or that every check currently passes. Runtime configuration must be supplied locally. Do not commit credentials, databases, uploads or private coordinates.

## Publication scope

This repository contains a sanitized reconstruction of the original two-commit source history. Private conversation exports, user attachments, third-party reference images and downloaded documents, agent sessions, operational receipts, screenshots, runtime data and host-specific deployment configuration are excluded. Documentation may retain historical references to those omitted files; they are not included in this public source package.

The synthetic seed and contract examples are explicitly artificial and do not represent a private production registry. No license grant has been added as part of publication.
