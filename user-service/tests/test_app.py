from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as user_app

INTERNAL_HEADERS = {"X-Internal-Service-Token": user_app.INTERNAL_SERVICE_TOKEN}

DEMO_STATE = user_app.load_demo_seed_data()
DEMO_USERS = [
    {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "password_hash": user_app.generate_password_hash(row["password"]),
        "role": row["role"],
    }
    for row in DEMO_STATE["users"]
]
DEMO_MANAGED_EVENTS = deepcopy(DEMO_STATE["managedEvents"])
DEMO_USER_TICKETS = deepcopy(DEMO_STATE["userTickets"])


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

        if sql.startswith("SELECT column_name FROM information_schema.columns"):
            self.results = [{"column_name": "password_hash"}]
            return

        if sql.startswith("ALTER TABLE users ADD COLUMN password_hash"):
            self.rowcount = 0
            return

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

        if sql.startswith("INSERT INTO users (name, email, password_hash, role) VALUES"):
            user = {
                "id": state["next_user_id"],
                "name": params[0],
                "email": params[1],
                "password_hash": params[2],
                "role": params[3],
            }
            state["next_user_id"] += 1
            state["users"].append(user)
            self.lastrowid = user["id"]
            self.rowcount = 1
            return

        if sql.startswith("DELETE FROM user_tickets"):
            ticket_count = len(DEMO_USER_TICKETS)
            event_count = len({row["eventId"] for row in DEMO_MANAGED_EVENTS} | {row["eventId"] for row in DEMO_USER_TICKETS})
            user_count = len({row["id"] for row in DEMO_USERS} | {row["userId"] for row in DEMO_USER_TICKETS} | {row["managerId"] for row in DEMO_MANAGED_EVENTS})
            target_ticket_ids = {str(value) for value in params[:ticket_count]}
            target_event_ids = {
                str(value) for value in params[ticket_count:ticket_count + event_count]
            }
            target_user_ids = {
                int(value)
                for value in params[
                    ticket_count + event_count:ticket_count + event_count + user_count
                ]
            }
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
            target_event_ids = {str(value) for value in params}
            before = len(state["managed_events"])
            state["managed_events"] = [
                row for row in state["managed_events"] if row["eventId"] not in target_event_ids
            ]
            self.rowcount = before - len(state["managed_events"])
            return

        if sql.startswith("DELETE FROM users"):
            user_count = len({row["id"] for row in DEMO_USERS} | {row["userId"] for row in DEMO_USER_TICKETS} | {row["managerId"] for row in DEMO_MANAGED_EVENTS})
            target_ids = {int(value) for value in params[:user_count]}
            target_emails = {str(value) for value in params[user_count:]}
            before = len(state["users"])
            state["users"] = [
                row
                for row in state["users"]
                if row["id"] not in target_ids and row["email"] not in target_emails
            ]
            self.rowcount = before - len(state["users"])
            return

        if sql.startswith("INSERT INTO users (id, name, email, password_hash, role) VALUES"):
            user = {
                "id": int(params[0]),
                "name": params[1],
                "email": params[2],
                "password_hash": params[3],
                "role": params[4],
            }
            state["users"] = [row for row in state["users"] if row["id"] != user["id"]]
            state["users"].append(user)
            state["users"].sort(key=lambda row: row["id"])
            state["next_user_id"] = max((row["id"] for row in state["users"]), default=0) + 1
            self.rowcount = 1
            return

        if sql.startswith("INSERT INTO managed_events (id, managerId, eventId, name, venue, date, price, status) VALUES"):
            event = {
                "id": int(params[0]),
                "managerId": int(params[1]),
                "eventId": str(params[2]),
                "name": params[3],
                "venue": params[4],
                "date": params[5],
                "price": params[6],
                "status": params[7],
            }
            state["managed_events"] = [
                row for row in state["managed_events"] if row["id"] != event["id"]
            ]
            state["managed_events"].append(event)
            state["managed_events"].sort(key=lambda row: row["id"])
            self.rowcount = 1
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

        if sql.startswith("INSERT INTO user_tickets (id, userId, ticketId, eventId, eventName, venue, date, status) VALUES"):
            row = {
                "id": int(params[0]),
                "userId": int(params[1]),
                "ticketId": str(params[2]),
                "eventId": str(params[3]),
                "eventName": params[4],
                "venue": params[5],
                "date": params[6],
                "status": params[7],
            }
            state["user_tickets"] = [
                existing for existing in state["user_tickets"] if existing["id"] != row["id"]
            ]
            state["user_tickets"].append(row)
            state["user_tickets"].sort(key=lambda item: item["id"])
            state["next_ticket_row_id"] = (
                max((item["id"] for item in state["user_tickets"]), default=0) + 1
            )
            self.rowcount = 1
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
    monkeypatch.setattr(user_app, "_user_auth_schema_checked", False)
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-auth-secret")
    monkeypatch.setattr(user_app, "get_db", lambda: db)
    return user_app.app.test_client(), db


def test_seed_defaults_restores_order_aligned_demo_rows(client):
    test_client, db = client

    db.state["user_tickets"] = []
    db.state["managed_events"] = []
    db.state["users"] = [{
        "id": 555,
        "name": "Temp",
        "email": "temp@example.com",
        "password_hash": user_app.generate_password_hash("Temporary123!"),
        "role": "fan",
    }]

    response = test_client.post("/user/seed", headers=INTERNAL_HEADERS)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "seeded",
        "userCount": len(DEMO_USERS),
        "managedEventCount": len(DEMO_MANAGED_EVENTS),
        "ticketCount": len(DEMO_USER_TICKETS),
    }

    active_event_tickets = test_client.get(
        "/user/tickets/by-event/con-001?status=active",
        headers=INTERNAL_HEADERS,
    )
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

    managed = test_client.get("/user/managing?userId=99", headers=INTERNAL_HEADERS)
    assert managed.status_code == 200
    assert {row["eventId"] for row in managed.get_json()["events"]} == {
        "1001",
        "1002",
        "1",
        "2",
        "789",
    }

    manager = test_client.get("/user/99", headers=INTERNAL_HEADERS)
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
        headers=INTERNAL_HEADERS,
    )

    assert response.status_code == 201
    assert response.get_json()["userId"] == 3
    assert response.get_json()["ticketId"] == "900"
    assert response.get_json()["eventId"] == "1"

    lookup = test_client.get("/user/ticket/tkt-900", headers=INTERNAL_HEADERS)
    assert lookup.status_code == 200
    assert lookup.get_json()["ticketId"] == "900"

    cancel = test_client.post("/user/managed/con-001/cancel", headers=INTERNAL_HEADERS)
    assert cancel.status_code == 200
    assert cancel.get_json()["eventId"] == "1"
    assert cancel.get_json()["status"] == "cancelled"


def test_auth_register_and_login_use_email_password(client):
    test_client, db = client

    register = test_client.post(
        "/auth/register",
        json={
            "name": "New Fan",
            "email": "newfan@example.com",
            "password": "Password123!",
            "role": "fan",
        },
    )

    assert register.status_code == 201
    register_payload = register.get_json()
    assert register_payload["email"] == "newfan@example.com"
    assert register_payload["authToken"]
    assert "password_hash" not in register_payload

    created_user = next(row for row in db.state["users"] if row["email"] == "newfan@example.com")
    assert user_app.check_password_hash(created_user["password_hash"], "Password123!")

    login = test_client.post(
        "/auth/login",
        json={"email": "newfan@example.com", "password": "Password123!"},
    )

    assert login.status_code == 200
    login_payload = login.get_json()
    assert login_payload["email"] == "newfan@example.com"
    assert login_payload["userId"] == register_payload["userId"]
    assert login_payload["authToken"]

    session = test_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login_payload['authToken']}"},
    )

    assert session.status_code == 200
    assert session.get_json()["userId"] == register_payload["userId"]


def test_auth_login_rejects_invalid_password(client):
    test_client, _db = client

    response = test_client.post(
        "/auth/login",
        json={"email": "fan@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "Invalid email or password"


def test_auth_me_rejects_missing_or_invalid_token(client):
    test_client, _db = client

    missing = test_client.get("/auth/me")
    invalid = test_client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_internal_user_routes_require_internal_service_token(client):
    test_client, _db = client

    users_response = test_client.get("/users")
    seed_response = test_client.post("/user/seed")

    assert users_response.status_code == 403
    assert seed_response.status_code == 403
