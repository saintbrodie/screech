from pathlib import Path

from backend.database import Database


def test_legacy_schema_is_migrated(tmp_path: Path):
    db = Database(tmp_path / "test.db")
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
