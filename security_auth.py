
import sqlite3
import bcrypt
import time
import re
from pathlib import Path

DB_PATH = Path(
    "/content/drive/MyDrive/FreightQuote_AI/database/security_auth.db"
)

MAX_ATTEMPTS = 3
LOCK_SECONDS = 15 * 60

QUESTIONS = {
    "pet": "What is your pet's name?",
    "school": "What was your first school's name?",
    "city": "What is your favourite city?",
}

def connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_users (
                email TEXT PRIMARY KEY,
                password_hash BLOB NOT NULL,
                pet_hash BLOB NOT NULL,
                school_hash BLOB NOT NULL,
                city_hash BLOB NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0
            )
        """)

def normalize(value):
    return " ".join(value.strip().casefold().split())

def hash_value(value):
    return bcrypt.hashpw(
        normalize(value).encode("utf-8"),
        bcrypt.gensalt(rounds=12)
    )

def check_value(value, stored_hash):
    try:
        return bcrypt.checkpw(
            normalize(value).encode("utf-8"),
            bytes(stored_hash)
        )
    except (ValueError, TypeError):
        return False

def valid_password(password):
    return (
        len(password) >= 10
        and bool(re.search(r"[A-Z]", password))
        and bool(re.search(r"[a-z]", password))
        and bool(re.search(r"\d", password))
    )

def register_user(email, password, pet, school, city):
    email = email.strip().lower()

    if not valid_password(password):
        return False, "Use at least 10 characters, uppercase, lowercase and a number."

    if not all(x.strip() for x in [email, pet, school, city]):
        return False, "All fields are required."

    try:
        with connect_db() as conn:
            conn.execute("""
                INSERT INTO auth_users
                (email, password_hash, pet_hash, school_hash, city_hash)
                VALUES (?, ?, ?, ?, ?)
            """, (
                email, hash_value(password), hash_value(pet),
                hash_value(school), hash_value(city)
            ))
        return True, "Account created successfully."
    except sqlite3.IntegrityError:
        return False, "Unable to create account. Check the details."

def login_user(email, password):
    email = email.strip().lower()

    with connect_db() as conn:
        user = conn.execute(
            "SELECT * FROM auth_users WHERE email = ?", (email,)
        ).fetchone()

        if not user:
            return False, "Invalid email or password."

        now = time.time()

        if user["locked_until"] > now:
            mins = int((user["locked_until"] - now + 59) // 60)
            return False, f"Account locked. Try again in {mins} minute(s)."

        if user["locked_until"] and user["locked_until"] <= now:
            conn.execute("""
                UPDATE auth_users
                SET failed_attempts = 0, locked_until = 0
                WHERE email = ?
            """, (email,))

        if check_value(password, user["password_hash"]):
            conn.execute("""
                UPDATE auth_users
                SET failed_attempts = 0, locked_until = 0
                WHERE email = ?
            """, (email,))
            return True, "Login successful."

        attempts = user["failed_attempts"] + 1

        if attempts >= MAX_ATTEMPTS:
            conn.execute("""
                UPDATE auth_users
                SET failed_attempts = ?, locked_until = ?
                WHERE email = ?
            """, (attempts, now + LOCK_SECONDS, email))
            return False, "Account locked for 15 minutes after 3 failed attempts."

        conn.execute("""
            UPDATE auth_users SET failed_attempts = ? WHERE email = ?
        """, (attempts, email))
        return False, f"Invalid email or password. Attempts remaining: {MAX_ATTEMPTS - attempts}."

def reset_password(email, pet, school, city, new_password):
    email = email.strip().lower()

    if not valid_password(new_password):
        return False, "Use at least 10 characters, uppercase, lowercase and a number."

    with connect_db() as conn:
        user = conn.execute(
            "SELECT * FROM auth_users WHERE email = ?", (email,)
        ).fetchone()

        if not user:
            return False, "Unable to verify account or security answers."

        if not all([
            check_value(pet, user["pet_hash"]),
            check_value(school, user["school_hash"]),
            check_value(city, user["city_hash"])
        ]):
            return False, "Unable to verify account or security answers."

        conn.execute("""
            UPDATE auth_users
            SET password_hash = ?, failed_attempts = 0, locked_until = 0
            WHERE email = ?
        """, (hash_value(new_password), email))

    return True, "Password reset successfully."

init_db()
