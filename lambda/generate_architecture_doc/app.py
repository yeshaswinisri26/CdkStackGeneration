import json
import logging
import os
import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_config = Config(
    read_timeout=3600,
    connect_timeout=10,
    retries={"max_attempts": 3, "mode": "standard"}
)

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=os.environ.get("BEDROCK_REGION", "ap-southeast-2"),
    config=bedrock_config
)

s3 = boto3.client("s3", region_name=os.environ.get("S3_REGION", "ap-southeast-2"))

MODEL_ID = os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-4-6")

PROMPT = """
You are a Senior AWS Cloud Architect and DevOps Engineer responsible for designing production-grade, secure, and scalable cloud systems.

Analyze the provided AWS architecture diagram image carefully and generate a detailed Low-Level Design (LLD) document.

Your task is to:
1. Identify all AWS services explicitly visible in the diagram.
2. Infer all missing but required infrastructure components needed for a production-grade deployment.
3. Distinguish clearly between "visible_in_diagram" and "inferred_required" resources.
4. For each resource, provide:
   - aws_service_name
   - logical_resource_name
   - purpose
   - dependencies
   - networking_details (VPC, subnet type, routing)
   - security_considerations (IAM roles, security groups, policies)
   - scalability_config (auto scaling, concurrency, etc.)
   - confidence_score (0 to 1)
5. Identify the overall architecture pattern (e.g., serverless, microservices, event-driven).
6. Derive complete network topology including VPC, public/private subnets, NAT gateways, route tables, and internet access paths.
7. Infer IAM roles, policies, and permissions required for each service interaction.
8. Include observability components such as logging (CloudWatch), tracing, and monitoring.
9. Include security best practices such as encryption (KMS), WAF, and least-privilege IAM.
10. Highlight any ambiguities or assumptions made during inference.
11. Provide deployment order (dependency-aware sequence of resource creation).
12. Suggest optional improvements or optimizations for cost, scalability, or resilience.
13. Ensure all inferred resources are realistic and aligned with AWS best practices.
14. Do not hallucinate services that are not logically required.
15. Be conservative: only mark a resource as "visible" if clearly identifiable in the diagram.

The output must be in well-structured, professional document format (NOT JSON), suitable for direct conversion into PDF or Word document.

Follow the structure strictly below:

1. Title
   - Provide a clear title for the architecture (e.g., "AWS Serverless Web Application Architecture - Low Level Design")

2. Overview
   - Brief description of the system purpose and functionality
   - High-level explanation of how the system works

3. Architecture Summary
   - Identify architecture type (e.g., serverless, microservices, event-driven)
   - Key design principles used (scalability, fault tolerance, decoupling)

4. Detailed Component Design
   For each AWS service:
   - Service Name
   - Purpose
   - Configuration Details (runtime, scaling, memory, etc.)
   - Interaction with other components
   - Data flow description

5. Network Architecture
   - VPC design (CIDR, public/private subnets)
   - Routing (Internet Gateway, NAT Gateway)
   - Security Groups and NACLs
   - Traffic flow explanation

6. Compute Layer
   - Lambda, ECS, Fargate usage
   - Scaling strategy (auto scaling, concurrency)
   - Execution flow

7. Storage Layer
   - S3 usage (buckets, access patterns)
   - Data lifecycle and durability

8. Orchestration and Workflow
   - Step Functions workflow explanation
   - Sequence of execution

9. Security and IAM
   - IAM roles and policies for each component
   - Least privilege principles
   - Encryption (KMS if applicable)

10. Observability and Monitoring
   - CloudWatch logs, metrics, alarms
   - Tracing if applicable

11. Deployment Architecture
   - Resource creation order
   - Dependencies between services
   - CI/CD considerations

12. Inferred Missing Components
   - List components not visible but required (e.g., IAM roles, NAT Gateway, route tables)
   - Explain why each is needed

13. Assumptions
   - Clearly state assumptions made during analysis

14. Improvements and Recommendations
   - Cost optimization
   - Performance improvements
   - Security enhancements

15. Conclusion
   - Summary of architecture strengths

Formatting Rules:
- Use clear headings and subheadings
- Use bullet points where appropriate
- Keep language professional and precise
- Avoid JSON or code-style output
- Ensure readability for architects and engineers

Important Constraints:
- Clearly distinguish between visible components and inferred components
- Do not hallucinate unnecessary services
- Ensure all recommendations follow AWS best practices
- Be concise but sufficiently detailed for implementation

Output must be clean, structured, and directly usable as a formal Low-Level Design document.
"""


# ===============================
# Extract Bedrock text
# ===============================
def extract_text(response: dict) -> str:
    content_blocks = response.get("output", {}).get("message", {}).get("content", [])
    texts = []

    for block in content_blocks:
        if "text" in block and block["text"]:
            texts.append(block["text"])

    return "\n".join(texts).strip()


# ===============================
# Lambda Handler
# ===============================
def lambda_handler(event, context):
    logger.info("===== STEP: Generate Architecture Document =====")
    logger.info("Input event: %s", json.dumps(event))

    # ===============================
    # Read input from workflow
    # ===============================
    image_bucket = event["imageBucket"]
    image_key = event["imageKey"]

    architecture_doc_bucket = event["architectureDocBucket"]

    # optional override
    architecture_doc_key = event.get(
        "architectureDocKey",
        f"output/{image_key.rsplit('.', 1)[0]}.txt"
    )

    logger.info("Reading image from s3://%s/%s", image_bucket, image_key)

    s3_obj = s3.get_object(Bucket=image_bucket, Key=image_key)
    image_bytes = s3_obj["Body"].read()

    logger.info("Read %d bytes from image", len(image_bytes))

    # ===============================
    # Call Bedrock
    # ===============================
    logger.info("Calling Bedrock...")

    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": "png",
                            "source": {
                                "bytes": image_bytes
                            }
                        }
                    },
                    {
                        "text": PROMPT
                    }
                ]
            }
        ],
        inferenceConfig={
            "maxTokens": 4000,
            "temperature": 0.0
        }
    )

    logger.info("Bedrock response received")

    text = extract_text(response)

    if not text:
        logger.error("No text returned from Bedrock")
        raise ValueError("Bedrock returned empty response")

    logger.info("Generated document size: %d chars", len(text))

    # ===============================
    # Store output in S3
    # ===============================
    logger.info("Writing doc to s3://%s/%s", architecture_doc_bucket, architecture_doc_key)

    s3.put_object(
        Bucket=architecture_doc_bucket,
        Key=architecture_doc_key,
        Body=text.encode("utf-8"),
        ContentType="text/plain"
    )

    # ===============================
    # Return for next step
    # ===============================
    return {
        **event,
        "architectureGeneration": {
            "status": "COMPLETED",
            "outputBucket": architecture_doc_bucket,
            "outputKey": architecture_doc_key,
            "docLocation": f"s3://{architecture_doc_bucket}/{architecture_doc_key}"
        }
    }