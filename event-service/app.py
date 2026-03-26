from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
import os

app = Flask(__name__)
CORS(app)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
