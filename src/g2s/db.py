"""SQLite manifest ledger tracking every media file from Takeout to NAS verification."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class ManifestDB:
    """Persistent SQLite ledger for idempotent, resumable migration stages."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS archives (
                    name TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS media_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL UNIQUE,
                    raw_sha256 TEXT NOT NULL,
                    raw_size INTEGER NOT NULL,
                    json_path TEXT,
                    capture_year TEXT NOT NULL,
                    capture_month TEXT NOT NULL,
                    staged_path TEXT,
                    staged_sha256 TEXT,
                    staged_size INTEGER,
                    dest_path TEXT,
                    duplicate_of INTEGER,
                    status TEXT NOT NULL DEFAULT 'scanned',
                    error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_media_status ON media_files(status);
                CREATE INDEX IF NOT EXISTS idx_media_raw_hash ON media_files(raw_sha256);
                """
            )

    def is_archive_extracted(self, name: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM archives WHERE name = ?", (name,)
            ).fetchone()
            return row is not None

    def mark_archive_extracted(self, name: str, size: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO archives (name, size) VALUES (?, ?)",
                (name, size),
            )

    def upsert_scanned(
        self,
        source_path: str,
        raw_sha256: str,
        raw_size: int,
        json_path: str | None,
        capture_year: str,
        capture_month: str,
    ) -> int:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO media_files (
                    source_path, raw_sha256, raw_size, json_path,
                    capture_year, capture_month, status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'scanned')
                ON CONFLICT(source_path) DO UPDATE SET
                    raw_sha256 = excluded.raw_sha256,
                    raw_size = excluded.raw_size,
                    json_path = excluded.json_path,
                    capture_year = excluded.capture_year,
                    capture_month = excluded.capture_month,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    source_path,
                    raw_sha256,
                    raw_size,
                    json_path,
                    capture_year,
                    capture_month,
                ),
            )
            row = conn.execute(
                "SELECT id FROM media_files WHERE source_path = ?", (source_path,)
            ).fetchone()
            return int(row["id"])

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM media_files WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM media_files ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def find_canonical_by_raw_hash(self, raw_sha256: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM media_files
                WHERE raw_sha256 = ?
                  AND status IN ('staged', 'transferred', 'verified')
                ORDER BY id LIMIT 1
                """,
                (raw_sha256,),
            ).fetchone()
            return dict(row) if row is not None else None

    def mark_duplicate_skipped(self, row_id: int, canonical_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE media_files
                SET status = 'duplicate_skipped',
                    duplicate_of = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (canonical_id, row_id),
            )

    def update_stage(
        self, row_id: int, staged_path: str, staged_sha256: str, staged_size: int
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE media_files
                SET staged_path = ?,
                    staged_sha256 = ?,
                    staged_size = ?,
                    status = 'staged',
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (staged_path, staged_sha256, staged_size, row_id),
            )

    def update_transfer(self, row_id: int, dest_path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE media_files
                SET dest_path = ?,
                    status = 'transferred',
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (dest_path, row_id),
            )

    def update_verify(self, row_id: int, verified: bool, error: str | None) -> None:
        new_status = "verified" if verified else "verify_failed"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE media_files
                SET status = ?,
                    error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_status, error, row_id),
            )

    def summary_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "total": 0,
            "scanned": 0,
            "staged": 0,
            "duplicate_skipped": 0,
            "transferred": 0,
            "verified": 0,
            "verify_failed": 0,
        }
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM media_files GROUP BY status"
            ).fetchall()
            for row in rows:
                counts[row["status"]] = int(row["cnt"])
                counts["total"] += int(row["cnt"])
        return counts

    def list_issues(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM media_files
                WHERE status NOT IN ('verified', 'duplicate_skipped')
                   OR json_path IS NULL
                   OR capture_year = 'UnknownDate'
                ORDER BY id
                """
            ).fetchall()
            return [dict(r) for r in rows]
