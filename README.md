# FreightQuote AI — Authentication Module

Streamlit app with Sign In (email **or** username), Register, and Forgot Password with a 6-digit email OTP.

## Folder
```
FreightQuote_AI/
├── app.py                     # the Streamlit app
├── run_colab.py               # starts Streamlit in background + ngrok tunnel
├── FreightQuote_AI_Colab.ipynb# clean 4-cell notebook
├── requirements.txt
├── agents/ data/ database/ logs/ pages/ services/ tests/ utils/
```

## Run in Google Colab
1. Colab Secrets (key icon, notebook access ON): `NGROK_AUTHTOKEN`, `SMTP_EMAIL`, `SMTP_APP_PASSWORD` (Gmail App Password).
2. Open `FreightQuote_AI_Colab.ipynb`, run cells 1 → 3, upload `FreightQuote_AI.zip` when asked.
3. Open the printed URL.

## Run locally
```
pip install -r requirements.txt
set SMTP_EMAIL=you@gmail.com            (Linux/mac: export ...)
set SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx
streamlit run app.py
```

## What was fixed
- Streamlit now starts in the **background** (old `!streamlit run` blocked the notebook, so the ngrok cell never ran).
- Old servers on 8501/8502/8503 and old tunnels are stopped before each start ("Port is not available").
- ngrok points at `127.0.0.1:<port>` (removes the `[::1] connection refused` warnings).
- Colab Secrets are read in the notebook and passed to the app as environment variables (`userdata.get` does not work inside the Streamlit subprocess → "Email delivery failed").
- Sign In accepts email or username again; username is case-insensitive.
- Database connections are always closed; commit/rollback handled.
- Registration validates username/email/password; duplicate check is case-insensitive.
- OTP: 60s resend limit, 5 attempts, 10-minute expiry, hashed with bcrypt, no account enumeration.
- After reset, the app switches back to Sign In; Sign Out button added.
- Works outside Colab (paths relative to `app.py`, secrets from env vars).


---

## Live Demo & Mentor Presentation

### Application URLs

- **Local URL (Colab runtime only):** http://127.0.0.1:8503
- **Public ngrok URL:** https://reptile-unspoken-tuition.ngrok-free.dev

> Important: The localhost URL is not accessible to your mentor from their computer.
> Share the HTTPS ngrok URL for a live demonstration. A free ngrok URL may change
> when the tunnel or runtime restarts. Refresh this section using the Colab cell
> whenever you start a new tunnel.

### How to Start the Demo

1. Open the Google Colab notebook for FreightQuote AI.
2. Connect the Colab runtime.
3. Mount Google Drive if it is not already mounted.
4. Start the Streamlit application and ngrok tunnel using the project's
   `run_colab.py` workflow.
5. Run the README refresh cell to record the current public URL.
6. Open the HTTPS ngrok URL and verify the login page before sharing it.

### Suggested Mentor Demonstration

1. Introduce FreightQuote AI and its maritime freight workflow.
2. Show the sign-in page and the available workspaces.
3. Sign in with an account assigned to the appropriate role.
4. Demonstrate only the features that are implemented and verified.
5. Explain which data is live, which integrations are pending, and any
   current limitations.

### Security Notes

- Never commit passwords, SMTP credentials, API keys, or ngrok auth tokens.
- Do not use real customer or confidential shipment data in a public demo.
- A workspace button does not itself grant a role; access must be authorized
  by the application's authentication and permission checks.
- Do not assume the demo is permanently online. Colab runtimes can disconnect.

### Project Location

`/content/drive/MyDrive/FreightQuote_AI`

_Last README refresh: 2026-10-25 18:06:51_
