import os
from pathlib import Path
import json
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request

app = Flask(__name__)
_db_initialized = False
DEMO_STATE_PATH = Path(__file__).resolve().parents[1] / "demo" / "local_demo_state.json"


def parse_positive_int(value, field_name):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive integer")
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def load_demo_seed_data():
    with DEMO_STATE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)

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
            ticket_id   BIGSERIAL   PRIMARY KEY,
            event_id    BIGINT      NOT NULL,
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
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tickets'
          AND column_name IN ('ticket_id', 'event_id')
        """
    )
    column_types = {row["column_name"]: row["data_type"] for row in cur.fetchall()}
    for column_name in ("ticket_id", "event_id"):
        if column_types.get(column_name) != "bigint":
            raise RuntimeError(
                f"Incompatible ticket_atomic schema: tickets.{column_name} is "
                f"{column_types.get(column_name)!r}. Reset the ticket-atomic database so the integer-ID schema can be applied."
            )
    conn.commit()
    cur.close()
    conn.close()


def ensure_db_initialized():
    global _db_initialized
    if _db_initialized:
        return
    init_db()
    _db_initialized = True


def reset_demo_tickets():
    demo_state = load_demo_seed_data()
    demo_tickets = demo_state["ticketAtomicTickets"]

    ensure_db_initialized()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE tickets RESTART IDENTITY")
    for ticket in demo_tickets:
        cur.execute(
            """
            INSERT INTO tickets (ticket_id, event_id, seat_section, seat_row, seat_number, is_valid, issued_at, invalidated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                ticket["ticketId"],
                ticket["eventId"],
                (ticket.get("seat") or {}).get("section"),
                (ticket.get("seat") or {}).get("row"),
                (ticket.get("seat") or {}).get("number"),
                ticket["isValid"],
                ticket["issuedAt"],
                ticket["invalidatedAt"],
            ),
        )

    if demo_tickets:
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('tickets', 'ticket_id'), %s, true)",
            (max(ticket["ticketId"] for ticket in demo_tickets),),
        )
    conn.commit()
    cur.close()
    conn.close()
    return len(demo_tickets)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def ticket_to_dict(row):
    """Convert a DB row to a JSON-serialisable dict."""
    return {
        "ticket_id":      int(row["ticket_id"]),
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
        ensure_db_initialized()
        conn = get_db()
        conn.close()
        return jsonify({"status": "ok"}), 200
    except Exception as exc:
        return jsonify({"status": "error", "detail": str(exc)}), 500


@app.route("/tickets/admin/reset-demo", methods=["POST"])
def reset_ticket_demo():
    count = reset_demo_tickets()
    return jsonify({"status": "reset", "ticketCount": count}), 200


# POST /tickets/issue
@app.route("/tickets/issue", methods=["POST"])
def issue_ticket():
    """
    Issue a new ticket.

    Body (JSON):
        event_id       integer required
        seat_section   string  optional
        seat_row       string  optional
        seat_number    string  optional
    """
    data = request.get_json(silent=True) or {}

    event_id_raw = data.get("event_id")
    if event_id_raw is None:
        return jsonify({"error": "event_id is required"}), 400
    try:
        event_id = parse_positive_int(event_id_raw, "event_id")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    seat_section = data.get("seat_section")
    seat_row     = data.get("seat_row")
    seat_number  = data.get("seat_number")

    ensure_db_initialized()
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
    """Fetch a single ticket by its integer ID."""
    try:
        ticket_id = parse_positive_int(ticket_id, "ticket_id")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    ensure_db_initialized()
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
    try:
        event_id = parse_positive_int(event_id, "event_id")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    ensure_db_initialized()
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
        ticket_id = parse_positive_int(ticket_id, "ticket_id")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    ensure_db_initialized()
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
    ensure_db_initialized()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
