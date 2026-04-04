from pathlib import Path
import os
import sys

os.environ["START_CONSUMER"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as notification_app


def test_direct_dispatch_resolves_ticket_holders_and_succeeds(monkeypatch):
    flask_app = notification_app.create_app(
        {
            "TESTING": True,
            "USER_SERVICE_URL": "http://user-service.test",
            "SENDGRID_API_KEY": "",
            "SENDGRID_FROM_EMAIL": "",
        }
    )
    client = flask_app.test_client()

    def _request_json(method, url, payload=None, timeout=8):
        if method == "GET" and url.endswith("/user/tickets/by-event/evt-123"):
            return 200, {
                "tickets": [
                    {"ticketId": "T1", "userId": 1, "status": "active"},
                    {"ticketId": "T2", "userId": 1, "status": "active"},
                    {"ticketId": "T3", "userId": 2, "status": "refunded"},
                    {"ticketId": "T4", "userId": 3, "status": "active"},
                ]
            }
        if method == "GET" and url.endswith("/user/1"):
            return 200, {"id": 1, "email": "fan1@example.com", "name": "Fan One"}
        if method == "GET" and url.endswith("/user/3"):
            return 200, {"id": 3, "email": "fan3@example.com", "name": "Fan Three"}
        raise AssertionError(f"Unexpected request: {method} {url} payload={payload} timeout={timeout}")

    monkeypatch.setattr(notification_app, "request_json", _request_json)

    response = client.post(
        "/notifications/event-updated",
        json={
            "eventId": "evt-123",
            "eventAfter": {"title": "Updated Event", "startAt": "2026-08-15T12:00:00.000Z"},
            "changes": [{"field": "title", "before": "Old Event", "after": "Updated Event"}],
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "processed",
        "recipients": 2,
        "eventId": "evt-123",
    }


def test_build_email_content_includes_refund_guidance_for_updated_event():
    payload = {
        "type": "event.updated",
        "eventId": "evt-456",
        "eventAfter": {
            "title": "Updated Event",
            "startAt": "2026-08-15T12:00:00.000Z",
            "venue": {"name": "Indoor Stadium", "city": "Singapore", "country": "Singapore"},
        },
        "changes": [{"field": "title", "before": "Old Event", "after": "Updated Event"}],
        "refundInfo": {
            "provider": "stripe",
            "message": "Request a refund if the updated timing no longer works for you.",
        },
    }

    subject = notification_app.build_subject(payload)
    plain_text = notification_app.build_plain_text_body(payload, "Fan One")
    html = notification_app.build_html_body(payload, "Fan One")

    assert subject == "Event update: Updated Event"
    assert "Request a refund if the updated timing no longer works for you." in plain_text
    assert "Changed details:" in plain_text
    assert "Refund info:" in html


def test_build_subject_uses_refund_event_title():
    payload = {
        "type": "refund.success",
        "event": {
            "eventId": "1",
            "title": "Pulse Arena Nights",
        },
        "ticketId": "457",
        "refundId": "re_123",
    }

    subject = notification_app.build_subject(payload)

    assert subject == "Refund confirmed: Pulse Arena Nights"


def test_refund_failure_cancelled_event_mentions_manager_follow_up():
    payload = {
        "type": "refund.failure",
        "source": "event_cancelled",
        "event": {
            "eventId": "2",
            "title": "Skyline VIP Session",
        },
        "ticketId": "3",
        "amountPaid": 200.0,
        "currency": "sgd",
        "supportEmail": "support@concerthub.local",
        "manager": {
            "name": "Maya Manager",
            "email": "manager@example.com",
        },
    }

    plain_text = notification_app.build_plain_text_body(payload, "Chloe Fan")
    html = notification_app.build_html_body(payload, "Chloe Fan")

    assert "automatic refund" in plain_text
    assert "Maya Manager <manager@example.com>" in plain_text
    assert "will follow up manually" in plain_text
    assert "manager@example.com" in html
    assert "automatic refund" in html


def test_direct_cancelled_dispatch_uses_cancelled_payload(monkeypatch):
    flask_app = notification_app.create_app(
        {
            "TESTING": True,
            "USER_SERVICE_URL": "http://user-service.test",
            "SENDGRID_API_KEY": "",
            "SENDGRID_FROM_EMAIL": "",
            "NOTIFICATION_ROUTING_KEYS": ["event.updated", "event.cancelled"],
        }
    )
    client = flask_app.test_client()

    def _request_json(method, url, payload=None, timeout=8):
        if method == "GET" and url.endswith("/user/tickets/by-event/evt-cancelled"):
            return 200, {
                "tickets": [
                    {"ticketId": "T1", "userId": 1, "status": "active"},
                ]
            }
        if method == "GET" and url.endswith("/user/1"):
            return 200, {"id": 1, "email": "fan1@example.com", "name": "Fan One"}
        raise AssertionError(f"Unexpected request: {method} {url} payload={payload} timeout={timeout}")

    monkeypatch.setattr(notification_app, "request_json", _request_json)

    payload = {
        "type": "event.cancelled",
        "eventId": "evt-cancelled",
        "eventBefore": {
            "title": "Cancelled Event",
            "startAt": "2026-09-01T12:00:00.000Z",
            "venue": {"name": "Indoor Stadium", "city": "Singapore", "country": "Singapore"},
        },
        "eventAfter": {
            "title": "Cancelled Event",
            "startAt": "2026-09-01T12:00:00.000Z",
            "venue": {"name": "Indoor Stadium", "city": "Singapore", "country": "Singapore"},
            "cancelledAt": "2026-08-15T09:00:00.000Z",
            "cancellationReason": "Artist illness",
        },
        "changes": [
            {"field": "status", "before": "PUBLISHED", "after": "CANCELLED"},
            {"field": "cancelledAt", "before": None, "after": "2026-08-15T09:00:00.000Z"},
        ],
        "refundInfo": {
            "provider": "stripe",
            "message": "A refund to your original payment method via Stripe is planned.",
        },
    }

    response = client.post("/notifications/event-cancelled", json=payload)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "processed",
        "recipients": 1,
        "eventId": "evt-cancelled",
    }

    plain_text = notification_app.build_plain_text_body(payload, "Fan One")
    assert 'The event "Cancelled Event" has been cancelled.' in plain_text
    assert "Reason: Artist illness" in plain_text
    assert "A refund to your original payment method via Stripe is planned." in plain_text
