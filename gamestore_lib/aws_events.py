import os
import json
from datetime import datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")


def get_sqs_client():
    """
    Return a boto3 SQS client.
    """
    return boto3.client("sqs", region_name=AWS_REGION)


def get_sns_client():
    """
    Return a boto3 SNS client.
    """
    return boto3.client("sns", region_name=AWS_REGION)


def send_order_event_to_sqs(order_id: int, user_id: int, total: float, items: list):
    """
    Send an order event message to SQS.

    items is expected to be a list of dicts with keys such as:
        [{"game_id": 1, "title": "...", "quantity": 2, "price": 9.99}, ...]
    """
    if not SQS_QUEUE_URL:
        raise RuntimeError("SQS_QUEUE_URL environment variable is not set.")

    sqs = get_sqs_client()

    payload = {
        "order_id": order_id,
        "user_id": user_id,
        "total": total,
        "items": items,
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        "source": "game-store-web",
    }

    try:
        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(payload),
        )
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Failed to send order event to SQS: {e}") from e


def notify_order_via_sns(order_id: int, user_email: str, total: float):
    """
    Publish a simple notification to SNS when an order is placed.
    """
    if not SNS_TOPIC_ARN:
        raise RuntimeError("SNS_TOPIC_ARN environment variable is not set.")

    sns = get_sns_client()

    subject = f"New Game Store Order #{order_id}"
    message = (
        f"A new order has been placed.\n\n"
        f"Order ID: {order_id}\n"
        f"Buyer: {user_email}\n"
        f"Total: €{total:.2f}\n"
        f"Time (UTC): {datetime.utcnow().isoformat(timespec='seconds')}\n"
    )

    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message,
        )
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Failed to publish order notification to SNS: {e}") from e