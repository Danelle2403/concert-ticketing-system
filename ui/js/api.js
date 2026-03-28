const API_BASE = "http://localhost:8000";

function buildUrl(path, query = {}) {
    const url = new URL(`${API_BASE}${path}`);

    Object.entries(query).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
            url.searchParams.set(key, String(value));
        }
    });

    return url.toString();
}

async function apiRequest(path, options = {}) {
    const { method = "GET", query, body } = options;
    const requestOptions = { method, headers: {} };

    if (body !== undefined) {
        requestOptions.headers["Content-Type"] = "application/json";
        requestOptions.body = JSON.stringify(body);
    }

    const response = await fetch(buildUrl(path, query), requestOptions);
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
        ? await response.json()
        : await response.text();

    if (!response.ok) {
        const message =
            payload?.error?.message ||
            payload?.error ||
            payload?.message ||
            `Request failed with status ${response.status}`;

        const error = new Error(message);
        error.status = response.status;
        error.payload = payload;
        throw error;
    }

    return payload;
}

function formatVenueLabel(venue) {
    if (!venue || typeof venue !== "object") {
        return "Venue TBC";
    }

    return [venue.name, venue.city, venue.country].filter(Boolean).join(", ");
}

function formatDateLabel(value, options = { day: "2-digit", month: "short", year: "numeric" }) {
    if (!value) {
        return "Date TBC";
    }

    return new Intl.DateTimeFormat("en-SG", options).format(new Date(value));
}

function formatDateTimeRange(startAt, endAt) {
    if (!startAt) {
        return "Date TBC";
    }

    const dateFormatter = new Intl.DateTimeFormat("en-SG", {
        weekday: "short",
        day: "2-digit",
        month: "short",
        year: "numeric"
    });
    const timeFormatter = new Intl.DateTimeFormat("en-SG", {
        hour: "numeric",
        minute: "2-digit"
    });

    const start = new Date(startAt);
    const end = endAt ? new Date(endAt) : null;
    const date = dateFormatter.format(start);

    if (!end) {
        return `${date} · ${timeFormatter.format(start)}`;
    }

    return `${date} · ${timeFormatter.format(start)} - ${timeFormatter.format(end)}`;
}

function normalizeEventRecord(event) {
    const pricingTiers = Array.isArray(event?.pricingTiers) ? event.pricingTiers : [];
    const seatSections = Array.isArray(event?.seatSections) ? event.seatSections : [];
    const numericPrices = pricingTiers
        .map((tier) => Number(tier.price))
        .filter((price) => Number.isFinite(price));
    const startingPrice = numericPrices.length > 0 ? Math.min(...numericPrices) : null;

    return {
        ...event,
        id: event.id,
        eventId: event.id,
        name: event.title,
        title: event.title,
        date: formatDateLabel(event.startAt),
        dateTimeLabel: formatDateTimeRange(event.startAt, event.endAt),
        venue: formatVenueLabel(event.venue),
        venueDetails: event.venue || {},
        price: startingPrice,
        priceLabel: startingPrice !== null ? `From $${startingPrice}` : "Price TBC",
        pricingTiers,
        seatSections,
        statusLabel: event.status || "DRAFT",
        statusKey: String(event.status || "draft").toLowerCase()
    };
}

// User Service
async function loginUser(userId) {
    return apiRequest(`/user/${userId}`);
}

async function registerUser(data) {
    return apiRequest("/user/new", { method: "POST", body: data });
}

async function getUserEvents(userId) {
    return apiRequest("/user/events", { query: { userId } });
}

async function getManagingEvents(userId) {
    const payload = await apiRequest("/events", {
        query: {
            managerId: userId,
            includeConfig: true
        }
    });

    return (payload.data || []).map(normalizeEventRecord);
}

// Event Service via Kong
async function getEvents(filters = {}) {
    const payload = await apiRequest("/events", {
        query: {
            includeConfig: true,
            purchasableOnly: filters.purchasableOnly ?? true,
            status: filters.status,
            managerId: filters.managerId,
            keyword: filters.keyword,
            venue: filters.venue
        }
    });

    return (payload.data || []).map(normalizeEventRecord);
}

async function getEventById(eventId) {
    const payload = await apiRequest(`/events/${eventId}`);
    return normalizeEventRecord(payload.data || {});
}

// Create/Edit Event Composite via Kong
async function createManagerEvent(data) {
    const payload = await apiRequest("/events/create", {
        method: "POST",
        body: data
    });

    return payload.data;
}

async function updateEvent(eventId, data) {
    const payload = await apiRequest(`/events/${eventId}/edit`, {
        method: "PUT",
        body: data
    });

    return payload.data;
}

async function cancelEvent(eventId) {
    return apiRequest(`/events/${eventId}/cancel`, {
        method: "POST"
    });
}

// Purchase Composite
async function buyTicket(data) {
    return apiRequest("/purchase/checkout", {
        method: "POST",
        body: data
    });
}

async function getPurchaseStatus(purchaseId) {
    return apiRequest(`/purchase/${purchaseId}/status`);
}

// Refund Composite
async function requestRefundByTicket(ticketId) {
    return apiRequest(`/refunds/${ticketId}`, {
        method: "POST"
    });
}

async function requestRefundByEvent(eventId) {
    return apiRequest(`/refunds/event/${eventId}`, {
        method: "POST"
    });
}
