import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS

import service_clients


def build_success(data, status=200, message=None, warnings=None):
    payload = {"data": data}
    if message:
        payload["message"] = message
    if warnings:
        payload["warnings"] = warnings
    return jsonify(payload), status


def build_error(status, code, message, details=None):
    return (
        jsonify(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details,
                }
            }
        ),
        status,
    )


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_audit_log(action, status, request_payload, response_payload, event_id=None, manager_id=None):
    print(
        json.dumps(
            {
                "timestamp": utc_now(),
                "action": action,
                "status": status,
                "eventId": event_id,
                "managerId": manager_id,
                "request": request_payload,
                "response": response_payload,
            }
        ),
        flush=True,
    )


def extract_manager_id(data):
    manager_id = data.get("managerId")
    if manager_id is None:
        raise ValueError("managerId is required")

    try:
        return int(manager_id)
    except (TypeError, ValueError):
        raise ValueError("managerId must be an integer")


def normalize_inventory_event_id(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_code(value):
    normalized = str(value or "").strip().upper()
    return normalized or None


def build_event_payload(data, apply_defaults=False):
    event_payload = {
        key: value
        for key, value in data.items()
        if key not in {"managerId", "seatInventoryEventId"}
    }

    if apply_defaults:
        event_payload["pricingTiers"] = event_payload.get("pricingTiers") or []
        event_payload["seatSections"] = event_payload.get("seatSections") or []
    return event_payload


def ensure_changed_by(event_payload, manager_id):
    if not event_payload.get("changedBy"):
        event_payload["changedBy"] = f"manager-{manager_id}"
    return event_payload


def build_inventory_seed_rows(event_payload):
    seat_sections = event_payload.get("seatSections") or []
    if not seat_sections:
        return []

    totals_by_category = {}
    for index, seat_section in enumerate(seat_sections):
        if not isinstance(seat_section, dict):
            raise ValueError(f"seatSections[{index}] must be an object")

        tier_code = normalize_code(seat_section.get("tierCode"))
        if not tier_code:
            raise ValueError(f"seatSections[{index}].tierCode is required")

        capacity = seat_section.get("capacity")
        try:
            normalized_capacity = int(capacity)
        except (TypeError, ValueError):
            raise ValueError(
                f"seatSections[{index}].capacity must be an integer > 0 so Seat Inventory can be initialized"
            ) from None

        if normalized_capacity <= 0:
            raise ValueError(
                f"seatSections[{index}].capacity must be > 0 so Seat Inventory can be initialized"
            )

        totals_by_category[tier_code] = totals_by_category.get(tier_code, 0) + normalized_capacity

    return [
        {
            "seatCategory": seat_category,
            "totalSeats": totals_by_category[seat_category],
            "availableSeats": totals_by_category[seat_category],
        }
        for seat_category in sorted(totals_by_category)
    ]


def summarize_inventory_totals(inventory_rows):
    summary = {}
    for row in inventory_rows:
        seat_category = normalize_code(row.get("seatCategory"))
        if not seat_category:
            continue
        summary[seat_category] = int(row.get("totalSeats", 0))
    return summary


def summarize_seed_totals(seed_rows):
    return {row["seatCategory"]: int(row["totalSeats"]) for row in seed_rows}


def ensure_inventory_matches_seed_rows(inventory_summary, expected_seed_rows):
    actual_totals = summarize_inventory_totals(inventory_summary.get("inventory") or [])
    expected_totals = summarize_seed_totals(expected_seed_rows)

    if actual_totals == expected_totals:
        return {
            "seatInventoryEventId": inventory_summary["seatInventoryEventId"],
            "availableCategories": sorted(actual_totals),
            "totalSeatsByCategory": actual_totals,
        }

    raise service_clients.ServiceError(
        409,
        "SEAT_INVENTORY_UPDATE_UNSUPPORTED",
        "Requested seat configuration would require Seat Inventory totals or categories to change, but the current admin API only supports initial creation.",
        {
            "seatInventoryEventId": inventory_summary["seatInventoryEventId"],
            "expectedTotalsByCategory": expected_totals,
            "actualTotalsByCategory": actual_totals,
        },
    )


def merge_event_configuration(current_event, event_payload):
    merged_event = dict(current_event)
    merged_event.update(event_payload)
    return merged_event


def bootstrap_inventory_for_event(app, seat_inventory_event_id, inventory_seed_rows):
    timeout = app.config["REQUEST_TIMEOUT_SECONDS"]
    seat_inventory_url = app.config["SEAT_INVENTORY_URL"]

    try:
        created_inventory = service_clients.create_seat_inventory_record(
            seat_inventory_url,
            seat_inventory_event_id,
            inventory_seed_rows,
            timeout,
        )
        return ensure_inventory_matches_seed_rows(created_inventory, inventory_seed_rows)
    except service_clients.ServiceError:
        existing_inventory = service_clients.get_seat_inventory_inventory(
            seat_inventory_url,
            seat_inventory_event_id,
            timeout,
            allow_missing=True,
        )
        if existing_inventory:
            return ensure_inventory_matches_seed_rows(existing_inventory, inventory_seed_rows)
        raise


def create_app(test_config=None):
    app = Flask(__name__)
    CORS(app)

    app.config.update(
        USER_SERVICE_URL=os.environ.get("USER_SERVICE_URL", "http://localhost:5001"),
        EVENT_SERVICE_URL=os.environ.get("EVENT_SERVICE_URL", "http://localhost:5002"),
        SEAT_INVENTORY_URL=os.environ.get("SEAT_INVENTORY_URL", "http://localhost:5004"),
        REQUEST_TIMEOUT_SECONDS=int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "8")),
    )

    if test_config:
        app.config.update(test_config)

    @app.route("/health", methods=["GET"])
    def health():
        return build_success(
            {
                "status": "Create/Edit Event Composite is running",
                "dependencies": {
                    "userService": app.config["USER_SERVICE_URL"],
                    "eventService": app.config["EVENT_SERVICE_URL"],
                    "seatInventoryService": app.config["SEAT_INVENTORY_URL"],
                },
            }
        )

    def handle_create_event():
        data = request.get_json(silent=True) or {}
        warnings = []

        try:
            manager_id = extract_manager_id(data)
        except ValueError as error:
            return build_error(400, "VALIDATION_ERROR", str(error))

        requested_inventory_event_id = normalize_inventory_event_id(data.get("seatInventoryEventId"))
        event_payload = ensure_changed_by(build_event_payload(data, apply_defaults=True), manager_id)
        event_payload["managerId"] = manager_id
        requested_status = (event_payload.get("status") or "DRAFT").upper()

        try:
            inventory_seed_rows = build_inventory_seed_rows(event_payload)
        except ValueError as error:
            return build_error(400, "INVALID_SEAT_CONFIGURATION", str(error))

        if requested_inventory_event_id:
            warnings.append(
                "seatInventoryEventId is ignored on create. The composite now bootstraps Seat Inventory with the Event Service event ID."
            )

        if requested_status == "PUBLISHED" and not inventory_seed_rows:
            return build_error(
                400,
                "INVENTORY_BOOTSTRAP_REQUIRED",
                "Published manager events require seatSections with positive capacity so Seat Inventory can be initialized.",
            )

        if not inventory_seed_rows:
            warnings.append(
                "Seat Inventory was not initialized because no seatSections with positive capacity were provided yet."
            )

        try:
            manager = service_clients.validate_manager_access(
                app.config["USER_SERVICE_URL"],
                manager_id,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )

            event = service_clients.create_event_record(
                app.config["EVENT_SERVICE_URL"],
                event_payload,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )

            seat_inventory_event_id = None
            inventory_summary = None
            if inventory_seed_rows:
                try:
                    inventory_summary = bootstrap_inventory_for_event(app, event["id"], inventory_seed_rows)
                    seat_inventory_event_id = event["id"]
                except service_clients.ServiceError as error:
                    payload = {
                        "event": event,
                        "inventorySeedRows": inventory_seed_rows,
                        "inventoryError": {
                            "code": error.code,
                            "message": error.message,
                            "details": error.payload,
                        },
                    }
                    write_audit_log(
                        "CREATE_EVENT",
                        "FAILED",
                        data,
                        payload,
                        event_id=event["id"],
                        manager_id=manager_id,
                    )
                    return build_error(
                        error.status_code,
                        "INVENTORY_BOOTSTRAP_FAILED",
                        "Event Service created the event, but Seat Inventory initialization failed. Manual reconciliation is required because Event Service has no rollback endpoint.",
                        {
                            "event": event,
                            "seatInventoryEventId": event["id"],
                            "inventorySeedRows": inventory_seed_rows,
                            "inventoryError": payload["inventoryError"],
                        },
                    )

            response_payload = {
                "manager": manager,
                "event": event,
                "integration": {
                    "seatInventoryEventId": seat_inventory_event_id,
                    "inventoryBootstrap": inventory_summary,
                },
            }
            write_audit_log(
                "CREATE_EVENT",
                "SUCCESS",
                data,
                response_payload,
                event_id=event["id"],
                manager_id=manager_id,
            )
            return build_success(
                response_payload,
                status=201,
                message="Manager event created",
                warnings=warnings,
            )
        except service_clients.ServiceError as error:
            write_audit_log(
                "CREATE_EVENT",
                "FAILED",
                data,
                error.payload,
                manager_id=manager_id,
            )
            return build_error(error.status_code, error.code, error.message, error.payload)

    def handle_edit_event(event_id):
        data = request.get_json(silent=True) or {}

        try:
            manager_id = extract_manager_id(data)
        except ValueError as error:
            return build_error(400, "VALIDATION_ERROR", str(error))

        event_payload = ensure_changed_by(build_event_payload(data, apply_defaults=False), manager_id)
        warnings = []

        try:
            manager = service_clients.validate_manager_access(
                app.config["USER_SERVICE_URL"],
                manager_id,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )

            current_event = service_clients.get_event_record(
                app.config["EVENT_SERVICE_URL"],
                event_id,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )
            if current_event.get("managerId") != manager_id:
                return build_error(
                    403,
                    "MANAGER_NOT_OWNER",
                    "This event is owned by a different manager.",
                )

            seat_inventory_event_id = event_id
            requested_status = (event_payload.get("status") or current_event.get("status") or "").upper()
            configuration_change_requested = any(
                key in event_payload for key in {"pricingTiers", "seatSections"}
            )
            inventory_summary = None
            inventory_exists = False
            inventory_seed_rows = []

            existing_inventory = service_clients.get_seat_inventory_inventory(
                app.config["SEAT_INVENTORY_URL"],
                seat_inventory_event_id,
                app.config["REQUEST_TIMEOUT_SECONDS"],
                allow_missing=True,
            )
            if existing_inventory:
                inventory_exists = True
                inventory_summary = existing_inventory

            if configuration_change_requested or (requested_status == "PUBLISHED" and not inventory_exists):
                merged_event = merge_event_configuration(current_event, event_payload)
                try:
                    inventory_seed_rows = build_inventory_seed_rows(merged_event)
                except ValueError as error:
                    return build_error(400, "INVALID_SEAT_CONFIGURATION", str(error))

            if configuration_change_requested and inventory_exists:
                inventory_summary = ensure_inventory_matches_seed_rows(
                    existing_inventory,
                    inventory_seed_rows,
                )
            elif requested_status == "PUBLISHED" and not inventory_exists and not inventory_seed_rows:
                return build_error(
                    400,
                    "INVENTORY_BOOTSTRAP_REQUIRED",
                    "Published manager events require seatSections with positive capacity so Seat Inventory can be initialized.",
                )
            elif not inventory_exists and inventory_seed_rows:
                warnings.append("Seat Inventory will be initialized after the event update succeeds.")
            elif not inventory_exists:
                warnings.append("Seat Inventory is still not initialized for this event.")

            event = service_clients.update_event_record(
                app.config["EVENT_SERVICE_URL"],
                event_id,
                event_payload,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )

            if not inventory_exists and inventory_seed_rows:
                try:
                    inventory_summary = bootstrap_inventory_for_event(app, event_id, inventory_seed_rows)
                except service_clients.ServiceError as error:
                    payload = {
                        "event": event,
                        "inventorySeedRows": inventory_seed_rows,
                        "inventoryError": {
                            "code": error.code,
                            "message": error.message,
                            "details": error.payload,
                        },
                    }
                    write_audit_log(
                        "EDIT_EVENT",
                        "FAILED",
                        data,
                        payload,
                        event_id=event_id,
                        manager_id=manager_id,
                    )
                    return build_error(
                        error.status_code,
                        "INVENTORY_BOOTSTRAP_FAILED",
                        "Event Service updated the event, but Seat Inventory initialization failed. Manual reconciliation is required because Event Service has no rollback endpoint.",
                        {
                            "event": event,
                            "seatInventoryEventId": event_id,
                            "inventorySeedRows": inventory_seed_rows,
                            "inventoryError": payload["inventoryError"],
                        },
                    )

            response_payload = {
                "manager": manager,
                "event": event,
                "integration": {
                    "seatInventoryEventId": seat_inventory_event_id,
                    "inventoryValidation": inventory_summary,
                },
            }
            write_audit_log(
                "EDIT_EVENT",
                "SUCCESS",
                data,
                response_payload,
                event_id=event_id,
                manager_id=manager_id,
            )
            return build_success(
                response_payload,
                message="Manager event updated",
                warnings=warnings,
            )
        except service_clients.ServiceError as error:
            write_audit_log(
                "EDIT_EVENT",
                "FAILED",
                data,
                error.payload,
                event_id=event_id,
                manager_id=manager_id,
            )
            return build_error(error.status_code, error.code, error.message, error.payload)

    @app.route("/manager/events", methods=["POST"])
    def create_event():
        return handle_create_event()

    @app.route("/events/create", methods=["POST"])
    def create_event_alias():
        return handle_create_event()

    @app.route("/manager/events/<event_id>", methods=["PUT"])
    def edit_event(event_id):
        return handle_edit_event(event_id)

    @app.route("/events/<event_id>/edit", methods=["PUT"])
    def edit_event_alias(event_id):
        return handle_edit_event(event_id)

    @app.route("/manager/events", methods=["GET"])
    def list_manager_event_links():
        manager_id_raw = request.args.get("managerId")
        try:
            manager_id = int(manager_id_raw)
        except (TypeError, ValueError):
            return build_error(400, "VALIDATION_ERROR", "managerId query parameter is required")

        try:
            manager = service_clients.validate_manager_access(
                app.config["USER_SERVICE_URL"],
                manager_id,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )
            events = service_clients.list_events_for_manager(
                app.config["EVENT_SERVICE_URL"],
                manager_id,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )
        except service_clients.ServiceError as error:
            return build_error(error.status_code, error.code, error.message, error.payload)

        enriched = [
            {
                "eventId": event["id"],
                "managerId": event["managerId"],
                "seatInventoryEventId": event["id"],
                "eventStatus": event["status"],
                "eventTitle": event["title"],
                "eventSummary": event,
                "eventError": None,
            }
            for event in events
        ]

        return build_success({"manager": manager, "events": enriched})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
