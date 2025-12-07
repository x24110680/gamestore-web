import boto3
import os
import json

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL")

def main():
    if not SQS_QUEUE_URL:
        print("Missing SQS_QUEUE_URL")
        return

    sqs = boto3.client("sqs", region_name=AWS_REGION)

    response = sqs.receive_message(
        QueueUrl=SQS_QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=2
    )

    messages = response.get("Messages", [])
    if not messages:
        print("No messages available.")
    else:
        for msg in messages:
            print("Message:")
            print(json.dumps(json.loads(msg["Body"]), indent=4))

if __name__ == "__main__":
    main()