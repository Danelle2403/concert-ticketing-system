# Ticket Atomic Service

Atomic Flask microservice for ticket issuance and validation, backed by PostgreSQL.

## Quick Start

### 1. Set up PostgreSQL

You have two options:

1. Use the included standalone `docker-compose.yml`, which starts both the API and a local PostgreSQL database.
2. Point `DATABASE_URL` at any existing PostgreSQL instance.

If you want to precreate the schema manually, paste the contents of `init.sql` into your SQL tool first.

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env only if you want to override the default local Docker database URL
```

### 3. Run with Docker Compose

```bash
docker compose up --build
```

The standalone service is now live at `http://localhost:5000`.

### Root stack integration

The repo root `docker-compose.yml` also includes:

- `ticket-atomic` on `http://localhost:5002`
- `ticket-atomic-db` as its local Postgres dependency

The purchase flow is wired to use this local service in the root stack, and refund/cancel flows propagate ticket invalidation through the purchase wrapper.
This service is internal to the composites and is not intended to be called directly from the browser.

---

## API Reference

### `POST /tickets/issue`
Issue a new ticket for an event.

**Request body:**
```json
{
  "event_id": "evt_abc123",
  "seat_section": "A",
  "seat_row": "3",
  "seat_number": "14"
}
```
- `event_id` — required
- `seat_section`, `seat_row`, `seat_number` — optional

**Response `201`:**
```json
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_id": "evt_abc123",
  "seat": { "section": "A", "row": "3", "number": "14" },
  "is_valid": true,
  "issued_at": "2026-03-24T10:00:00+00:00",
  "invalidated_at": null
}
```

---

### `GET /tickets/<ticket_id>`
Fetch a single ticket by its UUID.

**Response `200`:** ticket object (same shape as above)  
**Response `404`:** ticket not found

---

### `GET /tickets/event/<event_id>`
Return all tickets for a given event.

**Response `200`:**
```json
[
  { "ticket_id": "...", "event_id": "evt_abc123", ... },
  ...
]
```

---

### `POST /tickets/<ticket_id>/invalidate`
Invalidate a ticket (one-way, irreversible).

**Response `200`:** updated ticket with `is_valid: false` and `invalidated_at` set  
**Response `409`:** ticket already invalidated  
**Response `404`:** ticket not found

---

### `GET /health`
Liveness probe that also ensures the local schema exists.

---

## Project Structure

```
ticket_atomic/
├── app.py              # Flask application (all routes)
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container image
├── docker-compose.yml  # Compose config
├── init.sql            # One-time DB schema setup
├── tests/              # Pytest coverage
└── README.md
```

## Local tests

```bash
cd ticket_atomic
../.venv/bin/python -m pytest -q
```
