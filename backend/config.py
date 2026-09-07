from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    video_id: str = os.getenv("SCREECH_VIDEO_ID", "HRhToy9dA-Q")
    video_source: str = os.getenv("SCREECH_VIDEO_SOURCE", "")
    model_path: str = os.getenv("SCREECH_MODEL", "yolo26n.pt")

    detector_confidence: float = _env_float("SCREECH_DETECTOR_CONFIDENCE", 0.08)
    min_box_area_ratio: float = _env_float("SCREECH_MIN_BOX_AREA_RATIO", 0.005)
    female_area_ratio: float = _env_float("SCREECH_FEMALE_AREA_RATIO", 0.08)
    identity_deadband: float = _env_float("SCREECH_IDENTITY_DEADBAND", 0.01)
    identity_mode: str = os.getenv("SCREECH_IDENTITY_MODE", "size").strip().lower()

    scan_interval_seconds: float = _env_float("SCREECH_SCAN_INTERVAL_SECONDS", 5.0)
    stream_retry_seconds: float = _env_float("SCREECH_STREAM_RETRY_SECONDS", 10.0)
    empty_confirmations: int = _env_int("SCREECH_EMPTY_CONFIRMATIONS", 8)
    state_confirmations: int = _env_int("SCREECH_STATE_CONFIRMATIONS", 3)
    behavior_history: int = _env_int("SCREECH_BEHAVIOR_HISTORY", 6)
    movement_stddev_ratio: float = _env_float("SCREECH_MOVEMENT_STDDEV_RATIO", 0.012)

    weather_latitude: float = _env_float("SCREECH_WEATHER_LATITUDE", 38.8681)
    weather_longitude: float = _env_float("SCREECH_WEATHER_LONGITUDE", -77.2183)
    weather_ttl_seconds: int = _env_int("SCREECH_WEATHER_TTL_SECONDS", 600)
    fact_ttl_seconds: int = _env_int("SCREECH_FACT_TTL_SECONDS", 60)

    observation_interval_seconds: int = _env_int("SCREECH_OBSERVATION_INTERVAL_SECONDS", 60)
    timeline_limit: int = _env_int("SCREECH_TIMELINE_LIMIT", 10)
    stats_days: int = _env_int("SCREECH_STATS_DAYS", 7)
    save_snapshots: bool = _env_bool("SCREECH_SAVE_SNAPSHOTS", True)
    save_crops: bool = _env_bool("SCREECH_SAVE_CROPS", True)
    loop_local_source: bool = _env_bool("SCREECH_LOOP_LOCAL_SOURCE", True)

    data_dir: Path = Path(os.getenv("SCREECH_DATA_DIR", str(BACKEND_DIR))).expanduser().resolve()
    db_path: Path = Path(
        os.getenv("SCREECH_DB_PATH", str(BACKEND_DIR / "hawk_data.db"))
    ).expanduser().resolve()

    allowed_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("SCREECH_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    )

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def crop_dir(self) -> Path:
        return self.data_dir / "crops"

    @property
    def youtube_watch_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.save_snapshots:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if self.save_crops:
            self.crop_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
