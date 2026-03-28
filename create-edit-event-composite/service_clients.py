import requests


class ServiceError(Exception):
    def __init__(self, status_code, code, message, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.payload = payload or {}


def request_json(method, url, payload=None, timeout=8):
    try:
        response = requests.request(method, url, json=payload, timeout=timeout)
    except requests.RequestException as error:
        raise ServiceError(
            502,
            "DEPENDENCY_UNAVAILABLE",
            f"Dependency request failed: {url}",
            {"error": str(error)},
        ) from error

    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}

    return response.status_code, body


def unwrap_data(body):
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def validate_manager_access(user_service_url, manager_id, timeout):
    code, body = request_json("GET", f"{user_service_url}/user/{manager_id}", timeout=timeout)
    if code == 404:
        raise ServiceError(404, "MANAGER_NOT_FOUND", "Manager user was not found", body)
    if code != 200:
        raise ServiceError(code, "USER_SERVICE_ERROR", "User Service rejected the request", body)

    user = unwrap_data(body)
    if user.get("role") != "manager":
        raise ServiceError(
            403,
            "MANAGER_ACCESS_DENIED",
            "Only manager users can access this composite service",
            user,
        )
    return user


def validate_seat_inventory_mapping(
    seat_inventory_url, seat_inventory_event_id, expected_categories, timeout
):
    inventory_summary = get_seat_inventory_inventory(
        seat_inventory_url,
        seat_inventory_event_id,
        timeout,
    )
    inventory = inventory_summary["inventory"]
    available_categories = {row["seatCategory"].upper() for row in inventory if row.get("seatCategory")}
    required_categories = {category.upper() for category in expected_categories}
    missing_categories = sorted(required_categories - available_categories)

    if missing_categories:
        raise ServiceError(
            409,
            "SEAT_CATEGORY_MISMATCH",
            "Seat Inventory is missing pricing tier categories required by the event",
            {
                "seatInventoryEventId": seat_inventory_event_id,
                "missingCategories": missing_categories,
                "availableCategories": sorted(available_categories),
            },
        )

    return {
        "seatInventoryEventId": seat_inventory_event_id,
        "inventory": inventory,
        "availableCategories": sorted(available_categories),
    }


def list_events_for_manager(event_service_url, manager_id, timeout):
    code, body = request_json(
        "GET",
        f"{event_service_url}/events?managerId={manager_id}",
        timeout=timeout,
    )
    if code != 200:
        raise ServiceError(code, "EVENT_LIST_FAILED", "Event list lookup failed", body)
    return unwrap_data(body)


def create_event_record(event_service_url, event_payload, timeout):
    code, body = request_json(
        "POST", f"{event_service_url}/events", payload=event_payload, timeout=timeout
    )
    if code != 201:
        raise ServiceError(code, "EVENT_CREATE_FAILED", "Event Service rejected event creation", body)
    return unwrap_data(body)


def update_event_record(event_service_url, event_id, event_payload, timeout):
    code, body = request_json(
        "PUT",
        f"{event_service_url}/events/{event_id}",
        payload=event_payload,
        timeout=timeout,
    )
    if code != 200:
        raise ServiceError(code, "EVENT_UPDATE_FAILED", "Event Service rejected event update", body)
    return unwrap_data(body)


def get_event_record(event_service_url, event_id, timeout):
    code, body = request_json("GET", f"{event_service_url}/events/{event_id}", timeout=timeout)
    if code != 200:
        raise ServiceError(code, "EVENT_LOOKUP_FAILED", "Event lookup failed", body)
    return unwrap_data(body)


def get_event_summary(event_service_url, event_id, timeout):
    code, body = request_json(
        "GET", f"{event_service_url}/events/{event_id}/summary", timeout=timeout
    )
    if code != 200:
        raise ServiceError(code, "EVENT_LOOKUP_FAILED", "Event summary lookup failed", body)
    return unwrap_data(body)


def get_seat_inventory_inventory(
    seat_inventory_url, seat_inventory_event_id, timeout, allow_missing=False
):
    code, body = request_json(
        "GET",
        f"{seat_inventory_url}/inventory/{seat_inventory_event_id}",
        timeout=timeout,
    )

    if code == 404 and allow_missing:
        return None

    if code == 404:
        raise ServiceError(
            409,
            "SEAT_INVENTORY_MAPPING_NOT_FOUND",
            "Seat Inventory has no rows for the requested seatInventoryEventId",
            body,
        )

    if code != 200:
        raise ServiceError(
            code,
            "SEAT_INVENTORY_ERROR",
            "Seat Inventory could not load the event inventory",
            body,
        )

    inventory = body.get("inventory") or []
    return {
        "seatInventoryEventId": seat_inventory_event_id,
        "inventory": inventory,
        "availableCategories": sorted(
            {row["seatCategory"].upper() for row in inventory if row.get("seatCategory")}
        ),
    }


def create_seat_inventory_record(
    seat_inventory_url, seat_inventory_event_id, seat_categories, timeout
):
    code, body = request_json(
        "POST",
        f"{seat_inventory_url}/inventory/admin/create",
        payload={
            "eventId": seat_inventory_event_id,
            "seatCategories": seat_categories,
        },
        timeout=timeout,
    )

    if code != 201:
        raise ServiceError(
            code,
            "SEAT_INVENTORY_CREATE_FAILED",
            "Seat Inventory rejected inventory bootstrap",
            body,
        )

    inventory = body.get("inventory") or []
    return {
        "seatInventoryEventId": seat_inventory_event_id,
        "inventory": inventory,
        "availableCategories": sorted(
            {row["seatCategory"].upper() for row in inventory if row.get("seatCategory")}
        ),
    }
