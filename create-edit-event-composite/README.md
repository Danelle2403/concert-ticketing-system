# Create/Edit Event Composite

Manager-only Flask orchestration service for creating and editing events.

## What it does

- validates the acting user through User Service
- creates or edits event metadata through Event Service
- relies on `managerId` stored in Event Service for ownership checks and manager event listing
- bootstraps Seat Inventory with the Event Service UUID by aggregating `seatSections[].capacity` per pricing tier
- validates existing Seat Inventory totals before allowing seat-configuration edits
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
- `GET /manager/events?managerId=:managerId`

Compatibility aliases:

- `POST /events/create`
- `PUT /events/:eventId/edit`

## Run

```bash
cd create-edit-event-composite
docker compose up --build
```

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
