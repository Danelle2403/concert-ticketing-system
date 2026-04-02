# User Service

Atomic Flask service for user records, user ticket records, and manager-owned event links.

## What it does

- stores fan and manager users
- stores fan ticket rows used by notification, purchase, and refund flows
- stores manager event links used by manager-facing composites
- normalizes prefixed IDs from external services like `fan-001`, `tkt-002`, and `con-001`
- seeds local demo rows that align with the current external OrderService demo orders

## Endpoints

- `GET /health`
- `GET /users`
- `GET /user/<userId>`
- `POST /user/new`
- `POST /user/seed`
- `GET /user/events?userId=<userId>`
- `GET /user/managing?userId=<userId>`
- `POST /user/tickets/add`
- `GET /user/ticket/<ticketId>`
- `POST /user/ticket/<ticketId>/status`
- `GET /user/tickets/by-event/<eventId>`
- `PUT /user/managed/<eventId>`
- `POST /user/managed/<eventId>/cancel`

## Demo data

`POST /user/seed` restores the local user and ticket rows used by the current order-aligned flow, including:

- fan users `1`, `2`, `3`, and `123`
- manager user `99`
- demo managed events `1`, `2`, `789`, `EVT1001`, and `EVT1002`
- demo ticket rows for ticket IDs `1`, `2`, `3`, and `456`

## Run

Browser traffic should go through Kong at `http://localhost:8000/user`.
The direct port `http://localhost:5001` is for internal calls, health checks, and debugging.

## Local tests

```bash
cd user-service
../.venv/bin/python -m pytest -q
```
