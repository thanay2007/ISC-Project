# User workflows

## Sign in and choose a workspace

Open **Sign in** and choose Google or Apple when Clerk is configured. The first verified sign-in creates a verifier account unless its email matches the configured administrator email. A previously linked Google account keeps its workspace when Clerk supplies the same verified Google identity and primary email. Local password accounts are available with Clerk disabled. The built-in **Admin sign in** form is available on localhost.

| Role | Workspace access |
| --- | --- |
| Guest | Run demo scenarios when enabled and inspect the results in an isolated workspace. The guest session expires after 30 days. |
| Verifier | Upload documents, inspect owned analyses and reports, and check public issuer records. |
| Institution | Use the verifier tools, register signed originals, and manage its own issuance records. |
| Administrator | Use issuer tools, manage institution permissions, review security events, and access private issuer previews. |

An administrator can grant or remove institution access from **Institutions** or the administrator workspace. [Authentication and security](ARCHITECTURE.md)

## Analyze a document

1. Select **Analyze a document** from the landing page or open the **Document analyzer** in your workspace.
2. Upload a PDF, JPEG, PNG, or WebP up to 10 MiB. PDFs must be unlocked and have 1–8 pages. Images must contain a single frame.
3. Follow the live stages. Inspect extracted fields, switch between page image layers, and check which engines contributed. History lists previous analyses in the current workspace.
4. Open the report to inspect the visual assessment and the independent issuer check. **Reanalyze** creates a new job from the saved upload and keeps the previous result.

The visual classifier flags patterns associated with edits and can miss changes or flag original pages. A matching issuer signature and fingerprint establish that the bytes match the registered version. Check the current public record for revocation. [Model card](ML.md)

## Register and verify an original

1. As an institution or administrator, open the issuance page and upload the final document. Add any optional private certificate metadata.
2. Save or share the QR code or its public verification link. The public page shows issuance and revocation status. The issuer and administrators can open the private preview.
3. From the public page, submit a copy if you want to compare its SHA-256 fingerprint with the registered original.
4. To withdraw an issuance record, revoke it from the issuer workspace. The public record continues to show the revocation status.

## Export and verify a report

Open **Forensic reports**, choose a completed analysis, and download the PDF. The API also provides a detached hexadecimal signature. Submit the PDF and detached signature to the report verification endpoint to check that the report bytes match what this VERIFEX instance signed. [API reference](API.md)

The report assistant answers questions about a completed analysis. When Groq is configured, it receives the question and relevant findings, including extracted fields. Otherwise the backend answers from the saved report.
