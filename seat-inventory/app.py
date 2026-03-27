from datetime import datetime, timedelta
import os
import time
import uuid

from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector

app = Flask(__name__)
CORS(app)

DEFAULT_HOLD_TTL_SECONDS = int(os.environ.get("DEFAULT_HOLD_TTL_SECONDS", "300"))
MAX_HOLD_TTL_SECONDS = int(os.environ.get("MAX_HOLD_TTL_SECONDS", "1800"))


def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "seat_inventory_db"),
    )


def release_expired_holds(cursor, event_id=None, seat_category=None, hold_id=None):
    query = """
        SELECT holdId, eventId, seatCategory, quantity
        FROM seat_holds
        WHERE status = 'HELD' AND expiresAt <= UTC_TIMESTAMP()
    """
    params = []

    if hold_id:
        query += " AND holdId = %s"
        params.append(hold_id)
    if event_id:
        query += " AND eventId = %s"
        params.append(event_id)
    if seat_category:
        query += " AND seatCategory = %s"
        params.append(seat_category)

    query += " ORDER BY eventId, seatCategory, holdId FOR UPDATE"
    cursor.execute(query, tuple(params))
    expired_holds = cursor.fetchall()

    for hold in expired_holds:
        cursor.execute(
            """
            UPDATE seat_inventory
            SET availableSeats = availableSeats + %s,
                updatedAt = UTC_TIMESTAMP()
            WHERE eventId = %s AND seatCategory = %s
            """,
            (hold["quantity"], hold["eventId"], hold["seatCategory"]),
        )

        cursor.execute(
            """
            UPDATE seat_holds
            SET status = 'EXPIRED',
                releasedAt = UTC_TIMESTAMP(),
                releaseReason = 'HOLD_EXPIRED',
                updatedAt = UTC_TIMESTAMP()
            WHERE holdId = %s
            """,
            (hold["holdId"],),
        )

    return len(expired_holds)


def parse_positive_int(value, field_name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer")

    if parsed <= 0:
        raise ValueError(f"{field_name} must be > 0")

    return parsed


def parse_non_negative_int(value, field_name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer")

    if parsed < 0:
        raise ValueError(f"{field_name} must be >= 0")

    return parsed


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Seat Inventory Service is running"}), 200


@app.route("/inventory", methods=["GET"])
def get_all_inventory():
    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        db.start_transaction()
        release_expired_holds(cursor)

        cursor.execute(
            """
            SELECT eventId, seatCategory, totalSeats, availableSeats, updatedAt
            FROM seat_inventory
            ORDER BY eventId, seatCategory
            """
        )
        rows = cursor.fetchall()
        db.commit()
        return jsonify({"inventory": rows}), 200
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/inventory/<event_id>", methods=["GET"])
def get_inventory_by_event(event_id):
    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        db.start_transaction()
        release_expired_holds(cursor, event_id=event_id)

        cursor.execute(
            """
            SELECT eventId, seatCategory, totalSeats, availableSeats, updatedAt
            FROM seat_inventory
            WHERE eventId = %s
            ORDER BY seatCategory
            """,
            (event_id,),
        )
        rows = cursor.fetchall()
        db.commit()

        if not rows:
            return jsonify({"error": "Event not found"}), 404

        return jsonify({"eventId": event_id, "inventory": rows}), 200
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/inventory/<event_id>/<seat_category>", methods=["GET"])
def get_inventory_by_category(event_id, seat_category):
    quantity_raw = request.args.get("quantity", "1")

    try:
        quantity = parse_positive_int(quantity_raw, "quantity")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        db.start_transaction()
        release_expired_holds(cursor, event_id=event_id, seat_category=seat_category)

        cursor.execute(
            """
            SELECT eventId, seatCategory, totalSeats, availableSeats, updatedAt
            FROM seat_inventory
            WHERE eventId = %s AND seatCategory = %s
            FOR UPDATE
            """,
            (event_id, seat_category),
        )
        row = cursor.fetchone()
        db.commit()

        if not row:
            return jsonify({"error": "Seat category not found for event"}), 404

        row["requestedQuantity"] = quantity
        row["isAvailable"] = row["availableSeats"] >= quantity
        return jsonify(row), 200
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/inventory/admin/create", methods=["POST"])
def create_inventory_for_event():
    data = request.get_json(silent=True) or {}
    event_id = str(data.get("eventId", "")).strip()
    seat_categories = data.get("seatCategories")

    if not event_id:
        return jsonify({"error": "eventId is required"}), 400

    if not isinstance(seat_categories, list) or not seat_categories:
        return jsonify({"error": "seatCategories must be a non-empty array"}), 400

    parsed_rows = []
    seen_categories = set()

    try:
        for index, seat_row in enumerate(seat_categories):
            if not isinstance(seat_row, dict):
                raise ValueError(f"seatCategories[{index}] must be an object")

            seat_category = str(seat_row.get("seatCategory", "")).strip()
            if not seat_category:
                raise ValueError(f"seatCategories[{index}].seatCategory is required")

            normalized_category = seat_category.upper()
            if normalized_category in seen_categories:
                raise ValueError("seatCategories must not contain duplicate seatCategory values")
            seen_categories.add(normalized_category)

            total_seats = parse_positive_int(
                seat_row.get("totalSeats"), f"seatCategories[{index}].totalSeats"
            )
            available_seats = parse_non_negative_int(
                seat_row.get("availableSeats", total_seats),
                f"seatCategories[{index}].availableSeats",
            )

            if available_seats > total_seats:
                raise ValueError(
                    f"seatCategories[{index}].availableSeats must be <= totalSeats"
                )

            parsed_rows.append(
                {
                    "seatCategory": normalized_category,
                    "totalSeats": total_seats,
                    "availableSeats": available_seats,
                }
            )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        db.start_transaction()
        release_expired_holds(cursor, event_id=event_id)

        cursor.execute(
            """
            SELECT COUNT(*) AS rowCount
            FROM seat_inventory
            WHERE eventId = %s
            FOR UPDATE
            """,
            (event_id,),
        )
        existing = cursor.fetchone()
        if existing and existing["rowCount"] > 0:
            db.rollback()
            return (
                jsonify(
                    {
                        "error": "Inventory already exists for this eventId",
                        "eventId": event_id,
                    }
                ),
                409,
            )

        for row in parsed_rows:
            cursor.execute(
                """
                INSERT INTO seat_inventory
                (eventId, seatCategory, totalSeats, availableSeats, createdAt, updatedAt)
                VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP())
                """,
                (
                    event_id,
                    row["seatCategory"],
                    row["totalSeats"],
                    row["availableSeats"],
                ),
            )

        cursor.execute(
            """
            SELECT eventId, seatCategory, totalSeats, availableSeats, updatedAt
            FROM seat_inventory
            WHERE eventId = %s
            ORDER BY seatCategory
            """,
            (event_id,),
        )
        created_rows = cursor.fetchall()
        db.commit()

        return (
            jsonify(
                {
                    "eventId": event_id,
                    "inventory": created_rows,
                    "status": "CREATED",
                }
            ),
            201,
        )
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/inventory/hold", methods=["POST"])
def hold_seats():
    data = request.get_json(silent=True) or {}

    event_id = data.get("eventId")
    seat_category = data.get("seatCategory")

    if not event_id or not seat_category:
        return jsonify({"error": "eventId and seatCategory are required"}), 400

    try:
        quantity = parse_positive_int(data.get("quantity", 1), "quantity")
        ttl_seconds = parse_positive_int(
            data.get("ttlSeconds", DEFAULT_HOLD_TTL_SECONDS), "ttlSeconds"
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if ttl_seconds > MAX_HOLD_TTL_SECONDS:
        return jsonify({"error": f"ttlSeconds must be <= {MAX_HOLD_TTL_SECONDS}"}), 400

    max_retries = 3
    for attempt in range(max_retries):
        db = None
        try:
            db = get_db()
            cursor = db.cursor(dictionary=True)
            db.start_transaction()
            release_expired_holds(cursor, event_id=event_id, seat_category=seat_category)

            cursor.execute(
                """
                SELECT eventId, seatCategory, totalSeats, availableSeats
                FROM seat_inventory
                WHERE eventId = %s AND seatCategory = %s
                FOR UPDATE
                """,
                (event_id, seat_category),
            )
            inventory = cursor.fetchone()

            if not inventory:
                db.rollback()
                return jsonify({"error": "Seat category not found for event"}), 404

            if inventory["availableSeats"] < quantity:
                db.rollback()
                return (
                    jsonify(
                        {
                            "error": "Sold Out",
                            "requestedQuantity": quantity,
                            "availableSeats": inventory["availableSeats"],
                        }
                    ),
                    409,
                )

            hold_id = str(uuid.uuid4())
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

            cursor.execute(
                """
                UPDATE seat_inventory
                SET availableSeats = availableSeats - %s,
                    updatedAt = UTC_TIMESTAMP()
                WHERE eventId = %s AND seatCategory = %s
                """,
                (quantity, event_id, seat_category),
            )

            cursor.execute(
                """
                INSERT INTO seat_holds
                (holdId, eventId, seatCategory, quantity, status, expiresAt, createdAt, updatedAt)
                VALUES (%s, %s, %s, %s, 'HELD', %s, UTC_TIMESTAMP(), UTC_TIMESTAMP())
                """,
                (hold_id, event_id, seat_category, quantity, expires_at),
            )

            db.commit()

            return (
                jsonify(
                    {
                        "holdId": hold_id,
                        "eventId": event_id,
                        "seatCategory": seat_category,
                        "quantity": quantity,
                        "status": "HELD",
                        "expiresAt": expires_at.isoformat() + "Z",
                    }
                ),
                201,
            )
        except mysql.connector.Error as e:
            if db:
                db.rollback()
            # Retry transient lock conflicts under parallel traffic.
            if e.errno in (1205, 1213) and attempt < max_retries - 1:
                time.sleep(0.05 * (2 ** attempt))
                continue
            return jsonify({"error": str(e)}), 500
        except Exception as e:
            if db:
                db.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            if db:
                db.close()


@app.route("/inventory/confirm", methods=["POST"])
def confirm_hold():
    data = request.get_json(silent=True) or {}
    hold_id = data.get("holdId")

    if not hold_id:
        return jsonify({"error": "holdId is required"}), 400

    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        db.start_transaction()
        release_expired_holds(cursor, hold_id=hold_id)

        cursor.execute(
            """
            SELECT holdId, eventId, seatCategory, quantity, status, expiresAt
            FROM seat_holds
            WHERE holdId = %s
            FOR UPDATE
            """,
            (hold_id,),
        )
        hold = cursor.fetchone()

        if not hold:
            db.rollback()
            return jsonify({"error": "Hold not found"}), 404

        if hold["status"] == "CONFIRMED":
            db.commit()
            return jsonify({"holdId": hold_id, "status": "CONFIRMED"}), 200

        if hold["status"] in ("RELEASED", "EXPIRED"):
            db.commit()
            return (
                jsonify(
                    {
                        "error": f"Cannot confirm hold in {hold['status']} state",
                        "holdId": hold_id,
                        "status": hold["status"],
                    }
                ),
                409,
            )

        cursor.execute(
            """
            UPDATE seat_holds
            SET status = 'CONFIRMED',
                confirmedAt = UTC_TIMESTAMP(),
                updatedAt = UTC_TIMESTAMP()
            WHERE holdId = %s
            """,
            (hold_id,),
        )

        db.commit()
        return jsonify({"holdId": hold_id, "status": "CONFIRMED"}), 200
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/inventory/release", methods=["POST"])
def release_hold():
    data = request.get_json(silent=True) or {}
    hold_id = data.get("holdId")
    release_reason = data.get("reason", "MANUAL_RELEASE")
    allow_confirmed_release = bool(data.get("allowConfirmedRelease", False))

    if not hold_id:
        return jsonify({"error": "holdId is required"}), 400

    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        db.start_transaction()
        release_expired_holds(cursor, hold_id=hold_id)

        cursor.execute(
            """
            SELECT holdId, eventId, seatCategory, quantity, status
            FROM seat_holds
            WHERE holdId = %s
            FOR UPDATE
            """,
            (hold_id,),
        )
        hold = cursor.fetchone()

        if not hold:
            db.rollback()
            return jsonify({"error": "Hold not found"}), 404

        if hold["status"] == "HELD" or (
            hold["status"] == "CONFIRMED" and allow_confirmed_release
        ):
            cursor.execute(
                """
                UPDATE seat_inventory
                SET availableSeats = availableSeats + %s,
                    updatedAt = UTC_TIMESTAMP()
                WHERE eventId = %s AND seatCategory = %s
                """,
                (hold["quantity"], hold["eventId"], hold["seatCategory"]),
            )

            cursor.execute(
                """
                UPDATE seat_holds
                SET status = 'RELEASED',
                    releasedAt = UTC_TIMESTAMP(),
                    releaseReason = %s,
                    updatedAt = UTC_TIMESTAMP()
                WHERE holdId = %s
                """,
                (release_reason, hold_id),
            )

            db.commit()
            return jsonify({"holdId": hold_id, "status": "RELEASED"}), 200

        if hold["status"] == "CONFIRMED":
            db.commit()
            return (
                jsonify(
                    {
                        "error": (
                            "Confirmed holds require allowConfirmedRelease=true "
                            "for refund/cancellation release"
                        ),
                        "holdId": hold_id,
                    }
                ),
                409,
            )

        db.commit()
        return jsonify({"holdId": hold_id, "status": hold["status"]}), 200
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


@app.route("/inventory/holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    db = None
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        db.start_transaction()
        release_expired_holds(cursor, hold_id=hold_id)

        cursor.execute(
            """
            SELECT holdId, eventId, seatCategory, quantity, status,
                   expiresAt, confirmedAt, releasedAt, releaseReason, createdAt, updatedAt
            FROM seat_holds
            WHERE holdId = %s
            """,
            (hold_id,),
        )
        hold = cursor.fetchone()
        db.commit()

        if not hold:
            return jsonify({"error": "Hold not found"}), 404

        return jsonify(hold), 200
    except Exception as e:
        if db:
            db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if db:
            db.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
