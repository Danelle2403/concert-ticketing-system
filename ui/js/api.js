const API_BASE = "http://localhost:8000";
const USER_API_BASE = API_BASE;
const EVENT_API_BASE = API_BASE;
const INVENTORY_API_BASE = API_BASE;

function buildUrl(path, query = {}) {
    return buildAbsoluteUrl(API_BASE, path, query);
}

function buildAbsoluteUrl(baseUrl, path, query = {}) {
    const url = new URL(`${baseUrl}${path}`);

    Object.entries(query).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
            url.searchParams.set(key, String(value));
        }
    });

    return url.toString();
}

async function apiRequest(path, options = {}) {
    const {
        method = "GET",
        query,
        body,
        headers = {},
        includeAuth = true,
        baseUrl = API_BASE,
        timeoutMs = 15000
    } = options;
    const requestOptions = {
        method,
        headers: {
            ...(includeAuth ? getAuthHeaders() : {}),
            ...headers
        }
    };
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
    requestOptions.signal = controller.signal;

    if (body !== undefined) {
        requestOptions.headers["Content-Type"] = "application/json";
        requestOptions.body = JSON.stringify(body);
    }

    try {
        const response = await fetch(buildAbsoluteUrl(baseUrl, path, query), requestOptions);
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
    } catch (error) {
        if (error.name === "AbortError") {
            const timeoutError = new Error("Request timed out. Please try again.");
            timeoutError.status = 408;
            throw timeoutError;
        }
        throw error;
    } finally {
        window.clearTimeout(timeoutId);
    }
}

function getStoredUser() {
    try {
        return JSON.parse(sessionStorage.getItem("user"));
    } catch (_error) {
        return null;
    }
}

function storeUser(user) {
    sessionStorage.setItem("user", JSON.stringify(user));
}

function getStoredAuthToken() {
    return getStoredUser()?.authToken || null;
}

function getAuthHeaders() {
    const authToken = getStoredAuthToken();
    return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

function clearStoredSession() {
    ["user", "selectedEvent", "lastPurchase"].forEach((key) => {
        sessionStorage.removeItem(key);
    });
}

function logoutUser(redirectTo = "login.html") {
    clearStoredSession();
    window.location.href = redirectTo;
}

function formatVenueLabel(venue) {
    if (typeof venue === "string") {
        const text = venue.trim();
        return text || "Venue TBC";
    }

    if (!venue || typeof venue !== "object") {
        return "Venue TBC";
    }

    const primary = [
        venue.name,
        venue.placeName,
        venue.formattedAddress,
        venue.address
    ]
        .map((value) => String(value || "").trim())
        .find(Boolean);

    const locality = [venue.city, venue.country]
        .map((value) => String(value || "").trim())
        .filter(Boolean);

    const label = [primary, ...locality].filter(Boolean).join(", ");
    return label || "Venue TBC";
}

function normalizeVenueDetails(venue) {
    if (typeof venue === "string") {
        const text = venue.trim();
        return {
            name: text,
            address: null,
            city: null,
            country: null
        };
    }

    if (!venue || typeof venue !== "object") {
        return {};
    }

    return {
        name: venue.name || venue.placeName || venue.formattedAddress || venue.address || "",
        address: venue.address || venue.formattedAddress || "",
        city: venue.city || "",
        country: venue.country || ""
    };
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
        venueDetails: normalizeVenueDetails(event.venue),
        price: startingPrice,
        priceLabel: startingPrice !== null ? `From $${startingPrice}` : "Price TBC",
        pricingTiers,
        seatSections,
        statusLabel: event.status || "DRAFT",
        statusKey: String(event.status || "draft").toLowerCase()
    };
}

// User Service
async function loginUser(credentials) {
    return apiRequest("/auth/login", {
        method: "POST",
        body: credentials,
        includeAuth: false,
        baseUrl: USER_API_BASE,
        timeoutMs: 5000
    });
}

async function registerUser(data) {
    return apiRequest("/auth/register", {
        method: "POST",
        body: data,
        includeAuth: false,
        baseUrl: USER_API_BASE,
        timeoutMs: 5000
    });
}

async function getAuthenticatedUser() {
    return apiRequest("/auth/me", {
        baseUrl: API_BASE,
        timeoutMs: 5000
    });
}

async function getUserEvents(userId) {
    return apiRequest("/user/events", {
        query: { userId },
        timeoutMs: 5000
    });
}

async function getManagingEvents(userId) {
    const payload = await apiRequest("/manager/events", {
        query: {
            managerId: userId
        }
    });

    const eventRows = (payload?.data?.events) || [];

    const hydratedEvents = await Promise.all(eventRows.map(async (eventRow) => {
        const summary = eventRow.eventSummary || eventRow || {};
        const eventId = eventRow.eventId ?? summary.id ?? summary.eventId;

        const alreadyHasConfiguration =
            Array.isArray(summary.pricingTiers) && Array.isArray(summary.seatSections);

        if (!eventId || alreadyHasConfiguration) {
            return normalizeEventRecord(summary);
        }

        try {
            const detail = await getEventById(eventId);
            return normalizeEventRecord({
                ...summary,
                ...detail,
                id: detail.id ?? eventId,
                status: eventRow.eventStatus || detail.statusLabel || summary.status
            });
        } catch (_error) {
            return normalizeEventRecord(summary);
        }
    }));

    return hydratedEvents;
}

async function searchManagerLocations(query) {
    return apiRequest("/manager/locations", {
        query: { q: String(query || "").trim() },
        timeoutMs: 7000
    });
}

async function validateManagerLocation(location) {
    return apiRequest("/manager/locations/validate", {
        method: "POST",
        body: { location },
        timeoutMs: 7000
    });
}

// Event Service via Kong
async function getEvents(filters = {}) {
    const query = {
        includeConfig: true,
        purchasableOnly: filters.purchasableOnly ?? true,
        status: filters.status,
        managerId: filters.managerId,
        keyword: filters.keyword,
        venue: filters.venue
    };

    try {
        const payload = await apiRequest("/events", {
            includeAuth: false,
            query,
            timeoutMs: 5000
        });
        return (payload.data || []).map(normalizeEventRecord);
    } catch (_error) {
        const payload = await apiRequest("/events", {
            includeAuth: false,
            baseUrl: EVENT_API_BASE,
            query,
            timeoutMs: 5000
        });
        return (payload.data || []).map(normalizeEventRecord);
    }
}

async function getEventById(eventId) {
    try {
        const payload = await apiRequest(`/events/${eventId}`, {
            includeAuth: false,
            timeoutMs: 5000
        });
        return normalizeEventRecord(payload.data || {});
    } catch (_error) {
        const payload = await apiRequest(`/events/${eventId}`, {
            includeAuth: false,
            baseUrl: EVENT_API_BASE,
            timeoutMs: 5000
        });
        return normalizeEventRecord(payload.data || {});
    }
}

async function getInventorySnapshot() {
    const payload = await apiRequest("/inventory", {
        includeAuth: false,
        baseUrl: INVENTORY_API_BASE,
        timeoutMs: 5000
    });
    return payload.inventory || [];
}

async function getInventoryByEvent(eventId) {
    const payload = await apiRequest(`/inventory/${encodeURIComponent(String(eventId))}`, {
        includeAuth: false,
        baseUrl: INVENTORY_API_BASE,
        timeoutMs: 5000
    });
    return payload.inventory || [];
}

// Create/Edit Event Composite via Kong
async function createManagerEvent(data) {
    const payload = await apiRequest("/manager/events", {
        method: "POST",
        body: data
    });

    return payload.data;
}

async function updateEvent(eventId, data) {
    const payload = await apiRequest(`/manager/events/${eventId}`, {
        method: "PUT",
        body: data
    });

    return payload.data;
}

async function cancelEvent(eventId, data) {
    return apiRequest(`/manager/events/${eventId}/cancel`, {
        method: "POST",
        body: data
    });
}

// Purchase Composite
async function getPurchaseConfig() {
    return apiRequest("/purchase/config");
}

async function createCheckoutSession(data) {
    return apiRequest("/purchase/checkout/session", {
        method: "POST",
        body: data
    });
}

async function confirmCheckoutSession(data) {
    return apiRequest("/purchase/checkout/confirm", {
        method: "POST",
        body: data
    });
}

async function buyTicket(data) {
    return apiRequest("/purchase/checkout", {
        method: "POST",
        body: data
    });
}

async function getPurchaseStatus(purchaseId) {
    return apiRequest(`/purchase/${purchaseId}/status`);
}

async function getPurchaseTicketMapping(ticketId) {
    return apiRequest(`/purchase/ticket/${ticketId}`);
}

// Refund Composite
async function requestRefundByTicket(ticketId, data = {}) {
    return apiRequest(`/refunds/${ticketId}`, {
        method: "POST",
        body: data
    });
}

async function requestRefundByEvent(eventId, data = {}) {
    return apiRequest(`/refunds/event/${eventId}`, {
        method: "POST",
        body: data
    });
}
