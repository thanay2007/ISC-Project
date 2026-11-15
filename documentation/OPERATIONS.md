# Operations and testing

## Run with Docker Compose

Start Docker with Linux containers and configure the root `.env` before building. Set `DATABASE_URL` to a reachable PostgreSQL connection or to `sqlite:///./.verifex/verifex.sqlite3` for container-local data. [Environment setup](SETUP.md)

~~~sh
docker compose up --build
docker compose ps
docker compose logs api
~~~

Compose starts the frontend after the API health check passes. It publishes the frontend on `127.0.0.1:3000` and keeps FastAPI on the Compose network. The `verifex-data` volume holds SQLite files when configured, and `ocr-models` holds the Paddle model cache. Use `docker compose down` to stop the stack while keeping the volumes. [Workspace](http://localhost:3000) · [Health endpoint](http://localhost:3000/api/health)

## Deployment and backups

- Use HTTPS with a reverse proxy, set `PUBLIC_URL` to the public HTTPS origin, and set `COOKIE_SECURE=true`. Apply an upload size limit and allow the analysis SSE route to stream without buffering. Keep the API port private.
- Run one API process per database. It owns the persisted analysis queue and applies schema migrations before serving traffic. Back up the database before upgrading.
- Back up the database with its `APP_SECRET_KEY` and `ENCRYPTION_KEY` in protected storage. The keys are needed to decrypt evidence, use existing signing keys, and verify previously signed reports. For SQLite, use SQLite's backup mechanism or stop the stack before backing up the database.
- Set `DEMO_ENABLED=false` for a private deployment. Configure the administrator before their first sign-in, and set the optional provider credentials only when the deployment can send data to those services.

## Run checks

From the repository root in PowerShell, use a working local Python environment and the installed frontend dependencies.

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-test.txt
.\.venv\Scripts\python.exe -m pytest backend/tests
npm.cmd --prefix frontend run build
~~~

Use `.venv/bin/python` and `npm` on macOS or Linux. CI runs the backend test suite and the frontend production build. [CI workflow](../.github/workflows/ci.yml)

For a live browser check, use a local workspace with `DEMO_ENABLED=true`, run both services, and make sure Chrome and the OCR models are available. The check creates a guest session, runs a demo, exercises live progress and report views, and saves screenshots under `.verifex/browser-smoke`.

~~~powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m backend.tests.browser_smoke
~~~

The script defaults to Chrome and `http://localhost:3000`. Set `VERIFEX_BROWSER_CHANNEL` or `VERIFEX_TEST_URL` to test a different supported browser channel or workspace origin. [Live presentation guide](DEMO.md)
