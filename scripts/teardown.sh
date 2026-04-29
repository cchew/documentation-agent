#!/usr/bin/env bash
# Full teardown of the doco-agent AWS stack.
# Requires: AWS CLI configured, CDK venv at infra/aws/cdk/.venv

set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-2}"
TABLE_NAME="doco-agent-articles"
SSM_PARAMS=(
  /doco-agent/anthropic-api-key
  /doco-agent/slack-bot-token
  /doco-agent/slack-signing-secret
  /doco-agent/confluence-base-url
  /doco-agent/confluence-email
  /doco-agent/confluence-api-token
  /doco-agent/confluence-space-key
)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CDK_DIR="$REPO_ROOT/infra/aws/cdk"

echo "==> Destroying CDK stack..."
cd "$CDK_DIR"
source .venv/bin/activate
cdk destroy --force

echo "==> Deleting DynamoDB table ($TABLE_NAME)..."
aws dynamodb delete-table --region "$REGION" --table-name "$TABLE_NAME"

echo "==> Deleting SSM parameters..."
aws ssm delete-parameters --region "$REGION" --names "${SSM_PARAMS[@]}"

echo "==> Teardown complete."
