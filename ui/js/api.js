const API_BASE = window.API_BASE || "http://localhost:8000";

async function requestJson(path, options = {}) {
    const url = `${API_BASE}${path}`;
    const opts = {
        method: options.method || "GET",
        headers: { ...(options.headers || {}) }
    };

    if (options.body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(options.body);
    }

    const res = await fetch(url, opts);
    const contentType = res.headers.get("content-type") || "";
    let payload;

    if (contentType.includes("application/json")) {
        payload = await res.json();
    } else {
        const text = await res.text();
        payload = text ? { raw: text } : {};
    }

    if (!res.ok) {
        const message =
            payload?.error ||
            payload?.message ||
            `Request failed with status ${res.status}`;
        const error = new Error(message);
        error.status = res.status;
        error.payload = payload;
        throw error;
    }

    return payload;
}

// ─── USER SERVICE ────────────────────────────────────────────
async function loginUser(userId) {
    return requestJson(`/user/${encodeURIComponent(userId)}`);
}

async function registerUser(data) {
    return requestJson("/user/new", {
        method: "POST",
        body: data
    });
}

async function getUserEvents(userId) {
    return requestJson(`/user/events?userId=${encodeURIComponent(userId)}`);
}

async function getManagingEvents(userId) {
    return requestJson(`/user/managing?userId=${encodeURIComponent(userId)}`);
}

// ─── EVENT SERVICE ───────────────────────────────────────────
async function getEvents() {
    return requestJson("/events");
}

async function getEventById(eventId) {
    return requestJson(`/events/${encodeURIComponent(eventId)}`);
}

// ─── SEAT INVENTORY SERVICE ──────────────────────────────────
async function getInventoryByEvent(eventId) {
    return requestJson(`/inventory/${encodeURIComponent(eventId)}`);
}

async function checkSeatAvailability(eventId, seatCategory, quantity = 1) {
    return requestJson(
        `/inventory/${encodeURIComponent(eventId)}/${encodeURIComponent(seatCategory)}?quantity=${encodeURIComponent(quantity)}`
    );
}

// ─── TICKET SERVICE ──────────────────────────────────────────
async function getTicketById(ticketId) {
    return requestJson(`/tickets/${encodeURIComponent(ticketId)}`);
}

// ─── PURCHASE COMPOSITE ──────────────────────────────────────
async function buyTicket(data) {
    return requestJson("/purchase/checkout", {
        method: "POST",
        body: data
    });
}

async function getPurchaseStatus(purchaseId) {
    return requestJson(`/purchase/${encodeURIComponent(purchaseId)}/status`);
}

// ─── REFUND COMPOSITE ────────────────────────────────────────
async function requestRefundByTicket(ticketId) {
    return requestJson(`/refunds/${encodeURIComponent(ticketId)}`, {
        method: "POST",
        body: {}
    });
}

async function requestRefundByEvent(eventId) {
    return requestJson(`/refunds/event/${encodeURIComponent(eventId)}`, {
        method: "POST",
        body: {}
    });
}

// ─── EDIT EVENT COMPOSITE ────────────────────────────────────
async function updateEvent(eventId, data) {
    return requestJson(`/events/${encodeURIComponent(eventId)}/edit`, {
        method: "PUT",
        body: data
    });
}

async function cancelEvent(eventId) {
    return requestJson(`/events/${encodeURIComponent(eventId)}/cancel`, {
        method: "POST",
        body: {}
    });
}

// ─── NOTIFICATION SERVICE ────────────────────────────────────
async function getNotificationLogs() {
    return requestJson("/notifications");
}
