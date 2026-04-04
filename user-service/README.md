# User Service

Atomic Flask service for user records, user ticket records, and manager-owned event links.

## What it does

- stores fan and manager users
- authenticates email/password logins and issues JWT bearer tokens
- stores fan ticket rows used by notification, purchase, and refund flows
- stores manager event links used by manager-facing composites
- normalizes prefixed IDs from external services like `fan-001`, `tkt-002`, and `con-001`
- seeds local demo rows that align with the current external OrderService demo orders

## Endpoints

- `GET /health`
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
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

Default demo credentials after reset:

- `fan@example.com / Concert123!`
- `fan2@example.com / Concert123!`
- `manager@example.com / Concert123!`

## Run

Public auth and account routes are exposed through Kong:

- `http://localhost:8000/auth`
- `http://localhost:8000/user/events`
- `http://localhost:8000/user/managing`

Direct port `http://localhost:5001` is for internal calls, health checks, demo reset, and debugging.

Auth model:

- `POST /auth/register` and `POST /auth/login` are public
- `GET /auth/me`, `GET /user/events`, and `GET /user/managing` expect `Authorization: Bearer <jwt>`
- internal helper routes like `/users`, `/user/seed`, and ticket-management endpoints require `X-Internal-Service-Token`

## Local tests

```bash
cd user-service
../.venv/bin/python -m pytest -q
```
