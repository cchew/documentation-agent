"""SQS-triggered Lambda handler. Dispatches each record to the cloud-neutral pipeline."""
import json
import logging

from src.pipeline import run_pipeline

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        run_pipeline(
            body["channel_id"],
            body["thread_ts"],
            body.get("processing_ts"),
        )
    return {"status": "ok"}
