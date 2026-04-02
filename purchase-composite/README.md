# Purchase Composite

Scenario orchestration service for checkout, external order creation, and ticket mapping.

## What it does

- validates the buyer through User Service
- checks event metadata from Event Service or local order-aligned demo fallbacks
- holds and confirms inventory through Seat Inventory
- issues tickets through local Ticket Atomic
- writes orders to the external OutSystems OrderService
- stores local purchase and ticket mapping rows in SQLite
- pushes downstream ticket status updates back to OrderService

## Current limitations

- payment orchestration is still mocked; the service accepts or generates `paymentChargeId` directly
- the external OrderService still expects prefixed fan and concert IDs, so normalization is still in place
- local order-aligned demo events `1`, `2`, and `789` are still fallback records inside this wrapper

## Endpoints

- `GET /health`
- `POST /purchase/checkout`
- `GET /purchase/<purchaseId>/status`
- `GET /purchase/ticket/<ticketId>`
- `POST /purchase/ticket/<ticketId>/status`

## Run

The repo root stack exposes this service on `http://localhost:5010`.

Before using the order-aligned demo flow, seed:

```bash
curl -X POST http://localhost:5001/user/seed
curl -X POST http://localhost:5004/inventory/admin/seed-order-demo
```

## Local tests

```bash
cd purchase-composite
../.venv/bin/python -m pytest -q
```
