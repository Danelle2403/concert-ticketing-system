from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as payment_app


def test_create_payment_intent_success(monkeypatch):
    flask_app = payment_app.create_app({"TESTING": True, "STRIPE_SECRET_KEY": "sk_test_123"})
    client = flask_app.test_client()
    captured = {}

    def _create_intent(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "id": "pi_123",
            "client_secret": "pi_123_secret_abc",
            "status": "requires_payment_method",
            "amount": kwargs["amount"],
            "currency": kwargs["currency"],
        }

    monkeypatch.setattr(payment_app.stripe.PaymentIntent, "create", _create_intent)

    response = client.post(
        "/payments/intents",
        json={
            "amount": 12800,
            "currency": "sgd",
            "description": "Concert purchase",
            "receiptEmail": "fan@example.com",
            "metadata": {"eventId": "evt-123"},
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["data"]["paymentIntentId"] == "pi_123"
    assert payload["data"]["amount"] == 12800
    assert payload["data"]["currency"] == "sgd"
    assert captured["kwargs"]["automatic_payment_methods"] == {
        "enabled": True,
        "allow_redirects": "never",
    }


def test_create_refund_via_payment_intent_success(monkeypatch):
    flask_app = payment_app.create_app({"TESTING": True, "STRIPE_SECRET_KEY": "sk_test_123"})
    client = flask_app.test_client()

    monkeypatch.setattr(
        payment_app.stripe.PaymentIntent,
        "retrieve",
        lambda payment_intent_id: {
            "id": payment_intent_id,
            "latest_charge": "ch_123",
        },
    )
    monkeypatch.setattr(
        payment_app.stripe.Refund,
        "create",
        lambda **kwargs: {
            "id": "re_123",
            "charge": kwargs["charge"],
            "status": "succeeded",
            "amount": kwargs.get("amount"),
            "currency": "sgd",
        },
    )

    response = client.post(
        "/refunds",
        json={
            "paymentIntentId": "pi_123",
            "amount": 12800,
            "reason": "requested_by_customer",
            "metadata": {"ticketId": "TKT-123"},
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["data"]["refundId"] == "re_123"
    assert payload["data"]["chargeId"] == "ch_123"
    assert payload["data"]["paymentIntentId"] == "pi_123"


def test_health_reports_unconfigured_state():
    flask_app = payment_app.create_app({"TESTING": True, "STRIPE_SECRET_KEY": ""})
    client = flask_app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["stripeConfigured"] is False
