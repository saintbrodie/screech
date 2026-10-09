# Regression clip fixtures

Video files are intentionally not committed.

`archive-labeled.json` preserves the 40 human-reviewed ten-second archive windows
reviewed on October 9, 2026: 35 constant-count clips and five uncertain clips.
Counts include visible chicks as well as adults; notes are descriptive and do not
constitute identity or behavior ground truth. Uncertain clips have a null count.

To reproduce this dataset and benchmark:

```powershell
uv run python tools/fetch_test_clips.py fetch --manifest tests/fixtures/archive-labeled.json --continue-on-error
uv run python tools/benchmark_models.py --manifest tests/fixtures/archive-labeled.json
```

If a selected format produces invalid output, rerun the fetch with `--max-height
720`, then `--max-height 480` if needed; valid outputs remain skipped. The local
`clips.json` remains available for additional fixture selections.

1. Discover recent uploads from the GDIT Hawk Cam channel:

   ```bash
   python tools/fetch_test_clips.py discover
   ```

2. Review `tests/fixtures/discovered.json` and identify useful timestamps for:
   - empty nest
   - one hawk resting
   - one hawk moving/feeding
   - both hawks present
   - arrival/departure transitions
   - partial occlusion / difficult lighting

3. Copy `clips.example.json` to `clips.json` and add the selected URL/timestamp ranges.

4. Fetch the clips locally (requires `ffmpeg` for accurate section cutting):

   ```bash
   python tools/fetch_test_clips.py fetch
   ```

5. Run the detector over a clip:

   ```bash
   python tools/analyze_clip.py tests/fixtures/clips/example.mp4
   ```

Generated clips, annotated frames, discovery metadata, and result JSON are ignored by Git.
