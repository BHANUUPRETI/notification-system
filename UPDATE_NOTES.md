# Update Notes — 28 Sep 2026

This package was refreshed for the deployed assignment setup.

## Updated
- Automated test runs now force sandbox mode so a local production-style `.env` cannot trigger real provider calls during `python manage.py test`.
- Homepage provider wording now matches the live stack: Meta WhatsApp, Brevo Email, OneSignal Web Push.
- WhatsApp environment variable is standardized to `WHATSAPP_PHONE_NUMBER_ID`; legacy `PHONE_NUMBER_ID` still works as a fallback.
- Default WhatsApp API version is `v25.0`.
- Default email provider is Brevo.
- Removed the temporary `create_demo_users --admin` command from the permanent Render build.
- Removed the stale duplicate `backend/render.yaml`; repository-root `render.yaml` is the canonical Blueprint.
- Fixed template preview spacing so title/subject and body do not run together.
- README now includes the deployed Render/Vercel URLs, current provider status, free-plan admin bootstrap note, and an updated walkthrough-video checklist.
- `.gitignore` now also ignores exported ZIP files.

## Current provider verification
- Brevo Login/Logout Email: verified.
- OneSignal Login/Logout Web Push: verified on the Vercel production domain.
- WhatsApp Cloud API: configured; `welcome_back_v1` and `signed_out_v1` are still waiting for Meta approval before final real sends.

## Before final submission
1. Wait for both Meta templates to become Active/Approved.
2. In Notify Admin, open each WhatsApp template and click **Sync**.
3. Test-send both WhatsApp templates to the approved sandbox recipient.
4. Run real Login and Logout and confirm WhatsApp + Email + Web Push in Activity.
5. Complete the Edit/Toggle demo and inactivity-scan evidence for the walkthrough video.
6. Run the full backend tests and frontend production build in your normal local environment, then push the final changes to GitHub.
