# API guide

Open [Swagger UI](http://localhost:3000/api/docs) or [OpenAPI JSON](http://localhost:3000/api/openapi.json) while the stack runs. The frontend proxies requests to FastAPI. Writes require the **X-Verifex-Request** header set to **1** and a valid content length. A supplied Origin must match PUBLIC_URL. Browser clients receive an HttpOnly session cookie.

| Routes | Access and behavior |
| --- | --- |
| POST /api/auth/register, /api/auth/login, /api/auth/logout and GET /api/auth/me | Session management. Registration creates a verifier. |
| POST /api/analyses | Signed-in. Multipart file, optional certificate_ref and external_ai. Returns HTTP 202 and the job ID. |
| GET /api/analyses and /api/analyses/{job} | Owner only. Lists history or returns the analysis and its evidence. |
| GET /api/analyses/{job}/events | Owner only. Ordered stage events via SSE. A reconnect can replay events. |
| GET /api/analyses/{job}/pages/{page} | Owner only. Sanitized 1-based page PNG. Set layer to uploaded, processed, heatmap, mask, original, or difference. Original layers require authorized comparison. |
| POST /api/analyses/{job}/assistant | Owner only. JSON question and optional external_ai. Provider use also requires consent on the analysis. |
| GET /api/analyses/{job}/report.pdf | Owner only. Signed PDF. Set ?signature=true for the detached signature. |
| POST /api/reports/verify | Public. Multipart report file and hexadecimal signature. |
| POST /api/certificates, GET /api/certificates and POST /api/certificates/{ref}/revoke | Issuer or administrator. Upload a multipart file to sign it. |
| GET /api/certificates/{ref}/original | Issuer or administrator. Sanitized first-page preview. |
| GET /api/verify/{ref}, POST /api/verify/{ref} and GET /api/verify/{ref}/qr.png | Public issuance record, optional multipart file check, and QR image. |
| POST /api/ai/custom-forgery-detection | Signed-in. Multipart file. Returns measured scores, normalized regions, processing status, model version, and latency. |
| GET /api/ai/model-performance and /api/health | Public checkpoint metadata, measured results, and service health. |
| GET /api/dashboard and /api/security | Signed-in. Account-scoped evidence with broader audit access for administrators. |
| POST /api/security/summary, GET /api/admin/users and POST /api/admin/users/{id}/role | Administrator. Aggregate security summary and issuer permission management. |
| GET /api/demo and POST /api/demo/{scenario} | Signed-in and demo enabled. Scenarios are genuine, modified, unknown, failure, and reset. |

Example in PowerShell:

~~~powershell
curl.exe -c cookies.txt -H "X-Verifex-Request: 1" -H "Content-Type: application/json" --data-binary "@login.json" http://localhost:3000/api/auth/login
curl.exe -b cookies.txt -H "X-Verifex-Request: 1" -F "file=@sample.pdf" -F "external_ai=false" http://localhost:3000/api/analyses
curl.exe -N -b cookies.txt http://localhost:3000/api/analyses/JOB_ID/events
~~~

Create login.json with your email and password locally and keep both credential and cookie files outside the repository. The report public key is in the X-Report-Public-Key response header. Certificate signatures cover canonical issuer and issuance metadata plus the SHA-256 fingerprint.
