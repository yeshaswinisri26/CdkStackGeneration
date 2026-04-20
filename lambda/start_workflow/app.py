import json
import os
import uuid

import boto3

sfn = boto3.client("stepfunctions")


def lambda_handler(event, context):
    state_machine_arn = os.environ["STATE_MACHINE_ARN"]
    request_id = event.get("requestId") or str(uuid.uuid4())

    payload = {
        "requestId": request_id,
        "imageBucket": event["imageBucket"],
        "imageKey": event["imageKey"],
        "architectureDocBucket": event["architectureDocBucket"],
        "architectureDocKey": event["architectureDocKey"],
        "generatedCodeBucket": event["generatedCodeBucket"],
        "repoOwner": event["repoOwner"],
        "repoName": event["repoName"],
        "baseBranch": event.get("baseBranch", "main"),
        "mode": event.get("mode", "NEW_INFRA")
    }

    response = sfn.start_execution(
        stateMachineArn=state_machine_arn,
        name=f"new-infra-{request_id}",
        input=json.dumps(payload)
    )

    return {
        "executionArn": response["executionArn"],
        "requestId": request_id
    }