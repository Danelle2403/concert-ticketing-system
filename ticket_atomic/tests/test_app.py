from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as ticket_app


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def close(self):
        return None


class FakeConnection:
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        return None

    def close(self):
        return None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ticket_app, "_db_initialized", True)
    return ticket_app.app.test_client()


def test_issue_ticket_returns_created_ticket(client, monkeypatch):
    issued_at = datetime.now(timezone.utc)
    fake_row = {
        "ticket_id": 42,
        "event_id": 123,
        "seat_section": "A",
        "seat_row": "3",
        "seat_number": "14",
        "is_valid": True,
        "issued_at": issued_at,
        "invalidated_at": None,
    }
    monkeypatch.setattr(ticket_app, "get_db", lambda: FakeConnection([fake_row]))

    response = client.post(
        "/tickets/issue",
        json={
            "event_id": 123,
            "seat_section": "A",
            "seat_row": "3",
            "seat_number": "14",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["ticket_id"] == 42
    assert payload["event_id"] == 123
    assert payload["seat"] == {"section": "A", "row": "3", "number": "14"}
    assert payload["is_valid"] is True


def test_invalidate_ticket_rejects_non_numeric_ids(client):
    response = client.post("/tickets/not-a-number/invalidate")

    assert response.status_code == 400
    assert response.get_json()["error"] == "ticket_id must be a positive integer"
