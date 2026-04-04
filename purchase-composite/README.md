# Purchase Composite

Scenario orchestration service for checkout, Stripe payment verification, external order creation, and ticket mapping.

## What it does

- validates the buyer through User Service
- reads event metadata from Event Service
- holds and confirms inventory through Seat Inventory
- creates Stripe-backed checkout sessions through Payment Service
- verifies the PaymentIntent before issuing tickets
- issues tickets through local Ticket Atomic
- writes orders to the external OutSystems OrderService
- stores local purchase and ticket mapping rows in SQLite
- sends purchase confirmation emails through Notification Service
- pushes downstream ticket status updates back to OrderService

## Current limitations

- local order-aligned demo events `1`, `2`, and `789` are still fallback records inside this wrapper
- purchase confirmation currently relies on client confirmation plus server-side PaymentIntent verification; webhook-based reconciliation is still a future hardening step

## Endpoints

- `GET /health`
- `GET /purchase/config`
- `POST /purchase/checkout/session`
- `POST /purchase/checkout/confirm`
- `POST /purchase/checkout`
- `GET /purchase/<purchaseId>/status`
- `GET /purchase/ticket/<ticketId>`
- `POST /purchase/ticket/<ticketId>/status`

Public browser routes through Kong require `Authorization: Bearer <jwt>`.
Internal ticket mapping routes require `X-Internal-Service-Token`.

## Run

The browser should reach this service through Kong at `http://localhost:8000/purchase`.
The direct container port `http://localhost:5010` is for internal calls, health checks, and debugging.

Before using the order-aligned demo flow, reset the shared demo fixture:

```bash
python3 ../scripts/reset_local_demo_state.py
```

## Local tests

```bash
cd purchase-composite
../.venv/bin/python -m pytest -q
```
