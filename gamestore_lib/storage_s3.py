import os
import boto3
from botocore.exceptions import BotoCoreError, ClientError

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")


def get_s3_client():
    return boto3.client("s3", region_name=AWS_REGION)


def upload_game_image(file_storage, filename: str) -> str:
    """
    Upload a game image to S3 and return the public URL.

    Relies on the bucket policy for public-read access. This function
    does NOT set an ACL because the bucket uses Object Ownership
    'Bucket owner enforced', which disables ACLs.
    """
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME environment variable is not set.")

    s3_client = get_s3_client()
    key = f"game-images/{filename}"

    try:
        extra_args = {
            "ContentType": file_storage.mimetype or "image/jpeg"
        }

        s3_client.upload_fileobj(
            Fileobj=file_storage,
            Bucket=S3_BUCKET_NAME,
            Key=key,
            ExtraArgs=extra_args
        )

    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Failed to upload image to S3: {e}") from e

    url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}"
    return url