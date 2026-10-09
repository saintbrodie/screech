from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings  # noqa: E402
from backend.detector import DetectionSummary, HawkDetector  # noqa: E402


def load_manifest(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    items = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("name")): item for item in items
            if item.get("name") and item.get("enabled", True) is not False}


def source_fields(source: dict[str, Any] | None) -> dict[str, Any]:
    source = source or {}
    return {
        "source_url": source.get("url"), "source_start": source.get("start"),
        "source_end": source.get("end"), "source_video_id": source.get("source_video_id"),
        "human_label": None,
    }


def classify(counts: list[int], active_count: int) -> str:
    if not counts:
        return "unreadable"
    detection_rate = sum(count > 0 for count in counts) / len(counts)
    if max(counts) >= 2:
        return "possible_multiple"
    if detection_rate <= 0.10:
        return "empty_candidate"
    if detection_rate >= 0.70:
        if active_count / len(counts) >= 0.30:
            return "active_one_bird_candidate"
        return "one_bird_candidate"
    return "transition_or_hard_case"


def representative_score(summary: DetectionSummary) -> tuple[int, int, float]:
    """Prefer multi-bird, then active, then high-confidence samples for previewing."""
    return (
        summary.hawk_count,
        1 if summary.behavior == "Active / Moving" else 0,
        summary.confidence or 0.0,
    )


def analyze_clip(
    clip: Path,
    detector: HawkDetector,
    sample_seconds: float,
    preview_dir: Path,
    source: dict[str, Any] | None,
) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        capture.release()
        return {
            "clip": clip.name,
            "category": "unreadable",
            "error": "could_not_open",
            **source_fields(source),
        }

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    sample_frames = max(1, int(round(fps * sample_seconds)))
    counts: list[int] = []
    confidences: list[float] = []
    active_count = 0
    sample_records: list[dict[str, Any]] = []
    best_frame = None
    best_summary: DetectionSummary | None = None
    best_timestamp = 0.0

    detector.cy_history.clear()
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            if frame_index % sample_frames == 0:
                summary = detector.analyze(frame)
                timestamp = frame_index / fps
                counts.append(summary.hawk_count)
                if summary.confidence is not None:
                    confidences.append(summary.confidence)
                if summary.behavior == "Active / Moving":
                    active_count += 1

                sample_records.append(
                    {
                        "timestamp_seconds": round(timestamp, 3),
                        "hawk_count": summary.hawk_count,
                        "behavior": summary.behavior,
                        "confidence": summary.confidence,
                    }
                )

                if best_summary is None or representative_score(summary) > representative_score(best_summary):
                    best_summary = summary
                    best_frame = frame.copy()
                    best_timestamp = timestamp

            frame_index += 1
    finally:
        capture.release()

    sampled = len(counts)
    category = classify(counts, active_count)
    duration_seconds = frame_index / fps
    expected_duration = None
    if source and source.get("start") is not None and source.get("end") is not None:
        expected_duration = float(source["end"]) - float(source["start"])
    truncated = expected_duration is not None and duration_seconds + 0.5 < expected_duration
    if truncated:
        category = "unreadable"
    histogram = {str(count): counts.count(count) for count in sorted(set(counts))}
    preview_path = None
    if best_frame is not None and best_summary is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / f"{clip.stem}.jpg"
        detector.save_image(preview_path, detector.annotate(best_frame, best_summary))

    return {
        "clip": clip.name,
        "category": category,
        "error": "truncated_clip" if truncated else None,
        "decoded_duration_seconds": round(duration_seconds, 3),
        "sampled_frames": sampled,
        "detection_rate_pct": (
            round(100.0 * sum(count > 0 for count in counts) / sampled, 1)
            if sampled
            else 0.0
        ),
        "active_rate_pct": round(100.0 * active_count / sampled, 1) if sampled else 0.0,
        "mean_count": round(statistics.fmean(counts), 3) if counts else 0.0,
        "max_count": max(counts, default=0),
        "mean_confidence": (
            round(statistics.fmean(confidences), 4) if confidences else None
        ),
        "count_histogram": histogram,
        "representative_timestamp_seconds": round(best_timestamp, 3),
        "preview": str(preview_path) if preview_path else None,
        **source_fields(source),
        "samples": sample_records,
    }


def sort_key(result: dict[str, Any]) -> tuple[int, float, float]:
    priority = {
        "possible_multiple": 0,
        "transition_or_hard_case": 1,
        "active_one_bird_candidate": 2,
        "one_bird_candidate": 3,
        "empty_candidate": 4,
        "unreadable": 5,
    }
    return (
        priority.get(str(result.get("category")), 99),
        -float(result.get("detection_rate_pct") or 0.0),
        -float(result.get("mean_confidence") or 0.0),
    )


def print_summary(results: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    for result in results:
        category = str(result.get("category"))
        counts[category] = counts.get(category, 0) + 1

    print("Triage categories:")
    for category in (
        "possible_multiple",
        "transition_or_hard_case",
        "active_one_bird_candidate",
        "one_bird_candidate",
        "empty_candidate",
        "unreadable",
    ):
        if category in counts:
            print(f"  {category:<28} {counts[category]:>3}")


def write_report(path: Path, results: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(sorted(results, key=sort_key), indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan downloaded Hawk Cam triage clips and rank candidates for human labeling."
    )
    parser.add_argument(
        "--clips-dir",
        type=Path,
        default=Path("tests/fixtures/triage"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/triage.json"),
    )
    parser.add_argument("--model", default=settings.model_path)
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    parser.add_argument(
        "--preview-dir",
        type=Path,
        default=Path("tests/fixtures/triage-previews"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/triage-results.json"),
    )
    args = parser.parse_args()
    if not 0 < args.sample_seconds < float("inf"):
        parser.error("--sample-seconds must be positive and finite")

    clips = sorted(
        path
        for path in args.clips_dir.glob("*")
        if path.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"}
    )
    manifest = load_manifest(args.manifest)
    if not clips and not manifest:
        raise SystemExit(f"No video clips found in {args.clips_dir}")

    detector = HawkDetector(replace(settings, model_path=args.model))
    if clips:
        print(f"Loading {args.model}...")
        detector.load()

    available = {clip.stem for clip in clips}
    results: list[dict[str, Any]] = [
        {"clip": f"{name}.mp4", "category": "unreadable", "error": "missing_clip",
         **source_fields(source)}
        for name, source in manifest.items() if name not in available
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for index, clip in enumerate(clips, start=1):
        print(f"[{index}/{len(clips)}] {clip.name}")
        try:
            result = analyze_clip(
                clip,
                detector,
                args.sample_seconds,
                args.preview_dir,
                manifest.get(clip.stem),
            )
        except Exception as exc:
            result = {"clip": clip.name, "category": "unreadable", "error": str(exc),
                      **source_fields(manifest.get(clip.stem))}
            print(f"Warning: could not analyze {clip.name}: {exc}", file=sys.stderr)
        results.append(result)
        result["model"] = args.model
        result["sample_seconds"] = args.sample_seconds
        # Preserve completed analyses if a later clip or the process fails.
        write_report(args.output, results)

    results.sort(key=sort_key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, results)
    print_summary(results)
    print(f"\nWrote ranked triage report to {args.output}")
    print(f"Representative annotated previews are in {args.preview_dir}")


if __name__ == "__main__":
    main()
