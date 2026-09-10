"""Create and verify everything Second needs in AWS. Idempotent.

Run this the moment credentials exist:

    uv run python scripts/bootstrap_aws.py

It creates the DynamoDB table and the S3 bucket, checks Claude access, and
smoke-tests the pinned model id. Every step reports independently, so a partial
failure tells you which part to fix rather than stopping the whole thing.

The model smoke test is the one that earns its place. A bare foundation-model id
is the highest-probability day-one blocker in this build: Sonnet 4.6 has no
in-region endpoint outside eu-west-2, so ``anthropic.claude-sonnet-4-6`` fails
with ``ValidationException ... on-demand throughput isn't supported`` while
``global.anthropic.claude-sonnet-4-6`` works. Two minutes here saves an hour of
misdiagnosis later.
"""

from __future__ import annotations

import sys

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, TokenRetrievalError

from second.persistence.store import LivingGraphStore
from second.settings import AWS_REGION, BEDROCK_MODEL_ID, S3_BUCKET, TABLE_NAME

OK, FAIL, SKIP = "  ok  ", " FAIL ", " skip "


def report(status: str, step: str, detail: str = "") -> None:
    print(f"[{status}] {step}" + (f"\n         {detail}" if detail else ""))


def check_identity() -> bool:
    """Confirm credentials resolve at all."""
    try:
        identity = boto3.client("sts", region_name=AWS_REGION).get_caller_identity()
    except (NoCredentialsError, TokenRetrievalError) as error:
        report(FAIL, "AWS credentials", f"{error}\n         Try: aws sso login --profile second")
        return False
    except ClientError as error:
        report(FAIL, "AWS credentials", str(error))
        return False
    report(OK, "AWS credentials", f"{identity['Arn']}  (region {AWS_REGION})")
    return True


def ensure_table() -> bool:
    try:
        LivingGraphStore(table_name=TABLE_NAME, region=AWS_REGION).ensure_table()
    except ClientError as error:
        report(FAIL, f"DynamoDB table {TABLE_NAME}", str(error))
        return False
    report(OK, f"DynamoDB table {TABLE_NAME}")
    return True


def ensure_bucket() -> bool:
    """Create the voice bucket with the CORS the browser upload needs.

    The browser PUTs audio straight to S3 with a presigned URL, so the bucket
    must allow PUT from the app origin and expose no more than that.
    """
    s3 = boto3.client("s3", region_name=AWS_REGION)
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
        report(OK, f"S3 bucket {S3_BUCKET}", "already exists")
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
            report(FAIL, f"S3 bucket {S3_BUCKET}", str(error))
            return False
        try:
            s3.create_bucket(
                Bucket=S3_BUCKET,
                CreateBucketConfiguration={"LocationConstraint": AWS_REGION},
            )
            report(OK, f"S3 bucket {S3_BUCKET}", "created")
        except ClientError as create_error:
            report(FAIL, f"S3 bucket {S3_BUCKET}", f"{create_error}\n         Bucket names are global; try a suffix.")
            return False

    try:
        s3.put_bucket_cors(
            Bucket=S3_BUCKET,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedHeaders": ["content-type"],
                        "AllowedMethods": ["PUT"],
                        "AllowedOrigins": ["http://localhost:5173", "http://localhost:3000"],
                        "MaxAgeSeconds": 3000,
                    }
                ]
            },
        )
        report(OK, "S3 CORS for browser upload")
    except ClientError as error:
        report(FAIL, "S3 CORS", str(error))
        return False
    return True


def check_model_access() -> bool:
    """Confirm the Anthropic first-time-use agreement went through."""
    try:
        response = boto3.client("bedrock", region_name=AWS_REGION).get_foundation_model_availability(
            modelId="anthropic.claude-sonnet-4-6"
        )
    except ClientError as error:
        report(FAIL, "Bedrock model access", f"{error}\n         Bedrock console -> Model catalog -> Claude Sonnet 4.6 -> submit the use-case form.")
        return False
    except AttributeError:
        report(SKIP, "Bedrock model access", "installed botocore has no get_foundation_model_availability")
        return True

    agreement = response.get("agreementAvailability", {}).get("status")
    authorization = response.get("authorizationStatus")
    if agreement == "AVAILABLE" and authorization == "AUTHORIZED":
        report(OK, "Bedrock model access", f"{agreement} / {authorization}")
        return True
    report(FAIL, "Bedrock model access", f"{agreement} / {authorization} - allow up to 15 minutes after submitting.")
    return False


def smoke_test_model() -> bool:
    """Actually call the model. The only check that proves the id is right."""
    try:
        response = boto3.client("bedrock-runtime", region_name=AWS_REGION).converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": "Reply with the single word: ready"}]}],
            inferenceConfig={"maxTokens": 16},
        )
    except ClientError as error:
        hint = ""
        if "on-demand throughput" in str(error):
            hint = "\n         The model id lost its 'global.' prefix. Sonnet 4.6 has no in-region endpoint here."
        report(FAIL, f"Bedrock call ({BEDROCK_MODEL_ID})", f"{error}{hint}")
        return False

    text = response["output"]["message"]["content"][0]["text"].strip()
    usage = response.get("usage", {})
    report(OK, f"Bedrock call ({BEDROCK_MODEL_ID})", f"replied {text!r}, {usage.get('totalTokens', '?')} tokens")
    return True


def main() -> int:
    print(f"\nBootstrapping Second in {AWS_REGION}\n" + "-" * 60)
    if not check_identity():
        print("\nNothing else can run without credentials.\n")
        return 1

    results = [ensure_table(), ensure_bucket(), check_model_access(), smoke_test_model()]

    print("-" * 60)
    if all(results):
        print("All green. The live path is open.\n")
        return 0
    print(f"{results.count(False)} step(s) need attention. Each is independent; fix and re-run.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
