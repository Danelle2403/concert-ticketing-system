# Concert Ticketing System

## Project Overview
A concert ticketing platform built using a microservices architecture.
The system supports 3 main scenarios:
1. **Buy Ticket** — Fan browses events and purchases a ticket (with compensating transactions on failure)
2. **Update Concert** — Event manager edits concert details and fans are notified
3. **Cancel Concert** — Event manager cancels a concert triggering automatic refunds to all ticket holders

## Tech Stack
| Layer | Technology |
|---|---|
| UI | HTML, CSS, JavaScript |
| Microservices | Python, Flask |
| API Gateway | Kong |
| Messaging | RabbitMQ (AMQP) |
| Database | MySQL (User Service), PostgreSQL (Event + Ticket Atomic), SQLite (Purchase), InnoDB/MySQL-compatible stores elsewhere |
| External Services | Stripe (Payments), SendGrid (Notifications), OutSystems (Order Service) |
| Deployment | Docker, Docker Compose |
| Version Control | GitHub |

## Prerequisites
Make sure you have the following installed before running:
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Git](https://git-scm.com/)

## Local Environment Setup
Create a local `.env` file before starting the stack if you want real notification delivery and a configured Stripe wrapper:

```bash
cp .env.example .env
```

Required for SendGrid-backed notifications:
- `SENDGRID_API_KEY`: your SendGrid API key with Mail Send permission
- `SENDGRID_FROM_EMAIL`: a verified sender address or verified domain address in SendGrid

Optional for the standalone Stripe wrapper:
- `STRIPE_SECRET_KEY`: your Stripe secret key
- `STRIPE_PUBLISHABLE_KEY`: your Stripe publishable key (useful for UI work later)

If these are left blank, the notification wrapper still runs, but it switches to `log_only` mode and writes the notification payload to container logs instead of sending email.
If the Stripe keys are left blank, the payment wrapper still starts, but it returns `503 STRIPE_NOT_CONFIGURED` for live payment/refund requests.

Notification behavior added on this branch:
- event edits publish `event.updated` through RabbitMQ and fan out notification emails to current ticket holders
- event cancellations publish `event.cancelled` through RabbitMQ and fan out cancellation emails with planned Stripe refund messaging
- the notification wrapper can also be triggered directly through internal helper endpoints for testing

## How to Run

### 1. Clone the repository
```bash
git clone https://github.com/Danelle2403/concert-ticketing-system.git
cd concert-ticketing-system
```

### 2. Start all services
```bash
docker-compose up --build
```

### 3. Access the application
| Service | URL |
|---|---|
| UI | http://localhost:8080/index.html |
| Kong API Gateway (used by UI) | http://localhost:8000 |
| User Service | http://localhost:5001 |
| Event Service | http://localhost:5003 |
| Seat Inventory Service | http://localhost:5004 |
| Purchase Composite | http://localhost:5010 |
| Refund Composite | http://localhost:5011 |
| Edit Event Composite | http://localhost:5012 |
| Ticket Atomic Service | http://localhost:5002/health |
| Notification Service | http://localhost:5013/health |
| Payment Service | http://localhost:5014/health |
| RabbitMQ Dashboard | http://localhost:15672 |

### 4. Seed demo users/events
```bash
curl -X POST http://localhost:5001/user/seed
curl -X POST http://localhost:5004/inventory/admin/seed-order-demo
```

Default demo users:
- Fan login `User ID = 1`
- Manager login `User ID = 2`

The extra seat inventory seed keeps the local demo data aligned with the external OrderService rows used by the purchase/refund wrappers.

### 5. Stop all services
```bash
docker-compose down
```

### 6. Run Seat Inventory smoke tests
```bash
python3 seat-inventory/smoke_test.py
```

### 7. Run Python service tests locally
Each Python service now includes `pytest` in its own `requirements.txt`.
Docker still isolates the running services, but host-side test commands use your host Python unless you run them inside a container or install that service's requirements into a venv.

Example local workflow:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r create-edit-event-composite/requirements.txt
python -m pytest -q create-edit-event-composite/tests
```

Use the same pattern for `user-service`, `seat-inventory`, `purchase-composite`, `refund-composite`, `notification-service`, `payment-service`, and `ticket_atomic`.

## Project Structure
```
concert-ticketing-system/
├── ui/                        # Frontend HTML/CSS/JS
│   ├── index.html             # Browse events
│   ├── login.html             # Login & register
│   ├── buy-ticket.html        # Purchase tickets
│   ├── request-refund.html    # View tickets & request refund
│   ├── manage-event.html      # Event manager dashboard
│   ├── css/style.css
│   └── js/api.js
├── user-service/              # User atomic microservice
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── seat-inventory/            # Seat Inventory atomic microservice
│   ├── app.py
│   ├── init.sql
│   ├── requirements.txt
│   └── Dockerfile
├── event-service/             # Event atomic microservice
├── purchase-composite/        # Scenario 1 orchestration
├── refund-composite/          # Scenario 3 / ticket refund orchestration
├── create-edit-event-composite/ # Scenario 2 orchestration
├── ticket_atomic/              # Ticket issuance/validation atomic microservice
├── notification-service/      # SendGrid wrapper + RabbitMQ consumer
├── payment-service/           # Stripe wrapper (standalone for now)
├── kong/                      # Kong declarative routes
├── docker-compose.yml
└── README.md
```

## API Endpoints — User Service
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /users | Get all users |
| GET | /user/<userId> | Get user by ID |
| POST | /user/new | Register new user |
| GET | /user/events | Get fan's purchased tickets |
| GET | /user/managing | Get manager's events |
| POST | /user/seed | Seed demo users + manager events |
| POST | /user/tickets/add | Internal ticket upsert used by composites |
| GET | /user/ticket/<ticketId> | Internal ticket lookup |
| POST | /user/ticket/<ticketId>/status | Internal ticket status update |
| GET | /user/tickets/by-event/<eventId> | Internal event ticket lookup |
| PUT | /user/managed/<eventId> | Internal managed-event update |
| POST | /user/managed/<eventId>/cancel | Internal managed-event cancel |

## API Endpoints — Event Service
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /events | List events for browse page |
| GET | /events/<eventId> | Get event details |
| PUT | /events/<eventId>/edit | Edit event details |
| POST | /events/<eventId>/cancel | Cancel event |

## API Endpoints — Purchase Composite
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health check |
| POST | /purchase/checkout | Buy ticket flow orchestration |
| GET | /purchase/<purchaseId>/status | Get purchase status |
| GET | /purchase/ticket/<ticketId> | Internal ticket mapping lookup |
| POST | /purchase/ticket/<ticketId>/status | Internal ticket mapping status update |

## API Endpoints — Refund Composite
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health check |
| POST | /refunds/<ticketId> | Refund one ticket |
| POST | /refunds/event/<eventId> | Refund all active tickets for an event |

## API Endpoints — Ticket Atomic Service
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health check + schema bootstrap |
| POST | /tickets/issue | Issue a ticket for an event |
| GET | /tickets/<ticketId> | Fetch one ticket |
| GET | /tickets/event/<eventId> | Fetch tickets for an event |
| POST | /tickets/<ticketId>/invalidate | Invalidate a ticket |

## API Endpoints — Edit Event Composite
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health check |
| POST | /events/create | Scenario 2 create orchestration |
| PUT | /events/<eventId>/edit | Scenario 2 edit orchestration |
| POST | /events/<eventId>/cancel | Scenario 3 manager cancellation orchestration |

## API Endpoints — Notification Service
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health + consumer state |
| POST | /notifications/events | Internal/manual dispatch helper |
| POST | /notifications/event-updated | Internal/manual dispatch helper |
| POST | /notifications/event-cancelled | Internal/manual dispatch helper |

## API Endpoints — Payment Service
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health + Stripe configuration state |
| POST | /payments/intents | Create a Stripe PaymentIntent |
| GET | /payments/intents/<paymentIntentId> | Retrieve a Stripe PaymentIntent |
| POST | /refunds | Create a Stripe refund from `chargeId` or `paymentIntentId` |

## API Endpoints — Seat Inventory Service
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /inventory | Get all inventory rows |
| GET | /inventory/<eventId> | Get all seat categories for one event |
| GET | /inventory/<eventId>/<seatCategory>?quantity=1 | Check availability for requested quantity |
| POST | /inventory/hold | Hold seats atomically (`eventId`, `seatCategory`, `quantity`, optional `ttlSeconds`) |
| POST | /inventory/confirm | Confirm a hold (`holdId`) |
| POST | /inventory/release | Release a hold (`holdId`) and return seats (`allowConfirmedRelease=true` for refund/cancel) |
| GET | /inventory/holds/<holdId> | Get hold status/details |

## Notes & Assumptions
- The API Gateway runs on port 8000
- Each service has its own database
- Purchase checkout writes orders to the external OutSystems OrderService and issues tickets through the local `ticket-atomic` service
- The Stripe wrapper is now available as a standalone service, but it is not yet wired into the purchase or cancel composites
- RabbitMQ is used for async `event.updated` and `event.cancelled` fanout from the create/edit composite to the notification wrapper
- Event edit notifications include refund-request guidance, and cancel notifications include Stripe refund guidance for ticket holders that are not currently `cancelled` or `refunded`
