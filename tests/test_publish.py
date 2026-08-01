import pytest
from centrifugue_naming import publish_folder


def test_publishes_temp_dir_to_target(tmp_path):
    temp = tmp_path / ".song.tmp"
    temp.mkdir()
    (temp / "vocals.flac").write_text("audio")
    target = tmp_path / "song"

    publish_folder(temp, target, overwrite=False)

    assert target.is_dir()
    assert (target / "vocals.flac").read_text() == "audio"
    assert not temp.exists()


def test_overwrite_replaces_existing_contents(tmp_path):
    target = tmp_path / "song"
    target.mkdir()
    (target / "stale.flac").write_text("old")

    temp = tmp_path / ".song.tmp"
    temp.mkdir()
    (temp / "vocals.flac").write_text("new")

    publish_folder(temp, target, overwrite=True)

    assert (target / "vocals.flac").read_text() == "new"
    assert not (target / "stale.flac").exists()


def test_refuses_to_overwrite_when_not_requested(tmp_path):
    target = tmp_path / "song"
    target.mkdir()
    temp = tmp_path / ".song.tmp"
    temp.mkdir()

    with pytest.raises(FileExistsError):
        publish_folder(temp, target, overwrite=False)


def test_leaves_no_temp_dir_behind_on_success(tmp_path):
    temp = tmp_path / ".song.tmp"
    temp.mkdir()
    publish_folder(temp, tmp_path / "song", overwrite=False)
    assert list(tmp_path.glob(".*.tmp")) == []
