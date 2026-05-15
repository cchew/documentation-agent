"""Minimal run log — one JSONL record per pipeline run.

Fields: run_id, timestamp, action, target_page_id, match_candidates,
        protected_fields, status, error_message.

Localhost: appends to var/runs.jsonl (gitignored).
AWS Cycle 2: migrate to DynamoDB table doco-agent-runs.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

def log_run(
    action: str,
    target_page_id: str | None,
    match_candidates: list[dict],
    protected_fields: list[str],
    status: str,
    error_message: str | None = None,
) -> str:
    """Append one record to the JSONL run log. Returns the run_id."""
    run_id = str(uuid.uuid4())
    record = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action,
        "target_page_id": target_page_id,
        "match_candidates": match_candidates,
        "protected_fields": protected_fields,
        "status": status,
        "error_message": error_message,
    }
    log_path = Path(os.environ.get("RUN_LOG_PATH", "var/runs.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")
    return run_id
