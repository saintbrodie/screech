from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings  # noqa: E402
from backend.detector import HawkDetector  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Screech detection over a local test clip.")
    parser.add_argument("clip", type=Path)
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/results.json"))
    parser.add_argument(
        "--annotated-dir",
        type=Path,
        default=Path("tests/fixtures/annotated"),
    )
    args = parser.parse_args()

    capture = cv2.VideoCapture(str(args.clip))
    if not capture.isOpened():
        raise SystemExit(f"Could not open {args.clip}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    sample_frames = max(1, int(round(fps * args.sample_seconds)))
    detector = HawkDetector(settings)
    detector.load()
    args.annotated_dir.mkdir(parents=True, exist_ok=True)

    results = []
    frame_index = 0
    sample_index = 0

    while True:
        ok, frame = capture.read()
        if not ok:
            break

        if frame_index % sample_frames == 0:
            summary = detector.analyze(frame)
            timestamp = frame_index / fps
            record = {
                "timestamp_seconds": round(timestamp, 3),
                "hawk_count": summary.hawk_count,
                "identity": summary.identity,
                "behavior": summary.behavior,
                "confidence": summary.confidence,
                "raw_status": summary.raw_status,
                "detections": [
                    {
                        "xyxy": list(detection.xyxy),
                        "confidence": detection.confidence,
                        "area_ratio": detection.area_ratio,
                    }
                    for detection in summary.detections
                ],
            }
            results.append(record)

            annotated = detector.annotate(frame, summary)
            image_path = args.annotated_dir / f"frame_{sample_index:05d}.jpg"
            detector.save_image(image_path, annotated)
            sample_index += 1

        frame_index += 1

    capture.release()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Analyzed {len(results)} sampled frames -> {args.output}")


if __name__ == "__main__":
    main()
