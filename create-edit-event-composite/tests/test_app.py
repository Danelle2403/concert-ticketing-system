from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as composite_app


@pytest.fixture
def client():
    flask_app = composite_app.create_app(
        {
            "TESTING": True,
            "USER_SERVICE_URL": "http://user-service.test",
            "EVENT_SERVICE_URL": "http://event-service.test",
            "SEAT_INVENTORY_URL": "http://seat-inventory.test",
        }
    )
    return flask_app.test_client(), flask_app


def test_create_manager_event_success(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 2, "name": "Maya Manager", "role": "manager"},
    )

    captured_inventory_bootstrap = {}

    def _create_event_record(_event_service_url, event_payload, _timeout):
        assert event_payload["changedBy"] == "manager-2"
        assert event_payload["managerId"] == 2
        return {
            "id": "evt-123",
            "managerId": 2,
            "title": event_payload["title"],
            "status": "PUBLISHED",
        }

    def _create_seat_inventory_record(
        _seat_inventory_url, seat_inventory_event_id, seat_categories, _timeout
    ):
        captured_inventory_bootstrap["event_id"] = seat_inventory_event_id
        captured_inventory_bootstrap["seat_categories"] = seat_categories
        return {
            "seatInventoryEventId": seat_inventory_event_id,
            "inventory": [
                {
                    "eventId": seat_inventory_event_id,
                    "seatCategory": row["seatCategory"],
                    "totalSeats": row["totalSeats"],
                    "availableSeats": row["availableSeats"],
                }
                for row in seat_categories
            ],
        }

    monkeypatch.setattr(
        composite_app.service_clients,
        "create_event_record",
        _create_event_record,
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "create_seat_inventory_record",
        _create_seat_inventory_record,
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_seat_inventory_inventory",
        lambda *_args, **kwargs: None if kwargs.get("allow_missing") else None,
    )

    response = test_client.post(
        "/manager/events",
        json={
            "managerId": 2,
            "title": "Manager Created Event",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "Indoor Stadium"},
            "pricingTiers": [
                {"code": "VIP", "name": "VIP", "price": 188, "currency": "SGD"},
                {"code": "CAT1", "name": "CAT1", "price": 128, "currency": "SGD"},
            ],
            "seatSections": [
                {"code": "A1", "name": "Section A1", "tierCode": "VIP", "capacity": 50},
                {"code": "B1", "name": "Section B1", "tierCode": "CAT1", "capacity": 120},
            ],
            "status": "PUBLISHED",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["data"]["event"]["id"] == "evt-123"
    assert payload["data"]["event"]["managerId"] == 2
    assert payload["data"]["integration"]["seatInventoryEventId"] == "evt-123"
    assert payload["data"]["integration"]["inventoryBootstrap"]["totalSeatsByCategory"] == {
        "CAT1": 120,
        "VIP": 50,
    }
    assert captured_inventory_bootstrap == {
        "event_id": "evt-123",
        "seat_categories": [
            {"seatCategory": "CAT1", "totalSeats": 120, "availableSeats": 120},
            {"seatCategory": "VIP", "totalSeats": 50, "availableSeats": 50},
        ],
    }


def test_create_rejects_non_manager(client, monkeypatch):
    test_client, _app = client

    def _raise_non_manager(*_args, **_kwargs):
        raise composite_app.service_clients.ServiceError(
            403,
            "MANAGER_ACCESS_DENIED",
            "Only manager users can access this composite service",
        )

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        _raise_non_manager,
    )

    response = test_client.post(
        "/manager/events",
        json={
            "managerId": 1,
            "title": "Not Allowed",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "Indoor Stadium"},
            "pricingTiers": [],
            "seatSections": [],
            "status": "DRAFT",
        },
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "MANAGER_ACCESS_DENIED"


def test_create_rejects_publish_without_bootstrap_data(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 2, "role": "manager"},
    )

    response = test_client.post(
        "/manager/events",
        json={
            "managerId": 2,
            "title": "Needs Inventory",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "Indoor Stadium"},
            "pricingTiers": [{"code": "VIP", "name": "VIP", "price": 188, "currency": "SGD"}],
            "seatSections": [],
            "status": "PUBLISHED",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INVENTORY_BOOTSTRAP_REQUIRED"


def test_edit_rejects_non_owner_manager(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 3, "role": "manager"},
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-123",
            "managerId": 2,
            "status": "DRAFT",
        },
    )

    response = test_client.put(
        "/manager/events/evt-123",
        json={
            "managerId": 3,
            "title": "Attempted Update",
        },
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "MANAGER_NOT_OWNER"


def test_list_manager_events_returns_event_summaries(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 2, "role": "manager"},
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "list_events_for_manager",
        lambda *_args, **_kwargs: [
            {
                "id": "evt-123",
                "managerId": 2,
                "title": "Owned Event",
                "status": "PUBLISHED",
            }
        ],
    )

    response = test_client.get("/manager/events?managerId=2")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["events"][0]["eventId"] == "evt-123"
    assert payload["data"]["events"][0]["seatInventoryEventId"] == "evt-123"
    assert payload["data"]["events"][0]["eventSummary"]["status"] == "PUBLISHED"


def test_edit_partial_update_does_not_send_empty_configuration(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 2, "role": "manager"},
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-123",
            "managerId": 2,
            "status": "PUBLISHED",
            "pricingTiers": [],
            "seatSections": [],
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_seat_inventory_inventory",
        lambda *_args, **_kwargs: {
            "seatInventoryEventId": "evt-123",
            "inventory": [
                {
                    "eventId": "evt-123",
                    "seatCategory": "VIP",
                    "totalSeats": 50,
                    "availableSeats": 50,
                }
            ],
        },
    )

    captured_payload = {}

    def _update_event_record(_event_service_url, _event_id, event_payload, _timeout):
        captured_payload.update(event_payload)
        return {"id": "evt-123", "managerId": 2, "title": "Owned Event", "status": "PUBLISHED"}

    monkeypatch.setattr(
        composite_app.service_clients,
        "update_event_record",
        _update_event_record,
    )

    response = test_client.put(
        "/manager/events/evt-123",
        json={
            "managerId": 2,
            "description": "Partial update only",
        },
    )

    assert response.status_code == 200
    assert captured_payload == {
        "description": "Partial update only",
        "changedBy": "manager-2",
    }


def test_edit_rejects_inventory_shape_change_without_update_api(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 2, "role": "manager"},
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-123",
            "managerId": 2,
            "title": "Owned Event",
            "status": "PUBLISHED",
            "pricingTiers": [
                {"code": "VIP", "name": "VIP", "price": 188, "currency": "SGD"},
                {"code": "CAT1", "name": "CAT1", "price": 128, "currency": "SGD"},
            ],
            "seatSections": [
                {"code": "A1", "name": "Section A1", "tierCode": "VIP", "capacity": 50},
                {"code": "B1", "name": "Section B1", "tierCode": "CAT1", "capacity": 120},
            ],
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_seat_inventory_inventory",
        lambda *_args, **_kwargs: {
            "seatInventoryEventId": "evt-123",
            "inventory": [
                {
                    "eventId": "evt-123",
                    "seatCategory": "VIP",
                    "totalSeats": 50,
                    "availableSeats": 50,
                },
                {
                    "eventId": "evt-123",
                    "seatCategory": "CAT1",
                    "totalSeats": 120,
                    "availableSeats": 120,
                },
            ],
        },
    )

    def _unexpected_update(*_args, **_kwargs):
        raise AssertionError("Event update should not be attempted when inventory totals would drift")

    monkeypatch.setattr(
        composite_app.service_clients,
        "update_event_record",
        _unexpected_update,
    )

    response = test_client.put(
        "/manager/events/evt-123",
        json={
            "managerId": 2,
            "seatSections": [
                {"code": "A1", "name": "Section A1", "tierCode": "VIP", "capacity": 50},
                {"code": "B1", "name": "Section B1", "tierCode": "CAT1", "capacity": 130},
            ],
        },
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "SEAT_INVENTORY_UPDATE_UNSUPPORTED"


def test_edit_bootstraps_inventory_when_missing(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 2, "role": "manager"},
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-123",
            "managerId": 2,
            "title": "Owned Event",
            "status": "DRAFT",
            "pricingTiers": [
                {"code": "VIP", "name": "VIP", "price": 188, "currency": "SGD"},
                {"code": "CAT1", "name": "CAT1", "price": 128, "currency": "SGD"},
            ],
            "seatSections": [
                {"code": "A1", "name": "Section A1", "tierCode": "VIP", "capacity": 50},
                {"code": "B1", "name": "Section B1", "tierCode": "CAT1", "capacity": 120},
            ],
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_seat_inventory_inventory",
        lambda *_args, **_kwargs: None,
    )

    captured_inventory_bootstrap = {}

    def _update_event_record(_event_service_url, _event_id, event_payload, _timeout):
        assert event_payload["status"] == "PUBLISHED"
        return {"id": "evt-123", "managerId": 2, "title": "Owned Event", "status": "PUBLISHED"}

    def _create_seat_inventory_record(
        _seat_inventory_url, seat_inventory_event_id, seat_categories, _timeout
    ):
        captured_inventory_bootstrap["event_id"] = seat_inventory_event_id
        captured_inventory_bootstrap["seat_categories"] = seat_categories
        return {
            "seatInventoryEventId": seat_inventory_event_id,
            "inventory": [
                {
                    "eventId": seat_inventory_event_id,
                    "seatCategory": row["seatCategory"],
                    "totalSeats": row["totalSeats"],
                    "availableSeats": row["availableSeats"],
                }
                for row in seat_categories
            ],
        }

    monkeypatch.setattr(
        composite_app.service_clients,
        "update_event_record",
        _update_event_record,
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "create_seat_inventory_record",
        _create_seat_inventory_record,
    )

    response = test_client.put(
        "/manager/events/evt-123",
        json={
            "managerId": 2,
            "status": "PUBLISHED",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["integration"]["seatInventoryEventId"] == "evt-123"
    assert captured_inventory_bootstrap == {
        "event_id": "evt-123",
        "seat_categories": [
            {"seatCategory": "CAT1", "totalSeats": 120, "availableSeats": 120},
            {"seatCategory": "VIP", "totalSeats": 50, "availableSeats": 50},
        ],
    }


def test_edit_queues_notification_when_event_details_change(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 2, "name": "Maya Manager", "role": "manager"},
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-123",
            "managerId": 2,
            "title": "Old Title",
            "status": "PUBLISHED",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "Old Venue"},
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_seat_inventory_inventory",
        lambda *_args, **_kwargs: {
            "seatInventoryEventId": "evt-123",
            "inventory": [],
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "update_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-123",
            "managerId": 2,
            "title": "New Title",
            "status": "PUBLISHED",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "New Venue"},
            "changedBy": "manager-2",
        },
    )

    captured_message = {}

    def _publish_message(_rabbitmq_url, _exchange, _routing_key, payload):
        captured_message.update(payload)

    monkeypatch.setattr(composite_app.event_bus, "publish_message", _publish_message)

    response = test_client.put(
        "/manager/events/evt-123",
        json={
            "managerId": 2,
            "title": "New Title",
            "venue": {"name": "New Venue"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["integration"]["notificationQueued"] is True
    assert captured_message["type"] == "event.updated"
    assert captured_message["eventId"] == "evt-123"
    assert [change["field"] for change in captured_message["changes"]] == ["title", "venue"]


def test_edit_warns_when_notification_publish_fails(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {"id": 2, "name": "Maya Manager", "role": "manager"},
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-123",
            "managerId": 2,
            "title": "Old Title",
            "status": "PUBLISHED",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "Old Venue"},
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_seat_inventory_inventory",
        lambda *_args, **_kwargs: {
            "seatInventoryEventId": "evt-123",
            "inventory": [],
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "update_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-123",
            "managerId": 2,
            "title": "New Title",
            "status": "PUBLISHED",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "New Venue"},
            "changedBy": "manager-2",
        },
    )

    def _raise_publish_error(*_args, **_kwargs):
        raise RuntimeError("rabbit unavailable")

    monkeypatch.setattr(composite_app.event_bus, "publish_message", _raise_publish_error)

    response = test_client.put(
        "/manager/events/evt-123",
        json={
            "managerId": 2,
            "title": "New Title",
            "venue": {"name": "New Venue"},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["integration"]["notificationQueued"] is False
    assert "fan notifications were not queued" in payload["warnings"][0]


def test_cancel_manager_event_queues_cancelled_notification(client, monkeypatch):
    test_client, _app = client

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {
            "id": 2,
            "name": "Maya Manager",
            "email": "manager@example.com",
            "role": "manager",
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-cancelled",
            "managerId": 2,
            "title": "Cancelled Event",
            "status": "PUBLISHED",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "Indoor Stadium"},
            "cancelledAt": None,
            "cancellationReason": None,
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "cancel_event_record",
        lambda *_args, **_kwargs: {
            "id": "evt-cancelled",
            "managerId": 2,
            "title": "Cancelled Event",
            "status": "CANCELLED",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "Indoor Stadium"},
            "changedBy": "manager-2",
            "cancelledAt": "2026-08-01T09:00:00.000Z",
            "cancellationReason": "Artist illness",
        },
    )

    captured_routing_key = {}
    captured_message = {}

    def _publish_message(_rabbitmq_url, _exchange, routing_key, payload):
        captured_routing_key["value"] = routing_key
        captured_message.update(payload)

    monkeypatch.setattr(composite_app.event_bus, "publish_message", _publish_message)
    monkeypatch.setattr(
        composite_app.service_clients,
        "request_json",
        lambda method, url, payload=None, timeout=8: (
            200,
            {
                "eventId": "evt-cancelled",
                "processed": 1,
                "successful": 1,
                "failed": 0,
                "results": [{"ticketId": "2", "refundId": "re_123"}],
            },
        ),
    )

    response = test_client.post(
        "/manager/events/evt-cancelled/cancel",
        json={
            "managerId": 2,
            "reason": "Artist illness",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["integration"]["notificationQueued"] is True
    assert payload["data"]["integration"]["refundFlow"]["provider"] == "stripe"
    assert payload["data"]["integration"]["refundFlow"]["service"] == "refund-composite"
    assert payload["data"]["integration"]["refundFlow"]["requestRequired"] is False
    assert payload["data"]["integration"]["refundFlow"]["status"] == "completed"
    assert payload["data"]["integration"]["refundFlow"]["triggered"] is True
    assert payload["data"]["integration"]["refundFlow"]["eventRefundEndpoint"].endswith(
        "/refunds/event/evt-cancelled"
    )
    assert payload["data"]["integration"]["refundFlow"]["summary"]["successful"] == 1
    assert captured_routing_key["value"] == "event.cancelled"
    assert captured_message["type"] == "event.cancelled"
    assert captured_message["eventId"] == "evt-cancelled"
    assert captured_message["refundInfo"]["provider"] == "stripe"
    assert captured_message["refundInfo"]["requestRequired"] is False
    assert captured_message["refundInfo"]["status"] == "processing"
    assert captured_message["refundInfo"]["autoRefund"] is True


def test_edit_and_cancel_manager_event_lifecycle(client, monkeypatch):
    test_client, _app = client

    state = {
        "event": {
            "id": "evt-lifecycle",
            "managerId": 2,
            "title": "Original Event",
            "status": "PUBLISHED",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {"name": "Indoor Stadium"},
            "pricingTiers": [
                {"code": "VIP", "name": "VIP", "price": 188, "currency": "SGD"},
                {"code": "CAT1", "name": "CAT1", "price": 128, "currency": "SGD"},
            ],
            "seatSections": [
                {"code": "A1", "name": "Section A1", "tierCode": "VIP", "capacity": 50},
                {"code": "B1", "name": "Section B1", "tierCode": "CAT1", "capacity": 120},
            ],
        }
    }
    published_messages = []

    monkeypatch.setattr(
        composite_app.service_clients,
        "validate_manager_access",
        lambda *_args, **_kwargs: {
            "id": 2,
            "name": "Maya Manager",
            "email": "manager@example.com",
            "role": "manager",
        },
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_event_record",
        lambda *_args, **_kwargs: dict(state["event"]),
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "get_seat_inventory_inventory",
        lambda *_args, **_kwargs: {
            "seatInventoryEventId": "evt-lifecycle",
            "inventory": [
                {
                    "eventId": "evt-lifecycle",
                    "seatCategory": "VIP",
                    "totalSeats": 50,
                    "availableSeats": 50,
                },
                {
                    "eventId": "evt-lifecycle",
                    "seatCategory": "CAT1",
                    "totalSeats": 120,
                    "availableSeats": 120,
                },
            ],
        },
    )

    def _update_event_record(_event_service_url, _event_id, event_payload, _timeout):
        state["event"] = {**state["event"], **event_payload}
        return dict(state["event"])

    def _cancel_event_record(_event_service_url, _event_id, cancel_payload, _timeout):
        state["event"] = {
            **state["event"],
            "status": "CANCELLED",
            "cancellationReason": cancel_payload.get("reason"),
            "cancelledAt": "2026-08-01T09:00:00.000Z",
        }
        return dict(state["event"])

    monkeypatch.setattr(composite_app.service_clients, "update_event_record", _update_event_record)
    monkeypatch.setattr(composite_app.service_clients, "cancel_event_record", _cancel_event_record)
    monkeypatch.setattr(
        composite_app.event_bus,
        "publish_message",
        lambda _rabbitmq_url, _exchange, routing_key, payload: published_messages.append(
            {"routing_key": routing_key, "payload": payload}
        ),
    )
    monkeypatch.setattr(
        composite_app.service_clients,
        "request_json",
        lambda method, url, payload=None, timeout=8: (
            200,
            {
                "eventId": "evt-lifecycle",
                "processed": 2,
                "successful": 2,
                "failed": 0,
                "results": [
                    {"ticketId": "2", "refundId": "re_123"},
                    {"ticketId": "5", "refundId": "re_456"},
                ],
            },
        ),
    )

    edit_response = test_client.put(
        "/manager/events/evt-lifecycle",
        json={"managerId": 2, "title": "Updated Event"},
    )
    cancel_response = test_client.post(
        "/manager/events/evt-lifecycle/cancel",
        json={"managerId": 2, "reason": "Artist illness"},
    )

    assert edit_response.status_code == 200
    assert cancel_response.status_code == 200
    assert published_messages[0]["routing_key"] == "event.updated"
    assert published_messages[1]["routing_key"] == "event.cancelled"
    assert cancel_response.get_json()["data"]["integration"]["refundFlow"]["eventRefundEndpoint"].endswith(
        "/refunds/event/evt-lifecycle"
    )
    assert cancel_response.get_json()["data"]["integration"]["refundFlow"]["status"] == "completed"
