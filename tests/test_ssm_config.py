import os
import boto3
import pytest
from moto import mock_aws
from src.ssm_config import load_ssm_params_into_env


@mock_aws
def test_resolves_param_suffixed_env_vars():
    os.environ["AWS_DEFAULT_REGION"] = "ap-southeast-2"
    boto3.client("ssm").put_parameter(Name="/test/foo", Value="bar", Type="SecureString")
    os.environ["FOO_PARAM"] = "/test/foo"
    os.environ.pop("FOO", None)

    load_ssm_params_into_env()

    assert os.environ["FOO"] == "bar"
