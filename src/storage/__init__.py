import os
from functools import lru_cache
from src.storage.base import ArticleStore


@lru_cache(maxsize=1)
def get_store() -> ArticleStore:
    backend = os.environ.get("STORAGE_BACKEND", "memory")
    if backend == "memory":
        from src.storage.memory import MemoryStore
        return MemoryStore()
    if backend == "dynamodb":
        from src.storage.aws_dynamodb import DynamoDBStore
        return DynamoDBStore(table_name=os.environ["DDB_TABLE"])
    raise ValueError(f"Unknown STORAGE_BACKEND: {backend}")
