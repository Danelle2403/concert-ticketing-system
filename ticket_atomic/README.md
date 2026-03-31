# 🎟️ Ticket Microservice

Atomic Flask microservice for ticket issuance and validation, backed by Supabase (Postgres).

## Quick Start

### 1. Set up Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** → paste the contents of `init.sql` → **Run**
3. Go to **Project Settings → Database → Connection string → URI** and copy it

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and paste your DATABASE_URL
```

### 3. Run with Docker Compose

```bash
docker compose up --build
```

The API is now live at `http://localhost:5000`.

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
Liveness probe — also acts as a Supabase keep-alive ping.

---

## Keeping Supabase Free Tier Alive

Supabase pauses free projects after **7 days of inactivity**.  
If you have GitHub Actions, add this workflow to ping `/health` twice a week:

```yaml
# .github/workflows/keepalive.yml
name: Supabase Keep-Alive
on:
  schedule:
    - cron: '0 0 * * 0,4'   # Every Sunday and Thursday at midnight UTC
jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - run: curl -f ${{ secrets.API_URL }}/health
```

Add `API_URL` (e.g. `https://your-deployed-service.com`) as a GitHub Actions secret.

---

## Project Structure

```
ticket-service/
├── app.py              # Flask application (all routes)
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container image
├── docker-compose.yml  # Compose config
├── .env.example        # Environment variable template
├── init.sql            # One-time DB schema setup
└── README.md
```
