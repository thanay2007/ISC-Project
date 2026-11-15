# API guide

The frontend proxies `/api/*` to FastAPI. Write requests require `X-Verifex-Request: 1` and a valid `Content-Length`, even for empty requests. If a request supplies an `Origin`, it must match `PUBLIC_URL`. Password and guest sessions use the HttpOnly `verifex_session` cookie. Clerk sign-in uses Clerk's `__session` cookie. [Swagger UI](http://localhost:3000/api/docs) · [OpenAPI JSON](http://localhost:3000/api/openapi.json)

| Routes | Access and behavior |
| --- | --- |
| POST /api/auth/register, /api/auth/login | Password sign-in. Registration creates a verifier when Clerk is disabled. |
| POST /api/auth/guest, /api/auth/logout and GET /api/auth/me | Start a guest workspace, end a VERIFEX session, or inspect the current account. |
| POST /api/auth/admin/login | Built-in administrator sign-in on localhost. |
| POST /api/analyses | Verifier, institution, or administrator. Send a multipart file. Configured providers run automatically. Returns HTTP 202 and the job ID. |
| POST /api/analyses/{job}/reanalyze | Signed-in owner. Queues a new analysis of the saved upload and keeps the previous report. Returns HTTP 202 and the new job ID. |
| GET /api/analyses and /api/analyses/{job} | Owner only. Lists history or returns the analysis and its evidence. |
| GET /api/analyses/{job}/events | Owner only. Ordered stage events via SSE. A reconnect can replay events. |
| GET /api/analyses/{job}/pages/{page} | Owner only. Sanitized 1-based page PNG. Set layer to uploaded, processed, heatmap, or mask. |
| POST /api/analyses/{job}/assistant | Owner only. JSON question. Uses Groq automatically when configured. |
| GET /api/analyses/{job}/report.pdf | Owner only. Signed PDF. Set ?signature=true for the detached signature. |
| POST /api/reports/verify | Public. Multipart report file and hexadecimal signature. |
| POST /api/certificates, GET /api/certificates and POST /api/certificates/{ref}/revoke | Issuer or administrator. Upload a multipart file to sign it. |
| GET /api/certificates/{ref}/original | Owning issuer or administrator. Sanitized first-page preview. |
| GET /api/verify/{ref}, POST /api/verify/{ref} and GET /api/verify/{ref}/qr.png | Public issuance record, optional multipart file check, and QR image. |
| POST /api/ai/custom-forgery-detection | Signed-in. Multipart file. Returns measured scores, normalized regions, processing status, model version, and latency. |
| GET /api/ai/model-performance and /api/health | Public checkpoint metadata, measured results, and service health. |
| GET /api/dashboard and /api/security | Signed-in. Account-scoped evidence with broader audit access for administrators. |
| POST /api/security/summary, GET /api/admin/users and POST /api/admin/users/{user_id}/role | Administrator. Aggregate security summary and issuer permission management. |
| GET /api/demo and POST /api/demo/{scenario} | Signed-in and demo enabled. Scenarios are genuine, modified, unknown, failure, and reset. |

## Upload and follow an analysis

Use a verifier, institution, or administrator password account for this PowerShell example. Create `login.json` with an `email` and `password`. Run the commands from a directory outside the repository so the credentials and cookie jar stay out of source control.

~~~powershell
curl.exe -c cookies.txt -H "X-Verifex-Request: 1" -H "Content-Type: application/json" --data-binary "@login.json" http://localhost:3000/api/auth/login
curl.exe -b cookies.txt -H "X-Verifex-Request: 1" -F "file=@sample.pdf" http://localhost:3000/api/analyses
curl.exe -N -b cookies.txt http://localhost:3000/api/analyses/JOB_ID/events
~~~

Replace `JOB_ID` with the `id` from the upload response. The stream sends progress as SSE messages with sequential IDs and may send a separate `preview` event. A reconnect can replay earlier stages. Fetch the completed analysis at `GET /api/analyses/{job}`. The PDF response includes `X-Report-Signature` and `X-Report-Public-Key`. Certificate signatures separately cover canonical issuer and issuance metadata plus the SHA-256 fingerprint.
