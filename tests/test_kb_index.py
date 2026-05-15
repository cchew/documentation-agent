from __future__ import annotations

import pytest

from src.doco_agent_core.kb_index import KBIndex, KBIndexEntry


def make_entry(page_id: str = "P1", space_key: str = "SPACE", title: str = "Article") -> KBIndexEntry:
    return KBIndexEntry(
        page_id=page_id,
        space_key=space_key,
        title=title,
        incident_type="incident",
        systems_affected=["auth-service"],
        last_indexed_version=1,
        last_indexed_at="2026-05-15T00:00:00+00:00",
    )


def test_save_and_get(tmp_path):
    index = KBIndex(db_path=tmp_path / "kb.db")
    entry = make_entry()
    index.save(entry, "Authentication service login failure outage")
    retrieved = index.get("P1")
    assert retrieved is not None
    assert retrieved.page_id == "P1"
    assert retrieved.space_key == "SPACE"
    assert retrieved.title == "Article"
    assert retrieved.incident_type == "incident"
    assert retrieved.systems_affected == ["auth-service"]
    assert retrieved.last_indexed_version == 1
    assert retrieved.confluence_url is None

    # Verify confluence_url round-trips correctly
    entry_with_url = KBIndexEntry(
        page_id="P2",
        space_key="SPACE",
        title="Article with URL",
        incident_type="incident",
        systems_affected=["auth-service"],
        confluence_url="https://example.atlassian.net/wiki/spaces/SPACE/pages/12345",
    )
    index.save(entry_with_url, "Authentication service login failure outage")
    retrieved_with_url = index.get("P2")
    assert retrieved_with_url is not None
    assert retrieved_with_url.confluence_url == "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345"


def test_save_is_idempotent(tmp_path):
    index = KBIndex(db_path=tmp_path / "kb.db")
    entry_v1 = make_entry(title="Version 1")
    index.save(entry_v1, "First version of the article")

    entry_v2 = KBIndexEntry(
        page_id="P1",
        space_key="SPACE",
        title="Version 2",
        incident_type="qa",
        systems_affected=["db-service"],
        last_indexed_version=2,
        last_indexed_at="2026-05-16T00:00:00+00:00",
    )
    index.save(entry_v2, "Second version of the article")

    retrieved = index.get("P1")
    assert retrieved is not None
    assert retrieved.title == "Version 2"
    assert retrieved.incident_type == "qa"
    assert retrieved.last_indexed_version == 2

    import sqlite3
    conn = sqlite3.connect(tmp_path / "kb.db")
    count = conn.execute("SELECT COUNT(*) FROM kb_index").fetchone()[0]
    conn.close()
    assert count == 1


def test_delete(tmp_path):
    index = KBIndex(db_path=tmp_path / "kb.db")
    entry = make_entry()
    index.save(entry, "Some article text")
    index.delete("P1")
    assert index.get("P1") is None


def test_clear(tmp_path):
    index = KBIndex(db_path=tmp_path / "kb.db")
    index.save(make_entry(page_id="P1"), "First article about login failures")
    index.save(make_entry(page_id="P2", title="Article 2"), "Second article about database errors")
    index.clear()
    results = index.search("login failure")
    assert results == []


def test_search_returns_similar(tmp_path):
    index = KBIndex(db_path=tmp_path / "kb.db")

    auth_entry = KBIndexEntry(
        page_id="AUTH1",
        space_key="SPACE",
        title="Login Failure Incident",
        incident_type="incident",
        systems_affected=["auth-service"],
        last_indexed_version=1,
        last_indexed_at="2026-05-15T00:00:00+00:00",
    )
    index.save(auth_entry, "Users unable to login. Authentication service returned 401. LDAP connection timed out.")

    db_entry = KBIndexEntry(
        page_id="DB1",
        space_key="SPACE",
        title="Database Disk Full",
        incident_type="incident",
        systems_affected=["postgres"],
        last_indexed_version=1,
        last_indexed_at="2026-05-15T00:00:00+00:00",
    )
    index.save(db_entry, "Database server disk at 100% capacity. Write operations failing. Postgres out of disk space.")

    results = index.search("authentication login 401 error", top_k=5)
    assert len(results) >= 1
    top_entry, top_score = results[0]
    assert top_entry.page_id == "AUTH1"
    assert top_score > 0


def test_search_space_key_filter(tmp_path):
    index = KBIndex(db_path=tmp_path / "kb.db")

    index.save(
        make_entry(page_id="A1", space_key="ALPHA", title="Alpha Article"),
        "Alpha space article about network connectivity issues",
    )
    index.save(
        make_entry(page_id="B1", space_key="BETA", title="Beta Article"),
        "Beta space article about storage failures",
    )
    index.save(
        make_entry(page_id="A2", space_key="ALPHA", title="Alpha Article 2"),
        "Alpha space second article about service degradation",
    )

    results = index.search("article", top_k=10, space_key="ALPHA")
    page_ids = {entry.page_id for entry, _ in results}
    assert "A1" in page_ids
    assert "A2" in page_ids
    assert "B1" not in page_ids
