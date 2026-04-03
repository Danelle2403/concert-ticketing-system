import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests

import event_bus
import service_clients


def env_flag(name, default=False):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


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


def get_bearer_authorization():
    header = str(request.headers.get("Authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        return None
    return header


def authenticate_manager_request(user_service_url, timeout):
    authorization = get_bearer_authorization()
    if not authorization:
        raise service_clients.ServiceError(401, "AUTH_REQUIRED", "Authentication is required")

    try:
        response = requests.request(
            "GET",
            f"{user_service_url.rstrip('/')}/auth/me",
            timeout=timeout,
            headers={"Authorization": authorization},
        )
    except requests.RequestException as error:
        raise service_clients.ServiceError(
            502,
            "AUTH_SERVICE_UNAVAILABLE",
            "Authentication lookup failed",
            {"error": str(error)},
        ) from error

    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}

    if response.status_code != 200:
        raise service_clients.ServiceError(
            401,
            "AUTH_REQUIRED",
            "Authentication is required",
            body,
        )

    user = service_clients.unwrap_data(body)
    if user.get("role") != "manager":
        raise service_clients.ServiceError(
            403,
            "MANAGER_ACCESS_DENIED",
            "Only manager users can access this composite service",
            user,
        )
    return user


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
        REFUND_SERVICE_URL=os.environ.get("REFUND_SERVICE_URL", "http://refund-composite:5000"),
        UI_BASE_URL=os.environ.get("UI_BASE_URL", "http://localhost:8080"),
        RABBITMQ_URL=os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F"),
        NOTIFICATION_EXCHANGE=os.environ.get("NOTIFICATION_EXCHANGE", "concert.events"),
        EVENT_UPDATED_ROUTING_KEY=os.environ.get("EVENT_UPDATED_ROUTING_KEY", "event.updated"),
        EVENT_CANCELLED_ROUTING_KEY=os.environ.get("EVENT_CANCELLED_ROUTING_KEY", "event.cancelled"),
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

    def queue_notification(routing_key, payload, warnings):
        if not payload.get("changes"):
            return False

        try:
            event_bus.publish_message(
                app.config["RABBITMQ_URL"],
                app.config["NOTIFICATION_EXCHANGE"],
                routing_key,
                payload,
            )
            return True
        except Exception as error:
            warnings.append(f"Event change succeeded, but fan notifications were not queued: {error}")
            return False

    def build_refund_flow_plan(event_id):
        refund_service_url = str(app.config.get("REFUND_SERVICE_URL") or "").rstrip("/")
        return {
            "requestRequired": False,
            "provider": "stripe",
            "service": "refund-composite",
            "status": "processing",
            "triggered": False,
            "eventRefundEndpoint": (
                f"{refund_service_url}/refunds/event/{event_id}" if refund_service_url else None
            ),
        }

    def trigger_event_refunds(event_id, cancellation_reason):
        refund_service_url = str(app.config.get("REFUND_SERVICE_URL") or "").rstrip("/")
        if not refund_service_url:
            raise service_clients.ServiceError(
                503,
                "REFUND_SERVICE_NOT_CONFIGURED",
                "Refund service URL is not configured",
            )

        code, body = service_clients.request_json(
            "POST",
            f"{refund_service_url}/refunds/event/{event_id}",
            payload={
                "source": "event_cancelled",
                "reason": cancellation_reason,
            },
            timeout=app.config["REQUEST_TIMEOUT_SECONDS"],
        )
        if code != 200:
            raise service_clients.ServiceError(
                code,
                "REFUND_BATCH_FAILED",
                "Refund Composite could not process event refunds",
                body,
            )
        return body

    def handle_create_event():
        data = request.get_json(silent=True) or {}
        warnings = []

        try:
            manager = authenticate_manager_request(
                app.config["USER_SERVICE_URL"],
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )
            manager_id = int(manager["userId"])
            if data.get("managerId") is not None and extract_manager_id(data) != manager_id:
                return build_error(403, "MANAGER_NOT_OWNER", "Authenticated manager does not match managerId.")
        except ValueError as error:
            return build_error(400, "VALIDATION_ERROR", str(error))
        except service_clients.ServiceError as error:
            return build_error(error.status_code, error.code, error.message, error.payload)

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
            manager = authenticate_manager_request(
                app.config["USER_SERVICE_URL"],
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )
            manager_id = int(manager["userId"])
            if data.get("managerId") is not None and extract_manager_id(data) != manager_id:
                return build_error(403, "MANAGER_NOT_OWNER", "Authenticated manager does not match managerId.")
        except ValueError as error:
            return build_error(400, "VALIDATION_ERROR", str(error))
        except service_clients.ServiceError as error:
            return build_error(error.status_code, error.code, error.message, error.payload)

        event_payload = ensure_changed_by(build_event_payload(data, apply_defaults=False), manager_id)
        warnings = []

        try:
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
                    "notificationQueued": False,
                },
            }

            notification_payload = event_bus.build_event_updated_message(
                current_event,
                event,
                manager,
                ui_base_url=app.config.get("UI_BASE_URL"),
            )
            response_payload["integration"]["notificationQueued"] = queue_notification(
                app.config["EVENT_UPDATED_ROUTING_KEY"],
                notification_payload,
                warnings,
            )

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

    def handle_cancel_event(event_id):
        data = request.get_json(silent=True) or {}

        try:
            manager = authenticate_manager_request(
                app.config["USER_SERVICE_URL"],
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )
            manager_id = int(manager["userId"])
            if data.get("managerId") is not None and extract_manager_id(data) != manager_id:
                return build_error(403, "MANAGER_NOT_OWNER", "Authenticated manager does not match managerId.")
        except ValueError as error:
            return build_error(400, "VALIDATION_ERROR", str(error))
        except service_clients.ServiceError as error:
            return build_error(error.status_code, error.code, error.message, error.payload)

        cancel_payload = ensure_changed_by({"reason": data.get("reason")}, manager_id)
        warnings = []

        try:
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

            event = service_clients.cancel_event_record(
                app.config["EVENT_SERVICE_URL"],
                event_id,
                cancel_payload,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )

            refund_flow = build_refund_flow_plan(event_id)
            response_payload = {
                "manager": manager,
                "event": event,
                "integration": {
                    "notificationQueued": False,
                    "refundFlow": refund_flow,
                },
            }

            notification_payload = event_bus.build_event_cancelled_message(
                current_event,
                event,
                manager,
                ui_base_url=app.config.get("UI_BASE_URL"),
            )
            response_payload["integration"]["notificationQueued"] = queue_notification(
                app.config["EVENT_CANCELLED_ROUTING_KEY"],
                notification_payload,
                warnings,
            )

            try:
                refund_result = trigger_event_refunds(event_id, cancel_payload.get("reason"))
                refund_flow["triggered"] = True
                refund_flow["status"] = (
                    "completed" if refund_result.get("failed", 0) == 0 else "partial_failure"
                )
                refund_flow["summary"] = refund_result
            except service_clients.ServiceError as error:
                refund_flow["triggered"] = True
                refund_flow["status"] = "failed"
                refund_flow["error"] = {
                    "code": error.code,
                    "message": error.message,
                    "details": error.payload,
                }
                warnings.append(
                    "The event was cancelled, but the refund batch did not fully complete. "
                    "Check Refund Composite for manual follow-up."
                )

            write_audit_log(
                "CANCEL_EVENT",
                "SUCCESS",
                data,
                response_payload,
                event_id=event_id,
                manager_id=manager_id,
            )
            return build_success(
                response_payload,
                message="Manager event cancelled",
                warnings=warnings,
            )
        except service_clients.ServiceError as error:
            write_audit_log(
                "CANCEL_EVENT",
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

    @app.route("/manager/events/<event_id>/cancel", methods=["POST"])
    def cancel_event(event_id):
        return handle_cancel_event(event_id)

    @app.route("/events/<event_id>/cancel", methods=["POST"])
    def cancel_event_alias(event_id):
        return handle_cancel_event(event_id)

    @app.route("/manager/events", methods=["GET"])
    def list_manager_event_links():
        try:
            manager = authenticate_manager_request(
                app.config["USER_SERVICE_URL"],
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )
            manager_id = int(manager["userId"])
            manager_id_raw = request.args.get("managerId")
            if manager_id_raw is not None and int(manager_id_raw) != manager_id:
                return build_error(403, "MANAGER_NOT_OWNER", "Authenticated manager does not match managerId.")
            events = service_clients.list_events_for_manager(
                app.config["EVENT_SERVICE_URL"],
                manager_id,
                app.config["REQUEST_TIMEOUT_SECONDS"],
            )
        except ValueError:
            return build_error(400, "VALIDATION_ERROR", "managerId query parameter must be an integer")
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
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=env_flag("FLASK_DEBUG", False),
        use_reloader=env_flag("FLASK_USE_RELOADER", False),
    )
