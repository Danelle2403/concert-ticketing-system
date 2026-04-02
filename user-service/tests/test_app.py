from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as user_app


DEMO_USERS = [
    {"id": 1, "name": "Alice Fan", "email": "fan@example.com", "role": "fan"},
    {"id": 2, "name": "Noah Fan", "email": "fan2@example.com", "role": "fan"},
    {"id": 3, "name": "Chloe Fan", "email": "fan3@example.com", "role": "fan"},
    {"id": 99, "name": "Maya Manager", "email": "manager@example.com", "role": "manager"},
    {"id": 123, "name": "Legacy Fan", "email": "legacyfan@example.com", "role": "fan"},
]

DEMO_MANAGED_EVENTS = [
    {
        "id": 1,
        "managerId": 99,
        "eventId": "EVT1001",
        "name": "The Midnight World Tour",
        "venue": "Marina Bay Sands, Singapore",
        "date": "2026-08-15",
        "price": 88.0,
        "status": "active",
    },
    {
        "id": 2,
        "managerId": 99,
        "eventId": "EVT1002",
        "name": "Neon Bloom Live",
        "venue": "Singapore Indoor Stadium",
        "date": "2026-09-22",
        "price": 98.0,
        "status": "active",
    },
    {
        "id": 3,
        "managerId": 99,
        "eventId": "1",
        "name": "Pulse Arena Nights",
        "venue": "Capitol Theatre, Singapore",
        "date": "2026-04-18",
        "price": 80.0,
        "status": "active",
    },
    {
        "id": 4,
        "managerId": 99,
        "eventId": "2",
        "name": "Skyline VIP Session",
        "venue": "Singapore Indoor Stadium",
        "date": "2026-05-02",
        "price": 200.0,
        "status": "active",
    },
    {
        "id": 5,
        "managerId": 99,
        "eventId": "789",
        "name": "Harbour Lights Reunion",
        "venue": "The Star Theatre, Singapore",
        "date": "2026-03-10",
        "price": 150.0,
        "status": "cancelled",
    },
]

DEMO_USER_TICKETS = [
    {
        "id": 1,
        "userId": 123,
        "ticketId": "456",
        "eventId": "789",
        "eventName": "Harbour Lights Reunion",
        "venue": "The Star Theatre, Singapore",
        "date": "2026-03-10",
        "status": "refunded",
    },
    {
        "id": 2,
        "userId": 1,
        "ticketId": "1",
        "eventId": "1",
        "eventName": "Pulse Arena Nights",
        "venue": "Capitol Theatre, Singapore",
        "date": "2026-04-18",
        "status": "cancelled",
    },
    {
        "id": 3,
        "userId": 2,
        "ticketId": "2",
        "eventId": "1",
        "eventName": "Pulse Arena Nights",
        "venue": "Capitol Theatre, Singapore",
        "date": "2026-04-18",
        "status": "active",
    },
    {
        "id": 4,
        "userId": 3,
        "ticketId": "3",
        "eventId": "2",
        "eventName": "Skyline VIP Session",
        "venue": "Singapore Indoor Stadium",
        "date": "2026-05-02",
        "status": "active",
    },
]


def build_demo_state():
    return {
        "users": deepcopy(DEMO_USERS),
        "managed_events": deepcopy(DEMO_MANAGED_EVENTS),
        "user_tickets": deepcopy(DEMO_USER_TICKETS),
        "next_user_id": 124,
        "next_ticket_row_id": 5,
    }


class FakeUserCursor:
    def __init__(self, db):
        self.db = db
        self.results = []
        self.rowcount = 0
        self.lastrowid = None

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        params = params or ()
        self.results = []
        self.rowcount = 0
        state = self.db.state

        if sql == "SELECT * FROM users":
            self.results = [deepcopy(row) for row in state["users"]]
            return

        if sql.startswith("SELECT * FROM users WHERE id = %s"):
            user_id = int(params[0])
            self.results = [deepcopy(row) for row in state["users"] if row["id"] == user_id]
            return

        if sql.startswith("SELECT * FROM users WHERE email = %s"):
            email = params[0]
            self.results = [deepcopy(row) for row in state["users"] if row["email"] == email]
            return

        if sql.startswith("INSERT INTO users (name, email, role) VALUES"):
            user = {
                "id": state["next_user_id"],
                "name": params[0],
                "email": params[1],
                "role": params[2],
            }
            state["next_user_id"] += 1
            state["users"].append(user)
            self.lastrowid = user["id"]
            self.rowcount = 1
            return

        if sql.startswith("DELETE FROM user_tickets"):
            target_ticket_ids = {"1", "2", "3", "456"}
            target_event_ids = {"1", "2", "789"}
            target_user_ids = {1, 2, 3, 123}
            before = len(state["user_tickets"])
            state["user_tickets"] = [
                row
                for row in state["user_tickets"]
                if row["ticketId"] not in target_ticket_ids
                and row["eventId"] not in target_event_ids
                and row["userId"] not in target_user_ids
            ]
            self.rowcount = before - len(state["user_tickets"])
            return

        if sql.startswith("DELETE FROM managed_events"):
            target_event_ids = {"EVT1001", "EVT1002", "1", "2", "789"}
            before = len(state["managed_events"])
            state["managed_events"] = [
                row for row in state["managed_events"] if row["eventId"] not in target_event_ids
            ]
            self.rowcount = before - len(state["managed_events"])
            return

        if sql.startswith("DELETE FROM users"):
            target_ids = {1, 2, 3, 99, 123}
            target_emails = {
                "fan@example.com",
                "fan2@example.com",
                "fan3@example.com",
                "manager@example.com",
                "legacyfan@example.com",
            }
            before = len(state["users"])
            state["users"] = [
                row
                for row in state["users"]
                if row["id"] not in target_ids and row["email"] not in target_emails
            ]
            self.rowcount = before - len(state["users"])
            return

        if sql.startswith("INSERT INTO users (id, name, email, role) VALUES"):
            state["users"] = deepcopy(DEMO_USERS)
            state["next_user_id"] = 124
            self.rowcount = len(state["users"])
            return

        if sql.startswith("INSERT INTO managed_events (managerId, eventId, name, venue, date, price, status) VALUES"):
            state["managed_events"] = deepcopy(DEMO_MANAGED_EVENTS)
            self.rowcount = len(state["managed_events"])
            return

        if sql.startswith("SELECT * FROM user_tickets WHERE userId = %s"):
            user_id = int(params[0])
            self.results = [deepcopy(row) for row in state["user_tickets"] if row["userId"] == user_id]
            return

        if sql.startswith("SELECT id FROM user_tickets WHERE ticketId = %s"):
            ticket_id = str(params[0])
            self.results = [
                {"id": row["id"]}
                for row in state["user_tickets"]
                if row["ticketId"] == ticket_id
            ]
            return

        if sql.startswith("UPDATE user_tickets SET userId = %s, eventId = %s, eventName = %s, venue = %s, date = %s, status = %s WHERE ticketId = %s"):
            ticket_id = str(params[6])
            for row in state["user_tickets"]:
                if row["ticketId"] == ticket_id:
                    row.update(
                        {
                            "userId": int(params[0]),
                            "eventId": str(params[1]),
                            "eventName": params[2],
                            "venue": params[3],
                            "date": params[4],
                            "status": params[5],
                        }
                    )
                    self.rowcount = 1
                    return
            return

        if sql.startswith("INSERT INTO user_tickets (userId, ticketId, eventId, eventName, venue, date, status) VALUES (%s, %s, %s, %s, %s, %s, %s)"):
            row = {
                "id": state["next_ticket_row_id"],
                "userId": int(params[0]),
                "ticketId": str(params[1]),
                "eventId": str(params[2]),
                "eventName": params[3],
                "venue": params[4],
                "date": params[5],
                "status": params[6],
            }
            state["next_ticket_row_id"] += 1
            state["user_tickets"].append(row)
            self.rowcount = 1
            return

        if sql.startswith("INSERT INTO user_tickets (userId, ticketId, eventId, eventName, venue, date, status) VALUES"):
            state["user_tickets"] = deepcopy(DEMO_USER_TICKETS)
            state["next_ticket_row_id"] = 5
            self.rowcount = len(state["user_tickets"])
            return

        if sql.startswith("SELECT * FROM user_tickets WHERE ticketId = %s"):
            ticket_id = str(params[0])
            self.results = [deepcopy(row) for row in state["user_tickets"] if row["ticketId"] == ticket_id]
            return

        if sql.startswith("UPDATE user_tickets SET status = %s WHERE ticketId = %s"):
            ticket_id = str(params[1])
            for row in state["user_tickets"]:
                if row["ticketId"] == ticket_id:
                    row["status"] = params[0]
                    self.rowcount = 1
                    return
            return

        if sql.startswith("SELECT * FROM user_tickets WHERE eventId = %s AND status = %s"):
            event_id = str(params[0])
            status = params[1]
            self.results = [
                deepcopy(row)
                for row in state["user_tickets"]
                if row["eventId"] == event_id and row["status"] == status
            ]
            return

        if sql.startswith("SELECT * FROM user_tickets WHERE eventId = %s"):
            event_id = str(params[0])
            self.results = [deepcopy(row) for row in state["user_tickets"] if row["eventId"] == event_id]
            return

        if sql.startswith("SELECT * FROM managed_events WHERE managerId = %s"):
            manager_id = int(params[0])
            self.results = [
                deepcopy(row) for row in state["managed_events"] if row["managerId"] == manager_id
            ]
            return

        if sql.startswith("SELECT * FROM managed_events WHERE eventId = %s"):
            event_id = str(params[0])
            self.results = [
                deepcopy(row) for row in state["managed_events"] if row["eventId"] == event_id
            ]
            return

        if sql.startswith("UPDATE managed_events SET name = %s, venue = %s, date = %s, price = %s, status = %s WHERE eventId = %s"):
            event_id = str(params[5])
            for row in state["managed_events"]:
                if row["eventId"] == event_id:
                    row.update(
                        {
                            "name": params[0],
                            "venue": params[1],
                            "date": params[2],
                            "price": params[3],
                            "status": params[4],
                        }
                    )
                    self.rowcount = 1
                    return
            return

        if sql.startswith("UPDATE managed_events SET status = 'cancelled' WHERE eventId = %s"):
            event_id = str(params[0])
            for row in state["managed_events"]:
                if row["eventId"] == event_id:
                    row["status"] = "cancelled"
                    self.rowcount = 1
                    return
            return

        raise AssertionError(f"Unhandled SQL in test double: {sql}")

    def fetchone(self):
        return deepcopy(self.results[0]) if self.results else None

    def fetchall(self):
        return deepcopy(self.results)

    def close(self):
        return None


class FakeUserDB:
    def __init__(self):
        self.state = build_demo_state()

    def cursor(self, dictionary=False):
        return FakeUserCursor(self)

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


@pytest.fixture
def client(monkeypatch):
    db = FakeUserDB()
    monkeypatch.setattr(user_app, "get_db", lambda: db)
    return user_app.app.test_client(), db


def test_seed_defaults_restores_order_aligned_demo_rows(client):
    test_client, db = client

    db.state["user_tickets"] = []
    db.state["managed_events"] = []
    db.state["users"] = [{"id": 555, "name": "Temp", "email": "temp@example.com", "role": "fan"}]

    response = test_client.post("/user/seed")

    assert response.status_code == 200
    assert response.get_json() == {"status": "seeded"}

    active_event_tickets = test_client.get("/user/tickets/by-event/con-001?status=active")
    assert active_event_tickets.status_code == 200
    assert active_event_tickets.get_json()["tickets"] == [
        {
            "id": 3,
            "userId": 2,
            "ticketId": "2",
            "eventId": "1",
            "eventName": "Pulse Arena Nights",
            "venue": "Capitol Theatre, Singapore",
            "date": "2026-04-18",
            "status": "active",
        }
    ]

    managed = test_client.get("/user/managing?userId=99")
    assert managed.status_code == 200
    assert {row["eventId"] for row in managed.get_json()["events"]} == {
        "EVT1001",
        "EVT1002",
        "1",
        "2",
        "789",
    }

    manager = test_client.get("/user/99")
    assert manager.status_code == 200
    assert manager.get_json()["role"] == "manager"


def test_ticket_upsert_and_managed_event_cancel_normalize_prefixed_ids(client):
    test_client, _db = client

    response = test_client.post(
        "/user/tickets/add",
        json={
            "userId": "fan-003",
            "ticketId": "tkt-900",
            "eventId": "con-001",
            "eventName": "Pulse Arena Nights",
            "venue": "Capitol Theatre, Singapore",
            "date": "2026-04-18",
            "status": "active",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["userId"] == 3
    assert response.get_json()["ticketId"] == "900"
    assert response.get_json()["eventId"] == "1"

    lookup = test_client.get("/user/ticket/tkt-900")
    assert lookup.status_code == 200
    assert lookup.get_json()["ticketId"] == "900"

    cancel = test_client.post("/user/managed/con-001/cancel")
    assert cancel.status_code == 200
    assert cancel.get_json()["eventId"] == "1"
    assert cancel.get_json()["status"] == "cancelled"
