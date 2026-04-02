# Notification Service

SendGrid-backed notification wrapper that consumes RabbitMQ fanout events and emails ticket holders.

## What it does

- consumes `event.updated` and `event.cancelled` messages from RabbitMQ
- looks up active ticket holders for the event through User Service
- resolves recipient emails through User Service
- sends emails through SendGrid when configured
- falls back to `log_only` mode when SendGrid credentials are missing

## Message behavior

- `event.updated`: sends an update email with changed event details and refund-request guidance
- `event.cancelled`: sends a cancellation email with cancellation reason and automatic Stripe refund guidance
- `purchase.confirmed`: sends a purchase confirmation email with receipt details
- `refund.success`: sends a refund confirmation email to the fan
- `refund.failure`: sends an alert email so the fan and manager can resolve a failed refund

## Endpoints

- `GET /health`
- `POST /notifications/events`
- `POST /notifications/event-updated`
- `POST /notifications/event-cancelled`
- `POST /notifications/purchase-confirmation`
- `POST /notifications/refund-success`
- `POST /notifications/refund-failure`

## Environment variables

- `USER_SERVICE_URL`
- `RABBITMQ_URL`
- `NOTIFICATION_EXCHANGE`
- `NOTIFICATION_QUEUE`
- `NOTIFICATION_ROUTING_KEYS`
- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`
- `REQUEST_TIMEOUT_SECONDS`

## Run

This service is an internal dependency behind the composites and RabbitMQ consumer.
The repo root stack exposes it on `http://localhost:5013` for health checks and debugging.

## Local tests

```bash
cd notification-service
../.venv/bin/python -m pytest -q
```

## Smoke test

The included smoke test can publish either update or cancellation notifications:

```bash
python smoke_test.py --mode rabbitmq --event-type event.updated --email you@example.com
python smoke_test.py --mode rabbitmq --event-type event.cancelled --email you@example.com
```
