# Refund Composite

Scenario orchestration service for ticket refunds and event-wide refund batches.

## What it does

- loads ticket ownership/status from User Service
- looks up purchase mappings from Purchase Composite
- creates Stripe refunds through Payment Service
- releases inventory through Seat Inventory when a mapped hold exists
- invalidates or updates downstream ticket/order state where required
- sends refund success/failure emails through Notification Service
- updates ticket state in User Service
- updates purchase/order state through Purchase Composite

## Endpoints

- `GET /health`
- `POST /refunds/<ticketId>`
- `POST /refunds/event/<eventId>`

Auth:

- `POST /refunds/<ticketId>` expects a bearer token for the ticket owner
- `POST /refunds/event/<eventId>` is manager-only from the browser and also accepts the internal service token for orchestrated event cancellations

## Current state

- single-ticket and event-batch refund flows are implemented
- event cancellation orchestration now triggers event-batch refunds automatically from the create/edit event composite
- event reschedule flows allow the fan to trigger a Stripe refund from My Tickets
- refund IDs returned by this service are the Stripe refund IDs when Stripe succeeds

## Run

The browser should reach this service through Kong at `http://localhost:8000/refunds`.
The direct container port `http://localhost:5011` is for internal calls, health checks, and debugging.

## Local tests

```bash
cd refund-composite
../.venv/bin/python -m pytest -q
```
