import asyncio
import importlib
import time
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.config import Settings
from backend.database import Database
from backend.processor import HawkProcessor


@pytest.fixture
def server(tmp_path, monkeypatch):
    settings = replace(Settings(), data_dir=tmp_path, db_path=tmp_path / "api.db",
                       save_snapshots=False, save_crops=False)
    # Import-time initialization must use disposable data, not the user's DB.
    monkeypatch.setattr(config, "settings", settings)
    module = importlib.import_module("backend.server")
    database = Database(settings.db_path)
    database.initialize()
    processor = HawkProcessor(settings, database)
    processor.detector.load = Mock()

    async def blocked_reader():
        await asyncio.Event().wait()
    processor._read_frame = blocked_reader
    monkeypatch.setattr(module, "settings", settings)
    monkeypatch.setattr(module, "database", database)
    monkeypatch.setattr(module, "processor", processor)
    monkeypatch.setattr(module, "weather_service", Mock(get=Mock(return_value=None)))
    monkeypatch.setattr(module, "fact_service", Mock(get=Mock(return_value="Test fact")))
    return module


def test_api_stays_available_when_model_loading_fails(server):
    server.processor.detector.load.side_effect = OSError("unavailable model")
    with TestClient(server.app) as client:
        deadline = time.monotonic() + 2
        while server.processor.state["last_error"] is None and time.monotonic() < deadline:
            time.sleep(0.001)
        response = client.get("/api/health")
        assert response.status_code == 200
        health = response.json()
        assert not health["ok"]
        assert not health["processor"]["model_loaded"]
        assert "unavailable model" in health["processor"]["last_error"]
        data = client.get("/api/data").json()
        assert data["health"]["last_error"] == health["processor"]["last_error"]
        assert data["status"]["raw_status"] == "AI model unavailable"


@pytest.mark.parametrize("age, processing_ok, expected", [(0, True, True), (60, True, False), (0, False, False)])
def test_api_health_includes_frame_freshness_and_processing(server, age, processing_ok, expected):
    processor = server.processor
    processor.state.update(stream_health="Live", last_frame_at=time.time() - age,
                           processing_ok=processing_ok)
    with TestClient(server.app) as client:
        deadline = time.monotonic() + 2
        while not processor.model_loaded and time.monotonic() < deadline:
            time.sleep(0.001)
        health = client.get("/api/health").json()
        assert health["ok"] is expected
        assert health["processor"]["processing_ok"] is processing_ok
        assert health["processor"]["frame_fresh"] is (age == 0)


def test_stats_api_preserves_response_shape_and_validates_days(server):
    with TestClient(server.app) as client:
        rows = client.get("/api/stats?days=2").json()
        assert len(rows) == 2
        assert set(rows[0]) == {"day", "samples", "occupancy_pct", "activity_pct"}
        assert client.get("/api/stats?days=0").status_code == 422
        assert client.get("/api/stats?days=91").status_code == 422
