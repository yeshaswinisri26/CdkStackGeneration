import json
import os
import urllib.request
import urllib.error

import boto3

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")

ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg")


def get_github_token(secret_name: str) -> str:
    secret_value = secrets.get_secret_value(SecretId=secret_name)
    raw = secret_value.get("SecretString", "{}")
    parsed = json.loads(raw)
    token = parsed.get("token")
    if not token:
        raise ValueError("GitHub token not found in secret JSON under key 'token'")
    return token


def github_get(url: str, token: str):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bedrock-cdk-workflow-validator"
        },
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8")


def lambda_handler(event, context):
    image_bucket = event["imageBucket"]
    image_key = event["imageKey"]
    repo_owner = event["repoOwner"]
    repo_name = event["repoName"]

    if not image_key.lower().endswith(ALLOWED_EXTENSIONS):
        raise ValueError("imageKey must be a .png, .jpg or .jpeg file")

    s3.head_object(Bucket=image_bucket, Key=image_key)

    token = get_github_token(os.environ["GITHUB_SECRET_NAME"])
    status, _ = github_get(f"https://api.github.com/repos/{repo_owner}/{repo_name}", token)
    if status != 200:
        raise ValueError(f"GitHub repo {repo_owner}/{repo_name} is not accessible")

    return {
        **event,
        "validation": {
            "status": "PASSED"
        }
    }