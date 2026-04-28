"""SQS-triggered Lambda handler.
Posts the Slack 'processing' message, then dispatches to the cloud-neutral pipeline.
"""
import json
import logging

from src.ssm_config import load_ssm_params_into_env
load_ssm_params_into_env()

from src.pipeline import run_pipeline
from src.slack_client import post_processing

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        channel_id = body["channel_id"]
        thread_ts = body["thread_ts"]
        processing_ts = post_processing(channel_id, thread_ts)
        run_pipeline(channel_id, thread_ts, processing_ts)
    return {"status": "ok"}
