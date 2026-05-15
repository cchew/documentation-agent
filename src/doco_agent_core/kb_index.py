from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pydantic import BaseModel


class KBIndexEntry(BaseModel):
    page_id: str
    space_key: str
    title: str
    incident_type: str
    systems_affected: list[str]
    confluence_url: str | None = None
    last_indexed_version: int = 0
    last_indexed_at: str = ""  # ISO-8601
    draft_json: str = "{}"  # serialised KBArticle at last agent write (base for three-way merge)


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kb_index (
    page_id               TEXT PRIMARY KEY,
    space_key             TEXT NOT NULL,
    title                 TEXT NOT NULL,
    incident_type         TEXT NOT NULL,
    systems_affected      TEXT NOT NULL,
    confluence_url        TEXT NOT NULL DEFAULT '',
    embedding             BLOB NOT NULL,
    last_indexed_version  INTEGER NOT NULL DEFAULT 0,
    last_indexed_at       TEXT NOT NULL DEFAULT '',
    draft_json            TEXT NOT NULL DEFAULT '{}'
)
"""

_MIGRATE_ADD_DRAFT_JSON = (
    "ALTER TABLE kb_index ADD COLUMN draft_json TEXT NOT NULL DEFAULT '{}'"
)


class KBIndex:
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    EMBEDDING_DIM = 384

    def __init__(self, db_path: str | Path = "var/kb-index.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._model = None  # lazy load
        self._init_db()

    def _init_db(self) -> None:
        with contextlib.closing(self._connect()) as conn:
            conn.execute(_CREATE_TABLE_SQL)
            # Idempotent migration: add draft_json if the column doesn't exist yet
            cols = {row[1] for row in conn.execute("PRAGMA table_info(kb_index)").fetchall()}
            if "draft_json" not in cols:
                conn.execute(_MIGRATE_ADD_DRAFT_JSON)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _embed(self, text: str) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.EMBEDDING_MODEL)
        vec = self._model.encode(text, convert_to_numpy=True).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm == 0.0:
            return vec
        return vec / norm

    def save(self, entry: KBIndexEntry, embed_text: str) -> None:
        embedding = self._embed(embed_text)
        last_indexed_at = entry.last_indexed_at or datetime.now(timezone.utc).isoformat()
        with contextlib.closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO kb_index
                    (page_id, space_key, title, incident_type, systems_affected,
                     confluence_url, embedding, last_indexed_version, last_indexed_at,
                     draft_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.page_id,
                    entry.space_key,
                    entry.title,
                    entry.incident_type,
                    json.dumps(entry.systems_affected),
                    entry.confluence_url or "",
                    embedding.tobytes(),
                    entry.last_indexed_version,
                    last_indexed_at,
                    entry.draft_json,
                ),
            )
            conn.commit()

    def get(self, page_id: str) -> KBIndexEntry | None:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM kb_index WHERE page_id = ?", (page_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def delete(self, page_id: str) -> None:
        with contextlib.closing(self._connect()) as conn:
            conn.execute("DELETE FROM kb_index WHERE page_id = ?", (page_id,))
            conn.commit()

    def clear(self) -> None:
        with contextlib.closing(self._connect()) as conn:
            conn.execute("DELETE FROM kb_index")
            conn.commit()

    def search(
        self,
        query_text: str,
        top_k: int = 5,
        space_key: str | None = None,
    ) -> list[tuple[KBIndexEntry, float]]:
        query_vec = self._embed(query_text)

        sql = "SELECT * FROM kb_index"
        params: tuple = ()
        if space_key is not None:
            sql += " WHERE space_key = ?"
            params = (space_key,)

        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return []

        results: list[tuple[KBIndexEntry, float]] = []
        for row in rows:
            stored_vec = np.frombuffer(row["embedding"], dtype=np.float32)
            score = float(np.dot(query_vec, stored_vec))
            score = max(0.0, min(1.0, score))
            results.append((self._row_to_entry(row), score))

        results.sort(key=lambda t: t[1], reverse=True)
        return results[:top_k]

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> KBIndexEntry:
        stored_url = row["confluence_url"]
        keys = row.keys()
        return KBIndexEntry(
            page_id=row["page_id"],
            space_key=row["space_key"],
            title=row["title"],
            incident_type=row["incident_type"],
            systems_affected=json.loads(row["systems_affected"]),
            confluence_url=stored_url if stored_url else None,
            last_indexed_version=row["last_indexed_version"],
            last_indexed_at=row["last_indexed_at"],
            draft_json=row["draft_json"] if "draft_json" in keys else "{}",
        )
