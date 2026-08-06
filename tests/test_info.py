from centrifugue_info import build_info, probe_environment, SCHEMA_VERSION

SONG = {"title": "RockHard - Foolio", "slug": "rockhard_foolio",
        "url": "https://y.t/x", "video_id": "x", "duration_seconds": 256.14}
AUDIO = {"format": "flac", "codec": "flac", "sample_rate": 44100,
         "channels": 2, "bit_depth": 16}
FILES = [{"stem": "vocals", "filename": "vocals.flac", "bytes": 1}]
TIMING = {"started_at": "2026-08-01T17:04:03Z",
          "completed_at": "2026-08-01T17:09:14Z",
          "download_seconds": 12.4, "separation_seconds": 289.7,
          "total_seconds": 311.2}


def test_includes_schema_version():
    info = build_info(SONG, None, AUDIO, FILES, TIMING, environment={})
    assert info["schema_version"] == SCHEMA_VERSION


def test_top_level_keys_always_present():
    info = build_info(SONG, None, AUDIO, FILES, TIMING, environment={})
    for key in ("song", "separation", "audio", "files", "timing", "environment"):
        assert key in info


def test_separation_is_null_when_absent():
    info = build_info(SONG, None, AUDIO, FILES, TIMING, environment={})
    assert info["separation"] is None


def test_song_title_is_preserved_verbatim():
    info = build_info(SONG, None, AUDIO, FILES, TIMING, environment={})
    assert info["song"]["title"] == "RockHard - Foolio"
    assert info["song"]["slug"] == "rockhard_foolio"


def test_missing_song_fields_become_null_not_absent():
    info = build_info({"title": "t"}, None, AUDIO, FILES, TIMING, environment={})
    assert info["song"]["video_id"] is None
    assert info["song"]["duration_seconds"] is None


def test_missing_audio_fields_become_null():
    info = build_info(SONG, None, {"format": "mp3"}, FILES, TIMING, environment={})
    assert info["audio"]["bit_depth"] is None
    assert info["audio"]["sample_rate"] is None


def test_serializes_to_json():
    import json
    json.dumps(build_info(SONG, None, AUDIO, FILES, TIMING, environment={}))


def test_probe_environment_never_raises_and_has_expected_keys():
    env = probe_environment()
    for key in ("centrifugue_version", "python", "platform", "device",
                "demucs", "audio_separator", "torch", "yt_dlp"):
        assert key in env


# --- Regression: versions must come from the venv, not the host ------------
# The host runs under the system python (3.9.6 via /usr/bin/python3 when
# spawned by the browser), which cannot import torch or demucs at all, so
# device/demucs/torch/audio_separator all recorded as null.

def test_parse_venv_probe_reads_versions():
    from centrifugue_info import parse_venv_probe
    out = parse_venv_probe('{"demucs":"4.1.0","torch":"2.13.0",'
                           '"audio-separator":"0.28.5","device":"mps"}')
    assert out["demucs"] == "4.1.0"
    assert out["torch"] == "2.13.0"
    assert out["audio_separator"] == "0.28.5"
    assert out["device"] == "mps"


def test_parse_venv_probe_tolerates_garbage():
    from centrifugue_info import parse_venv_probe
    assert parse_venv_probe("not json") == {}
    assert parse_venv_probe("") == {}


def test_probe_environment_merges_venv_values(monkeypatch):
    import centrifugue_info as ci
    monkeypatch.setattr(ci, "_run_venv_probe",
                        lambda p: {"demucs": "4.1.0", "device": "mps"})
    env = ci.probe_environment(venv_python="/fake/python")
    assert env["demucs"] == "4.1.0"
    assert env["device"] == "mps"
    # host-side values still present
    assert env["python"] and env["platform"]


def test_probe_environment_without_venv_still_has_every_key():
    from centrifugue_info import probe_environment
    env = probe_environment()
    for key in ("centrifugue_version", "python", "platform", "device",
                "demucs", "audio_separator", "torch", "yt_dlp"):
        assert key in env


def test_a_broken_venv_path_never_raises():
    # A missing venv must degrade to the host-side values, not blow up.
    # (The suite itself runs inside the venv, so those may be populated.)
    from centrifugue_info import probe_environment
    env = probe_environment(venv_python="/nope/does/not/exist")
    for key in ("device", "demucs", "audio_separator", "torch"):
        assert key in env
