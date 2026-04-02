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
- `event.cancelled`: sends a cancellation email with cancellation reason and planned Stripe refund guidance

## Endpoints

- `GET /health`
- `POST /notifications/events`
- `POST /notifications/event-updated`
- `POST /notifications/event-cancelled`

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

The service is intended to run through the repo root `docker-compose.yml` and listens on `http://localhost:5013`.

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
