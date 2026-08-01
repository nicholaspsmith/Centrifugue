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
