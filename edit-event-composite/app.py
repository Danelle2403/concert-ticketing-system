from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import requests

app = Flask(__name__)
CORS(app)

EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL", "http://event-service:5000")
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5000")
REFUND_SERVICE_URL = os.environ.get("REFUND_SERVICE_URL", "http://refund-composite:5000")


def req_json(method, url, payload=None, timeout=8):
    res = requests.request(method, url, json=payload, timeout=timeout)
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text}
    return res.status_code, body


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Edit Event Composite is running"}), 200


@app.route("/events/<eventId>/edit", methods=["PUT"])
def edit_event(eventId):
    data = request.get_json() or {}

    code, event = req_json("PUT", f"{EVENT_SERVICE_URL}/events/{eventId}/edit", data)
    if code != 200:
        return jsonify(event), code

    req_json("PUT", f"{USER_SERVICE_URL}/user/managed/{eventId}", data)

    return jsonify(event), 200


@app.route("/events/<eventId>/cancel", methods=["POST"])
def cancel_event(eventId):
    code, event = req_json("POST", f"{EVENT_SERVICE_URL}/events/{eventId}/cancel")
    if code != 200:
        return jsonify(event), code

    req_json("POST", f"{USER_SERVICE_URL}/user/managed/{eventId}/cancel")
    refund_code, refund_result = req_json("POST", f"{REFUND_SERVICE_URL}/refunds/event/{eventId}")

    response = {
        "eventId": eventId,
        "status": "cancelled",
        "event": event,
        "refunds": refund_result,
    }

    if refund_code != 200:
        response["warning"] = "Refund batch encountered issues"

    return jsonify(response), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
