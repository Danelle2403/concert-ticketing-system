from flask import Flask, jsonify
from flask_cors import CORS
import os
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
import pika

app = Flask(__name__)
CORS(app)

DB_PATH = os.environ.get("NOTIFICATION_DB_PATH", "/data/notifications.db")
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
EVENT_EXCHANGE = os.environ.get("EVENT_EXCHANGE", "ticketing.events")
QUEUE_NAME = os.environ.get("NOTIFICATION_QUEUE", "notification.queue")

ROUTING_KEYS = [
    "ticket.purchased",
    "concert.updated",
    "concert.cancelled",
    "refund.confirmed",
    "concert.refund.failed",
]


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
        CREATE TABLE IF NOT EXISTS notification_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routing_key TEXT NOT NULL,
            email TEXT,
            subject TEXT,
            payload TEXT NOT NULL,
            sent_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def record_notification(routing_key, payload):
    email = payload.get("email")
    subject_map = {
        "ticket.purchased": "Ticket Purchase Confirmation",
        "concert.updated": "Concert Updated",
        "concert.cancelled": "Concert Cancelled",
        "refund.confirmed": "Refund Confirmed",
        "concert.refund.failed": "Refund Failed",
    }
    subject = subject_map.get(routing_key, "Concert Notification")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO notification_logs (routing_key, email, subject, payload, sent_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            routing_key,
            email,
            subject,
            json.dumps(payload),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    print(f"[notification-service] sent {routing_key} to {email}")


def consume_loop():
    while True:
        try:
            creds = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            params = pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=creds,
                heartbeat=30,
            )
            connection = pika.BlockingConnection(params)
            channel = connection.channel()

            channel.exchange_declare(exchange=EVENT_EXCHANGE, exchange_type="topic", durable=True)
            channel.queue_declare(queue=QUEUE_NAME, durable=True)

            for key in ROUTING_KEYS:
                channel.queue_bind(exchange=EVENT_EXCHANGE, queue=QUEUE_NAME, routing_key=key)

            def callback(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = {"raw": body.decode("utf-8", errors="ignore")}

                record_notification(method.routing_key, payload)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_qos(prefetch_count=20)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
            channel.start_consuming()
        except Exception as e:
            print(f"[notification-service] consumer reconnect after error: {e}")
            time.sleep(2)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Notification Service is running"}), 200


@app.route("/notifications", methods=["GET"])
def list_notifications():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM notification_logs ORDER BY id DESC LIMIT 200")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"notifications": rows}), 200


if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=consume_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
