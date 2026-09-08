# YouTube runtime setup

S.C.R.E.E.C.H. uses `yt-dlp` to resolve the Hawk Cam live stream and to build local regression clips from archived GDIT Hawk Cam uploads.

As of current yt-dlp releases, full YouTube support requires both:

1. the external JavaScript challenge scripts (`yt-dlp-ejs`), and
2. a supported JavaScript runtime.

Screech installs `yt-dlp[default]`, which includes the EJS package. The remaining system dependency is the JavaScript runtime.

## Recommended: Deno

Install a current Deno release (yt-dlp requires Deno 2.3 or newer) and make sure `deno` is on `PATH`.

Verify:

```powershell
deno --version
```

Deno is the simplest option for Screech because yt-dlp enables it by default. Without a supported JavaScript runtime, YouTube extraction may still work in a degraded mode, but format availability can be limited and future extraction may fail.

## ffmpeg

`ffmpeg` and `ffprobe` should also be available on `PATH` for merging YouTube formats and for precise timestamped fixture extraction.

Verify:

```powershell
ffmpeg -version
ffprobe -version
```

## Quick Screech check

After installing the project dependencies and Deno:

```powershell
uv run python tools\fetch_test_clips.py discover
```

A successful run should create `tests/fixtures/discovered.json` containing recent uploads from the public GDIT Hawk Cam channel.

Local fixture analysis (`SCREECH_VIDEO_SOURCE` pointing at a local video) does not require YouTube or Deno once the fixture already exists.
