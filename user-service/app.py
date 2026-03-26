from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
import os

app = Flask(__name__)
CORS(app)


# ── DATABASE CONNECTION ───────────────────────────────────────
def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "user_db"),
    )


def normalize_user(user):
    if not user:
        return user
    user["userId"] = user.get("id")
    return user


def parse_int(value, field_name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer")


# ── HEALTH CHECK ──────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "User Service is running"}), 200


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
@app.route("/user/seed", methods=["POST"])
def seed_defaults():
    db = None
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO users (id, name, email, role)
            VALUES
              (1, 'Alice Fan', 'fan@example.com', 'fan'),
              (2, 'Maya Manager', 'manager@example.com', 'manager')
            ON DUPLICATE KEY UPDATE
              name = VALUES(name),
              role = VALUES(role)
            """
        )
        cursor.execute(
            "DELETE FROM managed_events WHERE managerId = 2 AND eventId IN ('EVT1001', 'EVT1002')"
        )
        cursor.execute(
            """
            INSERT INTO managed_events (managerId, eventId, name, venue, date, price, status)
            VALUES
              (2, 'EVT1001', 'The Midnight World Tour', 'Marina Bay Sands, Singapore', '2026-08-15', 88.00, 'active'),
              (2, 'EVT1002', 'Neon Bloom Live', 'Singapore Indoor Stadium', '2026-09-22', 98.00, 'active')
            """
        )
        db.commit()
        cursor.close()
        db.close()
        return jsonify({"status": "seeded"}), 200
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


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
        ticket_id = data.get("ticketId")
        event_id = data.get("eventId")
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
    app.run(host="0.0.0.0", port=5000, debug=True)
