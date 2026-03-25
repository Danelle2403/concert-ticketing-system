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
        database=os.environ.get("DB_NAME", "user_db")
    )

# ── HEALTH CHECK ──────────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "User Service is running"}), 200

# ── GET ALL USERS ─────────────────────────────────────────────
# Used by: admin/internal calls
@app.route('/users', methods=['GET'])
def get_all_users():
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"users": users}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── GET USER BY ID ────────────────────────────────────────────
# Used by: login flow, other services verifying user
@app.route('/user/<userId>', methods=['GET'])
def get_user(userId):
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE userId = %s", (userId,))
        user = cursor.fetchone()
        cursor.close()
        db.close()
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify(user), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── CREATE NEW USER ───────────────────────────────────────────
# Used by: registration flow
@app.route('/user/new', methods=['POST'])
def create_user():
    try:
        data = request.get_json()
        name = data.get("name")
        email = data.get("email")
        role = data.get("role", "fan")  # default role is fan

        if not name or not email:
            return jsonify({"error": "Name and email are required"}), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Check if email already exists
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing = cursor.fetchone()
        if existing:
            return jsonify({"error": "Email already registered"}), 409

        cursor.execute(
            "INSERT INTO users (name, email, role) VALUES (%s, %s, %s)",
            (name, email, role)
        )
        db.commit()
        new_id = cursor.lastrowid

        cursor.execute("SELECT * FROM users WHERE id = %s", (new_id,))
        new_user = cursor.fetchone()
        cursor.close()
        db.close()

        return jsonify(new_user), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── GET TICKETS/EVENTS FOR A FAN ──────────────────────────────
# Used by: request-refund.html to show fan's purchased tickets
@app.route('/user/events', methods=['GET'])
def get_user_events():
    try:
        userId = request.args.get("userId")
        if not userId:
            return jsonify({"error": "userId is required"}), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM user_tickets WHERE id = %s",
            (userId,)
        )
        events = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"events": events}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── GET EVENTS MANAGED BY AN EVENT MANAGER ───────────────────
# Used by: manage-event.html to show manager's concerts
@app.route('/user/managing', methods=['GET'])
def get_managing_events():
    try:
        userId = request.args.get("userId")
        if not userId:
            return jsonify({"error": "userId is required"}), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM managed_events WHERE managerId = %s",
            (userId,)
        )
        events = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify({"events": events}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── MAIN ──────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
