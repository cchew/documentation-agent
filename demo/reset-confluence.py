"""
Delete all KB article pages from the Confluence demo space.

Usage:
    python demo/reset-confluence.py

Deletes every page in the KD space. Use this to reset Confluence to a clean
state before the demo or between test runs.
"""
import sys
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.confluence_client import delete_page, list_space_pages


def main() -> None:
    pages = list_space_pages()

    if not pages:
        print("No pages found in the demo space — nothing to delete.")
        return

    print(f"Found {len(pages)} page(s) in the KD space:")
    for p in pages:
        print(f"  [{p['id']}] {p['title']}")

    confirm = input("\nDelete all? (y/N): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    deleted = 0
    failed = 0
    for p in pages:
        try:
            delete_page(p["id"])
            print(f"  Deleted: {p['title']}")
            deleted += 1
        except RuntimeError as e:
            print(f"  Failed: {p['title']} — {e}")
            failed += 1

    print(f"\nDone. Deleted {deleted}, failed {failed}.")


if __name__ == "__main__":
    main()
