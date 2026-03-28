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
