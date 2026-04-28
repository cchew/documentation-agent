"""Clear the storage backend selected by STORAGE_BACKEND env."""
import os
import sys
from dotenv import load_dotenv

# Allow running from repo root: `python demo/reset-storage.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from src.storage import get_store


def main() -> None:
    backend = os.environ.get("STORAGE_BACKEND", "memory")
    store = get_store()
    before = len(store.list_all())
    store.clear()
    after = len(store.list_all())
    print(f"backend={backend} cleared {before - after} articles (before={before}, after={after})")


if __name__ == "__main__":
    main()
