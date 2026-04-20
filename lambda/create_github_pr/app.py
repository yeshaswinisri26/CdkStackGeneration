import base64
import json
import os
import shutil
import urllib.parse
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

import boto3

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")

TMP_EXTRACT_DIR = os.environ.get("TMP_EXTRACT_DIR", "/tmp/extracted")


def get_github_token(secret_name: str) -> str:
    secret_value = secrets.get_secret_value(SecretId=secret_name)
    raw = secret_value.get("SecretString", "{}")
    parsed = json.loads(raw)
    token = parsed.get("token")
    if not token:
        raise ValueError("GitHub token not found in secret JSON under key 'token'")
    return token


def github_request(method: str, url: str, token: str, body=None, expected=(200, 201)):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bedrock-cdk-workflow-pr-bot"
        },
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            text = resp.read().decode("utf-8")
            if status not in expected:
                raise RuntimeError(f"GitHub API unexpected status {status}: {text}")
            return status, json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API failed: {e.code} {body_text}") from e


def download_s3_zip(bucket: str, key: str, local_path: str):
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, key, local_path)


def safe_extract_zip(zip_path: str, extract_to: str):
    if os.path.exists(extract_to):
        shutil.rmtree(extract_to)
    os.makedirs(extract_to, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            normalized = os.path.normpath(member)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError(f"Unsafe path in zip: {member}")
        zf.extractall(extract_to)


def list_files(root: str):
    result = []
    for path in Path(root).rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            result.append(rel)
    return sorted(result)


def get_branch_ref(owner: str, repo: str, branch: str, token: str):
    url = f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{urllib.parse.quote(branch, safe='')}"
    _, body = github_request("GET", url, token, expected=(200,))
    return body


def create_branch(owner: str, repo: str, branch: str, sha: str, token: str):
    url = f"https://api.github.com/repos/{owner}/{repo}/git/refs"
    payload = {
        "ref": f"refs/heads/{branch}",
        "sha": sha
    }
    github_request("POST", url, token, body=payload, expected=(201,))


def get_file_sha_if_exists(owner: str, repo: str, path: str, branch: str, token: str):
    encoded_path = urllib.parse.quote(path, safe="/")
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}?ref={urllib.parse.quote(branch, safe='')}"
    try:
        _, body = github_request("GET", url, token, expected=(200,))
        return body.get("sha")
    except RuntimeError as e:
        if "404" in str(e):
            return None
        raise


def put_file(owner: str, repo: str, path: str, branch: str, local_file_path: str, token: str):
    encoded_path = urllib.parse.quote(path, safe="/")
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"

    with open(local_file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    sha = get_file_sha_if_exists(owner, repo, path, branch, token)

    payload = {
        "message": f"Add generated file {path}",
        "content": encoded,
        "branch": branch
    }
    if sha:
        payload["sha"] = sha

    github_request("PUT", url, token, body=payload, expected=(200, 201))


def create_pull_request(owner: str, repo: str, head_branch: str, base_branch: str, title: str, body_text: str, token: str):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    payload = {
        "title": title,
        "head": head_branch,
        "base": base_branch,
        "body": body_text
    }
    _, body = github_request("POST", url, token, body=payload, expected=(201,))
    return body


def lambda_handler(event, context):
    repo_owner = event["repoOwner"]
    repo_name = event["repoName"]
    base_branch = event.get("baseBranch", "main")
    request_id = event.get("requestId", "manual")

    code_gen = event.get("codeGeneration", {})
    zip_bucket = code_gen.get("zipBucket") or event.get("generatedCodeBucket")
    zip_key = code_gen.get("zipKey")
    project_name = code_gen.get("projectName", "generated-cdk-project")

    if not zip_bucket or not zip_key:
        raise ValueError("Missing generated zip location. Expected codeGeneration.zipBucket and codeGeneration.zipKey")

    token = get_github_token(os.environ["GITHUB_SECRET_NAME"])

    zip_path = "/tmp/project.zip"
    extract_path = TMP_EXTRACT_DIR

    download_s3_zip(zip_bucket, zip_key, zip_path)
    safe_extract_zip(zip_path, extract_path)

    files = list_files(extract_path)
    if not files:
        raise ValueError("ZIP extracted successfully but no files were found")

    base_ref = get_branch_ref(repo_owner, repo_name, base_branch, token)
    base_sha = base_ref["object"]["sha"]

    branch_name = f"feature/bedrock-{request_id}"
    create_branch(repo_owner, repo_name, branch_name, base_sha, token)

    # Serial file uploads; GitHub recommends avoiding parallel create/update file requests.
    for rel_path in files:
        local_file_path = os.path.join(extract_path, rel_path)
        put_file(repo_owner, repo_name, rel_path, branch_name, local_file_path, token)

    pr_title = f"Generate infrastructure CDK for {project_name}"
    pr_body = (
        "This PR was generated automatically from an AWS architecture workflow.\n\n"
        f"- Request ID: {request_id}\n"
        f"- Source ZIP: s3://{zip_bucket}/{zip_key}\n"
        f"- Project: {project_name}\n"
    )

    pr = create_pull_request(
        repo_owner,
        repo_name,
        branch_name,
        base_branch,
        pr_title,
        pr_body,
        token
    )

    return {
        **event,
        "github": {
            "status": "COMPLETED",
            "branchName": branch_name,
            "pullRequestUrl": pr["html_url"],
            "pullRequestNumber": pr["number"]
        }
    }