import json
from unittest.mock import patch
from src.adapters.aws_lambda_worker import handler


@patch("src.adapters.aws_lambda_worker.run_pipeline")
@patch("src.adapters.aws_lambda_worker.post_processing")
def test_handler_posts_processing_then_runs_pipeline(mock_post, mock_run):
    mock_post.return_value = "p.123"
    event = {"Records": [{"body": json.dumps({"channel_id": "C1", "thread_ts": "1.1"})}]}

    handler(event, context=None)

    mock_post.assert_called_once_with("C1", "1.1")
    mock_run.assert_called_once_with("C1", "1.1", "p.123")


@patch("src.adapters.aws_lambda_worker.run_pipeline")
@patch("src.adapters.aws_lambda_worker.post_processing")
def test_handler_propagates_exception(mock_post, mock_run):
    mock_post.return_value = "p.1"
    mock_run.side_effect = RuntimeError("boom")
    event = {"Records": [{"body": json.dumps({"channel_id": "C", "thread_ts": "1"})}]}
    try:
        handler(event, context=None)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
