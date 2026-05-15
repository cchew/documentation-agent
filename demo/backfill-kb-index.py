#!/usr/bin/env python
"""Backfill the KB index from an existing Confluence space.

Walks all pages in CONFLUENCE_SPACE_KEY, generates embeddings from the page
title + body text, and saves them to the SQLite KB index. Idempotent — pages
already indexed at their current version are skipped.

Usage:
    python demo/backfill-kb-index.py [--dry-run]

Environment: reads from .env (CONFLUENCE_URL, CONFLUENCE_EMAIL,
CONFLUENCE_API_TOKEN, CONFLUENCE_SPACE_KEY, KB_INDEX_PATH).
"""
import argparse
import html
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx

from src.confluence_client import _auth_header, _base_url
from src.doco_agent_core.kb_index import KBIndex, KBIndexEntry


def strip_html(text: str) -> str:
    """Strip Confluence storage-format XML/HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def fetch_all_pages(space_key: str) -> list[dict]:
    """Return all pages in the space with version + body.storage expanded."""
    base = _base_url()
    headers = {"Authorization": _auth_header(), "Accept": "application/json"}
    pages: list[dict] = []
    start = 0
    with httpx.Client() as client:
        while True:
            resp = client.get(
                f"{base}/rest/api/content",
                headers=headers,
                params={
                    "spaceKey": space_key,
                    "type": "page",
                    "limit": 50,
                    "start": start,
                    "expand": "version,body.storage",
                },
                timeout=20,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Confluence list failed: {resp.status_code} {resp.text}")
            data = resp.json()
            results = data.get("results", [])
            pages.extend(results)
            if len(results) < 50:
                break
            start += 50
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill KB index from Confluence space")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List pages found without writing to index",
    )
    args = parser.parse_args()

    space_key = os.environ["CONFLUENCE_SPACE_KEY"]
    index_path = os.environ.get("KB_INDEX_PATH", "var/kb-index.db")
    confluence_base = os.environ["CONFLUENCE_URL"].rstrip("/")

    print(f"Space:  {space_key}")
    print(f"Index:  {index_path}")

    print("Fetching page list from Confluence...")
    pages = fetch_all_pages(space_key)
    print(f"Found {len(pages)} pages\n")

    if args.dry_run:
        for p in pages:
            print(f"  [{p['id']}] {p['title']}")
        print("\n--dry-run: nothing written.")
        return

    kb_index = KBIndex(db_path=index_path)
    indexed = 0
    skipped = 0

    for page in pages:
        page_id: str = page["id"]
        title: str = page["title"]
        version_number: int = page.get("version", {}).get("number", 0)

        existing = kb_index.get(page_id)
        if existing and existing.last_indexed_version >= version_number:
            skipped += 1
            continue

        body_storage: str = page.get("body", {}).get("storage", {}).get("value", "")
        plain_body = strip_html(body_storage)
        # Trim to 1000 chars for embedding — captures the semantically dense lead
        embed_text = f"{title}. {plain_body[:1000]}"

        entry = KBIndexEntry(
            page_id=page_id,
            space_key=space_key,
            title=title,
            incident_type="incident",
            systems_affected=[],
            confluence_url=f"{confluence_base}/spaces/{space_key}/pages/{page_id}",
            last_indexed_version=version_number,
        )
        kb_index.save(entry, embed_text)
        indexed += 1
        print(f"  [indexed]  [{page_id}] {title}")

    print(f"\nDone: {indexed} indexed, {skipped} skipped (already current).")


if __name__ == "__main__":
    main()
