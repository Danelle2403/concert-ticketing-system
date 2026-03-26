from flask import Flask, jsonify
from flask_cors import CORS
import os
import json
import threading
import time
import pika

app = Flask(__name__)
CORS(app)

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
EVENT_EXCHANGE = os.environ.get("EVENT_EXCHANGE", "ticketing.events")
DLX_EXCHANGE = os.environ.get("DLX_EXCHANGE", "ticketing.dlx")
DLQ_NAME = os.environ.get("REFUND_DLQ", "refund.request.dlq")


def connection_params():
    creds = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    return pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=creds,
        heartbeat=30,
    )


def consume_loop():
    while True:
        try:
            connection = pika.BlockingConnection(connection_params())
            channel = connection.channel()
            channel.exchange_declare(exchange=EVENT_EXCHANGE, exchange_type="topic", durable=True)
            channel.exchange_declare(exchange=DLX_EXCHANGE, exchange_type="topic", durable=True)
            channel.queue_declare(queue=DLQ_NAME, durable=True)
            channel.queue_bind(
                exchange=DLX_EXCHANGE,
                queue=DLQ_NAME,
                routing_key="refund.request.failed",
            )

            def callback(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = {}

                if "reason" not in payload:
                    payload["reason"] = "Refund request moved to DLQ after retry exhaustion"

                # send failure response for refund-composite orchestration
                channel.basic_publish(
                    exchange=EVENT_EXCHANGE,
                    routing_key="refund.response.failed",
                    body=json.dumps(payload),
                    properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
                )

                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_qos(prefetch_count=20)
            channel.basic_consume(queue=DLQ_NAME, on_message_callback=callback)
            channel.start_consuming()
        except Exception as e:
            print(f"[dead-letter-consumer] reconnect after error: {e}")
            time.sleep(2)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Dead Letter Consumer is running"}), 200


if __name__ == "__main__":
    t = threading.Thread(target=consume_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
