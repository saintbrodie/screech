from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
from yt_dlp import YoutubeDL

from .config import PROJECT_ROOT, Settings
from .database import Database
from .detector import DetectionSummary, HawkDetector
from .state import NestStateMachine


def resolve_youtube_stream(url: str) -> str:
    options = {
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 15,
        "noplaylist": True,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        return info["url"]


class LatestFrameCapture:
    """Continuously drain a live capture so inference always sees the newest frame."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError("Video source could not be opened")

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._reader,
            name="screech-frame-grabber",
            daemon=True,
        )
        self._frame = None
        self.last_frame_at: float | None = None
        self.error: str | None = None
        self._thread.start()

    def _reader(self) -> None:
        while not self._stop.is_set():
            ok, frame = self.capture.read()
            if not ok or frame is None:
                self.error = "Video source returned no frame"
                break
            with self._lock:
                self._frame = frame
                self.last_frame_at = time.time()

    def latest(self):
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    @property
    def alive(self) -> bool:
        return self._thread.is_alive() and self.error is None

    def close(self) -> None:
        self._stop.set()
        self.capture.release()
        if self._thread.is_alive():
            self._thread.join(timeout=2)


class HawkProcessor:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.detector = HawkDetector(settings)
        self.machine = NestStateMachine(
            empty_confirmations=settings.empty_confirmations,
            state_confirmations=settings.state_confirmations,
        )

        self.live_capture: LatestFrameCapture | None = None
        self.file_capture: cv2.VideoCapture | None = None
        self.stop_event = asyncio.Event()
        self.last_observation_at = 0.0
        self.model_loaded = False
        self.started_at: float | None = None

        self.state: dict[str, Any] = {
            "status": "Initializing AI model...",
            "raw_status": "No scan yet",
            "hawk_count": 0,
            "raw_hawk_count": 0,
            "last_updated": None,
            "last_frame_at": None,
            "stream_health": "Connecting",
            "behavior": "Unknown",
            "confidence": None,
            "identity": "unknown",
            "model": settings.model_path,
            "source_mode": "configured" if settings.video_source else "youtube_live",
        }

    def request_stop(self) -> None:
        self.stop_event.set()

    @staticmethod
    def _is_network_source(source: str) -> bool:
        scheme = urlparse(source).scheme.lower()
        return scheme in {"http", "https", "rtsp", "rtmp", "udp", "tcp"}

    def _local_source_path(self) -> Path | None:
        source = self.settings.video_source.strip()
        if not source or self._is_network_source(source):
            return None

        candidate = Path(source).expanduser()
        if candidate.is_absolute():
            return candidate.resolve() if candidate.exists() else None

        cwd_candidate = (Path.cwd() / candidate).resolve()
        if cwd_candidate.exists():
            return cwd_candidate

        repo_candidate = (PROJECT_ROOT / candidate).resolve()
        if repo_candidate.exists():
            return repo_candidate
        return None

    def _source_is_local_file(self) -> bool:
        return self._local_source_path() is not None

    async def _resolved_source(self) -> str:
        if self.settings.video_source:
            source = self.settings.video_source.strip()
            local_path = self._local_source_path()
            if local_path is not None:
                return str(local_path)
            if source.startswith(("https://www.youtube.com/", "https://youtu.be/")):
                return await asyncio.to_thread(resolve_youtube_stream, source)
            if self._is_network_source(source):
                return source
            raise FileNotFoundError(
                f"Configured local video source was not found: {source!r}. "
                f"Relative paths are checked from the current directory and {PROJECT_ROOT}."
            )
        return await asyncio.to_thread(resolve_youtube_stream, self.settings.youtube_watch_url)

    async def _open_capture(self) -> None:
        source = await self._resolved_source()
        self.state["status"] = "Connecting to video source..."

        if self._source_is_local_file():
            capture = await asyncio.to_thread(cv2.VideoCapture, source)
            if not await asyncio.to_thread(capture.isOpened):
                await asyncio.to_thread(capture.release)
                raise RuntimeError("Local fixture could not be opened")
            self.file_capture = capture
            self.state["stream_health"] = "Fixture"
            self.state["source_mode"] = "fixture"
        else:
            self.live_capture = await asyncio.to_thread(LatestFrameCapture, source)
            deadline = time.monotonic() + 15
            while self.live_capture.latest() is None:
                if not self.live_capture.alive:
                    error = self.live_capture.error or "Live frame grabber stopped"
                    await self._release_capture()
                    raise RuntimeError(error)
                if time.monotonic() >= deadline:
                    await self._release_capture()
                    raise RuntimeError("Timed out waiting for the first live frame")
                await asyncio.sleep(0.1)
            self.state["stream_health"] = "Live"
            self.state["source_mode"] = "stream"

        self.state["status"] = self.machine.stable_status or "Analyzing video feed..."

    async def _release_capture(self) -> None:
        if self.live_capture is not None:
            capture = self.live_capture
            self.live_capture = None
            await asyncio.to_thread(capture.close)

        if self.file_capture is not None:
            capture = self.file_capture
            self.file_capture = None
            await asyncio.to_thread(capture.release)

    async def _read_frame(self):
        if self.live_capture is None and self.file_capture is None:
            await self._open_capture()

        if self.file_capture is not None:
            ok, frame = await asyncio.to_thread(self.file_capture.read)
            if ok and frame is not None:
                return frame

            if self.settings.loop_local_source:
                await asyncio.to_thread(self.file_capture.set, cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = await asyncio.to_thread(self.file_capture.read)
                if ok and frame is not None:
                    return frame

            await self._release_capture()
            raise RuntimeError("Local fixture reached end of file")

        assert self.live_capture is not None
        frame = self.live_capture.latest()
        if frame is not None and self.live_capture.alive:
            return frame

        error = self.live_capture.error or "Live frame grabber stopped"
        await self._release_capture()
        raise RuntimeError(error)

    def _timestamp_name(self, prefix: str = "event") -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        return f"{prefix}_{stamp}"

    async def _save_transition_media(
        self,
        frame,
        summary: DetectionSummary,
    ) -> str | None:
        base_name = self._timestamp_name()
        snapshot_path: Path | None = None

        if self.settings.save_snapshots:
            snapshot_path = self.settings.snapshot_dir / f"{base_name}.jpg"
            annotated = await asyncio.to_thread(self.detector.annotate, frame, summary)
            await asyncio.to_thread(self.detector.save_image, snapshot_path, annotated)

        if self.settings.save_crops and summary.detections:
            await asyncio.to_thread(
                self.detector.save_crops,
                base_name,
                frame,
                summary,
                self.settings.crop_dir,
            )

        return str(snapshot_path) if snapshot_path else None

    async def _process_frame(self, frame) -> None:
        summary = await asyncio.to_thread(self.detector.analyze, frame)
        now = time.time()

        self.state["raw_status"] = summary.raw_status
        self.state["raw_hawk_count"] = summary.hawk_count
        self.state["behavior"] = summary.behavior
        self.state["confidence"] = (
            round(summary.confidence, 3) if summary.confidence is not None else None
        )
        self.state["identity"] = summary.identity
        self.state["last_updated"] = now
        self.state["last_frame_at"] = now
        self.state["stream_health"] = "Fixture" if self.file_capture is not None else "Live"

        transition = self.machine.update(summary.hawk_count, summary.identity)
        if transition is not None:
            snapshot_path = await self._save_transition_media(frame, summary)
            self.state["status"] = transition.status
            self.state["hawk_count"] = transition.hawk_count

            await asyncio.to_thread(
                self.database.log_event,
                event_type=transition.event_type,
                text=transition.status,
                hawk_count=summary.hawk_count,
                confidence=summary.confidence,
                snapshot_path=snapshot_path,
            )
        elif self.machine.stable_status:
            self.state["status"] = self.machine.stable_status

        if now - self.last_observation_at >= self.settings.observation_interval_seconds:
            await asyncio.to_thread(
                self.database.log_observation,
                hawk_count=summary.hawk_count,
                behavior=summary.behavior,
                confidence=summary.confidence,
            )
            self.last_observation_at = now

    async def run(self) -> None:
        self.started_at = time.time()
        try:
            self.state["status"] = "Loading AI model..."
            await asyncio.to_thread(self.detector.load)
            self.model_loaded = True
            self.state["status"] = "Connecting to video source..."

            while not self.stop_event.is_set():
                try:
                    frame = await self._read_frame()
                    await self._process_frame(frame)
                    await asyncio.sleep(self.settings.scan_interval_seconds)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.state["stream_health"] = "Offline"
                    self.state["status"] = f"Source error: {exc}"
                    await self._release_capture()
                    await asyncio.sleep(self.settings.stream_retry_seconds)
        finally:
            await self._release_capture()

    def health(self) -> dict[str, Any]:
        now = time.time()
        frame_age = (
            round(now - self.state["last_frame_at"], 1)
            if self.state["last_frame_at"]
            else None
        )
        source_ok = self.state["stream_health"] in {"Live", "Fixture"}
        return {
            "model_loaded": self.model_loaded,
            "source_ok": source_ok,
            "stream_health": self.state["stream_health"],
            "frame_age_seconds": frame_age,
            "source_mode": self.state["source_mode"],
            "model": self.settings.model_path,
            "uptime_seconds": round(now - self.started_at, 1) if self.started_at else 0,
        }
