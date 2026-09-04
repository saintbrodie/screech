from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import download_range_func


DEFAULT_CHANNEL = "https://www.youtube.com/@GDIT-HawkCam"


def canonical_watch_url(item: dict[str, Any]) -> str | None:
    video_id = item.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    for key in ("webpage_url", "url"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def discover(channel_url: str, limit: int) -> list[dict[str, Any]]:
    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"{channel_url.rstrip('/')}/videos", download=False)

    entries = []
    for item in info.get("entries") or []:
        entries.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "url": canonical_watch_url(item),
                "duration": item.get("duration"),
                "upload_date": item.get("upload_date"),
                "timestamp": item.get("timestamp"),
            }
        )
    return entries


def download_manifest(manifest_path: Path, output_dir: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)

    for clip in manifest:
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
        description="Discover GDIT Hawk Cam uploads or fetch timestamped local regression clips."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    discover_parser = sub.add_parser("discover")
    discover_parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    discover_parser.add_argument("--limit", type=int, default=20)
    discover_parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/discovered.json"),
    )

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
        entries = discover(args.channel, args.limit)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        print(f"Wrote {len(entries)} entries to {args.output}")
        return

    download_manifest(args.manifest, args.output_dir)


if __name__ == "__main__":
    main()
