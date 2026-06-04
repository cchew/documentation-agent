#!/usr/bin/env bash
# Deploy the doco-agent AWS stack.
# Requires: AWS CLI configured, Rust toolchain + cargo-lambda, CDK venv at infra/aws/cdk/.venv
# Assumes SSM secrets at /doco-agent/* have been set manually (see DEPLOY.md step 1).

set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-2}"
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
API_LAMBDA_DIR="$REPO_ROOT/infra/aws/api-lambda"
CDK_DIR="$REPO_ROOT/infra/aws/cdk"

echo "==> Checking prerequisites..."
missing_tools=()
for tool in aws cargo cdk node; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    missing_tools+=("$tool")
  fi
done
if ! cargo lambda --version >/dev/null 2>&1; then
  missing_tools+=("cargo-lambda")
fi
if [ ! -d "$CDK_DIR/.venv" ]; then
  missing_tools+=("infra/aws/cdk/.venv (run: cd infra/aws/cdk && python3 -m venv .venv && pip install -r requirements.txt)")
fi
if [ ${#missing_tools[@]} -gt 0 ]; then
  echo "ERROR: missing prerequisites:"
  printf '  - %s\n' "${missing_tools[@]}"
  echo "See DEPLOY.md Prerequisites section."
  exit 1
fi

echo "==> Checking SSM parameters exist in $REGION..."
missing=()
for p in "${SSM_PARAMS[@]}"; do
  if ! aws ssm get-parameter --region "$REGION" --name "$p" >/dev/null 2>&1; then
    missing+=("$p")
  fi
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "ERROR: missing SSM parameters:"
  printf '  %s\n' "${missing[@]}"
  echo "Set them manually per DEPLOY.md step 1, then re-run."
  exit 1
fi

echo "==> Building Rust API Lambda (arm64)..."
cd "$API_LAMBDA_DIR"
cargo lambda build --release --arm64

echo "==> Activating CDK venv..."
cd "$CDK_DIR"
source .venv/bin/activate

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_ACCOUNT="$ACCOUNT"

if ! aws cloudformation describe-stacks --region "$REGION" --stack-name CDKToolkit >/dev/null 2>&1; then
  echo "==> Bootstrapping CDK (first-time setup) in aws://$ACCOUNT/$REGION..."
  cdk bootstrap "aws://$ACCOUNT/$REGION"
else
  echo "==> CDK already bootstrapped, skipping."
fi

echo "==> Deploying stack..."
cdk deploy --require-approval never

echo "==> Deploy complete. Note the SlackWebhookUrl in the outputs above."
