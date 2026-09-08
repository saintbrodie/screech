# Regression clip fixtures

Video files are intentionally not committed.

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
