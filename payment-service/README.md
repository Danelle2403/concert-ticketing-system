# Payment Service

Standalone Stripe wrapper for payment intent and refund operations.

## What it does

- creates Stripe PaymentIntents for future purchase integration
- retrieves Stripe PaymentIntent status/details
- creates Stripe refunds from either a `chargeId` or a `paymentIntentId`
- returns a clear `STRIPE_NOT_CONFIGURED` error when Stripe keys are missing

## Endpoints

- `GET /health`
- `POST /payments/intents`
- `GET /payments/intents/:paymentIntentId`
- `POST /refunds`

## Environment variables

- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`

## Run

The service is wired into the repo root `docker-compose.yml` and listens on `http://localhost:5014`.

## Example requests

Create a payment intent:

```bash
curl -X POST http://localhost:5014/payments/intents \
  -H 'Content-Type: application/json' \
  -d '{"amount":12800,"currency":"sgd","description":"Concert purchase","receiptEmail":"fan@example.com"}'
```

Create a refund from a PaymentIntent:

```bash
curl -X POST http://localhost:5014/refunds \
  -H 'Content-Type: application/json' \
  -d '{"paymentIntentId":"pi_123","amount":12800,"reason":"requested_by_customer"}'
```

## Local tests

```bash
cd payment-service
pytest
```
