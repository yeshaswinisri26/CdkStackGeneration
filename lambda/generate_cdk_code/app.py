import os
import boto3
import zipfile
from botocore.config import Config

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=os.environ.get("BEDROCK_REGION", "ap-southeast-2"),
    config=Config(
        read_timeout=3600,
        connect_timeout=10,
        retries={"max_attempts": 3, "mode": "standard"},
    ),
)

s3 = boto3.client("s3", region_name=os.environ.get("S3_REGION", "ap-southeast-2"))

MODEL_ID = os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-4-6")

PROMPT_TEMPLATE = """
You are a senior AWS CDK architect and expert Java developer.

Your task is to convert the provided AWS Low-Level Design document into a complete, production-ready AWS CDK project in Java.

Generate the code as a multi-file project, not as a single file.

Requirements:
1. Use AWS CDK v2 in Java.
2. Use Maven project structure.
3. Generate a complete project that can be compiled and deployed with `mvn clean package` and `cdk deploy`.
4. Include all required files such as:
   - pom.xml
   - cdk.json
   - README.md
   - src/main/java/.../application/App.java
   - src/main/java/.../resources/S3Resources.java
   - src/main/java/.../resources/LambdaResources.java
   - src/main/java/.../resources/StepfunctionResources.java
   - src/main/java/.../stacks/MainStack.java
   - additional construct classes if needed
5. Use clear package naming: `com.example.architecture`.
6. Translate the architecture document into AWS CDK resources as accurately as possible.
7. For networking, include VPC, subnets, gateways, route tables, and security groups where required.
8. For compute, include Lambda, ECS, Fargate, Step Functions, IAM roles, and related policies where required.
9. For storage, include S3 buckets and relevant permissions.
10. Use least-privilege IAM wherever possible.
11. Avoid placeholders unless ambiguity is unavoidable.
12. If something is ambiguous, make a reasonable assumption and document it in README.md.

Output format rules:

PROJECT_NAME: aws-cdk-java-project

FILE_PATH: <relative path>
FILE_CONTENT_START
<full file content>
FILE_CONTENT_END

No explanations.

Architecture document:
---
{architecture_doc}
---
"""


def _extract_text(response: dict) -> str:
    content_blocks = response.get("output", {}).get("message", {}).get("content", [])
    texts = []
    for block in content_blocks:
        if "text" in block and block["text"]:
            texts.append(block["text"])
    return "\n".join(texts).strip()


def parse_project_files(text: str):
    lines = text.splitlines()

    project_name = None
    files = []
    current_path = None
    current_content = []

    for line in lines:
        if line.startswith("PROJECT_NAME:"):
            project_name = line.split(":", 1)[1].strip()
        elif line.startswith("FILE_PATH:"):
            current_path = line.split(":", 1)[1].strip()
            current_content = []
        elif line.strip() == "FILE_CONTENT_START":
            continue
        elif line.strip() == "FILE_CONTENT_END":
            files.append({
                "path": current_path,
                "content": "\n".join(current_content)
            })
            current_path = None
            current_content = []
        else:
            if current_path:
                current_content.append(line)

    if not project_name:
        raise ValueError("PROJECT_NAME not found")
    if not files:
        raise ValueError("No files parsed")

    return project_name, files


def create_zip(project_name: str, files: list[dict]) -> str:
    base_dir = f"/tmp/{project_name}"
    zip_path = f"/tmp/{project_name}.zip"

    for file in files:
        file_path = os.path.join(base_dir, file["path"])
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(file["content"])

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, filenames in os.walk(base_dir):
            for name in filenames:
                full_path = os.path.join(root, name)
                arcname = os.path.relpath(full_path, base_dir)
                z.write(full_path, arcname)

    return zip_path


def lambda_handler(event, context):
    # Input expected from Step Functions
    architecture_doc_bucket = event["architectureDocBucket"]
    architecture_doc_key = event["architectureDocKey"]
    generated_code_bucket = event["generatedCodeBucket"]

    print(f"Reading architecture doc from s3://{architecture_doc_bucket}/{architecture_doc_key}")
    obj = s3.get_object(Bucket=architecture_doc_bucket, Key=architecture_doc_key)
    architecture_doc = obj["Body"].read().decode("utf-8")

    prompt = PROMPT_TEMPLATE.replace("{architecture_doc}", architecture_doc)

    print("Calling Bedrock for CDK generation...")
    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}]
            }
        ],
        inferenceConfig={
            "maxTokens": 12000,
            "temperature": 0.0
        }
    )

    generated_text = _extract_text(response)

    print("Parsing model output...")
    project_name, files = parse_project_files(generated_text)

    print(f"Creating ZIP for project: {project_name}")
    zip_path = create_zip(project_name, files)

    zip_key = f"generated-projects/{project_name}.zip"

    print(f"Uploading ZIP to s3://{generated_code_bucket}/{zip_key}")
    s3.upload_file(zip_path, generated_code_bucket, zip_key)

    # Return full workflow state + step output for next task
    return {
        **event,
        "codeGeneration": {
            "status": "COMPLETED",
            "projectName": project_name,
            "zipBucket": generated_code_bucket,
            "zipKey": zip_key,
            "zipLocation": f"s3://{generated_code_bucket}/{zip_key}"
        }
    }