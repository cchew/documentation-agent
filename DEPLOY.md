# AWS Deployment

Full walkthrough for deploying the Documentation Agent to AWS. Estimated time: ~30 minutes.

## Architecture

```
Slack shortcut
  → API Gateway (HTTP API)
  → Rust Lambda (HMAC verify + enqueue)
  → SQS queue
  → Python worker Lambda
  → Claude API → DynamoDB + Confluence + Slack
```

Secrets live in SSM Parameter Store and are resolved at Lambda cold-start. No secrets in environment variables or source code.

## Prerequisites

- AWS account with CLI configured (`aws configure` or assume a role)
- [AWS CDK CLI](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html): `npm install -g aws-cdk`
- [Rust toolchain](https://rustup.rs/) + ARM64 target: `rustup target add aarch64-unknown-linux-musl`
- [cargo-lambda](https://www.cargo-lambda.info/): `pip install cargo-lambda` or `brew install cargo-lambda`
- Python 3.12+ for CDK

---

## Step 0: IAM permissions for the deploying principal

If your IAM user/role has `AdministratorAccess`, skip this step.

For a least-privilege setup, two policies are provided in [`infra/aws/cdk/`](infra/aws/cdk/):

- [`bootstrap-policy.json`](infra/aws/cdk/bootstrap-policy.json) — broader perms needed **once** to run `cdk bootstrap` (creates IAM roles, S3 bucket, ECR repo, SSM parameter for the CDK toolkit). Detach after Step 3.
- [`deploy-policy.json`](infra/aws/cdk/deploy-policy.json) — minimal perms for steady-state deploys. Covers app-secret SSM writes (`/doco-agent/*`), assuming the CDK-created `cdk-*` roles, and reading CFN state. CDK then assumes its own roles to actually create resources.

Attach the bootstrap policy first:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
USER=$(aws sts get-caller-identity --query Arn --output text | awk -F/ '{print $NF}')

aws iam put-user-policy \
  --user-name "$USER" \
  --policy-name DocoAgentCdkBootstrap \
  --policy-document file://infra/aws/cdk/bootstrap-policy.json
```

After Step 3 (CDK bootstrap) completes, swap to the narrower policy:

```bash
aws iam delete-user-policy --user-name "$USER" --policy-name DocoAgentCdkBootstrap

aws iam put-user-policy \
  --user-name "$USER" \
  --policy-name DocoAgentCdkDeploy \
  --policy-document file://infra/aws/cdk/deploy-policy.json
```

The deploy policy works because `cdk deploy` does not create resources directly with your user's credentials — it assumes the `cdk-hnb659fds-deploy-role-*` IAM role created during bootstrap, and that role holds the broad permissions needed for CloudFormation execution.

If you're using an IAM role instead of a user, swap `put-user-policy`/`delete-user-policy` for `put-role-policy`/`delete-role-policy` and `--user-name` for `--role-name`.

---

## Step 1: Store secrets in SSM Parameter Store

All secrets are stored as `SecureString` parameters in SSM. Run the following, replacing each value:

```bash
AWS_REGION=ap-southeast-2

aws ssm put-parameter --region $AWS_REGION \
  --name /doco-agent/anthropic-api-key \
  --value "sk-ant-..." --type SecureString

aws ssm put-parameter --region $AWS_REGION \
  --name /doco-agent/slack-bot-token \
  --value "xoxb-..." --type SecureString

aws ssm put-parameter --region $AWS_REGION \
  --name /doco-agent/slack-signing-secret \
  --value "your-signing-secret" --type SecureString

aws ssm put-parameter --region $AWS_REGION \
  --name /doco-agent/confluence-base-url \
  --value "https://yourname.atlassian.net/wiki" --type SecureString

aws ssm put-parameter --region $AWS_REGION \
  --name /doco-agent/confluence-email \
  --value "you@example.com" --type SecureString

aws ssm put-parameter --region $AWS_REGION \
  --name /doco-agent/confluence-api-token \
  --value "your-api-token" --type SecureString

aws ssm put-parameter --region $AWS_REGION \
  --name /doco-agent/confluence-space-key \
  --value "DEMO" --type SecureString
```

---

## Step 2: Build the Rust API Lambda

```bash
cd infra/aws/api-lambda
cargo lambda build --release --arm64
```

Output binary: `target/lambda/api-lambda/bootstrap`

---

## Step 3: Bootstrap CDK (first time only)

```bash
cd infra/aws/cdk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Bootstrap CDK in your account/region
CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/ap-southeast-2
```

---

## Step 4: Deploy

```bash
cd infra/aws/cdk
source .venv/bin/activate

CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
cdk deploy
```

CDK will print the stack outputs when complete. Note the `SlackWebhookUrl` output.

---

## Step 5: Configure Slack

Update your Slack app's shortcut Request URL to the `SlackWebhookUrl` from step 4:

```
https://<api-id>.execute-api.ap-southeast-2.amazonaws.com/slack/actions
```

Slack shortcut → App Settings → Interactivity & Shortcuts → update Request URL.

---

## Step 6: Smoke test

1. Trigger the ⚡ shortcut on any Slack thread
2. Watch the SQS queue drain (Lambda picks up within seconds)
3. Confirm a KB article appears in Confluence
4. Confirm the Slack Block Kit response appears in the thread

---

## Monitoring

- **CloudWatch Alarms:** `doco-agent-alarms` SNS topic fires on Lambda errors, DLQ depth, or DynamoDB user errors. Subscribe an email:
  ```bash
  aws sns subscribe \
    --topic-arn <AlarmTopicArn from stack outputs> \
    --protocol email \
    --notification-endpoint you@example.com
  ```
- **X-Ray traces:** both Lambdas have active tracing enabled — view in AWS Console → X-Ray
- **Budget:** monthly spend alert at $10 USD configured in CDK

---

## Teardown

```bash
cd infra/aws/cdk
source .venv/bin/activate
cdk destroy
```

Note: DynamoDB table has `RemovalPolicy.RETAIN` — delete manually if you want a full teardown:

```bash
aws dynamodb delete-table --table-name doco-agent-articles
```

---

## GitHub Actions automated deploy

See [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml). Requires:

- `AWS_DEPLOY_ROLE_ARN` secret in GitHub — an IAM role with OIDC trust for your repo
- The workflow builds the Rust Lambda and runs `cdk deploy --require-approval never`
