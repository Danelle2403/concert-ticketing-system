# Create/Edit Event Composite

Manager-only Flask orchestration service for creating, editing, and cancelling events.

## What it does

- validates the acting user through User Service
- creates or edits event metadata through Event Service
- cancels events through Event Service and returns refund-flow metadata for downstream handling
- relies on `managerId` stored in Event Service for ownership checks and manager event listing
- bootstraps Seat Inventory with the Event Service UUID by aggregating `seatSections[].capacity` per pricing tier
- validates existing Seat Inventory totals before allowing seat-configuration edits
- publishes `event.updated` and `event.cancelled` messages to RabbitMQ for the notification wrapper
- writes composite audit entries to container stdout as structured JSON

## Current limitation

Seat Inventory now has an admin create endpoint, and Event Service now stores the owning `managerId`. Because of that, the composite no longer needs a local SQLite store for ownership links.

What is still missing is an admin update/delete API in Seat Inventory. Because of that:

- create works end-to-end when `seatSections` contain positive `capacity` values
- draft events can exist without inventory if seat capacities are not ready yet
- edit will reject seat-configuration changes that would require inventory totals or categories to change after bootstrap

## Endpoints

- `GET /health`
- `POST /manager/events`
- `PUT /manager/events/:eventId`
- `POST /manager/events/:eventId/cancel`
- `GET /manager/events?managerId=:managerId`

Compatibility aliases:

- `POST /events/create`
- `PUT /events/:eventId/edit`
- `POST /events/:eventId/cancel`

## Run

Environment variables used by this service:
- `USER_SERVICE_URL`
- `EVENT_SERVICE_URL`
- `SEAT_INVENTORY_URL`
- `RABBITMQ_URL`
- `NOTIFICATION_EXCHANGE`
- `EVENT_UPDATED_ROUTING_KEY`
- `EVENT_CANCELLED_ROUTING_KEY`

The composite listens on `http://localhost:5012`.

## Seed dummy data

This seed path assumes:

- User Service is on `localhost:5001`
- Event Service is on `localhost:5002`
- Seat Inventory is on `localhost:5004`

```bash
cd create-edit-event-composite
python3 seed_dummy_data.py
```

## Local tests

```bash
cd create-edit-event-composite
pytest
```

## Notification behavior

- Edit requests publish `event.updated` only when tracked event fields actually change
- Cancel requests publish `event.cancelled` with refund guidance indicating Stripe is the planned provider
- If RabbitMQ publish fails, the event change still succeeds and the API response includes a warning instead of rolling back
