from datetime import datetime, timezone
import json

import pika


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _normalize_venue(venue):
    if not isinstance(venue, dict):
        return venue

    return {
        "name": venue.get("name"),
        "address": venue.get("address"),
        "city": venue.get("city"),
        "country": venue.get("country"),
    }


def _tracked_fields(event):
    return {
        "title": event.get("title"),
        "description": event.get("description"),
        "status": event.get("status"),
        "startAt": event.get("startAt"),
        "endAt": event.get("endAt"),
        "venue": _normalize_venue(event.get("venue")),
        "cancelledAt": event.get("cancelledAt"),
        "cancellationReason": event.get("cancellationReason"),
    }


def summarize_changes(before_event, after_event):
    before_fields = _tracked_fields(before_event or {})
    after_fields = _tracked_fields(after_event or {})
    changes = []

    for field, before_value in before_fields.items():
        after_value = after_fields.get(field)
        if before_value != after_value:
            changes.append(
                {
                    "field": field,
                    "before": before_value,
                    "after": after_value,
                }
            )

    return changes


def build_refund_info(notification_type, event_id=None, ui_base_url=None):
    event_id = str(event_id or "").strip()
    ui_base_url = str(ui_base_url or "").rstrip("/")
    refund_page = (
        f"{ui_base_url}/request-refund.html?eventId={event_id}&refundContext={notification_type}"
        if ui_base_url and event_id
        else None
    )

    if notification_type == "event.cancelled":
        return {
            "requestRequired": False,
            "provider": "stripe",
            "status": "processing",
            "autoRefund": True,
            "message": (
                "Your refund is being processed automatically back to your original "
                "payment method through Stripe. No separate request is needed."
            ),
            "actionLabel": "View ticket status" if refund_page else None,
            "actionUrl": refund_page,
        }

    return {
        "requestRequired": True,
        "provider": "stripe",
        "status": "available",
        "autoRefund": False,
        "message": (
            "If the updated date or venue no longer works for you, use the refund button "
            "in My Tickets to return the ticket to your original payment method through Stripe."
        ),
        "actionLabel": "Request a refund" if refund_page else None,
        "actionUrl": refund_page,
    }


def build_event_updated_message(before_event, after_event, manager, ui_base_url=None):
    changes = summarize_changes(before_event, after_event)
    return {
        "type": "event.updated",
        "publishedAt": utc_now(),
        "eventId": after_event.get("id"),
        "managerId": after_event.get("managerId"),
        "changedBy": after_event.get("changedBy"),
        "manager": {
            "id": manager.get("id"),
            "name": manager.get("name"),
            "email": manager.get("email"),
        },
        "changes": changes,
        "eventBefore": _tracked_fields(before_event or {}),
        "eventAfter": _tracked_fields(after_event or {}),
        "refundInfo": build_refund_info(
            "event.updated", after_event.get("id"), ui_base_url=ui_base_url
        ),
    }


def build_event_cancelled_message(before_event, after_event, manager, ui_base_url=None):
    changes = summarize_changes(before_event, after_event)
    return {
        "type": "event.cancelled",
        "publishedAt": utc_now(),
        "eventId": after_event.get("id"),
        "managerId": after_event.get("managerId"),
        "changedBy": after_event.get("changedBy"),
        "manager": {
            "id": manager.get("id"),
            "name": manager.get("name"),
            "email": manager.get("email"),
        },
        "changes": changes,
        "eventBefore": _tracked_fields(before_event or {}),
        "eventAfter": _tracked_fields(after_event or {}),
        "refundInfo": build_refund_info(
            "event.cancelled", after_event.get("id"), ui_base_url=ui_base_url
        ),
    }


def publish_message(rabbitmq_url, exchange, routing_key, payload):
    parameters = pika.URLParameters(rabbitmq_url)
    connection = pika.BlockingConnection(parameters)
    try:
        channel = connection.channel()
        channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=json.dumps(payload),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )
    finally:
        connection.close()
