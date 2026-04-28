import os
import boto3
import pytest
from moto import mock_aws
from src.extraction.models import KBArticle
from src.storage.memory import MemoryStore
from src.storage.aws_dynamodb import DynamoDBStore


TABLE_NAME = "doco-agent-articles-test"


def _sample_article() -> KBArticle:
    return KBArticle(
        title="t", summary="s", incident_type="incident",
        systems_affected=["x"], steps_taken=["a"], resolution="r",
        tags=["k"], related_topics=["rt"],
        confidence_score=0.9, extraction_viable=True, pii_detected=False,
    )


@pytest.fixture
def memory_store():
    return MemoryStore()


@pytest.fixture
def dynamodb_store():
    with mock_aws():
        os.environ["AWS_DEFAULT_REGION"] = "ap-southeast-2"
        client = boto3.client("dynamodb")
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "article_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "article_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoDBStore(table_name=TABLE_NAME)


@pytest.fixture(params=["memory", "dynamodb"])
def store(request, memory_store, dynamodb_store):
    return memory_store if request.param == "memory" else dynamodb_store


def test_save_and_get(store):
    store.save("id1", _sample_article())
    got = store.get("id1")
    assert got is not None and got.title == "t"


def test_get_missing_returns_none(store):
    assert store.get("missing") is None


def test_save_page_id_and_get_page_id(store):
    store.save("id1", _sample_article())
    store.save_page_id("id1", "page-123")
    assert store.get_page_id("id1") == "page-123"


def test_get_page_id_missing(store):
    assert store.get_page_id("nope") is None


def test_list_all_returns_dicts(store):
    store.save("id1", _sample_article())
    rows = store.list_all()
    assert len(rows) == 1
    assert rows[0]["id"] == "id1"
    assert rows[0]["title"] == "t"


def test_clear(store):
    store.save("id1", _sample_article())
    store.clear()
    assert store.get("id1") is None
    assert store.list_all() == []
