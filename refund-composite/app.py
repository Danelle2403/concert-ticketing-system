from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import re
import requests

app = Flask(__name__)
CORS(app)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
PURCHASE_SERVICE_URL = os.environ.get("PURCHASE_SERVICE_URL", "http://purchase-composite:5000")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://seat-inventory:5000")
PAYMENT_SERVICE_URL = os.environ.get("PAYMENT_SERVICE_URL", "http://payment-service:5000")
EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL", "http://event-service:5000")
NOTIFICATION_SERVICE_URL = os.environ.get(
    "NOTIFICATION_SERVICE_URL", "http://notification-service:5000"
)
CUSTOMER_SUPPORT_EMAIL = os.environ.get("CUSTOMER_SUPPORT_EMAIL", "support@concerthub.local")


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


def extract_data(body):
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return body


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


def normalize_source(value):
    source = str(value or "customer_request").strip().lower()
    allowed = {"customer_request", "event_change_request", "event_cancelled"}
    return source if source in allowed else "customer_request"


def to_minor_units(amount):
    return int(round(float(amount or 0) * 100))


def fetch_user(user_id):
    code, body = req_json("GET", f"{USER_SERVICE_URL}/user/{user_id}")
    return extract_data(body) if code == 200 else None


def fetch_event(event_id):
    code, body = req_json("GET", f"{EVENT_SERVICE_URL}/events/{event_id}")
    return extract_data(body) if code == 200 else None


def fetch_manager_for_event(event_id):
    event = fetch_event(event_id)
    if not event:
        return event, None
    manager_id = event.get("managerId")
    if manager_id is None:
        return event, None
    return event, fetch_user(manager_id)


def notify_success(ticket, mapping, refund, source):
    user = fetch_user(ticket.get("userId"))
    event, manager = fetch_manager_for_event(mapping.get("eventId") or ticket.get("eventId"))
    payload = {
        "ticketId": mapping.get("ticketId") or ticket.get("ticketId"),
        "purchaseId": mapping.get("purchaseId"),
        "refundId": refund.get("refundId"),
        "paymentIntentId": mapping.get("paymentIntentId"),
        "paymentChargeId": mapping.get("paymentChargeId"),
        "amountPaid": mapping.get("amountPaid"),
        "currency": mapping.get("currency") or "sgd",
        "source": source,
        "supportEmail": CUSTOMER_SUPPORT_EMAIL,
        "event": {
            "eventId": mapping.get("eventId") or ticket.get("eventId"),
            "title": mapping.get("eventName") or (event or {}).get("title"),
            "venue": mapping.get("venue") or (event or {}).get("venue"),
            "date": mapping.get("date") or (event or {}).get("startAt"),
        },
        "fan": user,
        "manager": manager,
    }
    req_json(
        "POST",
        f"{NOTIFICATION_SERVICE_URL}/notifications/refund-success",
        payload,
        timeout=10,
    )


def notify_failure(ticket, mapping, source, reason, error_details):
    user = fetch_user(ticket.get("userId"))
    event, manager = fetch_manager_for_event(mapping.get("eventId") or ticket.get("eventId"))
    payload = {
        "ticketId": mapping.get("ticketId") or ticket.get("ticketId"),
        "purchaseId": mapping.get("purchaseId"),
        "paymentIntentId": mapping.get("paymentIntentId"),
        "amountPaid": mapping.get("amountPaid"),
        "currency": mapping.get("currency") or "sgd",
        "source": source,
        "reason": reason,
        "error": error_details,
        "supportEmail": CUSTOMER_SUPPORT_EMAIL,
        "event": {
            "eventId": mapping.get("eventId") or ticket.get("eventId"),
            "title": mapping.get("eventName") or (event or {}).get("title"),
            "venue": mapping.get("venue") or (event or {}).get("venue"),
            "date": mapping.get("date") or (event or {}).get("startAt"),
        },
        "fan": user,
        "manager": manager,
    }
    req_json(
        "POST",
        f"{NOTIFICATION_SERVICE_URL}/notifications/refund-failure",
        payload,
        timeout=10,
    )


def refund_single(ticket_id, source="customer_request", reason=None):
    ticket_id = normalize_ticket_id(ticket_id)
    source = normalize_source(source)

    code, ticket = req_json("GET", f"{USER_SERVICE_URL}/user/ticket/{ticket_id}")
    if code != 200:
        return False, {"error": "Ticket not found", "ticketId": ticket_id}, 404

    if str(ticket.get("status") or "").lower() != "active":
        return False, {"error": "Ticket is not active", "ticketId": ticket_id}, 409

    code, mapping = req_json("GET", f"{PURCHASE_SERVICE_URL}/purchase/ticket/{ticket_id}")
    if code != 200:
        return False, {"error": "Purchase mapping not found", "ticketId": ticket_id}, 404

    if not mapping.get("paymentIntentId"):
        return (
            False,
            {
                "error": "Ticket purchase does not have a Stripe payment intent",
                "ticketId": ticket_id,
            },
            409,
        )

    refund_request = {
        "paymentIntentId": mapping.get("paymentIntentId"),
        "amount": to_minor_units(mapping.get("amountPaid")),
        "reason": "requested_by_customer",
        "metadata": {
            "ticketId": ticket_id,
            "eventId": str(mapping.get("eventId") or ticket.get("eventId") or ""),
            "purchaseId": str(mapping.get("purchaseId") or ""),
            "source": source,
        },
    }
    code, refund_body = req_json(
        "POST",
        f"{PAYMENT_SERVICE_URL}/refunds",
        refund_request,
        timeout=15,
    )
    if code != 201:
        notify_failure(ticket, mapping, source, reason, refund_body)
        return (
            False,
            {
                "error": "Stripe refund failed",
                "ticketId": ticket_id,
                "details": refund_body,
            },
            502,
        )

    refund = extract_data(refund_body)
    hold_id = mapping.get("holdId")

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
        {"status": "REFUNDED", "refundId": refund.get("refundId")},
    )

    notify_success(ticket, mapping, refund, source)
    return (
        True,
        {
            "refundId": refund.get("refundId"),
            "ticketId": ticket_id,
            "purchaseId": mapping.get("purchaseId"),
            "paymentIntentId": mapping.get("paymentIntentId"),
            "status": "refunded",
            "source": source,
        },
        200,
    )


@app.route("/health", methods=["GET"])
def health():
    return (
        jsonify(
            {
                "status": "Refund Composite is running",
                "dependencies": {
                    "userService": USER_SERVICE_URL,
                    "purchaseService": PURCHASE_SERVICE_URL,
                    "seatInventory": SEAT_INVENTORY_URL,
                    "paymentService": PAYMENT_SERVICE_URL,
                    "eventService": EVENT_SERVICE_URL,
                    "notificationService": NOTIFICATION_SERVICE_URL,
                },
            }
        ),
        200,
    )


@app.route("/refunds/<ticketId>", methods=["POST"])
def refund_ticket(ticketId):
    payload = request.get_json(silent=True) or {}
    ok, refund_payload, code = refund_single(
        normalize_ticket_id(ticketId),
        source=payload.get("source"),
        reason=payload.get("reason"),
    )
    return jsonify(refund_payload), code


@app.route("/refunds/event/<eventId>", methods=["POST"])
def refund_event(eventId):
    payload = request.get_json(silent=True) or {}
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
        ok, refund_payload, _ = refund_single(
            tid,
            source=payload.get("source") or "event_cancelled",
            reason=payload.get("reason"),
        )
        if ok:
            success += 1
        results.append(refund_payload)

    return (
        jsonify(
            {
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
