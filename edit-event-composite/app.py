from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import json
import requests
import pika

app = Flask(__name__)
CORS(app)

EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL", "http://event-service:5000")
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
REFUND_SERVICE_URL = os.environ.get("REFUND_SERVICE_URL", "http://refund-composite:5000")

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
EVENT_EXCHANGE = os.environ.get("EVENT_EXCHANGE", "ticketing.events")


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
        print(f"[edit-event-composite] publish failed for {routing_key}: {e}")


def get_active_tickets(event_id):
    code, data = req_json(
        "GET",
        f"{USER_SERVICE_URL}/user/tickets/by-event/{event_id}?status=active",
    )
    if code != 200:
        return []
    return data.get("tickets", [])


def enrich_with_user(ticket):
    user_id = ticket.get("userId")
    email = ticket.get("email")
    name = ticket.get("name")

    if user_id is not None:
        code, user = req_json("GET", f"{USER_SERVICE_URL}/user/{user_id}")
        if code == 200:
            email = email or user.get("email")
            name = name or user.get("name")

    return {
        "ticketId": ticket.get("ticketId"),
        "userId": user_id,
        "email": email,
        "name": name,
        "eventName": ticket.get("eventName"),
        "venue": ticket.get("venue"),
        "date": ticket.get("date"),
    }


def detect_changes(before_event, after_event):
    changed = {}
    for field in ["name", "venue", "date", "price", "genre"]:
        old = before_event.get(field)
        new = after_event.get(field)
        if str(old) != str(new):
            changed[field] = {"from": old, "to": new}
    return changed


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Edit Event Composite is running"}), 200


@app.route("/events/<eventId>/edit", methods=["PUT"])
def edit_event(eventId):
    data = request.get_json() or {}

    # Take a snapshot to include concrete changes in notifications.
    _, before_event = req_json("GET", f"{EVENT_SERVICE_URL}/events/{eventId}")

    code, event = req_json("PUT", f"{EVENT_SERVICE_URL}/events/{eventId}/edit", data)
    if code != 200:
        return jsonify(event), code

    req_json("PUT", f"{USER_SERVICE_URL}/user/managed/{eventId}", data)

    changed = detect_changes(before_event if isinstance(before_event, dict) else {}, event)
    active_tickets = get_active_tickets(eventId)

    for ticket in active_tickets:
        recipient = enrich_with_user(ticket)
        publish_event(
            "concert.updated",
            {
                "eventId": eventId,
                "ticketId": recipient.get("ticketId"),
                "email": recipient.get("email"),
                "name": recipient.get("name"),
                "eventName": event.get("name"),
                "venue": event.get("venue"),
                "date": event.get("date"),
                "changes": changed,
            },
        )

    return jsonify(event), 200


@app.route("/events/<eventId>/cancel", methods=["POST"])
def cancel_event(eventId):
    data = request.get_json(silent=True) or {}

    _, existing_event = req_json("GET", f"{EVENT_SERVICE_URL}/events/{eventId}")
    audience = [enrich_with_user(t) for t in get_active_tickets(eventId)]

    code, event = req_json("POST", f"{EVENT_SERVICE_URL}/events/{eventId}/cancel")
    if code != 200:
        return jsonify(event), code

    req_json("POST", f"{USER_SERVICE_URL}/user/managed/{eventId}/cancel")

    for recipient in audience:
        publish_event(
            "concert.cancelled",
            {
                "eventId": eventId,
                "ticketId": recipient.get("ticketId"),
                "email": recipient.get("email"),
                "name": recipient.get("name"),
                "eventName": event.get("name") or existing_event.get("name"),
                "venue": event.get("venue") or existing_event.get("venue"),
                "date": event.get("date") or existing_event.get("date"),
            },
        )

    refund_payload = {}
    if data.get("simulateFailureTicketIds"):
        refund_payload["simulateFailureTicketIds"] = data.get("simulateFailureTicketIds")

    refund_code, refund_result = req_json(
        "POST",
        f"{REFUND_SERVICE_URL}/refunds/event/{eventId}",
        refund_payload,
    )

    response = {
        "eventId": eventId,
        "status": "cancelled",
        "event": event,
        "refunds": refund_result,
        "audienceNotified": len(audience),
    }

    if refund_code not in (200, 202):
        response["warning"] = "Refund queueing encountered issues"

    return jsonify(response), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
