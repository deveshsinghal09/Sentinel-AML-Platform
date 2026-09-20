"""AWS settings and the standard boto3 credential provider chain."""
import os


def enabled() -> bool:
    # A copied example file may enable the feature flag before resource outputs
    # are filled in. Keep the existing local persistence active until AWS mode
    # is fully configured rather than failing halfway through a local workflow.
    resources = ("AWS_S3_BUCKET", "AWS_DYNAMODB_TABLE", "AWS_SNS_TOPIC_ARN")
    return (os.getenv("AWS_ENABLED", "false").lower() == "true"
            and all(os.getenv(name, "").strip() for name in resources))


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required in AWS mode")
    return value


def client(service: str):
    import boto3
    from botocore.config import Config

    return boto3.client(service, region_name=os.getenv("AWS_REGION", "ap-south-1"),
                        config=Config(connect_timeout=5, read_timeout=60,
                                      retries={"mode": "standard", "max_attempts": 3}))
