# Archived Hawk Cam triage

The discovered GDIT Hawk Cam archive contains many multi-hour livestreams with generic titles. Do not hand-label random timestamps blindly. Screech includes a bounded triage workflow that samples the archive, runs the current detector as a search aid, and produces annotated previews for human review.

## 1. Discover streams

```powershell
uv run python tools\fetch_test_clips.py discover
```

This writes `tests/fixtures/discovered.json`.

## 2. Build a bounded triage manifest

```powershell
uv run python tools\fetch_test_clips.py triage
```

Defaults:

- two evenly spaced windows per discovered stream
- ten seconds per window
- output: `tests/fixtures/triage.json`

With 20 discovered streams this is at most 40 clips / 400 seconds of footage.

You can change the coverage explicitly:

```powershell
uv run python tools\fetch_test_clips.py triage --samples-per-stream 3 --clip-seconds 12
```

The generated windows are deliberately unlabeled. YOLO output is not ground truth.

## 3. Download the triage windows

```powershell
uv run python tools\fetch_test_clips.py fetch `
  --manifest tests\fixtures\triage.json `
  --output-dir tests\fixtures\triage `
  --continue-on-error
```

Completed clips are skipped automatically when the command is re-run, so the batch is resumable. Use `--overwrite` only when you intentionally want to fetch an existing clip again.

## 4. Rank clips with the current detector

```powershell
uv run python tools\triage_archive.py
```

By default this uses Screech's configured production model and samples each local triage clip once per second. It writes:

- `tests/fixtures/triage-results.json` — ranked candidate report
- `tests/fixtures/triage-previews/` — one representative annotated image per clip

Candidate categories are heuristics for review:

- `possible_multiple` — at least one sampled frame reported 2+ birds; verify visually because duplicate boxes/false positives are possible
- `transition_or_hard_case` — intermittent detections; useful for arrivals, departures, occlusion, or detector misses
- `active_one_bird_candidate` — persistent one-bird detection with substantial movement signal
- `one_bird_candidate` — persistent one-bird detection
- `empty_candidate` — 10% or fewer sampled frames had a detection
- `unreadable` — local clip could not be opened

The report includes source video URL and source timestamps so useful clips can be promoted into the permanent labeled regression manifest.

## 5. Human-label useful clips

Review the annotated previews and the corresponding local clips. Promote representative cases into `tests/fixtures/clips.json` with `expected_count` only when the count is visually unambiguous.

Aim to collect:

- empty nest
- one hawk resting
- one hawk moving
- two birds
- arrival
- departure
- partial occlusion
- difficult lighting/weather
- detector false positives

Transition clips should normally omit `expected_count` because the count changes during the clip.

## 6. Re-run the detector benchmark

```powershell
uv run python tools\benchmark_models.py
```

Once `expected_count` labels exist, `exact_count_accuracy_pct` becomes a real ground-truth metric rather than just a smoke-test statistic.
