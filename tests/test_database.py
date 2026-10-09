from pathlib import Path
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from backend.database import Database


def test_legacy_schema_is_migrated(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    with sqlite3.connect(db.path) as conn:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, event_text TEXT, hawk_count INTEGER)")
        conn.execute("INSERT INTO events(event_text, hawk_count) VALUES ('Existing event', 2)")
    db.initialize()

    db.log_event(
        event_type="arrival",
        text="A hawk arrived",
        hawk_count=1,
        confidence=0.8,
        snapshot_path="/tmp/example.jpg",
    )

    timeline = db.timeline(10)
    assert timeline[0]["event_type"] == "arrival"
    assert timeline[0]["confidence"] == 0.8
    assert timeline[1]["event"] == "Existing event"
    assert timeline[1]["event_type"] == "legacy"
    assert timeline[0]["snapshot_url"] == "/snapshots/example.jpg"


def test_daily_stats(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    db.log_observation(hawk_count=1, behavior="Active / Moving", confidence=0.9)
    db.log_observation(hawk_count=0, behavior="Unknown", confidence=None)

    stats = db.daily_stats(1)
    assert stats[0]["samples"] == 2
    assert stats[0]["occupancy_pct"] == 50.0
    assert stats[0]["activity_pct"] == 50.0


@pytest.mark.parametrize("instant, expected_day", [
    ("2026-10-09T00:00:00", "2026-10-08"),
    ("2026-10-09T03:59:59", "2026-10-08"),
    ("2026-10-09T04:00:00", "2026-10-09"),
    ("2026-01-09T04:59:59", "2026-01-08"),
    ("2026-01-09T05:00:00", "2026-01-09"),
])
def test_today_rolls_over_at_eastern_midnight(tmp_path, instant, expected_day):
    db = Database(tmp_path / "test.db")
    db.initialize()
    now = datetime.fromisoformat(instant).replace(tzinfo=timezone.utc)
    assert db.daily_stats(1, now=now)[0]["day"] == expected_day


def test_stats_include_utc_evening_and_exclude_next_local_day(tmp_path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    with db._connect() as conn:
        conn.executemany(
            "INSERT INTO observations(timestamp, hawk_count, behavior) VALUES (?, ?, ?)",
            [("2026-10-08 03:59:59", 0, "Unknown"),
             ("2026-10-08 04:00:00", 1, "Incubating / Resting"),
             ("2026-10-09 00:00:00", 0, "Unknown"),
             ("2026-10-09 03:59:59", 2, "Active / Moving"),
             ("2026-10-09 04:00:00", 0, "Unknown")],
        )
    result = db.daily_stats(2, now=datetime(2026, 10, 9, 4, tzinfo=timezone.utc))
    assert result == [
        {"day": "2026-10-08", "samples": 3, "occupancy_pct": 66.7, "activity_pct": 33.3},
        {"day": "2026-10-09", "samples": 1, "occupancy_pct": 0.0, "activity_pct": 0.0},
    ]


@pytest.mark.parametrize("start, end, interior, day", [
    ("2026-03-08 05:00:00", "2026-03-09 04:00:00",
     ["2026-03-08 06:30:00", "2026-03-08 07:30:00"], "2026-03-08"),
    ("2026-11-01 04:00:00", "2026-11-02 05:00:00",
     ["2026-11-01 05:30:00", "2026-11-01 06:30:00"], "2026-11-01"),
])
def test_dst_days_use_correct_utc_bounds(tmp_path, start, end, interior, day):
    db = Database(tmp_path / "test.db")
    db.initialize()
    before = (datetime.fromisoformat(start) - timedelta(seconds=1)).isoformat(sep=" ")
    last = (datetime.fromisoformat(end) - timedelta(seconds=1)).isoformat(sep=" ")
    stamps = [before, start, *interior, last, end]
    with db._connect() as conn:
        conn.executemany(
            "INSERT INTO observations(timestamp, hawk_count, behavior) VALUES (?, 1, 'Active / Moving')",
            [(stamp,) for stamp in stamps],
        )
    now = datetime.fromisoformat(day + "T18:00:00").replace(tzinfo=timezone.utc)
    result = db.daily_stats(1, now=now)[0]
    assert result["samples"] == 4
    assert result["occupancy_pct"] == result["activity_pct"] == 100.0
    with db._connect() as conn:
        assert [row[0] for row in conn.execute("SELECT timestamp FROM observations ORDER BY id")] == stamps
