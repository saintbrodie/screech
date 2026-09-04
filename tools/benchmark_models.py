from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings  # noqa: E402
from backend.detector import HawkDetector  # noqa: E402


def load_expected_counts(manifest_path: Path | None) -> dict[str, int]:
    if manifest_path is None or not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected: dict[str, int] = {}
    for item in manifest:
        value = item.get("expected_count")
        if isinstance(value, int):
            expected[item["name"]] = value
    return expected


def analyze_clip(
    clip: Path,
    detector: HawkDetector,
    sample_seconds: float,
    expected_count: int | None,
) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {clip}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    sample_frames = max(1, int(round(fps * sample_seconds)))
    frame_index = 0
    counts: list[int] = []
    confidences: list[float] = []
    latencies: list[float] = []

    detector.cy_history.clear()

    while True:
        ok, frame = capture.read()
        if not ok:
            break

        if frame_index % sample_frames == 0:
            started = time.perf_counter()
            summary = detector.analyze(frame)
            latencies.append(time.perf_counter() - started)
            counts.append(summary.hawk_count)
            if summary.confidence is not None:
                confidences.append(summary.confidence)

        frame_index += 1

    capture.release()

    sampled = len(counts)
    exact_accuracy = None
    if expected_count is not None and sampled:
        exact_accuracy = round(
            100.0 * sum(count == expected_count for count in counts) / sampled,
            1,
        )

    histogram = {str(count): counts.count(count) for count in sorted(set(counts))}
    return {
        "clip": clip.name,
        "sampled_frames": sampled,
        "expected_count": expected_count,
        "exact_count_accuracy_pct": exact_accuracy,
        "detection_rate_pct": (
            round(100.0 * sum(count > 0 for count in counts) / sampled, 1)
            if sampled
            else 0.0
        ),
        "mean_count": round(statistics.fmean(counts), 3) if counts else 0.0,
        "mean_confidence": (
            round(statistics.fmean(confidences), 4) if confidences else None
        ),
        "mean_inference_ms": (
            round(statistics.fmean(latencies) * 1000.0, 2) if latencies else None
        ),
        "count_histogram": histogram,
    }


def print_summary(results: list[dict[str, Any]]) -> None:
    header = (
        f"{'MODEL':<16} {'CLIP':<34} {'N':>5} {'DETECT%':>8} "
        f"{'COUNT-ACC%':>11} {'CONF':>7} {'MS':>9}"
    )
    print(header)
    print("-" * len(header))
    for result in results:
        acc = result["exact_count_accuracy_pct"]
        confidence = result["mean_confidence"]
        latency = result["mean_inference_ms"]
        print(
            f"{result['model']:<16} {result['clip']:<34} "
            f"{result['sampled_frames']:>5} {result['detection_rate_pct']:>8.1f} "
            f"{(f'{acc:.1f}' if acc is not None else '--'):>11} "
            f"{(f'{confidence:.3f}' if confidence is not None else '--'):>7} "
            f"{(f'{latency:.1f}' if latency is not None else '--'):>9}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Screech detector models across the same local hawk fixtures."
    )
    parser.add_argument(
        "clips",
        nargs="*",
        type=Path,
        help="Clip paths. Defaults to every video in tests/fixtures/clips.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["yolo26n.pt", "yolov8n.pt"],
    )
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/clips.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/benchmark-results.json"),
    )
    args = parser.parse_args()

    clips = args.clips
    if not clips:
        fixture_dir = Path("tests/fixtures/clips")
        clips = sorted(
            path
            for path in fixture_dir.glob("*")
            if path.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"}
        )
    if not clips:
        raise SystemExit("No local fixture clips found. Run fetch_test_clips.py first.")

    expected_counts = load_expected_counts(args.manifest)
    all_results: list[dict[str, Any]] = []

    for model_name in args.models:
        model_settings = replace(settings, model_path=model_name)
        detector = HawkDetector(model_settings)
        print(f"Loading {model_name}...")
        detector.load()

        for clip in clips:
            result = analyze_clip(
                clip,
                detector,
                args.sample_seconds,
                expected_counts.get(clip.stem),
            )
            result["model"] = model_name
            all_results.append(result)

        del detector

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print_summary(all_results)
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
