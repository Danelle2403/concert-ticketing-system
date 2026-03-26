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
| Database | MySQL (User Service), Supabase/PostgreSQL (Ticket Service) |
| External Services | Stripe (Payments), SendGrid (Notifications), OutSystems (Order Service) |
| Deployment | Docker, Docker Compose |
| Version Control | GitHub |

## Prerequisites
Make sure you have the following installed before running:
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Git](https://git-scm.com/)

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
| UI | http://localhost:8080 |
| User Service | http://localhost:5001 |
| Seat Inventory Service | http://localhost:5004 |
| [Other services added by teammates] | http://localhost:500X |

### 4. Stop all services
```bash
docker-compose down
```

### 5. Run Seat Inventory smoke tests
```bash
python3 seat-inventory/smoke_test.py
```

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
- OutSystems is used for the Payment Service
- RabbitMQ handles all async messaging between services
