import os
import uuid
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def get_db():
    """Return a new database connection using DATABASE_URL env var."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    """Create the tickets table if it does not exist yet."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id    TEXT        NOT NULL,
            seat_row    TEXT,
            seat_number TEXT,
            seat_section TEXT,
            is_valid    BOOLEAN     NOT NULL DEFAULT TRUE,
            issued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            invalidated_at TIMESTAMPTZ
        );
    """)
    # Index for fast look-ups by event
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_tickets_event_id ON tickets (event_id);
    """)
    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def ticket_to_dict(row):
    """Convert a DB row to a JSON-serialisable dict."""
    return {
        "ticket_id":      str(row["ticket_id"]),
        "event_id":       row["event_id"],
        "seat": {
            "section": row["seat_section"],
            "row":     row["seat_row"],
            "number":  row["seat_number"],
        },
        "is_valid":       row["is_valid"],
        "issued_at":      row["issued_at"].isoformat() if row["issued_at"] else None,
        "invalidated_at": row["invalidated_at"].isoformat() if row["invalidated_at"] else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Simple liveness probe — also acts as Supabase keep-alive ping."""
    try:
        conn = get_db()
        conn.close()
        return jsonify({"status": "ok"}), 200
    except Exception as exc:
        return jsonify({"status": "error", "detail": str(exc)}), 500


# POST /tickets/issue
@app.route("/tickets/issue", methods=["POST"])
def issue_ticket():
    """
    Issue a new ticket.

    Body (JSON):
        event_id       string  required
        seat_section   string  optional
        seat_row       string  optional
        seat_number    string  optional
    """
    data = request.get_json(silent=True) or {}

    event_id = data.get("event_id")
    if not event_id:
        return jsonify({"error": "event_id is required"}), 400

    seat_section = data.get("seat_section")
    seat_row     = data.get("seat_row")
    seat_number  = data.get("seat_number")

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        """
        INSERT INTO tickets (event_id, seat_section, seat_row, seat_number)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (event_id, seat_section, seat_row, seat_number),
    )
    ticket = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ticket_to_dict(ticket)), 201


# GET /tickets/<ticket_id>
@app.route("/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    """Fetch a single ticket by its UUID."""
    try:
        uuid.UUID(ticket_id)          # validate format early
    except ValueError:
        return jsonify({"error": "Invalid ticket_id format"}), 400

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
    ticket = cur.fetchone()
    cur.close()
    conn.close()

    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    return jsonify(ticket_to_dict(ticket)), 200


# GET /tickets/event/<event_id>
@app.route("/tickets/event/<event_id>", methods=["GET"])
def get_tickets_by_event(event_id):
    """Return all tickets for a given event_id."""
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM tickets WHERE event_id = %s ORDER BY issued_at DESC",
        (event_id,),
    )
    tickets = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([ticket_to_dict(t) for t in tickets]), 200


# POST /tickets/<ticket_id>/invalidate
@app.route("/tickets/<ticket_id>/invalidate", methods=["POST"])
def invalidate_ticket(ticket_id):
    """
    Mark a ticket as invalid (one-way operation).
    Returns 409 if the ticket is already invalid.
    """
    try:
        uuid.UUID(ticket_id)
    except ValueError:
        return jsonify({"error": "Invalid ticket_id format"}), 400

    conn = get_db()
    cur  = conn.cursor()

    # Check existence first
    cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
    ticket = cur.fetchone()

    if not ticket:
        cur.close()
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404

    if not ticket["is_valid"]:
        cur.close()
        conn.close()
        return jsonify({"error": "Ticket is already invalidated"}), 409

    now = datetime.now(timezone.utc)
    cur.execute(
        """
        UPDATE tickets
        SET is_valid = FALSE, invalidated_at = %s
        WHERE ticket_id = %s
        RETURNING *
        """,
        (now, ticket_id),
    )
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(ticket_to_dict(updated)), 200


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
