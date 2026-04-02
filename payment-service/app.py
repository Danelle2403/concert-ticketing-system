import os

from flask import Flask, jsonify, request
from flask_cors import CORS
import stripe


def env_flag(name, default=False):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def build_success(data, status=200, message=None):
    payload = {"data": data}
    if message:
        payload["message"] = message
    return jsonify(payload), status


def build_error(status, code, message, details=None):
    return (
        jsonify(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details,
                }
            }
        ),
        status,
    )


def normalize_currency(value):
    currency = str(value or "").strip().lower()
    return currency or None


def read_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def create_app(test_config=None):
    app = Flask(__name__)
    CORS(app)

    app.config.update(
        STRIPE_SECRET_KEY=os.environ.get("STRIPE_SECRET_KEY", ""),
        STRIPE_PUBLISHABLE_KEY=os.environ.get("STRIPE_PUBLISHABLE_KEY", ""),
    )

    if test_config:
        app.config.update(test_config)

    stripe.api_key = app.config["STRIPE_SECRET_KEY"]

    def require_stripe():
        if not app.config["STRIPE_SECRET_KEY"]:
            return build_error(
                503,
                "STRIPE_NOT_CONFIGURED",
                "Stripe is not configured. Set STRIPE_SECRET_KEY before using the payment wrapper.",
            )
        return None

    @app.route("/health", methods=["GET"])
    def health():
        return build_success(
            {
                "status": "Payment Service is running",
                "stripeConfigured": bool(app.config["STRIPE_SECRET_KEY"]),
                "publishableKeyConfigured": bool(app.config["STRIPE_PUBLISHABLE_KEY"]),
            }
        )

    @app.route("/payments/config", methods=["GET"])
    def get_payment_config():
        return build_success(
            {
                "stripeConfigured": bool(app.config["STRIPE_SECRET_KEY"]),
                "publishableKeyConfigured": bool(app.config["STRIPE_PUBLISHABLE_KEY"]),
                "publishableKey": app.config["STRIPE_PUBLISHABLE_KEY"] or None,
            }
        )

    @app.route("/payments/intents", methods=["POST"])
    def create_payment_intent():
        stripe_error = require_stripe()
        if stripe_error:
            return stripe_error

        payload = request.get_json(silent=True) or {}

        try:
            amount = int(payload.get("amount"))
        except (TypeError, ValueError):
            return build_error(400, "VALIDATION_ERROR", "amount must be an integer in the smallest currency unit")

        if amount <= 0:
            return build_error(400, "VALIDATION_ERROR", "amount must be greater than 0")

        currency = normalize_currency(payload.get("currency"))
        if not currency or len(currency) != 3:
            return build_error(400, "VALIDATION_ERROR", "currency must be a 3-letter ISO code")

        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            return build_error(400, "VALIDATION_ERROR", "metadata must be an object")

        try:
            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                automatic_payment_methods={
                    "enabled": True,
                    "allow_redirects": "never",
                },
                description=payload.get("description"),
                metadata=metadata,
                receipt_email=payload.get("receiptEmail"),
            )
        except Exception as error:
            return build_error(502, "STRIPE_PAYMENT_INTENT_FAILED", "Stripe rejected the payment intent", str(error))

        return build_success(
            {
                "paymentIntentId": read_value(intent, "id"),
                "clientSecret": read_value(intent, "client_secret"),
                "status": read_value(intent, "status"),
                "amount": read_value(intent, "amount"),
                "currency": read_value(intent, "currency"),
            },
            status=201,
            message="Payment intent created",
        )

    @app.route("/payments/intents/<payment_intent_id>", methods=["GET"])
    def get_payment_intent(payment_intent_id):
        stripe_error = require_stripe()
        if stripe_error:
            return stripe_error

        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        except Exception as error:
            return build_error(502, "STRIPE_PAYMENT_INTENT_LOOKUP_FAILED", "Stripe lookup failed", str(error))

        return build_success(
            {
                "paymentIntentId": read_value(intent, "id"),
                "clientSecret": read_value(intent, "client_secret"),
                "status": read_value(intent, "status"),
                "amount": read_value(intent, "amount"),
                "currency": read_value(intent, "currency"),
                "latestChargeId": read_value(intent, "latest_charge"),
            }
        )

    @app.route("/refunds", methods=["POST"])
    def create_refund():
        stripe_error = require_stripe()
        if stripe_error:
            return stripe_error

        payload = request.get_json(silent=True) or {}
        charge_id = payload.get("chargeId")
        payment_intent_id = payload.get("paymentIntentId")
        amount = payload.get("amount")
        metadata = payload.get("metadata") or {}

        if not charge_id and not payment_intent_id:
            return build_error(400, "VALIDATION_ERROR", "Either chargeId or paymentIntentId is required")

        if amount is not None:
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                return build_error(400, "VALIDATION_ERROR", "amount must be an integer in the smallest currency unit")
            if amount <= 0:
                return build_error(400, "VALIDATION_ERROR", "amount must be greater than 0")

        if not isinstance(metadata, dict):
            return build_error(400, "VALIDATION_ERROR", "metadata must be an object")

        if not charge_id and payment_intent_id:
            try:
                intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            except Exception as error:
                return build_error(502, "STRIPE_PAYMENT_INTENT_LOOKUP_FAILED", "Stripe lookup failed", str(error))

            charge_id = read_value(intent, "latest_charge")
            if not charge_id:
                return build_error(
                    409,
                    "PAYMENT_INTENT_NOT_CHARGED",
                    "Stripe payment intent does not have a charge available for refund yet.",
                )

        refund_payload = {
            "charge": charge_id,
            "reason": payload.get("reason"),
            "metadata": metadata,
        }
        if amount is not None:
            refund_payload["amount"] = amount

        try:
            refund = stripe.Refund.create(**refund_payload)
        except Exception as error:
            return build_error(502, "STRIPE_REFUND_FAILED", "Stripe rejected the refund", str(error))

        return build_success(
            {
                "refundId": read_value(refund, "id"),
                "chargeId": read_value(refund, "charge"),
                "paymentIntentId": payment_intent_id,
                "status": read_value(refund, "status"),
                "amount": read_value(refund, "amount"),
                "currency": read_value(refund, "currency"),
            },
            status=201,
            message="Refund created",
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=env_flag("FLASK_DEBUG", False),
        use_reloader=env_flag("FLASK_USE_RELOADER", False),
    )
