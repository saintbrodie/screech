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
    }

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    with YoutubeDL(options) as ydl:
        for tab in tabs:
            tab_url = f"{channel_url.rstrip('/')}/{tab}"
            try:
                info = ydl.extract_info(tab_url, download=False)
            except DownloadError as exc:
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
        description="Discover GDIT Hawk Cam uploads/streams or fetch timestamped regression clips."
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

    download_manifest(args.manifest, args.output_dir)


if __name__ == "__main__":
    main()
