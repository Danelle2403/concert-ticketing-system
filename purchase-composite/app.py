from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import json
import uuid
import sqlite3
from datetime import datetime, timezone
import requests
import pika

app = Flask(__name__)
CORS(app)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL", "http://event-service:5000")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://seat-inventory:5000")
TICKET_SERVICE_URL = os.environ.get("TICKET_SERVICE_URL", "http://ticket-service:5000")
DB_PATH = os.environ.get("PURCHASE_DB_PATH", "/data/purchase.db")
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
EVENT_EXCHANGE = os.environ.get("EVENT_EXCHANGE", "ticketing.events")


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
    conn.commit()
    conn.close()


def req_json(method, url, payload=None, timeout=8):
    res = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text}
    return res.status_code, body


def publish_event(routing_key, payload):
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            credentials=credentials,
            heartbeat=30,
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.exchange_declare(exchange=EVENT_EXCHANGE, exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange=EVENT_EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(payload),
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
        )
        connection.close()
    except Exception as e:
        print(f"[purchase-composite] publish failed for {routing_key}: {e}")


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

    user_id = data.get("userId")
    event_id = data.get("eventId")
    quantity = int(data.get("quantity", 1))

    if not user_id or not event_id:
        return jsonify({"error": "userId and eventId are required"}), 400
    if quantity <= 0:
        return jsonify({"error": "quantity must be > 0"}), 400

    # Validate user
    code, user = req_json("GET", f"{USER_SERVICE_URL}/user/{user_id}")
    if code != 200:
        return jsonify({"error": "User not found"}), 404

    # Validate event
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

        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO purchases (purchaseId, userId, eventId, quantity, seatCategory, status, paymentId, createdAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (purchase_id, int(user_id), event_id, quantity, seat_category, "SUCCESS", payment_id, now),
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

        buyer_email = data.get("email") or user.get("email")
        buyer_name = data.get("name") or user.get("name")
        for item in created:
            publish_event(
                "ticket.purchased",
                {
                    "purchaseId": purchase_id,
                    "ticketId": item["ticketId"],
                    "userId": int(user_id),
                    "email": buyer_email,
                    "name": buyer_name,
                    "eventId": event_id,
                    "eventName": event.get("name"),
                    "venue": event.get("venue"),
                    "date": event.get("date"),
                    "seatCategory": seat_category,
                    "paymentId": payment_id,
                },
            )

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
            (purchase_id, int(user_id), event_id, quantity, seat_category, "FAILED", None, now),
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
