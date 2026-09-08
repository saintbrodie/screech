from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, download_range_func


DEFAULT_CHANNEL = "https://www.youtube.com/@GDIT-HawkCam"
DEFAULT_TABS = ("videos", "streams")


def _missing_tab_message(message: str) -> bool:
    lowered = message.lower()
    return "this channel does not have a" in lowered and "tab" in lowered


class DiscoveryLogger:
    """Keep expected missing-tab errors from looking like discovery failures."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        print(f"yt-dlp warning: {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        if _missing_tab_message(message):
            return
        print(f"yt-dlp error: {message}", file=sys.stderr)


def canonical_watch_url(item: dict[str, Any]) -> str | None:
    video_id = item.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    for key in ("webpage_url", "url"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def discover(
    channel_url: str,
    limit_per_tab: int,
    tabs: tuple[str, ...] = DEFAULT_TABS,
) -> list[dict[str, Any]]:
    """Discover ordinary uploads and archived livestreams, deduplicated by video ID."""
    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit_per_tab,
        "logger": DiscoveryLogger(),
    }

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    with YoutubeDL(options) as ydl:
        for tab in tabs:
            tab_url = f"{channel_url.rstrip('/')}/{tab}"
            try:
                info = ydl.extract_info(tab_url, download=False)
            except DownloadError as exc:
                if _missing_tab_message(str(exc)):
                    print(f"Skipping unavailable channel tab: {tab}", file=sys.stderr)
                else:
                    print(f"Warning: could not inspect {tab_url}: {exc}", file=sys.stderr)
                continue

            for item in info.get("entries") or []:
                video_id = item.get("id")
                url = canonical_watch_url(item)
                dedupe_key = str(video_id or url or item.get("title"))
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                entries.append(
                    {
                        "id": video_id,
                        "title": item.get("title"),
                        "url": url,
                        "duration": item.get("duration"),
                        "upload_date": item.get("upload_date"),
                        "timestamp": item.get("timestamp"),
                        "source_tab": tab,
                    }
                )

    return entries


def build_triage_manifest(
    entries: list[dict[str, Any]],
    clip_seconds: float = 10.0,
    samples_per_stream: int = 2,
) -> list[dict[str, Any]]:
    """Create evenly spaced short windows for quickly triaging an archive."""
    if clip_seconds <= 0:
        raise ValueError("clip_seconds must be positive")
    if samples_per_stream < 1:
        raise ValueError("samples_per_stream must be at least 1")

    manifest: list[dict[str, Any]] = []
    fractions = [
        (index + 1) / (samples_per_stream + 1)
        for index in range(samples_per_stream)
    ]

    for source_index, item in enumerate(entries, start=1):
        url = item.get("url")
        video_id = str(item.get("id") or f"source{source_index:02d}")
        duration_value = item.get("duration")
        try:
            duration = float(duration_value)
        except (TypeError, ValueError):
            continue
        if not url or duration <= 0:
            continue

        effective_clip = min(clip_seconds, duration)
        if duration <= effective_clip:
            starts = [0.0]
        else:
            starts = []
            for fraction in fractions:
                center = duration * fraction
                start = center - effective_clip / 2.0
                start = max(0.0, min(duration - effective_clip, start))
                rounded = round(start, 3)
                if rounded not in starts:
                    starts.append(rounded)

        for sample_index, start in enumerate(starts, start=1):
            end = min(duration, start + effective_clip)
            safe_id = "".join(char if char.isalnum() else "_" for char in video_id)
            name = f"triage_{source_index:02d}_{sample_index:02d}_{safe_id}_{int(start):06d}"
            manifest.append(
                {
                    "name": name,
                    "url": url,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "source_video_id": item.get("id"),
                    "source_duration": duration_value,
                    "source_title": item.get("title"),
                    "triage_fraction": round((start + effective_clip / 2.0) / duration, 4),
                    "notes": "Auto-generated unlabeled triage window. Inspect before assigning expected_count.",
                }
            )

    return manifest


def download_manifest(manifest_path: Path, output_dir: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)

    for clip in manifest:
        if clip.get("enabled", True) is False:
            print(f"Skipping disabled fixture entry: {clip.get('name', '<unnamed>')}")
            continue

        name = clip["name"]
        url = clip["url"]
        start = float(clip["start"])
        end = float(clip["end"])
        if end <= start:
            raise ValueError(f"{name}: end must be after start")

        # yt-dlp's CLI calls this feature --download-sections, but the Python
        # API consumes a callable in the `download_ranges` option.
        options = {
            "quiet": False,
            "no_warnings": False,
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "merge_output_format": "mp4",
            "download_ranges": download_range_func([], [[start, end]]),
            "force_keyframes_at_cuts": True,
            "outtmpl": str(output_dir / f"{name}.%(ext)s"),
        }
        with YoutubeDL(options) as ydl:
            ydl.download([url])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover, triage, or fetch timestamped GDIT Hawk Cam regression clips."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    discover_parser = sub.add_parser("discover")
    discover_parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    discover_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum entries to inspect per selected channel tab.",
    )
    discover_parser.add_argument(
        "--tabs",
        nargs="+",
        choices=("videos", "streams"),
        default=list(DEFAULT_TABS),
        help="Channel tabs to inspect. Defaults to both videos and archived streams.",
    )
    discover_parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/discovered.json"),
    )

    triage_parser = sub.add_parser("triage")
    triage_parser.add_argument(
        "--discovered",
        type=Path,
        default=Path("tests/fixtures/discovered.json"),
    )
    triage_parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/triage.json"),
    )
    triage_parser.add_argument("--clip-seconds", type=float, default=10.0)
    triage_parser.add_argument("--samples-per-stream", type=int, default=2)

    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/clips.json"),
    )
    fetch_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/fixtures/clips"),
    )

    args = parser.parse_args()

    if args.command == "discover":
        entries = discover(args.channel, args.limit, tuple(args.tabs))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        print(f"Wrote {len(entries)} deduplicated entries to {args.output}")
        return

    if args.command == "triage":
        entries = json.loads(args.discovered.read_text(encoding="utf-8"))
        manifest = build_triage_manifest(
            entries,
            clip_seconds=args.clip_seconds,
            samples_per_stream=args.samples_per_stream,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        total_seconds = sum(float(item["end"]) - float(item["start"]) for item in manifest)
        print(
            f"Wrote {len(manifest)} unlabeled triage windows "
            f"({total_seconds:.0f}s total) to {args.output}"
        )
        return

    download_manifest(args.manifest, args.output_dir)


if __name__ == "__main__":
    main()
