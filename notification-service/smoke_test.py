import argparse
import json
import os
import sys
import time
import uuid

import pika
import requests


INTERNAL_SERVICE_TOKEN = os.environ.get(
    "INTERNAL_SERVICE_TOKEN", "concert-hub-internal-dev-token"
)


def request_json(method, url, payload=None, timeout=8):
    headers = None
    if "/user/" in url:
        headers = {"X-Internal-Service-Token": INTERNAL_SERVICE_TOKEN}
    response = requests.request(method, url, json=payload, timeout=timeout, headers=headers)
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    return response.status_code, body


def ensure_user(user_service_url, email):
    create_payload = {
        "name": "Notification Smoke Fan",
        "email": email,
        "role": "fan",
    }
    status_code, body = request_json("POST", f"{user_service_url}/user/new", create_payload)
    if status_code in (200, 201):
        return body["userId"]

    if status_code == 409:
        status_code, users_payload = request_json("GET", f"{user_service_url}/users")
        if status_code != 200:
            raise RuntimeError("Unable to look up existing user after email conflict")

        for user in users_payload.get("users", []):
            if user.get("email") == email:
                return user["userId"]

    raise RuntimeError(f"Unable to create or locate user: {status_code} {body}")


def upsert_ticket(user_service_url, user_id, event_id, ticket_id):
    status_code, body = request_json(
        "POST",
        f"{user_service_url}/user/tickets/add",
        {
            "userId": user_id,
            "ticketId": ticket_id,
            "eventId": event_id,
            "eventName": "Notification Smoke Test Event",
            "venue": "Smoke Test Venue, Singapore",
            "date": "2026-10-01",
            "status": "active",
        },
    )
    if status_code not in (200, 201):
        raise RuntimeError(f"Unable to upsert ticket: {status_code} {body}")


def build_payload(event_type, event_id):
    if event_type == "event.cancelled":
        return {
            "type": "event.cancelled",
            "eventId": event_id,
            "managerId": 2,
            "changedBy": "manager-2",
            "manager": {"id": 2, "name": "Maya Manager"},
            "changes": [
                {"field": "status", "before": "PUBLISHED", "after": "CANCELLED"},
                {"field": "cancelledAt", "before": None, "after": "2026-09-15T09:30:00.000Z"},
            ],
            "eventBefore": {
                "title": "Notification Smoke Test Event",
                "startAt": "2026-10-01T12:00:00.000Z",
                "venue": {"name": "Smoke Test Venue", "city": "Singapore", "country": "Singapore"},
            },
            "eventAfter": {
                "title": "Notification Smoke Test Event",
                "startAt": "2026-10-01T12:00:00.000Z",
                "venue": {"name": "Smoke Test Venue", "city": "Singapore", "country": "Singapore"},
                "cancelledAt": "2026-09-15T09:30:00.000Z",
                "cancellationReason": "Smoke test cancellation verification",
            },
            "refundInfo": {
                "provider": "stripe",
                "requestRequired": False,
                "message": (
                    "Refunds for cancelled events are intended to go back to the original "
                    "payment method through Stripe once the refund flow is enabled."
                ),
            },
        }

    return {
        "type": "event.updated",
        "eventId": event_id,
        "managerId": 2,
        "changedBy": "manager-2",
        "manager": {"id": 2, "name": "Maya Manager"},
        "changes": [
            {
                "field": "title",
                "before": "Notification Smoke Test Event",
                "after": "Notification Smoke Test Event (Updated)",
            },
            {
                "field": "venue",
                "before": {"name": "Smoke Test Venue", "city": "Singapore", "country": "Singapore"},
                "after": {"name": "Updated Smoke Test Venue", "city": "Singapore", "country": "Singapore"},
            },
        ],
        "eventBefore": {
            "title": "Notification Smoke Test Event",
            "startAt": "2026-10-01T12:00:00.000Z",
            "venue": {"name": "Smoke Test Venue", "city": "Singapore", "country": "Singapore"},
        },
        "eventAfter": {
            "title": "Notification Smoke Test Event (Updated)",
            "startAt": "2026-10-01T12:00:00.000Z",
            "venue": {"name": "Updated Smoke Test Venue", "city": "Singapore", "country": "Singapore"},
        },
    }


def publish_event_update(rabbitmq_url, exchange, routing_key, payload):
    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    try:
        channel = connection.channel()
        channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=json.dumps(payload),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )
    finally:
        connection.close()


def wait_for_delivery(notification_health_url, event_id, timeout_seconds=30):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status_code, body = request_json("GET", notification_health_url)
        if status_code == 200:
            consumer = body.get("consumer") or {}
            if consumer.get("lastEventId") == event_id:
                if consumer.get("lastError"):
                    raise RuntimeError(
                        f"Notification consumer processed the event but reported an error: {consumer['lastError']}"
                    )
                return body
        time.sleep(1)

    raise RuntimeError("Timed out waiting for notification-service to process the message")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["direct", "rabbitmq"], default="direct")
    parser.add_argument("--event-type", choices=["event.updated", "event.cancelled"], default="event.updated")
    parser.add_argument("--email", default="sheenhern@outlook.com")
    parser.add_argument("--user-service-url", default="http://localhost:5001")
    parser.add_argument("--notification-url", default="http://localhost:5013/notifications/events")
    parser.add_argument("--notification-health-url", default="http://localhost:5013/health")
    parser.add_argument("--rabbitmq-url", default="amqp://guest:guest@localhost:5672/%2F")
    parser.add_argument("--exchange", default="concert.events")
    parser.add_argument("--routing-key", default="event.updated")
    args = parser.parse_args()

    event_id = f"SMOKE-EVT-{uuid.uuid4()}"
    ticket_id = f"SMOKE-TKT-{uuid.uuid4()}"
    payload = build_payload(args.event_type, event_id)
    user_id = ensure_user(args.user_service_url, args.email)
    upsert_ticket(args.user_service_url, user_id, event_id, ticket_id)

    if args.mode == "rabbitmq":
        routing_key = args.routing_key
        if routing_key == "event.updated" and args.event_type == "event.cancelled":
            routing_key = "event.cancelled"
        publish_event_update(args.rabbitmq_url, args.exchange, routing_key, payload)
        health = wait_for_delivery(args.notification_health_url, event_id)
        consumer = health["consumer"]
        result = {
            "status": "ok",
            "mode": args.mode,
            "eventType": args.event_type,
            "eventId": event_id,
            "userId": user_id,
            "email": args.email,
            "deliveryMode": consumer.get("lastDeliveryMode"),
            "recipientCount": consumer.get("lastRecipientCount"),
            "lastEventId": consumer.get("lastEventId"),
        }
    else:
        status_code, body = request_json("POST", args.notification_url, payload)
        if status_code != 200:
            raise RuntimeError(f"Direct notification dispatch failed: {status_code} {body}")
        result = {
            "status": "ok",
            "mode": args.mode,
            "eventType": args.event_type,
            "eventId": event_id,
            "userId": user_id,
            "email": args.email,
            "response": body,
        }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
