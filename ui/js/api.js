const API_BASE = "http://localhost:8000"; // API Gateway URL

async function getEvents() {
    const res = await fetch(`${API_BASE}/events`);
    return res.json();
}

async function buyTicket(data) {
    const res = await fetch(`${API_BASE}/purchase/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
    });
    return res.json();
}
