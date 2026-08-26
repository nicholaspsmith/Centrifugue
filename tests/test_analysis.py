"""Pure helpers from centrifugue_analysis: no audio, no librosa, no venv."""

import pytest

from centrifugue_analysis import (analysis_suffix, apply_analysis_suffix,
                                  camelot, fold_tempo, format_bpm, format_key,
                                  strip_analysis_suffix)


def test_format_key_uses_sharps():
    assert format_key(0, "major") == "Cmaj"
    assert format_key(5, "minor") == "Fmin"
    assert format_key(6, "major") == "F#maj"


def test_format_key_wraps_pitch_class():
    assert format_key(12, "major") == "Cmaj"
    assert format_key(-1, "minor") == "Bmin"


def test_format_key_rejects_unknown_mode():
    assert format_key(0, "dorian") is None
    assert format_key(None, "major") is None


def test_camelot_relative_keys_share_a_number():
    # A minor and C major are relatives, so 8A and 8B on the wheel.
    assert camelot(9, "minor") == "8A"
    assert camelot(0, "major") == "8B"


def test_fold_tempo_brings_extremes_into_range():
    assert fold_tempo(62) == 124.0
    assert fold_tempo(240) == 120.0
    assert fold_tempo(124) == 124.0


def test_fold_tempo_leaves_in_range_values_alone():
    # 75 is a legitimate hiphop tempo and must not be doubled to 150.
    assert fold_tempo(75) == 75.0
    assert fold_tempo(179) == 179.0


def test_fold_tempo_rejects_nonsense():
    assert fold_tempo(None) is None
    assert fold_tempo(0) is None
    assert fold_tempo(-5) is None
    assert fold_tempo("fast") is None


def test_fold_tempo_survives_an_impossible_range():
    assert fold_tempo(120, low=200, high=100) == 120.0


def test_format_bpm_drops_a_trailing_zero():
    assert format_bpm(124.0) == "124"
    assert format_bpm(123.5) == "123.5"
    assert format_bpm(124.02) == "124"
    assert format_bpm(None) is None


def test_analysis_suffix_handles_partial_results():
    assert analysis_suffix(124.0, "Fmin") == "_124bpm_Fmin"
    assert analysis_suffix(124.0, None) == "_124bpm"
    assert analysis_suffix(None, "Fmin") == "_Fmin"
    assert analysis_suffix(None, None) == ""


def test_apply_analysis_suffix_inserts_before_extension():
    assert apply_analysis_suffix("vocals.flac", 124.0, "Fmin") == \
        "vocals_124bpm_Fmin.flac"


def test_apply_analysis_suffix_is_idempotent():
    once = apply_analysis_suffix("vocals.flac", 124.0, "Fmin")
    assert apply_analysis_suffix(once, 124.0, "Fmin") == once


def test_apply_analysis_suffix_replaces_a_stale_result():
    # Re-analysing with a different answer must not stack suffixes.
    once = apply_analysis_suffix("vocals.flac", 124.0, "Fmin")
    assert apply_analysis_suffix(once, 90.0, "Amaj") == "vocals_90bpm_Amaj.flac"


def test_strip_analysis_suffix_leaves_untouched_names():
    assert strip_analysis_suffix("vocals.flac") == "vocals.flac"
    assert strip_analysis_suffix("other_mixed.flac") == "other_mixed.flac"


def test_strip_analysis_suffix_removes_a_camelot_tail():
    assert strip_analysis_suffix("vocals_124bpm_Fmin_4A.flac") == "vocals.flac"


def test_suffix_survives_a_sharp_key():
    assert apply_analysis_suffix("drums.flac", 140.0, "F#min") == \
        "drums_140bpm_F#min.flac"
    assert strip_analysis_suffix("drums_140bpm_F#min.flac") == "drums.flac"


@pytest.mark.parametrize("name", ["vocals", "vocals.", ".hidden"])
def test_apply_analysis_suffix_tolerates_odd_names(name):
    assert apply_analysis_suffix(name, 124.0, "Fmin").startswith(
        name.rstrip(".") if name != ".hidden" else ".hidden")


def test_filename_bpm_is_a_whole_number():
    # Detected tempos are rarely integral; the filename still reads as one.
    from centrifugue_analysis import format_bpm_integer
    assert format_bpm_integer(101.33) == "101"
    assert format_bpm_integer(123.6) == "124"
    assert format_bpm_integer(None) is None
    assert format_bpm_integer(0) is None


def test_suffix_rounds_a_fractional_tempo():
    assert apply_analysis_suffix("beat.flac", 101.33, "Emin") == \
        "beat_101bpm_Emin.flac"


def test_stripping_removes_a_legacy_fractional_suffix():
    # Folders analysed before the rounding change carry a decimal tail.
    assert strip_analysis_suffix("beat_101.3bpm_Emin.flac") == "beat.flac"
