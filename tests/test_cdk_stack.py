import os
import sys
import pytest

# CDK tests require aws-cdk-lib; skip if not installed
pytest.importorskip("aws_cdk")

import aws_cdk as cdk
from aws_cdk.assertions import Template

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "infra", "aws", "cdk"))
from doco_agent_stack import DocoAgentStack


@pytest.fixture(scope="module")
def template() -> Template:
    # Passing bundling-stacks=[] via context tells CDK to skip all asset bundling.
    # This avoids Docker/pip bundling during unit tests; we only care about template shape.
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    stack = DocoAgentStack(app, "TestStack", env=cdk.Environment(account="123456789012", region="ap-southeast-2"))
    return Template.from_stack(stack)


def test_dlq_max_receive_count(template: Template) -> None:
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "RedrivePolicy": {
                "maxReceiveCount": 3,
            }
        },
    )


def test_dynamodb_pay_per_request(template: Template) -> None:
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"BillingMode": "PAY_PER_REQUEST"},
    )


def test_api_lambda_arm64(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "doco-agent-api",
            "Architectures": ["arm64"],
        },
    )


def test_worker_lambda_arm64_python311(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "doco-agent-worker",
            "Architectures": ["arm64"],
            "Runtime": "python3.11",
        },
    )
