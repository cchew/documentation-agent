import jsii
import os.path
import shutil
import subprocess
from aws_cdk import (
    BundlingOptions,
    ILocalBundling,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as apigw_int,
    aws_budgets as budgets,
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as ddb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_events,
    aws_logs as logs,
    aws_sns as sns,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct


@jsii.implements(ILocalBundling)
class _LocalWorkerBundler:
    """Install deps and copy src locally, avoiding Docker for local synth."""

    def __init__(self, repo_root: str) -> None:
        self._repo_root = repo_root

    def try_bundle(self, output_dir: str, /, options=None, **kwargs) -> bool:
        try:
            subprocess.run(
                ["pip", "install", "-r", "requirements.txt", "-t", output_dir],
                cwd=self._repo_root, check=True, capture_output=True,
            )
            shutil.copytree(
                os.path.join(self._repo_root, "src"),
                os.path.join(output_dir, "src"),
                dirs_exist_ok=True,
            )
            return True
        except Exception:
            return False  # Fall back to Docker


class DocoAgentStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── SQS: main queue + DLQ ─────────────────────────────────────────────
        self.dlq = sqs.Queue(
            self, "DocoAgentDLQ",
            queue_name="doco-agent-dlq",
            retention_period=Duration.days(14),
        )
        self.queue = sqs.Queue(
            self, "DocoAgentQueue",
            queue_name="doco-agent-queue",
            visibility_timeout=Duration.minutes(6),
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=self.dlq),
        )

        # ── DynamoDB table ────────────────────────────────────────────────────
        self.table = ddb.Table(
            self, "DocoAgentTable",
            table_name="doco-agent-articles",
            partition_key=ddb.Attribute(name="article_id", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── SSM parameter names (injected as env vars; resolved at runtime) ──
        ssm_prefix = "/doco-agent"
        self.ssm_param_names = {
            "ANTHROPIC_API_KEY_PARAM": f"{ssm_prefix}/anthropic-api-key",
            "SLACK_BOT_TOKEN_PARAM": f"{ssm_prefix}/slack-bot-token",
            "SLACK_SIGNING_SECRET_PARAM": f"{ssm_prefix}/slack-signing-secret",
            "CONFLUENCE_BASE_URL_PARAM": f"{ssm_prefix}/confluence-base-url",
            "CONFLUENCE_EMAIL_PARAM": f"{ssm_prefix}/confluence-email",
            "CONFLUENCE_API_TOKEN_PARAM": f"{ssm_prefix}/confluence-api-token",
            "CONFLUENCE_SPACE_KEY_PARAM": f"{ssm_prefix}/confluence-space-key",
        }
        self.ssm_param_arn_prefix = self.format_arn(
            service="ssm", resource="parameter",
            resource_name="doco-agent/*",
        )

        # ── Python worker Lambda ──────────────────────────────────────────────
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

        worker_env = {
            "STORAGE_BACKEND": "dynamodb",
            "DDB_TABLE": self.table.table_name,
            **self.ssm_param_names,
        }

        self.worker_fn = lambda_.Function(
            self, "DocoAgentWorker",
            function_name="doco-agent-worker",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.ARM_64,
            handler="src.adapters.aws_lambda_worker.handler",
            code=lambda_.Code.from_asset(
                repo_root,
                exclude=[
                    "infra/**", "tests/**", "demo/**", "presentation/**",
                    "schema-validation/**", ".venv/**", ".git/**",
                    "**/__pycache__/**", "**/*.pyc", "*.md", ".env*",
                ],
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -r src /asset-output/",
                    ],
                    local=_LocalWorkerBundler(repo_root),
                ),
            ),
            timeout=Duration.minutes(5),
            memory_size=1024,
            environment=worker_env,
            tracing=lambda_.Tracing.ACTIVE,
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )

        self.queue.grant_consume_messages(self.worker_fn)
        self.table.grant_read_write_data(self.worker_fn)
        self.worker_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameters", "ssm:GetParameter"],
            resources=[self.ssm_param_arn_prefix],
        ))
        self.worker_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["kms:Decrypt"],
            resources=["*"],
            conditions={"StringEquals": {"kms:ViaService": f"ssm.{self.region}.amazonaws.com"}},
        ))

        self.worker_fn.add_event_source(lambda_events.SqsEventSource(self.queue, batch_size=1))

        # ── Rust API Lambda ───────────────────────────────────────────────────
        rust_binary_dir = os.path.join(repo_root, "infra/aws/api-lambda/target/lambda/api-lambda")

        self.api_fn = lambda_.Function(
            self, "DocoAgentApi",
            function_name="doco-agent-api",
            runtime=lambda_.Runtime.PROVIDED_AL2023,
            architecture=lambda_.Architecture.ARM_64,
            handler="bootstrap",
            code=lambda_.Code.from_asset(rust_binary_dir),
            timeout=Duration.seconds(5),
            memory_size=128,
            environment={
                "SQS_QUEUE_URL": self.queue.queue_url,
                "SLACK_SIGNING_SECRET_PARAM": self.ssm_param_names["SLACK_SIGNING_SECRET_PARAM"],
            },
            tracing=lambda_.Tracing.ACTIVE,
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )
        self.queue.grant_send_messages(self.api_fn)
        self.api_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.ssm_param_arn_prefix],
        ))
        self.api_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["kms:Decrypt"],
            resources=["*"],
            conditions={"StringEquals": {"kms:ViaService": f"ssm.{self.region}.amazonaws.com"}},
        ))

        # ── API Gateway HTTP API ──────────────────────────────────────────────
        self.http_api = apigw.HttpApi(
            self, "DocoAgentHttpApi",
            api_name="doco-agent",
            default_integration=None,
        )
        self.http_api.add_routes(
            path="/slack/actions",
            methods=[apigw.HttpMethod.POST],
            integration=apigw_int.HttpLambdaIntegration("DocoAgentApiInt", self.api_fn),
        )
        cfn_stage = self.http_api.default_stage.node.default_child
        cfn_stage.default_route_settings = {
            "throttlingBurstLimit": 10,
            "throttlingRateLimit": 5,
        }

        # ── CloudWatch alarms, SNS, Budget ────────────────────────────────────
        self.alarm_topic = sns.Topic(self, "DocoAgentAlarms", topic_name="doco-agent-alarms")

        def _alarm(name: str, metric: cw.IMetric, threshold: float = 0) -> None:
            cw.Alarm(
                self, name,
                metric=metric,
                threshold=threshold,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            ).add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        _alarm("ApiLambdaErrors", self.api_fn.metric_errors(period=Duration.minutes(5)))
        _alarm("WorkerLambdaErrors", self.worker_fn.metric_errors(period=Duration.minutes(5)))
        _alarm("DLQDepth", self.dlq.metric_approximate_number_of_messages_visible(period=Duration.minutes(5)))
        _alarm("DDBUserErrors", self.table.metric_user_errors(period=Duration.minutes(5)))

        budgets.CfnBudget(
            self, "DocoAgentBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="doco-agent-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=10, unit="USD"),
            ),
            notifications_with_subscribers=[],
        )

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(self, "SlackWebhookUrl", value=self.http_api.api_endpoint + "/slack/actions")
        CfnOutput(self, "QueueUrl", value=self.queue.queue_url)
        CfnOutput(self, "TableName", value=self.table.table_name)
        CfnOutput(self, "AlarmTopicArn", value=self.alarm_topic.topic_arn)
