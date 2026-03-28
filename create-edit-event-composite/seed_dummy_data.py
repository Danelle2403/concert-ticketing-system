import os
import sys

import requests


COMPOSITE_URL = os.environ.get("COMPOSITE_URL", "http://localhost:5012")
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://localhost:5001")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://localhost:5004")
MANAGER_EMAIL = os.environ.get("MANAGER_EMAIL", "manager@example.com")
MANAGER_NAME = os.environ.get("MANAGER_NAME", "Maya Manager")


def req_json(method, url, payload=None, timeout=10):
    response = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    return response.status_code, body


def ensure_manager():
    code, body = req_json("GET", f"{USER_SERVICE_URL}/users")
    if code != 200:
        raise RuntimeError(f"Unable to read User Service users: {body}")

    users = body.get("users") or []
    for user in users:
        if user.get("email") == MANAGER_EMAIL:
            if user.get("role") != "manager":
                raise RuntimeError(f"User {MANAGER_EMAIL} exists but is not a manager: {user}")
            return user["id"]

    code, body = req_json(
        "POST",
        f"{USER_SERVICE_URL}/user/new",
        {"name": MANAGER_NAME, "email": MANAGER_EMAIL, "role": "manager"},
    )
    if code != 201:
        raise RuntimeError(f"Unable to create manager user: {body}")
    return body["id"]


def ensure_inventory_seeded(event_id):
    code, body = req_json("GET", f"{SEAT_INVENTORY_URL}/inventory/{event_id}")
    if code != 200:
        raise RuntimeError(f"Seat Inventory bootstrap for {event_id} is unavailable: {body}")


def list_existing_titles(manager_id):
    code, body = req_json("GET", f"{COMPOSITE_URL}/manager/events?managerId={manager_id}")
    if code != 200:
        raise RuntimeError(f"Unable to list existing manager events: {body}")

    return {
        row.get("eventTitle")
        for row in body.get("data", {}).get("events", [])
        if row.get("eventTitle")
    }


def seed_event(payload):
    code, body = req_json("POST", f"{COMPOSITE_URL}/manager/events", payload)
    if code != 201:
        raise RuntimeError(f"Failed to seed event: {body}")
    return body


def main():
    manager_id = ensure_manager()
    existing_titles = list_existing_titles(manager_id)

    samples = [
        {
            "title": "Composite Demo: Midnight World Tour",
            "description": "Dummy seeded through the create/edit event composite.",
            "startAt": "2026-08-15T12:00:00.000Z",
            "endAt": "2026-08-15T15:00:00.000Z",
            "venue": {
                "name": "Marina Bay Sands",
                "address": "10 Bayfront Avenue",
                "city": "Singapore",
                "country": "Singapore",
            },
            "pricingTiers": [
                {"code": "VIP", "name": "VIP", "price": 188, "currency": "SGD"},
                {"code": "CAT1", "name": "Category 1", "price": 128, "currency": "SGD"},
                {"code": "CAT2", "name": "Category 2", "price": 88, "currency": "SGD"},
            ],
            "seatSections": [
                {"code": "A1", "name": "Floor Left", "tierCode": "VIP", "capacity": 50},
                {"code": "B1", "name": "Lower Bowl", "tierCode": "CAT1", "capacity": 120},
                {"code": "C1", "name": "Upper Bowl", "tierCode": "CAT2", "capacity": 200},
            ],
            "status": "PUBLISHED",
            "managerId": manager_id,
            "changedBy": f"manager-{manager_id}",
        },
        {
            "title": "Composite Demo: Neon Bloom Live",
            "description": "Second dummy event seeded through the composite.",
            "startAt": "2026-09-22T12:30:00.000Z",
            "endAt": "2026-09-22T15:30:00.000Z",
            "venue": {
                "name": "Singapore Indoor Stadium",
                "address": "2 Stadium Walk",
                "city": "Singapore",
                "country": "Singapore",
            },
            "pricingTiers": [
                {"code": "VIP", "name": "VIP", "price": 198, "currency": "SGD"},
                {"code": "CAT1", "name": "Category 1", "price": 138, "currency": "SGD"},
                {"code": "CAT2", "name": "Category 2", "price": 98, "currency": "SGD"},
            ],
            "seatSections": [
                {"code": "D1", "name": "Front Floor", "tierCode": "VIP", "capacity": 40},
                {"code": "E1", "name": "Lower Tier", "tierCode": "CAT1", "capacity": 150},
                {"code": "F1", "name": "Upper Tier", "tierCode": "CAT2", "capacity": 250},
            ],
            "status": "PUBLISHED",
            "managerId": manager_id,
            "changedBy": f"manager-{manager_id}",
        },
    ]

    for payload in samples:
        if payload["title"] in existing_titles:
            print(f"Skipping existing seed: {payload['title']}")
            continue

        body = seed_event(payload)
        event_id = body["data"]["event"]["id"]
        ensure_inventory_seeded(event_id)
        print(f"Seeded {payload['title']} -> {event_id}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
