# Refund Composite

Scenario orchestration service for ticket refunds and event-wide refund batches.

## What it does

- loads ticket ownership/status from User Service
- looks up purchase mappings from Purchase Composite
- releases inventory through Seat Inventory when a mapped hold exists
- updates ticket state in User Service
- updates purchase/order state through Purchase Composite

## Endpoints

- `GET /health`
- `POST /refunds/<ticketId>`
- `POST /refunds/event/<eventId>`

## Current state

- single-ticket and event-batch refund flows are implemented
- create/edit cancel flows do not trigger this service yet; they currently return planned refund metadata so later wiring is straightforward
- refund IDs and batch IDs are local composite IDs, not Stripe-native IDs

## Run

The repo root stack exposes this service on `http://localhost:5011`.

## Local tests

```bash
cd refund-composite
../.venv/bin/python -m pytest -q
```
