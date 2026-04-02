from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as purchase_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(purchase_app, "DB_PATH", str(tmp_path / "purchase.db"))
    purchase_app.init_db()
    return purchase_app.app.test_client()


def test_checkout_uses_live_order_service_contract(client, monkeypatch):
    captured_order_payload = {}

    def fake_req_json(method, url, payload=None, timeout=8):
        if method == "GET" and url.endswith("/user/2"):
            return 200, {"id": 2, "userId": 2}
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
        "FanId": "fan-002",
        "TicketId": "tkt-002",
        "ConcertId": "con-001",
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

    response = client.post("/purchase/ticket/tkt-002/status", json={"status": "REFUNDED"})

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
