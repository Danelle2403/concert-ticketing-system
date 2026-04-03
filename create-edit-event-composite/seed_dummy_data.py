import os
from pathlib import Path
import sys
import json

import requests


COMPOSITE_URL = os.environ.get("COMPOSITE_URL", "http://localhost:5012")
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://localhost:5001")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://localhost:5004")
MANAGER_EMAIL = os.environ.get("MANAGER_EMAIL", "manager@example.com")
MANAGER_NAME = os.environ.get("MANAGER_NAME", "Maya Manager")
DEMO_STATE_PATH = Path(__file__).resolve().parents[1] / "demo" / "local_demo_state.json"


def load_demo_state():
    with DEMO_STATE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_sample_payloads(manager_id):
    demo_state = load_demo_state()
    samples = []
    for event in demo_state["eventServiceEvents"]:
        if int(event["id"]) not in {1001, 1002}:
            continue
        samples.append(
            {
                "title": f"Composite Demo: {event['title']}",
                "description": event["description"],
                "startAt": event["startAt"],
                "endAt": event["endAt"],
                "venue": event["venue"],
                "pricingTiers": [
                    {
                        "code": tier["code"],
                        "name": tier["name"],
                        "price": tier["price"],
                        "currency": tier["currency"],
                    }
                    for tier in event["pricingTiers"]
                ],
                "seatSections": [
                    {
                        "code": section["code"],
                        "name": section["name"],
                        "tierCode": section["tierCode"],
                        "capacity": section["capacity"],
                    }
                    for section in event["seatSections"]
                ],
                "status": event["status"],
                "managerId": manager_id,
                "changedBy": f"manager-{manager_id}",
            }
        )
    return samples


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
    samples = build_sample_payloads(manager_id)

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
