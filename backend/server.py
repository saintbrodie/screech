from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIR, settings
from .database import Database
from .processor import HawkProcessor
from .services import FactService, WeatherService


settings.ensure_directories()
database = Database(settings.db_path)
database.initialize()
processor = HawkProcessor(settings, database)
weather_service = WeatherService(
    settings.weather_latitude,
    settings.weather_longitude,
    settings.weather_ttl_seconds,
)
fact_service = FactService(settings.fact_ttl_seconds)


def configured_youtube_video_id() -> str | None:
    source = settings.video_source.strip()
    if not source:
        return settings.video_id

    parsed = urlparse(source)
    host = parsed.netloc.lower().split(":", 1)[0]

    if host in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/", 1)[0] or None

    if host.endswith("youtube.com"):
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id:
            return query_id

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
            return parts[1]

    return None


def video_metadata() -> dict[str, str | None]:
    video_id = configured_youtube_video_id()
    embed_url = (
        f"https://www.youtube.com/embed/{video_id}?autoplay=1&mute=1"
        if video_id
        else None
    )
    return {"video_id": video_id, "embed_url": embed_url}


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(processor.run(), name="screech-hawk-processor")
    try:
        yield
    finally:
        processor.request_stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="S.C.R.E.E.C.H.", version="2.0.0", lifespan=lifespan)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )


@app.get("/api/status")
async def get_status():
    return dict(processor.state)


@app.get("/api/weather")
async def get_weather():
    weather = await asyncio.to_thread(weather_service.get)
    return weather or {"error": "Could not fetch weather"}


@app.get("/api/facts")
async def get_facts():
    return {"fact": fact_service.get()}


@app.get("/api/timeline")
async def get_timeline():
    return await asyncio.to_thread(database.timeline, settings.timeline_limit)


@app.get("/api/stats")
async def get_stats(days: int = Query(default=settings.stats_days, ge=1, le=90)):
    return await asyncio.to_thread(database.daily_stats, days)


@app.get("/api/health")
async def get_health():
    db_health = await asyncio.to_thread(database.health)
    processor_health = processor.health()
    ok = (
        db_health["ok"]
        and processor_health["model_loaded"]
        and processor_health["source_ok"]
    )
    return {
        "ok": ok,
        "processor": processor_health,
        "database": db_health,
    }


@app.get("/api/data")
async def get_bulk_data():
    weather, timeline, stats = await asyncio.gather(
        asyncio.to_thread(weather_service.get),
        asyncio.to_thread(database.timeline, settings.timeline_limit),
        asyncio.to_thread(database.daily_stats, settings.stats_days),
    )
    return {
        "status": dict(processor.state),
        "timeline": timeline,
        "fact": fact_service.get(),
        "weather": weather,
        "stats": stats,
        "health": processor.health(),
        "video": video_metadata(),
    }


if settings.save_snapshots:
    app.mount(
        "/snapshots",
        StaticFiles(directory=str(settings.snapshot_dir)),
        name="snapshots",
    )

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
