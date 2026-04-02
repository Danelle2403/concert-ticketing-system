(function () {
    function disableCustomCursor() {
        if (document.body) {
            document.body.classList.remove("custom-cursor-enabled");
        }
    }

    function ensureStyles() {
        if (document.getElementById("cursor-style-inject")) {
            return;
        }

        const style = document.createElement("style");
        style.id = "cursor-style-inject";
        style.textContent = `
            body { cursor: none !important; }
            .cursor {
                width: 8px;
                height: 8px;
                background: #d4709a;
                border-radius: 50%;
                position: fixed;
                top: 0;
                left: 0;
                pointer-events: none;
                z-index: 9999;
                transform: translate(-50%, -50%);
                transition: width 0.2s, height 0.2s, background 0.2s;
            }
            .cursor-follower {
                width: 36px;
                height: 36px;
                border: 1px solid rgba(212, 112, 154, 0.5);
                border-radius: 50%;
                position: fixed;
                top: 0;
                left: 0;
                pointer-events: none;
                z-index: 9998;
                transform: translate(-50%, -50%);
                transition: width 0.3s, height 0.3s, border-color 0.3s;
            }
            .cursor.cursor-hover {
                width: 16px;
                height: 16px;
                background: #f2c4d0;
            }
            .cursor-follower.cursor-hover {
                width: 56px;
                height: 56px;
                border-color: #d4709a;
            }
        `;
        document.head.appendChild(style);
    }

    function ensureCursorElements() {
        let cursor = document.getElementById("cursor");
        let follower = document.getElementById("cursor-follower");

        if (!cursor) {
            cursor = document.createElement("div");
            cursor.id = "cursor";
            cursor.className = "cursor";
            document.body.appendChild(cursor);
        }

        if (!follower) {
            follower = document.createElement("div");
            follower.id = "cursor-follower";
            follower.className = "cursor-follower";
            document.body.appendChild(follower);
        }

        return { cursor, follower };
    }

    function init() {
        ensureStyles();
        const { cursor, follower } = ensureCursorElements();

        let mouseX = window.innerWidth / 2;
        let mouseY = window.innerHeight / 2;
        let followerX = mouseX;
        let followerY = mouseY;

        // Ensure cursor is visible immediately, even before first mousemove.
        cursor.style.left = mouseX + "px";
        cursor.style.top = mouseY + "px";
        follower.style.left = followerX + "px";
        follower.style.top = followerY + "px";

        if (document.body) {
            document.body.classList.add("custom-cursor-enabled");
        }

        const interactiveSelector = [
            "a",
            "button",
            "input",
            "select",
            "textarea",
            "label",
            "[role='button']",
            ".event-card",
            ".genre-card",
            ".artist-card",
            ".filter-tab"
        ].join(",");

        document.addEventListener("mousemove", function (e) {
            mouseX = e.clientX;
            mouseY = e.clientY;
            cursor.style.left = mouseX + "px";
            cursor.style.top = mouseY + "px";
        });

        document.addEventListener("mouseover", function (e) {
            if (e.target.closest(interactiveSelector)) {
                cursor.classList.add("cursor-hover");
                follower.classList.add("cursor-hover");
            }
        });

        document.addEventListener("mouseout", function (e) {
            if (e.target.closest(interactiveSelector)) {
                cursor.classList.remove("cursor-hover");
                follower.classList.remove("cursor-hover");
            }
        });

        document.addEventListener("mouseleave", function () {
            cursor.style.opacity = "0";
            follower.style.opacity = "0";
        });

        document.addEventListener("mouseenter", function () {
            cursor.style.opacity = "1";
            follower.style.opacity = "1";
        });

        function animateFollower() {
            followerX += (mouseX - followerX) * 0.1;
            followerY += (mouseY - followerY) * 0.1;
            follower.style.left = followerX + "px";
            follower.style.top = followerY + "px";
            requestAnimationFrame(animateFollower);
        }

        animateFollower();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            try {
                init();
            } catch (e) {
                disableCustomCursor();
            }
        });
    } else {
        try {
            init();
        } catch (e) {
            disableCustomCursor();
        }
    }
})();
