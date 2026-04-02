from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import uuid
import sqlite3
from datetime import datetime, timezone
import requests

app = Flask(__name__)
CORS(app)

# ── Service URLs ──
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL", "http://event-service:5000")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://seat-inventory:5000")
TICKET_SERVICE_URL = os.environ.get("TICKET_SERVICE_URL", "https://ticketatomic-production.up.railway.app")
ORDER_SERVICE_URL = os.environ.get(
    "ORDER_SERVICE_URL",
    "https://personal-uq3wxrah.outsystemscloud.com/OrderService/rest/Order",
)
DB_PATH = os.environ.get("PURCHASE_DB_PATH", "/data/purchase.db")


# ── Local DB for ticket_map only ──
# We keep ticket_map locally because it tracks holdId-to-ticketId mappings
# needed for compensating transactions (seat releases, refunds).
# The Order/purchase record itself lives in the OutSystems Order service.

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
    conn.commit()
    conn.close()


def req_json(method, url, payload=None, timeout=8):
    """Fire an HTTP request and return (status_code, parsed_body)."""
    res = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text}
    return res.status_code, body


def issue_ticket(event_id):
    """Ask the Ticket Atomic service for a new ticket ID."""
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

    user_id = data.get("userId")
    event_id = data.get("eventId")
    quantity = int(data.get("quantity", 1))

    if not user_id or not event_id:
        return jsonify({"error": "userId and eventId are required"}), 400
    if quantity <= 0:
        return jsonify({"error": "quantity must be > 0"}), 400

    # ── 1. Validate user ──
    code, user = req_json("GET", f"{USER_SERVICE_URL}/user/{user_id}")
    if code != 200:
        return jsonify({"error": "User not found"}), 404

    # ── 2. Validate event ──
    code, event = req_json("GET", f"{EVENT_SERVICE_URL}/events/{event_id}")
    if code != 200:
        return jsonify({"error": "Event not found"}), 404
    if event.get("status") == "cancelled":
        return jsonify({"error": "Event is cancelled"}), 409

    seat_category = data.get("seatCategory") or event.get("defaultSeatCategory") or "CAT1"

    purchase_id = str(uuid.uuid4())
    payment_id = f"PAY-{uuid.uuid4()}"

    created = []
    conn = get_db()
    cur = conn.cursor()

    try:
        # ── 3. Reserve seats & issue tickets ──
        for _ in range(quantity):
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
                    "userId": int(user_id),
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

        order_payload = {
            "UserId": int(user_id),
            "EventId": event_id,
            "Quantity": quantity,
            "SeatCategory": seat_category,
            "Status": "SUCCESS",
            "PaymentId": payment_id,
            "TicketIds": ",".join(item["ticketId"] for item in created),
            "CreatedAt": datetime.now(timezone.utc).isoformat(),
        }

        code, order_resp = req_json("POST", f"{ORDER_SERVICE_URL}/", order_payload)
        if code not in (200, 201):
            raise RuntimeError(f"Order creation failed: {order_resp}")

        # ── 5. Save ticket_map locally (for hold/refund tracking) ──
        now = datetime.now(timezone.utc).isoformat()
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
                    int(user_id),
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

        # OutSystems usually returns the created record with an Id field
        order_id = order_resp.get("Id") or order_resp.get("OrderId") or purchase_id

        return (
            jsonify(
                {
                    "purchaseId": purchase_id,
                    "orderId": order_id,
                    "status": "SUCCESS",
                    "paymentId": payment_id,
                    "tickets": [c["ticketId"] for c in created],
                }
            ),
            201,
        )

    except Exception as e:
        conn.rollback()

        # ── Compensating rollback ──
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

        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/purchase/<purchaseId>/status", methods=["GET"])
def purchase_status(purchaseId):
    """Look up order from OutSystems Order Service."""
    # TODO: Confirm with Vidhi how to look up orders — by her auto-generated Id,
    #       or if she added a filter endpoint like ?PurchaseId=...
    #       For now this tries to fetch by purchaseId directly.
    code, body = req_json("GET", f"{ORDER_SERVICE_URL}/{purchaseId}")
    if code != 200:
        return jsonify({"error": "Purchase not found"}), 404
    return jsonify(body), 200


@app.route("/purchase/ticket/<ticketId>", methods=["GET"])
def ticket_lookup(ticketId):
    """Look up ticket mapping from local ticket_map."""
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
    """Update ticket status in local ticket_map."""
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
