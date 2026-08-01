import json
import pytest
import centrifugue_config as cc


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "get_config_path", lambda: tmp_path / "config.json")
    return tmp_path


def test_missing_config_returns_defaults():
    assert cc.load_config() == cc.DEFAULT_CONFIG


def test_malformed_config_falls_back_to_defaults(isolated_home):
    (isolated_home / "config.json").write_text("{not json")
    assert cc.load_config() == cc.DEFAULT_CONFIG


def test_partial_config_merges_over_defaults(isolated_home):
    (isolated_home / "config.json").write_text(json.dumps({"output_dir": "/tmp/x"}))
    cfg = cc.load_config()
    assert cfg["output_dir"] == "/tmp/x"
    assert cfg["naming"]["max_length"] == 80
    assert cfg["write_info_json"] is True


def test_output_dir_expands_tilde():
    out = cc.get_output_dir({"output_dir": "~/Music/Centrifugue"})
    assert str(out).startswith("/")
    assert "~" not in str(out)


def test_save_config_writes_and_returns_merged(isolated_home):
    result = cc.save_config({"output_dir": str(isolated_home)})
    assert result["output_dir"] == str(isolated_home)
    on_disk = json.loads((isolated_home / "config.json").read_text())
    assert on_disk["output_dir"] == str(isolated_home)


def test_save_config_rejects_non_writable_dir():
    with pytest.raises(ValueError, match="not writable|cannot"):
        cc.save_config({"output_dir": "/proc/nonexistent/nope"})


def test_save_config_rejects_non_string_output_dir():
    with pytest.raises(ValueError):
        cc.save_config({"output_dir": 42})
