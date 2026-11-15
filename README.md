# VERIFEX

**Trust Every Document. Verify Every Detail.**

VERIFEX inspects PDFs and images, including bills, invoices, receipts, and certificates, with OCR, OpenCV, a custom-trained U-Net, Gemini, and Groq. Reports show Fake or Original with a confidence score. The visual classifier uses the uploaded pages alone. A signed issuer record, when present, provides independent verification.

## Run locally on Windows

Use Python 3.12 or 3.13 (64-bit) and Node.js 22. In PowerShell, from the repository root:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt -r backend/requirements-ocr.txt
.\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch>=2.8,<3'
npm.cmd --prefix frontend ci
~~~

Run `.\.venv\Scripts\python.exe backend/setup_env.py` to generate `.env`, then set `DATABASE_URL` as described below. From the repository root in PowerShell, run:

~~~powershell
.\run.ps1
~~~

You can also open `run.ps1` in VS Code and select **Run Code** with Code Runner in a PowerShell terminal. Both services log to the same terminal. Press Ctrl+C to stop them. On macOS and Linux, use `bash ./run.sh`.

Open [VERIFEX on localhost](http://localhost:3000) and select **Analyze a document** to sign in and upload a document. The demo lab can also run with a guest session. Use the hostname from PUBLIC_URL in the browser because the API checks write origins. Startup upgrades the database with Alembic. PaddleOCR downloads its two English mobile models on first use and caches them locally. Preload them before a presentation:

~~~powershell
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
.\.venv\Scripts\python.exe -c "from backend.verifex.ocr_service import OCR; OCR().warm()"
~~~

The auto OCR mode prefers PaddleOCR, then uses an installed Tesseract binary, then a readable PDF text layer. If PaddleOCR installation is unavailable, install the base dependencies and set TESSERACT_CMD to an installed executable for raster OCR. OpenCV, local inference, and cryptography run independently of external AI services.

## Supabase database

Open your Supabase project, click **Connect**, and copy the **Session pooler** connection string on port `5432`. Replace the password placeholder with your database password, URL-encoding reserved characters such as `@` as `%40`. Paste the finished string into the root `.env` as `DATABASE_URL`. VERIFEX accepts the `postgresql://` string as supplied and uses an encrypted PostgreSQL connection. [Supabase connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres)

On startup, Alembic creates or upgrades the VERIFEX tables using the database role in `DATABASE_URL`. For Supabase, use the owner connection from the dashboard. PostgreSQL migrations enable row-level security and remove direct API-role grants on the app tables. FastAPI continues to handle login and access to records. The PostgreSQL URL supplies all database credentials for this app.

Existing local SQLite records require a separate data migration to appear in Supabase. For local SQLite development, explicitly set `DATABASE_URL=sqlite:///./.verifex/verifex.sqlite3`.

## Docker and API configuration

After setting up `.env`, run `docker compose up --build` using Docker Desktop with its Linux engine running. The frontend binds to localhost. Compose persists the PaddleOCR cache and any explicitly configured local SQLite database in named volumes.

| Setting | Purpose |
| --- | --- |
| APP_SECRET_KEY, ENCRYPTION_KEY | Generated locally. Preserve both keys with database backups. The former derives session hashes and the report signing key. The latter seals documents, issuer private keys, and forensic results. |
| PUBLIC_URL, COOKIE_SECURE | Browser origin and QR link base. For an HTTPS deployment, use the public HTTPS URL and set secure cookies to true. |
| GEMINI_API_KEY, GEMINI_MODEL | Optional image analysis. Create a key in [Google AI Studio](https://aistudio.google.com/apikey). Example model `gemini-3.5-flash-lite`. |
| GROQ_API_KEY, GROQ_MODEL | Optional forensic explanations and follow-up answers. Create a key in the [Groq console](https://console.groq.com/keys). Example model `openai/gpt-oss-20b`. |
| CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY | Clerk application keys for sign-up and sign-in. FastAPI serves only the publishable key to the browser. |
| ADMIN_EMAIL | Set to the administrator's verified email before their first Clerk sign-in. |
| ADMIN_PASSWORD | Optional password for the legacy administrator API. Leave it blank for a new Clerk administrator. |
| DEMO_ENABLED | Enables the fictional demo and seeds a synthetic issuer. Disable it when deploying a private workspace. |
| OCR_ENGINE, TESSERACT_CMD | Select OCR behavior and optionally set the Tesseract executable path. |

Provider keys stay on the API server. New analyses send page images to Gemini, which checks for visible edits and can contribute evidence to the verdict. Groq uses the structured findings to explain the assessment. If the verdict is unavailable, select **Reanalyze** to run the current engines on the saved upload. [Gemini models](https://ai.google.dev/gemini-api/docs/models), [Groq models](https://console.groq.com/docs/models).

### Clerk social sign-in

Create a Clerk application and copy `CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` from **API keys** into the root `.env`. Enable the **Google** and **Apple** social connections for sign-up and sign-in in Clerk. Restart VERIFEX and use the browser origin configured in `PUBLIC_URL`. [Clerk setup](https://clerk.com/docs/getting-started/quickstart/setup-clerk) · [Google connection setup](https://clerk.com/docs/guides/configure/auth-strategies/social-connections/google) · [Apple connection setup](https://clerk.com/docs/guides/configure/auth-strategies/social-connections/apple)

Open **Sign in** and choose Google or Apple. The first successful sign-in creates a local Supabase account with verifier access, or administrator access if the verified email matches `ADMIN_EMAIL`. A previously linked Google account keeps its workspace when Clerk supplies the same verified Google identity and primary email. Guest sessions have separate workspaces and expire after 30 days. Private originals are accessible to their issuer and administrators. The QR link opens the public issuance record.

On localhost, **Admin sign in** opens a separate username and password form. This account uses the fixed local credentials and stores an Argon2id password hash. Hosted admin access uses the configured Clerk administrator or an existing administrator account.

Use a single API process per database. Its persisted queue reclaims unfinished analyses at startup. For a deployment, use a TLS reverse proxy that restricts request size and trusts forwarded headers from known proxies.

## Architecture

~~~mermaid
flowchart LR
  U[Next.js workspace] -->|Same-origin REST and SSE| A[FastAPI and role checks]
  A --> D[(SQLite or PostgreSQL)]
  A --> Q[Persisted analysis queue]
  Q --> O[PaddleOCR and OpenCV]
  O --> M[Custom U-Net]
  M --> G[Gemini visual analysis]
  G --> C[SHA-256 and Ed25519]
  C --> R[Groq explanation]
  R --> P[Forensic report]
  D --- V[AES-256-GCM vault]
  A --> I[Issuer portal and QR verification]
~~~

## Verification and documentation

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-test.txt
.\.venv\Scripts\python.exe -m pytest backend/tests
npm --prefix frontend run build
~~~

For a live browser check with Chrome installed, install **playwright** and run **python -m backend.tests.browser_smoke** while both servers are running. It opens a guest workspace and captures screenshots under **.verifex/browser-smoke**.

- [API guide](docs/API.md)
- [Presentation walkthrough](docs/DEMO.md)
- [Dataset sources, evaluation, and training](ml/README.md)

The bundled U-Net is experimental. Use its scores and masks as review leads. A signature independently establishes whether the uploaded bytes match the registered issuance record, and revocation status can change after a report is generated.
