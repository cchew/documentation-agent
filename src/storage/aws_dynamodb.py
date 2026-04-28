import boto3
from src.extraction.models import KBArticle
from src.storage.base import ArticleStore


class DynamoDBStore(ArticleStore):
    """
    Single-table store. PK: article_id (String).
    Attributes: article_json (S), confluence_page_id (S, optional), extraction_viable (BOOL), created_at (S).
    """

    def __init__(self, table_name: str) -> None:
        self._table = boto3.resource("dynamodb").Table(table_name)

    def save(self, article_id: str, article: KBArticle) -> None:
        self._table.update_item(
            Key={"article_id": article_id},
            UpdateExpression="SET article_json = :j, extraction_viable = :v, created_at = if_not_exists(created_at, :c)",
            ExpressionAttributeValues={
                ":j": article.model_dump_json(),
                ":v": article.extraction_viable,
                ":c": _now_iso(),
            },
        )

    def save_page_id(self, article_id: str, page_id: str) -> None:
        self._table.update_item(
            Key={"article_id": article_id},
            UpdateExpression="SET confluence_page_id = :p",
            ExpressionAttributeValues={":p": page_id},
        )

    def get(self, article_id: str) -> KBArticle | None:
        resp = self._table.get_item(Key={"article_id": article_id})
        item = resp.get("Item")
        if not item or "article_json" not in item:
            return None
        return KBArticle.model_validate_json(item["article_json"])

    def get_page_id(self, article_id: str) -> str | None:
        resp = self._table.get_item(Key={"article_id": article_id}, ProjectionExpression="confluence_page_id")
        item = resp.get("Item") or {}
        return item.get("confluence_page_id")

    def list_all(self) -> list[dict]:
        rows: list[dict] = []
        kwargs: dict = {}
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                if "article_json" not in item:
                    continue
                article = KBArticle.model_validate_json(item["article_json"])
                rows.append({"id": item["article_id"], **article.model_dump()})
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return rows

    def clear(self) -> None:
        with self._table.batch_writer() as batch:
            kwargs: dict = {}
            while True:
                resp = self._table.scan(ProjectionExpression="article_id", **kwargs)
                for item in resp.get("Items", []):
                    batch.delete_item(Key={"article_id": item["article_id"]})
                if "LastEvaluatedKey" not in resp:
                    break
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
