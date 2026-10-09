import json
import subprocess
from unittest.mock import MagicMock

import pytest

from tools.fetch_test_clips import (
    _completed_output, _download_with_timeout, _ffmpeg_input_args, _validate_output,
    build_triage_manifest, download_manifest,
)
from yt_dlp.utils import DownloadError
from tools.review_triage import build_review, promote_labels, main as review_main
from tools.benchmark_models import load_expected_counts
from tools.triage_archive import analyze_clip, classify, main as triage_main


SOURCE = {"name": "sample", "url": "https://example.com/archive", "start": 10, "end": 20}
LABEL = {"name": "sample", "kind": "homogeneous", "expected_count": 1, "verified": True}


def test_windows_are_bounded_unlabeled_and_skip_invalid_durations():
    entries = [{"id": str(duration), "url": "https://example.com", "duration": duration}
               for duration in (5, 120, None, float("nan"), float("inf"))]
    windows = build_triage_manifest(entries)
    assert len(windows) == 3
    for window in windows:
        assert 0 <= window["start"] < window["end"] <= window["source_duration"]
        assert window["end"] - window["start"] <= 10
        assert "expected_count" not in window


def test_resume_ignores_sidecars_partial_and_unmerged_outputs(tmp_path):
    for name in ("sample.info.json", "sample.mp4.part", "sample.f137.mp4", "sample.mp4"):
        (tmp_path / name).touch()
    assert _completed_output(tmp_path, "sample") is None
    (tmp_path / "sample.mp4").write_bytes(b"video")
    assert _completed_output(tmp_path, "sample") == tmp_path / "sample.mp4"


def test_download_timeout_stops_worker_tree(monkeypatch):
    process = MagicMock()
    process.communicate.side_effect = subprocess.TimeoutExpired("worker", 1)
    monkeypatch.setattr("tools.fetch_test_clips.subprocess.Popen", lambda *a, **k: process)
    stop = MagicMock()
    monkeypatch.setattr("tools.fetch_test_clips._stop_download", stop)
    with pytest.raises(DownloadError, match="exceeded"):
        _download_with_timeout({}, "https://example.com", 1)
    stop.assert_called_once_with(process)


@pytest.mark.parametrize("help_text, enabled", [
    ("  -request_size <int64>\n  -short_seek_size <int>\n", True),
    ("  -short_seek_size <int>\n", False),
    ("  -initial_request_size <int64>\n  -short_seek_size <int>\n", False),
])
def test_http_range_options_require_ffmpeg_support(monkeypatch, help_text, enabled):
    monkeypatch.setattr("tools.fetch_test_clips.shutil.which", lambda _: "ffmpeg")
    monkeypatch.setattr("tools.fetch_test_clips.subprocess.run", lambda *a, **k:
                        subprocess.CompletedProcess([], 0, stdout=help_text, stderr=""))
    args = _ffmpeg_input_args()
    assert ("-request_size" in args) is enabled
    assert ("-short_seek_size" in args) is enabled
    assert "-rw_timeout" in args


def test_ffmpeg_capability_probe_timeout_keeps_base_options(monkeypatch):
    monkeypatch.setattr("tools.fetch_test_clips.shutil.which", lambda _: "ffmpeg")
    probe = MagicMock(side_effect=subprocess.TimeoutExpired("ffmpeg", 5))
    monkeypatch.setattr("tools.fetch_test_clips.subprocess.run", probe)
    assert "-request_size" not in _ffmpeg_input_args()


def test_failed_download_does_not_stop_batch(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([SOURCE, {**SOURCE, "name": "next"}]))
    download = MagicMock(side_effect=[DownloadError("timeout"), None])
    monkeypatch.setattr("tools.fetch_test_clips._download_with_timeout", download)
    download_manifest(manifest, tmp_path / "clips", continue_on_error=True)
    assert download.call_count == 2


@pytest.mark.parametrize("metadata", [
    {"format": {"duration": "0"}, "streams": [{"codec_type": "video"}]},
    {"format": {"duration": "2"}, "streams": [{"codec_type": "video"}]},
    {"format": {"duration": "10"}, "streams": [{"codec_type": "audio"}]},
    {"format": {"duration": "nan"}, "streams": [{"codec_type": "video"}]},
])
def test_output_validation_rejects_empty_short_and_nonvideo(monkeypatch, tmp_path, metadata):
    monkeypatch.setattr("tools.fetch_test_clips.subprocess.run", lambda *a, **k:
                        subprocess.CompletedProcess([], 0, stdout=json.dumps(metadata), stderr=""))
    with pytest.raises(DownloadError):
        _validate_output(tmp_path / "clip.mp4", 10)


def test_invalid_existing_output_is_replaced_and_validated(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([SOURCE]))
    output = tmp_path / "sample.mp4"
    output.write_bytes(b"invalid video")
    validate = MagicMock(side_effect=[DownloadError("empty output"), None])
    download = MagicMock()
    monkeypatch.setattr("tools.fetch_test_clips._validate_output", validate)
    monkeypatch.setattr("tools.fetch_test_clips._download_with_timeout", download)
    download_manifest(manifest, tmp_path, max_height=720)
    assert download.call_args.args[0]["overwrites"] is True
    assert download.call_args.args[0]["format"] == (
        "bestvideo[height<=720][vcodec^=avc1]/bestvideo[height<=720]/best[height<=720]")
    assert validate.call_count == 2


def test_valid_existing_output_is_skipped_after_validation(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([SOURCE]))
    (tmp_path / "sample.mp4").write_bytes(b"video")
    validate, download = MagicMock(), MagicMock()
    monkeypatch.setattr("tools.fetch_test_clips._validate_output", validate)
    monkeypatch.setattr("tools.fetch_test_clips._download_with_timeout", download)
    download_manifest(manifest, tmp_path)
    validate.assert_called_once_with(tmp_path / "sample.mp4", 10)
    download.assert_not_called()


def test_successful_worker_without_output_is_a_download_failure(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([SOURCE]))
    monkeypatch.setattr("tools.fetch_test_clips._download_with_timeout", MagicMock())
    with pytest.raises(DownloadError, match="no video output"):
        download_manifest(manifest, tmp_path)


def test_promotion_preserves_source_instead_of_label_supplied_url():
    result = promote_labels([SOURCE], [{**LABEL, "url": "https://wrong.example", "start": 99}])
    assert result[0]["url"] == SOURCE["url"]
    assert result[0]["start"] == SOURCE["start"]
    assert result[0]["label_source"] == "human"


@pytest.mark.parametrize("changes", [
    {"verified": False}, {"expected_count": True}, {"expected_count": -1},
    {"kind": "transition"}, {"name": "missing"}, {"expected_count": None},
])
def test_promotion_rejects_unverified_or_misleading_labels(changes):
    with pytest.raises(ValueError):
        promote_labels([SOURCE], [{**LABEL, **changes}])


def test_transition_remains_unlabeled():
    result = promote_labels([SOURCE], [{**LABEL, "kind": "transition", "expected_count": None}])
    assert result[0]["expected_count"] is None


def test_promotion_cli_merges_and_is_repeatable(tmp_path, monkeypatch):
    manifest, labels, output = (tmp_path / name for name in ("triage.json", "labels.json", "clips.json"))
    manifest.write_text(json.dumps([SOURCE]))
    labels.write_text(json.dumps([LABEL]))
    existing = {"name": "existing", "url": "https://example.com/other", "start": 0, "end": 10}
    output.write_text(json.dumps([existing]))
    monkeypatch.setattr("sys.argv", ["review_triage", "promote", "--manifest", str(manifest),
                                    "--labels", str(labels), "--output", str(output)])
    review_main()
    review_main()
    result = json.loads(output.read_text())
    assert len(result) == 2
    assert result[0] == existing
    assert result[1]["expected_count"] == 1
    assert result[1]["verified"] is True


def test_benchmark_excludes_disabled_and_transition_labels(tmp_path):
    path = tmp_path / "clips.json"
    path.write_text(json.dumps([
        {"name": "disabled", "expected_count": 2, "enabled": False},
        {"name": "transition", "expected_count": None},
        {"name": "empty", "expected_count": 0},
    ]))
    assert load_expected_counts(path) == {"empty": 0}


def test_review_escapes_untrusted_metadata_and_does_not_prefill_count(tmp_path):
    page = build_review([{"clip": "sample.mp4", "category": "<script>guess</script>",
                          "max_count": 2}], tmp_path)
    assert "&lt;script&gt;guess&lt;/script&gt;" in page
    assert 'value="2"' not in page
    assert (tmp_path / "sample.mp4").as_uri() in page
    with pytest.raises(ValueError):
        build_review([{"clip": "../escape.mp4"}], tmp_path)


def test_unavailable_clips_have_no_review_controls(tmp_path):
    page = build_review([{"clip": "missing.mp4", "category": "unreadable",
                          "error": "missing_clip"}], tmp_path)
    assert 'class="verified"' not in page
    assert "Unavailable for labeling: missing_clip" in page


def test_triage_categories_remain_search_suggestions():
    assert classify([], 0) == "unreadable"
    assert classify([0] * 10, 0) == "empty_candidate"
    assert classify([1] * 10, 0) == "one_bird_candidate"
    assert classify([1] * 10, 5) == "active_one_bird_candidate"
    assert classify([0, 1] * 5, 0) == "transition_or_hard_case"
    assert classify([0, 2, 0], 0) == "possible_multiple"


def test_analysis_releases_capture_on_inference_error(tmp_path, monkeypatch):
    capture = MagicMock()
    capture.get.return_value = 30
    capture.read.return_value = (True, object())
    monkeypatch.setattr("tools.triage_archive.cv2.VideoCapture", lambda _: capture)
    detector = MagicMock()
    detector.analyze.side_effect = RuntimeError("inference failed")
    with pytest.raises(RuntimeError, match="inference failed"):
        analyze_clip(tmp_path / "clip.mp4", detector, 1, tmp_path, None)
    capture.release.assert_called_once()


def test_missing_clips_are_reported_without_loading_model(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([SOURCE]))
    output = tmp_path / "results.json"
    detector = MagicMock()
    monkeypatch.setattr("tools.triage_archive.HawkDetector", lambda _: detector)
    monkeypatch.setattr("sys.argv", ["triage_archive", "--manifest", str(manifest),
                                    "--clips-dir", str(tmp_path / "missing"),
                                    "--output", str(output)])
    triage_main()
    detector.load.assert_not_called()
    results = json.loads(output.read_text())
    assert results[0]["error"] == "missing_clip"
    assert results[0]["source_url"] == SOURCE["url"]
    assert results[0]["human_label"] is None
