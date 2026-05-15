import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    log_path = tmp_path / "runs.jsonl"
    monkeypatch.setenv("RUN_LOG_PATH", str(log_path))
    # Force module-level path to refresh
    import importlib
    import src.run_log
    importlib.reload(src.run_log)
    yield log_path
    importlib.reload(src.run_log)


def test_log_run_creates_jsonl_file(tmp_log):
    from src.run_log import log_run
    log_run(action="create", target_page_id="page-1", match_candidates=[], protected_fields=[], status="success")
    assert tmp_log.exists()


def test_log_run_returns_run_id(tmp_log):
    from src.run_log import log_run
    run_id = log_run(action="create", target_page_id="page-1", match_candidates=[], protected_fields=[], status="success")
    assert isinstance(run_id, str) and len(run_id) == 36  # UUID4


def test_log_run_record_structure(tmp_log):
    from src.run_log import log_run
    log_run(
        action="update",
        target_page_id="page-99",
        match_candidates=[{"page_id": "page-1", "score": 0.9}],
        protected_fields=["resolution"],
        status="success",
    )
    records = [json.loads(line) for line in tmp_log.read_text().splitlines()]
    assert len(records) == 1
    r = records[0]
    assert r["action"] == "update"
    assert r["target_page_id"] == "page-99"
    assert r["protected_fields"] == ["resolution"]
    assert r["status"] == "success"
    assert "run_id" in r
    assert "timestamp" in r


def test_log_run_appends_multiple_records(tmp_log):
    from src.run_log import log_run
    log_run(action="create", target_page_id="p1", match_candidates=[], protected_fields=[], status="success")
    log_run(action="cancel", target_page_id=None, match_candidates=[], protected_fields=[], status="success")
    records = [json.loads(line) for line in tmp_log.read_text().splitlines()]
    assert len(records) == 2


def test_log_run_records_error_message(tmp_log):
    from src.run_log import log_run
    log_run(action="update", target_page_id="p1", match_candidates=[], protected_fields=[], status="error", error_message="Confluence unreachable")
    records = [json.loads(line) for line in tmp_log.read_text().splitlines()]
    assert records[0]["error_message"] == "Confluence unreachable"


def test_log_run_creates_parent_dir(tmp_path, monkeypatch):
    nested = tmp_path / "nested" / "dir" / "runs.jsonl"
    monkeypatch.setenv("RUN_LOG_PATH", str(nested))
    import importlib
    import src.run_log
    importlib.reload(src.run_log)
    from src.run_log import log_run
    log_run(action="create", target_page_id=None, match_candidates=[], protected_fields=[], status="success")
    assert nested.exists()
    importlib.reload(src.run_log)
