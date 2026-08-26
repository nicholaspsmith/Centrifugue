"""Stem discovery, source selection, rename planning and tag arguments."""

import json

import pytest

import centrifugue_postprocess as postprocess


def _folder(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_bytes(b"\x00")
    return tmp_path


def test_find_stems_keys_by_stem_name(tmp_path):
    _folder(tmp_path, "vocals.flac", "drums.flac", "info.json")
    assert sorted(postprocess.find_stems(tmp_path)) == ["drums", "vocals"]


def test_find_stems_ignores_a_previous_suffix(tmp_path):
    # A re-analysed folder must still be recognised as vocals/drums.
    _folder(tmp_path, "vocals_124bpm_Fmin.flac", "drums_124bpm_Fmin.flac")
    assert sorted(postprocess.find_stems(tmp_path)) == ["drums", "vocals"]


def test_find_stems_skips_non_audio(tmp_path):
    _folder(tmp_path, "vocals.flac", "info.json", "cover.png", "set.als")
    assert list(postprocess.find_stems(tmp_path)) == ["vocals"]


def test_find_stems_on_a_missing_folder():
    assert postprocess.find_stems("/nonexistent/centrifugue") == {}


def test_pick_sources_prefers_isolated_drums():
    stems = {"vocals": "v", "drums": "d", "bass": "b", "other": "o"}
    bpm_source, key_sources = postprocess.pick_sources(stems)
    assert bpm_source == "d"
    # Drums are excluded from key detection: percussion smears the chroma.
    assert "d" not in key_sources
    assert key_sources == ["b", "o"]


def test_pick_sources_falls_back_to_beat_in_hiphop_mode():
    # Hiphop mode outputs vocals + beat only; there is no drums stem.
    bpm_source, key_sources = postprocess.pick_sources({"vocals": "v", "beat": "b"})
    assert bpm_source == "b"
    assert key_sources == ["b"]


def test_pick_sources_caps_key_inputs():
    stems = {"bass": "b", "other": "o", "instrumental": "i", "beat": "x"}
    _, key_sources = postprocess.pick_sources(stems)
    assert len(key_sources) == 2


def test_pick_sources_on_an_empty_folder():
    assert postprocess.pick_sources({}) == (None, [])


def test_ordered_stems_puts_a_rhythmic_stem_first():
    # The first track becomes the song tempo master in the Live Set.
    order = [n for n, _ in postprocess.ordered_stems(
        {"vocals": 1, "other": 2, "drums": 3})]
    assert order[0] == "drums"


def test_ordered_stems_keeps_unknown_stems(tmp_path):
    order = [n for n, _ in postprocess.ordered_stems({"vocals": 1, "strings": 2})]
    assert sorted(order) == ["strings", "vocals"]


def test_plan_renames_targets_every_stem(tmp_path):
    _folder(tmp_path, "vocals.flac", "drums.flac")
    planned = postprocess.plan_renames(
        [tmp_path / "vocals.flac", tmp_path / "drums.flac"], 124.0, "Fmin")
    assert sorted(p.name for p in planned.values()) == \
        ["drums_124bpm_Fmin.flac", "vocals_124bpm_Fmin.flac"]


def test_plan_renames_skips_files_already_named(tmp_path):
    _folder(tmp_path, "vocals_124bpm_Fmin.flac")
    planned = postprocess.plan_renames(
        [tmp_path / "vocals_124bpm_Fmin.flac"], 124.0, "Fmin")
    assert planned == {}


def test_plan_renames_refuses_to_clobber(tmp_path):
    # Renaming onto an existing file would destroy it; leave it alone.
    _folder(tmp_path, "vocals.flac", "vocals_124bpm_Fmin.flac")
    planned = postprocess.plan_renames([tmp_path / "vocals.flac"], 124.0, "Fmin")
    assert planned == {}


def test_plan_renames_with_no_analysis_is_a_no_op(tmp_path):
    _folder(tmp_path, "vocals.flac")
    assert postprocess.plan_renames([tmp_path / "vocals.flac"], None, None) == {}


def test_apply_renames_moves_the_asd_sidecar(tmp_path):
    # An .asd is bound to its audio file by name; leaving it behind orphans
    # Live's existing analysis.
    _folder(tmp_path, "vocals.flac", "vocals.flac.asd")
    planned = postprocess.plan_renames([tmp_path / "vocals.flac"], 124.0, "Fmin")
    postprocess.apply_renames(planned)
    assert (tmp_path / "vocals_124bpm_Fmin.flac").exists()
    assert (tmp_path / "vocals_124bpm_Fmin.flac.asd").exists()
    assert not (tmp_path / "vocals.flac.asd").exists()


def test_mp3_tags_use_id3_frame_names():
    args = postprocess._tag_arguments(".mp3", 124.0, "Fmin", "4A")
    assert "TBPM=124" in args and "TKEY=Fmin" in args


def test_flac_tags_use_vorbis_comments():
    args = postprocess._tag_arguments(".flac", 124.0, "Fmin", "4A")
    assert "BPM=124" in args and "INITIALKEY=Fmin" in args
    assert not any(a.startswith("TBPM") for a in args)


def test_tag_arguments_empty_without_a_result():
    assert postprocess._tag_arguments(".flac", None, None, None) == []


def test_update_info_adds_an_analysis_block(tmp_path):
    (tmp_path / "info.json").write_text(json.dumps({"schema_version": 1}))
    assert postprocess.update_info(tmp_path, {"bpm": 124.0, "key": "Fmin"})
    written = json.loads((tmp_path / "info.json").read_text())
    assert written["analysis"]["bpm"] == 124.0
    assert written["schema_version"] == 1


def test_update_info_tolerates_a_missing_or_broken_file(tmp_path):
    assert postprocess.update_info(tmp_path, {"bpm": 1}) is False
    (tmp_path / "info.json").write_text("not json")
    assert postprocess.update_info(tmp_path, {"bpm": 1}) is False


def test_run_analysis_survives_a_missing_interpreter():
    assert postprocess.run_analysis("/nonexistent/python", "a.flac", []) is None


def _stub_duration(monkeypatch, seconds=180.0):
    monkeypatch.setattr(postprocess, "probe_duration", lambda *a, **k: seconds)


def test_write_live_clips_writes_one_per_stem(tmp_path, monkeypatch):
    _stub_duration(monkeypatch)
    _folder(tmp_path, "vocals.flac", "drums.flac")
    written = postprocess.write_live_clips(
        tmp_path, postprocess.find_stems(tmp_path), 124.0, key="Fmin")
    assert sorted(written) == ["drums.alc", "vocals.alc"]
    assert (tmp_path / "drums.alc").exists()


def test_live_clips_of_one_render_share_their_warp(tmp_path, monkeypatch):
    # Stems drifting apart in Live was the bug; identical markers is the fix.
    import gzip
    import re

    _stub_duration(monkeypatch)
    _folder(tmp_path, "vocals.flac", "drums.flac")
    postprocess.write_live_clips(
        tmp_path, postprocess.find_stems(tmp_path), 124.0)

    def markers(name):
        xml = gzip.open(tmp_path / f"{name}.alc").read().decode()
        return re.findall(r'SecTime="([^"]*)" BeatTime="([^"]*)"', xml)

    assert markers("drums") == markers("vocals")


def test_live_clips_reference_the_final_folder(tmp_path, monkeypatch):
    # A fresh render is assembled in a staging directory and only then
    # renamed into place, so an absolute path to the staging directory
    # would be dead by the time anyone drags the clip in.
    import gzip

    _stub_duration(monkeypatch)
    staging = tmp_path / ".staging"
    staging.mkdir()
    _folder(staging, "drums.flac")
    final = tmp_path / "song"

    postprocess.write_live_clips(
        staging, postprocess.find_stems(staging), 124.0, final_folder=final)
    xml = gzip.open(staging / "drums.alc").read().decode()
    assert str(final / "drums.flac") in xml
    assert str(staging / "drums.flac") not in xml


def test_write_live_clips_on_an_empty_folder(tmp_path):
    assert postprocess.write_live_clips(tmp_path, {}, 124.0) == []
