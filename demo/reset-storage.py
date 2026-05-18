"""Clear the storage backend and KB index."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

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

    kb_index_path = Path(os.environ.get("KB_INDEX_PATH", "var/kb-index.db"))
    if kb_index_path.exists():
        kb_index_path.unlink()
        print(f"kb-index cleared: {kb_index_path}")
    else:
        print(f"kb-index not found (already clean): {kb_index_path}")

    run_log_path = Path("var/runs.jsonl")
    if run_log_path.exists():
        run_log_path.unlink()
        print(f"run log cleared: {run_log_path}")


if __name__ == "__main__":
    main()
