import pytest
from centrifugue_naming import slugify


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
