from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import mysql.connector
import os
from pathlib import Path
import re
import time

app = Flask(__name__)
CORS(app)

DB_CONNECT_RETRIES = int(os.environ.get("DB_CONNECT_RETRIES", "15"))
DB_CONNECT_RETRY_DELAY_SECONDS = float(os.environ.get("DB_CONNECT_RETRY_DELAY_SECONDS", "1"))
DB_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5"))
DEMO_STATE_PATH = Path(__file__).resolve().parents[1] / "demo" / "local_demo_state.json"


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


def env_flag(name, default=False):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_user(user):
    if not user:
        return user
    user["userId"] = user.get("id")
    return user


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


# ── HEALTH CHECK ──────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    db = None
    try:
        db = get_db()
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
        db = get_db()
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

        db = get_db()
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


# ── CREATE NEW USER ───────────────────────────────────────────
@app.route("/user/new", methods=["POST"])
def create_user():
    db = None
    try:
        data = request.get_json() or {}
        name = data.get("name")
        email = data.get("email")
        role = data.get("role", "fan")

        if not name or not email:
            return jsonify({"error": "Name and email are required"}), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing = cursor.fetchone()
        if existing:
            return jsonify({"error": "Email already registered"}), 409

        cursor.execute(
            "INSERT INTO users (name, email, role) VALUES (%s, %s, %s)",
            (name, email, role),
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
        db = get_db()
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
                "INSERT INTO users (id, name, email, role) VALUES (%s, %s, %s, %s)",
                (user["id"], user["name"], user["email"], user["role"]),
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

        db = get_db()
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

        db = get_db()
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

        db = get_db()
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
        db = get_db()
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

        db = get_db()
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

        db = get_db()
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

        db = get_db()
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
        db = get_db()
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
