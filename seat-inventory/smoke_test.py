import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://localhost:5004"


class TestFail(Exception):
    pass


def req(method, path, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.getcode(), json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, json.loads(raw) if raw else None


def assert_true(condition, message):
    if not condition:
        raise TestFail(message)


def test_all():
    code, payload = req("GET", "/health")
    assert_true(code == 200 and payload.get("status"), f"health failed: {code} {payload}")

    code, payload = req("GET", "/inventory")
    assert_true(code == 200 and isinstance(payload.get("inventory"), list), "inventory list failed")

    code, _ = req("GET", "/inventory/EVT1001")
    assert_true(code == 200, "event lookup failed")

    code, _ = req("GET", "/inventory/NOEVENT")
    assert_true(code == 404, "event 404 failed")

    code, _ = req("GET", "/inventory/EVT1001/VIP?quantity=abc")
    assert_true(code == 400, "quantity validation failed")

    code, _ = req("POST", "/inventory/hold", {})
    assert_true(code == 400, "hold required field validation failed")

    code, _ = req("POST", "/inventory/hold", {"eventId": "EVT1001", "seatCategory": "VIP", "quantity": 99999})
    assert_true(code == 409, "sold-out behavior failed")

    code, hold = req("POST", "/inventory/hold", {"eventId": "EVT1001", "seatCategory": "CAT1", "quantity": 1, "ttlSeconds": 120})
    assert_true(code == 201 and hold.get("holdId"), f"hold create failed: {code} {hold}")
    hold_id = hold["holdId"]

    code, _ = req("POST", "/inventory/confirm", {"holdId": hold_id})
    assert_true(code == 200, "confirm failed")

    code, _ = req("POST", "/inventory/release", {"holdId": hold_id})
    assert_true(code == 409, "confirmed hold release guard failed")

    code, _ = req("POST", "/inventory/release", {"holdId": hold_id, "allowConfirmedRelease": True, "reason": "TEST"})
    assert_true(code == 200, "confirmed release override failed")

    code, before = req("GET", "/inventory/EVT1001/CAT2?quantity=1")
    assert_true(code == 200, "pre-expiry availability read failed")
    before_avail = before["availableSeats"]

    code, exp_hold = req("POST", "/inventory/hold", {"eventId": "EVT1001", "seatCategory": "CAT2", "quantity": 1, "ttlSeconds": 1})
    assert_true(code == 201, "expiry hold create failed")
    exp_hold_id = exp_hold["holdId"]

    time.sleep(2)
    req("GET", "/inventory")

    code, exp_state = req("GET", f"/inventory/holds/{exp_hold_id}")
    assert_true(code == 200 and exp_state.get("status") == "EXPIRED", "hold expiry failed")

    code, after = req("GET", "/inventory/EVT1001/CAT2?quantity=1")
    assert_true(code == 200 and after["availableSeats"] == before_avail, "expiry did not restore seats")

    code, snap = req("GET", "/inventory/EVT1002/VIP?quantity=1")
    assert_true(code == 200, "concurrency pre-check failed")
    start_avail = snap["availableSeats"]
    attempts = min(start_avail + 5, 60)

    def hold_once(_):
        return req("POST", "/inventory/hold", {"eventId": "EVT1002", "seatCategory": "VIP", "quantity": 1, "ttlSeconds": 120})

    results = []
    with ThreadPoolExecutor(max_workers=attempts) as pool:
        futures = [pool.submit(hold_once, i) for i in range(attempts)]
        for future in as_completed(futures):
            results.append(future.result())

    successes = [p for c, p in results if c == 201]
    conflicts = [p for c, p in results if c == 409]
    others = [(c, p) for c, p in results if c not in (201, 409)]

    assert_true(not others, f"unexpected statuses: {others}")
    assert_true(len(successes) <= start_avail, "oversell detected")

    for s in successes:
        req("POST", "/inventory/release", {"holdId": s["holdId"], "reason": "TEST_CLEANUP"})

    code, end_snap = req("GET", "/inventory/EVT1002/VIP?quantity=1")
    assert_true(code == 200 and end_snap["availableSeats"] == start_avail, "cleanup did not restore availability")

    return {
        "start_avail_evt1002_vip": start_avail,
        "oversubscribe_attempts": attempts,
        "successes": len(successes),
        "conflicts": len(conflicts),
    }


if __name__ == "__main__":
    summary = test_all()
    print("ALL_TESTS_PASSED")
    print(json.dumps(summary, indent=2))
