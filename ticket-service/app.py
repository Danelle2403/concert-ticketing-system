from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import sqlite3
import uuid
from datetime import datetime, timezone

app = Flask(__name__)
CORS(app)

DB_PATH = os.environ.get("TICKET_DB_PATH", "/data/tickets.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            is_valid INTEGER NOT NULL,
            issued_at TEXT NOT NULL,
            invalidated_at TEXT,
            seat_section TEXT,
            seat_row TEXT,
            seat_number TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def normalize(row):
    if not row:
        return None
    return {
        "ticket_id": row["ticket_id"],
        "event_id": row["event_id"],
        "is_valid": bool(row["is_valid"]),
        "issued_at": row["issued_at"],
        "invalidated_at": row["invalidated_at"],
        "seat": {
            "section": row["seat_section"],
            "row": row["seat_row"],
            "number": row["seat_number"],
        },
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/tickets/issue", methods=["POST"])
def issue_ticket():
    data = request.get_json(silent=True) or {}
    event_id = data.get("event_id")
    if not event_id:
        return jsonify({"error": "event_id is required"}), 400

    ticket_id = str(uuid.uuid4())
    issued_at = datetime.now(timezone.utc).isoformat()

    seat = data.get("seat") or {}
    section = seat.get("section")
    row = seat.get("row")
    number = seat.get("number")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tickets
        (ticket_id, event_id, is_valid, issued_at, invalidated_at, seat_section, seat_row, seat_number)
        VALUES (?, ?, 1, ?, NULL, ?, ?, ?)
        """,
        (ticket_id, event_id, issued_at, section, row, number),
    )
    conn.commit()
    cur.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    row_data = cur.fetchone()
    conn.close()

    return jsonify(normalize(row_data)), 201


@app.route("/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    row_data = cur.fetchone()
    conn.close()

    if not row_data:
        return jsonify({"error": "ticket not found"}), 404

    return jsonify(normalize(row_data)), 200


@app.route("/tickets/event/<event_id>", methods=["GET"])
def get_event_tickets(event_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tickets WHERE event_id = ? ORDER BY issued_at DESC", (event_id,))
    rows = cur.fetchall()
    conn.close()
    return jsonify([normalize(r) for r in rows]), 200


@app.route("/tickets/<ticket_id>/invalidate", methods=["POST"])
def invalidate_ticket(ticket_id):
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE tickets
        SET is_valid = 0,
            invalidated_at = ?
        WHERE ticket_id = ?
        """,
        (now, ticket_id),
    )
    if cur.rowcount == 0:
        conn.rollback()
        conn.close()
        return jsonify({"error": "ticket not found"}), 404

    conn.commit()
    cur.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    row_data = cur.fetchone()
    conn.close()

    return jsonify(normalize(row_data)), 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
