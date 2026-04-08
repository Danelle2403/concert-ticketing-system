from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as purchase_app

AUTH_USER = {"id": 2, "userId": 2, "email": "fan2@example.com", "role": "fan"}
INTERNAL_HEADERS = {"X-Internal-Service-Token": "concert-hub-internal-dev-token"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(purchase_app, "DB_PATH", str(tmp_path / "purchase.db"))
    purchase_app.init_db()
    conn = purchase_app.get_db()
    try:
        purchases, ticket_maps = purchase_app.build_demo_purchase_seed()
        purchase_app.reset_order_aligned_demo_data(conn, purchases=purchases, ticket_maps=ticket_maps)
    finally:
        conn.close()
    return purchase_app.app.test_client()


def test_checkout_uses_live_order_service_contract(client, monkeypatch):
    captured_order_payload = {}
    monkeypatch.setattr(purchase_app, "authenticate_request_user", lambda: dict(AUTH_USER))

    def fake_req_json(method, url, payload=None, timeout=8):
        if method == "GET" and url.endswith("/events/1"):
            return 404, {"error": "not found"}
        if method == "POST" and url.endswith("/inventory/hold"):
            return 201, {"holdId": "hold-123"}
        if method == "POST" and url.endswith("/inventory/confirm"):
            return 200, {"holdId": "hold-123", "status": "CONFIRMED"}
        if method == "POST" and url.endswith("/user/tickets/add"):
            return 201, {"ticketId": payload["ticketId"]}
        if method == "POST" and url.endswith("/order/"):
            captured_order_payload.update(payload)
            return 200, {"order_id": 55, **payload, "Status": "CONFIRMED"}
        raise AssertionError(f"Unexpected request: {method} {url} payload={payload} timeout={timeout}")

    monkeypatch.setattr(purchase_app, "req_json", fake_req_json)
    monkeypatch.setattr(purchase_app, "issue_ticket", lambda _event_id: "2")

    response = client.post(
        "/purchase/checkout",
        json={"userId": "fan-002", "eventId": "con-001", "quantity": 1},
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["orderIds"] == [55]
    assert payload["tickets"] == ["2"]
    assert captured_order_payload == {
        "FanId": 2,
        "TicketId": 2,
        "ConcertId": 1,
        "PaymentChargeId": payload["paymentChargeId"],
        "SeatCategory": "Standard",
        "AmountPaid": 80.0,
    }


def test_ticket_status_update_pushes_external_order_status(client, monkeypatch):
    updates = []

    def fake_req_json(method, url, payload=None, timeout=8):
        if method == "PUT" and url.endswith("/order/3/status/"):
            updates.append({"url": url, "payload": payload})
            return 200, {"order_id": 3, "Status": payload["Status"]}
        return 200, {}

    monkeypatch.setattr(purchase_app, "req_json", fake_req_json)

    response = client.post(
        "/purchase/ticket/tkt-002/status",
        json={"status": "REFUNDED"},
        headers=INTERNAL_HEADERS,
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "REFUNDED"
    assert updates == [
        {
            "url": f"{purchase_app.ORDER_SERVICE_URL}/order/3/status/",
            "payload": {"Status": "REFUNDED"},
        }
    ]

    purchase_db = purchase_app.get_db()
    try:
        cur = purchase_db.cursor()
        cur.execute("SELECT status FROM purchases WHERE purchaseId = ?", ("ORDER-DEMO-3",))
        row = cur.fetchone()
        assert row["status"] == "REFUNDED"
    finally:
        purchase_db.close()


def test_checkout_session_and_confirm_use_stripe_flow(client, monkeypatch):
    captured_order_payload = {}
    sent_notifications = []
    monkeypatch.setattr(purchase_app, "authenticate_request_user", lambda: dict(AUTH_USER))

    def fake_req_json(method, url, payload=None, timeout=8):
        if method == "GET" and url.endswith("/events/1"):
            return 404, {"error": "not found"}
        if method == "POST" and url.endswith("/inventory/hold"):
            return 201, {"holdId": f"hold-{len(sent_notifications) + 1}", "expiresAt": "2026-04-03T10:00:00Z"}
        if method == "POST" and url.endswith("/payments/intents"):
            return 201, {
                "data": {
                    "paymentIntentId": "pi_123",
                    "clientSecret": "pi_123_secret",
                    "status": "requires_payment_method",
                    "amount": 8000,
                    "currency": "sgd",
                }
            }
        if method == "GET" and url.endswith("/payments/intents/pi_123"):
            return 200, {
                "data": {
                    "paymentIntentId": "pi_123",
                    "status": "succeeded",
                    "latestChargeId": "ch_123",
                }
            }
        if method == "POST" and url.endswith("/inventory/confirm"):
            return 200, {"status": "CONFIRMED"}
        if method == "POST" and url.endswith("/user/tickets/add"):
            return 201, {"ticketId": payload["ticketId"]}
        if method == "POST" and url.endswith("/order/"):
            captured_order_payload.update(payload)
            return 200, {"order_id": 77, **payload, "Status": "CONFIRMED"}
        raise AssertionError(f"Unexpected request: {method} {url} payload={payload} timeout={timeout}")

    monkeypatch.setattr(purchase_app, "req_json", fake_req_json)
    monkeypatch.setattr(purchase_app, "issue_ticket", lambda _event_id: "2")
    monkeypatch.setattr(
        purchase_app,
        "send_purchase_confirmation_notification",
        lambda payload: sent_notifications.append(payload) or True,
    )

    session_response = client.post(
        "/purchase/checkout/session",
        json={
            "userId": "fan-002",
            "eventId": "con-001",
            "quantity": 1,
            "name": "Noah Fan",
            "email": "fan2@example.com",
            "seatCategory": "Standard",
        },
    )

    assert session_response.status_code == 201
    session_payload = session_response.get_json()
    assert session_payload["paymentIntentId"] == "pi_123"
    assert session_payload["clientSecret"] == "pi_123_secret"

    confirm_response = client.post(
        "/purchase/checkout/confirm",
        json={
            "checkoutSessionId": session_payload["checkoutSessionId"],
            "paymentIntentId": "pi_123",
        },
    )

    assert confirm_response.status_code == 201
    confirm_payload = confirm_response.get_json()
    assert confirm_payload["orderIds"] == [77]
    assert confirm_payload["tickets"] == ["2"]
    assert confirm_payload["paymentChargeId"] == "ch_123"
    assert captured_order_payload == {
        "FanId": 2,
        "TicketId": 2,
        "ConcertId": 1,
        "PaymentChargeId": "ch_123",
        "SeatCategory": "Standard",
        "AmountPaid": 80.0,
    }
    assert sent_notifications[0]["purchaseId"] == confirm_payload["purchaseId"]


def test_create_external_order_rejects_non_numeric_ticket_ids():
    with pytest.raises(ValueError, match="TicketId"):
        purchase_app.create_external_order(
            user_id=2,
            ticket_id="79c25060-979f-4267-99a0-c1b301427a09",
            event_id=1,
            event=purchase_app.ORDER_ALIGNED_DEMO_EVENTS["1"],
            seat_category="STANDARD",
            payment_charge_id="ch_123",
            amount_paid=80.0,
        )


def test_purchase_status_rejects_other_users(client, monkeypatch):
    monkeypatch.setattr(
        purchase_app,
        "authenticate_request_user",
        lambda: {"id": 99, "userId": 99, "email": "manager@example.com", "role": "manager"},
    )

    response = client.get("/purchase/ORDER-DEMO-2/status")

    assert response.status_code == 403


def test_ticket_lookup_allows_owner_via_auth(client, monkeypatch):
    monkeypatch.setattr(purchase_app, "authenticate_request_user", lambda: dict(AUTH_USER))

    response = client.get("/purchase/ticket/tkt-002")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ticketId"] == "2"
    assert payload["seatCategory"] == "STANDARD"


def test_ticket_lookup_rejects_non_owner_via_auth(client, monkeypatch):
    monkeypatch.setattr(
        purchase_app,
        "authenticate_request_user",
        lambda: {"id": 99, "userId": 99, "email": "manager@example.com", "role": "manager"},
    )

    response = client.get("/purchase/ticket/tkt-002")

    assert response.status_code == 403
