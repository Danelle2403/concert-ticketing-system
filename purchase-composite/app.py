from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import re
import uuid
import sqlite3
from datetime import datetime, timezone
import requests

app = Flask(__name__)
CORS(app)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL", "http://event-service:5000")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://seat-inventory:5000")
TICKET_SERVICE_URL = os.environ.get("TICKET_SERVICE_URL", "https://ticketatomic-production.up.railway.app")
DB_PATH = os.environ.get("PURCHASE_DB_PATH", "/data/purchase.db")
ORDER_ALIGNED_DEMO_EVENTS = {
    "1": {
        "id": "1",
        "name": "Pulse Arena Nights",
        "venue": "Capitol Theatre, Singapore",
        "date": "2026-04-18",
        "status": "active",
        "defaultSeatCategory": "STANDARD",
    },
    "2": {
        "id": "2",
        "name": "Skyline VIP Session",
        "venue": "Singapore Indoor Stadium",
        "date": "2026-05-02",
        "status": "active",
        "defaultSeatCategory": "VIP",
    },
    "789": {
        "id": "789",
        "name": "Harbour Lights Reunion",
        "venue": "The Star Theatre, Singapore",
        "date": "2026-03-10",
        "status": "cancelled",
        "defaultSeatCategory": "VIP",
    },
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_prefixed_id(value, prefixes):
    if value is None:
        return value

    text = str(value).strip()
    for prefix in prefixes:
        match = re.fullmatch(rf"{prefix}-(\d+)", text, flags=re.IGNORECASE)
        if match:
            return str(int(match.group(1)))

    return text


def normalize_user_id(value):
    normalized = normalize_prefixed_id(value, ("fan",))
    return int(normalized)


def normalize_ticket_id(value):
    return normalize_prefixed_id(value, ("tkt",))


def normalize_event_id(value):
    return normalize_prefixed_id(value, ("con",))


def normalize_seat_category(value):
    if value is None:
        return value
    return str(value).strip().upper()


def seed_order_aligned_demo_data(cur):
    purchase_rows = [
        ("ORDER-1", 123, "789", 1, "VIP", "REFUNDED", "ch_stripe_abc", "2026-03-27T05:42:46+00:00"),
        ("ORDER-2", 1, "1", 1, "VIP", "CANCELLED", "ch_stripe_abc123", "2026-03-27T21:15:59+00:00"),
        ("ORDER-3", 2, "1", 1, "STANDARD", "SUCCESS", "ch_stripe_def456", "2026-03-27T21:16:23+00:00"),
        ("ORDER-4", 3, "2", 1, "VIP", "SUCCESS", "ch_stripe_ghi789", "2026-03-27T21:16:49+00:00"),
    ]
    for row in purchase_rows:
        cur.execute(
            """
            INSERT OR IGNORE INTO purchases
            (purchaseId, userId, eventId, quantity, seatCategory, status, paymentId, createdAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    ticket_rows = [
        (
            "456",
            "ORDER-1",
            "11111111-1111-1111-1111-111111111111",
            123,
            "789",
            "Harbour Lights Reunion",
            "The Star Theatre, Singapore",
            "2026-03-10",
            "VIP",
            "REFUNDED",
            "2026-03-27T05:42:46+00:00",
        ),
        (
            "1",
            "ORDER-2",
            "22222222-2222-2222-2222-222222222222",
            1,
            "1",
            "Pulse Arena Nights",
            "Capitol Theatre, Singapore",
            "2026-04-18",
            "VIP",
            "CANCELLED",
            "2026-03-27T21:15:59+00:00",
        ),
        (
            "2",
            "ORDER-3",
            "33333333-3333-3333-3333-333333333333",
            2,
            "1",
            "Pulse Arena Nights",
            "Capitol Theatre, Singapore",
            "2026-04-18",
            "STANDARD",
            "ACTIVE",
            "2026-03-27T21:16:23+00:00",
        ),
        (
            "3",
            "ORDER-4",
            "44444444-4444-4444-4444-444444444444",
            3,
            "2",
            "Skyline VIP Session",
            "Singapore Indoor Stadium",
            "2026-05-02",
            "VIP",
            "ACTIVE",
            "2026-03-27T21:16:49+00:00",
        ),
    ]
    for row in ticket_rows:
        cur.execute(
            """
            INSERT OR IGNORE INTO ticket_map
            (ticketId, purchaseId, holdId, userId, eventId, eventName, venue, date, seatCategory, status, createdAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS purchases (
            purchaseId TEXT PRIMARY KEY,
            userId INTEGER NOT NULL,
            eventId TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            seatCategory TEXT NOT NULL,
            status TEXT NOT NULL,
            paymentId TEXT,
            createdAt TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_map (
            ticketId TEXT PRIMARY KEY,
            purchaseId TEXT NOT NULL,
            holdId TEXT NOT NULL,
            userId INTEGER NOT NULL,
            eventId TEXT NOT NULL,
            eventName TEXT,
            venue TEXT,
            date TEXT,
            seatCategory TEXT,
            status TEXT NOT NULL,
            createdAt TEXT NOT NULL
        )
        """
    )
    seed_order_aligned_demo_data(cur)
    conn.commit()
    conn.close()


def req_json(method, url, payload=None, timeout=8):
    res = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text}
    return res.status_code, body


def issue_ticket(event_id):
    code, body = req_json("POST", f"{TICKET_SERVICE_URL}/tickets/issue", {"event_id": event_id})
    if code in (200, 201) and body.get("ticket_id"):
        return body["ticket_id"]
    return f"LOCAL-{uuid.uuid4()}"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Purchase Composite is running"}), 200


@app.route("/purchase/checkout", methods=["POST"])
def checkout():
    data = request.get_json() or {}

    user_id_raw = data.get("userId")
    event_id = normalize_event_id(data.get("eventId"))
    quantity = int(data.get("quantity", 1))

    if not user_id_raw or not event_id:
        return jsonify({"error": "userId and eventId are required"}), 400
    if quantity <= 0:
        return jsonify({"error": "quantity must be > 0"}), 400

    try:
        user_id = normalize_user_id(user_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "userId must be an integer"}), 400

    # Validate user
    code, user = req_json("GET", f"{USER_SERVICE_URL}/user/{user_id}")
    if code != 200:
        return jsonify({"error": "User not found"}), 404

    # Validate event
    code, event = req_json("GET", f"{EVENT_SERVICE_URL}/events/{event_id}")
    if code != 200:
        event = ORDER_ALIGNED_DEMO_EVENTS.get(event_id)
        if not event:
            return jsonify({"error": "Event not found"}), 404
    if event.get("status") == "cancelled":
        return jsonify({"error": "Event is cancelled"}), 409

    seat_category = normalize_seat_category(
        data.get("seatCategory") or event.get("defaultSeatCategory") or "CAT1"
    )

    purchase_id = str(uuid.uuid4())
    payment_id = f"PAY-{uuid.uuid4()}"

    created = []
    conn = get_db()
    cur = conn.cursor()

    try:
        for _ in range(quantity):
            # Reserve one seat per ticket for simple per-ticket refund support
            code, hold = req_json(
                "POST",
                f"{SEAT_INVENTORY_URL}/inventory/hold",
                {
                    "eventId": event_id,
                    "seatCategory": seat_category,
                    "quantity": 1,
                    "ttlSeconds": 300,
                },
            )
            if code != 201:
                raise RuntimeError(f"Seat hold failed: {hold}")

            hold_id = hold["holdId"]
            ticket_id = issue_ticket(event_id)

            code, _ = req_json("POST", f"{SEAT_INVENTORY_URL}/inventory/confirm", {"holdId": hold_id})
            if code != 200:
                raise RuntimeError("Seat confirm failed")

            code, _ = req_json(
                "POST",
                f"{USER_SERVICE_URL}/user/tickets/add",
                {
                    "userId": user_id,
                    "ticketId": ticket_id,
                    "eventId": event_id,
                    "eventName": event.get("name"),
                    "venue": event.get("venue"),
                    "date": event.get("date"),
                    "status": "active",
                },
            )
            if code not in (200, 201):
                raise RuntimeError("User ticket write failed")

            created.append({"ticketId": ticket_id, "holdId": hold_id})

        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO purchases (purchaseId, userId, eventId, quantity, seatCategory, status, paymentId, createdAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (purchase_id, user_id, event_id, quantity, seat_category, "SUCCESS", payment_id, now),
        )

        for item in created:
            cur.execute(
                """
                INSERT OR REPLACE INTO ticket_map
                (ticketId, purchaseId, holdId, userId, eventId, eventName, venue, date, seatCategory, status, createdAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["ticketId"],
                    purchase_id,
                    item["holdId"],
                    user_id,
                    event_id,
                    event.get("name"),
                    event.get("venue"),
                    event.get("date"),
                    seat_category,
                    "ACTIVE",
                    now,
                ),
            )

        conn.commit()

        return (
            jsonify(
                {
                    "purchaseId": purchase_id,
                    "status": "SUCCESS",
                    "paymentId": payment_id,
                    "tickets": [c["ticketId"] for c in created],
                }
            ),
            201,
        )

    except Exception as e:
        conn.rollback()

        # Compensating rollback
        for item in created:
            req_json(
                "POST",
                f"{SEAT_INVENTORY_URL}/inventory/release",
                {
                    "holdId": item["holdId"],
                    "allowConfirmedRelease": True,
                    "reason": "PURCHASE_ROLLBACK",
                },
            )
            req_json(
                "POST",
                f"{USER_SERVICE_URL}/user/ticket/{item['ticketId']}/status",
                {"status": "cancelled"},
            )

        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT OR REPLACE INTO purchases (purchaseId, userId, eventId, quantity, seatCategory, status, paymentId, createdAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (purchase_id, user_id, event_id, quantity, seat_category, "FAILED", None, now),
        )
        conn.commit()

        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/purchase/<purchaseId>/status", methods=["GET"])
def purchase_status(purchaseId):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM purchases WHERE purchaseId = ?", (purchaseId,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Purchase not found"}), 404

    return jsonify(dict(row)), 200


@app.route("/purchase/ticket/<ticketId>", methods=["GET"])
def ticket_lookup(ticketId):
    ticketId = normalize_ticket_id(ticketId)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ticket_map WHERE ticketId = ?", (ticketId,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Ticket mapping not found"}), 404

    return jsonify(dict(row)), 200


@app.route("/purchase/ticket/<ticketId>/status", methods=["POST"])
def ticket_update_status(ticketId):
    ticketId = normalize_ticket_id(ticketId)
    data = request.get_json() or {}
    status = data.get("status")
    if not status:
        return jsonify({"error": "status is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE ticket_map SET status = ? WHERE ticketId = ?", (status, ticketId))
    if cur.rowcount == 0:
        conn.rollback()
        conn.close()
        return jsonify({"error": "Ticket mapping not found"}), 404

    conn.commit()
    cur.execute("SELECT * FROM ticket_map WHERE ticketId = ?", (ticketId,))
    row = cur.fetchone()
    conn.close()
    return jsonify(dict(row)), 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
