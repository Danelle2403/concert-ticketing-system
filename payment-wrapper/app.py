from flask import Flask, jsonify
from flask_cors import CORS
import os
import json
import threading
import time
import uuid
import pika

app = Flask(__name__)
CORS(app)

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
EVENT_EXCHANGE = os.environ.get("EVENT_EXCHANGE", "ticketing.events")
DLX_EXCHANGE = os.environ.get("DLX_EXCHANGE", "ticketing.dlx")
REFUND_REQUEST_QUEUE = os.environ.get("REFUND_REQUEST_QUEUE", "refund.request.q")
REFUND_RESPONSE_SUCCESS_KEY = "refund.response.success"


def connection_params():
    creds = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    return pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=creds,
        heartbeat=30,
    )


def publish_success(channel, payload):
    payload["paymentRefundId"] = f"PR-{uuid.uuid4()}"
    channel.basic_publish(
        exchange=EVENT_EXCHANGE,
        routing_key=REFUND_RESPONSE_SUCCESS_KEY,
        body=json.dumps(payload),
        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
    )


def consume_loop():
    while True:
        try:
            connection = pika.BlockingConnection(connection_params())
            channel = connection.channel()
            channel.exchange_declare(exchange=EVENT_EXCHANGE, exchange_type="topic", durable=True)
            channel.exchange_declare(exchange=DLX_EXCHANGE, exchange_type="topic", durable=True)
            channel.queue_declare(
                queue=REFUND_REQUEST_QUEUE,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": DLX_EXCHANGE,
                    "x-dead-letter-routing-key": "refund.request.failed",
                },
            )
            channel.queue_bind(
                exchange=EVENT_EXCHANGE,
                queue=REFUND_REQUEST_QUEUE,
                routing_key="refund.request",
            )

            def callback(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = {}

                # if simulateFailure is set, dead-letter the message
                if payload.get("simulateFailure"):
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    return

                publish_success(ch, payload)
                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_qos(prefetch_count=20)
            channel.basic_consume(queue=REFUND_REQUEST_QUEUE, on_message_callback=callback)
            channel.start_consuming()
        except Exception as e:
            print(f"[payment-wrapper] consumer reconnect after error: {e}")
            time.sleep(2)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Payment Wrapper is running"}), 200


if __name__ == "__main__":
    t = threading.Thread(target=consume_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
