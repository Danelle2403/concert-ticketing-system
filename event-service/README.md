# Event Service

Standalone Event Service for the concert ticketing platform. This service owns:

- event metadata
- pricing tier metadata
- seat section metadata
- event lifecycle state
- reschedule history

It does not own orders, seats, payments, tickets, refunds, or notifications.

## Stack

- Node.js
- TypeScript
- Express
- PostgreSQL
- Zod
- Jest + Supertest
- OpenAPI via Swagger UI

## Endpoints

- `GET /health`
- `GET /events`
- `GET /events/:id`
- `GET /events/:id/summary`
- `POST /events`
- `PUT /events/:id`
- `PUT /events/:id/reschedule`
- `POST /events/:id/cancel`
- `GET /docs`
- `GET /docs/openapi.json`

## Run with Docker

```bash
cd event-service
docker compose up --build
```

Service URLs:

- API: `http://localhost:5002`
- Swagger UI: `http://localhost:5002/docs`
- PostgreSQL: `localhost:5434`

## Local development

```bash
cd event-service
npm install
cp .env.example .env
npm run db:migrate
npm run dev
```

## Notes

- New events default to `DRAFT`
- Only `PUBLISHED` events are marked as purchasable
- `RESCHEDULED` and `CANCELLED` can only be set through their dedicated endpoints
- `CANCELLED` events cannot be rescheduled again
