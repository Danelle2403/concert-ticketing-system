from flask import Flask, jsonify
from flask_cors import CORS
import os
import re
import uuid
import requests

app = Flask(__name__)
CORS(app)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
PURCHASE_SERVICE_URL = os.environ.get("PURCHASE_SERVICE_URL", "http://purchase-composite:5000")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://seat-inventory:5000")


def env_flag(name, default=False):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def req_json(method, url, payload=None, timeout=8):
    res = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text}
    return res.status_code, body


def normalize_prefixed_id(value, prefixes):
    if value is None:
        return value

    text = str(value).strip()
    for prefix in prefixes:
        match = re.fullmatch(rf"{prefix}-(\d+)", text, flags=re.IGNORECASE)
        if match:
            return str(int(match.group(1)))

    return text


def normalize_ticket_id(value):
    return normalize_prefixed_id(value, ("tkt",))


def normalize_event_id(value):
    return normalize_prefixed_id(value, ("con",))


def refund_single(ticket_id):
    ticket_id = normalize_ticket_id(ticket_id)
    code, ticket = req_json("GET", f"{USER_SERVICE_URL}/user/ticket/{ticket_id}")
    if code != 200:
        return False, {"error": "Ticket not found"}, 404

    if ticket.get("status") != "active":
        return False, {"error": "Ticket is not active", "ticketId": ticket_id}, 409

    code, mapping = req_json("GET", f"{PURCHASE_SERVICE_URL}/purchase/ticket/{ticket_id}")
    hold_id = mapping.get("holdId") if code == 200 else None

    if hold_id:
        req_json(
            "POST",
            f"{SEAT_INVENTORY_URL}/inventory/release",
            {
                "holdId": hold_id,
                "allowConfirmedRelease": True,
                "reason": "REFUND",
            },
        )

    req_json(
        "POST",
        f"{USER_SERVICE_URL}/user/ticket/{ticket_id}/status",
        {"status": "refunded"},
    )

    req_json(
        "POST",
        f"{PURCHASE_SERVICE_URL}/purchase/ticket/{ticket_id}/status",
        {"status": "REFUNDED"},
    )

    refund_id = f"RF-{uuid.uuid4()}"
    return True, {"refundId": refund_id, "ticketId": ticket_id, "status": "refunded"}, 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Refund Composite is running"}), 200


@app.route("/refunds/<ticketId>", methods=["POST"])
def refund_ticket(ticketId):
    ok, payload, code = refund_single(normalize_ticket_id(ticketId))
    return jsonify(payload), code


@app.route("/refunds/event/<eventId>", methods=["POST"])
def refund_event(eventId):
    eventId = normalize_event_id(eventId)
    code, data = req_json(
        "GET",
        f"{USER_SERVICE_URL}/user/tickets/by-event/{eventId}?status=active",
    )
    if code != 200:
        return jsonify({"error": "Unable to fetch tickets for event"}), 500

    tickets = data.get("tickets", [])
    results = []
    success = 0

    for ticket in tickets:
        tid = ticket.get("ticketId")
        ok, payload, _ = refund_single(tid)
        if ok:
            success += 1
        results.append(payload)

    return (
        jsonify(
            {
                "refundBatchId": f"RFB-{uuid.uuid4()}",
                "eventId": eventId,
                "processed": len(tickets),
                "successful": success,
                "failed": len(tickets) - success,
                "results": results,
            }
        ),
        200,
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=env_flag("FLASK_DEBUG", False),
        use_reloader=env_flag("FLASK_USE_RELOADER", False),
    )
