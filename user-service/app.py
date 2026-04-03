from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import mysql.connector
import os
from pathlib import Path
import re
import secrets
import time
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
CORS(app)

DB_CONNECT_RETRIES = int(os.environ.get("DB_CONNECT_RETRIES", "15"))
DB_CONNECT_RETRY_DELAY_SECONDS = float(os.environ.get("DB_CONNECT_RETRY_DELAY_SECONDS", "1"))
DB_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5"))
AUTH_TOKEN_MAX_AGE_SECONDS = int(os.environ.get("AUTH_TOKEN_MAX_AGE_SECONDS", "604800"))
AUTH_TOKEN_SALT = "concert-hub-auth"
DEMO_STATE_PATH = Path(__file__).resolve().parents[1] / "demo" / "local_demo_state.json"
_user_auth_schema_checked = False


def load_demo_seed_data():
    with DEMO_STATE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def demo_seed_filters(demo_state):
    users = demo_state["users"]
    managed_events = demo_state["managedEvents"]
    user_tickets = demo_state["userTickets"]
    return {
        "user_ids": sorted({int(row["id"]) for row in users} | {int(row["userId"]) for row in user_tickets} | {int(row["managerId"]) for row in managed_events}),
        "emails": sorted({row["email"] for row in users}),
        "event_ids": sorted({str(row["eventId"]) for row in managed_events} | {str(row["eventId"]) for row in user_tickets}),
        "ticket_ids": sorted({str(row["ticketId"]) for row in user_tickets}),
    }


def ensure_user_auth_schema(conn):
    global _user_auth_schema_checked
    if _user_auth_schema_checked:
        return

    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = 'users'
          AND column_name = 'password_hash'
        """,
        (os.environ.get("DB_NAME", "user_db"),),
    )
    if not cursor.fetchone():
        cursor.execute(
            """
            ALTER TABLE users
            ADD COLUMN password_hash VARCHAR(255) NULL AFTER email
            """
        )
        conn.commit()
    cursor.close()
    _user_auth_schema_checked = True


def build_public_user(user):
    if not user:
        return user

    payload = dict(user)
    payload.pop("password_hash", None)
    payload["userId"] = payload.get("id")
    return payload


def normalize_email(value):
    return str(value or "").strip().lower()


def validate_password(value):
    password = str(value or "")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    return password


def get_auth_serializer():
    secret = (
        os.environ.get("AUTH_TOKEN_SECRET")
        or os.environ.get("FLASK_SECRET_KEY")
        or "concert-hub-local-dev-secret"
    )
    return URLSafeTimedSerializer(secret_key=secret)


def issue_auth_token(user):
    user_id = user.get("userId", user.get("id"))
    return get_auth_serializer().dumps(
        {
            "userId": int(user_id),
            "email": normalize_email(user.get("email")),
            "role": user.get("role"),
        },
        salt=AUTH_TOKEN_SALT,
    )


def build_auth_response(user):
    payload = build_public_user(user)
    payload["authToken"] = issue_auth_token(payload)
    return payload


def get_bearer_token():
    header = str(request.headers.get("Authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    return token or None


def authenticate_request():
    db = None
    try:
        token = get_bearer_token()
        if not token:
            return None

        claims = get_auth_serializer().loads(
            token,
            salt=AUTH_TOKEN_SALT,
            max_age=AUTH_TOKEN_MAX_AGE_SECONDS,
        )
        user_id = parse_int(claims.get("userId"), "userId")

        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        if not user:
            return None

        if normalize_email(user.get("email")) != normalize_email(claims.get("email")):
            return None

        return normalize_user(user)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    finally:
        if db:
            db.close()


# ── DATABASE CONNECTION ───────────────────────────────────────
def get_db():
    last_error = None
    for attempt in range(DB_CONNECT_RETRIES):
        try:
            return mysql.connector.connect(
                host=os.environ.get("DB_HOST", "localhost"),
                user=os.environ.get("DB_USER", "root"),
                password=os.environ.get("DB_PASSWORD", "root"),
                database=os.environ.get("DB_NAME", "user_db"),
                connection_timeout=DB_CONNECT_TIMEOUT_SECONDS,
            )
        except mysql.connector.Error as error:
            last_error = error
            if attempt == DB_CONNECT_RETRIES - 1:
                break
            time.sleep(DB_CONNECT_RETRY_DELAY_SECONDS)

    raise last_error


def connect_db():
    conn = get_db()
    ensure_user_auth_schema(conn)
    return conn


def env_flag(name, default=False):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_user(user):
    return build_public_user(user)


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
    return normalize_prefixed_id(value, ("fan",))


def normalize_ticket_id(value):
    return normalize_prefixed_id(value, ("tkt",))


def normalize_event_id(value):
    return normalize_prefixed_id(value, ("con",))


def parse_int(value, field_name):
    try:
        return int(normalize_user_id(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer")


def authenticate_user(email, password):
    db = None
    try:
        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (normalize_email(email),))
        user = cursor.fetchone()
        cursor.close()
        if not user or not user.get("password_hash"):
            return None
        if not check_password_hash(user["password_hash"], password):
            return None
        return normalize_user(user)
    finally:
        if db:
            db.close()


# ── HEALTH CHECK ──────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    db = None
    try:
        db = connect_db()
        return jsonify({"status": "User Service is running", "database": "ok"}), 200
    except Exception as error:
        return (
            jsonify(
                {
                    "status": "User Service is running",
                    "database": "error",
                    "error": str(error),
                }
            ),
            503,
        )
    finally:
        if db:
            db.close()


# ── GET ALL USERS ─────────────────────────────────────────────
@app.route("/users", methods=["GET"])
def get_all_users():
    db = None
    try:
        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users")
        users = [normalize_user(u) for u in cursor.fetchall()]
        cursor.close()
        db.close()
        return jsonify({"users": users}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── GET USER BY ID ────────────────────────────────────────────
@app.route("/user/<userId>", methods=["GET"])
def get_user(userId):
    db = None
    try:
        user_id = parse_int(userId, "userId")

        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if not user:
            return jsonify({"error": "User not found"}), 404

        return jsonify(normalize_user(user)), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/auth/register", methods=["POST"])
def register_user():
    db = None
    try:
        data = request.get_json() or {}
        name = str(data.get("name") or "").strip()
        email = normalize_email(data.get("email"))
        raw_password = str(data.get("password") or "")
        role = data.get("role", "fan")

        if not name or not email or not raw_password:
            return jsonify({"error": "Name, email, and password are required"}), 400
        password = validate_password(raw_password)
        if role not in {"fan", "manager"}:
            return jsonify({"error": "Role must be fan or manager"}), 400

        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing = cursor.fetchone()
        if existing:
            return jsonify({"error": "Email already registered"}), 409

        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            (name, email, generate_password_hash(password), role),
        )
        db.commit()
        new_id = cursor.lastrowid
        cursor.execute("SELECT * FROM users WHERE id = %s", (new_id,))
        user = cursor.fetchone()
        cursor.close()
        return jsonify(build_auth_response(user)), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": str(error)}), 500
    finally:
        if db:
            db.close()


@app.route("/auth/login", methods=["POST"])
def login_user():
    try:
        data = request.get_json() or {}
        email = normalize_email(data.get("email"))
        password = str(data.get("password") or "")
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        user = authenticate_user(email, password)
        if not user:
            return jsonify({"error": "Invalid email or password"}), 401
        return jsonify(build_auth_response(user)), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@app.route("/auth/me", methods=["GET"])
def auth_me():
    try:
        user = authenticate_request()
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        return jsonify(user), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 500


# ── CREATE NEW USER ───────────────────────────────────────────
@app.route("/user/new", methods=["POST"])
def create_user():
    db = None
    try:
        data = request.get_json() or {}
        name = str(data.get("name") or "").strip()
        email = normalize_email(data.get("email"))
        role = data.get("role", "fan")
        password = str(data.get("password") or "")

        if not name or not email:
            return jsonify({"error": "Name and email are required"}), 400

        db = connect_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing = cursor.fetchone()
        if existing:
            return jsonify({"error": "Email already registered"}), 409

        password_hash = generate_password_hash(password) if password else generate_password_hash(
            secrets.token_urlsafe(24)
        )
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            (name, email, password_hash, role),
        )
        db.commit()
        new_id = cursor.lastrowid

        cursor.execute("SELECT * FROM users WHERE id = %s", (new_id,))
        new_user = cursor.fetchone()
        cursor.close()
        db.close()

        return jsonify(normalize_user(new_user)), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── INTERNAL: SEED DEFAULT USERS/EVENTS ──────────────────────
def reset_demo_state(full_reset=False):
    db = None
    try:
        demo_state = load_demo_seed_data()
        users = demo_state["users"]
        managed_events = demo_state["managedEvents"]
        user_tickets = demo_state["userTickets"]
        filters = demo_seed_filters(demo_state)
        db = connect_db()
        cursor = db.cursor()
        if full_reset:
            cursor.execute("DELETE FROM user_tickets")
            cursor.execute("DELETE FROM managed_events")
            cursor.execute("DELETE FROM users")
        else:
            ticket_placeholders = ", ".join(["%s"] * len(filters["ticket_ids"]))
            event_placeholders = ", ".join(["%s"] * len(filters["event_ids"]))
            user_placeholders = ", ".join(["%s"] * len(filters["user_ids"]))
            email_placeholders = ", ".join(["%s"] * len(filters["emails"]))

            cursor.execute(
                f"""
                DELETE FROM user_tickets
                WHERE ticketId IN ({ticket_placeholders})
                   OR eventId IN ({event_placeholders})
                   OR userId IN ({user_placeholders})
                """,
                tuple(filters["ticket_ids"] + filters["event_ids"] + filters["user_ids"]),
            )
            cursor.execute(
                f"""
                DELETE FROM managed_events
                WHERE eventId IN ({event_placeholders})
                """,
                tuple(filters["event_ids"]),
            )
            cursor.execute(
                f"""
                DELETE FROM users
                WHERE id IN ({user_placeholders})
                   OR email IN ({email_placeholders})
                """,
                tuple(filters["user_ids"] + filters["emails"]),
            )

        for user in users:
            cursor.execute(
                "INSERT INTO users (id, name, email, password_hash, role) VALUES (%s, %s, %s, %s, %s)",
                (
                    user["id"],
                    user["name"],
                    normalize_email(user["email"]),
                    generate_password_hash(validate_password(user["password"])),
                    user["role"],
                ),
            )
        for event in managed_events:
            cursor.execute(
                """
                INSERT INTO managed_events (id, managerId, eventId, name, venue, date, price, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event["id"],
                    event["managerId"],
                    str(event["eventId"]),
                    event["name"],
                    event["venue"],
                    event["date"],
                    event["price"],
                    event["status"],
                ),
            )
        for ticket in user_tickets:
            cursor.execute(
                """
                INSERT INTO user_tickets (id, userId, ticketId, eventId, eventName, venue, date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ticket["id"],
                    ticket["userId"],
                    str(ticket["ticketId"]),
                    str(ticket["eventId"]),
                    ticket["eventName"],
                    ticket["venue"],
                    ticket["date"],
                    ticket["status"],
                ),
            )
        db.commit()
        return {"status": "seeded", "userCount": len(users), "managedEventCount": len(managed_events), "ticketCount": len(user_tickets)}, 200
    except Exception as e:
        if db:
            db.rollback()
        return {"error": str(e)}, 500
    finally:
        if db:
            db.close()


@app.route("/user/seed", methods=["POST"])
def seed_defaults():
    payload, status = reset_demo_state(full_reset=False)
    return jsonify(payload), status


@app.route("/user/admin/reset-demo", methods=["POST"])
def reset_demo_defaults():
    payload, status = reset_demo_state(full_reset=True)
    return jsonify(payload), status


# ── GET TICKETS/EVENTS FOR A FAN ──────────────────────────────
@app.route("/user/events", methods=["GET"])
def get_user_events():
    db = None
    try:
        user_id_raw = request.args.get("userId")
        if not user_id_raw:
            return jsonify({"error": "userId is required"}), 400

        user_id = parse_int(user_id_raw, "userId")

        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_tickets WHERE userId = %s", (user_id,))
        events = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"events": events}), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── GET EVENTS MANAGED BY AN EVENT MANAGER ───────────────────
@app.route("/user/managing", methods=["GET"])
def get_managing_events():
    db = None
    try:
        user_id_raw = request.args.get("userId")
        if not user_id_raw:
            return jsonify({"error": "userId is required"}), 400

        user_id = parse_int(user_id_raw, "userId")

        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM managed_events WHERE managerId = %s", (user_id,))
        events = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"events": events}), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── INTERNAL: UPSERT USER TICKET ──────────────────────────────
@app.route("/user/tickets/add", methods=["POST"])
def add_user_ticket():
    db = None
    try:
        data = request.get_json() or {}

        user_id = parse_int(data.get("userId"), "userId")
        ticket_id = normalize_ticket_id(data.get("ticketId"))
        event_id = normalize_event_id(data.get("eventId"))
        event_name = data.get("eventName")
        venue = data.get("venue")
        date = data.get("date")
        status = data.get("status", "active")

        if not ticket_id or not event_id:
            return jsonify({"error": "ticketId and eventId are required"}), 400

        db = connect_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT id FROM user_tickets WHERE ticketId = %s", (ticket_id,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """
                UPDATE user_tickets
                SET userId = %s, eventId = %s, eventName = %s, venue = %s, date = %s, status = %s
                WHERE ticketId = %s
                """,
                (user_id, event_id, event_name, venue, date, status, ticket_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO user_tickets (userId, ticketId, eventId, eventName, venue, date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, ticket_id, event_id, event_name, venue, date, status),
            )

        db.commit()
        cursor.execute("SELECT * FROM user_tickets WHERE ticketId = %s", (ticket_id,))
        ticket = cursor.fetchone()
        cursor.close()
        db.close()
        return jsonify(ticket), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── INTERNAL: GET ONE TICKET ─────────────────────────────────
@app.route("/user/ticket/<ticketId>", methods=["GET"])
def get_ticket(ticketId):
    db = None
    try:
        ticketId = normalize_ticket_id(ticketId)
        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_tickets WHERE ticketId = %s", (ticketId,))
        ticket = cursor.fetchone()
        cursor.close()
        db.close()

        if not ticket:
            return jsonify({"error": "Ticket not found"}), 404

        return jsonify(ticket), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── INTERNAL: UPDATE TICKET STATUS ───────────────────────────
@app.route("/user/ticket/<ticketId>/status", methods=["POST"])
def update_ticket_status(ticketId):
    db = None
    try:
        ticketId = normalize_ticket_id(ticketId)
        data = request.get_json() or {}
        status = data.get("status")
        if not status:
            return jsonify({"error": "status is required"}), 400

        db = connect_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "UPDATE user_tickets SET status = %s WHERE ticketId = %s",
            (status, ticketId),
        )
        if cursor.rowcount == 0:
            db.rollback()
            return jsonify({"error": "Ticket not found"}), 404

        db.commit()
        cursor.execute("SELECT * FROM user_tickets WHERE ticketId = %s", (ticketId,))
        ticket = cursor.fetchone()
        cursor.close()
        db.close()
        return jsonify(ticket), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── INTERNAL: GET TICKETS BY EVENT ───────────────────────────
@app.route("/user/tickets/by-event/<eventId>", methods=["GET"])
def get_tickets_by_event(eventId):
    db = None
    try:
        eventId = normalize_event_id(eventId)
        status = request.args.get("status")

        db = connect_db()
        cursor = db.cursor(dictionary=True)
        if status:
            cursor.execute(
                "SELECT * FROM user_tickets WHERE eventId = %s AND status = %s",
                (eventId, status),
            )
        else:
            cursor.execute("SELECT * FROM user_tickets WHERE eventId = %s", (eventId,))

        tickets = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"tickets": tickets}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── INTERNAL: UPDATE MANAGED EVENT ───────────────────────────
@app.route("/user/managed/<eventId>", methods=["PUT"])
def update_managed_event(eventId):
    db = None
    try:
        eventId = normalize_event_id(eventId)
        data = request.get_json() or {}

        db = connect_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT * FROM managed_events WHERE eventId = %s", (eventId,))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({"error": "Managed event not found"}), 404

        name = data.get("name", existing.get("name"))
        venue = data.get("venue", existing.get("venue"))
        date = data.get("date", existing.get("date"))
        price = data.get("price", existing.get("price"))
        status = data.get("status", existing.get("status"))

        cursor.execute(
            """
            UPDATE managed_events
            SET name = %s, venue = %s, date = %s, price = %s, status = %s
            WHERE eventId = %s
            """,
            (name, venue, date, price, status, eventId),
        )
        db.commit()

        cursor.execute("SELECT * FROM managed_events WHERE eventId = %s", (eventId,))
        updated = cursor.fetchone()
        cursor.close()
        db.close()

        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── INTERNAL: CANCEL MANAGED EVENT ───────────────────────────
@app.route("/user/managed/<eventId>/cancel", methods=["POST"])
def cancel_managed_event(eventId):
    db = None
    try:
        eventId = normalize_event_id(eventId)
        db = connect_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "UPDATE managed_events SET status = 'cancelled' WHERE eventId = %s",
            (eventId,),
        )
        if cursor.rowcount == 0:
            db.rollback()
            return jsonify({"error": "Managed event not found"}), 404

        db.commit()
        cursor.execute("SELECT * FROM managed_events WHERE eventId = %s", (eventId,))
        updated = cursor.fetchone()
        cursor.close()
        db.close()
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


# ── MAIN ──────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=env_flag("FLASK_DEBUG", False),
        use_reloader=env_flag("FLASK_USE_RELOADER", False),
    )
