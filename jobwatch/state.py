"""SQLite-backed record of which listing IDs have already been seen/posted."""

import sqlite3
import time
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    source TEXT NOT NULL,
    id TEXT NOT NULL,
    seen_at INTEGER NOT NULL,
    PRIMARY KEY (source, id)
);
CREATE TABLE IF NOT EXISTS etags (
    source TEXT PRIMARY KEY,
    etag TEXT
);
"""


class State:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def is_seeded(self, source: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen WHERE source = ? LIMIT 1", (source,)).fetchone()
        return row is not None

    def seen_ids(self, source: str) -> set[str]:
        rows = self.conn.execute("SELECT id FROM seen WHERE source = ?", (source,))
        return {r[0] for r in rows}

    def mark_seen(self, source: str, ids: Iterable[str]) -> None:
        now = int(time.time())
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO seen (source, id, seen_at) VALUES (?, ?, ?)",
                ((source, i, now) for i in ids),
            )

    def get_etag(self, source: str) -> str | None:
        row = self.conn.execute("SELECT etag FROM etags WHERE source = ?", (source,)).fetchone()
        return row[0] if row else None

    def set_etag(self, source: str, etag: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO etags (source, etag) VALUES (?, ?) "
                "ON CONFLICT(source) DO UPDATE SET etag = excluded.etag",
                (source, etag),
            )
