const API_BASE = "http://localhost:8000"; // API Gateway URL

// ─── USER SERVICE ────────────────────────────────────────────
async function loginUser(userId) {
    const res = await fetch(`${API_BASE}/user/${userId}`);
    return res.json();
}

async function registerUser(data) {
    const res = await fetch(`${API_BASE}/user/new`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
    });
    return res.json();
}

async function getUserEvents(userId) {
    const res = await fetch(`${API_BASE}/user/events?userId=${userId}`);
    return res.json();
}

async function getManagingEvents(userId) {
    const res = await fetch(`${API_BASE}/user/managing?userId=${userId}`);
    return res.json();
}

// ─── EVENT SERVICE ───────────────────────────────────────────
async function getEvents() {
    const res = await fetch(`${API_BASE}/events`);
    return res.json();
}

async function getEventById(eventId) {
    const res = await fetch(`${API_BASE}/events/${eventId}`);
    return res.json();
}

// ─── PURCHASE COMPOSITE ──────────────────────────────────────
async function buyTicket(data) {
    const res = await fetch(`${API_BASE}/purchase/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
    });
    return res.json();
}

async function getPurchaseStatus(purchaseId) {
    const res = await fetch(`${API_BASE}/purchase/${purchaseId}/status`);
    return res.json();
}

// ─── REFUND COMPOSITE ────────────────────────────────────────
async function requestRefundByTicket(ticketId) {
    const res = await fetch(`${API_BASE}/refunds/${ticketId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
    });
    return res.json();
}

async function requestRefundByEvent(eventId) {
    const res = await fetch(`${API_BASE}/refunds/event/${eventId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
    });
    return res.json();
}

// ─── EDIT EVENT COMPOSITE ────────────────────────────────────
async function updateEvent(eventId, data) {
    const res = await fetch(`${API_BASE}/events/${eventId}/edit`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
    });
    return res.json();
}

async function cancelEvent(eventId) {
    const res = await fetch(`${API_BASE}/events/${eventId}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
    });
    return res.json();
}
