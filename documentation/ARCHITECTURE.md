# Architecture

~~~mermaid
flowchart LR
    Browser[Next.js workspace] -->|REST and SSE| API[FastAPI]
    API --> DB[(PostgreSQL or SQLite)]
    API --> Worker[Analysis worker]
    Worker -->|Jobs and progress| DB
    Worker --> Local[Render, OCR, OpenCV and U-Net]
    Worker --> Verify[SHA-256 and Ed25519 verification]
    Worker -->|Page images when configured| Gemini[Gemini]
    Worker -->|Structured findings when configured| Groq[Groq]
    API --> Reports[Signed PDF reports]
    API --> Issuance[Issuer registry and public QR links]
~~~

## Repository map

| Path | Responsibility |
| --- | --- |
| `frontend/src/app/` | Next.js App Router pages and workspace routes. |
| `frontend/src/components/` | Sign-in, analyzer, overlays, reports, dashboard, issuer, and admin interfaces. |
| `frontend/src/lib/` | Typed API client and shared response types. |
| `backend/verifex/` | FastAPI, access checks, document parsing, analysis pipeline, issuance, and report generation. |
| `backend/migrations/` | Alembic schema history for PostgreSQL and SQLite. |
| `backend/app/services/custom_forgery_model.py` | Model loading, inference, and validation of recorded metrics. |
| `backend/tests/` | API, authentication and database tests, plus a live browser smoke script. |
| `ml/models/`, `ml/results/`, `ml/samples/` | Shipped checkpoint, document-classifier artifact, evaluation outputs, and sample images. |
| `ml/scripts/`, `ml/training/`, `ml/inference/` | Dataset preparation, training and calibration, evaluation, and CLI inference. |
| `run.ps1`, `run.sh`, `compose.yaml` | Local startup and container orchestration. |

## Analysis lifecycle

1. FastAPI validates the upload, encrypts the source bytes, and stores a queued analysis. The API returns a job ID immediately after acceptance.
2. A worker reads queued jobs, renders pages, extracts text and fields, runs OpenCV checks, and generates U-Net scores, heatmaps, and masks. The document classifier combines model features and scan statistics across the uploaded pages.
3. Gemini can contribute visual evidence when configured. Separately, the worker hashes the original upload bytes and checks matching issuer records, signatures, and revocation status.
4. Groq can explain the structured findings when configured. The worker saves the encrypted report and stage history. The frontend subscribes to server-sent events and fetches the report and page layers through the API.

The worker restores interrupted jobs from the database on startup. Run one API worker per database so one process owns the queue. [Model card and training](ML.md) · [API guide](API.md)

## Storage and access

- SQLAlchemy stores users, sessions, certificates, analyses, and audit events. Alembic upgrades the schema during startup. PostgreSQL migrations enable row-level security and remove direct grants for Supabase API roles on application tables.
- Local passwords use Argon2id. Local and guest session tokens are stored as keyed hashes. When configured, the backend validates Clerk session tokens and maps them to application accounts and roles.
- AES-256-GCM protects uploaded documents, private issuer metadata, issuer private keys, and analysis reports. Owner and role checks protect private API routes. Authorization failures on protected resources are audited.
- Issuers sign the registered document's SHA-256 fingerprint and canonical issuance fields with Ed25519. Public verification returns issuance information and can compare a submitted file fingerprint. Report PDFs use a separate signing key derived from the application secret.

The confidence shown in a visual result is a model score. Verification of a matching, unrevoked issuer record supplies independent evidence about the uploaded bytes. [User workflows](WORKFLOWS.md)
