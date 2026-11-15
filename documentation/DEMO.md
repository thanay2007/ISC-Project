# Live presentation guide

Set `DEMO_ENABLED=true` and restart the stack. Before presenting, preload PaddleOCR and run one sample. Configured providers run automatically. The **Engines** tab shows which engines contributed. [Setup guide](SETUP.md) · [Demo lab](http://localhost:3000/demo)

| Scenario | What to show |
| --- | --- |
| Genuine certificate | Follow live stages. Show that the exact bytes match the registered hash and verify against the issuer signature. Inspect the custom model score separately. |
| Modified grade | Show the Fake verdict and inspect the visual evidence. Open Text to see the uploaded grade of **A+**. The uploaded fingerprint differs from the signed record. |
| Unknown certificate | Show that the reference and trusted fingerprint are absent. Review visual warnings independently. Use Document analyzer to try a separate fictional upload. |
| Model failure analysis | Compare the current visual prediction with the recorded ground-truth class and independent issuance check. Open **Model performance** to see how often the model missed changes or raised false alerts. |
| Unauthorized access | Use a verifier account and run the restricted request. Open the recorded audit event after the real HTTP 403. |
| PDF report | Open **Forensic reports** to download a completed analysis with its verdict, confidence score, and findings. |

**Reset demo** clears this account’s demo analyses while preserving audit events. For an issuance walkthrough, sign in with an institution or administrator account, register a fictional document, open the public QR record, and revoke the certificate. [User workflows](WORKFLOWS.md)

For a phone scan on the same network, set PUBLIC_URL to the LAN address of the computer running the frontend and bind Next.js to that interface. Restart both services and open the LAN URL before generating the QR code.
