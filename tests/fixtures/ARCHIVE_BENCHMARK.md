# Human-reviewed archive benchmark

The October 9, 2026 review contains 40 ten-second windows from 20 GDIT Hawk Cam
archives. The human reviewer supplied 35 constant counts and marked five clips
uncertain. The labeled distribution is nine empty, 23 one-bird, and one each
with two, three, and four birds. Counts include visible chicks. Eggs are not birds.

The source ranges, verification, and reviewer notes are preserved in
[`archive-labeled.json`](archive-labeled.json). Following the reviewer's correction,
`triage_16_02_OazVlA6kdEs_002383` has count 1, matching its “adult resting” note.
The original downloaded review exports are unchanged.

## Results

Each model sampled the same footage once per second: 350 scored frames, plus
50 uncertain frames excluded from accuracy. The separate unlabeled 30-second
smoke clip was also analyzed and excluded from these totals. Settings were
confidence 0.08, NMS IoU 0.50, and minimum box area ratio 0.005.

| Model | Exact count, all 350 | Empty, 90 | One bird, 230 | Multiple, 30 | Empty false positives | Occupied misses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| YOLO11n | 51.14% | 96.67% | 39.57% | 3.33% | 3/90 | 100/260 |
| YOLO26n | 52.86% | 91.11% | 44.35% | 3.33% | 8/90 | 61/260 |
| YOLOv8n | 67.43% | 97.78% | 64.35% | 0.00% | 2/90 | 100/260 |

An occupied miss means zero detections in a frame labeled with at least one bird.
An empty false positive means at least one detection in a frame labeled empty.
These are sampled-frame count and occupancy metrics, not bounding-box precision
or recall, identity accuracy, behavior accuracy, or debounced runtime-state scores.
Machine-readable totals are in
[`archive-benchmark-summary.json`](archive-benchmark-summary.json); local per-clip
results are in the ignored `benchmark-results.json`.

YOLOv8n is the strongest exact-count candidate in this set. YOLO26n misses fewer
occupied frames but produces more empty-frame false positives. No model counts
the three multi-bird examples reliably. The production default remains YOLO11n;
this comparison identifies candidates for further validation rather than changing
production settings automatically.

## Limits and next evaluation

Neighboring frames are correlated, and the multi-bird group contains only three
clips. This is an initial regression set, not a representative season-wide test
or an independent holdout for tuning. Reviewer notes describe conditions but are
not structured identity or behavior labels. Mixed 1080p, 720p, and 480p downloads
were needed to recover invalid source-format extractions; all models used the
same local files. Reported inference timing is machine-specific.

The next evaluation should compare YOLOv8n and YOLO11n on additional independently
reviewed footage, inspect count errors on chick scenes, and measure arrival,
departure, and stable occupancy through the runtime state machine. Threshold or
ROI tuning should reserve separate source videos for holdout evaluation.

## Reproduce

```powershell
uv run python tools/fetch_test_clips.py fetch --manifest tests/fixtures/archive-labeled.json --continue-on-error
uv run python tools/benchmark_models.py --manifest tests/fixtures/archive-labeled.json
```

Retry invalid downloads with `--max-height 720` or `--max-height 480` as needed.
Valid existing clips remain skipped. Video files and model weights are local
artifacts and are not committed.
