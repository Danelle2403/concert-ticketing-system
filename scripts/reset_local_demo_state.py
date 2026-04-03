#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[1]
DEMO_STATE_PATH = ROOT / "demo" / "local_demo_state.json"

DEFAULT_SERVICE_URLS = {
    "user": "http://localhost:5001",
    "event": "http://localhost:5003",
    "seat": "http://localhost:5004",
    "ticket": "http://localhost:5002",
    "purchase": "http://localhost:5010",
}
DEFAULT_ORDER_SERVICE_URL = (
    "https://personal-uq3wxrah.outsystemscloud.com/OrderService/rest/Order"
)


def load_demo_state():
    with DEMO_STATE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def http_json(method, url, payload=None, timeout=20):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            parsed_body = json.loads(body) if body else None
            return response.status, parsed_body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed_body = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed_body = {"raw": body}
        return exc.code, parsed_body


def require_ok(method, url, payload=None, expected_statuses=(200,), timeout=20):
    status, body = http_json(method, url, payload=payload, timeout=timeout)
    if status not in expected_statuses:
        raise RuntimeError(f"{method} {url} failed with {status}: {body}")
    return body


def wait_for_health(name, url, timeout_seconds):
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        try:
            status, body = http_json("GET", url, timeout=5)
            if status == 200:
                return body
            last_error = f"{status}: {body}"
        except Exception as exc:  # pragma: no cover - defensive path for local script
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"{name} health check did not become ready at {url}: {last_error}")


def build_purchase_reset_payload(demo_state, order_id_overrides):
    purchases = []
    ticket_maps = []

    for row in demo_state["orderDemoOrders"]:
        order_id = order_id_overrides[row["purchaseId"]]
        purchases.append(
            {
                "purchaseId": row["purchaseId"],
                "orderIds": [order_id],
                "ticketIds": [row["ticketId"]],
                "userId": row["userId"],
                "eventId": row["eventId"],
                "quantity": row["quantity"],
                "seatCategory": row["seatCategory"],
                "status": row["purchaseStatus"],
                "paymentChargeId": row["paymentChargeId"],
                "paymentIntentId": row.get("paymentIntentId"),
                "paymentStatus": row["purchaseStatus"],
                "latestChargeId": row["paymentChargeId"],
                "amountPaid": row["amountPaid"],
                "currency": row["currency"],
                "createdAt": row["createdAt"],
                "updatedAt": row["updatedAt"],
            }
        )
        ticket_maps.append(
            {
                "ticketId": row["ticketId"],
                "purchaseId": row["purchaseId"],
                "orderId": order_id,
                "holdId": row["holdId"],
                "userId": row["userId"],
                "eventId": row["eventId"],
                "eventName": row["eventName"],
                "venue": row["venue"],
                "date": row["date"],
                "seatCategory": row["seatCategory"],
                "status": "ACTIVE" if row["purchaseStatus"] == "SUCCESS" else row["purchaseStatus"],
                "amountPaid": row["amountPaid"],
                "currency": row["currency"],
                "paymentIntentId": row.get("paymentIntentId"),
                "paymentChargeId": row["paymentChargeId"],
                "refundId": None,
                "createdAt": row["createdAt"],
                "updatedAt": row["updatedAt"],
            }
        )

    return {"purchases": purchases, "ticketMaps": ticket_maps}


def extract_order_id(body):
    if not isinstance(body, dict):
        return None
    for key in ("order_id", "orderId", "Id", "id"):
        value = body.get(key)
        if value is not None:
            return int(value)
    return None


def reset_external_orders(order_service_url, demo_state):
    order_ids = {}
    created = []

    for row in demo_state["orderDemoOrders"]:
        payload = {
            "FanId": int(row["userId"]),
            "TicketId": int(row.get("ticketIdInt") or row["ticketId"]),
            "ConcertId": int(row.get("eventIdInt") or row["eventId"]),
            "PaymentChargeId": row["paymentChargeId"],
            "SeatCategory": row.get("orderSeatCategory") or row["seatCategory"],
            "AmountPaid": row["amountPaid"],
        }
        body = require_ok(
            "POST",
            f"{order_service_url.rstrip('/')}/order/",
            payload=payload,
            expected_statuses=(200, 201),
            timeout=20,
        )
        order_id = extract_order_id(body)
        if order_id is None:
            raise RuntimeError(f"OrderService create response missing order_id: {body}")

        target_status = str(row.get("orderStatus") or "CONFIRMED").upper()
        if target_status != "CONFIRMED":
            require_ok(
                "PUT",
                f"{order_service_url.rstrip('/')}/order/{order_id}/status/",
                payload={"Status": target_status},
                expected_statuses=(200, 201),
                timeout=20,
            )

        order_ids[row["purchaseId"]] = order_id
        created.append({"purchaseId": row["purchaseId"], "orderId": order_id, "status": target_status})

    return order_ids, created


def summarize_local_state(service_urls):
    user_events = require_ok(
        "GET",
        f"{service_urls['user'].rstrip('/')}/user/managing?{parse.urlencode({'userId': 99})}",
    )
    event_rows = require_ok("GET", f"{service_urls['event'].rstrip('/')}/events")
    inventory_rows = require_ok("GET", f"{service_urls['seat'].rstrip('/')}/inventory")
    fan_tickets = require_ok(
        "GET",
        f"{service_urls['user'].rstrip('/')}/user/events?{parse.urlencode({'userId': 2})}",
    )
    return {
        "managedEvents": len(user_events.get("events", [])),
        "eventServiceEvents": len(event_rows.get("data", [])),
        "seatInventoryRows": len(inventory_rows.get("inventory", [])),
        "fan2Tickets": len(fan_tickets.get("events", [])),
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reset the local demo state from demo/local_demo_state.json."
    )
    parser.add_argument("--user-url", default=DEFAULT_SERVICE_URLS["user"])
    parser.add_argument("--event-url", default=DEFAULT_SERVICE_URLS["event"])
    parser.add_argument("--seat-url", default=DEFAULT_SERVICE_URLS["seat"])
    parser.add_argument("--ticket-url", default=DEFAULT_SERVICE_URLS["ticket"])
    parser.add_argument("--purchase-url", default=DEFAULT_SERVICE_URLS["purchase"])
    parser.add_argument("--order-url", default=DEFAULT_ORDER_SERVICE_URL)
    parser.add_argument("--skip-order-service", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=45)
    return parser.parse_args()


def main():
    args = parse_args()
    demo_state = load_demo_state()
    service_urls = {
        "user": args.user_url,
        "event": args.event_url,
        "seat": args.seat_url,
        "ticket": args.ticket_url,
        "purchase": args.purchase_url,
    }

    health_checks = {
        "user-service": f"{service_urls['user'].rstrip('/')}/health",
        "event-service": f"{service_urls['event'].rstrip('/')}/health",
        "seat-inventory": f"{service_urls['seat'].rstrip('/')}/health",
        "ticket-atomic": f"{service_urls['ticket'].rstrip('/')}/health",
        "purchase-composite": f"{service_urls['purchase'].rstrip('/')}/health",
    }
    for name, health_url in health_checks.items():
        wait_for_health(name, health_url, args.wait_seconds)

    require_ok("POST", f"{service_urls['event'].rstrip('/')}/admin/reset-demo")
    require_ok("POST", f"{service_urls['ticket'].rstrip('/')}/tickets/admin/reset-demo")
    require_ok("POST", f"{service_urls['user'].rstrip('/')}/user/admin/reset-demo")
    require_ok("POST", f"{service_urls['seat'].rstrip('/')}/inventory/admin/reset-demo")

    if args.skip_order_service:
        order_id_overrides = {
            row["purchaseId"]: int(row["defaultOrderId"]) for row in demo_state["orderDemoOrders"]
        }
        created_orders = []
    else:
        order_id_overrides, created_orders = reset_external_orders(args.order_url, demo_state)

    purchase_payload = build_purchase_reset_payload(demo_state, order_id_overrides)
    require_ok(
        "POST",
        f"{service_urls['purchase'].rstrip('/')}/purchase/admin/reset-demo",
        payload=purchase_payload,
    )

    summary = summarize_local_state(service_urls)
    print(
        json.dumps(
            {
                "status": "reset",
                "services": service_urls,
                "orderServiceCreated": created_orders,
                "summary": summary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # pragma: no cover - script exit path
        print("Interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
