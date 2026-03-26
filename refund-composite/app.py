from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import json
import threading
import time
import uuid
import requests
import pika

app = Flask(__name__)
CORS(app)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
PURCHASE_SERVICE_URL = os.environ.get("PURCHASE_SERVICE_URL", "http://purchase-composite:5000")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://seat-inventory:5000")
TICKET_SERVICE_URL = os.environ.get("TICKET_SERVICE_URL", "http://ticket-service:5000")

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
EVENT_EXCHANGE = os.environ.get("EVENT_EXCHANGE", "ticketing.events")
REFUND_RESPONSE_QUEUE = os.environ.get("REFUND_RESPONSE_QUEUE", "refund.response.q")


def req_json(method, url, payload=None, timeout=8):
    res = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text}
    return res.status_code, body


def rabbit_params():
    creds = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    return pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=creds,
        heartbeat=30,
    )


def publish_event(routing_key, payload):
    try:
        connection = pika.BlockingConnection(rabbit_params())
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
        print(f"[refund-composite] publish failed for {routing_key}: {e}")


def apply_refund_state(ticket_id, payment_refund_id=None, notify=True):
    code, ticket = req_json("GET", f"{USER_SERVICE_URL}/user/ticket/{ticket_id}")
    if code != 200:
        return False, {"error": "Ticket not found", "ticketId": ticket_id}, 404

    if ticket.get("status") != "active":
        return True, {
            "ticketId": ticket_id,
            "status": ticket.get("status"),
            "skipped": True,
            "reason": "Ticket already not active",
        }, 200

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

    # Best-effort sync with local ticket validity state.
    req_json("POST", f"{TICKET_SERVICE_URL}/tickets/{ticket_id}/invalidate")

    refund_id = payment_refund_id or f"RF-{uuid.uuid4()}"

    result = {
        "refundId": refund_id,
        "ticketId": ticket_id,
        "status": "refunded",
        "eventId": ticket.get("eventId"),
        "eventName": ticket.get("eventName"),
        "email": ticket.get("email"),
        "userId": ticket.get("userId"),
    }

    if notify:
        publish_event("refund.confirmed", result)

    return True, result, 200


def handle_refund_response_success(payload):
    ticket_id = payload.get("ticketId")
    if not ticket_id:
        return

    payment_refund_id = payload.get("paymentRefundId")
    ok, result, _ = apply_refund_state(ticket_id, payment_refund_id=payment_refund_id, notify=True)

    if ok:
        print(f"[refund-composite] async refund success for ticket {ticket_id}")
    else:
        print(f"[refund-composite] async refund apply failed for ticket {ticket_id}: {result}")


def handle_refund_response_failed(payload):
    ticket_id = payload.get("ticketId")
    if not ticket_id:
        return

    # Keep ticket active for manual follow-up, but mark purchase mapping as needing attention.
    req_json(
        "POST",
        f"{PURCHASE_SERVICE_URL}/purchase/ticket/{ticket_id}/status",
        {"status": "REFUND_PENDING_MANUAL"},
    )

    alert_payload = {
        "ticketId": ticket_id,
        "eventId": payload.get("eventId"),
        "eventName": payload.get("eventName"),
        "userId": payload.get("userId"),
        "email": payload.get("email"),
        "reason": payload.get("reason") or "Payment refund failed after retries",
        "status": "manual_action_required",
    }
    publish_event("concert.refund.failed", alert_payload)


def consume_responses_loop():
    while True:
        try:
            connection = pika.BlockingConnection(rabbit_params())
            channel = connection.channel()

            channel.exchange_declare(exchange=EVENT_EXCHANGE, exchange_type="topic", durable=True)
            channel.queue_declare(queue=REFUND_RESPONSE_QUEUE, durable=True)
            channel.queue_bind(
                exchange=EVENT_EXCHANGE,
                queue=REFUND_RESPONSE_QUEUE,
                routing_key="refund.response.success",
            )
            channel.queue_bind(
                exchange=EVENT_EXCHANGE,
                queue=REFUND_RESPONSE_QUEUE,
                routing_key="refund.response.failed",
            )

            def callback(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = {}

                if method.routing_key == "refund.response.success":
                    handle_refund_response_success(payload)
                elif method.routing_key == "refund.response.failed":
                    handle_refund_response_failed(payload)

                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_qos(prefetch_count=20)
            channel.basic_consume(queue=REFUND_RESPONSE_QUEUE, on_message_callback=callback)
            channel.start_consuming()
        except Exception as e:
            print(f"[refund-composite] response consumer reconnect after error: {e}")
            time.sleep(2)


def refund_single(ticket_id):
    return apply_refund_state(ticket_id, notify=True)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Refund Composite is running"}), 200


@app.route("/refunds/<ticketId>", methods=["POST"])
def refund_ticket(ticketId):
    ok, payload, code = refund_single(ticketId)
    return jsonify(payload), code


@app.route("/refunds/event/<eventId>", methods=["POST"])
def refund_event(eventId):
    data = request.get_json(silent=True) or {}
    simulate_failure_ticket_ids = set(data.get("simulateFailureTicketIds", []))

    code, data = req_json(
        "GET",
        f"{USER_SERVICE_URL}/user/tickets/by-event/{eventId}?status=active",
    )
    if code != 200:
        return jsonify({"error": "Unable to fetch tickets for event"}), 500

    tickets = data.get("tickets", [])
    batch_id = f"RFB-{uuid.uuid4()}"
    queued = []

    for ticket in tickets:
        ticket_id = ticket.get("ticketId")
        if not ticket_id:
            continue

        payload = {
            "refundBatchId": batch_id,
            "ticketId": ticket_id,
            "eventId": eventId,
            "eventName": ticket.get("eventName"),
            "userId": ticket.get("userId"),
            "email": ticket.get("email"),
            "simulateFailure": ticket_id in simulate_failure_ticket_ids,
        }

        publish_event("refund.request", payload)
        queued.append({"ticketId": ticket_id, "status": "queued"})

    return (
        jsonify(
            {
                "refundBatchId": batch_id,
                "eventId": eventId,
                "queued": len(queued),
                "results": queued,
            }
        ),
        202,
    )


if __name__ == "__main__":
    t = threading.Thread(target=consume_responses_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
