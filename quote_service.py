import os
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(
    os.environ.get("FREIGHTQUOTE_DB", BASE_DIR / "freightquote.db")
)

VALID_CARGO_TYPES = {
    "General cargo",
    "Refrigerated cargo",
    "Hazardous cargo",
    "Bulk cargo",
    "Other",
}

VALID_CONTAINER_TYPES = {
    "20 ft",
    "40 ft",
    "40 ft High Cube",
    "Refrigerated",
    "Not sure",
}


def connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_quotes_table():
    """Create the quote table only when explicitly called."""
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS freight_quotes (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                origin_port TEXT NOT NULL,
                destination_port TEXT NOT NULL,
                cargo_type TEXT NOT NULL,
                container_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                shipment_date TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL
            )
        """)


def create_quote(
    user,
    origin_port,
    destination_port,
    cargo_type,
    container_type,
    quantity,
    shipment_date,
    notes="",
):
    """Store a quote request for the currently authenticated user."""
    if not user or not user.get("id") or not user.get("username"):
        raise ValueError("An authenticated user is required.")

    origin_port = (origin_port or "").strip()
    destination_port = (destination_port or "").strip()
    notes = (notes or "").strip()

    if not origin_port or not destination_port:
        raise ValueError("Origin and destination ports are required.")

    if origin_port.casefold() == destination_port.casefold():
        raise ValueError("Origin and destination must be different.")

    if cargo_type not in VALID_CARGO_TYPES:
        raise ValueError("Invalid cargo type.")

    if container_type not in VALID_CONTAINER_TYPES:
        raise ValueError("Invalid container type.")

    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ValueError("Quantity must be a whole number.")

    if not 1 <= quantity <= 10000:
        raise ValueError("Quantity must be between 1 and 10000.")

    if not shipment_date:
        raise ValueError("Shipment date is required.")

    quote_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with connect_db() as conn:
        conn.execute("""
            INSERT INTO freight_quotes (
                id, user_id, username, origin_port, destination_port,
                cargo_type, container_type, quantity, shipment_date,
                notes, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (
            quote_id,
            int(user["id"]),
            str(user["username"]),
            origin_port,
            destination_port,
            cargo_type,
            container_type,
            quantity,
            str(shipment_date),
            notes,
            created_at,
        ))

    return quote_id


def list_my_quotes(user):
    """Return only quote requests belonging to the authenticated user."""
    if not user or not user.get("id"):
        raise ValueError("An authenticated user is required.")

    with connect_db() as conn:
        rows = conn.execute("""
            SELECT id, origin_port, destination_port, cargo_type,
                   container_type, quantity, shipment_date, notes,
                   status, created_at
            FROM freight_quotes
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (int(user["id"]),)).fetchall()

    return [dict(row) for row in rows]
