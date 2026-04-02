(function () {
    const OVERLAY_ID = "notifications-overlay";
    const LIST_ID = "notifications-overlay-list";
    const LOADING_ID = "notifications-overlay-loading";
    const EMPTY_ID = "notifications-overlay-empty";
    const ERROR_ID = "notifications-overlay-error";

    function ensureStyles() {
        if (document.getElementById("notifications-overlay-style")) {
            return;
        }
        const style = document.createElement("style");
        style.id = "notifications-overlay-style";
        style.textContent = `
            .notifications-overlay-content {
                width: min(780px, 92vw);
                max-height: 80vh;
                overflow-y: auto;
            }
            .notifications-overlay-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 8px;
            }
            .notifications-overlay-meta {
                color: var(--text-secondary);
                font-size: 0.9rem;
            }
        `;
        document.head.appendChild(style);
    }

    function ensureOverlay() {
        let overlay = document.getElementById(OVERLAY_ID);
        if (overlay) {
            return overlay;
        }

        ensureStyles();

        overlay = document.createElement("div");
        overlay.id = OVERLAY_ID;
        overlay.className = "modal hidden";
        overlay.innerHTML = `
            <div class="modal-content notifications-overlay-content">
                <div class="notifications-overlay-header">
                    <h3>Notifications</h3>
                    <div class="ticket-actions">
                        <button class="btn-secondary" id="notifications-overlay-refresh">Refresh</button>
                        <button class="btn-secondary" id="notifications-overlay-close">Close</button>
                    </div>
                </div>
                <p class="notifications-overlay-meta">In-page inbox view</p>
                <div id="${LOADING_ID}" class="loading-msg">Loading your notifications...</div>
                <div id="${ERROR_ID}" class="error-msg hidden">Failed to load notifications.</div>
                <div id="${EMPTY_ID}" class="hidden"><p>No notifications yet.</p></div>
                <div id="${LIST_ID}"></div>
            </div>
        `;
        document.body.appendChild(overlay);

        document.getElementById("notifications-overlay-close").addEventListener("click", closeNotificationsOverlay);
        document.getElementById("notifications-overlay-refresh").addEventListener("click", loadNotificationsOverlay);
        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) {
                closeNotificationsOverlay();
            }
        });

        return overlay;
    }

    function parsePayload(raw) {
        if (!raw) return {};
        try {
            return JSON.parse(raw);
        } catch (e) {
            return { raw };
        }
    }

    function formatTime(ts) {
        if (!ts) return "Unknown time";
        const d = new Date(ts);
        if (Number.isNaN(d.getTime())) return ts;
        return d.toLocaleString();
    }

    function extractTitle(item) {
        if (item.subject) return item.subject;
        const map = {
            "ticket.purchased": "Ticket Purchased",
            "concert.updated": "Concert Updated",
            "concert.cancelled": "Concert Cancelled",
            "refund.confirmed": "Refund Confirmed",
            "concert.refund.failed": "Refund Failed",
        };
        return map[item.routing_key] || "Notification";
    }

    function extractBody(item, payload) {
        if (payload.eventName && payload.ticketId) return `${payload.eventName} • Ticket ${payload.ticketId}`;
        if (payload.eventName) return payload.eventName;
        if (payload.reason) return payload.reason;
        return item.routing_key || "Notification";
    }

    async function loadNotificationsOverlay() {
        const loading = document.getElementById(LOADING_ID);
        const error = document.getElementById(ERROR_ID);
        const empty = document.getElementById(EMPTY_ID);
        const list = document.getElementById(LIST_ID);

        loading.classList.remove("hidden");
        error.classList.add("hidden");
        empty.classList.add("hidden");
        list.innerHTML = "";

        const user = JSON.parse(sessionStorage.getItem("user"));
        if (!user) {
            loading.classList.add("hidden");
            error.textContent = "Please login first to view notifications.";
            error.classList.remove("hidden");
            return;
        }

        try {
            const data = await getNotificationLogs();
            let notifications = data.notifications || [];

            if (user.role !== "manager") {
                const email = (user.email || "").toLowerCase();
                notifications = notifications.filter(n => {
                    const payload = parsePayload(n.payload);
                    const payloadUserId = payload.userId != null ? String(payload.userId) : null;
                    const viewerUserId = user.userId != null ? String(user.userId) : null;
                    const emailMatches = (n.email || "").toLowerCase() === email;
                    const userIdMatches = payloadUserId && viewerUserId && payloadUserId === viewerUserId;
                    return emailMatches || userIdMatches;
                });
            }

            loading.classList.add("hidden");

            if (!notifications.length) {
                empty.classList.remove("hidden");
                return;
            }

            notifications.forEach(item => {
                const payload = parsePayload(item.payload);
                const card = document.createElement("div");
                card.className = "ticket-card";
                card.innerHTML = `
                    <div class="ticket-info">
                        <h3>${extractTitle(item)}</h3>
                        <p>${extractBody(item, payload)}</p>
                        <p>Type: ${item.routing_key || "-"}</p>
                        <p>Sent: ${formatTime(item.sent_at)}</p>
                        <span class="ticket-status status-active">${item.email || "broadcast"}</span>
                    </div>
                `;
                list.appendChild(card);
            });
        } catch (e) {
            loading.classList.add("hidden");
            error.textContent = e.message || "Failed to load notifications.";
            error.classList.remove("hidden");
        }
    }

    function closeNotificationsOverlay() {
        const overlay = document.getElementById(OVERLAY_ID);
        if (overlay) {
            overlay.classList.add("hidden");
        }
    }

    async function openNotificationsOverlay(event) {
        if (event) event.preventDefault();
        const overlay = ensureOverlay();
        overlay.classList.remove("hidden");
        await loadNotificationsOverlay();
    }

    window.openNotificationsOverlay = openNotificationsOverlay;
    window.closeNotificationsOverlay = closeNotificationsOverlay;
    window.loadNotificationsOverlay = loadNotificationsOverlay;
})();
