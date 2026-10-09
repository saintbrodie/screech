import asyncio
import time
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.config import Settings
from backend.database import Database
from backend.detector import DetectionSummary
from backend.processor import HawkProcessor


SUMMARY = DetectionSummary(1, "unknown", "Incubating / Resting", 0.8, [], "One bird")


@pytest.fixture
def processor(tmp_path):
    fixture = tmp_path / "fixture.mp4"
    fixture.touch()
    settings = replace(Settings(), video_source=str(fixture), data_dir=tmp_path,
                       db_path=tmp_path / "test.db", save_snapshots=False, save_crops=False,
                       scan_interval_seconds=0, stream_retry_seconds=0,
                       observation_interval_seconds=0)
    database = Database(settings.db_path)
    database.initialize()
    result = HawkProcessor(settings, database)
    result.detector.load = Mock()
    result.detector.analyze = Mock(return_value=SUMMARY)
    return result


def fake_capture(*, readable=True):
    capture = Mock()
    capture.isOpened.return_value = True
    capture.read.return_value = (readable, object() if readable else None)
    return capture


def stop_after_scans(processor, scans=2):
    original = processor._process_frame
    count = 0

    async def process(frame):
        nonlocal count
        count += 1
        try:
            await original(frame)
        finally:
            if count >= scans:
                processor.request_stop()
    processor._process_frame = process


def test_model_load_failure_remains_visible_and_never_opens_source(processor):
    processor.detector.load.side_effect = OSError("missing weights")
    processor._open_capture = AsyncMock()
    asyncio.run(processor.run())
    assert not processor.health()["model_loaded"]
    assert not processor.health()["source_ok"]
    assert "Model load error: missing weights" == processor.health()["last_error"]
    processor._open_capture.assert_not_awaited()


def test_source_disconnect_reopens_capture_and_retains_error(processor, monkeypatch):
    broken, healthy = fake_capture(readable=False), fake_capture()
    open_capture = Mock(side_effect=[broken, healthy])
    monkeypatch.setattr("backend.processor.cv2.VideoCapture", open_capture)
    stop_after_scans(processor, 1)
    asyncio.run(processor.run())
    assert open_capture.call_count == 2
    broken.release.assert_called_once()
    healthy.release.assert_called_once()
    assert processor.state["raw_hawk_count"] == 1
    assert "Source error" in processor.state["last_error"]
    assert processor.state["stream_health"] == "Stopped"


@pytest.mark.parametrize("failure", ["event", "observation", "media", "inference"])
def test_processing_failures_do_not_reconnect_healthy_video(processor, monkeypatch, failure):
    capture = fake_capture()
    open_capture = Mock(return_value=capture)
    monkeypatch.setattr("backend.processor.cv2.VideoCapture", open_capture)
    if failure == "event":
        processor.database.log_event = Mock(side_effect=OSError("disk full"))
    elif failure == "observation":
        processor.database.log_observation = Mock(side_effect=OSError("disk full"))
    elif failure == "media":
        processor._save_transition_media = AsyncMock(side_effect=OSError("disk full"))
    else:
        processor.detector.analyze.side_effect = [RuntimeError("inference failed"), SUMMARY]
    stop_after_scans(processor)
    asyncio.run(processor.run())
    assert open_capture.call_count == 1
    assert capture.read.call_count == 2
    capture.release.assert_called_once()  # Shutdown, not a reconnect.
    assert processor.state["last_error"] is not None
    assert processor.detector.analyze.call_count == 2


def test_live_stale_frame_is_released_even_when_reader_claims_alive(processor):
    capture = Mock()
    capture.alive = True
    capture.latest.return_value = object()
    capture.last_frame_at = time.time() - processor.settings.frame_stale_seconds - 1
    processor.live_capture = capture
    processor.state["stream_health"] = "Live"
    with pytest.raises(RuntimeError, match="stale"):
        asyncio.run(processor._read_frame())
    capture.close.assert_called_once()
    assert processor.live_capture is None


def test_inference_does_not_refresh_capture_timestamp(processor):
    capture = Mock()
    capture.alive = True
    capture.latest.return_value = object()
    captured_at = time.time() - 5
    capture.last_frame_at = captured_at
    processor.live_capture = capture

    async def scan():
        frame = await processor._read_frame()
        await processor._process_frame(frame)
    asyncio.run(scan())
    assert processor.state["last_frame_at"] == captured_at
    assert processor.health()["frame_age_seconds"] >= 5


@pytest.mark.parametrize("age, fresh", [(None, False), (0, True), (29.96, True), (30, False), (60, False)])
def test_health_requires_a_fresh_frame(processor, monkeypatch, age, fresh):
    monkeypatch.setattr("backend.processor.time.time", lambda: 1000)
    processor.state["stream_health"] = "Fixture"
    processor.state["last_frame_at"] = None if age is None else 1000 - age
    assert processor.health()["source_ok"] is fresh
    assert processor.health()["frame_fresh"] is fresh


def test_storage_error_marks_processing_unhealthy_and_recovery_keeps_history(processor):
    processor.database.log_observation = Mock(side_effect=[OSError("locked DB"), None])
    processor.state["last_frame_at"] = time.time()
    asyncio.run(processor._process_frame(object()))
    assert processor.health()["source_ok"]
    assert not processor.health()["processing_ok"]
    error = processor.health()["last_error"]
    asyncio.run(processor._process_frame(object()))
    assert processor.health()["processing_ok"]
    assert processor.health()["last_error"] == error


@pytest.mark.parametrize("cancel", [False, True])
def test_shutdown_releases_capture_during_long_scan_pause(processor, monkeypatch, cancel):
    capture = fake_capture()
    monkeypatch.setattr("backend.processor.cv2.VideoCapture", Mock(return_value=capture))
    processor.settings = replace(processor.settings, scan_interval_seconds=3600)

    async def run_and_stop():
        task = asyncio.create_task(processor.run())

        async def wait_for_scan():
            while processor.state["last_updated"] is None:
                await asyncio.sleep(0.001)
        await asyncio.wait_for(wait_for_scan(), 2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            processor.request_stop()
            await asyncio.wait_for(task, 1)
    asyncio.run(run_and_stop())
    capture.release.assert_called_once()
    assert processor.file_capture is None
    assert processor.state["stream_health"] == "Stopped"
