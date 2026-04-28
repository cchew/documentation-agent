#!/usr/bin/env python3
import os
import aws_cdk as cdk
from doco_agent_stack import DocoAgentStack

app = cdk.App()
region = app.node.try_get_context("region") or "ap-southeast-2"
account = os.environ.get("CDK_DEFAULT_ACCOUNT")

DocoAgentStack(app, "DocoAgentStack", env=cdk.Environment(account=account, region=region))

app.synth()
