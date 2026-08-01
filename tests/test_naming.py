import pytest
from centrifugue_naming import slugify, resolve_output_folder


@pytest.mark.parametrize("title,expected", [
    ("RockHard - Foolio", "rockhard_foolio"),
    ("Café Tacvba — Éres (Official)", "cafe_tacvba_eres_official"),
    (
        "Linkin ParkLimp BizkitSlipknot Style-FFO; "
        "Aggressive NU Metal- encore - Isokuici",
        "linkin_parklimp_bizkitslipknot_style-ffo_aggressive_nu_metal_encore_isokuici",
    ),
])
def test_slugify_examples(title, expected):
    assert slugify(title) == expected


def test_internal_hyphen_survives_but_separator_hyphen_does_not():
    assert slugify("Style-FFO - Live") == "style-ffo_live"


def test_non_latin_title_falls_back_to_video_id():
    assert slugify("米津玄師 - アイドル", video_id="AMxCPVRUKQo") == "video_AMxCPVRUKQo"


def test_non_latin_title_without_video_id_falls_back_to_untitled():
    assert slugify("米津玄師") == "untitled"


def test_only_punctuation_falls_back():
    assert slugify("!!! ??? ***") == "untitled"


def test_only_spaces_falls_back():
    assert slugify("     ") == "untitled"


def test_empty_and_none_fall_back():
    assert slugify("") == "untitled"
    assert slugify(None) == "untitled"


def test_truncation_respects_max_length_and_never_ends_in_separator():
    out = slugify("a" * 50 + " " + "b" * 50, max_length=51)
    assert len(out) <= 51
    assert not out.endswith(("_", "-"))


def test_collapses_repeated_separators():
    assert slugify("a   ---   b") == "a_b"


def _info(genre, quality):
    return {"separation": {"genre_mode": genre, "quality_preset": quality}}


def test_fresh_slug_uses_base_folder(tmp_path):
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra", read_info=lambda p: None)
    assert target == tmp_path / "song"
    assert overwrite is False


def test_matching_settings_overwrites_in_place(tmp_path):
    (tmp_path / "song").mkdir()
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra",
        read_info=lambda p: _info("rock", "ultra"))
    assert target == tmp_path / "song"
    assert overwrite is True


def test_different_settings_get_variant_folder(tmp_path):
    (tmp_path / "song").mkdir()
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra",
        read_info=lambda p: _info("full", "fast"))
    assert target == tmp_path / "song_rock_ultra"
    assert overwrite is False


def test_folder_without_info_json_is_never_overwritten(tmp_path):
    (tmp_path / "song").mkdir()
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra", read_info=lambda p: None)
    assert target == tmp_path / "song_rock_ultra"
    assert overwrite is False


def test_variant_collision_appends_counter(tmp_path):
    (tmp_path / "song").mkdir()
    (tmp_path / "song_rock_ultra").mkdir()
    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra",
        read_info=lambda p: _info("full", "fast"))
    assert target == tmp_path / "song_rock_ultra_2"
    assert overwrite is False


def test_variant_with_matching_settings_overwrites(tmp_path):
    (tmp_path / "song").mkdir()
    (tmp_path / "song_rock_ultra").mkdir()

    def reader(p):
        return _info("full", "fast") if p.name == "song" else _info("rock", "ultra")

    target, overwrite = resolve_output_folder(
        tmp_path, "song", "rock", "ultra", read_info=reader)
    assert target == tmp_path / "song_rock_ultra"
    assert overwrite is True
