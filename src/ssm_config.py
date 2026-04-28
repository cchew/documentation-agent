"""Resolve secrets from SSM Parameter Store at Lambda cold start."""
import os
import boto3


def load_ssm_params_into_env() -> None:
    """For each env var ending in _PARAM, fetch the SSM parameter and set the unsuffixed env var."""
    ssm = boto3.client("ssm")
    suffix = "_PARAM"
    to_resolve = {k: v for k, v in os.environ.items() if k.endswith(suffix)}
    if not to_resolve:
        return
    names = list(to_resolve.values())
    # SSM get_parameters takes max 10 names per call.
    for i in range(0, len(names), 10):
        batch = names[i : i + 10]
        resp = ssm.get_parameters(Names=batch, WithDecryption=True)
        by_name = {p["Name"]: p["Value"] for p in resp["Parameters"]}
        for env_key, param_name in to_resolve.items():
            if param_name in by_name:
                os.environ[env_key.removesuffix(suffix)] = by_name[param_name]
