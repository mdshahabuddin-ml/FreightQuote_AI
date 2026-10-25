"""
FreightQuote AI - Authentication module
Sign In (email or username) / Register / Forgot Password.

Register collects three security answers (pet name, first school, favorite city).
Sign In locks an account after too many wrong passwords.
Forgot Password works two ways:
    1. Security questions - no email setup needed
    2. Email OTP          - needs the two secrets below

Secrets (Colab Secrets or environment variables):
    SMTP_EMAIL         - Gmail address used to send OTP emails
    SMTP_APP_PASSWORD  - Gmail App Password (16 chars, spaces allowed)
"""

import os
import re
import ssl
import sqlite3
import secrets
import smtplib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import bcrypt
import streamlit as st

# ---------------- Configuration ----------------

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("FREIGHTQUOTE_DB", BASE_DIR / "freightquote.db"))

OTP_MINUTES = 10
MAX_OTP_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 72  # bcrypt limit (bytes)

MAX_ANSWER_ATTEMPTS = 5
ANSWER_LOCKOUT_MINUTES = 15
MIN_ANSWER_LENGTH = 2

# Account lock after wrong passwords at Sign In.
# "More than 3 wrong attempts" -> the 4th wrong attempt locks the account.
# (Set LOCK_AFTER_FAILED_ATTEMPTS = 3 to lock on the 3rd wrong attempt instead.)
LOCK_AFTER_FAILED_ATTEMPTS = 4
LOGIN_LOCK_MINUTES = 30

# (database column, question shown to the user)
SECURITY_QUESTIONS = [
    ("pet_hash", "What is your pet’s name?"),
    ("school_hash", "What is the name of your first school?"),
    ("city_hash", "What is your favorite city?"),
]

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,50}")

st.set_page_config(
    page_title="FreightQuote AI",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="auto",
)

# ---------------- Database ----------------


@contextmanager
def db():
    """Open a connection, commit on success, roll back on error, always close."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash BLOB NOT NULL,
                role TEXT NOT NULL DEFAULT 'Customer',
                created_at TEXT NOT NULL,
                pet_hash BLOB,
                school_hash BLOB,
                city_hash BLOB
            )
        """)

        # Upgrade an older database that was created without the security columns.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        for column, _ in SECURITY_QUESTIONS:
            if column not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} BLOB")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                email TEXT PRIMARY KEY,
                otp_hash BLOB NOT NULL,
                expires_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                verified_at TEXT,
                last_sent_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                email TEXT PRIMARY KEY,
                failures INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS answer_attempts (
                email TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT
            )
        """)


init_db()

# ---------------- Helpers ----------------


def now_utc():
    return datetime.now(timezone.utc)


def parse_time(value):
    return datetime.fromisoformat(value)


def normalize_email(email):
    return (email or "").strip().lower()


def normalize_answer(value):
    """Case-insensitive, whitespace-insensitive form used for security answers."""
    return " ".join((value or "").strip().casefold().split())


def valid_password(password):
    password = password or ""
    return (MIN_PASSWORD_LENGTH <= len(password)
            and len(password.encode("utf-8")) <= MAX_PASSWORD_LENGTH)


def hash_secret(value):
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt())


def check_secret(value, stored_hash):
    try:
        return bcrypt.checkpw(value.encode("utf-8"), bytes(stored_hash))
    except (ValueError, TypeError):
        return False


def get_secret(name):
    """Environment variable first (set by run_colab.py), then Colab Secrets."""
    value = os.environ.get(name)
    if not value:
        try:
            from google.colab import userdata  # works only in the notebook kernel
            value = userdata.get(name)
        except Exception:
            value = None
    return value.strip() if value else None


# ---------------- Email OTP ----------------


def send_otp_email(to_email, otp):
    sender = get_secret("SMTP_EMAIL")
    app_password = get_secret("SMTP_APP_PASSWORD")

    if not sender or not app_password:
        raise RuntimeError("SMTP_EMAIL or SMTP_APP_PASSWORD is not configured.")

    message = EmailMessage()
    message["Subject"] = "FreightQuote AI Password Reset OTP"
    message["From"] = sender
    message["To"] = to_email
    message.set_content(
        f"Your FreightQuote AI password reset code is: {otp}\n\n"
        f"This code expires in {OTP_MINUTES} minutes.\n"
        "If you did not request this code, you can ignore this email.\n"
    )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465,
        context=ssl.create_default_context(), timeout=20,
    ) as server:
        server.login(sender, app_password.replace(" ", ""))
        server.send_message(message)


# ---------------- Auth logic ----------------


def find_user(identity):
    """Find by username (case-insensitive) or email."""
    identity = (identity or "").strip()
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?) OR email = ?",
            (identity, normalize_email(identity)),
        ).fetchone()


def register_user(username, email, password, confirm, answers):
    """`answers` is a list of three strings, in SECURITY_QUESTIONS order."""
    username = (username or "").strip()
    email = normalize_email(email)
    answers = [normalize_answer(a) for a in answers]

    if not USERNAME_RE.fullmatch(username):
        return False, ("Username must be 3–50 characters: letters, numbers, "
                       "dots, underscores or hyphens.")
    if not EMAIL_RE.fullmatch(email):
        return False, "Enter a valid email address."
    if not valid_password(password):
        return False, f"Password must be {MIN_PASSWORD_LENGTH}–{MAX_PASSWORD_LENGTH} characters."
    if password != confirm:
        return False, "Passwords do not match."
    if any(len(a) < MIN_ANSWER_LENGTH for a in answers):
        return False, (f"Answer all three security questions "
                       f"(at least {MIN_ANSWER_LENGTH} characters each).")

    try:
        with db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE lower(username) = lower(?) OR email = ?",
                (username, email),
            ).fetchone()
            if exists:
                return False, "That username or email is already registered."
            conn.execute(
                """INSERT INTO users
                       (username, email, password_hash, role, created_at,
                        pet_hash, school_hash, city_hash)
                   VALUES (?, ?, ?, 'Customer', ?, ?, ?, ?)""",
                (
                    username, email, hash_secret(password),
                    now_utc().isoformat(),
                    hash_secret(answers[0]),
                    hash_secret(answers[1]),
                    hash_secret(answers[2]),
                ),
            )
    except sqlite3.IntegrityError:
        return False, "That username or email is already registered."
    return True, "Account created. You can now sign in."


# ----- Sign In with account lock -----


def login_lock_minutes(email):
    """Minutes left before this account unlocks, or 0 if it is not locked."""
    with db() as conn:
        row = conn.execute(
            "SELECT locked_until FROM login_attempts WHERE email = ?", (email,)
        ).fetchone()
    if row and row["locked_until"]:
        remaining = (parse_time(row["locked_until"]) - now_utc()).total_seconds()
        if remaining > 0:
            return int(remaining // 60) + 1
    return 0


def record_login_failure(email):
    """Count a wrong password. Returns attempts left before the lock (0 = just locked)."""
    with db() as conn:
        row = conn.execute(
            "SELECT failures, locked_until FROM login_attempts WHERE email = ?",
            (email,),
        ).fetchone()
        failures = row["failures"] if row else 0
        # an expired lock starts a fresh count
        if row and row["locked_until"] and now_utc() >= parse_time(row["locked_until"]):
            failures = 0
        failures += 1

        locked_until = None
        left = LOCK_AFTER_FAILED_ATTEMPTS - failures
        if left <= 0:
            locked_until = (now_utc() + timedelta(minutes=LOGIN_LOCK_MINUTES)).isoformat()
            failures = 0
            left = 0

        conn.execute(
            """INSERT INTO login_attempts (email, failures, locked_until)
               VALUES (?, ?, ?)
               ON CONFLICT(email) DO UPDATE SET
                   failures = excluded.failures,
                   locked_until = excluded.locked_until""",
            (email, failures, locked_until),
        )
    return left


def clear_login_failures(email):
    """Forget wrong-password history and unlock the account."""
    with db() as conn:
        conn.execute("DELETE FROM login_attempts WHERE email = ?", (email,))


def authenticate(identity, password):
    """Returns (user_row_or_None, error_message)."""
    user = find_user(identity) if (identity or "").strip() else None
    if not user:
        return None, "Invalid email/username or password."

    email = user["email"]
    minutes = login_lock_minutes(email)
    if minutes:
        return None, (f"🔒 This account is locked after too many wrong passwords. "
                      f"Try again in {minutes} minute(s), or unlock it now with "
                      f"Forgot Password.")

    if check_secret(password, user["password_hash"]):
        clear_login_failures(email)
        return user, ""

    left = record_login_failure(email)
    if left == 0:
        return None, (f"🔒 Too many wrong passwords. Your account is locked for "
                      f"{LOGIN_LOCK_MINUTES} minutes. You can unlock it sooner with "
                      f"Forgot Password.")
    return None, (f"Invalid email/username or password. "
                  f"{left} more wrong attempt(s) will lock your account.")


# ----- Reset method 1: security questions -----


def _locked_minutes(email):
    """Minutes left on a lockout for this account, or 0 if not locked."""
    with db() as conn:
        row = conn.execute(
            "SELECT locked_until FROM answer_attempts WHERE email = ?", (email,)
        ).fetchone()
    if row and row["locked_until"]:
        remaining = (parse_time(row["locked_until"]) - now_utc()).total_seconds()
        if remaining > 0:
            return int(remaining // 60) + 1
    return 0


def _record_answer_failure(email):
    with db() as conn:
        row = conn.execute(
            "SELECT attempts, locked_until FROM answer_attempts WHERE email = ?",
            (email,),
        ).fetchone()
        attempts = row["attempts"] if row else 0
        # an expired lockout starts a fresh count
        if row and row["locked_until"] and now_utc() >= parse_time(row["locked_until"]):
            attempts = 0
        attempts += 1

        locked_until = None
        if attempts >= MAX_ANSWER_ATTEMPTS:
            locked_until = (now_utc() + timedelta(minutes=ANSWER_LOCKOUT_MINUTES)).isoformat()
            attempts = 0

        conn.execute(
            """INSERT INTO answer_attempts (email, attempts, locked_until)
               VALUES (?, ?, ?)
               ON CONFLICT(email) DO UPDATE SET
                   attempts = excluded.attempts,
                   locked_until = excluded.locked_until""",
            (email, attempts, locked_until),
        )


def reset_with_answers(identity, answers, new_password, confirm):
    """Reset a password after all three security answers match."""
    answers = [normalize_answer(a) for a in answers]
    mismatch = "Those details did not match. Check your answers and try again."

    if not (identity or "").strip():
        return False, "Enter your email or username."
    if any(len(a) < MIN_ANSWER_LENGTH for a in answers):
        return False, "Answer all three security questions."
    if not valid_password(new_password):
        return False, f"Password must be {MIN_PASSWORD_LENGTH}–{MAX_PASSWORD_LENGTH} characters."
    if new_password != confirm:
        return False, "Passwords do not match."

    user = find_user(identity)
    if not user:
        return False, mismatch  # same message as a wrong answer

    email = user["email"]
    minutes = _locked_minutes(email)
    if minutes:
        return False, f"Too many failed attempts. Try again in {minutes} minute(s)."

    stored = [user[column] for column, _ in SECURITY_QUESTIONS]
    if any(h is None for h in stored):
        return False, ("This account has no security answers saved. "
                       "Use the Email OTP option instead.")

    # check all three (no early exit) so timing doesn't reveal which one was wrong
    results = [check_secret(a, h) for a, h in zip(answers, stored)]
    if not all(results):
        _record_answer_failure(email)
        return False, mismatch

    with db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (hash_secret(new_password), email),
        )
        conn.execute("DELETE FROM answer_attempts WHERE email = ?", (email,))
        conn.execute("DELETE FROM password_resets WHERE email = ?", (email,))
        conn.execute("DELETE FROM login_attempts WHERE email = ?", (email,))  # unlock
    return True, "Password reset successful. Please sign in."


# ----- Reset method 2: email OTP -----


def request_otp(email):
    """Returns (ok, message). Never reveals whether an account exists."""
    email = normalize_email(email)
    generic = "If this email belongs to an account, an OTP has been sent."

    user = find_user(email)
    if not user or user["email"] != email:
        return True, generic

    with db() as conn:
        old = conn.execute(
            "SELECT last_sent_at FROM password_resets WHERE email = ?", (email,)
        ).fetchone()

    if old:
        elapsed = (now_utc() - parse_time(old["last_sent_at"])).total_seconds()
        if elapsed < OTP_RESEND_SECONDS:
            wait = int(OTP_RESEND_SECONDS - elapsed) + 1
            return False, f"Please wait {wait} seconds before requesting another OTP."

    otp = f"{secrets.randbelow(1_000_000):06d}"
    send_otp_email(email, otp)  # save only after a successful send

    with db() as conn:
        conn.execute(
            """INSERT INTO password_resets
                   (email, otp_hash, expires_at, attempts, verified_at, last_sent_at)
               VALUES (?, ?, ?, 0, NULL, ?)
               ON CONFLICT(email) DO UPDATE SET
                   otp_hash = excluded.otp_hash,
                   expires_at = excluded.expires_at,
                   attempts = 0,
                   verified_at = NULL,
                   last_sent_at = excluded.last_sent_at""",
            (
                email,
                hash_secret(otp),
                (now_utc() + timedelta(minutes=OTP_MINUTES)).isoformat(),
                now_utc().isoformat(),
            ),
        )
    return True, generic


def verify_otp(email, otp):
    email = normalize_email(email)
    otp = (otp or "").strip()

    if not re.fullmatch(r"\d{6}", otp):
        return False, "Enter the 6-digit OTP."

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM password_resets WHERE email = ?", (email,)
        ).fetchone()

        if not row:
            return False, "Request an OTP first."
        if row["attempts"] >= MAX_OTP_ATTEMPTS:
            return False, "Too many attempts. Request a new OTP."
        if now_utc() > parse_time(row["expires_at"]):
            return False, "OTP expired. Request a new one."
        if not check_secret(otp, row["otp_hash"]):
            conn.execute(
                "UPDATE password_resets SET attempts = attempts + 1 WHERE email = ?",
                (email,),
            )
            left = MAX_OTP_ATTEMPTS - row["attempts"] - 1
            return False, f"Invalid OTP. {left} attempt(s) left."

        conn.execute(
            "UPDATE password_resets SET verified_at = ? WHERE email = ?",
            (now_utc().isoformat(), email),
        )
    return True, "OTP verified. Set your new password below."


def reset_password(email, new_password, confirm):
    email = normalize_email(email)

    if not valid_password(new_password):
        return False, f"Password must be {MIN_PASSWORD_LENGTH}–{MAX_PASSWORD_LENGTH} characters."
    if new_password != confirm:
        return False, "Passwords do not match."

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM password_resets WHERE email = ?", (email,)
        ).fetchone()
        if not row or not row["verified_at"]:
            return False, "Verify your OTP first."
        if now_utc() > parse_time(row["expires_at"]):
            return False, "OTP expired. Request a new one."

        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (hash_secret(new_password), email),
        )
        conn.execute("DELETE FROM password_resets WHERE email = ?", (email,))
        conn.execute("DELETE FROM login_attempts WHERE email = ?", (email,))  # unlock
    return True, "Password reset successful. Please sign in."


# ---------------- UI ----------------
# Enterprise UI (fq_ui.py). All authentication logic above is unchanged.

import fq_ui

ss = st.session_state
ss.setdefault("user", None)
ss.setdefault("flash", None)
ss.setdefault("auth_mode", "Sign In")

fq_ui.inject_base_css()


def _sign_out():
    for key in ("user", "fq_page", "fq_copilot_history", "fq_pending_q", "customer_view",
                "selected_login_role", "otp_email", "otp_verified_email"):
        ss.pop(key, None)
    ss.user = None
    ss.auth_mode = "Sign In"


# ---- Signed-in view ----
if ss.user:
    if ss.flash:
        st.toast(ss.flash)
        ss.flash = None
    fq_ui.render_app(ss.user, db_path=DB_PATH, on_sign_out=_sign_out)
    st.stop()


# ---- Signed-out view (Sign In / Register / Forgot Password) ----
if ss.get("next_mode"):
    ss.auth_mode = ss.pop("next_mode")
mode = ss.auth_mode


def _set_mode(new_mode):
    ss.auth_mode = new_mode


fq_ui.inject_login_css(mode)

# Phase 1 RBAC: the selected workspace must match the account's database role.
ROLE_ALIASES = {
    "admin": "admin",
    "operations manager": "operations manager",
    "freight broker": "freight broker",
    "auditor": "auditor",
    "customer": "customer",
}

with st.container(key="fq_login"):
    hero_col, form_col = st.columns([1.08, 1], gap=None)
    with hero_col:
        fq_ui.render_login_hero()
    with form_col:
        with st.container(key="fq_auth_panel"):
            fq_ui.render_auth_header(mode)

            if ss.flash:
                st.success(ss.flash)
                ss.flash = None

            # ---- Sign In ----
            if mode == "Sign In":
                with st.form("signin_form", border=False):
                    identity = st.text_input("Email or username", max_chars=254)
                    password = st.text_input("Password", type="password",
                                             max_chars=MAX_PASSWORD_LENGTH)
                    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
                    c_submit, c_links = st.columns([1, 2.2], vertical_alignment="center")
                    with c_submit:
                        submit = st.form_submit_button("Sign in", type="primary")
                    with c_links:
                        with st.container(horizontal=True, horizontal_alignment="right",
                                          key="fq_auth_links"):
                            st.form_submit_button("Register", type="tertiary",
                                                  on_click=_set_mode, args=("Register",))
                            st.form_submit_button("Forgot password", type="tertiary",
                                                  on_click=_set_mode, args=("Forgot Password",))

                if submit and ss.auth_mode == "Sign In":
                    user, error = authenticate(identity, password)
                    if user:
                        selected_role = ss.get("selected_login_role")
                        actual_role = str(user["role"]).strip().casefold()
                        expected_role = ROLE_ALIASES.get(
                            str(selected_role).strip().casefold()) if selected_role else None
                        verified_role = ROLE_ALIASES.get(actual_role)

                        if expected_role is None:
                            st.warning("Please select a workspace before signing in.")
                        elif verified_role is None:
                            st.error("Your account has an unrecognized role. "
                                     "Please contact an administrator.")
                        elif expected_role != verified_role:
                            st.error(f"Access denied: this account is assigned the "
                                     f"{user['role']} role, not {selected_role}. "
                                     "Select the workspace assigned to your account.")
                        else:
                            ss.user = {"id": user["id"], "username": user["username"],
                                       "email": user["email"], "role": user["role"]}
                            st.rerun()
                    else:
                        st.error(error)

                fq_ui.render_role_chips(ss.get("selected_login_role"))

            # ---- Register ----
            elif mode == "Register":
                with st.form("register_form", clear_on_submit=False, border=False):
                    username = st.text_input("Username", max_chars=50)
                    email = st.text_input("Email address", max_chars=254)
                    password = st.text_input("Password", type="password",
                                             max_chars=MAX_PASSWORD_LENGTH)
                    confirm = st.text_input("Confirm password", type="password",
                                            max_chars=MAX_PASSWORD_LENGTH)
                    st.markdown('<div class="fq-auth-heading" style="font-size:13px">Security questions'
                                ' <span style="font-weight:400;color:#6b7280">(used to reset your '
                                'password)</span></div>', unsafe_allow_html=True)
                    reg_answers = [
                        st.text_input(question, max_chars=100, key=f"reg_{column}")
                        for column, question in SECURITY_QUESTIONS
                    ]
                    c_submit, c_links = st.columns([1, 1.4], vertical_alignment="center")
                    with c_submit:
                        submit = st.form_submit_button("Create account", type="primary")
                    with c_links:
                        with st.container(horizontal=True, horizontal_alignment="right",
                                          key="fq_auth_links"):
                            st.form_submit_button("Back to sign in", type="tertiary",
                                                  on_click=_set_mode, args=("Sign In",))

                if submit and ss.auth_mode == "Register":
                    ok, msg = register_user(username, email, password, confirm, reg_answers)
                    if ok:
                        ss.flash = msg
                        ss.next_mode = "Sign In"
                        st.rerun()
                    else:
                        st.error(msg)

            # ---- Forgot Password ----
            else:
                method = st.radio("Reset method", ["Security questions", "Email OTP"],
                                  horizontal=True, key="reset_method",
                                  label_visibility="collapsed")

                # -- Method 1: security questions --
                if method == "Security questions":
                    with st.form("reset_answers_form", border=False):
                        identity = st.text_input("Email or username", max_chars=254)
                        reset_answers = [
                            st.text_input(question, max_chars=100, key=f"reset_{column}")
                            for column, question in SECURITY_QUESTIONS
                        ]
                        new_password = st.text_input("New password", type="password",
                                                     max_chars=MAX_PASSWORD_LENGTH, key="qa_new_pw")
                        confirm_password = st.text_input("Confirm new password", type="password",
                                                         max_chars=MAX_PASSWORD_LENGTH,
                                                         key="qa_confirm_pw")
                        change = st.form_submit_button("Reset password", type="primary")

                    if change:
                        ok, msg = reset_with_answers(identity, reset_answers, new_password,
                                                     confirm_password)
                        if ok:
                            ss.flash = msg
                            ss.next_mode = "Sign In"
                            st.rerun()
                        else:
                            st.error(msg)

                # -- Method 2: email OTP --
                else:
                    with st.form("request_otp_form", border=False):
                        email = st.text_input("Registered email address", max_chars=254)
                        send = st.form_submit_button("Send OTP", type="primary")

                    if send:
                        email = normalize_email(email)
                        if not EMAIL_RE.fullmatch(email):
                            st.error("Enter a valid email address.")
                        else:
                            try:
                                ok, msg = request_otp(email)
                                if ok:
                                    ss.otp_email = email
                                    ss.pop("otp_verified_email", None)
                                    st.success(msg)
                                else:
                                    st.warning(msg)
                            except Exception as exc:
                                st.error("Email delivery failed. Check SMTP_EMAIL / SMTP_APP_PASSWORD, "
                                         "or use the Security questions option.")
                                print("SMTP error:", type(exc).__name__, str(exc)[:200])

                    reset_email = ss.get("otp_email")

                    if reset_email and ss.get("otp_verified_email") != reset_email:
                        st.caption(f"OTP requested for: {reset_email}")
                        with st.form("verify_otp_form", border=False):
                            otp = st.text_input("6-digit OTP", max_chars=6)
                            verify = st.form_submit_button("Verify OTP")
                        if verify:
                            ok, msg = verify_otp(reset_email, otp)
                            if ok:
                                ss.otp_verified_email = reset_email
                                st.rerun()
                            else:
                                st.error(msg)

                    if reset_email and ss.get("otp_verified_email") == reset_email:
                        st.success("OTP verified. Set your new password.")
                        with st.form("reset_password_form", border=False):
                            new_password = st.text_input("New password", type="password",
                                                         max_chars=MAX_PASSWORD_LENGTH,
                                                         key="otp_new_pw")
                            confirm_password = st.text_input("Confirm new password", type="password",
                                                             max_chars=MAX_PASSWORD_LENGTH,
                                                             key="otp_confirm_pw")
                            change = st.form_submit_button("Reset password", type="primary")
                        if change:
                            ok, msg = reset_password(reset_email, new_password, confirm_password)
                            if ok:
                                ss.pop("otp_email", None)
                                ss.pop("otp_verified_email", None)
                                ss.flash = msg
                                ss.next_mode = "Sign In"
                                st.rerun()
                            else:
                                st.error(msg)

                st.button("Back to sign in", type="tertiary", key="fq_back_signin",
                          on_click=_set_mode, args=("Sign In",))
