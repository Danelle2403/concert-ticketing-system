from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from datetime import datetime, timezone

import requests

app = Flask(__name__)
CORS(app)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL", "http://event-service:5000")
SEAT_INVENTORY_URL = os.environ.get("SEAT_INVENTORY_URL", "http://seat-inventory:5000")
TICKET_SERVICE_URL = os.environ.get("TICKET_SERVICE_URL", "http://ticket-atomic:5000")
PAYMENT_SERVICE_URL = os.environ.get("PAYMENT_SERVICE_URL", "http://payment-service:5000")
NOTIFICATION_SERVICE_URL = os.environ.get(
    "NOTIFICATION_SERVICE_URL", "http://notification-service:5000"
)
ORDER_SERVICE_URL = os.environ.get(
    "ORDER_SERVICE_URL",
    "https://personal-uq3wxrah.outsystemscloud.com/OrderService/rest/Order",
).rstrip("/")
DB_PATH = os.environ.get("PURCHASE_DB_PATH", "/data/purchase.db")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
CHECKOUT_HOLD_TTL_SECONDS = int(os.environ.get("CHECKOUT_HOLD_TTL_SECONDS", "600"))
DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "sgd")
INTERNAL_SERVICE_TOKEN = os.environ.get(
    "INTERNAL_SERVICE_TOKEN", "concert-hub-internal-dev-token"
)
INTERNAL_SERVICE_PREFIXES = (
    "http://user-service:",
    "http://event-service:",
    "http://seat-inventory:",
    "http://ticket-atomic:",
    "http://payment-service:",
    "http://notification-service:",
)


def env_flag(name, default=False):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def internal_service_headers_for_url(url):
    if any(str(url).startswith(prefix) for prefix in INTERNAL_SERVICE_PREFIXES):
        return {"X-Internal-Service-Token": INTERNAL_SERVICE_TOKEN}
    return {}

DEMO_STATE_PATH = Path(__file__).resolve().parents[1] / "demo" / "local_demo_state.json"


def load_demo_seed_data():
    with DEMO_STATE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_order_aligned_demo_events():
    demo_state = load_demo_seed_data()
    events = {}
    for event in demo_state["eventServiceEvents"]:
        event_id = str(event["id"])
        if event_id not in {"1", "2", "789"}:
            continue
        events[event_id] = {
            "id": event_id,
            "managerId": event.get("managerId"),
            "title": event["title"],
            "description": event.get("description", ""),
            "venue": event["venue"],
            "startAt": event["startAt"],
            "endAt": event["endAt"],
            "status": event["status"],
            "pricingTiers": event.get("pricingTiers", []),
            "seatSections": event.get("seatSections", []),
            "defaultSeatCategory": event.get("defaultSeatCategory"),
        }
    return events


def build_demo_purchase_seed(order_id_overrides=None):
    order_id_overrides = order_id_overrides or {}
    demo_state = load_demo_seed_data()
    purchases = []
    ticket_maps = []

    for row in demo_state["orderDemoOrders"]:
        order_id = order_id_overrides.get(row["purchaseId"], row["defaultOrderId"])
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

    return purchases, ticket_maps


ORDER_ALIGNED_DEMO_EVENTS = build_order_aligned_demo_events()


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_prefixed_id(value, prefixes):
    if value is None:
        return value

    text = str(value).strip()
    for prefix in prefixes:
        match = re.fullmatch(rf"{prefix}-(\d+)", text, flags=re.IGNORECASE)
        if match:
            return str(int(match.group(1)))
    return text


def normalize_user_id(value):
    return int(normalize_prefixed_id(value, ("fan",)))


def normalize_ticket_id(value):
    return normalize_prefixed_id(value, ("tkt",))


def normalize_event_id(value):
    return normalize_prefixed_id(value, ("con",))


def normalize_seat_category(value):
    if value is None:
        return value
    return str(value).strip().upper()


def order_api_int(value, field_name):
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    raise ValueError(f"OrderService expects integer {field_name}; got {text!r}")


def normalize_order_status_from_ticket(status):
    normalized = str(status or "").strip().upper()
    mapping = {
        "ACTIVE": "CONFIRMED",
        "SUCCESS": "CONFIRMED",
        "CONFIRMED": "CONFIRMED",
        "REFUNDED": "REFUNDED",
        "CANCELLED": "CANCELLED",
        "FAILED": "CANCELLED",
    }
    return mapping.get(normalized, normalized or "CONFIRMED")


def normalize_purchase_status(created_rows):
    statuses = {row["status"] for row in created_rows}
    if not created_rows:
        return "FAILED"
    if statuses == {"REFUNDED"}:
        return "REFUNDED"
    if statuses == {"CANCELLED"}:
        return "CANCELLED"
    if "ACTIVE" in statuses:
        return "SUCCESS"
    return created_rows[0]["status"]


def req_json(method, url, payload=None, timeout=8):
    response = requests.request(
        method,
        url,
        json=payload,
        timeout=timeout,
        headers=internal_service_headers_for_url(url) or None,
    )
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    return response.status_code, body


def extract_data(body):
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return body


def get_bearer_authorization():
    header = str(request.headers.get("Authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        return None
    return header


def authenticate_request_user():
    authorization = get_bearer_authorization()
    if not authorization:
        return None

    response = requests.request(
        "GET",
        f"{USER_SERVICE_URL}/auth/me",
        timeout=8,
        headers={"Authorization": authorization},
    )
    if response.status_code != 200:
        return None

    try:
        return extract_data(response.json())
    except Exception:
        return None


def require_authenticated_user():
    user = authenticate_request_user()
    if not user:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return user, None


def has_internal_service_access():
    provided = str(request.headers.get("X-Internal-Service-Token") or "")
    return bool(provided) and provided == INTERNAL_SERVICE_TOKEN


def to_minor_units(amount):
    return int(round(float(amount) * 100))


def normalize_currency(value):
    currency = str(value or "").strip().lower()
    return currency or DEFAULT_CURRENCY


def event_currency(event):
    tiers = event_pricing_tiers(event)
    for tier in tiers:
        currency = normalize_currency(tier.get("currency"))
        if currency:
            return currency
    return DEFAULT_CURRENCY


def hold_single_seat(event_id, seat_category, ttl_seconds):
    code, hold = req_json(
        "POST",
        f"{SEAT_INVENTORY_URL}/inventory/hold",
        {
            "eventId": event_id,
            "seatCategory": seat_category,
            "quantity": 1,
            "ttlSeconds": ttl_seconds,
        },
    )
    if code != 201:
        raise RuntimeError(f"Seat hold failed: {hold}")
    return hold


def release_hold(hold_id, reason):
    if not hold_id:
        return None
    return req_json(
        "POST",
        f"{SEAT_INVENTORY_URL}/inventory/release",
        {
            "holdId": hold_id,
            "allowConfirmedRelease": True,
            "reason": reason,
        },
    )


def create_payment_intent(amount_minor, currency, description, receipt_email, metadata):
    code, body = req_json(
        "POST",
        f"{PAYMENT_SERVICE_URL}/payments/intents",
        {
            "amount": amount_minor,
            "currency": currency,
            "description": description,
            "receiptEmail": receipt_email,
            "metadata": metadata,
        },
    )
    if code != 201:
        raise RuntimeError(f"Payment intent creation failed: {body}")
    return extract_data(body)


def fetch_payment_intent(payment_intent_id):
    code, body = req_json("GET", f"{PAYMENT_SERVICE_URL}/payments/intents/{payment_intent_id}")
    if code != 200:
        raise RuntimeError(f"Payment intent lookup failed: {body}")
    return extract_data(body)


def refund_payment(payment_intent_id, amount_minor, reason, metadata):
    code, body = req_json(
        "POST",
        f"{PAYMENT_SERVICE_URL}/refunds",
        {
            "paymentIntentId": payment_intent_id,
            "amount": amount_minor,
            "reason": reason,
            "metadata": metadata,
        },
    )
    if code != 201:
        raise RuntimeError(f"Payment refund failed: {body}")
    return extract_data(body)


def send_purchase_confirmation_notification(payload):
    try:
        req_json(
            "POST",
            f"{NOTIFICATION_SERVICE_URL}/notifications/purchase-confirmation",
            payload,
            timeout=10,
        )
    except Exception:
        return False
    return True


def issue_ticket(event_id):
    code, body = req_json("POST", f"{TICKET_SERVICE_URL}/tickets/issue", {"event_id": event_id})
    if code in (200, 201) and body.get("ticket_id") is not None:
        return body["ticket_id"]
    raise RuntimeError(f"Ticket issuance failed: {body}")


def invalidate_ticket(ticket_id):
    if not re.fullmatch(r"\d+", str(ticket_id).strip()):
        return
    req_json("POST", f"{TICKET_SERVICE_URL}/tickets/{ticket_id}/invalidate")


def ensure_sqlite_schema(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS purchases (
            purchaseId TEXT PRIMARY KEY,
            orderIds TEXT NOT NULL DEFAULT '[]',
            ticketIds TEXT NOT NULL DEFAULT '[]',
            userId INTEGER NOT NULL,
            eventId TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            seatCategory TEXT NOT NULL,
            status TEXT NOT NULL,
            paymentChargeId TEXT,
            paymentIntentId TEXT,
            paymentStatus TEXT,
            latestChargeId TEXT,
            amountPaid REAL,
            currency TEXT,
            buyerName TEXT,
            buyerEmail TEXT,
            createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_map (
            ticketId TEXT PRIMARY KEY,
            purchaseId TEXT NOT NULL,
            orderId INTEGER,
            holdId TEXT NOT NULL,
            userId INTEGER NOT NULL,
            eventId TEXT NOT NULL,
            eventName TEXT,
            venue TEXT,
            date TEXT,
            seatCategory TEXT,
            status TEXT NOT NULL,
            amountPaid REAL,
            currency TEXT,
            paymentIntentId TEXT,
            paymentChargeId TEXT,
            refundId TEXT,
            createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS checkout_sessions (
            checkoutSessionId TEXT PRIMARY KEY,
            purchaseId TEXT,
            userId INTEGER NOT NULL,
            eventId TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            seatCategory TEXT NOT NULL,
            amountPaid REAL NOT NULL,
            currency TEXT NOT NULL,
            buyerName TEXT,
            buyerEmail TEXT,
            holdIds TEXT NOT NULL DEFAULT '[]',
            paymentIntentId TEXT NOT NULL,
            clientSecret TEXT NOT NULL,
            status TEXT NOT NULL,
            expiresAt TEXT NOT NULL,
            createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL
        )
        """
    )
    ensure_sqlite_columns(
        cur,
        "purchases",
        {
            "orderIds": "TEXT NOT NULL DEFAULT '[]'",
            "ticketIds": "TEXT NOT NULL DEFAULT '[]'",
            "paymentChargeId": "TEXT",
            "paymentIntentId": "TEXT",
            "paymentStatus": "TEXT",
            "latestChargeId": "TEXT",
            "amountPaid": "REAL",
            "currency": "TEXT",
            "buyerName": "TEXT",
            "buyerEmail": "TEXT",
            "updatedAt": "TEXT NOT NULL DEFAULT ''",
        },
    )
    ensure_sqlite_columns(
        cur,
        "ticket_map",
        {
            "orderId": "INTEGER",
            "amountPaid": "REAL",
            "currency": "TEXT",
            "paymentIntentId": "TEXT",
            "paymentChargeId": "TEXT",
            "refundId": "TEXT",
            "updatedAt": "TEXT NOT NULL DEFAULT ''",
        },
    )
    conn.commit()


def ensure_sqlite_columns(cur, table_name, columns):
    cur.execute(f"PRAGMA table_info({table_name})")
    existing = {row[1] for row in cur.fetchall()}
    for column_name, column_type in columns.items():
        if column_name not in existing:
            cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def reset_order_aligned_demo_data(conn, purchases=None, ticket_maps=None):
    purchases = purchases or []
    ticket_maps = ticket_maps or []
    cur = conn.cursor()
    cur.execute("DELETE FROM checkout_sessions")
    cur.execute("DELETE FROM ticket_map")
    cur.execute("DELETE FROM purchases")

    for purchase in purchases:
        cur.execute(
            """
            INSERT INTO purchases
            (purchaseId, orderIds, ticketIds, userId, eventId, quantity, seatCategory, status, paymentChargeId,
             paymentIntentId, paymentStatus, latestChargeId, amountPaid, currency, buyerName, buyerEmail, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                purchase["purchaseId"],
                json.dumps(purchase["orderIds"]),
                json.dumps(purchase["ticketIds"]),
                purchase["userId"],
                purchase["eventId"],
                purchase["quantity"],
                purchase["seatCategory"],
                purchase["status"],
                purchase["paymentChargeId"],
                purchase.get("paymentIntentId"),
                purchase.get("paymentStatus"),
                purchase.get("latestChargeId"),
                purchase["amountPaid"],
                purchase.get("currency"),
                purchase.get("buyerName"),
                purchase.get("buyerEmail"),
                purchase["createdAt"],
                purchase["updatedAt"],
            ),
        )

    for ticket_map in ticket_maps:
        cur.execute(
            """
            INSERT INTO ticket_map
            (ticketId, purchaseId, orderId, holdId, userId, eventId, eventName, venue, date, seatCategory,
             status, amountPaid, currency, paymentIntentId, paymentChargeId, refundId, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_map["ticketId"],
                ticket_map["purchaseId"],
                ticket_map["orderId"],
                ticket_map["holdId"],
                ticket_map["userId"],
                ticket_map["eventId"],
                ticket_map["eventName"],
                ticket_map["venue"],
                ticket_map["date"],
                ticket_map["seatCategory"],
                ticket_map["status"],
                ticket_map.get("amountPaid"),
                ticket_map.get("currency"),
                ticket_map.get("paymentIntentId"),
                ticket_map.get("paymentChargeId"),
                ticket_map.get("refundId"),
                ticket_map["createdAt"],
                ticket_map["updatedAt"],
            ),
        )
    conn.commit()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    ensure_sqlite_schema(conn)
    conn.close()


def extract_event_payload(body):
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return body


def fetch_event(event_id):
    code, body = req_json("GET", f"{EVENT_SERVICE_URL}/events/{event_id}")
    if code == 200:
        return extract_event_payload(body)
    return ORDER_ALIGNED_DEMO_EVENTS.get(event_id)


def event_title(event):
    return event.get("title") or event.get("name") or "Untitled Event"


def event_status(event):
    return str(event.get("status") or "").strip().upper()


def event_venue_label(event):
    venue = event.get("venue")
    if isinstance(venue, dict):
        return ", ".join(part for part in [venue.get("name"), venue.get("city"), venue.get("country")] if part)
    if venue:
        return str(venue)
    return "Venue TBC"


def event_date_label(event):
    raw = event.get("date") or event.get("startAt")
    if not raw:
        return ""
    return str(raw)[:10]


def event_pricing_tiers(event):
    tiers = event.get("pricingTiers")
    return tiers if isinstance(tiers, list) else []


def derive_seat_category(event, requested):
    if requested:
        return normalize_seat_category(requested)

    default_category = event.get("defaultSeatCategory")
    if default_category:
        return normalize_seat_category(default_category)

    tiers = event_pricing_tiers(event)
    if tiers:
        sorted_tiers = sorted(tiers, key=lambda tier: float(tier.get("price") or 0))
        tier_code = sorted_tiers[0].get("code") or sorted_tiers[0].get("name")
        if tier_code:
            return normalize_seat_category(tier_code)

    sections = event.get("seatSections") if isinstance(event.get("seatSections"), list) else []
    if sections and sections[0].get("tierCode"):
        return normalize_seat_category(sections[0]["tierCode"])

    return "CAT1"


def derive_amount_paid(event, seat_category):
    normalized = normalize_seat_category(seat_category)
    tiers = event_pricing_tiers(event)
    for tier in tiers:
        if normalize_seat_category(tier.get("code")) == normalized:
            return float(tier.get("price") or 0)
        if normalize_seat_category(tier.get("name")) == normalized:
            return float(tier.get("price") or 0)

    fallback_price = event.get("price")
    if fallback_price is not None:
        return float(fallback_price)

    numeric_prices = [float(tier.get("price") or 0) for tier in tiers if tier.get("price") is not None]
    if numeric_prices:
        return min(numeric_prices)

    return 0.0


def order_seat_category(event, seat_category):
    normalized = normalize_seat_category(seat_category)
    tiers = event_pricing_tiers(event)
    for tier in tiers:
        if normalize_seat_category(tier.get("code")) == normalized:
            return tier.get("name") or tier.get("code") or seat_category
        if normalize_seat_category(tier.get("name")) == normalized:
            return tier.get("name") or seat_category
    return seat_category


def create_external_order(user_id, ticket_id, event_id, event, seat_category, payment_charge_id, amount_paid):
    payload = {
        "FanId": order_api_int(user_id, "FanId"),
        "TicketId": order_api_int(ticket_id, "TicketId"),
        "ConcertId": order_api_int(event_id, "ConcertId"),
        "PaymentChargeId": payment_charge_id,
        "SeatCategory": order_seat_category(event, seat_category),
        "AmountPaid": amount_paid,
    }
    code, body = req_json("POST", f"{ORDER_SERVICE_URL}/order/", payload)
    if code not in (200, 201):
        raise RuntimeError(f"Order creation failed: {body}")
    return body


def update_external_order_status(order_id, status):
    if not order_id:
        return None
    _, body = req_json(
        "PUT",
        f"{ORDER_SERVICE_URL}/order/{order_id}/status/",
        {"Status": normalize_order_status_from_ticket(status)},
    )
    return body


def fetch_external_order(order_id):
    code, body = req_json("GET", f"{ORDER_SERVICE_URL}/order/{order_id}/")
    if code == 200:
        return body
    return {"order_id": order_id, "error": body}


def serialize_purchase_row(row):
    payload = dict(row)
    for key in ("orderIds", "ticketIds"):
        try:
            payload[key] = json.loads(payload.get(key) or "[]")
        except json.JSONDecodeError:
            payload[key] = []
    return payload


def serialize_checkout_session_row(row):
    payload = dict(row)
    try:
        payload["holdIds"] = json.loads(payload.get("holdIds") or "[]")
    except json.JSONDecodeError:
        payload["holdIds"] = []
    return payload


@app.route("/health", methods=["GET"])
def health():
    checks = {}
    for name, url in (
        ("userService", f"{USER_SERVICE_URL}/health"),
        ("seatInventory", f"{SEAT_INVENTORY_URL}/health"),
        ("ticketAtomic", f"{TICKET_SERVICE_URL}/health"),
        ("paymentService", f"{PAYMENT_SERVICE_URL}/health"),
    ):
        code, body = req_json("GET", url, timeout=5)
        checks[name] = {"ok": code == 200, "statusCode": code, "body": body}

    status_code = 200 if all(check["ok"] for check in checks.values()) else 503
    return jsonify({"status": "Purchase Composite is running", "checks": checks}), status_code


@app.route("/purchase/config", methods=["GET"])
def purchase_config():
    return (
        jsonify(
            {
                "stripeConfigured": bool(STRIPE_PUBLISHABLE_KEY),
                "publishableKey": STRIPE_PUBLISHABLE_KEY or None,
                "seatHoldTtlSeconds": CHECKOUT_HOLD_TTL_SECONDS,
                "currency": DEFAULT_CURRENCY,
            }
        ),
        200,
    )


@app.route("/purchase/admin/reset-demo", methods=["POST"])
def reset_purchase_demo():
    if not has_internal_service_access():
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    purchases = data.get("purchases")
    ticket_maps = data.get("ticketMaps")
    if purchases is None or ticket_maps is None:
        purchases, ticket_maps = build_demo_purchase_seed()

    conn = get_db()
    try:
        reset_order_aligned_demo_data(conn, purchases=purchases, ticket_maps=ticket_maps)
    finally:
        conn.close()

    return (
        jsonify(
            {
                "status": "reset",
                "purchaseCount": len(purchases),
                "ticketMapCount": len(ticket_maps),
            }
        ),
        200,
    )


@app.route("/purchase/checkout/session", methods=["POST"])
def create_checkout_session():
    auth_user, error_response = require_authenticated_user()
    if error_response:
        return error_response

    data = request.get_json() or {}

    user_id_raw = data.get("userId")
    event_id = normalize_event_id(data.get("eventId"))
    quantity = int(data.get("quantity", 1))
    buyer_name = str(data.get("name") or "").strip()
    buyer_email = str(data.get("email") or "").strip()

    if not event_id:
        return jsonify({"error": "eventId is required"}), 400
    if quantity <= 0:
        return jsonify({"error": "quantity must be > 0"}), 400
    if not buyer_name or not buyer_email:
        return jsonify({"error": "name and email are required"}), 400

    user_id = int(auth_user["userId"])
    if user_id_raw is not None:
        try:
            requested_user_id = normalize_user_id(user_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "userId must be an integer"}), 400
        if requested_user_id != user_id:
            return jsonify({"error": "Forbidden"}), 403

    event = fetch_event(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    if event_status(event) == "CANCELLED":
        return jsonify({"error": "Event is cancelled"}), 409

    seat_category = derive_seat_category(event, data.get("seatCategory"))
    amount_per_ticket = derive_amount_paid(event, seat_category)
    currency = event_currency(event)
    amount_minor = to_minor_units(amount_per_ticket * quantity)
    checkout_session_id = str(uuid.uuid4())

    created_holds = []
    conn = None
    try:
        for _ in range(quantity):
            created_holds.append(
                hold_single_seat(event_id, seat_category, CHECKOUT_HOLD_TTL_SECONDS)
            )

        payment_intent = create_payment_intent(
            amount_minor=amount_minor,
            currency=currency,
            description=f"Concert purchase for {event_title(event)}",
            receipt_email=buyer_email or auth_user.get("email"),
            metadata={
                "checkoutSessionId": checkout_session_id,
                "eventId": str(event_id),
                "seatCategory": order_seat_category(event, seat_category),
                "quantity": quantity,
                "userId": str(user_id),
            },
        )

        now = utc_now_iso()
        expires_at = min(hold.get("expiresAt") for hold in created_holds)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO checkout_sessions
            (checkoutSessionId, purchaseId, userId, eventId, quantity, seatCategory, amountPaid, currency,
             buyerName, buyerEmail, holdIds, paymentIntentId, clientSecret, status, expiresAt, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkout_session_id,
                None,
                user_id,
                event_id,
                quantity,
                seat_category,
                amount_per_ticket * quantity,
                currency,
                buyer_name,
                buyer_email or auth_user.get("email"),
                json.dumps([hold["holdId"] for hold in created_holds]),
                payment_intent["paymentIntentId"],
                payment_intent["clientSecret"],
                "PENDING_PAYMENT",
                expires_at,
                now,
                now,
            ),
        )
        conn.commit()

        return (
            jsonify(
                {
                    "checkoutSessionId": checkout_session_id,
                    "paymentIntentId": payment_intent["paymentIntentId"],
                    "clientSecret": payment_intent["clientSecret"],
                    "publishableKey": STRIPE_PUBLISHABLE_KEY or None,
                    "currency": currency,
                    "amount": amount_minor,
                    "amountDisplay": round(amount_per_ticket * quantity, 2),
                    "seatCategory": seat_category,
                    "quantity": quantity,
                    "holdExpiresAt": expires_at,
                    "event": {
                        "eventId": event_id,
                        "title": event_title(event),
                        "venue": event_venue_label(event),
                        "date": event_date_label(event),
                    },
                }
            ),
            201,
        )
    except Exception as error:
        for hold in created_holds:
            release_hold(hold.get("holdId"), "CHECKOUT_SESSION_ABORTED")
        return jsonify({"error": str(error)}), 500
    finally:
        if conn:
            conn.close()


@app.route("/purchase/checkout/confirm", methods=["POST"])
def confirm_checkout_session():
    auth_user, error_response = require_authenticated_user()
    if error_response:
        return error_response

    data = request.get_json() or {}
    checkout_session_id = str(data.get("checkoutSessionId") or "").strip()
    payment_intent_id = str(data.get("paymentIntentId") or "").strip()

    if not checkout_session_id:
        return jsonify({"error": "checkoutSessionId is required"}), 400

    conn = None
    created_rows = []
    checkout_session = None

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM checkout_sessions WHERE checkoutSessionId = ?",
            (checkout_session_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Checkout session not found"}), 404

        checkout_session = serialize_checkout_session_row(row)
        if int(checkout_session["userId"]) != int(auth_user["userId"]):
            conn.close()
            return jsonify({"error": "Forbidden"}), 403
        if (
            payment_intent_id
            and checkout_session.get("paymentIntentId")
            and payment_intent_id != checkout_session["paymentIntentId"]
        ):
            conn.close()
            return jsonify({"error": "paymentIntentId does not match checkout session"}), 409

        if checkout_session["status"] == "COMPLETED" and checkout_session.get("purchaseId"):
            purchase_id = checkout_session["purchaseId"]
            cur.execute("SELECT * FROM purchases WHERE purchaseId = ?", (purchase_id,))
            purchase_row = cur.fetchone()
            conn.close()
            if purchase_row:
                payload = serialize_purchase_row(purchase_row)
                payload["orders"] = [
                    fetch_external_order(order_id) for order_id in payload.get("orderIds", [])
                ]
                return jsonify(payload), 200
            return jsonify({"error": "Completed purchase record is missing"}), 500

        event_id = checkout_session["eventId"]
        event = fetch_event(event_id)
        if not event:
            conn.close()
            return jsonify({"error": "Event not found"}), 404

        payment_intent = fetch_payment_intent(checkout_session["paymentIntentId"])
        payment_status = str(payment_intent.get("status") or "").lower()
        if payment_status != "succeeded":
            conn.close()
            return (
                jsonify(
                    {
                        "error": "Payment has not succeeded yet",
                        "paymentStatus": payment_intent.get("status"),
                    }
                ),
                409,
            )

        latest_charge_id = (
            payment_intent.get("latestChargeId")
            or payment_intent.get("paymentIntentId")
            or checkout_session["paymentIntentId"]
        )
        amount_per_ticket = float(checkout_session["amountPaid"]) / max(
            int(checkout_session["quantity"]), 1
        )
        purchase_id = str(uuid.uuid4())
        now = utc_now_iso()

        for hold_id in checkout_session["holdIds"]:
            code, confirm_payload = req_json(
                "POST",
                f"{SEAT_INVENTORY_URL}/inventory/confirm",
                {"holdId": hold_id},
            )
            if code != 200:
                raise RuntimeError(f"Seat confirm failed: {confirm_payload}")

            ticket_id = issue_ticket(event_id)
            code, _ = req_json(
                "POST",
                f"{USER_SERVICE_URL}/user/tickets/add",
                {
                    "userId": checkout_session["userId"],
                    "ticketId": ticket_id,
                    "eventId": event_id,
                    "eventName": event_title(event),
                    "venue": event_venue_label(event),
                    "date": event_date_label(event),
                    "status": "active",
                },
            )
            if code not in (200, 201):
                raise RuntimeError("User ticket write failed")

            order_resp = create_external_order(
                user_id=checkout_session["userId"],
                ticket_id=ticket_id,
                event_id=event_id,
                event=event,
                seat_category=checkout_session["seatCategory"],
                payment_charge_id=latest_charge_id,
                amount_paid=amount_per_ticket,
            )

            created_rows.append(
                {
                    "ticketId": ticket_id,
                    "holdId": hold_id,
                    "orderId": order_resp.get("order_id"),
                    "status": "ACTIVE",
                    "amountPaid": amount_per_ticket,
                }
            )

        order_ids = [row["orderId"] for row in created_rows if row.get("orderId") is not None]
        ticket_ids = [row["ticketId"] for row in created_rows]

        cur.execute(
            """
            INSERT OR REPLACE INTO purchases
            (purchaseId, orderIds, ticketIds, userId, eventId, quantity, seatCategory, status, paymentChargeId,
             paymentIntentId, paymentStatus, latestChargeId, amountPaid, currency, buyerName, buyerEmail, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                purchase_id,
                json.dumps(order_ids),
                json.dumps(ticket_ids),
                checkout_session["userId"],
                event_id,
                checkout_session["quantity"],
                checkout_session["seatCategory"],
                "SUCCESS",
                latest_charge_id,
                checkout_session["paymentIntentId"],
                "SUCCEEDED",
                latest_charge_id,
                checkout_session["amountPaid"],
                checkout_session["currency"],
                checkout_session.get("buyerName"),
                checkout_session.get("buyerEmail"),
                now,
                now,
            ),
        )

        for row in created_rows:
            cur.execute(
                """
                INSERT OR REPLACE INTO ticket_map
                (ticketId, purchaseId, orderId, holdId, userId, eventId, eventName, venue, date, seatCategory,
                 status, amountPaid, currency, paymentIntentId, paymentChargeId, refundId, createdAt, updatedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["ticketId"],
                    purchase_id,
                    row["orderId"],
                    row["holdId"],
                    checkout_session["userId"],
                    event_id,
                    event_title(event),
                    event_venue_label(event),
                    event_date_label(event),
                    checkout_session["seatCategory"],
                    row["status"],
                    row["amountPaid"],
                    checkout_session["currency"],
                    checkout_session["paymentIntentId"],
                    latest_charge_id,
                    None,
                    now,
                    now,
                ),
            )

        cur.execute(
            """
            UPDATE checkout_sessions
            SET purchaseId = ?, status = 'COMPLETED', updatedAt = ?
            WHERE checkoutSessionId = ?
            """,
            (purchase_id, now, checkout_session_id),
        )

        conn.commit()
        conn.close()

        send_purchase_confirmation_notification(
            {
                "purchaseId": purchase_id,
                "paymentIntentId": checkout_session["paymentIntentId"],
                "paymentChargeId": latest_charge_id,
                "amountPaid": checkout_session["amountPaid"],
                "currency": checkout_session["currency"],
                "buyerName": checkout_session.get("buyerName"),
                "buyerEmail": checkout_session.get("buyerEmail"),
                "event": {
                    "eventId": event_id,
                    "title": event_title(event),
                    "venue": event_venue_label(event),
                    "date": event_date_label(event),
                },
                "ticketIds": ticket_ids,
                "orderIds": order_ids,
            }
        )

        return (
            jsonify(
                {
                    "purchaseId": purchase_id,
                    "orderIds": order_ids,
                    "status": "SUCCESS",
                    "paymentIntentId": checkout_session["paymentIntentId"],
                    "paymentChargeId": latest_charge_id,
                    "tickets": ticket_ids,
                }
            ),
            201,
        )
    except Exception as error:
        if conn:
            conn.rollback()
            conn.close()

        refund_data = None
        if checkout_session:
            for hold_id in checkout_session.get("holdIds", []):
                release_hold(hold_id, "CHECKOUT_CONFIRM_FAILED")

            for row in created_rows:
                req_json(
                    "POST",
                    f"{USER_SERVICE_URL}/user/ticket/{row['ticketId']}/status",
                    {"status": "cancelled"},
                )
                if row.get("orderId") is not None:
                    update_external_order_status(row["orderId"], "CANCELLED")
                invalidate_ticket(row["ticketId"])

            try:
                refund_data = refund_payment(
                    checkout_session["paymentIntentId"],
                    to_minor_units(checkout_session["amountPaid"]),
                    "requested_by_customer",
                    {
                        "checkoutSessionId": checkout_session["checkoutSessionId"],
                        "eventId": str(checkout_session["eventId"]),
                    },
                )
            except Exception:
                refund_data = None

            if refund_data:
                for row in created_rows:
                    if row.get("orderId") is not None:
                        update_external_order_status(row["orderId"], "REFUNDED")

            repair_conn = get_db()
            try:
                repair_cur = repair_conn.cursor()
                repair_cur.execute(
                    """
                    UPDATE checkout_sessions
                    SET status = ?, updatedAt = ?
                    WHERE checkoutSessionId = ?
                    """,
                    (
                        "REFUNDED" if refund_data else "FAILED",
                        utc_now_iso(),
                        checkout_session_id,
                    ),
                )
                repair_conn.commit()
            finally:
                repair_conn.close()

        response = {"error": str(error)}
        if refund_data:
            response["refund"] = refund_data
        return jsonify(response), 500


@app.route("/purchase/checkout", methods=["POST"])
def checkout():
    auth_user, error_response = require_authenticated_user()
    if error_response:
        return error_response

    data = request.get_json() or {}

    user_id_raw = data.get("userId")
    event_id = normalize_event_id(data.get("eventId"))
    quantity = int(data.get("quantity", 1))

    if not event_id:
        return jsonify({"error": "eventId is required"}), 400
    if quantity <= 0:
        return jsonify({"error": "quantity must be > 0"}), 400

    user_id = int(auth_user["userId"])
    if user_id_raw is not None:
        try:
            requested_user_id = normalize_user_id(user_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "userId must be an integer"}), 400
        if requested_user_id != user_id:
            return jsonify({"error": "Forbidden"}), 403

    event = fetch_event(event_id)
    if not event:
        return jsonify({"error": "Event not found"}), 404
    if event_status(event) == "CANCELLED":
        return jsonify({"error": "Event is cancelled"}), 409

    seat_category = derive_seat_category(event, data.get("seatCategory"))
    amount_paid = derive_amount_paid(event, seat_category)
    payment_charge_id = str(data.get("paymentChargeId") or f"PAY-{uuid.uuid4()}")
    purchase_id = str(uuid.uuid4())

    created_rows = []
    conn = get_db()
    cur = conn.cursor()

    try:
        for _ in range(quantity):
            code, hold = req_json(
                "POST",
                f"{SEAT_INVENTORY_URL}/inventory/hold",
                {
                    "eventId": event_id,
                    "seatCategory": seat_category,
                    "quantity": 1,
                    "ttlSeconds": 300,
                },
            )
            if code != 201:
                raise RuntimeError(f"Seat hold failed: {hold}")

            hold_id = hold["holdId"]
            ticket_id = issue_ticket(event_id)

            code, _ = req_json("POST", f"{SEAT_INVENTORY_URL}/inventory/confirm", {"holdId": hold_id})
            if code != 200:
                raise RuntimeError("Seat confirm failed")

            code, _ = req_json(
                "POST",
                f"{USER_SERVICE_URL}/user/tickets/add",
                {
                    "userId": user_id,
                    "ticketId": ticket_id,
                    "eventId": event_id,
                    "eventName": event_title(event),
                    "venue": event_venue_label(event),
                    "date": event_date_label(event),
                    "status": "active",
                },
            )
            if code not in (200, 201):
                raise RuntimeError("User ticket write failed")

            order_resp = create_external_order(
                user_id=user_id,
                ticket_id=ticket_id,
                event_id=event_id,
                event=event,
                seat_category=seat_category,
                payment_charge_id=payment_charge_id,
                amount_paid=amount_paid,
            )

            created_rows.append(
                {
                    "ticketId": ticket_id,
                    "holdId": hold_id,
                    "orderId": order_resp.get("order_id"),
                    "status": "ACTIVE",
                }
            )

        now = utc_now_iso()
        order_ids = [row["orderId"] for row in created_rows if row.get("orderId") is not None]
        ticket_ids = [row["ticketId"] for row in created_rows]

        cur.execute(
            """
            INSERT OR REPLACE INTO purchases
            (purchaseId, orderIds, ticketIds, userId, eventId, quantity, seatCategory, status, paymentChargeId, amountPaid, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                purchase_id,
                json.dumps(order_ids),
                json.dumps(ticket_ids),
                user_id,
                event_id,
                quantity,
                seat_category,
                "SUCCESS",
                payment_charge_id,
                amount_paid * quantity,
                now,
                now,
            ),
        )

        for row in created_rows:
            cur.execute(
                """
                INSERT OR REPLACE INTO ticket_map
                (ticketId, purchaseId, orderId, holdId, userId, eventId, eventName, venue, date, seatCategory, status, createdAt, updatedAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["ticketId"],
                    purchase_id,
                    row["orderId"],
                    row["holdId"],
                    user_id,
                    event_id,
                    event_title(event),
                    event_venue_label(event),
                    event_date_label(event),
                    seat_category,
                    row["status"],
                    now,
                    now,
                ),
            )

        conn.commit()
        return (
            jsonify(
                {
                    "purchaseId": purchase_id,
                    "orderIds": order_ids,
                    "status": "SUCCESS",
                    "paymentChargeId": payment_charge_id,
                    "tickets": ticket_ids,
                }
            ),
            201,
        )
    except Exception as error:
        conn.rollback()

        for row in created_rows:
            if row.get("orderId") is not None:
                update_external_order_status(row["orderId"], "CANCELLED")
            req_json(
                "POST",
                f"{SEAT_INVENTORY_URL}/inventory/release",
                {
                    "holdId": row["holdId"],
                    "allowConfirmedRelease": True,
                    "reason": "PURCHASE_ROLLBACK",
                },
            )
            req_json(
                "POST",
                f"{USER_SERVICE_URL}/user/ticket/{row['ticketId']}/status",
                {"status": "cancelled"},
            )
            invalidate_ticket(row["ticketId"])

        now = utc_now_iso()
        cur.execute(
            """
            INSERT OR REPLACE INTO purchases
            (purchaseId, orderIds, ticketIds, userId, eventId, quantity, seatCategory, status, paymentChargeId, amountPaid, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                purchase_id,
                json.dumps([row["orderId"] for row in created_rows if row.get("orderId") is not None]),
                json.dumps([row["ticketId"] for row in created_rows]),
                user_id,
                event_id,
                quantity,
                seat_category,
                "FAILED",
                payment_charge_id,
                amount_paid * quantity,
                now,
                now,
            ),
        )
        conn.commit()
        return jsonify({"error": str(error)}), 500
    finally:
        conn.close()


@app.route("/purchase/<purchaseId>/status", methods=["GET"])
def purchase_status(purchaseId):
    auth_user, error_response = require_authenticated_user()
    if error_response:
        return error_response

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM purchases WHERE purchaseId = ?", (purchaseId,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Purchase not found"}), 404

    payload = serialize_purchase_row(row)
    if int(payload["userId"]) != int(auth_user["userId"]):
        return jsonify({"error": "Forbidden"}), 403
    payload["orders"] = [fetch_external_order(order_id) for order_id in payload["orderIds"]]
    return jsonify(payload), 200


@app.route("/purchase/ticket/<ticketId>", methods=["GET"])
def ticket_lookup(ticketId):
    if not has_internal_service_access():
        return jsonify({"error": "Forbidden"}), 403
    ticketId = normalize_ticket_id(ticketId)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ticket_map WHERE ticketId = ?", (ticketId,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Ticket mapping not found"}), 404
    return jsonify(dict(row)), 200


@app.route("/purchase/ticket/<ticketId>/status", methods=["POST"])
def ticket_update_status(ticketId):
    if not has_internal_service_access():
        return jsonify({"error": "Forbidden"}), 403
    ticketId = normalize_ticket_id(ticketId)
    data = request.get_json() or {}
    status = str(data.get("status") or "").strip().upper()
    refund_id = data.get("refundId")
    if not status:
        return jsonify({"error": "status is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ticket_map WHERE ticketId = ?", (ticketId,))
    existing = cur.fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Ticket mapping not found"}), 404

    now = utc_now_iso()
    cur.execute(
        "UPDATE ticket_map SET status = ?, refundId = COALESCE(?, refundId), updatedAt = ? WHERE ticketId = ?",
        (status, refund_id, now, ticketId),
    )
    cur.execute("SELECT * FROM ticket_map WHERE ticketId = ?", (ticketId,))
    row = cur.fetchone()

    cur.execute("SELECT * FROM purchases WHERE purchaseId = ?", (row["purchaseId"],))
    purchase_row = cur.fetchone()
    if purchase_row:
        cur.execute("SELECT * FROM ticket_map WHERE purchaseId = ?", (row["purchaseId"],))
        purchase_ticket_rows = cur.fetchall()
        purchase_status_value = normalize_purchase_status(purchase_ticket_rows)
        payment_status = purchase_row["paymentStatus"]
        if purchase_status_value == "REFUNDED":
            payment_status = "REFUNDED"
        elif purchase_status_value == "CANCELLED":
            payment_status = "CANCELLED"
        cur.execute(
            "UPDATE purchases SET status = ?, paymentStatus = ?, updatedAt = ? WHERE purchaseId = ?",
            (purchase_status_value, payment_status, now, row["purchaseId"]),
        )

    conn.commit()
    conn.close()

    if row["orderId"] is not None:
        update_external_order_status(row["orderId"], status)

    if status in {"REFUNDED", "CANCELLED"}:
        invalidate_ticket(ticketId)

    return jsonify(dict(row)), 200


if __name__ == "__main__":
    init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=env_flag("FLASK_DEBUG", False),
        use_reloader=env_flag("FLASK_USE_RELOADER", False),
    )
