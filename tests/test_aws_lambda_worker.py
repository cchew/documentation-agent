import json
from unittest.mock import patch
from src.adapters.aws_lambda_worker import handler


@patch("src.adapters.aws_lambda_worker.run_pipeline")
def test_handler_dispatches_each_record_to_pipeline(mock_run):
    event = {
        "Records": [
            {"body": json.dumps({"channel_id": "C1", "thread_ts": "1.1", "processing_ts": "p.1"})},
            {"body": json.dumps({"channel_id": "C2", "thread_ts": "2.2", "processing_ts": None})},
        ]
    }

    handler(event, context=None)

    assert mock_run.call_count == 2
    mock_run.assert_any_call("C1", "1.1", "p.1")
    mock_run.assert_any_call("C2", "2.2", None)


@patch("src.adapters.aws_lambda_worker.run_pipeline")
def test_handler_propagates_exception_for_sqs_retry(mock_run):
    mock_run.side_effect = RuntimeError("boom")
    event = {"Records": [{"body": json.dumps({"channel_id": "C", "thread_ts": "1", "processing_ts": None})}]}
    try:
        handler(event, context=None)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
