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
| Messaging | RabbitMQ (AMQP) |
| Database | MySQL |
| External Services | Stripe (Payments), SendGrid (Notifications) |
| Deployment | Docker, Docker Compose |

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
| [Other services added by teammates] | http://localhost:500X |

### 4. Stop all services
```bash
docker-compose down
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

## Notes & Assumptions
- The API Gateway runs on port 8000
- Each service has its own database
- OutSystems is used for the Payment Service
- RabbitMQ handles all async messaging between services
