from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
import os

app = Flask(__name__)
CORS(app)

DEMO_EVENTS = [
    ("EVT1001", "The Midnight World Tour", "Marina Bay Sands, Singapore", "2026-08-15", 88.00, "electronic", "VIP", "active"),
    ("EVT1002", "Neon Bloom Live", "Singapore Indoor Stadium", "2026-09-22", 98.00, "pop", "CAT1", "active"),
    ("EVT1003", "Wave Artist Live", "Esplanade Theatre", "2026-10-10", 78.00, "hiphop", "CAT2", "active"),
]


def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "event_db"),
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Event Service is running"}), 200


@app.route("/events", methods=["GET"])
def get_events():
    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM events WHERE status != 'deleted' ORDER BY date")
        events = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"events": events}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/events/<eventId>", methods=["GET"])
def get_event(eventId):
    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM events WHERE eventId = %s", (eventId,))
        event = cursor.fetchone()
        cursor.close()
        db.close()

        if not event:
            return jsonify({"error": "Event not found"}), 404

        return jsonify(event), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/events/<eventId>/edit", methods=["PUT"])
def edit_event(eventId):
    db = None
    try:
        data = request.get_json() or {}

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM events WHERE eventId = %s", (eventId,))
        existing = cursor.fetchone()

        if not existing:
            return jsonify({"error": "Event not found"}), 404

        name = data.get("name", existing["name"])
        venue = data.get("venue", existing["venue"])
        date = data.get("date", existing["date"])
        price = data.get("price", existing["price"])
        genre = data.get("genre", existing["genre"])

        cursor.execute(
            """
            UPDATE events
            SET name = %s, venue = %s, date = %s, price = %s, genre = %s
            WHERE eventId = %s
            """,
            (name, venue, date, price, genre, eventId),
        )
        db.commit()

        cursor.execute("SELECT * FROM events WHERE eventId = %s", (eventId,))
        updated = cursor.fetchone()
        cursor.close()
        db.close()

        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/events/<eventId>/cancel", methods=["POST"])
def cancel_event(eventId):
    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("UPDATE events SET status = 'cancelled' WHERE eventId = %s", (eventId,))

        if cursor.rowcount == 0:
            db.rollback()
            return jsonify({"error": "Event not found"}), 404

        db.commit()
        cursor.execute("SELECT * FROM events WHERE eventId = %s", (eventId,))
        updated = cursor.fetchone()
        cursor.close()
        db.close()

        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/events/reset-demo", methods=["POST"])
def reset_demo_events():
    db = None
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.executemany(
            """
            INSERT INTO events (eventId, name, venue, date, price, genre, defaultSeatCategory, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              name = VALUES(name),
              venue = VALUES(venue),
              date = VALUES(date),
              price = VALUES(price),
              genre = VALUES(genre),
              defaultSeatCategory = VALUES(defaultSeatCategory),
              status = VALUES(status),
              updated_at = CURRENT_TIMESTAMP
            """,
            DEMO_EVENTS,
        )
        db.commit()
        cursor.close()
        db.close()
        return jsonify({"status": "demo events reset", "count": len(DEMO_EVENTS)}), 200
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
