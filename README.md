# VERIFEX

**Trust Every Document. Verify Every Detail.**

VERIFEX inspects academic documents with OCR, OpenCV, a custom-trained U-Net, and optional Gemini and Groq analysis. Issuance and verification use the exact uploaded bytes, SHA-256, trusted Ed25519 issuer keys, and independently recorded revocation status.

## Run locally on Windows

Use Python 3.12 or 3.13 (64-bit) and Node.js 22. In PowerShell, from the repository root:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt -r backend/requirements-ocr.txt
.\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch>=2.8,<3'
.\.venv\Scripts\python.exe backend/setup_env.py
.\.venv\Scripts\python.exe -m uvicorn backend.verifex.main:app --host 127.0.0.1 --port 8000
~~~

In a second PowerShell window:

~~~powershell
Set-Location frontend
npm ci
npm run dev
~~~

Open [VERIFEX on localhost](http://localhost:3000). Register a verifier account and open **Live demo**. Use the hostname from PUBLIC_URL in the browser because the API checks write origins. Startup upgrades the database with Alembic. PaddleOCR downloads its two English mobile models on first use and caches them locally. Preload them before a presentation:

~~~powershell
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
.\.venv\Scripts\python.exe -c "from backend.verifex.ocr_service import OCR; OCR().warm()"
~~~

The auto OCR mode prefers PaddleOCR, then uses an installed Tesseract binary, then a readable PDF text layer. If PaddleOCR installation is unavailable, install the base dependencies and set TESSERACT_CMD to an installed executable for raster OCR. OpenCV, local inference, comparison, and cryptography run independently of external AI services.

## Docker and configuration

Generate .env with **python backend/setup_env.py**, then run **docker compose up --build** using Docker Desktop with its Linux engine running. The frontend binds to localhost. Compose persists the SQLite database and PaddleOCR cache in named volumes. For PostgreSQL, set DATABASE_URL to a postgresql+psycopg connection URL and provide the database separately.

| Setting | Purpose |
| --- | --- |
| APP_SECRET_KEY, ENCRYPTION_KEY | Generated locally. Preserve both keys with database backups. The former derives session hashes and the report signing key. The latter seals documents, issuer private keys, and forensic results. |
| PUBLIC_URL, COOKIE_SECURE | Browser origin and QR link base. For an HTTPS deployment, use the public HTTPS URL and set secure cookies to true. |
| GEMINI_API_KEY, GEMINI_MODEL | Optional. Choose an account model with image input and structured output. |
| GROQ_API_KEY, GROQ_MODEL | Optional. Choose an account model that supports chat completions with JSON Object Mode. |
| ADMIN_EMAIL, ADMIN_PASSWORD | Set before startup to create the first administrator with a unique email and a password of at least 12 characters. Remove the bootstrap values afterward. |
| DEMO_ENABLED | Enables the fictional demo and seeds a synthetic issuer. Disable it when deploying a private workspace. |
| OCR_ENGINE, TESSERACT_CMD | Select OCR behavior and optionally set the Tesseract executable path. |

Provider keys stay on the API server. Enable external processing per analysis to send page images to Gemini and structured findings to Groq. When an authorized original is part of a comparison, consent also covers that original. Check account quotas and supported models in the official catalogs. [Gemini models](https://ai.google.dev/gemini-api/docs/models), [Groq models](https://console.groq.com/docs/models).

An administrator can promote a verifier to institution access on **Institution management**. Institutions can issue, share, and revoke credentials. Private originals are accessible to their issuer and administrators. The QR link contains a random reference. Its public record exposes the issuer, timestamp, integrity metadata, and revocation status.

Use a single API process per database. Its persisted queue reclaims unfinished analyses at startup. For a deployment, use a TLS reverse proxy that restricts request size and trusts forwarded headers from known proxies.

## Architecture

~~~mermaid
flowchart LR
  U[Next.js workspace] -->|Same-origin REST and SSE| A[FastAPI and role checks]
  A --> D[(SQLite or PostgreSQL)]
  A --> Q[Persisted analysis queue]
  Q --> O[PaddleOCR and OpenCV]
  O --> M[Custom U-Net]
  M --> G[Gemini with consent]
  G --> C[SHA-256 and Ed25519]
  C --> R[Groq with consent]
  R --> P[Forensic report and detached signature]
  D --- V[AES-256-GCM vault]
  A --> I[Issuer portal and QR verification]
~~~

## Verification and documentation

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-test.txt
.\.venv\Scripts\python.exe -m pytest backend/tests
npm --prefix frontend run build
~~~

For a live browser check with Chrome installed, install **playwright** and run **python -m backend.tests.browser_smoke** while both servers are running. It creates a verifier account and captures screenshots under **.verifex/browser-smoke**.

- [API guide](docs/API.md)
- [Presentation walkthrough](docs/DEMO.md)
- [Dataset sources, evaluation, and training](ml/README.md)

The bundled U-Net is experimental. Use its scores and masks as review leads. A signature independently establishes whether the uploaded bytes match the registered issuance record, and revocation status can change after a report is generated.
