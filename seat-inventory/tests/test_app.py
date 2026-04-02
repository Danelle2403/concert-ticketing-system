from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as seat_app


def timestamp_string():
    return "2026-04-03 00:00:00"


class FakeSeatCursor:
    def __init__(self, db):
        self.db = db
        self.results = []
        self.rowcount = 0

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        params = params or ()
        self.results = []
        self.rowcount = 0
        inventory = self.db.inventory
        holds = self.db.holds

        if sql.startswith("INSERT INTO seat_inventory") and "ON DUPLICATE KEY UPDATE" in sql:
            event_id, seat_category, total_seats, available_seats = params
            inventory[(str(event_id), str(seat_category))] = {
                "eventId": str(event_id),
                "seatCategory": str(seat_category),
                "totalSeats": int(total_seats),
                "availableSeats": int(available_seats),
                "updatedAt": timestamp_string(),
            }
            self.rowcount = 1
            return

        if sql.startswith("INSERT INTO seat_holds") and "ON DUPLICATE KEY UPDATE" in sql:
            (
                hold_id,
                event_id,
                seat_category,
                quantity,
                status,
                expires_at,
                confirmed_at,
                released_at,
                release_reason,
                created_at,
                updated_at,
            ) = params
            holds[str(hold_id)] = {
                "holdId": str(hold_id),
                "eventId": str(event_id),
                "seatCategory": str(seat_category),
                "quantity": int(quantity),
                "status": status,
                "expiresAt": expires_at,
                "confirmedAt": confirmed_at,
                "releasedAt": released_at,
                "releaseReason": release_reason,
                "createdAt": created_at,
                "updatedAt": updated_at,
            }
            self.rowcount = 1
            return

        if sql.startswith("SELECT eventId, seatCategory, totalSeats, availableSeats, updatedAt FROM seat_inventory ORDER BY eventId, seatCategory"):
            self.results = [
                deepcopy(inventory[key])
                for key in sorted(inventory.keys())
            ]
            return

        if sql.startswith("SELECT eventId, seatCategory, totalSeats, availableSeats, updatedAt FROM seat_inventory WHERE eventId = %s ORDER BY seatCategory"):
            event_id = str(params[0])
            self.results = [
                deepcopy(row)
                for key, row in sorted(inventory.items())
                if key[0] == event_id
            ]
            return

        if sql.startswith("SELECT eventId, seatCategory, totalSeats, availableSeats FROM seat_inventory WHERE eventId = %s AND seatCategory = %s FOR UPDATE"):
            event_id, seat_category = str(params[0]), str(params[1])
            row = inventory.get((event_id, seat_category))
            self.results = [deepcopy(row)] if row else []
            return

        if sql.startswith("SELECT eventId, seatCategory, totalSeats, availableSeats, updatedAt FROM seat_inventory WHERE eventId = %s AND seatCategory = %s FOR UPDATE"):
            event_id, seat_category = str(params[0]), str(params[1])
            row = inventory.get((event_id, seat_category))
            self.results = [deepcopy(row)] if row else []
            return

        if sql.startswith("SELECT COUNT(*) AS rowCount FROM seat_inventory WHERE eventId = %s FOR UPDATE"):
            event_id = str(params[0])
            count = sum(1 for key in inventory if key[0] == event_id)
            self.results = [{"rowCount": count}]
            return

        if sql.startswith("INSERT INTO seat_inventory") and "ON DUPLICATE KEY UPDATE" not in sql:
            event_id, seat_category, total_seats, available_seats = params
            inventory[(str(event_id), str(seat_category))] = {
                "eventId": str(event_id),
                "seatCategory": str(seat_category),
                "totalSeats": int(total_seats),
                "availableSeats": int(available_seats),
                "updatedAt": timestamp_string(),
            }
            self.rowcount = 1
            return

        if sql.startswith("UPDATE seat_inventory SET availableSeats = availableSeats - %s"):
            quantity, event_id, seat_category = int(params[0]), str(params[1]), str(params[2])
            inventory[(event_id, seat_category)]["availableSeats"] -= quantity
            inventory[(event_id, seat_category)]["updatedAt"] = timestamp_string()
            self.rowcount = 1
            return

        if sql.startswith("UPDATE seat_inventory SET availableSeats = availableSeats + %s"):
            quantity, event_id, seat_category = int(params[0]), str(params[1]), str(params[2])
            inventory[(event_id, seat_category)]["availableSeats"] += quantity
            inventory[(event_id, seat_category)]["updatedAt"] = timestamp_string()
            self.rowcount = 1
            return

        if sql.startswith("INSERT INTO seat_holds") and "VALUES (%s, %s, %s, %s, 'HELD', %s" in sql:
            hold_id, event_id, seat_category, quantity, expires_at = params
            holds[str(hold_id)] = {
                "holdId": str(hold_id),
                "eventId": str(event_id),
                "seatCategory": str(seat_category),
                "quantity": int(quantity),
                "status": "HELD",
                "expiresAt": expires_at,
                "confirmedAt": None,
                "releasedAt": None,
                "releaseReason": None,
                "createdAt": timestamp_string(),
                "updatedAt": timestamp_string(),
            }
            self.rowcount = 1
            return

        if sql.startswith("SELECT holdId, eventId, seatCategory, quantity, status, expiresAt FROM seat_holds WHERE holdId = %s FOR UPDATE"):
            hold = holds.get(str(params[0]))
            self.results = [deepcopy(hold)] if hold else []
            return

        if sql.startswith("SELECT holdId, eventId, seatCategory, quantity, status FROM seat_holds WHERE holdId = %s FOR UPDATE"):
            hold = holds.get(str(params[0]))
            self.results = [deepcopy(hold)] if hold else []
            return

        if sql.startswith("SELECT holdId, eventId, seatCategory, quantity, status, expiresAt, confirmedAt, releasedAt, releaseReason, createdAt, updatedAt FROM seat_holds WHERE holdId = %s"):
            hold = holds.get(str(params[0]))
            self.results = [deepcopy(hold)] if hold else []
            return

        if sql.startswith("UPDATE seat_holds SET status = 'CONFIRMED'"):
            hold_id = str(params[0])
            hold = holds[hold_id]
            hold["status"] = "CONFIRMED"
            hold["confirmedAt"] = timestamp_string()
            hold["updatedAt"] = timestamp_string()
            self.rowcount = 1
            return

        if sql.startswith("UPDATE seat_holds SET status = 'RELEASED'"):
            release_reason, hold_id = params
            hold = holds[str(hold_id)]
            hold["status"] = "RELEASED"
            hold["releasedAt"] = timestamp_string()
            hold["releaseReason"] = release_reason
            hold["updatedAt"] = timestamp_string()
            self.rowcount = 1
            return

        raise AssertionError(f"Unhandled SQL in test double: {sql}")

    def fetchone(self):
        return deepcopy(self.results[0]) if self.results else None

    def fetchall(self):
        return deepcopy(self.results)

    def close(self):
        return None


class FakeSeatDB:
    def __init__(self):
        self.inventory = {}
        self.holds = {}

    def cursor(self, dictionary=False):
        return FakeSeatCursor(self)

    def start_transaction(self):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


@pytest.fixture
def client(monkeypatch):
    db = FakeSeatDB()
    monkeypatch.setattr(seat_app, "get_db", lambda: db)
    monkeypatch.setattr(seat_app, "release_expired_holds", lambda *args, **kwargs: 0)
    return seat_app.app.test_client(), db


def test_seed_order_demo_inventory_supports_prefixed_lookup(client):
    test_client, _db = client

    response = test_client.post("/inventory/admin/seed-order-demo")

    assert response.status_code == 200
    assert response.get_json() == {"status": "seeded", "inventoryRows": 4, "holdRows": 4}

    lookup = test_client.get("/inventory/con-001")
    assert lookup.status_code == 200
    inventory = lookup.get_json()["inventory"]
    assert {(row["seatCategory"], row["availableSeats"]) for row in inventory} == {
        ("STANDARD", 149),
        ("VIP", 40),
    }


def test_hold_confirm_and_release_restore_demo_inventory(client):
    test_client, _db = client
    test_client.post("/inventory/admin/seed-order-demo")

    before = test_client.get("/inventory/con-001/STANDARD?quantity=1")
    assert before.status_code == 200
    assert before.get_json()["availableSeats"] == 149
    assert before.get_json()["isAvailable"] is True

    hold = test_client.post(
        "/inventory/hold",
        json={"eventId": "con-001", "seatCategory": "standard", "quantity": 1, "ttlSeconds": 120},
    )
    assert hold.status_code == 201
    hold_id = hold.get_json()["holdId"]

    after_hold = test_client.get("/inventory/con-001/STANDARD?quantity=1")
    assert after_hold.status_code == 200
    assert after_hold.get_json()["availableSeats"] == 148

    confirm = test_client.post("/inventory/confirm", json={"holdId": hold_id})
    assert confirm.status_code == 200
    assert confirm.get_json()["status"] == "CONFIRMED"

    blocked_release = test_client.post("/inventory/release", json={"holdId": hold_id})
    assert blocked_release.status_code == 409

    release = test_client.post(
        "/inventory/release",
        json={"holdId": hold_id, "allowConfirmedRelease": True, "reason": "REFUND"},
    )
    assert release.status_code == 200
    assert release.get_json()["status"] == "RELEASED"

    after_release = test_client.get("/inventory/con-001/STANDARD?quantity=1")
    assert after_release.status_code == 200
    assert after_release.get_json()["availableSeats"] == 149

    hold_state = test_client.get(f"/inventory/holds/{hold_id}")
    assert hold_state.status_code == 200
    assert hold_state.get_json()["status"] == "RELEASED"
    assert hold_state.get_json()["releaseReason"] == "REFUND"


def test_admin_create_bootstraps_inventory_for_new_event_and_blocks_recreate(client):
    test_client, _db = client

    create = test_client.post(
        "/inventory/admin/create",
        json={
            "eventId": "evt-runtime-123",
            "seatCategories": [
                {"seatCategory": "VIP", "totalSeats": 20},
                {"seatCategory": "CAT1", "totalSeats": 80, "availableSeats": 75},
            ],
        },
    )

    assert create.status_code == 201
    assert create.get_json()["status"] == "CREATED"
    assert len(create.get_json()["inventory"]) == 2

    duplicate = test_client.post(
        "/inventory/admin/create",
        json={
            "eventId": "evt-runtime-123",
            "seatCategories": [{"seatCategory": "VIP", "totalSeats": 10}],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.get_json()["eventId"] == "evt-runtime-123"
