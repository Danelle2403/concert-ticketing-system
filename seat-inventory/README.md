# Seat Inventory Service

Atomic Flask service for seat availability, seat holds, confirmations, and releases.

## What it does

- stores per-event inventory by seat category
- creates short-lived seat holds for checkout
- confirms holds after purchase succeeds
- releases held or confirmed inventory for rollback, refund, or event cancellation
- seeds local demo rows that align with the current external order data

## Endpoints

- `GET /health`
- `GET /inventory`
- `GET /inventory/<eventId>`
- `GET /inventory/<eventId>/<seatCategory>?quantity=1`
- `POST /inventory/admin/create`
- `POST /inventory/admin/seed-order-demo`
- `POST /inventory/hold`
- `POST /inventory/confirm`
- `POST /inventory/release`
- `GET /inventory/holds/<holdId>`

## Demo data

`POST /inventory/admin/seed-order-demo` restores the local inventory and hold rows for the order-aligned demo events:

- event `1` with `VIP` and `STANDARD`
- event `2` with `VIP`
- event `789` with `VIP`

This seed keeps the local inventory state coherent with the order rows used by the purchase and refund wrappers.

## Run

The repo root stack exposes this service on `http://localhost:5004`.

## Local tests

```bash
cd seat-inventory
../.venv/bin/python -m pytest -q
```

## Smoke test

```bash
python3 smoke_test.py
```
