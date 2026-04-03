from collections import OrderedDict
from datetime import datetime, timezone
import html
import json
import os
import threading
import time

from flask import Flask, jsonify, request
from flask_cors import CORS
import pika
import requests


INTERNAL_SERVICE_TOKEN = os.environ.get(
    "INTERNAL_SERVICE_TOKEN", "concert-hub-internal-dev-token"
)
INTERNAL_SERVICE_PREFIXES = ("http://user-service:",)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def env_flag(name, default=False):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def request_json(method, url, payload=None, timeout=8):
    headers = None
    if any(str(url).startswith(prefix) for prefix in INTERNAL_SERVICE_PREFIXES):
        headers = {"X-Internal-Service-Token": INTERNAL_SERVICE_TOKEN}
    response = requests.request(method, url, json=payload, timeout=timeout, headers=headers)
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    return response.status_code, body


def unwrap_data(body):
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def format_venue_label(venue):
    if not isinstance(venue, dict):
        return str(venue or "").strip()

    return ", ".join(
        [
            str(venue.get("name") or "").strip(),
            str(venue.get("city") or "").strip(),
            str(venue.get("country") or "").strip(),
        ]
    ).strip(", ")


def format_change_value(field, value):
    if value is None:
        return "Not set"

    if field in {"startAt", "endAt", "publishedAt", "cancelledAt"}:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime(
                "%d %b %Y %I:%M %p UTC"
            )
        except ValueError:
            return str(value)

    if field == "venue":
        return format_venue_label(value) or "Venue TBC"

    return str(value)


def format_money(amount, currency):
    if amount is None:
        return "Amount unavailable"
    normalized_currency = str(currency or "sgd").upper()
    return f"{normalized_currency} {float(amount):.2f}"


def build_change_lines(changes):
    lines = []
    for change in changes:
        field = change.get("field", "Field")
        label = field.replace("At", " At").replace("Id", " ID")
        lines.append(
            {
                "label": label[0].upper() + label[1:],
                "before": format_change_value(field, change.get("before")),
                "after": format_change_value(field, change.get("after")),
            }
        )
    return lines


def get_notification_type(payload):
    return str(payload.get("type") or "event.updated")


def get_event_snapshot(payload):
    event_after = payload.get("eventAfter") or {}
    event_before = payload.get("eventBefore") or {}
    return event_after or event_before


def build_default_refund_info(notification_type):
    if notification_type == "event.cancelled":
        return {
            "requestRequired": False,
            "provider": "stripe",
            "message": (
                "Your refund is being processed automatically back to your original "
                "payment method through Stripe. No separate request is needed."
            ),
            "autoRefund": True,
        }

    return {
        "requestRequired": True,
        "provider": "stripe",
        "message": (
            "If the updated event details no longer work for you, use the refund button in "
            "My Tickets to return the ticket to your original payment method through Stripe."
        ),
        "autoRefund": False,
    }


def get_refund_info(payload):
    notification_type = get_notification_type(payload)
    refund_info = payload.get("refundInfo")
    if isinstance(refund_info, dict):
        default = build_default_refund_info(notification_type)
        default.update({key: value for key, value in refund_info.items() if value is not None})
        return default
    return build_default_refund_info(notification_type)


def build_subject(payload):
    notification_type = get_notification_type(payload)
    event_snapshot = get_event_snapshot(payload)
    title = event_snapshot.get("title") or payload.get("eventId")
    if notification_type == "purchase.confirmed":
        prefix = "Purchase confirmed"
    elif notification_type == "refund.success":
        prefix = "Refund confirmed"
    elif notification_type == "refund.failure":
        prefix = "Refund requires attention"
    else:
        prefix = "Event cancelled" if notification_type == "event.cancelled" else "Event update"
    return f"{prefix}: {title}"


def build_plain_text_body(payload, recipient_name):
    notification_type = get_notification_type(payload)
    if notification_type == "purchase.confirmed":
        event_snapshot = payload.get("event") or {}
        ticket_ids = payload.get("ticketIds") or []
        return "\n".join(
            [
                f"Hi {recipient_name or 'there'},",
                "",
                f'Your purchase for "{event_snapshot.get("title") or payload.get("eventId")}" is confirmed.',
                f"Venue: {event_snapshot.get('venue') or 'Venue TBC'}",
                f"Date: {event_snapshot.get('date') or 'Date TBC'}",
                f"Purchase ID: {payload.get('purchaseId')}",
                f"Amount paid: {format_money(payload.get('amountPaid'), payload.get('currency'))}",
                f"Ticket IDs: {', '.join(ticket_ids) if ticket_ids else 'Pending'}",
                "",
                "Keep this email as your receipt and refer to My Tickets for your latest ticket status.",
                "",
                "Concert Hub",
            ]
        )

    if notification_type == "refund.success":
        event_snapshot = payload.get("event") or {}
        return "\n".join(
            [
                f"Hi {recipient_name or 'there'},",
                "",
                f'Your refund for "{event_snapshot.get("title") or payload.get("eventId")}" has been processed successfully.',
                f"Ticket ID: {payload.get('ticketId')}",
                f"Refund ID: {payload.get('refundId')}",
                f"Amount refunded: {format_money(payload.get('amountPaid'), payload.get('currency'))}",
                "",
                "The refund will appear on your original payment method once Stripe and your bank complete processing.",
                "",
                "Concert Hub",
            ]
        )

    if notification_type == "refund.failure":
        event_snapshot = payload.get("event") or {}
        support_email = payload.get("supportEmail") or "support@concerthub.local"
        source = str(payload.get("source") or "customer_request")
        manager_line = ""
        if source == "event_change_request":
            manager = payload.get("manager") or {}
            manager_line = (
                f"Event manager alerted: {manager.get('name')} <{manager.get('email')}>\n"
                if manager.get("email")
                else ""
            )
        guidance = (
            "Please contact customer support to complete the refund manually."
            if source == "event_cancelled"
            else "We have alerted the event manager and support team to follow up."
        )
        return "\n".join(
            [
                f"Hi {recipient_name or 'there'},",
                "",
                f'We could not complete the refund for "{event_snapshot.get("title") or payload.get("eventId")}".',
                f"Ticket ID: {payload.get('ticketId')}",
                f"Requested amount: {format_money(payload.get('amountPaid'), payload.get('currency'))}",
                manager_line.rstrip(),
                guidance,
                f"Support: {support_email}",
                "",
                "Concert Hub",
            ]
        ).replace("\n\n\n", "\n\n")

    event_snapshot = get_event_snapshot(payload)
    title = event_snapshot.get("title") or payload.get("eventId")
    venue = format_venue_label(event_snapshot.get("venue")) or "Venue TBC"
    start_at = format_change_value("startAt", event_snapshot.get("startAt"))
    cancelled_at = format_change_value("cancelledAt", event_snapshot.get("cancelledAt"))
    cancellation_reason = event_snapshot.get("cancellationReason") or "No reason provided"
    refund_info = get_refund_info(payload)
    lines = build_change_lines(payload.get("changes") or [])

    body = [
        f"Hi {recipient_name or 'there'},",
        "",
    ]

    if notification_type == "event.cancelled":
        action_line = (
            f"Track your refund: {refund_info['actionUrl']}"
            if refund_info.get("actionUrl")
            else None
        )
        body.extend(
            [
                f'The event "{title}" has been cancelled.',
                f"Venue: {venue}",
                f"Original start: {start_at}",
                f"Cancelled at: {cancelled_at}",
                f"Reason: {cancellation_reason}",
                "",
                f"Refund info: {refund_info['message']}",
                action_line or "No separate purchase action is needed from this email.",
                "",
                "Concert Hub",
            ]
        )
        return "\n".join(body)

    body.extend(
        [
            f'The event "{title}" has been updated.',
            f"Venue: {venue}",
            f"Start: {start_at}",
            "",
        ]
    )

    if lines:
        body.append("Changed details:")
        body.extend(
            [
                f"- {line['label']}: {line['before']} -> {line['after']}"
                for line in lines
            ]
        )
        body.append("")

    body.extend(
        [
            "Please review the updated event details before attending.",
            f"Refund info: {refund_info['message']}",
            (
                f"{refund_info.get('actionLabel')}: {refund_info.get('actionUrl')}"
                if refund_info.get("actionUrl")
                else ""
            ),
            "",
            "Concert Hub",
        ]
    )
    return "\n".join(body)


def build_html_body(payload, recipient_name):
    notification_type = get_notification_type(payload)
    if notification_type == "purchase.confirmed":
        event_snapshot = payload.get("event") or {}
        ticket_ids = payload.get("ticketIds") or []
        ticket_list = "".join([f"<li>{html.escape(str(ticket_id))}</li>" for ticket_id in ticket_ids])
        return f"""
        <div style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.6;">
          <p>Hi {html.escape(recipient_name or 'there')},</p>
          <p>Your purchase for <strong>{html.escape(str(event_snapshot.get("title") or payload.get("eventId")))}</strong> is confirmed.</p>
          <p>
            <strong>Venue:</strong> {html.escape(str(event_snapshot.get("venue") or "Venue TBC"))}<br>
            <strong>Date:</strong> {html.escape(str(event_snapshot.get("date") or "Date TBC"))}<br>
            <strong>Purchase ID:</strong> {html.escape(str(payload.get("purchaseId")))}<br>
            <strong>Amount paid:</strong> {html.escape(format_money(payload.get("amountPaid"), payload.get("currency")))}
          </p>
          <p><strong>Ticket IDs:</strong></p>
          <ul>{ticket_list or "<li>Pending</li>"}</ul>
          <p>Keep this email as your receipt and refer to My Tickets for your latest ticket status.</p>
          <p>Concert Hub</p>
        </div>
        """.strip()

    if notification_type == "refund.success":
        event_snapshot = payload.get("event") or {}
        return f"""
        <div style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.6;">
          <p>Hi {html.escape(recipient_name or 'there')},</p>
          <p>Your refund for <strong>{html.escape(str(event_snapshot.get("title") or payload.get("eventId")))}</strong> has been processed successfully.</p>
          <p>
            <strong>Ticket ID:</strong> {html.escape(str(payload.get("ticketId")))}<br>
            <strong>Refund ID:</strong> {html.escape(str(payload.get("refundId")))}<br>
            <strong>Amount refunded:</strong> {html.escape(format_money(payload.get("amountPaid"), payload.get("currency")))}
          </p>
          <p>The refund will appear on your original payment method once Stripe and your bank complete processing.</p>
          <p>Concert Hub</p>
        </div>
        """.strip()

    if notification_type == "refund.failure":
        event_snapshot = payload.get("event") or {}
        support_email = payload.get("supportEmail") or "support@concerthub.local"
        source = str(payload.get("source") or "customer_request")
        manager = payload.get("manager") or {}
        manager_html = ""
        if source == "event_change_request" and manager.get("email"):
            manager_html = (
                f"<p><strong>Event manager alerted:</strong> {html.escape(str(manager.get('name') or 'Manager'))} "
                f"&lt;{html.escape(str(manager.get('email')))}&gt;</p>"
            )
        guidance = (
            "Please contact customer support to complete the refund manually."
            if source == "event_cancelled"
            else "We have alerted the event manager and support team to follow up."
        )
        return f"""
        <div style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.6;">
          <p>Hi {html.escape(recipient_name or 'there')},</p>
          <p>We could not complete the refund for <strong>{html.escape(str(event_snapshot.get("title") or payload.get("eventId")))}</strong>.</p>
          <p>
            <strong>Ticket ID:</strong> {html.escape(str(payload.get("ticketId")))}<br>
            <strong>Requested amount:</strong> {html.escape(format_money(payload.get("amountPaid"), payload.get("currency")))}
          </p>
          {manager_html}
          <p>{html.escape(guidance)}</p>
          <p><strong>Support:</strong> {html.escape(str(support_email))}</p>
          <p>Concert Hub</p>
        </div>
        """.strip()

    event_snapshot = get_event_snapshot(payload)
    title = event_snapshot.get("title") or payload.get("eventId")
    venue = format_venue_label(event_snapshot.get("venue")) or "Venue TBC"
    start_at = format_change_value("startAt", event_snapshot.get("startAt"))
    cancelled_at = format_change_value("cancelledAt", event_snapshot.get("cancelledAt"))
    cancellation_reason = event_snapshot.get("cancellationReason") or "No reason provided"
    refund_info = get_refund_info(payload)
    lines = build_change_lines(payload.get("changes") or [])

    change_items = "".join(
        [
            "<li><strong>{label}</strong>: {before} &rarr; {after}</li>".format(
                label=html.escape(line["label"]),
                before=html.escape(line["before"]),
                after=html.escape(line["after"]),
            )
            for line in lines
        ]
    )

    if notification_type == "event.cancelled":
        action_html = (
            f'<p><a href="{html.escape(str(refund_info["actionUrl"]))}" '
            'style="display:inline-block;padding:10px 16px;background:#0f172a;color:#fff;'
            'text-decoration:none;border-radius:8px;">Track refund status</a></p>'
            if refund_info.get("actionUrl")
            else "<p>No separate purchase action is needed from this email.</p>"
        )
        return f"""
        <div style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.6;">
          <p>Hi {html.escape(recipient_name or 'there')},</p>
          <p>Your event <strong>{html.escape(str(title))}</strong> has been cancelled.</p>
          <p>
            <strong>Venue:</strong> {html.escape(venue)}<br>
            <strong>Original start:</strong> {html.escape(start_at)}<br>
            <strong>Cancelled at:</strong> {html.escape(cancelled_at)}<br>
            <strong>Reason:</strong> {html.escape(str(cancellation_reason))}
          </p>
          <p><strong>Refund info:</strong> {html.escape(refund_info["message"])}</p>
          {action_html}
          <p>Concert Hub</p>
        </div>
        """.strip()

    action_html = (
        f'<p><a href="{html.escape(str(refund_info["actionUrl"]))}" '
        'style="display:inline-block;padding:10px 16px;background:#0f172a;color:#fff;'
        'text-decoration:none;border-radius:8px;">'
        f'{html.escape(str(refund_info.get("actionLabel") or "Request a refund"))}</a></p>'
        if refund_info.get("actionUrl")
        else ""
    )

    return f"""
    <div style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.6;">
      <p>Hi {html.escape(recipient_name or 'there')},</p>
      <p>Your event <strong>{html.escape(str(title))}</strong> has been updated.</p>
      <p>
        <strong>Venue:</strong> {html.escape(venue)}<br>
        <strong>Start:</strong> {html.escape(start_at)}
      </p>
      {"<p><strong>Changed details:</strong></p><ul>" + change_items + "</ul>" if change_items else ""}
      <p>Please review the updated event details before attending.</p>
      <p><strong>Refund info:</strong> {html.escape(refund_info["message"])}</p>
      {action_html}
      <p>Concert Hub</p>
    </div>
    """.strip()


def create_app(test_config=None):
    app = Flask(__name__)
    CORS(app)

    app.config.update(
        USER_SERVICE_URL=os.environ.get("USER_SERVICE_URL", "http://user-service:5000"),
        RABBITMQ_URL=os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F"),
        NOTIFICATION_EXCHANGE=os.environ.get("NOTIFICATION_EXCHANGE", "concert.events"),
        NOTIFICATION_QUEUE=os.environ.get("NOTIFICATION_QUEUE", "notification.event-updated"),
        NOTIFICATION_ROUTING_KEYS=[],
        SENDGRID_API_KEY=os.environ.get("SENDGRID_API_KEY", ""),
        SENDGRID_FROM_EMAIL=os.environ.get("SENDGRID_FROM_EMAIL", ""),
        REQUEST_TIMEOUT_SECONDS=int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "8")),
        START_CONSUMER=os.environ.get("START_CONSUMER", "1") == "1",
    )

    if test_config:
        app.config.update(test_config)

    if not app.config["NOTIFICATION_ROUTING_KEYS"]:
        routing_keys_raw = os.environ.get("NOTIFICATION_ROUTING_KEYS")
        if routing_keys_raw:
            app.config["NOTIFICATION_ROUTING_KEYS"] = [
                key.strip() for key in routing_keys_raw.split(",") if key.strip()
            ]
        else:
            legacy_key = os.environ.get("NOTIFICATION_ROUTING_KEY", "event.updated")
            app.config["NOTIFICATION_ROUTING_KEYS"] = [legacy_key, "event.cancelled"]

    consumer_state = {
        "startedAt": utc_now(),
        "connected": False,
        "lastMessageAt": None,
        "lastError": None,
        "lastDeliveryMode": "log_only"
        if not app.config["SENDGRID_API_KEY"] or not app.config["SENDGRID_FROM_EMAIL"]
        else "sendgrid",
        "lastRecipientCount": 0,
        "lastEventId": None,
    }

    def log_json(payload):
        print(json.dumps(payload), flush=True)

    def get_ticket_holders(event_id, notification_type):
        status_code, payload = request_json(
            "GET",
            f"{app.config['USER_SERVICE_URL']}/user/tickets/by-event/{event_id}",
            timeout=app.config["REQUEST_TIMEOUT_SECONDS"],
        )
        if status_code != 200:
            raise RuntimeError(f"Unable to fetch issued tickets for event {event_id}")

        tickets = payload.get("tickets") or []
        allowed_statuses = {"active"}
        if notification_type == "event.cancelled":
            allowed_statuses = {"active", "refunded"}

        return [
            ticket
            for ticket in tickets
            if str(ticket.get("status", "")).lower() in allowed_statuses
        ]

    def resolve_recipients(event_id, notification_type):
        recipients = OrderedDict()
        tickets = get_ticket_holders(event_id, notification_type)
        for ticket in tickets:
            user_id = ticket.get("userId")
            if user_id in recipients or user_id is None:
                continue

            status_code, user_payload = request_json(
                "GET",
                f"{app.config['USER_SERVICE_URL']}/user/{user_id}",
                timeout=app.config["REQUEST_TIMEOUT_SECONDS"],
            )
            if status_code != 200:
                continue

            user = unwrap_data(user_payload)
            email = user.get("email")
            if not email:
                continue

            recipients[user_id] = {
                "userId": user_id,
                "email": email,
                "name": user.get("name") or "there",
            }

        return list(recipients.values())

    def send_direct_notification(recipients, payload):
        sent = 0
        for recipient in recipients:
            if not recipient or not recipient.get("email"):
                continue
            send_email(recipient, payload)
            sent += 1

        consumer_state["lastMessageAt"] = utc_now()
        consumer_state["lastRecipientCount"] = sent
        consumer_state["lastEventId"] = (
            (payload.get("event") or {}).get("eventId") or payload.get("eventId")
        )
        consumer_state["lastError"] = None
        return sent

    def send_email(recipient, payload):
        subject = build_subject(payload)
        plain_text = build_plain_text_body(payload, recipient.get("name"))
        html = build_html_body(payload, recipient.get("name"))

        if not app.config["SENDGRID_API_KEY"] or not app.config["SENDGRID_FROM_EMAIL"]:
            consumer_state["lastDeliveryMode"] = "log_only"
            log_json(
                {
                    "service": "notification-service",
                    "mode": "log_only",
                    "to": recipient.get("email"),
                    "subject": subject,
                    "eventId": payload.get("eventId"),
                    "changes": payload.get("changes") or [],
                }
            )
            return

        response = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {app.config['SENDGRID_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "from": {"email": app.config["SENDGRID_FROM_EMAIL"]},
                "personalizations": [{"to": [{"email": recipient.get("email")}]}],
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": plain_text},
                    {"type": "text/html", "value": html},
                ],
            },
            timeout=app.config["REQUEST_TIMEOUT_SECONDS"],
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"SendGrid rejected notification for {recipient.get('email')}: {response.status_code}"
            )
        consumer_state["lastDeliveryMode"] = "sendgrid"

    def process_notification(payload):
        event_id = payload.get("eventId")
        if not event_id:
            raise RuntimeError("eventId is required in notification payload")

        recipients = resolve_recipients(event_id, get_notification_type(payload))
        for recipient in recipients:
            send_email(recipient, payload)

        consumer_state["lastMessageAt"] = utc_now()
        consumer_state["lastRecipientCount"] = len(recipients)
        consumer_state["lastEventId"] = event_id
        consumer_state["lastError"] = None
        return {"recipients": len(recipients), "eventId": event_id}

    def ensure_topology(channel):
        channel.exchange_declare(
            exchange=app.config["NOTIFICATION_EXCHANGE"],
            exchange_type="topic",
            durable=True,
        )
        channel.queue_declare(queue=app.config["NOTIFICATION_QUEUE"], durable=True)
        for routing_key in app.config["NOTIFICATION_ROUTING_KEYS"]:
            channel.queue_bind(
                exchange=app.config["NOTIFICATION_EXCHANGE"],
                queue=app.config["NOTIFICATION_QUEUE"],
                routing_key=routing_key,
            )

    def consume_forever():
        params = pika.URLParameters(app.config["RABBITMQ_URL"])
        while True:
            connection = None
            try:
                connection = pika.BlockingConnection(params)
                channel = connection.channel()
                ensure_topology(channel)
                channel.basic_qos(prefetch_count=1)
                consumer_state["connected"] = True
                consumer_state["lastError"] = None

                def _on_message(ch, _method, _properties, body):
                    try:
                        payload = json.loads(body.decode("utf-8"))
                        process_notification(payload)
                        ch.basic_ack(delivery_tag=_method.delivery_tag)
                    except Exception as error:
                        consumer_state["lastError"] = str(error)
                        log_json(
                            {
                                "service": "notification-service",
                                "status": "message_failed",
                                "error": str(error),
                                "body": body.decode("utf-8", errors="replace"),
                            }
                        )
                        ch.basic_ack(delivery_tag=_method.delivery_tag)

                channel.basic_consume(
                    queue=app.config["NOTIFICATION_QUEUE"],
                    on_message_callback=_on_message,
                )
                channel.start_consuming()
            except Exception as error:
                consumer_state["connected"] = False
                consumer_state["lastError"] = str(error)
                log_json(
                    {
                        "service": "notification-service",
                        "status": "consumer_disconnected",
                        "error": str(error),
                    }
                )
                time.sleep(3)
            finally:
                try:
                    if connection and connection.is_open:
                        connection.close()
                except Exception:
                    pass

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify(
            {
                "status": "Notification Service is running",
                "sendgridConfigured": bool(
                    app.config["SENDGRID_API_KEY"] and app.config["SENDGRID_FROM_EMAIL"]
                ),
                "consumer": consumer_state,
                "dependencies": {
                    "userService": app.config["USER_SERVICE_URL"],
                    "rabbitmqUrl": app.config["RABBITMQ_URL"],
                    "routingKeys": app.config["NOTIFICATION_ROUTING_KEYS"],
                },
            }
        )

    @app.route("/notifications/events", methods=["POST"])
    def dispatch_direct():
        payload = request.get_json() or {}
        result = process_notification(payload)
        return jsonify({"status": "processed", **result}), 200

    @app.route("/notifications/event-updated", methods=["POST"])
    def dispatch_updated_direct():
        payload = request.get_json() or {}
        result = process_notification(payload)
        return jsonify({"status": "processed", **result}), 200

    @app.route("/notifications/event-cancelled", methods=["POST"])
    def dispatch_cancelled_direct():
        payload = request.get_json() or {}
        result = process_notification(payload)
        return jsonify({"status": "processed", **result}), 200

    @app.route("/notifications/purchase-confirmation", methods=["POST"])
    def dispatch_purchase_confirmation():
        payload = request.get_json() or {}
        payload["type"] = "purchase.confirmed"
        fan = payload.get("fan") or {
            "name": payload.get("buyerName"),
            "email": payload.get("buyerEmail"),
        }
        sent = send_direct_notification([fan], payload)
        return jsonify({"status": "processed", "recipients": sent}), 200

    @app.route("/notifications/refund-success", methods=["POST"])
    def dispatch_refund_success():
        payload = request.get_json() or {}
        payload["type"] = "refund.success"
        fan = payload.get("fan") or {}
        sent = send_direct_notification([fan], payload)
        return jsonify({"status": "processed", "recipients": sent}), 200

    @app.route("/notifications/refund-failure", methods=["POST"])
    def dispatch_refund_failure():
        payload = request.get_json() or {}
        payload["type"] = "refund.failure"
        fan = payload.get("fan") or {}
        manager = payload.get("manager") or {}
        recipients = [fan]
        if str(payload.get("source") or "") == "event_change_request":
            recipients.append(manager)
        sent = send_direct_notification(recipients, payload)
        return jsonify({"status": "processed", "recipients": sent}), 200

    if not app.config.get("TESTING") and app.config.get("START_CONSUMER", True):
        consumer_thread = threading.Thread(target=consume_forever, daemon=True)
        consumer_thread.start()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=env_flag("FLASK_DEBUG", False),
        use_reloader=env_flag("FLASK_USE_RELOADER", False),
    )
