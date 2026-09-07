from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    event_text TEXT,
                    hawk_count INTEGER
                )
                """
            )
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
            migrations = {
                "event_type": "TEXT",
                "confidence": "REAL",
                "snapshot_path": "TEXT",
            }
            for column, column_type in migrations.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE events ADD COLUMN {column} {column_type}")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    hawk_count INTEGER NOT NULL,
                    behavior TEXT NOT NULL,
                    confidence REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_observations_timestamp ON observations(timestamp)"
            )

    def log_event(
        self,
        *,
        event_type: str,
        text: str,
        hawk_count: int,
        confidence: float | None,
        snapshot_path: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events
                    (event_type, event_text, hawk_count, confidence, snapshot_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_type, text, hawk_count, confidence, snapshot_path),
            )

    def last_event_text(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_text FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row["event_text"] if row else None

    def log_observation(
        self,
        *,
        hawk_count: int,
        behavior: str,
        confidence: float | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO observations (hawk_count, behavior, confidence)
                VALUES (?, ?, ?)
                """,
                (hawk_count, behavior, confidence),
            )

    def timeline(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, event_type, event_text, hawk_count, confidence, snapshot_path
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "timestamp": row["timestamp"],
                "event_type": row["event_type"] or "legacy",
                "event": row["event_text"],
                "count": row["hawk_count"],
                "confidence": row["confidence"],
                "snapshot_url": (
                    f"/snapshots/{Path(row['snapshot_path']).name}"
                    if row["snapshot_path"]
                    else None
                ),
            }
            for row in rows
        ]

    def daily_stats(self, days: int = 7) -> list[dict[str, Any]]:
        days = max(1, min(days, 90))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days - 1)
        cutoff_day = cutoff.date().isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    date(timestamp) AS day,
                    COUNT(*) AS samples,
                    SUM(CASE WHEN hawk_count > 0 THEN 1 ELSE 0 END) AS occupied_samples,
                    SUM(CASE WHEN behavior = 'Active / Moving' THEN 1 ELSE 0 END) AS active_samples
                FROM observations
                WHERE date(timestamp) >= date(?)
                GROUP BY date(timestamp)
                ORDER BY day ASC
                """,
                (cutoff_day,),
            ).fetchall()

        by_day = {row["day"]: row for row in rows}
        result: list[dict[str, Any]] = []
        for offset in range(days):
            day = (cutoff.date() + timedelta(days=offset)).isoformat()
            row = by_day.get(day)
            samples = int(row["samples"]) if row else 0
            occupied = int(row["occupied_samples"] or 0) if row else 0
            active = int(row["active_samples"] or 0) if row else 0
            result.append(
                {
                    "day": day,
                    "samples": samples,
                    "occupancy_pct": round((occupied / samples) * 100, 1) if samples else 0.0,
                    "activity_pct": round((active / samples) * 100, 1) if samples else 0.0,
                }
            )
        return result

    def health(self) -> dict[str, Any]:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return {"ok": True, "path": str(self.path)}
        except sqlite3.Error as exc:
            return {"ok": False, "path": str(self.path), "error": str(exc)}
