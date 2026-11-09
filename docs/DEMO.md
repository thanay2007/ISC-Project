# Live presentation guide

Open [the demo lab](http://localhost:3000/demo) while signed in as a verifier. Before presenting, run the PaddleOCR preload command from the [setup guide](../README.md) and run one sample. Leave external processing unchecked for an offline presentation. When provider keys and models are configured, check the consent box on the fictional examples and show the Engines tab.

| Scenario | What to show |
| --- | --- |
| Genuine certificate | Follow live stages. Show that the exact bytes match the registered hash and verify against the issuer signature. Inspect the custom model score separately. |
| Modified grade | Open Text to see the extracted grade change from **B** to **A+**. Open **Compare** and select **Image difference** or move the before/after slider. The registered original signature still validates, while the uploaded fingerprint and candidate signature check fail. |
| Unknown certificate | Show that the reference and trusted fingerprint are absent. Review visual warnings independently. Use Document analyzer to try a separate fictional upload. |
| Model failure analysis | Compare the current visual prediction with the recorded ground-truth class and independent issuance check. Open **Model performance** to see how often the model missed changes or raised false alerts. |
| Unauthorized access | Use a verifier account and run the restricted request. Open the recorded audit event after the real HTTP 403. |
| Signed report | From a completed analysis, save the PDF and signature file. Verify them on **Forensic reports**. A changed PDF fails verification. |

**Reset demo** clears this account’s demo analyses while preserving audit events. For an issuance walkthrough, sign in as an institution and register a fictional document, open the public QR record, and revoke the certificate.

For a phone scan on the same network, set PUBLIC_URL to the LAN address of the computer running the frontend and bind Next.js to that interface. Restart both services and open the LAN URL before generating the QR code.
