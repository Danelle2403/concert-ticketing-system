(function () {
    function getFieldContainer(field) {
        if (!field) {
            return null;
        }

        return field.closest(".form-group") || field.parentElement || null;
    }

    function ensureErrorNode(container) {
        let node = container.querySelector(".field-error-text");
        if (!node) {
            node = document.createElement("div");
            node.className = "field-error-text";
            node.setAttribute("role", "alert");
            container.appendChild(node);
        }
        return node;
    }

    function setFieldError(field, message) {
        const container = getFieldContainer(field);
        if (!container || !field) {
            return false;
        }

        container.classList.add("has-error");
        field.setAttribute("aria-invalid", "true");
        ensureErrorNode(container).textContent = message;
        return true;
    }

    function clearFieldError(field) {
        const container = getFieldContainer(field);
        if (!container || !field) {
            return;
        }

        container.classList.remove("has-error");
        field.removeAttribute("aria-invalid");
        const node = container.querySelector(".field-error-text");
        if (node) {
            node.remove();
        }
    }

    function clearErrors(scope = document) {
        scope.querySelectorAll(".form-group.has-error").forEach((container) => {
            container.classList.remove("has-error");
            const field = container.querySelector("input, select, textarea");
            if (field) {
                field.removeAttribute("aria-invalid");
            }

            const node = container.querySelector(".field-error-text");
            if (node) {
                node.remove();
            }
        });
    }

    function focusFirstError(scope = document) {
        const field = scope.querySelector(".form-group.has-error input, .form-group.has-error select, .form-group.has-error textarea");
        if (field) {
            field.focus();
        }
    }

    function validateRequired(field, message) {
        if (!field || String(field.value || "").trim()) {
            clearFieldError(field);
            return true;
        }

        return !setFieldError(field, message);
    }

    function validateEmail(field, message) {
        const value = String(field?.value || "").trim();
        const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

        if (value && emailPattern.test(value)) {
            clearFieldError(field);
            return true;
        }

        return !setFieldError(field, message);
    }

    function validateNumber(field, options = {}) {
        const value = String(field?.value || "").trim();
        const number = Number(value);
        const { integer = false, min, max, message } = options;

        if (!value) {
            return !setFieldError(field, message || "This field is required.");
        }

        if (!Number.isFinite(number)) {
            return !setFieldError(field, message || "Enter a valid number.");
        }

        if (integer && !Number.isInteger(number)) {
            return !setFieldError(field, message || "Enter a whole number.");
        }

        if (min !== undefined && number < min) {
            return !setFieldError(field, message || `Enter a value of at least ${min}.`);
        }

        if (max !== undefined && number > max) {
            return !setFieldError(field, message || `Enter a value of at most ${max}.`);
        }

        clearFieldError(field);
        return true;
    }

    function bindLiveValidation(scope = document) {
        const handler = (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) {
                return;
            }

            if (target.matches("input, select, textarea")) {
                clearFieldError(target);
            }
        };

        scope.addEventListener("input", handler);
        scope.addEventListener("change", handler);
    }

    window.formValidation = {
        bindLiveValidation,
        clearErrors,
        clearFieldError,
        focusFirstError,
        setFieldError,
        validateEmail,
        validateNumber,
        validateRequired
    };
})();
