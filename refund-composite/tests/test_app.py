from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as refund_app


@pytest.fixture
def client():
    return refund_app.app.test_client()


def test_refund_single_normalizes_prefixed_ticket_and_updates_downstream_services(client, monkeypatch):
    state = {
        "tickets": {
            "2": {
                "ticketId": "2",
                "eventId": "1",
                "userId": 2,
                "status": "active",
            }
        },
        "mappings": {
            "2": {
                "ticketId": "2",
                "holdId": "33333333-3333-3333-3333-333333333333",
                "orderId": 3,
            }
        },
        "released": [],
        "purchase_status_updates": [],
    }

    def _req_json(method, url, payload=None, timeout=8):
        if method == "GET" and url.endswith("/user/ticket/2"):
            return 200, dict(state["tickets"]["2"])
        if method == "GET" and url.endswith("/purchase/ticket/2"):
            return 200, dict(state["mappings"]["2"])
        if method == "POST" and url.endswith("/inventory/release"):
            state["released"].append(payload)
            return 200, {"holdId": payload["holdId"], "status": "RELEASED"}
        if method == "POST" and url.endswith("/user/ticket/2/status"):
            state["tickets"]["2"]["status"] = payload["status"]
            return 200, dict(state["tickets"]["2"])
        if method == "POST" and url.endswith("/purchase/ticket/2/status"):
            state["purchase_status_updates"].append(payload)
            return 200, {"ticketId": "2", "status": payload["status"]}
        raise AssertionError(f"Unexpected request: {method} {url} payload={payload} timeout={timeout}")

    monkeypatch.setattr(refund_app, "req_json", _req_json)

    response = client.post("/refunds/tkt-002")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ticketId"] == "2"
    assert payload["status"] == "refunded"
    assert state["tickets"]["2"]["status"] == "refunded"
    assert state["released"] == [
        {
            "holdId": "33333333-3333-3333-3333-333333333333",
            "allowConfirmedRelease": True,
            "reason": "REFUND",
        }
    ]
    assert state["purchase_status_updates"] == [{"status": "REFUNDED"}]


def test_refund_event_batches_active_tickets_for_normalized_event(client, monkeypatch):
    state = {
        "tickets": {
            "2": {"ticketId": "2", "eventId": "1", "userId": 2, "status": "active"},
            "5": {"ticketId": "5", "eventId": "1", "userId": 1, "status": "active"},
        },
        "mappings": {
            "2": {"ticketId": "2", "holdId": "33333333-3333-3333-3333-333333333333"},
            "5": {"ticketId": "5", "holdId": "55555555-5555-5555-5555-555555555555"},
        },
        "released": [],
        "purchase_updates": [],
    }

    def _req_json(method, url, payload=None, timeout=8):
        if method == "GET" and url.endswith("/user/tickets/by-event/1?status=active"):
            return 200, {"tickets": [dict(state["tickets"]["2"]), dict(state["tickets"]["5"])]}
        if method == "GET" and url.endswith("/user/ticket/2"):
            return 200, dict(state["tickets"]["2"])
        if method == "GET" and url.endswith("/user/ticket/5"):
            return 200, dict(state["tickets"]["5"])
        if method == "GET" and url.endswith("/purchase/ticket/2"):
            return 200, dict(state["mappings"]["2"])
        if method == "GET" and url.endswith("/purchase/ticket/5"):
            return 200, dict(state["mappings"]["5"])
        if method == "POST" and url.endswith("/inventory/release"):
            state["released"].append(payload["holdId"])
            return 200, {"status": "RELEASED"}
        if method == "POST" and "/user/ticket/" in url and url.endswith("/status"):
            ticket_id = url.rsplit("/", 2)[1]
            state["tickets"][ticket_id]["status"] = payload["status"]
            return 200, dict(state["tickets"][ticket_id])
        if method == "POST" and "/purchase/ticket/" in url and url.endswith("/status"):
            ticket_id = url.rsplit("/", 2)[1]
            state["purchase_updates"].append((ticket_id, payload["status"]))
            return 200, {"ticketId": ticket_id, "status": payload["status"]}
        raise AssertionError(f"Unexpected request: {method} {url} payload={payload} timeout={timeout}")

    monkeypatch.setattr(refund_app, "req_json", _req_json)

    response = client.post("/refunds/event/con-001")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["eventId"] == "1"
    assert payload["processed"] == 2
    assert payload["successful"] == 2
    assert payload["failed"] == 0
    assert {result["ticketId"] for result in payload["results"]} == {"2", "5"}
    assert state["released"] == [
        "33333333-3333-3333-3333-333333333333",
        "55555555-5555-5555-5555-555555555555",
    ]
    assert state["purchase_updates"] == [("2", "REFUNDED"), ("5", "REFUNDED")]
