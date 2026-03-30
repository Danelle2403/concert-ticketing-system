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
