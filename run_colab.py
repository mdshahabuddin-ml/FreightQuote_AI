"""
Start FreightQuote AI in Google Colab: Streamlit in the background + ngrok tunnel.

Usage in a Colab cell:
    %run /content/FreightQuote_AI/run_colab.py
Optional: set PORT before running, e.g.  import os; os.environ["FQ_PORT"] = "8504"
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests
from pyngrok import ngrok, conf

PROJECT_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("FQ_PORT", "8503"))
LOG_FILE = PROJECT_DIR / "logs" / "streamlit_server.log"


def get_secret(name):
    try:
        from google.colab import userdata
        value = userdata.get(name)
    except Exception:
        value = None
    value = value or os.environ.get(name)
    return value.strip() if value else None


def stop_old():
    # Stop every old Streamlit server and tunnel (frees 8501/8502/8503...)
    subprocess.run(["pkill", "-f", "streamlit run"], check=False)
    try:
        ngrok.kill()
    except Exception:
        pass
    time.sleep(2)


def start_streamlit():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "w")
    # Colab Secrets can only be read in the notebook kernel, not inside the
    # Streamlit subprocess, so pass them to the app as environment variables.
    env = os.environ.copy()
    for name in ("SMTP_EMAIL", "SMTP_APP_PASSWORD"):
        value = get_secret(name)
        if value:
            env[name] = value
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(PROJECT_DIR / "app.py"),
         "--server.port", str(PORT),
         "--server.address", "127.0.0.1",
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=str(PROJECT_DIR), env=env, stdout=log, stderr=log,
        preexec_fn=os.setsid,
    )
    health = f"http://127.0.0.1:{PORT}/_stcore/health"
    for _ in range(30):
        if proc.poll() is not None:
            break
        try:
            if requests.get(health, timeout=2).ok:
                print(f"Streamlit running on 127.0.0.1:{PORT} (pid {proc.pid})")
                return proc
        except requests.RequestException:
            pass
        time.sleep(1)
    print("Streamlit failed to start. Log:\n")
    print(LOG_FILE.read_text(errors="replace"))
    raise SystemExit(1)


def start_tunnel():
    token = get_secret("NGROK_AUTHTOKEN")
    if not token:
        raise SystemExit("NGROK_AUTHTOKEN missing. Add it in Colab Secrets and enable notebook access.")
    conf.get_default().auth_token = token
    # Connect to the local port using correct syntax
    tunnel = ngrok.connect(addr=PORT, proto="http")
    url = tunnel.public_url
    r = requests.get(url, headers={"ngrok-skip-browser-warning": "true"}, timeout=20)
    print("\n" + "=" * 55)
    print("FreightQuote AI URL:", url)
    print("Health check:", "PASS" if r.ok else f"HTTP {r.status_code}")
    print("=" * 55)
    return url


def check_smtp_secrets():
    for name in ("SMTP_EMAIL", "SMTP_APP_PASSWORD"):
        print(f"{name}: {'OK' if get_secret(name) else 'MISSING (OTP email will fail)'}")


if __name__ == "__main__":
    check_smtp_secrets()
    stop_old()
    start_streamlit()
    start_tunnel()
